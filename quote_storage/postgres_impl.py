"""PostgreSQL 报价持久化（与 SQLite 侧字段与接口一致）。

环境变量：
- QUOTE_DATABASE_URL：连接串，如 postgresql://user:pass@127.0.0.1:5432/quotes

上传文件仍落在项目 data/uploads 下（与 SQLite 模式相同）。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from quote_storage.db_common import sanitize_original_name, summarize_quote_result, utc_now_iso

_PG_LOCK = threading.Lock()


def _db_url() -> str:
    url = os.environ.get("QUOTE_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("QUOTE_DATABASE_URL 未设置（PostgreSQL 模式必填）")
    return url


def _connect_ctx():
    import psycopg

    return psycopg.connect(_db_url())


def _root() -> Path:
    import quote_upload_storage as qus

    return qus.ROOT


_DDL_FRAGMENTS = [
    """
    CREATE TABLE IF NOT EXISTS quote_files (
        file_id TEXT PRIMARY KEY,
        quote_id TEXT NOT NULL,
        quote_uid TEXT,
        calc_quote_id TEXT,
        version_no INTEGER NOT NULL DEFAULT 1,
        original_name TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        mime_type TEXT,
        file_size INTEGER NOT NULL,
        file_hash_sha256 TEXT NOT NULL,
        uploaded_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_quote_files_quote_id ON quote_files(quote_id)",
    "CREATE INDEX IF NOT EXISTS idx_quote_files_quote_uid ON quote_files(quote_uid)",
    """
    CREATE TABLE IF NOT EXISTS quotes (
        quote_uid TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        latest_saved_at TEXT NOT NULL,
        product_name TEXT,
        sheet_original_name TEXT,
        latest_version_no INTEGER NOT NULL DEFAULT 0,
        latest_calc_quote_id TEXT,
        material_total DOUBLE PRECISION,
        tier1_cost_before_margin DOUBLE PRECISION,
        approval_status TEXT NOT NULL DEFAULT 'pending',
        approved_version_no INTEGER,
        approved_calc_quote_id TEXT,
        approved_at TEXT,
        approved_by TEXT,
        approval_note TEXT
    )
    """,
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'pending'",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS approved_version_no INTEGER",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS approved_calc_quote_id TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS approved_at TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS approved_by TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS approval_note TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_correction_note TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_correction_problem_types TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_correction_file_id TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_correction_at TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_correction_by TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_feedback_at TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_feedback_by TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_calculated_file_id TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_calculated_at TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_calculated_by TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_update_status TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_update_at TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_update_viewed_at TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS admin_update_handled_at TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS sales_hidden_at TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS sales_user_id TEXT",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS sales_user_name TEXT",
    "CREATE INDEX IF NOT EXISTS idx_quotes_sales_user ON quotes(sales_user_id, updated_at DESC)",
    "UPDATE quote_files SET file_role = 'admin_corrected' WHERE file_role = 'admin_correction'",
    "ALTER TABLE quote_files ADD COLUMN IF NOT EXISTS file_role TEXT DEFAULT 'sales_sheet'",
    "ALTER TABLE quote_files ADD COLUMN IF NOT EXISTS uploaded_by TEXT",
    "CREATE INDEX IF NOT EXISTS idx_quotes_updated_at ON quotes(updated_at)",
    """
    CREATE TABLE IF NOT EXISTS quote_customer_profiles (
        sales_user_id TEXT NOT NULL,
        customer_key TEXT NOT NULL,
        cust_name TEXT,
        cust_contact TEXT,
        cust_phone TEXT,
        cust_addr TEXT,
        seller_email TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (sales_user_id, customer_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quote_versions (
        id SERIAL PRIMARY KEY,
        quote_uid TEXT NOT NULL REFERENCES quotes(quote_uid) ON DELETE CASCADE,
        version_no INTEGER NOT NULL,
        calc_quote_id TEXT NOT NULL UNIQUE,
        saved_at TEXT NOT NULL,
        intent TEXT,
        quote_json TEXT NOT NULL,
        UNIQUE (quote_uid, version_no)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_quote_versions_uid ON quote_versions(quote_uid)",
    """
    CREATE TABLE IF NOT EXISTS quote_items (
        id SERIAL PRIMARY KEY,
        quote_uid TEXT NOT NULL REFERENCES quotes(quote_uid) ON DELETE CASCADE,
        version_no INTEGER NOT NULL,
        line_no INTEGER NOT NULL,
        name TEXT,
        spec TEXT,
        usage TEXT,
        unit_price TEXT,
        amount DOUBLE PRECISION,
        amount_text TEXT,
        source TEXT,
        calc_note TEXT,
        kb_hit INTEGER NOT NULL DEFAULT 0,
        UNIQUE (quote_uid, version_no, line_no)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_quote_items_uid_ver ON quote_items(quote_uid, version_no)",
    """
    CREATE TABLE IF NOT EXISTS saved_quotes (
        quote_id TEXT PRIMARY KEY,
        saved_at TEXT NOT NULL,
        product_name TEXT,
        sheet_original_name TEXT,
        material_total DOUBLE PRECISION,
        tier1_cost_before_margin DOUBLE PRECISION,
        quote_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quote_chat_messages (
        message_id TEXT PRIMARY KEY,
        quote_series_uid TEXT NOT NULL REFERENCES quotes(quote_uid) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        metadata_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_qcm_series_time ON quote_chat_messages(quote_series_uid, created_at)",
]


def init_quote_storage() -> None:
    import quote_upload_storage as qus

    qus.DATA_DIR.mkdir(parents=True, exist_ok=True)
    qus.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    with _PG_LOCK:
        with _connect_ctx() as conn:
            for frag in _DDL_FRAGMENTS:
                conn.execute(frag)
            _migrate_legacy_saved_quotes(conn)
            conn.commit()


def _migrate_legacy_saved_quotes(conn: Any) -> None:
    import psycopg.errors

    row = conn.execute("SELECT COUNT(*)::bigint FROM quotes").fetchone()
    if row and int(row[0] or 0) > 0:
        return
    try:
        sc = conn.execute("SELECT * FROM saved_quotes ORDER BY saved_at ASC")
    except psycopg.errors.UndefinedTable:
        return
    colnames = [d.name for d in sc.description]
    rows = sc.fetchall()
    if not rows:
        return
    for tup in rows:
        rd = dict(zip(colnames, tup))
        uid = str(rd.get("quote_id") or "").strip()
        if not uid:
            continue
        saved_at = str(rd.get("saved_at") or utc_now_iso())
        pn = str(rd.get("product_name") or "")
        sheet_nm = str(rd.get("sheet_original_name") or "")
        try:
            mt = float(rd.get("material_total") or 0.0)
        except (TypeError, ValueError):
            mt = 0.0
        tier1 = rd.get("tier1_cost_before_margin")
        raw_json = rd.get("quote_json") or "{}"
        conn.execute(
            """
            INSERT INTO quotes (
                quote_uid, created_at, updated_at, latest_saved_at,
                product_name, sheet_original_name, latest_version_no,
                latest_calc_quote_id, material_total, tier1_cost_before_margin
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (quote_uid) DO NOTHING
            """,
            (uid, saved_at, saved_at, saved_at, pn, sheet_nm, 1, uid, mt, tier1),
        )
        conn.execute(
            """
            INSERT INTO quote_versions (
                quote_uid, version_no, calc_quote_id, saved_at, intent, quote_json
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (calc_quote_id) DO NOTHING
            """,
            (uid, 1, uid, saved_at, None, raw_json),
        )
        try:
            obj = json.loads(raw_json)
            dr = obj.get("detail_rows") if isinstance(obj, dict) else None
            if isinstance(dr, list):
                _insert_quote_items(conn, uid, 1, dr)
        except json.JSONDecodeError:
            pass


def _insert_quote_items(conn: Any, quote_uid: str, version_no: int, detail_rows: list[Any]) -> None:
    conn.execute("DELETE FROM quote_items WHERE quote_uid = %s AND version_no = %s", (quote_uid, version_no))
    line_no = 0
    for raw in detail_rows:
        if not isinstance(raw, dict):
            continue
        line_no += 1
        try:
            amt = float(raw.get("amount") or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        kb_hit = 1 if raw.get("kb_hit") else 0
        conn.execute(
            """
            INSERT INTO quote_items (
                quote_uid, version_no, line_no, name, spec, usage,
                unit_price, amount, amount_text, source, calc_note, kb_hit
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                quote_uid,
                version_no,
                line_no,
                str(raw.get("name") or ""),
                str(raw.get("spec") or ""),
                str(raw.get("usage") or ""),
                str(raw.get("unit_price") or ""),
                amt,
                str(raw.get("amount_text") or ""),
                str(raw.get("source") or ""),
                str(raw.get("calc_note") or ""),
                kb_hit,
            ),
        )


def _next_file_version(conn: Any, quote_uid: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_no), 0) + 1 FROM quote_files WHERE quote_uid = %s OR quote_id = %s",
        (quote_uid, quote_uid),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 1


def _fetch_quote_files_rows(q_uid: str) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT file_id, quote_id, quote_uid, calc_quote_id, version_no,
                           original_name, stored_path, mime_type, file_size,
                           file_hash_sha256, uploaded_at, file_role, uploaded_by
                    FROM quote_files
                    WHERE quote_uid = %s OR quote_id = %s
                    ORDER BY version_no ASC, uploaded_at ASC
                    """,
                    (q_uid, q_uid),
                )
                return list(cur.fetchall())


def persist_uploaded_sheet_for_quote(
    quote_uid: str,
    uploaded_sheet: dict[str, Any],
    *,
    calc_quote_id: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(uploaded_sheet, dict):
        return None
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return None
    b64 = str(uploaded_sheet.get("content_base64") or "").strip()
    if not b64:
        return None
    original_name = sanitize_original_name(str(uploaded_sheet.get("name") or ""))
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None

    init_quote_storage()
    file_id = uuid.uuid4().hex
    ext = Path(original_name).suffix if len(Path(original_name).suffix) <= 12 else ""
    stored_rel = Path("data") / "uploads" / f"{file_id}{ext}"
    abs_path = _root() / stored_rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(raw)

    digest = hashlib.sha256(raw).hexdigest()
    mime_guess = mimetypes.guess_type(original_name)[0]
    mime_type = mime_guess or "application/octet-stream"
    uploaded_at = utc_now_iso()
    calc_q = str(calc_quote_id or "").strip() or None

    with _PG_LOCK:
        with _connect_ctx() as conn:
            ver = _next_file_version(conn, q_uid)
            conn.execute(
                """
                INSERT INTO quote_files (
                    file_id, quote_id, quote_uid, calc_quote_id, version_no,
                    original_name, stored_path, mime_type, file_size,
                    file_hash_sha256, uploaded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    file_id,
                    q_uid,
                    q_uid,
                    calc_q,
                    ver,
                    original_name,
                    stored_rel.as_posix(),
                    mime_type,
                    len(raw),
                    digest,
                    uploaded_at,
                ),
            )
            conn.commit()

    return {
        "file_id": file_id,
        "quote_id": q_uid,
        "quote_uid": q_uid,
        "calc_quote_id": calc_q,
        "version_no": ver,
        "original_name": original_name,
        "stored_path": stored_rel.as_posix(),
        "mime_type": mime_type,
        "file_size": len(raw),
        "file_hash_sha256": digest,
        "uploaded_at": uploaded_at,
    }


def list_quote_files_for_quote(quote_uid: str) -> list[dict[str, Any]]:
    init_quote_storage()
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return []
    return _fetch_quote_files_rows(q_uid)


def get_quote_file_record(file_id: str) -> dict[str, Any] | None:
    from psycopg.rows import dict_row

    init_quote_storage()
    fid = str(file_id or "").strip()
    if not fid:
        return None
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT file_id, quote_id, quote_uid, calc_quote_id, version_no,
                           original_name, stored_path, mime_type, file_size,
                           file_hash_sha256, uploaded_at, file_role, uploaded_by
                    FROM quote_files WHERE file_id = %s
                    """,
                    (fid,),
                )
                row = cur.fetchone()
    return dict(row) if row else None


def save_quote_calculation(
    *,
    quote_uid: str,
    calc_quote_id: str,
    sheet_original_display_name: str,
    uploaded_sheet: dict[str, Any] | None,
    quote_result: dict[str, Any],
    sales_user_id: str | None = None,
    sales_user_name: str | None = None,
) -> None:
    q_uid = str(quote_uid or "").strip()
    calc_id = str(calc_quote_id or "").strip()
    if not q_uid or not calc_id or not isinstance(quote_result, dict):
        return
    sid = str(sales_user_id or "").strip()
    sname = str(sales_user_name or "").strip()

    init_quote_storage()

    if isinstance(uploaded_sheet, dict) and str(uploaded_sheet.get("content_base64") or "").strip():
        try:
            persist_uploaded_sheet_for_quote(q_uid, uploaded_sheet, calc_quote_id=calc_id)
        except Exception:
            pass

    pn, _, mt, tier1_cbm = summarize_quote_result(quote_result)
    sheet_nm = str(sheet_original_display_name or "").strip()
    intent = quote_result.get("intent")
    intent_str = str(intent) if intent is not None else None

    try:
        from quote_sheet_meta import carry_forward_quote_sheet_meta

        carry_forward_quote_sheet_meta(q_uid, quote_result)
    except Exception:
        pass

    try:
        payload_json = json.dumps(quote_result, ensure_ascii=False, default=str)
    except TypeError:
        payload_json = "{}"

    saved_at = utc_now_iso()
    detail_rows = quote_result.get("detail_rows")
    if not isinstance(detail_rows, list):
        detail_rows = []

    import psycopg.errors

    with _PG_LOCK:
        with _connect_ctx() as conn:
            try:
                cur_mx = conn.execute(
                    "SELECT COALESCE(MAX(version_no), 0) FROM quote_versions WHERE quote_uid = %s",
                    (q_uid,),
                ).fetchone()
                next_ver = int(cur_mx[0] or 0) + 1

                exists = conn.execute("SELECT 1 FROM quotes WHERE quote_uid = %s", (q_uid,)).fetchone()
                if not exists:
                    conn.execute(
                        """
                        INSERT INTO quotes (
                            quote_uid, created_at, updated_at, latest_saved_at,
                            product_name, sheet_original_name, latest_version_no,
                            latest_calc_quote_id, material_total, tier1_cost_before_margin,
                            approval_status, sales_user_id, sales_user_name
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            q_uid,
                            saved_at,
                            saved_at,
                            saved_at,
                            pn,
                            sheet_nm,
                            next_ver,
                            calc_id,
                            mt,
                            tier1_cbm,
                            "pending",
                            sid or None,
                            sname or None,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE quotes SET
                            updated_at = %s,
                            latest_saved_at = %s,
                            latest_version_no = %s,
                            latest_calc_quote_id = %s,
                            product_name = %s,
                            sheet_original_name = CASE
                                WHEN %s <> '' THEN %s
                                ELSE sheet_original_name
                            END,
                            material_total = %s,
                            tier1_cost_before_margin = %s,
                            approval_status = 'pending',
                            approved_version_no = NULL,
                            approved_calc_quote_id = NULL,
                            approved_at = NULL,
                            approved_by = NULL,
                            approval_note = NULL,
                            sales_user_id = CASE
                                WHEN (sales_user_id IS NULL OR sales_user_id = '') AND %s <> ''
                                THEN %s
                                ELSE sales_user_id
                            END,
                            sales_user_name = CASE
                                WHEN (sales_user_name IS NULL OR sales_user_name = '') AND %s <> ''
                                THEN %s
                                ELSE sales_user_name
                            END
                        WHERE quote_uid = %s
                        """,
                        (
                            saved_at,
                            saved_at,
                            next_ver,
                            calc_id,
                            pn,
                            sheet_nm,
                            sheet_nm,
                            mt,
                            tier1_cbm,
                            sid,
                            sid,
                            sname,
                            sname,
                            q_uid,
                        ),
                    )

                conn.execute(
                    """
                    INSERT INTO quote_versions (
                        quote_uid, version_no, calc_quote_id, saved_at, intent, quote_json
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (q_uid, next_ver, calc_id, saved_at, intent_str, payload_json),
                )

                _insert_quote_items(conn, q_uid, next_ver, detail_rows)
                conn.commit()
            except psycopg.errors.UniqueViolation:
                conn.rollback()


def delete_quote_series(quote_uid: str) -> bool:
    import quote_upload_storage as qus

    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return False
    init_quote_storage()
    files_meta = _fetch_quote_files_rows(q_uid)
    deleted = False
    with _PG_LOCK:
        with _connect_ctx() as conn:
            exists = conn.execute("SELECT 1 FROM quotes WHERE quote_uid = %s", (q_uid,)).fetchone()
            if not exists:
                pass
            else:
                conn.execute("DELETE FROM quote_items WHERE quote_uid = %s", (q_uid,))
                conn.execute("DELETE FROM quote_versions WHERE quote_uid = %s", (q_uid,))
                conn.execute(
                    "DELETE FROM quote_files WHERE quote_uid = %s OR quote_id = %s",
                    (q_uid, q_uid),
                )
                conn.execute("DELETE FROM quotes WHERE quote_uid = %s", (q_uid,))
                try:
                    conn.execute("DELETE FROM saved_quotes WHERE quote_id = %s", (q_uid,))
                except Exception:
                    pass
                conn.commit()
                deleted = True
    if not deleted:
        return False
    for rec in files_meta:
        fs_path = qus.resolve_stored_file_path(str(rec.get("stored_path") or ""))
        if fs_path:
            try:
                fs_path.unlink(missing_ok=True)
            except OSError:
                pass
    return True


def update_saved_quote_approval(
    quote_uid: str,
    *,
    approval_status: str,
    approval_note: str | None = None,
    version_no: int | None = None,
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    from quote_approval import (
        approval_result_payload,
        normalize_approval_note,
        normalize_approval_status,
        normalize_reviewer_name,
    )

    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        raise ValueError("缺少报价 UID。")
    status = normalize_approval_status(approval_status)
    note = normalize_approval_note(approval_note)
    init_quote_storage()
    actor = normalize_reviewer_name(reviewed_by)
    reviewed_at = utc_now_iso()
    want_ver_i = 0
    calc_id: str | None = None

    with _PG_LOCK:
        with _connect_ctx() as conn:
            qrow = conn.execute(
                "SELECT latest_version_no FROM quotes WHERE quote_uid = %s",
                (q_uid,),
            ).fetchone()
            if not qrow:
                raise ValueError("报价不存在。")
            want_ver = version_no
            if want_ver is None:
                want_ver = int(qrow[0] or 0)
            try:
                want_ver_i = int(want_ver or 0)
            except (TypeError, ValueError):
                want_ver_i = 0
            if want_ver_i <= 0:
                raise ValueError("版本号无效。")
            vrow = conn.execute(
                """
                SELECT version_no, calc_quote_id, saved_at
                FROM quote_versions
                WHERE quote_uid = %s AND version_no = %s
                """,
                (q_uid, want_ver_i),
            ).fetchone()
            if not vrow:
                raise ValueError("指定版本不存在。")
            calc_id = str(vrow[1] or "").strip() or None

            if status == "approved":
                conn.execute(
                    """
                    UPDATE quotes SET
                        approval_status = %s,
                        approval_note = %s,
                        approved_version_no = %s,
                        approved_calc_quote_id = %s,
                        approved_at = %s,
                        approved_by = %s,
                        updated_at = %s
                    WHERE quote_uid = %s
                    """,
                    (
                        status,
                        note,
                        want_ver_i,
                        calc_id,
                        reviewed_at,
                        actor,
                        reviewed_at,
                        q_uid,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE quotes SET
                        approval_status = %s,
                        approval_note = %s,
                        approved_version_no = NULL,
                        approved_calc_quote_id = NULL,
                        approved_at = %s,
                        approved_by = %s,
                        updated_at = %s
                    WHERE quote_uid = %s
                    """,
                    (status, note, reviewed_at, actor, reviewed_at, q_uid),
                )
            _mark_admin_update_pending_pg(conn, q_uid, now=reviewed_at)
            conn.commit()

    from quote_upload_storage import record_approval_chat_notification

    result = approval_result_payload(
        quote_uid=q_uid,
        approval_status=status,
        approval_note=note,
        approved_version_no=want_ver_i if status == "approved" else None,
        approved_calc_quote_id=calc_id if status == "approved" else None,
        approved_at=reviewed_at,
        approved_by=actor,
    )
    try:
        record_approval_chat_notification(q_uid, result)
    except Exception:
        pass
    return result


def approve_saved_quote(
    quote_uid: str,
    *,
    version_no: int | None = None,
    approved_by: str | None = None,
    approval_note: str | None = None,
) -> dict[str, Any]:
    return update_saved_quote_approval(
        quote_uid,
        approval_status="approved",
        approval_note=approval_note,
        version_no=version_no,
        reviewed_by=approved_by,
    )


def _resolve_quote_uid_for_public_lookup(conn, lookup_id: str) -> str | None:
    lid = str(lookup_id or "").strip()
    if not lid:
        return None
    row = conn.execute(
        "SELECT quote_uid FROM quotes WHERE quote_uid = %s LIMIT 1",
        (lid,),
    ).fetchone()
    if row:
        return str(row[0])
    row = conn.execute(
        """
        SELECT quote_uid FROM quote_versions
        WHERE calc_quote_id = %s
        ORDER BY version_no DESC LIMIT 1
        """,
        (lid,),
    ).fetchone()
    if row:
        return str(row[0])
    return None


def get_saved_quote_approval_public(lookup_id: str) -> dict[str, str]:
    from quote_approval import public_approval_snapshot

    lid = str(lookup_id or "").strip()
    if not lid:
        return public_approval_snapshot()
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            q_uid = _resolve_quote_uid_for_public_lookup(conn, lid)
            if not q_uid:
                return public_approval_snapshot()
            row = conn.execute(
                """
                SELECT approval_status, approval_note, approved_at, approved_by
                FROM quotes WHERE quote_uid = %s
                """,
                (q_uid,),
            ).fetchone()
    if not row:
        return public_approval_snapshot()
    return public_approval_snapshot(
        approval_status=row[0],
        approval_note=row[1],
        approved_at=row[2],
        approved_by=row[3],
    )


def get_saved_quote_approval_for_sales_user(
    lookup_id: str,
    sales_user_id: str,
) -> dict[str, str] | None:
    """前台审批只读：校验业务员归属；None 表示不存在或无权。"""
    from quote_approval import public_approval_snapshot

    lid = str(lookup_id or "").strip()
    sid = str(sales_user_id or "").strip()
    if not lid or not sid:
        return None
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            q_uid = _resolve_quote_uid_for_public_lookup(conn, lid)
            if not q_uid:
                return None
            from quote_upload_storage import sales_user_can_access_quote

            if not sales_user_can_access_quote(q_uid, sid):
                return None
            row = conn.execute(
                """
                SELECT approval_status, approval_note, approved_at, approved_by
                FROM quotes WHERE quote_uid = %s
                """,
                (q_uid,),
            ).fetchone()
    if not row:
        return None
    return public_approval_snapshot(
        approval_status=row[0],
        approval_note=row[1],
        approved_at=row[2],
        approved_by=row[3],
    )


def list_saved_quotes_summaries(
    *,
    limit: int = 50,
    offset: int = 0,
    search_q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    version_min: int | None = None,
    status: str | None = None,
    sales_user_q: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    from psycopg.rows import dict_row

    init_quote_storage()
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))

    conds: list[str] = ["TRUE"]
    params: list[Any] = []

    sq = str(search_q or "").strip()
    if sq:
        term = f"%{sq}%"
        conds.append(
            "(quote_uid LIKE %s OR COALESCE(product_name,'') LIKE %s OR COALESCE(sheet_original_name,'') LIKE %s)"
        )
        params.extend([term, term, term])

    df = str(date_from or "").strip()[:10]
    if df:
        conds.append("SUBSTRING(COALESCE(latest_saved_at,''), 1, 10) >= %s")
        params.append(df)

    dt_to = str(date_to or "").strip()[:10]
    if dt_to:
        conds.append("SUBSTRING(COALESCE(latest_saved_at,''), 1, 10) <= %s")
        params.append(dt_to)

    if version_min is not None:
        try:
            vmin = max(1, int(version_min))
            conds.append("latest_version_no >= %s")
            params.append(vmin)
        except (TypeError, ValueError):
            pass

    suq = str(sales_user_q or "").strip()
    if suq:
        owner_term = f"%{suq}%"
        conds.append(
            "(COALESCE(sales_user_id,'') LIKE %s OR COALESCE(sales_user_name,'') LIKE %s)"
        )
        params.extend([owner_term, owner_term])

    st = str(status or "").strip().lower()
    if st == "risk":
        conds.append("(tier1_cost_before_margin IS NULL OR COALESCE(material_total, 0) <= 0)")
    elif st == "warn":
        conds.append("(tier1_cost_before_margin IS NOT NULL AND COALESCE(material_total, 0) > 0)")
        conds.append(
            """EXISTS (
                SELECT 1 FROM quote_items qi
                WHERE qi.quote_uid = quotes.quote_uid
                  AND qi.version_no = quotes.latest_version_no
                  AND (qi.calc_note IS NULL OR TRIM(COALESCE(qi.calc_note, '')) = '')
            )"""
        )
    elif st == "normal":
        conds.append("(tier1_cost_before_margin IS NOT NULL AND COALESCE(material_total, 0) > 0)")
        conds.append(
            """NOT EXISTS (
                SELECT 1 FROM quote_items qi
                WHERE qi.quote_uid = quotes.quote_uid
                  AND qi.version_no = quotes.latest_version_no
                  AND (qi.calc_note IS NULL OR TRIM(COALESCE(qi.calc_note, '')) = '')
            )"""
        )

    where_sql = " AND ".join(conds)

    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT COUNT(*)::bigint AS c FROM quotes WHERE {where_sql}", params)
                total_row = cur.fetchone()
                total = int(total_row["c"]) if total_row else 0
                cur.execute(
                    f"""
                    SELECT quote_uid AS quote_id,
                           latest_saved_at AS saved_at,
                           product_name,
                           sheet_original_name,
                           material_total,
                           tier1_cost_before_margin,
                           latest_version_no,
                           approval_status,
                           approval_note,
                           approved_version_no,
                           approved_at,
                           approved_by,
                           sales_user_id,
                           sales_user_name
                    FROM quotes
                    WHERE {where_sql}
                    ORDER BY latest_saved_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, lim, off),
                )
                rows = cur.fetchall()
    items = [dict(r) for r in rows] if rows else []
    return items, total


def list_saved_quotes_changes_since(
    since: str,
    *,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    from psycopg.rows import dict_row

    since_norm = str(since or "").strip()
    if not since_norm:
        return [], 0
    init_quote_storage()
    lim = max(1, min(int(limit), 100))
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT COUNT(*)::bigint AS c FROM quotes WHERE latest_saved_at > %s",
                    (since_norm,),
                )
                count_row = cur.fetchone()
                new_count = int(count_row["c"]) if count_row else 0
                cur.execute(
                    """
                    SELECT quote_uid AS quote_id,
                           latest_saved_at AS saved_at,
                           product_name,
                           sheet_original_name,
                           material_total,
                           tier1_cost_before_margin,
                           latest_version_no,
                           approval_status,
                           approval_note,
                           approved_version_no,
                           approved_at,
                           approved_by
                    FROM quotes
                    WHERE latest_saved_at > %s
                    ORDER BY latest_saved_at DESC
                    LIMIT %s
                    """,
                    (since_norm, lim),
                )
                rows = cur.fetchall()
    return [dict(r) for r in rows], new_count


def get_admin_dashboard_stats() -> dict[str, Any]:
    from psycopg.rows import dict_row

    init_quote_storage()
    sql = """
    SELECT
        COUNT(*)::bigint AS total_quotes,
        SUM(
            CASE WHEN SUBSTRING(COALESCE(latest_saved_at,''), 1, 10) =
                      TO_CHAR((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD')
            THEN 1 ELSE 0 END
        )::bigint AS today_new,
        AVG(material_total) AS avg_material_total,
        AVG(tier1_cost_before_margin) AS avg_tier1_cost_before_margin,
        MAX(latest_saved_at) AS latest_saved_at,
        (
            SELECT AVG(
                CASE WHEN qv.quote_json ~ '^[[:space:]]*\\{'
                     THEN (qv.quote_json::json->'tiers'->0->>'exw_price')::double precision
                     ELSE NULL END
            )
            FROM quotes q
            INNER JOIN quote_versions qv ON qv.quote_uid = q.quote_uid AND qv.version_no = q.latest_version_no
        ) AS avg_tier1_exw
    FROM quotes
    """
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql)
                rd = dict(cur.fetchone() or {})

    def _f(v: Any) -> float | None:
        if v is None:
            return None
        try:
            return round(float(v), 4)
        except (TypeError, ValueError):
            return None

    return {
        "total_quotes": int(rd.get("total_quotes") or 0),
        "today_new": int(rd.get("today_new") or 0),
        "avg_material_total": _f(rd.get("avg_material_total")),
        "avg_tier1_cost_before_margin": _f(rd.get("avg_tier1_cost_before_margin")),
        "avg_tier1_exw": _f(rd.get("avg_tier1_exw")),
        "latest_saved_at": str(rd.get("latest_saved_at") or "") or None,
    }


def get_saved_quote_admin_bundle(
    quote_uid: str, *, version_no: int | None = None
) -> dict[str, Any] | None:
    from psycopg.rows import dict_row

    init_quote_storage()
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return None
    meta_out: dict[str, Any] = {}
    quote_obj: dict[str, Any] = {}
    items_db: list[dict[str, Any]] = []
    versions: list[dict[str, Any]] = []
    ver_no_use = 1
    system_quote: dict[str, Any] | None = None

    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM quotes WHERE quote_uid = %s", (q_uid,))
                qrow = cur.fetchone()
                if not qrow:
                    return None
                meta = dict(qrow)

                want_ver = version_no
                if want_ver is None:
                    want_ver = int(meta.get("latest_version_no") or 1)

                cur.execute(
                    """
                    SELECT * FROM quote_versions
                    WHERE quote_uid = %s AND version_no = %s
                    """,
                    (q_uid, want_ver),
                )
                vrow = cur.fetchone()
                if not vrow:
                    cur.execute(
                        """
                        SELECT * FROM quote_versions WHERE quote_uid = %s
                        ORDER BY version_no DESC LIMIT 1
                        """,
                        (q_uid,),
                    )
                    vrow = cur.fetchone()
                if not vrow:
                    return None

                vdict = dict(vrow)
                raw_json = vdict.get("quote_json") or "{}"
                try:
                    quote_obj = json.loads(raw_json)
                except json.JSONDecodeError:
                    quote_obj = {}

                ver_no_use = int(vdict["version_no"])
                cur.execute(
                    """
                    SELECT line_no, name, spec, usage, unit_price, amount, amount_text,
                           source, calc_note, kb_hit
                    FROM quote_items
                    WHERE quote_uid = %s AND version_no = %s
                    ORDER BY line_no ASC
                    """,
                    (q_uid, ver_no_use),
                )
                items_db = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT version_no, calc_quote_id, saved_at, intent FROM quote_versions
                    WHERE quote_uid = %s
                    ORDER BY version_no DESC
                    """,
                    (q_uid,),
                )
                versions = [dict(r) for r in cur.fetchall()]

                meta_out = {
                    **meta,
                    "selected_version_no": ver_no_use,
                    "selected_calc_quote_id": vdict.get("calc_quote_id"),
                }
                latest_ver = int(meta.get("latest_version_no") or ver_no_use or 1)
                system_quote: dict[str, Any] | None = None
                if latest_ver > 1:
                    system_quote = load_quote_version_object(q_uid, 1)
                elif isinstance(quote_obj, dict):
                    system_quote = quote_obj

    files = _fetch_quote_files_rows(q_uid)
    from quote_upload_storage import reconcile_admin_quote_detail_rows

    reconcile_admin_quote_detail_rows(quote_obj, items_db)
    from piece_area_table import enrich_quote_piece_area_on_read

    enrich_quote_piece_area_on_read(quote_obj, items_db)
    from marker_room_bom_display import enrich_quote_marker_room_bom_table

    enrich_quote_marker_room_bom_table(quote_obj)
    return {
        "meta": meta_out,
        "quote": quote_obj,
        "items": items_db,
        "versions": versions,
        "files": files,
        "system_quote": system_quote,
    }


def search_quote_items_by_keyword(keyword: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """按材料名/规格检索历史报价明细（最新版本）。"""
    q = str(keyword or "").strip()
    if not q or len(q) < 2:
        return []
    lim = max(1, min(int(limit), 20))
    term = f"%{q}%"
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT qi.name, qi.spec, qi.unit_price, qi.amount, qi.amount_text,
                           q.product_name, q.latest_saved_at AS saved_at, q.quote_uid
                    FROM quote_items qi
                    INNER JOIN quotes q ON q.quote_uid = qi.quote_uid
                        AND qi.version_no = q.latest_version_no
                    WHERE COALESCE(qi.name, '') ILIKE %s
                       OR COALESCE(qi.spec, '') ILIKE %s
                    ORDER BY q.latest_saved_at DESC NULLS LAST
                    LIMIT %s
                    """,
                    (term, term, lim),
                )
                rows = cur.fetchall()
                return [dict(r) for r in rows]


def load_quote_version_object(quote_uid: str, version_no: int) -> dict[str, Any] | None:
    """加载指定版本的 quote_json（Postgres）。"""
    from psycopg.rows import dict_row

    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return None
    try:
        ver = int(version_no)
    except (TypeError, ValueError):
        return None
    if ver <= 0:
        return None
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT quote_json FROM quote_versions
                    WHERE quote_uid = %s AND version_no = %s
                    LIMIT 1
                    """,
                    (q_uid, ver),
                )
                row = cur.fetchone()
    if not row:
        return None
    try:
        obj = json.loads(str(row.get("quote_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def load_latest_quote_object(quote_uid: str) -> dict[str, Any] | None:
    """加载最新版本 quote_json（Postgres）。"""
    from psycopg.rows import dict_row

    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return None
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT quote_json FROM quote_versions
                    WHERE quote_uid = %s
                    ORDER BY version_no DESC
                    LIMIT 1
                    """,
                    (q_uid,),
                )
                row = cur.fetchone()
    if not row:
        return None
    try:
        obj = json.loads(str(row.get("quote_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def lookup_customer_profile(sales_user_id: str, cust_name: str) -> dict[str, str]:
    """读取同业务员、同客户的报价单资料建议（Postgres）。"""
    from psycopg.rows import dict_row
    from quote_sheet_meta import normalize_customer_key, normalize_meta_payload

    sid = str(sales_user_id or "").strip()
    key = normalize_customer_key(cust_name)
    if not sid or not key:
        return {}
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT cust_contact, cust_phone, cust_addr, seller_email
                    FROM quote_customer_profiles
                    WHERE sales_user_id = %s AND customer_key = %s
                    LIMIT 1
                    """,
                    (sid, key),
                )
                row = cur.fetchone()
    if not row:
        return {}
    return normalize_meta_payload(
        {
            "cust_contact": row.get("cust_contact"),
            "cust_phone": row.get("cust_phone"),
            "cust_addr": row.get("cust_addr"),
            "seller_email": row.get("seller_email"),
        }
    )


def upsert_customer_profile(sales_user_id: str, meta: dict[str, Any]) -> None:
    """保存同客户历史资料建议（Postgres）。"""
    from quote_sheet_meta import normalize_customer_key, normalize_meta_payload

    sid = str(sales_user_id or "").strip()
    payload = normalize_meta_payload(meta)
    cust_name = str(payload.get("cust_name") or "").strip()
    key = normalize_customer_key(cust_name)
    if not sid or not key:
        return
    if not any(
        str(payload.get(k) or "").strip()
        for k in ("cust_contact", "cust_phone", "cust_addr", "seller_email")
    ):
        return
    init_quote_storage()
    now = utc_now_iso()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            conn.execute(
                """
                INSERT INTO quote_customer_profiles (
                    sales_user_id, customer_key, cust_name,
                    cust_contact, cust_phone, cust_addr, seller_email, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sales_user_id, customer_key) DO UPDATE SET
                    cust_name = EXCLUDED.cust_name,
                    cust_contact = CASE
                        WHEN EXCLUDED.cust_contact <> '' THEN EXCLUDED.cust_contact
                        ELSE quote_customer_profiles.cust_contact
                    END,
                    cust_phone = CASE
                        WHEN EXCLUDED.cust_phone <> '' THEN EXCLUDED.cust_phone
                        ELSE quote_customer_profiles.cust_phone
                    END,
                    cust_addr = CASE
                        WHEN EXCLUDED.cust_addr <> '' THEN EXCLUDED.cust_addr
                        ELSE quote_customer_profiles.cust_addr
                    END,
                    seller_email = CASE
                        WHEN EXCLUDED.seller_email <> '' THEN EXCLUDED.seller_email
                        ELSE quote_customer_profiles.seller_email
                    END,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    sid,
                    key,
                    cust_name,
                    payload.get("cust_contact", ""),
                    payload.get("cust_phone", ""),
                    payload.get("cust_addr", ""),
                    payload.get("seller_email", ""),
                    now,
                ),
            )
            conn.commit()


def save_quote_sheet_meta(
    quote_series_uid: str,
    sales_user_id: str,
    meta_payload: dict[str, Any],
    *,
    quote_no_manual: bool | None = None,
) -> dict[str, Any]:
    """保存报价单表头/客户资料到最新 quote_versions.quote_json（Postgres）。"""
    from psycopg.rows import dict_row
    from quote_sheet_meta import (
        _mirror_meta_to_quote_root,
        extract_saved_meta,
        normalize_meta_payload,
        quote_no_manual_from_saved,
    )

    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid:
        return {"ok": False, "error": "invalid_request", "message": "缺少报价或业务员标识。"}
    if not sales_user_can_access_quote(q_uid, sid):
        return {"ok": False, "error": "not_found", "message": "报价不存在或无权操作。"}

    meta = normalize_meta_payload(meta_payload)
    manual_flag = quote_no_manual
    if manual_flag is None:
        manual_flag = bool(meta.get("quote_no"))

    init_quote_storage()
    now = utc_now_iso()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT version_no, quote_json FROM quote_versions
                    WHERE quote_uid = %s
                    ORDER BY version_no DESC
                    LIMIT 1
                    """,
                    (q_uid,),
                )
                row = cur.fetchone()
                if not row:
                    return {"ok": False, "error": "not_found", "message": "报价记录不存在。"}
                ver = int(row.get("version_no") or 0)
                try:
                    quote_obj = json.loads(str(row.get("quote_json") or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    quote_obj = {}
                if not isinstance(quote_obj, dict):
                    quote_obj = {}

                prev_saved = extract_saved_meta(quote_obj)
                if manual_flag and meta.get("quote_no"):
                    pass
                elif quote_no_manual_from_saved(quote_obj) and prev_saved.get("quote_no"):
                    meta["quote_no"] = prev_saved["quote_no"]

                block = {
                    **meta,
                    "updated_at": now,
                    "saved_by_sales_user_id": sid,
                }
                if manual_flag and meta.get("quote_no"):
                    block["quote_no_manual"] = True

                quote_obj["quote_sheet_meta"] = block
                quote_obj["quote_sheet_no_manual"] = bool(block.get("quote_no_manual"))
                _mirror_meta_to_quote_root(quote_obj, meta)

                cur.execute(
                    """
                    UPDATE quote_versions SET quote_json = %s
                    WHERE quote_uid = %s AND version_no = %s
                    """,
                    (json.dumps(quote_obj, ensure_ascii=False, default=str), q_uid, ver),
                )
                cur.execute(
                    "UPDATE quotes SET updated_at = %s WHERE quote_uid = %s",
                    (now, q_uid),
                )
            conn.commit()

    upsert_customer_profile(sid, meta)
    return {"ok": True, "quote_series_uid": q_uid, "meta": meta}


def save_admin_quote_feedback(
    quote_uid: str,
    *,
    correction_note: str | None = None,
    correction_problem_types: list[str] | str | None = None,
    reviewed_by: str = "admin",
    notify_sales: bool = True,
    deal_status: str = "",
    final_price: str = "",
    loss_reason: str = "",
) -> dict[str, Any]:
    from admin_correction_inbox import normalize_correction_problem_types
    from psycopg.rows import dict_row
    from quote_upload_storage import (
        _record_admin_correction_chat_notification,
        build_admin_feedback_public,
        list_quote_files_for_quote,
    )

    q_uid = str(quote_uid or "").strip()
    actor = str(reviewed_by or "admin").strip() or "admin"
    if not q_uid:
        raise ValueError("quote_uid 不能为空")
    note = str(correction_note or "").strip()
    problem_types = normalize_correction_problem_types(correction_problem_types)
    problem_types_json = json.dumps(problem_types, ensure_ascii=False) if problem_types else ""
    now = utc_now_iso()
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            row = conn.execute(
                "SELECT quote_uid FROM quotes WHERE quote_uid = %s LIMIT 1",
                (q_uid,),
            ).fetchone()
            if not row:
                raise ValueError("not_found")
            conn.execute(
                """
                UPDATE quotes SET
                    admin_correction_note = %s,
                    admin_correction_problem_types = %s,
                    admin_feedback_at = %s,
                    admin_feedback_by = %s,
                    updated_at = %s
                WHERE quote_uid = %s
                """,
                (note, problem_types_json, now, actor, now, q_uid),
            )
            _mark_admin_update_pending_pg(conn, q_uid, now=now)
            conn.commit()
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM quotes WHERE quote_uid = %s", (q_uid,))
                meta_row = cur.fetchone()
            meta = dict(meta_row) if meta_row else {}
    if notify_sales:
        _record_admin_correction_chat_notification(q_uid, note, actor, now)
    if deal_status or final_price or loss_reason:
        try:
            from quote_price_auto_learning import patch_quote_learning_deal_info

            patch_quote_learning_deal_info(
                q_uid,
                deal_status=deal_status,
                final_price=final_price,
                loss_reason=loss_reason,
                operator=actor,
            )
        except Exception:
            import logging

            logging.getLogger(__name__).debug(
                "patch quote learning deal info skipped", exc_info=True
            )
    files = list_quote_files_for_quote(q_uid)
    return {
        "ok": True,
        "quote_uid": q_uid,
        "admin_feedback": build_admin_feedback_public(meta, files),
    }


def _mark_admin_update_pending_pg(conn: Any, q_uid: str, *, now: str | None = None) -> None:
    from quote_upload_storage import ADMIN_UPDATE_STATUS_PENDING

    ts = now or utc_now_iso()
    conn.execute(
        """
        UPDATE quotes SET
            admin_update_status = %s,
            admin_update_at = %s,
            admin_update_viewed_at = NULL,
            admin_update_handled_at = NULL,
            updated_at = %s
        WHERE quote_uid = %s
        """,
        (ADMIN_UPDATE_STATUS_PENDING, ts, ts, q_uid),
    )


def mark_admin_visual_correction_pending(
    quote_uid: str,
    actor: str = "admin",
    *,
    now: str | None = None,
) -> None:
    from psycopg.rows import dict_row
    from quote_upload_storage import ADMIN_UPDATE_STATUS_PENDING

    q_uid = str(quote_uid or "").strip()
    act = str(actor or "admin").strip() or "admin"
    if not q_uid:
        raise ValueError("quote_uid 不能为空")
    ts = now or utc_now_iso()
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT quote_uid FROM quotes WHERE quote_uid = %s LIMIT 1",
                    (q_uid,),
                )
                if not cur.fetchone():
                    raise ValueError("not_found")
            conn.execute(
                """
                UPDATE quotes SET
                    admin_update_status = %s,
                    admin_update_at = %s,
                    admin_update_viewed_at = NULL,
                    admin_update_handled_at = NULL,
                    admin_feedback_at = %s,
                    admin_feedback_by = %s,
                    updated_at = %s
                WHERE quote_uid = %s
                """,
                (ADMIN_UPDATE_STATUS_PENDING, ts, ts, act, ts, q_uid),
            )
            conn.commit()


def _persist_admin_typed_sheet_pg(
    quote_uid: str,
    uploaded_sheet: dict[str, Any],
    *,
    sheet_kind: str,
    uploaded_by: str = "admin",
    replace_confirmed: bool = False,
) -> dict[str, Any]:
    from quote_upload_storage import (
        ADMIN_SHEET_KIND_CONFIG,
        _decode_admin_upload_sheet,
        _record_admin_sheet_upload_notification,
        resolve_stored_file_path,
    )

    cfg = ADMIN_SHEET_KIND_CONFIG.get(sheet_kind)
    if not cfg:
        raise ValueError("invalid_sheet_kind")
    q_uid = str(quote_uid or "").strip()
    actor = str(uploaded_by or "admin").strip() or "admin"
    if not q_uid:
        raise ValueError("quote_uid 不能为空")
    original_name, raw = _decode_admin_upload_sheet(uploaded_sheet, sheet_kind=sheet_kind)
    file_id_col = str(cfg["file_id_col"])
    at_col = str(cfg["at_col"])
    by_col = str(cfg["by_col"])
    file_role = str(cfg["file_role"])

    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"SELECT quote_uid, {file_id_col} AS prev_file_id FROM quotes WHERE quote_uid = %s LIMIT 1",
                    (q_uid,),
                )
                qrow = cur.fetchone()
            if not qrow:
                raise ValueError("not_found")
            prev_fid = str(qrow.get("prev_file_id") or "").strip()
            if prev_fid and not replace_confirmed:
                raise ValueError("replace_confirm_required")
            if prev_fid:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT stored_path FROM quote_files WHERE file_id = %s LIMIT 1",
                        (prev_fid,),
                    )
                    prev = cur.fetchone()
                conn.execute("DELETE FROM quote_files WHERE file_id = %s", (prev_fid,))
                if prev:
                    old_path = resolve_stored_file_path(str(prev.get("stored_path") or ""))
                    if old_path:
                        try:
                            old_path.unlink(missing_ok=True)
                        except OSError:
                            pass
            conn.commit()

    file_id = uuid.uuid4().hex
    ext = Path(original_name).suffix if len(Path(original_name).suffix) <= 12 else ""
    stored_rel = Path("data") / "uploads" / f"{file_id}{ext}"
    abs_path = _root() / stored_rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(raw)

    digest = hashlib.sha256(raw).hexdigest()
    mime_guess = mimetypes.guess_type(original_name)[0]
    mime_type = mime_guess or "application/octet-stream"
    uploaded_at = utc_now_iso()

    with _PG_LOCK:
        with _connect_ctx() as conn:
            ver = _next_file_version(conn, q_uid)
            conn.execute(
                """
                INSERT INTO quote_files (
                    file_id, quote_id, quote_uid, calc_quote_id, version_no,
                    original_name, stored_path, mime_type, file_size,
                    file_hash_sha256, uploaded_at, file_role, uploaded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    file_id,
                    q_uid,
                    q_uid,
                    None,
                    ver,
                    original_name,
                    stored_rel.as_posix(),
                    mime_type,
                    len(raw),
                    digest,
                    uploaded_at,
                    file_role,
                    actor,
                ),
            )
            conn.execute(
                f"""
                UPDATE quotes SET
                    {file_id_col} = %s,
                    {at_col} = %s,
                    {by_col} = %s,
                    updated_at = %s
                WHERE quote_uid = %s
                """,
                (file_id, uploaded_at, actor, uploaded_at, q_uid),
            )
            _mark_admin_update_pending_pg(conn, q_uid, now=uploaded_at)
            conn.commit()

    _record_admin_sheet_upload_notification(
        q_uid,
        sheet_kind,
        original_name=original_name,
        actor=actor,
        at=uploaded_at,
    )
    return {
        "ok": True,
        "quote_uid": q_uid,
        "sheet_kind": sheet_kind,
        "file": {
            "file_id": file_id,
            "quote_id": q_uid,
            "quote_uid": q_uid,
            "calc_quote_id": None,
            "version_no": ver,
            "original_name": original_name,
            "stored_path": stored_rel.as_posix(),
            "mime_type": mime_type,
            "file_size": len(raw),
            "file_hash_sha256": digest,
            "uploaded_at": uploaded_at,
            "file_role": file_role,
            "uploaded_by": actor,
            "sheet_type": sheet_kind,
        },
    }


def persist_admin_correction_sheet(
    quote_uid: str,
    uploaded_sheet: dict[str, Any],
    *,
    uploaded_by: str = "admin",
    replace_confirmed: bool = False,
) -> dict[str, Any]:
    from quote_upload_storage import ADMIN_SHEET_KIND_CORRECTED

    return _persist_admin_typed_sheet_pg(
        quote_uid,
        uploaded_sheet,
        sheet_kind=ADMIN_SHEET_KIND_CORRECTED,
        uploaded_by=uploaded_by,
        replace_confirmed=replace_confirmed,
    )


def persist_admin_calculated_sheet(
    quote_uid: str,
    uploaded_sheet: dict[str, Any],
    *,
    uploaded_by: str = "admin",
    replace_confirmed: bool = False,
) -> dict[str, Any]:
    from quote_upload_storage import ADMIN_SHEET_KIND_CALCULATED

    return _persist_admin_typed_sheet_pg(
        quote_uid,
        uploaded_sheet,
        sheet_kind=ADMIN_SHEET_KIND_CALCULATED,
        uploaded_by=uploaded_by,
        replace_confirmed=replace_confirmed,
    )


def delete_admin_sheet_by_kind(
    quote_uid: str,
    *,
    sheet_kind: str,
    deleted_by: str = "admin",
) -> dict[str, Any]:
    from quote_upload_storage import (
        ADMIN_SHEET_KIND_CONFIG,
        _admin_sheet_roles_for_kind,
        resolve_stored_file_path,
    )

    cfg = ADMIN_SHEET_KIND_CONFIG.get(sheet_kind)
    if not cfg:
        raise ValueError("invalid_sheet_kind")
    q_uid = str(quote_uid or "").strip()
    _ = str(deleted_by or "admin").strip() or "admin"
    if not q_uid:
        raise ValueError("quote_uid 不能为空")
    file_id_col = str(cfg["file_id_col"])
    at_col = str(cfg["at_col"])
    by_col = str(cfg["by_col"])
    no_sheet_error = str(cfg["no_sheet_error"])
    roles = _admin_sheet_roles_for_kind(sheet_kind)
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"SELECT quote_uid, {file_id_col} AS prev_file_id FROM quotes WHERE quote_uid = %s LIMIT 1",
                    (q_uid,),
                )
                qrow = cur.fetchone()
            if not qrow:
                raise ValueError("not_found")
            prev_fid = str(qrow.get("prev_file_id") or "").strip()
            placeholders = ",".join("%s" for _ in roles)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT file_id, stored_path FROM quote_files
                    WHERE quote_uid = %s AND file_role IN ({placeholders})
                    """,
                    (q_uid, *roles),
                )
                rows = list(cur.fetchall())
            if not prev_fid and not rows:
                raise ValueError(no_sheet_error)
            targets: dict[str, str] = {str(r["file_id"]): str(r.get("stored_path") or "") for r in rows}
            if prev_fid and prev_fid not in targets:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT file_id, stored_path FROM quote_files WHERE file_id = %s AND quote_uid = %s LIMIT 1",
                        (prev_fid, q_uid),
                    )
                    extra = cur.fetchone()
                if extra:
                    targets[str(extra["file_id"])] = str(extra.get("stored_path") or "")
            removed = 0
            for fid, stored_path in targets.items():
                fs_path = resolve_stored_file_path(stored_path)
                if fs_path:
                    try:
                        fs_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                conn.execute("DELETE FROM quote_files WHERE file_id = %s", (fid,))
                removed += 1
            if removed <= 0 and not prev_fid:
                raise ValueError(no_sheet_error)
            now = utc_now_iso()
            conn.execute(
                f"""
                UPDATE quotes SET
                    {file_id_col} = NULL,
                    {at_col} = NULL,
                    {by_col} = NULL,
                    updated_at = %s
                WHERE quote_uid = %s
                """,
                (now, q_uid),
            )
            conn.commit()
    return {"ok": True, "quote_uid": q_uid, "deleted": True, "sheet_kind": sheet_kind}


def delete_admin_correction_sheet(
    quote_uid: str,
    *,
    deleted_by: str = "admin",
) -> dict[str, Any]:
    from quote_upload_storage import ADMIN_SHEET_KIND_CORRECTED

    return delete_admin_sheet_by_kind(
        quote_uid,
        sheet_kind=ADMIN_SHEET_KIND_CORRECTED,
        deleted_by=deleted_by,
    )


def mark_sales_admin_update_viewed(
    quote_series_uid: str,
    sales_user_id: str,
) -> dict[str, Any] | None:
    from quote_upload_storage import (
        ADMIN_UPDATE_STATUS_PENDING,
        ADMIN_UPDATE_STATUS_VIEWED,
        build_admin_feedback_public,
        list_quote_files_for_quote,
        sales_user_can_access_quote,
    )

    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid or not sales_user_can_access_quote(q_uid, sid):
        return None
    now = utc_now_iso()
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT admin_update_status FROM quotes WHERE quote_uid = %s LIMIT 1",
                    (q_uid,),
                )
                row = cur.fetchone()
            if not row:
                return None
            status = str(row.get("admin_update_status") or "").strip().lower()
            if status != ADMIN_UPDATE_STATUS_PENDING:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT * FROM quotes WHERE quote_uid = %s LIMIT 1", (q_uid,))
                    meta_row = cur.fetchone()
                meta = dict(meta_row) if meta_row else {}
                files = list_quote_files_for_quote(q_uid)
                return {
                    "ok": True,
                    "quote_uid": q_uid,
                    "admin_feedback": build_admin_feedback_public(meta, files),
                }
            conn.execute(
                """
                UPDATE quotes SET
                    admin_update_status = %s,
                    admin_update_viewed_at = %s,
                    updated_at = %s
                WHERE quote_uid = %s
                """,
                (ADMIN_UPDATE_STATUS_VIEWED, now, now, q_uid),
            )
            conn.commit()
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM quotes WHERE quote_uid = %s LIMIT 1", (q_uid,))
                meta_row = cur.fetchone()
            meta = dict(meta_row) if meta_row else {}
    files = list_quote_files_for_quote(q_uid)
    return {
        "ok": True,
        "quote_uid": q_uid,
        "admin_feedback": build_admin_feedback_public(meta, files),
    }


def mark_sales_admin_update_handled(
    quote_series_uid: str,
    sales_user_id: str,
) -> dict[str, Any] | None:
    from admin_correction_inbox import ADMIN_UPDATE_STATUS_HANDLED
    from quote_upload_storage import (
        build_admin_feedback_public,
        list_quote_files_for_quote,
        sales_user_can_access_quote,
    )

    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid or not sales_user_can_access_quote(q_uid, sid):
        return None
    now = utc_now_iso()
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT quote_uid FROM quotes WHERE quote_uid = %s LIMIT 1",
                    (q_uid,),
                )
                if not cur.fetchone():
                    return None
            conn.execute(
                """
                UPDATE quotes SET
                    admin_update_status = %s,
                    admin_update_handled_at = %s,
                    updated_at = %s
                WHERE quote_uid = %s
                """,
                (ADMIN_UPDATE_STATUS_HANDLED, now, now, q_uid),
            )
            conn.commit()
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM quotes WHERE quote_uid = %s LIMIT 1", (q_uid,))
                meta_row = cur.fetchone()
            meta = dict(meta_row) if meta_row else {}
    files = list_quote_files_for_quote(q_uid)
    return {
        "ok": True,
        "quote_uid": q_uid,
        "admin_feedback": build_admin_feedback_public(meta, files),
    }


def _sales_quote_visible_sql_pg() -> str:
    return "(sales_hidden_at IS NULL OR sales_hidden_at = '')"


def _latest_amount_text_from_quote_row(row: dict[str, Any]) -> str:
    try:
        mt = float(row.get("material_total") or 0.0)
    except (TypeError, ValueError):
        mt = 0.0
    return f"¥{mt:.2f}" if mt > 0 else "-"


def list_my_quotes_for_sales_user(
    sales_user_id: str,
    *,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row
    from quote_upload_storage import ADMIN_UPDATE_STATUS_PENDING

    sid = str(sales_user_id or "").strip()
    if not sid:
        return []
    init_quote_storage()
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    filt = str(status_filter or "").strip().lower()
    conds = [f"sales_user_id = %s", _sales_quote_visible_sql_pg()]
    params: list[Any] = [sid]
    if filt in {"pending", "approved", "rejected"}:
        conds.append("approval_status = %s")
        params.append(filt)
    where_sql = " AND ".join(conds)
    params.extend([lim, off])
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT quote_uid, latest_calc_quote_id, product_name, sheet_original_name,
                           created_at, updated_at, material_total, tier1_cost_before_margin,
                           approval_status, approval_note, approved_by, approved_at,
                           sales_user_id, sales_user_name,
                           admin_update_status, admin_update_at, admin_update_viewed_at
                    FROM quotes
                    WHERE {where_sql}
                    ORDER BY updated_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
    items: list[dict[str, Any]] = []
    for row in rows or []:
        rd = dict(row)
        update_status = str(rd.get("admin_update_status") or "").strip().lower()
        items.append(
            {
                "quote_series_uid": rd.get("quote_uid"),
                "quote_id": rd.get("latest_calc_quote_id"),
                "sales_user_id": rd.get("sales_user_id"),
                "sales_user_name": rd.get("sales_user_name"),
                "product_name": rd.get("product_name") or "",
                "sheet_original_name": rd.get("sheet_original_name") or "",
                "created_at": rd.get("created_at"),
                "updated_at": rd.get("updated_at"),
                "approval_status": rd.get("approval_status") or "pending",
                "approval_comment": rd.get("approval_note") or "",
                "approved_by": rd.get("approved_by") or "",
                "approved_at": rd.get("approved_at") or "",
                "latest_amount_text": _latest_amount_text_from_quote_row(rd),
                "admin_update_status": update_status,
                "admin_update_at": rd.get("admin_update_at") or "",
                "admin_update_viewed_at": rd.get("admin_update_viewed_at") or "",
                "has_admin_update": update_status == ADMIN_UPDATE_STATUS_PENDING,
            }
        )
    return items


def count_unread_admin_updates_for_sales_user(sales_user_id: str) -> int:
    from quote_upload_storage import ADMIN_UPDATE_STATUS_PENDING

    sid = str(sales_user_id or "").strip()
    if not sid:
        return 0
    init_quote_storage()
    activity_sql = """
        (
            latest_version_no > 1
            OR COALESCE(admin_update_at, '') <> ''
            OR COALESCE(admin_feedback_at, '') <> ''
            OR COALESCE(admin_calculated_file_id, '') <> ''
            OR COALESCE(admin_correction_note, '') <> ''
        )
    """
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS c FROM quotes
                    WHERE sales_user_id = %s AND {_sales_quote_visible_sql_pg()}
                      AND admin_update_status = %s AND {activity_sql}
                    """,
                    (sid, ADMIN_UPDATE_STATUS_PENDING),
                )
                row = cur.fetchone()
    return int((row or {}).get("c") or 0)


def list_my_admin_updates_for_sales_user(
    sales_user_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    from quote_upload_storage import (
        _admin_update_has_activity,
        build_admin_feedback_public,
        list_quote_files_for_quote,
    )

    sid = str(sales_user_id or "").strip()
    if not sid:
        return []
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    activity_sql = """
        (
            latest_version_no > 1
            OR COALESCE(admin_update_at, '') <> ''
            OR COALESCE(admin_feedback_at, '') <> ''
            OR COALESCE(admin_calculated_file_id, '') <> ''
            OR COALESCE(admin_correction_note, '') <> ''
        )
    """
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT * FROM quotes
                    WHERE sales_user_id = %s AND {_sales_quote_visible_sql_pg()} AND {activity_sql}
                    ORDER BY COALESCE(admin_update_at, updated_at) DESC
                    LIMIT %s OFFSET %s
                    """,
                    (sid, lim, off),
                )
                rows = cur.fetchall() or []
    items: list[dict[str, Any]] = []
    for rd in rows:
        meta = dict(rd)
        q_uid = str(meta.get("quote_uid") or "").strip()
        files = list_quote_files_for_quote(q_uid)
        fb = build_admin_feedback_public(meta, files)
        if not fb.get("has_admin_correction") and not _admin_update_has_activity(meta):
            continue
        items.append(
            {
                "quote_series_uid": q_uid,
                "quote_id": meta.get("latest_calc_quote_id"),
                "product_name": meta.get("product_name") or "",
                "sheet_original_name": meta.get("sheet_original_name") or "",
                "updated_at": meta.get("updated_at"),
                "admin_update_status": fb.get("admin_update_status") or "",
                "admin_update_at": fb.get("admin_update_at") or "",
                "admin_update_viewed_at": fb.get("admin_update_viewed_at") or "",
                "admin_update_handled_at": fb.get("admin_update_handled_at") or "",
                "status_label_cn": fb.get("status_label_cn") or "",
                "correction_types": fb.get("correction_types") or [],
                "correction_types_label": fb.get("correction_types_label") or "",
                "feedback_by": fb.get("feedback_by") or "",
                "feedback_at": fb.get("feedback_at") or fb.get("admin_update_at") or "",
                "has_admin_update": bool(fb.get("has_admin_update")),
                "correction_note": fb.get("correction_note") or "",
                "approval_status": str(meta.get("approval_status") or "pending"),
                "approval_note": str(meta.get("approval_note") or ""),
                "rejection_reason": fb.get("rejection_reason") or "",
                "has_calculated_sheet": bool(fb.get("calculated_sheet")),
            }
        )
    return items


def sales_user_can_access_quote(quote_uid: str, sales_user_id: str) -> bool:
    from psycopg.rows import dict_row
    from quote_storage.db_common import sales_user_owns_quote

    q_uid = str(quote_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid:
        return False
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT sales_user_id, sales_hidden_at FROM quotes
                    WHERE quote_uid = %s LIMIT 1
                    """,
                    (q_uid,),
                )
                row = cur.fetchone()
    if not row:
        return False
    if str(row.get("sales_hidden_at") or "").strip():
        return False
    owner = str(row.get("sales_user_id") or "").strip()
    return sales_user_owns_quote(owner, sid)


def get_admin_sheet_for_sales(
    quote_series_uid: str,
    sales_user_id: str,
    *,
    sheet_kind: str,
) -> dict[str, Any] | None:
    from psycopg.rows import dict_row
    from quote_upload_storage import (
        ADMIN_SHEET_KIND_CONFIG,
        _normalize_file_role,
        get_quote_file_record,
    )

    cfg = ADMIN_SHEET_KIND_CONFIG.get(sheet_kind)
    if not cfg:
        return None
    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid or not sales_user_can_access_quote(q_uid, sid):
        return None
    file_id_col = str(cfg["file_id_col"])
    expected_role = str(cfg["file_role"])
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"SELECT {file_id_col} AS file_id FROM quotes WHERE quote_uid = %s LIMIT 1",
                    (q_uid,),
                )
                row = cur.fetchone()
    if not row:
        return None
    fid = str(row.get("file_id") or "").strip()
    if not fid:
        return None
    rec = get_quote_file_record(fid)
    if not rec or _normalize_file_role(rec.get("file_role")) != expected_role:
        return None
    return rec


def batch_hide_quotes_for_sales_user(
    sales_user_id: str,
    quote_uids: list[Any],
    *,
    max_items: int = 50,
) -> dict[str, Any]:
    from psycopg.rows import dict_row
    from quote_storage.db_common import sales_user_owns_quote

    sid = str(sales_user_id or "").strip()
    if not sid:
        raise ValueError("auth_required")
    if not isinstance(quote_uids, list):
        raise ValueError("invalid_request")
    uniq: list[str] = []
    seen: set[str] = set()
    cap = max(1, min(int(max_items), 100))
    for raw in quote_uids[:cap]:
        uid = str(raw or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        uniq.append(uid)
    if not uniq:
        raise ValueError("empty_quote_uids")
    now = utc_now_iso()
    deleted = 0
    not_found: list[str] = []
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            for uid in uniq:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        SELECT quote_uid, sales_user_id, sales_hidden_at
                        FROM quotes WHERE quote_uid = %s LIMIT 1
                        """,
                        (uid,),
                    )
                    row = cur.fetchone()
                if not row:
                    not_found.append(uid)
                    continue
                owner = str(row.get("sales_user_id") or "").strip()
                if not sales_user_owns_quote(owner, sid):
                    not_found.append(uid)
                    continue
                if str(row.get("sales_hidden_at") or "").strip():
                    deleted += 1
                    continue
                conn.execute(
                    """
                    UPDATE quotes SET sales_hidden_at = %s, updated_at = %s
                    WHERE quote_uid = %s
                    """,
                    (now, now, uid),
                )
                deleted += 1
            conn.commit()
    return {"ok": True, "deleted": deleted, "not_found": not_found}


def _chat_message_dict_from_row(rd: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    raw_meta = rd.get("metadata_json")
    if raw_meta:
        try:
            parsed = json.loads(raw_meta)
            if isinstance(parsed, dict):
                meta = parsed
        except json.JSONDecodeError:
            meta = {}
    return {
        "message_id": rd.get("message_id"),
        "quote_series_uid": rd.get("quote_series_uid"),
        "role": rd.get("role"),
        "content": rd.get("content") or "",
        "metadata": meta,
        "created_at": rd.get("created_at"),
    }


def bind_quote_sales_user(
    quote_uid: str,
    sales_user_id: str,
    *,
    sales_user_name: str | None = None,
) -> None:
    q_uid = str(quote_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid:
        return
    sname = str(sales_user_name or "").strip()
    now = utc_now_iso()
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            conn.execute(
                """
                UPDATE quotes SET
                    sales_user_id = CASE
                        WHEN sales_user_id IS NULL OR sales_user_id = '' THEN %s
                        ELSE sales_user_id
                    END,
                    sales_user_name = CASE
                        WHEN (sales_user_name IS NULL OR sales_user_name = '') AND %s <> ''
                        THEN %s
                        ELSE sales_user_name
                    END,
                    updated_at = %s
                WHERE quote_uid = %s
                """,
                (sid, sname, sname, now, q_uid),
            )
            conn.commit()


def save_quote_chat_message(
    quote_series_uid: str,
    role: str,
    content: str,
    *,
    message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> str:
    q_uid = str(quote_series_uid or "").strip()
    if not q_uid:
        return ""
    mid = str(message_id or "").strip() or uuid.uuid4().hex
    r = str(role or "system").strip().lower() or "system"
    body = str(content or "")
    meta_json = None
    if isinstance(metadata, dict) and metadata:
        try:
            meta_json = json.dumps(metadata, ensure_ascii=False, default=str)
        except TypeError:
            meta_json = "{}"
    ts = str(created_at or "").strip() or utc_now_iso()
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            conn.execute(
                """
                INSERT INTO quote_chat_messages (
                    message_id, quote_series_uid, role, content, metadata_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO UPDATE SET
                    quote_series_uid = EXCLUDED.quote_series_uid,
                    role = EXCLUDED.role,
                    content = EXCLUDED.content,
                    metadata_json = EXCLUDED.metadata_json,
                    created_at = EXCLUDED.created_at
                """,
                (mid, q_uid, r, body, meta_json, ts),
            )
            conn.commit()
    return mid


def list_quote_chat_messages(quote_series_uid: str, *, limit: int = 500) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    q_uid = str(quote_series_uid or "").strip()
    if not q_uid:
        return []
    lim = max(1, min(int(limit), 1000))
    init_quote_storage()
    with _PG_LOCK:
        with _connect_ctx() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT message_id, quote_series_uid, role, content, metadata_json, created_at
                    FROM quote_chat_messages
                    WHERE quote_series_uid = %s
                    ORDER BY created_at ASC, message_id ASC
                    LIMIT %s
                    """,
                    (q_uid, lim),
                )
                rows = cur.fetchall()
    return [_chat_message_dict_from_row(dict(row)) for row in rows]


def upsert_quote_chat_messages(
    quote_series_uid: str,
    messages: list[dict[str, Any]],
    *,
    sales_user_id: str | None = None,
    sales_user_name: str | None = None,
) -> int:
    q_uid = str(quote_series_uid or "").strip()
    if not q_uid or not isinstance(messages, list):
        return 0
    sid = str(sales_user_id or "").strip()
    if sid:
        bind_quote_sales_user(q_uid, sid, sales_user_name=sales_user_name)
    saved = 0
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        meta = raw.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
        for k in ("type", "msgId", "fileName", "quote_id", "subtype", "replyType"):
            if raw.get(k) is not None and k not in meta:
                meta[k] = raw.get(k)
        save_quote_chat_message(
            q_uid,
            str(raw.get("role") or "assistant"),
            str(raw.get("content") if raw.get("content") is not None else raw.get("text") or ""),
            message_id=str(raw.get("message_id") or raw.get("msgId") or "").strip() or None,
            metadata=meta,
            created_at=str(raw.get("created_at") or raw.get("time") or "").strip() or None,
        )
        saved += 1
    return saved
