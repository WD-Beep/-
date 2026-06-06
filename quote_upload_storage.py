"""报价持久化实现（当前：SQLite）。

PostgreSQL：见 ``quote_storage.backend``、``quote_storage/postgres_placeholder``。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sales_rep_fields import enrich_quote_sales_fields
from piece_area_table import attach_piece_area_calculation, enrich_quote_piece_area_on_read
from quote_storage.backend import (
    configured_quote_db_backend,
    ensure_quote_db_backend_supported,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "quotes.db"

_DB_LOCK = threading.Lock()
_SQLITE_TIMEOUT_SEC = 8.0
_DASHBOARD_CACHE_TTL_SEC = 5.0
_DASHBOARD_CACHE: tuple[float, dict[str, Any]] | None = None

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-()\u4e00-\u9fff]+")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=_SQLITE_TIMEOUT_SEC, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=8000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


def _invalidate_admin_cache() -> None:
    global _DASHBOARD_CACHE
    _DASHBOARD_CACHE = None


def admin_role_ok(headers: Any) -> bool:
    """从请求头读取 X-User-Role，admin 放行。"""
    if headers is None:
        return False
    try:
        role = headers.get("X-User-Role") or headers.get("x-user-role") or ""
    except Exception:
        role = ""
    return str(role).strip().lower() == "admin"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summarize_quote_result(quote_result: dict[str, Any]) -> tuple[str, str, float, float | None]:
    pn = str(quote_result.get("product_name") or "").strip()
    try:
        mt = float(quote_result.get("material_total") or 0.0)
    except (TypeError, ValueError):
        mt = 0.0
    tier1_cbm = None
    tiers = quote_result.get("tiers")
    if isinstance(tiers, list) and tiers and isinstance(tiers[0], dict):
        try:
            tier1_cbm = float(tiers[0].get("cost_before_margin") or tiers[0].get("total_cost") or 0.0)
        except (TypeError, ValueError):
            tier1_cbm = None
    return pn, "", mt, tier1_cbm


def _ensure_quote_files_columns(conn: sqlite3.Connection) -> None:
    """兼容旧库：补充 quote_uid / calc_quote_id / file_role / uploaded_by。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(quote_files)").fetchall()}
    if "quote_uid" not in cols:
        conn.execute("ALTER TABLE quote_files ADD COLUMN quote_uid TEXT")
    if "calc_quote_id" not in cols:
        conn.execute("ALTER TABLE quote_files ADD COLUMN calc_quote_id TEXT")
    if "file_role" not in cols:
        conn.execute("ALTER TABLE quote_files ADD COLUMN file_role TEXT DEFAULT 'sales_sheet'")
    if "uploaded_by" not in cols:
        conn.execute("ALTER TABLE quote_files ADD COLUMN uploaded_by TEXT")
    conn.execute(
        """
        UPDATE quote_files SET file_role = ?
        WHERE file_role = ?
        """,
        (FILE_ROLE_ADMIN_CORRECTED, FILE_ROLE_ADMIN_CORRECTION),
    )
    conn.execute(
        """
        UPDATE quote_files
        SET quote_uid = quote_id
        WHERE quote_uid IS NULL OR quote_uid = ''
        """
    )
    conn.execute(
        """
        UPDATE quote_files
        SET calc_quote_id = quote_id
        WHERE calc_quote_id IS NULL OR calc_quote_id = ''
        """
    )


def _ensure_quotes_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(quotes)").fetchall()}
    additions = {
        "approval_status": "TEXT NOT NULL DEFAULT 'pending'",
        "approved_version_no": "INTEGER",
        "approved_calc_quote_id": "TEXT",
        "approved_at": "TEXT",
        "approved_by": "TEXT",
        "approval_note": "TEXT",
        "sales_user_id": "TEXT",
        "sales_user_name": "TEXT",
        "admin_correction_note": "TEXT",
        "admin_correction_problem_types": "TEXT",
        "admin_correction_file_id": "TEXT",
        "admin_correction_at": "TEXT",
        "admin_correction_by": "TEXT",
        "admin_feedback_at": "TEXT",
        "admin_feedback_by": "TEXT",
        "admin_calculated_file_id": "TEXT",
        "admin_calculated_at": "TEXT",
        "admin_calculated_by": "TEXT",
        "admin_update_status": "TEXT",
        "admin_update_at": "TEXT",
        "admin_update_viewed_at": "TEXT",
        "admin_update_handled_at": "TEXT",
        "sales_hidden_at": "TEXT",
    }
    for name, ddl in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE quotes ADD COLUMN {name} {ddl}")


def init_quote_storage() -> None:
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        postgres_impl.init_quote_storage()
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
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
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quote_files_quote_id ON quote_files(quote_id)"
            )
            _ensure_quote_files_columns(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quote_files_quote_uid ON quote_files(quote_uid)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quote_files_uid_ver ON quote_files(quote_uid, version_no DESC)"
            )

            conn.execute(
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
                    material_total REAL,
                    tier1_cost_before_margin REAL,
                    approval_status TEXT NOT NULL DEFAULT 'pending',
                    approved_version_no INTEGER,
                    approved_calc_quote_id TEXT,
                    approved_at TEXT,
                    approved_by TEXT
                )
                """
            )
            _ensure_quotes_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quote_chat_messages (
                    message_id TEXT PRIMARY KEY,
                    quote_series_uid TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (quote_series_uid) REFERENCES quotes(quote_uid) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_qcm_series_time ON quote_chat_messages(quote_series_uid, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quotes_sales_user ON quotes(sales_user_id, updated_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quotes_latest_saved_at ON quotes(latest_saved_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quotes_product_name ON quotes(product_name)"
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quote_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quote_uid TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    calc_quote_id TEXT NOT NULL UNIQUE,
                    saved_at TEXT NOT NULL,
                    intent TEXT,
                    quote_json TEXT NOT NULL,
                    UNIQUE (quote_uid, version_no),
                    FOREIGN KEY (quote_uid) REFERENCES quotes(quote_uid)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quote_versions_uid ON quote_versions(quote_uid)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quote_versions_uid_ver_desc ON quote_versions(quote_uid, version_no DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quote_versions_saved_at ON quote_versions(saved_at DESC)"
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quote_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quote_uid TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    line_no INTEGER NOT NULL,
                    name TEXT,
                    spec TEXT,
                    usage TEXT,
                    unit_price TEXT,
                    amount REAL,
                    amount_text TEXT,
                    source TEXT,
                    calc_note TEXT,
                    kb_hit INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (quote_uid, version_no, line_no),
                    FOREIGN KEY (quote_uid) REFERENCES quotes(quote_uid)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quote_items_uid_ver ON quote_items(quote_uid, version_no)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quote_items_uid_ver_calc_note ON quote_items(quote_uid, version_no, calc_note)"
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_quotes (
                    quote_id TEXT PRIMARY KEY,
                    saved_at TEXT NOT NULL,
                    product_name TEXT,
                    sheet_original_name TEXT,
                    material_total REAL,
                    tier1_cost_before_margin REAL,
                    quote_json TEXT NOT NULL
                )
                """
            )

            conn.execute("PRAGMA foreign_keys=ON")

            from quote_correction_learning import ensure_correction_tables

            ensure_correction_tables(conn)
            conn.commit()

            _migrate_legacy_saved_quotes(conn)
            conn.commit()
        finally:
            conn.close()


def _migrate_legacy_saved_quotes(conn: sqlite3.Connection) -> None:
    """一次性：saved_quotes → quotes + quote_versions + quote_items。"""
    n_quotes = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
    if int(n_quotes or 0) > 0:
        return
    conn.row_factory = sqlite3.Row
    try:
        legacy_rows = conn.execute(
            "SELECT * FROM saved_quotes ORDER BY saved_at ASC"
        ).fetchall()
    except sqlite3.OperationalError:
        return
    if not legacy_rows:
        return
    for row in legacy_rows:
        uid = str(row["quote_id"] or "").strip()
        if not uid:
            continue
        saved_at = str(row["saved_at"] or _utc_now_iso())
        pn = str(row["product_name"] or "")
        sheet_nm = str(row["sheet_original_name"] or "")
        try:
            mt = float(row["material_total"] or 0.0)
        except (TypeError, ValueError):
            mt = 0.0
        tier1 = row["tier1_cost_before_margin"]
        raw_json = row["quote_json"] or "{}"
        conn.execute(
            """
            INSERT OR IGNORE INTO quotes (
                quote_uid, created_at, updated_at, latest_saved_at,
                product_name, sheet_original_name, latest_version_no,
                latest_calc_quote_id, material_total, tier1_cost_before_margin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                saved_at,
                saved_at,
                saved_at,
                pn,
                sheet_nm,
                1,
                uid,
                mt,
                tier1,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO quote_versions (
                quote_uid, version_no, calc_quote_id, saved_at, intent, quote_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uid, 1, uid, saved_at, None, raw_json),
        )
        try:
            obj = json.loads(raw_json)
        except json.JSONDecodeError:
            obj = {}
        rows_detail = obj.get("detail_rows") if isinstance(obj, dict) else None
        if isinstance(rows_detail, list):
            _insert_quote_items(conn, uid, 1, rows_detail)


def _insert_quote_items(
    conn: sqlite3.Connection,
    quote_uid: str,
    version_no: int,
    detail_rows: list[Any],
) -> None:
    conn.execute(
        "DELETE FROM quote_items WHERE quote_uid = ? AND version_no = ?",
        (quote_uid, version_no),
    )
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _detail_dict_from_quote_item(it: dict[str, Any]) -> dict[str, Any]:
    kb = it.get("kb_hit")
    return {
        "name": str(it.get("name") or ""),
        "spec": str(it.get("spec") or ""),
        "usage": str(it.get("usage") or ""),
        "unit_price": str(it.get("unit_price") or ""),
        "amount": it.get("amount"),
        "amount_text": str(it.get("amount_text") or ""),
        "source": str(it.get("source") or ""),
        "calc_note": str(it.get("calc_note") or ""),
        "kb_hit": bool(kb) if kb not in (None, "") else False,
        "accuracy_hints": [],
    }


def reconcile_admin_quote_detail_rows(
    quote_obj: dict[str, Any], items_db: list[dict[str, Any]]
) -> None:
    """读取后台 bundle 时：若 quote_json 中 detail_rows 短于 quote_items，用数据库行补齐（不写库）。"""
    if not isinstance(quote_obj, dict) or not items_db:
        return
    dr_in = quote_obj.get("detail_rows")
    dr = dr_in if isinstance(dr_in, list) else []
    imap: dict[int, dict[str, Any]] = {}
    for it in items_db:
        if not isinstance(it, dict):
            continue
        try:
            ln = int(it.get("line_no") or 0)
        except (TypeError, ValueError):
            continue
        if ln > 0:
            imap[ln] = it
    if not imap:
        return
    max_line = len(dr)
    for k in imap.keys():
        max_line = max(max_line, k)
    if max_line <= 0:
        return

    def _merge_row(r: dict[str, Any], db: dict[str, Any]) -> dict[str, Any]:
        merged = dict(r)
        for k in ("name", "spec", "usage", "unit_price", "amount_text", "source", "calc_note"):
            cur = merged.get(k)
            empty = cur is None or (isinstance(cur, str) and cur.strip() == "")
            dv = db.get(k)
            if empty and dv is not None and str(dv).strip() != "":
                merged[k] = dv
        if merged.get("amount") in (None, "") and db.get("amount") is not None:
            merged["amount"] = db["amount"]
        kb_m = merged.get("kb_hit")
        if kb_m is None or kb_m == "":
            merged["kb_hit"] = bool(db.get("kb_hit"))
        return merged

    out: list[dict[str, Any]] = []
    for line_no in range(1, max_line + 1):
        r = dr[line_no - 1] if line_no - 1 < len(dr) else None
        db = imap.get(line_no)
        if isinstance(r, dict) and db is not None:
            out.append(_merge_row(r, db))
        elif isinstance(r, dict):
            out.append(r)
        elif db is not None:
            out.append(_detail_dict_from_quote_item(db))
        else:
            out.append(
                {
                    "name": "-",
                    "spec": "",
                    "usage": "",
                    "unit_price": "",
                    "amount": None,
                    "amount_text": "",
                    "source": "",
                    "calc_note": "",
                    "kb_hit": False,
                    "accuracy_hints": [],
                }
            )

    quote_obj["detail_rows"] = out


def _next_file_version(conn: sqlite3.Connection, quote_uid: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_no), 0) + 1 FROM quote_files WHERE quote_uid = ? OR quote_id = ?",
        (quote_uid, quote_uid),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 1


def _sanitize_original_name(name: str) -> str:
    base = Path(str(name or "").strip()).name
    if not base or base in {".", ".."}:
        return "upload.bin"
    base = _SAFE_NAME_RE.sub("_", base)
    return base[:180] if len(base) > 180 else base


def persist_uploaded_sheet_for_quote(
    quote_uid: str,
    uploaded_sheet: dict[str, Any],
    *,
    calc_quote_id: str | None = None,
) -> dict[str, Any] | None:
    """解码 uploaded_sheet.content_base64，落盘并写入 quote_files。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.persist_uploaded_sheet_for_quote(
            quote_uid,
            uploaded_sheet,
            calc_quote_id=calc_quote_id,
        )
    if not isinstance(uploaded_sheet, dict):
        return None
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return None
    b64 = str(uploaded_sheet.get("content_base64") or "").strip()
    if not b64:
        return None
    original_name = _sanitize_original_name(str(uploaded_sheet.get("name") or ""))
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
    abs_path = ROOT / stored_rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(raw)

    try:
        from quote_sheet_images import persist_sheet_product_images

        persist_sheet_product_images(
            q_uid,
            FILE_ROLE_SALES_SHEET,
            raw,
            original_name=original_name,
        )
    except Exception:
        pass

    digest = hashlib.sha256(raw).hexdigest()
    mime_guess = mimetypes.guess_type(original_name)[0]
    mime_type = mime_guess or "application/octet-stream"
    uploaded_at = _utc_now_iso()

    calc_q = str(calc_quote_id or "").strip() or None

    with _DB_LOCK:
        conn = _connect()
        try:
            _ensure_quote_files_columns(conn)
            existing = conn.execute(
                """
                SELECT file_id, quote_id, quote_uid, calc_quote_id, version_no,
                       original_name, stored_path, mime_type, file_size,
                       file_hash_sha256, uploaded_at
                FROM quote_files
                WHERE quote_uid = ? AND calc_quote_id = ? AND file_hash_sha256 = ?
                LIMIT 1
                """,
                (q_uid, calc_q, digest),
            ).fetchone()
            if existing:
                try:
                    abs_path.unlink(missing_ok=True)
                except OSError:
                    pass
                keys = [
                    "file_id",
                    "quote_id",
                    "quote_uid",
                    "calc_quote_id",
                    "version_no",
                    "original_name",
                    "stored_path",
                    "mime_type",
                    "file_size",
                    "file_hash_sha256",
                    "uploaded_at",
                ]
                return dict(zip(keys, existing))
            ver = _next_file_version(conn, q_uid)
            conn.execute(
                """
                INSERT INTO quote_files (
                    file_id, quote_id, quote_uid, calc_quote_id, version_no,
                    original_name, stored_path, mime_type, file_size,
                    file_hash_sha256, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        finally:
            conn.close()

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
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.list_quote_files_for_quote(quote_uid)
    init_quote_storage()
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return []
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            _ensure_quote_files_columns(conn)
            rows = conn.execute(
                """
                SELECT file_id, quote_id, quote_uid, calc_quote_id, version_no,
                       original_name, stored_path, mime_type, file_size,
                       file_hash_sha256, uploaded_at, file_role, uploaded_by
                FROM quote_files
                WHERE quote_uid = ? OR quote_id = ?
                ORDER BY version_no ASC, uploaded_at ASC
                """,
                (q_uid, q_uid),
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def get_quote_file_record(file_id: str) -> dict[str, Any] | None:
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.get_quote_file_record(file_id)
    init_quote_storage()
    fid = str(file_id or "").strip()
    if not fid:
        return None
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            _ensure_quote_files_columns(conn)
            row = conn.execute(
                """
                SELECT file_id, quote_id, quote_uid, calc_quote_id, version_no,
                       original_name, stored_path, mime_type, file_size,
                       file_hash_sha256, uploaded_at, file_role, uploaded_by
                FROM quote_files WHERE file_id = ?
                """,
                (fid,),
            ).fetchone()
        finally:
            conn.close()
    return dict(row) if row else None


ADMIN_CORRECTION_SHEET_MAX_BYTES = 15 * 1024 * 1024
ADMIN_ATTACHMENT_MAX_BYTES = 100 * 1024 * 1024
ADMIN_CORRECTION_SHEET_SUFFIXES = {".xlsx", ".xls", ".csv"}
ADMIN_CALCULATED_ATTACHMENT_SUFFIXES = {
    ".xlsx",
    ".xls",
    ".csv",
    ".pdf",
    ".doc",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
    ".zip",
    ".rar",
}
ADMIN_ATTACHMENT_BLOCKED_SUFFIXES = {
    ".exe",
    ".bat",
    ".cmd",
    ".ps1",
    ".js",
    ".vbs",
    ".msi",
    ".scr",
    ".dll",
    ".com",
    ".jar",
    ".sh",
}
FILE_ROLE_SALES_SHEET = "sales_sheet"
FILE_ROLE_ADMIN_CORRECTION = "admin_correction"  # 历史别名，读写时归一化为 admin_corrected
FILE_ROLE_ADMIN_CORRECTED = "admin_corrected"
FILE_ROLE_ADMIN_CALCULATED = "admin_calculated"
ADMIN_SHEET_KIND_CORRECTED = "admin_corrected"
ADMIN_SHEET_KIND_CALCULATED = "admin_calculated"
ADMIN_UPDATE_STATUS_PENDING = "pending_view"
ADMIN_UPDATE_STATUS_VIEWED = "viewed"

_ADMIN_SHEET_KIND_CONFIG: dict[str, dict[str, Any]] = {
    ADMIN_SHEET_KIND_CORRECTED: {
        "file_role": FILE_ROLE_ADMIN_CORRECTED,
        "legacy_roles": (FILE_ROLE_ADMIN_CORRECTION,),
        "file_id_col": "admin_correction_file_id",
        "at_col": "admin_correction_at",
        "by_col": "admin_correction_by",
        "no_sheet_error": "no_correction_sheet",
        "label": "管理员修正版表格",
    },
    ADMIN_SHEET_KIND_CALCULATED: {
        "file_role": FILE_ROLE_ADMIN_CALCULATED,
        "legacy_roles": (),
        "file_id_col": "admin_calculated_file_id",
        "at_col": "admin_calculated_at",
        "by_col": "admin_calculated_by",
        "no_sheet_error": "no_calculated_sheet",
        "label": "管理员自算表格",
    },
}

# Postgres 分支与外部模块共用同一配置表（勿在运行时修改）
ADMIN_SHEET_KIND_CONFIG = _ADMIN_SHEET_KIND_CONFIG


def _normalize_file_role(raw: Any) -> str:
    role = str(raw or FILE_ROLE_SALES_SHEET).strip().lower()
    if role in (FILE_ROLE_ADMIN_CORRECTION, FILE_ROLE_ADMIN_CORRECTED):
        return FILE_ROLE_ADMIN_CORRECTED
    if role == FILE_ROLE_ADMIN_CALCULATED:
        return FILE_ROLE_ADMIN_CALCULATED
    return FILE_ROLE_SALES_SHEET


def _admin_sheet_roles_for_kind(sheet_kind: str) -> tuple[str, ...]:
    cfg = _ADMIN_SHEET_KIND_CONFIG.get(sheet_kind)
    if not cfg:
        raise ValueError("invalid_sheet_kind")
    roles = (str(cfg["file_role"]),)
    legacy = cfg.get("legacy_roles") or ()
    return roles + tuple(str(r) for r in legacy if r)


def categorize_quote_files(files: list[dict[str, Any]]) -> dict[str, Any]:
    sales: list[dict[str, Any]] = []
    admin_corrected: dict[str, Any] | None = None
    admin_calculated: dict[str, Any] | None = None
    for row in files or []:
        if not isinstance(row, dict):
            continue
        role = _normalize_file_role(row.get("file_role"))
        if role == FILE_ROLE_ADMIN_CORRECTED:
            admin_corrected = row
        elif role == FILE_ROLE_ADMIN_CALCULATED:
            admin_calculated = row
        else:
            sales.append(row)
    return {
        "sales": sales,
        "admin_corrected": admin_corrected,
        "admin_calculated": admin_calculated,
    }


def _attachment_suffix(name: str) -> str:
    return Path(str(name or "").strip()).suffix.lower()


def _is_blocked_admin_attachment_name(name: str) -> bool:
    return _attachment_suffix(name) in ADMIN_ATTACHMENT_BLOCKED_SUFFIXES


def _is_allowed_correction_sheet_name(name: str) -> bool:
    suffix = _attachment_suffix(name)
    return suffix in ADMIN_CORRECTION_SHEET_SUFFIXES


def _is_allowed_admin_calculated_attachment_name(name: str) -> bool:
    if _is_blocked_admin_attachment_name(name):
        return False
    return _attachment_suffix(name) in ADMIN_CALCULATED_ATTACHMENT_SUFFIXES


def split_quote_files_by_role(files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    cat = categorize_quote_files(files)
    return cat["sales"], cat["admin_corrected"]


def _admin_sheet_public(
    file_rec: dict[str, Any] | None,
    meta: dict[str, Any],
    *,
    fid_key: str,
    at_key: str,
    by_key: str,
    sheet_type: str,
    type_label: str,
) -> dict[str, Any] | None:
    m = meta if isinstance(meta, dict) else {}
    rec = file_rec if isinstance(file_rec, dict) else None
    fid = str((rec or {}).get("file_id") or m.get(fid_key) or "").strip()
    if not fid:
        return None
    role = _normalize_file_role((rec or {}).get("file_role"))
    if rec and role not in (FILE_ROLE_ADMIN_CORRECTED, FILE_ROLE_ADMIN_CALCULATED):
        return None
    return {
        "file_id": fid,
        "original_name": str((rec or {}).get("original_name") or ""),
        "uploaded_at": str((rec or {}).get("uploaded_at") or m.get(at_key) or ""),
        "uploaded_by": str((rec or {}).get("uploaded_by") or m.get(by_key) or ""),
        "sheet_type": sheet_type,
        "type_label": type_label,
    }


def _amount_text_from_quote_obj(quote_obj: dict[str, Any]) -> str:
    if not isinstance(quote_obj, dict):
        return "-"
    tiers = quote_obj.get("tiers")
    if isinstance(tiers, list) and tiers:
        t0 = tiers[0] if isinstance(tiers[0], dict) else {}
        for key in ("cost_before_margin", "total_cost"):
            try:
                val = float(t0.get(key))
            except (TypeError, ValueError):
                continue
            if val > 0:
                return f"¥{val:.2f}"
    try:
        mt = float(quote_obj.get("material_total") or 0.0)
    except (TypeError, ValueError):
        mt = 0.0
    return f"¥{mt:.2f}" if mt > 0 else "-"


def _quote_version_amount_text(conn: sqlite3.Connection, quote_uid: str, version_no: int) -> str:
    row = conn.execute(
        """
        SELECT quote_json FROM quote_versions
        WHERE quote_uid = ? AND version_no = ?
        LIMIT 1
        """,
        (quote_uid, int(version_no)),
    ).fetchone()
    if not row:
        return "-"
    try:
        raw_json = row[0] if not isinstance(row, sqlite3.Row) else row["quote_json"]
        quote_obj = json.loads(raw_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return "-"
    return _amount_text_from_quote_obj(quote_obj if isinstance(quote_obj, dict) else {})


def _format_amount_delta_text(original_text: str, corrected_text: str) -> str:
    def _parse(raw: str) -> float | None:
        s = str(raw or "").strip().replace("¥", "").replace(",", "")
        if not s or s == "-":
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    orig = _parse(original_text)
    corr = _parse(corrected_text)
    if orig is None or corr is None:
        return "-"
    delta = corr - orig
    sign = "+" if delta > 0 else ""
    return f"{sign}¥{delta:.2f}"


def _admin_update_has_activity(meta: dict[str, Any]) -> bool:
    m = meta if isinstance(meta, dict) else {}
    latest_ver = int(m.get("latest_version_no") or 0)
    if latest_ver > 1:
        return True
    if str(m.get("admin_update_status") or "").strip().lower() == ADMIN_UPDATE_STATUS_PENDING:
        return True
    approval_status = str(m.get("approval_status") or "").strip().lower()
    if approval_status in ("approved", "rejected") and str(m.get("approved_at") or "").strip():
        return True
    for key in (
        "admin_update_at",
        "admin_feedback_at",
        "admin_calculated_file_id",
        "admin_correction_file_id",
        "admin_correction_note",
    ):
        if str(m.get(key) or "").strip():
            return True
    return False


def _load_quote_version_object(conn: sqlite3.Connection, quote_uid: str, version_no: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT quote_json FROM quote_versions
        WHERE quote_uid = ? AND version_no = ?
        LIMIT 1
        """,
        (quote_uid, int(version_no)),
    ).fetchone()
    if not row:
        return None
    try:
        raw_json = row[0] if not isinstance(row, sqlite3.Row) else row["quote_json"]
        obj = json.loads(raw_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _build_admin_feedback_extras(meta: dict[str, Any], files: list[dict[str, Any]] | None) -> dict[str, Any]:
    from admin_correction_inbox import (
        ADMIN_UPDATE_STATUS_HANDLED,
        admin_update_status_label_cn,
        build_correction_types,
        compute_bom_diff_summary,
        correction_types_label_cn,
        extract_detail_rows_from_quote,
    )

    m = meta if isinstance(meta, dict) else {}
    q_uid = str(m.get("quote_uid") or "").strip()
    cat = categorize_quote_files(list(files or []))
    latest_ver = int(m.get("latest_version_no") or 0)
    has_visual_correction = latest_ver > 1
    note = str(m.get("admin_correction_note") or "").strip()
    has_calculated = bool(cat.get("admin_calculated") or m.get("admin_calculated_file_id"))
    has_corrected_sheet = bool(cat.get("admin_corrected") or m.get("admin_correction_file_id"))
    approval_status = str(m.get("approval_status") or "").strip().lower()
    correction_types = build_correction_types(
        has_visual_correction=has_visual_correction,
        has_calculated_sheet=has_calculated,
        has_correction_note=bool(note),
        has_corrected_sheet=has_corrected_sheet,
        approval_status=approval_status,
    )
    update_status = str(m.get("admin_update_status") or "").strip().lower()
    handled_at = str(m.get("admin_update_handled_at") or "").strip()
    extras: dict[str, Any] = {
        "admin_update_handled_at": handled_at,
        "status_label_cn": admin_update_status_label_cn(update_status),
        "correction_types": correction_types,
        "correction_types_label": correction_types_label_cn(correction_types),
        "bom_diff": {"added": [], "removed": [], "changed": [], "lines": [], "has_changes": False},
        "original_quote_result": None,
        "admin_corrected_quote_result": None,
    }
    if not q_uid or not has_visual_correction:
        return extras
    orig_obj: dict[str, Any] | None = None
    corr_obj: dict[str, Any] | None = None
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        orig_obj = postgres_impl.load_quote_version_object(q_uid, 1)
        corr_obj = postgres_impl.load_quote_version_object(q_uid, latest_ver)
    else:
        init_quote_storage()
        with _DB_LOCK:
            conn = _connect()
            try:
                orig_obj = _load_quote_version_object(conn, q_uid, 1)
                corr_obj = _load_quote_version_object(conn, q_uid, latest_ver)
            finally:
                conn.close()
    if isinstance(orig_obj, dict):
        extras["original_quote_result"] = orig_obj
    if isinstance(corr_obj, dict):
        extras["admin_corrected_quote_result"] = corr_obj
    if isinstance(orig_obj, dict) and isinstance(corr_obj, dict):
        extras["bom_diff"] = compute_bom_diff_summary(
            extract_detail_rows_from_quote(orig_obj),
            extract_detail_rows_from_quote(corr_obj),
        )
    return extras


def build_admin_feedback_public(meta: dict[str, Any], files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """业务员可见的管理员修正反馈摘要。"""
    from admin_correction_inbox import (
        correction_problem_types_label_cn,
        normalize_correction_problem_types,
    )

    m = meta if isinstance(meta, dict) else {}
    q_uid = str(m.get("quote_uid") or "").strip()
    note = str(m.get("admin_correction_note") or "").strip()
    feedback_at = str(m.get("admin_feedback_at") or "").strip()
    feedback_by = str(m.get("admin_feedback_by") or "").strip()
    has_feedback = bool(feedback_at)
    cat = categorize_quote_files(list(files or []))
    admin_corrected = cat["admin_corrected"]
    admin_calculated = cat["admin_calculated"]
    corr_fid = str(m.get("admin_correction_file_id") or "").strip()
    if not admin_corrected and corr_fid:
        admin_corrected = next((f for f in (files or []) if str(f.get("file_id") or "") == corr_fid), None)
    calc_fid = str(m.get("admin_calculated_file_id") or "").strip()
    if not admin_calculated and calc_fid:
        admin_calculated = next((f for f in (files or []) if str(f.get("file_id") or "") == calc_fid), None)
    corrected_sheet = _admin_sheet_public(
        admin_corrected,
        m,
        fid_key="admin_correction_file_id",
        at_key="admin_correction_at",
        by_key="admin_correction_by",
        sheet_type=ADMIN_SHEET_KIND_CORRECTED,
        type_label="管理员修正版表格",
    )
    calculated_sheet = _admin_sheet_public(
        admin_calculated,
        m,
        fid_key="admin_calculated_file_id",
        at_key="admin_calculated_at",
        by_key="admin_calculated_by",
        sheet_type=ADMIN_SHEET_KIND_CALCULATED,
        type_label="管理员自算表格",
    )
    update_status = str(m.get("admin_update_status") or "").strip().lower()
    update_at = str(m.get("admin_update_at") or "").strip()
    update_viewed_at = str(m.get("admin_update_viewed_at") or "").strip()
    has_admin_update = update_status == ADMIN_UPDATE_STATUS_PENDING
    has_admin_sheets = bool(corrected_sheet or calculated_sheet)
    latest_ver = int(m.get("latest_version_no") or 0)
    has_visual_correction = latest_ver > 1
    approval_status = str(m.get("approval_status") or "pending").strip().lower()
    approval_note = str(m.get("approval_note") or "").strip()
    approved_at = str(m.get("approved_at") or "").strip()
    approved_by = str(m.get("approved_by") or "").strip()
    rejection_reason = approval_note if approval_status == "rejected" else ""
    display_note = note or rejection_reason
    has_admin_correction = (
        has_feedback
        or has_visual_correction
        or approval_status in ("approved", "rejected")
    )
    corrected_amount_text = _latest_amount_text_from_quote_row(m)
    original_amount_text = corrected_amount_text
    amount_delta_text = "-"
    if has_visual_correction and q_uid:
        init_quote_storage()
        with _DB_LOCK:
            conn = _connect()
            try:
                original_amount_text = _quote_version_amount_text(conn, q_uid, 1)
            finally:
                conn.close()
        amount_delta_text = _format_amount_delta_text(original_amount_text, corrected_amount_text)
    sales_original_sheet = None
    sales_files = cat.get("sales") or []
    if sales_files:
        sf = sales_files[0]
        fid = str(sf.get("file_id") or "").strip()
        if fid:
            sales_original_sheet = {
                "file_id": fid,
                "original_name": str(sf.get("original_name") or ""),
                "uploaded_at": str(sf.get("uploaded_at") or ""),
                "sheet_type": FILE_ROLE_SALES_SHEET,
                "type_label": "原始表格",
            }
    return {
        "has_feedback": has_feedback,
        "has_admin_correction": has_admin_correction,
        "has_visual_correction": has_visual_correction,
        "correction_note": display_note,
        "admin_correction_note": note,
        "approval_status": approval_status,
        "approval_note": approval_note,
        "approved_at": approved_at,
        "approved_by": approved_by,
        "rejection_reason": rejection_reason,
        "correction_problem_types": normalize_correction_problem_types(m.get("admin_correction_problem_types")),
        "correction_problem_types_label": correction_problem_types_label_cn(
            normalize_correction_problem_types(m.get("admin_correction_problem_types"))
        ),
        "feedback_at": feedback_at,
        "feedback_by": feedback_by,
        "corrected_amount_text": corrected_amount_text,
        "original_amount_text": original_amount_text,
        "amount_delta_text": amount_delta_text,
        "corrected_sheet": corrected_sheet,
        "calculated_sheet": calculated_sheet,
        "correction_sheet": corrected_sheet,
        "sales_original_sheet": sales_original_sheet,
        "has_admin_update": has_admin_update,
        "admin_update_status": update_status,
        "admin_update_at": update_at,
        "admin_update_viewed_at": update_viewed_at,
        "has_admin_sheets": has_admin_sheets,
        "sales_view_status": update_status or (ADMIN_UPDATE_STATUS_VIEWED if update_viewed_at else ""),
        **_build_admin_feedback_extras(m, files),
    }


def save_admin_quote_feedback(
    quote_uid: str,
    *,
    correction_note: str | None = None,
    correction_problem_types: list[str] | str | None = None,
    reviewed_by: str = "admin",
    notify_sales: bool = True,
) -> dict[str, Any]:
    """保存管理员修正说明并标记已反馈业务员。"""
    from admin_correction_inbox import normalize_correction_problem_types

    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.save_admin_quote_feedback(
            quote_uid,
            correction_note=correction_note,
            correction_problem_types=correction_problem_types,
            reviewed_by=reviewed_by,
            notify_sales=notify_sales,
        )
    q_uid = str(quote_uid or "").strip()
    actor = str(reviewed_by or "admin").strip() or "admin"
    if not q_uid:
        raise ValueError("quote_uid 不能为空")
    note = str(correction_note or "").strip()
    problem_types = normalize_correction_problem_types(correction_problem_types)
    problem_types_json = json.dumps(problem_types, ensure_ascii=False) if problem_types else ""
    now = _utc_now_iso()
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            _ensure_quotes_columns(conn)
            row = conn.execute(
                "SELECT quote_uid FROM quotes WHERE quote_uid = ? LIMIT 1",
                (q_uid,),
            ).fetchone()
            if not row:
                raise ValueError("not_found")
            conn.execute(
                """
                UPDATE quotes SET
                    admin_correction_note = ?,
                    admin_correction_problem_types = ?,
                    admin_feedback_at = ?,
                    admin_feedback_by = ?,
                    updated_at = ?
                WHERE quote_uid = ?
                """,
                (note, problem_types_json, now, actor, now, q_uid),
            )
            _mark_admin_update_pending(conn, q_uid, now=now)
            conn.commit()
            meta = dict(
                conn.execute("SELECT * FROM quotes WHERE quote_uid = ?", (q_uid,)).fetchone()
            )
        finally:
            conn.close()
    if notify_sales:
        _record_admin_correction_chat_notification(q_uid, note, actor, now)
    files = list_quote_files_for_quote(q_uid)
    return {
        "ok": True,
        "quote_uid": q_uid,
        "admin_feedback": build_admin_feedback_public(meta, files),
    }


def _mark_admin_update_pending(conn: sqlite3.Connection, q_uid: str, *, now: str | None = None) -> None:
    ts = now or _utc_now_iso()
    _ensure_quotes_columns(conn)
    conn.execute(
        """
        UPDATE quotes SET
            admin_update_status = ?,
            admin_update_at = ?,
            admin_update_viewed_at = NULL,
            admin_update_handled_at = NULL,
            updated_at = ?
        WHERE quote_uid = ?
        """,
        (ADMIN_UPDATE_STATUS_PENDING, ts, ts, q_uid),
    )


def mark_admin_visual_correction_pending(
    quote_uid: str,
    actor: str = "admin",
    *,
    now: str | None = None,
) -> None:
    """管理员可视化 BOM 修正保存后，标记业务员待查看（不影响普通业务员报价保存）。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        postgres_impl.mark_admin_visual_correction_pending(quote_uid, actor, now=now)
        return
    q_uid = str(quote_uid or "").strip()
    act = str(actor or "admin").strip() or "admin"
    if not q_uid:
        raise ValueError("quote_uid 不能为空")
    ts = now or _utc_now_iso()
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        try:
            _ensure_quotes_columns(conn)
            row = conn.execute(
                "SELECT quote_uid FROM quotes WHERE quote_uid = ? LIMIT 1",
                (q_uid,),
            ).fetchone()
            if not row:
                raise ValueError("not_found")
            conn.execute(
                """
                UPDATE quotes SET
                    admin_update_status = ?,
                    admin_update_at = ?,
                    admin_update_viewed_at = NULL,
                    admin_update_handled_at = NULL,
                    admin_feedback_at = ?,
                    admin_feedback_by = ?,
                    updated_at = ?
                WHERE quote_uid = ?
                """,
                (ADMIN_UPDATE_STATUS_PENDING, ts, ts, act, ts, q_uid),
            )
            conn.commit()
        finally:
            conn.close()


def _record_admin_sheet_upload_notification(
    quote_uid: str,
    sheet_kind: str,
    *,
    original_name: str,
    actor: str,
    at: str,
) -> None:
    cfg = _ADMIN_SHEET_KIND_CONFIG.get(sheet_kind) or {}
    label = str(cfg.get("label") or "管理员表格")
    content = f"管理员已上传{label}：{original_name or '表格文件'}，请查看。"
    save_quote_chat_message(
        quote_uid,
        "admin",
        content,
        metadata={
            "type": "admin_sheet_upload_notice",
            "sheet_kind": sheet_kind,
            "sheet_label": label,
            "original_name": original_name,
            "uploaded_by": actor,
            "uploaded_at": at,
        },
    )


def _decode_admin_upload_sheet(
    uploaded_sheet: dict[str, Any],
    *,
    sheet_kind: str,
) -> tuple[str, bytes]:
    if not isinstance(uploaded_sheet, dict):
        raise ValueError("缺少 uploaded_sheet 数据")
    b64 = str(uploaded_sheet.get("content_base64") or "").strip()
    if not b64:
        raise ValueError("缺少文件内容 content_base64")
    original_name = _sanitize_original_name(str(uploaded_sheet.get("name") or ""))
    if not original_name:
        raise ValueError("缺少文件名")
    if _is_blocked_admin_attachment_name(original_name):
        raise ValueError("不允许上传可执行或脚本类文件")
    if sheet_kind == ADMIN_SHEET_KIND_CALCULATED:
        if not _is_allowed_admin_calculated_attachment_name(original_name):
            raise ValueError(
                "仅支持 xlsx、xls、csv、pdf、doc、docx、png、jpg、jpeg、zip、rar 等附件格式"
            )
    elif not _is_allowed_correction_sheet_name(original_name):
        raise ValueError("仅支持 xlsx、xls、csv 表格文件")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("文件内容无效") from exc
    if not raw:
        raise ValueError("文件内容为空")
    if len(raw) > ADMIN_ATTACHMENT_MAX_BYTES:
        raise ValueError(f"文件大小不能超过 {ADMIN_ATTACHMENT_MAX_BYTES // (1024 * 1024)}MB")
    return original_name, raw


def _persist_admin_typed_sheet_sqlite(
    quote_uid: str,
    uploaded_sheet: dict[str, Any],
    *,
    sheet_kind: str,
    uploaded_by: str = "admin",
    replace_confirmed: bool = False,
) -> dict[str, Any]:
    cfg = _ADMIN_SHEET_KIND_CONFIG.get(sheet_kind)
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
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            _ensure_quote_files_columns(conn)
            _ensure_quotes_columns(conn)
            qrow = conn.execute(
                f"SELECT quote_uid, {file_id_col} AS prev_file_id FROM quotes WHERE quote_uid = ? LIMIT 1",
                (q_uid,),
            ).fetchone()
            if not qrow:
                raise ValueError("not_found")
            prev_fid = str(qrow["prev_file_id"] or "").strip()
            if prev_fid and not replace_confirmed:
                raise ValueError("replace_confirm_required")
            if prev_fid:
                prev = conn.execute(
                    "SELECT stored_path FROM quote_files WHERE file_id = ? LIMIT 1",
                    (prev_fid,),
                ).fetchone()
                conn.execute("DELETE FROM quote_files WHERE file_id = ?", (prev_fid,))
                if prev:
                    old_path = resolve_stored_file_path(str(prev["stored_path"] or ""))
                    if old_path:
                        try:
                            old_path.unlink(missing_ok=True)
                        except OSError:
                            pass
            conn.commit()
        finally:
            conn.close()

    file_id = uuid.uuid4().hex
    ext = Path(original_name).suffix if len(Path(original_name).suffix) <= 12 else ""
    stored_rel = Path("data") / "uploads" / f"{file_id}{ext}"
    abs_path = ROOT / stored_rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(raw)

    if original_name.lower().endswith(".xlsx") and sheet_kind in (
        ADMIN_SHEET_KIND_CORRECTED,
        ADMIN_SHEET_KIND_CALCULATED,
    ):
        try:
            from quote_sheet_images import persist_sheet_product_images

            img_role = (
                FILE_ROLE_ADMIN_CORRECTED
                if sheet_kind == ADMIN_SHEET_KIND_CORRECTED
                else FILE_ROLE_ADMIN_CALCULATED
            )
            persist_sheet_product_images(
                q_uid,
                img_role,
                raw,
                original_name=original_name,
            )
        except Exception:
            pass

    digest = hashlib.sha256(raw).hexdigest()
    mime_guess = mimetypes.guess_type(original_name)[0]
    mime_type = mime_guess or "application/octet-stream"
    uploaded_at = _utc_now_iso()

    with _DB_LOCK:
        conn = _connect()
        try:
            _ensure_quote_files_columns(conn)
            _ensure_quotes_columns(conn)
            ver = _next_file_version(conn, q_uid)
            conn.execute(
                """
                INSERT INTO quote_files (
                    file_id, quote_id, quote_uid, calc_quote_id, version_no,
                    original_name, stored_path, mime_type, file_size,
                    file_hash_sha256, uploaded_at, file_role, uploaded_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    {file_id_col} = ?,
                    {at_col} = ?,
                    {by_col} = ?,
                    updated_at = ?
                WHERE quote_uid = ?
                """,
                (file_id, uploaded_at, actor, uploaded_at, q_uid),
            )
            _mark_admin_update_pending(conn, q_uid, now=uploaded_at)
            conn.commit()
        finally:
            conn.close()

    _record_admin_sheet_upload_notification(
        q_uid,
        sheet_kind,
        original_name=original_name,
        actor=actor,
        at=uploaded_at,
    )
    rec = {
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
    }
    return {"ok": True, "quote_uid": q_uid, "file": rec, "sheet_kind": sheet_kind}


def persist_admin_correction_sheet(
    quote_uid: str,
    uploaded_sheet: dict[str, Any],
    *,
    uploaded_by: str = "admin",
    replace_confirmed: bool = False,
) -> dict[str, Any]:
    """上传管理员修正版表格（不解析 BOM，仅作附件）。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.persist_admin_correction_sheet(
            quote_uid,
            uploaded_sheet,
            uploaded_by=uploaded_by,
            replace_confirmed=replace_confirmed,
        )
    return _persist_admin_typed_sheet_sqlite(
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
    """上传管理员自算表格（不解析 BOM，仅作附件）。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.persist_admin_calculated_sheet(
            quote_uid,
            uploaded_sheet,
            uploaded_by=uploaded_by,
            replace_confirmed=replace_confirmed,
        )
    return _persist_admin_typed_sheet_sqlite(
        quote_uid,
        uploaded_sheet,
        sheet_kind=ADMIN_SHEET_KIND_CALCULATED,
        uploaded_by=uploaded_by,
        replace_confirmed=replace_confirmed,
    )


def _purge_admin_sheet_files(
    conn: sqlite3.Connection,
    q_uid: str,
    sheet_kind: str,
    *,
    known_fid: str = "",
) -> int:
    _ensure_quote_files_columns(conn)
    roles = _admin_sheet_roles_for_kind(sheet_kind)
    targets: dict[str, str] = {}
    if known_fid:
        row = conn.execute(
            "SELECT file_id, stored_path FROM quote_files WHERE file_id = ? AND quote_uid = ? LIMIT 1",
            (known_fid, q_uid),
        ).fetchone()
        if row:
            targets[str(row["file_id"])] = str(row["stored_path"] or "")
    placeholders = ",".join("?" for _ in roles)
    rows = conn.execute(
        f"""
        SELECT file_id, stored_path FROM quote_files
        WHERE quote_uid = ? AND file_role IN ({placeholders})
        """,
        (q_uid, *roles),
    ).fetchall()
    for row in rows:
        targets[str(row["file_id"])] = str(row["stored_path"] or "")
    removed = 0
    for fid, stored_path in targets.items():
        fs_path = resolve_stored_file_path(stored_path)
        if fs_path:
            try:
                fs_path.unlink(missing_ok=True)
            except OSError:
                pass
        conn.execute("DELETE FROM quote_files WHERE file_id = ?", (fid,))
        removed += 1
    return removed


def _delete_admin_typed_sheet_sqlite(
    quote_uid: str,
    *,
    sheet_kind: str,
    deleted_by: str = "admin",
) -> dict[str, Any]:
    cfg = _ADMIN_SHEET_KIND_CONFIG.get(sheet_kind)
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
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            _ensure_quotes_columns(conn)
            qrow = conn.execute(
                f"SELECT quote_uid, {file_id_col} AS prev_file_id FROM quotes WHERE quote_uid = ? LIMIT 1",
                (q_uid,),
            ).fetchone()
            if not qrow:
                raise ValueError("not_found")
            prev_fid = str(qrow["prev_file_id"] or "").strip()
            if not prev_fid:
                roles = _admin_sheet_roles_for_kind(sheet_kind)
                placeholders = ",".join("?" for _ in roles)
                orphan = conn.execute(
                    f"""
                    SELECT file_id FROM quote_files
                    WHERE quote_uid = ? AND file_role IN ({placeholders})
                    LIMIT 1
                    """,
                    (q_uid, *roles),
                ).fetchone()
                if not orphan:
                    raise ValueError(no_sheet_error)
            removed = _purge_admin_sheet_files(conn, q_uid, sheet_kind, known_fid=prev_fid)
            if removed <= 0 and not prev_fid:
                raise ValueError(no_sheet_error)
            now = _utc_now_iso()
            conn.execute(
                f"""
                UPDATE quotes SET
                    {file_id_col} = NULL,
                    {at_col} = NULL,
                    {by_col} = NULL,
                    updated_at = ?
                WHERE quote_uid = ?
                """,
                (now, q_uid),
            )
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "quote_uid": q_uid, "deleted": True, "sheet_kind": sheet_kind}


def delete_admin_sheet_by_kind(
    quote_uid: str,
    *,
    sheet_kind: str,
    deleted_by: str = "admin",
) -> dict[str, Any]:
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.delete_admin_sheet_by_kind(
            quote_uid,
            sheet_kind=sheet_kind,
            deleted_by=deleted_by,
        )
    return _delete_admin_typed_sheet_sqlite(quote_uid, sheet_kind=sheet_kind, deleted_by=deleted_by)


def _purge_admin_correction_files(conn: sqlite3.Connection, q_uid: str, *, known_fid: str = "") -> int:
    """删除 quote 关联的管理员修正版表格文件（DB + 磁盘），返回删除条数。"""
    return _purge_admin_sheet_files(conn, q_uid, ADMIN_SHEET_KIND_CORRECTED, known_fid=known_fid)


def delete_admin_correction_sheet(
    quote_uid: str,
    *,
    deleted_by: str = "admin",
) -> dict[str, Any]:
    """删除当前报价的管理员修正版表格（不影响业务员原始表格）。"""
    return delete_admin_sheet_by_kind(
        quote_uid,
        sheet_kind=ADMIN_SHEET_KIND_CORRECTED,
        deleted_by=deleted_by,
    )


def delete_admin_calculated_sheet(
    quote_uid: str,
    *,
    deleted_by: str = "admin",
) -> dict[str, Any]:
    """删除当前报价的管理员自算表格（不影响业务员原始表格）。"""
    return delete_admin_sheet_by_kind(
        quote_uid,
        sheet_kind=ADMIN_SHEET_KIND_CALCULATED,
        deleted_by=deleted_by,
    )


def get_admin_sheet_for_sales(
    quote_series_uid: str,
    sales_user_id: str,
    *,
    sheet_kind: str,
) -> dict[str, Any] | None:
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.get_admin_sheet_for_sales(
            quote_series_uid,
            sales_user_id,
            sheet_kind=sheet_kind,
        )
    cfg = _ADMIN_SHEET_KIND_CONFIG.get(sheet_kind)
    if not cfg:
        return None
    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid or not sales_user_can_access_quote(q_uid, sid):
        return None
    file_id_col = str(cfg["file_id_col"])
    expected_role = str(cfg["file_role"])
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            _ensure_quotes_columns(conn)
            row = conn.execute(
                f"SELECT {file_id_col} AS file_id FROM quotes WHERE quote_uid = ? LIMIT 1",
                (q_uid,),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    fid = str(row["file_id"] or "").strip()
    if not fid:
        return None
    rec = get_quote_file_record(fid)
    if not rec or _normalize_file_role(rec.get("file_role")) != expected_role:
        return None
    return rec


def get_admin_correction_sheet_for_sales(
    quote_series_uid: str,
    sales_user_id: str,
) -> dict[str, Any] | None:
    return get_admin_sheet_for_sales(
        quote_series_uid,
        sales_user_id,
        sheet_kind=ADMIN_SHEET_KIND_CORRECTED,
    )


def get_admin_calculated_sheet_for_sales(
    quote_series_uid: str,
    sales_user_id: str,
) -> dict[str, Any] | None:
    return get_admin_sheet_for_sales(
        quote_series_uid,
        sales_user_id,
        sheet_kind=ADMIN_SHEET_KIND_CALCULATED,
    )


def get_sales_original_sheet_for_sales(
    quote_series_uid: str,
    sales_user_id: str,
) -> dict[str, Any] | None:
    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid or not sales_user_can_access_quote(q_uid, sid):
        return None
    files = list_quote_files_for_quote(q_uid)
    sales_files = categorize_quote_files(files).get("sales") or []
    if not sales_files:
        return None
    rec = sales_files[0]
    fid = str(rec.get("file_id") or "").strip()
    if not fid:
        return None
    stored = get_quote_file_record(fid)
    return stored if isinstance(stored, dict) else rec


def mark_sales_admin_update_viewed(
    quote_series_uid: str,
    sales_user_id: str,
) -> dict[str, Any] | None:
    """业务员查看详情后标记管理员更新为已读。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.mark_sales_admin_update_viewed(quote_series_uid, sales_user_id)
    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid or not sales_user_can_access_quote(q_uid, sid):
        return None
    now = _utc_now_iso()
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            _ensure_quotes_columns(conn)
            row = conn.execute(
                "SELECT admin_update_status FROM quotes WHERE quote_uid = ? LIMIT 1",
                (q_uid,),
            ).fetchone()
            if not row:
                return None
            status = str(row["admin_update_status"] or "").strip().lower()
            if status != ADMIN_UPDATE_STATUS_PENDING:
                meta = dict(
                    conn.execute("SELECT * FROM quotes WHERE quote_uid = ?", (q_uid,)).fetchone()
                )
                files = list_quote_files_for_quote(q_uid)
                return {
                    "ok": True,
                    "quote_uid": q_uid,
                    "admin_feedback": build_admin_feedback_public(meta, files),
                }
            conn.execute(
                """
                UPDATE quotes SET
                    admin_update_status = ?,
                    admin_update_viewed_at = ?,
                    updated_at = ?
                WHERE quote_uid = ?
                """,
                (ADMIN_UPDATE_STATUS_VIEWED, now, now, q_uid),
            )
            conn.commit()
            meta = dict(
                conn.execute("SELECT * FROM quotes WHERE quote_uid = ?", (q_uid,)).fetchone()
            )
        finally:
            conn.close()
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
    """业务员确认已知晓管理员修正。"""
    from admin_correction_inbox import ADMIN_UPDATE_STATUS_HANDLED

    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.mark_sales_admin_update_handled(quote_series_uid, sales_user_id)
    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid or not sales_user_can_access_quote(q_uid, sid):
        return None
    now = _utc_now_iso()
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            _ensure_quotes_columns(conn)
            row = conn.execute(
                "SELECT quote_uid FROM quotes WHERE quote_uid = ? LIMIT 1",
                (q_uid,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                UPDATE quotes SET
                    admin_update_status = ?,
                    admin_update_handled_at = ?,
                    updated_at = ?
                WHERE quote_uid = ?
                """,
                (ADMIN_UPDATE_STATUS_HANDLED, now, now, q_uid),
            )
            conn.commit()
            meta = dict(
                conn.execute("SELECT * FROM quotes WHERE quote_uid = ?", (q_uid,)).fetchone()
            )
        finally:
            conn.close()
    files = list_quote_files_for_quote(q_uid)
    return {
        "ok": True,
        "quote_uid": q_uid,
        "admin_feedback": build_admin_feedback_public(meta, files),
    }


def count_unread_admin_updates_for_sales_user(sales_user_id: str) -> int:
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.count_unread_admin_updates_for_sales_user(sales_user_id)
    sid = str(sales_user_id or "").strip()
    if not sid:
        return 0
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS c FROM quotes
                WHERE sales_user_id = ? AND {_sales_quote_visible_sql()}
                  AND admin_update_status = ?
                  AND (
                    latest_version_no > 1
                    OR admin_update_at IS NOT NULL AND admin_update_at != ''
                    OR admin_feedback_at IS NOT NULL AND admin_feedback_at != ''
                    OR admin_calculated_file_id IS NOT NULL AND admin_calculated_file_id != ''
                    OR admin_correction_note IS NOT NULL AND admin_correction_note != ''
                  )
                """,
                (sid, ADMIN_UPDATE_STATUS_PENDING),
            ).fetchone()
        finally:
            conn.close()
    return int(row[0] if row else 0)


def list_my_admin_updates_for_sales_user(
    sales_user_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.list_my_admin_updates_for_sales_user(
            sales_user_id,
            limit=limit,
            offset=offset,
        )
    sid = str(sales_user_id or "").strip()
    if not sid:
        return []
    init_quote_storage()
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    activity_sql = """
        (
            latest_version_no > 1
            OR admin_update_at IS NOT NULL AND admin_update_at != ''
            OR admin_feedback_at IS NOT NULL AND admin_feedback_at != ''
            OR admin_calculated_file_id IS NOT NULL AND admin_calculated_file_id != ''
            OR admin_correction_note IS NOT NULL AND admin_correction_note != ''
        )
    """
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"""
                SELECT *
                FROM quotes
                WHERE sales_user_id = ? AND {_sales_quote_visible_sql()} AND {activity_sql}
                ORDER BY COALESCE(admin_update_at, updated_at) DESC
                LIMIT ? OFFSET ?
                """,
                (sid, lim, off),
            ).fetchall()
        finally:
            conn.close()
    items: list[dict[str, Any]] = []
    for row in rows:
        rd = dict(row)
        q_uid = str(rd.get("quote_uid") or "").strip()
        files = list_quote_files_for_quote(q_uid)
        fb = build_admin_feedback_public(rd, files)
        if not fb.get("has_admin_correction") and not _admin_update_has_activity(rd):
            continue
        items.append(
            {
                "quote_series_uid": q_uid,
                "quote_id": rd.get("latest_calc_quote_id"),
                "product_name": rd.get("product_name") or "",
                "sheet_original_name": rd.get("sheet_original_name") or "",
                "updated_at": rd.get("updated_at"),
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
                "approval_status": str(rd.get("approval_status") or "pending"),
                "approval_note": str(rd.get("approval_note") or ""),
                "rejection_reason": fb.get("rejection_reason") or "",
                "has_calculated_sheet": bool(fb.get("calculated_sheet")),
            }
        )
    return items


def _record_admin_correction_chat_notification(
    quote_uid: str,
    note: str,
    actor: str,
    at: str,
) -> None:
    if note:
        content = f"管理员已修正此报价 BOM，请查看修正说明与修正后报价。\n\n修正说明：{note}"
    else:
        content = "管理员已更新修正版，请查看修正后报价。"
    save_quote_chat_message(
        quote_uid,
        "admin",
        content,
        metadata={
            "type": "admin_correction_notice",
            "correction_note": note,
            "feedback_by": actor,
            "feedback_at": at,
        },
    )


def resolve_stored_file_path(stored_path: str) -> Path | None:
    """解析数据库中的 stored_path，且必须落在 data/uploads 下以防路径穿越。"""
    rel = Path(str(stored_path or "").strip())
    if rel.is_absolute():
        return None
    candidate = (ROOT / rel).resolve()
    uploads_root = UPLOADS_DIR.resolve()
    try:
        candidate.relative_to(uploads_root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


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
    """写入 quotes / quote_versions / quote_items；可选上传原始表 → quote_files。"""
    q_uid = str(quote_uid or "").strip()
    calc_id = str(calc_quote_id or "").strip()
    if not q_uid or not calc_id or not isinstance(quote_result, dict):
        return

    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        postgres_impl.save_quote_calculation(
            quote_uid=q_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name=sheet_original_display_name,
            uploaded_sheet=uploaded_sheet,
            quote_result=quote_result,
            sales_user_id=sales_user_id,
            sales_user_name=sales_user_name,
        )
        return

    init_quote_storage()

    if isinstance(uploaded_sheet, dict) and str(uploaded_sheet.get("content_base64") or "").strip():
        try:
            persist_uploaded_sheet_for_quote(q_uid, uploaded_sheet, calc_quote_id=calc_id)
        except Exception:
            pass

    pn, _, mt, tier1_cbm = _summarize_quote_result(quote_result)
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

    saved_at = _utc_now_iso()
    detail_rows = quote_result.get("detail_rows")
    if not isinstance(detail_rows, list):
        detail_rows = []
    sid = str(sales_user_id or "").strip()
    sname = str(sales_user_name or "").strip()

    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            dup = conn.execute(
                "SELECT 1 FROM quote_versions WHERE calc_quote_id = ?",
                (calc_id,),
            ).fetchone()
            if dup:
                conn.rollback()
                return
            row_mx = conn.execute(
                "SELECT COALESCE(MAX(version_no), 0) FROM quote_versions WHERE quote_uid = ?",
                (q_uid,),
            ).fetchone()
            next_ver = int(row_mx[0] or 0) + 1

            exists = conn.execute(
                "SELECT 1 FROM quotes WHERE quote_uid = ?", (q_uid,)
            ).fetchone()
            if not exists:
                conn.execute(
                    """
                    INSERT INTO quotes (
                        quote_uid, created_at, updated_at, latest_saved_at,
                        product_name, sheet_original_name, latest_version_no,
                        latest_calc_quote_id, material_total, tier1_cost_before_margin,
                        approval_status, sales_user_id, sales_user_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        updated_at = ?,
                        latest_saved_at = ?,
                        latest_version_no = ?,
                        latest_calc_quote_id = ?,
                        product_name = ?,
                        sheet_original_name = CASE
                            WHEN ? != '' THEN ?
                            ELSE sheet_original_name
                        END,
                        material_total = ?,
                        tier1_cost_before_margin = ?,
                        approval_status = 'pending',
                        approved_version_no = NULL,
                        approved_calc_quote_id = NULL,
                        approved_at = NULL,
                        approved_by = NULL,
                        approval_note = NULL,
                        sales_user_id = CASE
                            WHEN (sales_user_id IS NULL OR sales_user_id = '') AND ? != ''
                            THEN ?
                            ELSE sales_user_id
                        END,
                        sales_user_name = CASE
                            WHEN (sales_user_name IS NULL OR sales_user_name = '') AND ? != ''
                            THEN ?
                            ELSE sales_user_name
                        END
                    WHERE quote_uid = ?
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
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (q_uid, next_ver, calc_id, saved_at, intent_str, payload_json),
            )

            _insert_quote_items(conn, q_uid, next_ver, detail_rows)
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        finally:
            conn.close()
    _invalidate_admin_cache()


def finalize_quote_persistence(
    *,
    quote_series_uid: str,
    quote_result: dict[str, Any],
    uploaded_sheet: dict[str, Any] | None,
    sheet_original_display_name: str,
    sales_user_id: str | None = None,
    sales_user_name: str | None = None,
) -> None:
    """报价成功后入库（版本递增）。"""
    calc_id = str(quote_result.get("quote_id") or "").strip()
    if not calc_id:
        return
    attach_piece_area_calculation(quote_result)
    series = str(quote_series_uid or "").strip() or calc_id
    save_quote_calculation(
        quote_uid=series,
        calc_quote_id=calc_id,
        sheet_original_display_name=sheet_original_display_name,
        uploaded_sheet=uploaded_sheet,
        quote_result=quote_result,
        sales_user_id=sales_user_id,
        sales_user_name=sales_user_name,
    )
    merge_public_approval_fields(quote_result, series)


def _resolve_quote_uid_for_public_lookup(conn: sqlite3.Connection, lookup_id: str) -> str | None:
    lid = str(lookup_id or "").strip()
    if not lid:
        return None
    row = conn.execute(
        "SELECT quote_uid FROM quotes WHERE quote_uid = ? LIMIT 1",
        (lid,),
    ).fetchone()
    if row:
        return str(row[0])
    row = conn.execute(
        """
        SELECT quote_uid FROM quotes
        WHERE latest_calc_quote_id = ? OR approved_calc_quote_id = ?
        LIMIT 1
        """,
        (lid, lid),
    ).fetchone()
    if row:
        return str(row[0])
    row = conn.execute(
        """
        SELECT quote_uid FROM quote_versions
        WHERE calc_quote_id = ?
        ORDER BY version_no DESC LIMIT 1
        """,
        (lid,),
    ).fetchone()
    if row:
        return str(row[0])
    return None


def get_saved_quote_approval_public(lookup_id: str) -> dict[str, str]:
    """前台只读：按归档 quote_uid 或 calc_quote_id 查询审批核实结果。"""
    from quote_approval import public_approval_snapshot

    lid = str(lookup_id or "").strip()
    if not lid:
        return public_approval_snapshot()
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        if hasattr(postgres_impl, "get_saved_quote_approval_public"):
            return postgres_impl.get_saved_quote_approval_public(lid)
        return public_approval_snapshot()

    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            q_uid = _resolve_quote_uid_for_public_lookup(conn, lid)
            if not q_uid:
                return public_approval_snapshot()
            row = conn.execute(
                """
                SELECT approval_status, approval_note, approved_at, approved_by
                FROM quotes WHERE quote_uid = ?
                """,
                (q_uid,),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return public_approval_snapshot()
    rd = dict(row)
    return public_approval_snapshot(
        approval_status=rd.get("approval_status"),
        approval_note=rd.get("approval_note"),
        approved_at=rd.get("approved_at"),
        approved_by=rd.get("approved_by"),
    )


def get_saved_quote_approval_for_sales_user(
    lookup_id: str,
    sales_user_id: str,
) -> dict[str, str] | None:
    """前台审批只读：校验业务员归属；None 表示不存在或无权（统一 404，不泄露）。"""
    from quote_approval import public_approval_snapshot

    lid = str(lookup_id or "").strip()
    sid = str(sales_user_id or "").strip()
    if not lid or not sid:
        return None
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        if hasattr(postgres_impl, "get_saved_quote_approval_for_sales_user"):
            return postgres_impl.get_saved_quote_approval_for_sales_user(lid, sid)
        return None

    init_quote_storage()
    from quote_storage.db_common import sales_user_owns_quote

    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            q_uid = _resolve_quote_uid_for_public_lookup(conn, lid)
            if not q_uid:
                return None
            if _quote_sales_hidden_at(conn, q_uid):
                return None
            owner = _quote_owner_sales_user_id(conn, q_uid)
            if not sales_user_owns_quote(owner, sid):
                return None
            row = conn.execute(
                """
                SELECT approval_status, approval_note, approved_at, approved_by
                FROM quotes WHERE quote_uid = ?
                """,
                (q_uid,),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    rd = dict(row)
    return public_approval_snapshot(
        approval_status=rd.get("approval_status"),
        approval_note=rd.get("approval_note"),
        approved_at=rd.get("approved_at"),
        approved_by=rd.get("approved_by"),
    )


def merge_public_approval_fields(target: dict[str, Any], lookup_id: str) -> None:
    """将归档审批字段写入前台报价 JSON（就地更新）。"""
    if not isinstance(target, dict):
        return
    snap = get_saved_quote_approval_public(lookup_id)
    target.update(snap)


def update_saved_quote_approval(
    quote_uid: str,
    *,
    approval_status: str,
    approval_note: str | None = None,
    version_no: int | None = None,
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    """更新报价归档审批状态（pending / approved / rejected）及备注。"""
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        raise ValueError("缺少报价 UID。")
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        if hasattr(postgres_impl, "update_saved_quote_approval"):
            return postgres_impl.update_saved_quote_approval(
                q_uid,
                approval_status=approval_status,
                approval_note=approval_note,
                version_no=version_no,
                reviewed_by=reviewed_by,
            )
        raise RuntimeError("PostgreSQL 报价审批接口暂未启用。")

    from quote_approval import (
        approval_result_payload,
        normalize_approval_note,
        normalize_approval_status,
        normalize_reviewer_name,
    )

    status = normalize_approval_status(approval_status)
    note = normalize_approval_note(approval_note)
    init_quote_storage()
    actor = normalize_reviewer_name(reviewed_by)
    reviewed_at = _utc_now_iso()
    want_ver_i = 0
    calc_id: str | None = None
    vdict: dict[str, Any] = {}

    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            qrow = conn.execute(
                "SELECT * FROM quotes WHERE quote_uid = ?",
                (q_uid,),
            ).fetchone()
            if not qrow:
                conn.rollback()
                raise ValueError("报价不存在。")
            qmeta = dict(qrow)
            want_ver = version_no
            if want_ver is None:
                want_ver = int(qmeta.get("latest_version_no") or 0)
            try:
                want_ver_i = int(want_ver or 0)
            except (TypeError, ValueError):
                want_ver_i = 0
            if want_ver_i <= 0:
                conn.rollback()
                raise ValueError("版本号无效。")
            vrow = conn.execute(
                """
                SELECT version_no, calc_quote_id, saved_at
                FROM quote_versions
                WHERE quote_uid = ? AND version_no = ?
                """,
                (q_uid, want_ver_i),
            ).fetchone()
            if not vrow:
                conn.rollback()
                raise ValueError("指定版本不存在。")
            vdict = dict(vrow)
            calc_id = str(vdict.get("calc_quote_id") or "").strip() or None

            if status == "approved":
                conn.execute(
                    """
                    UPDATE quotes SET
                        approval_status = ?,
                        approval_note = ?,
                        approved_version_no = ?,
                        approved_calc_quote_id = ?,
                        approved_at = ?,
                        approved_by = ?,
                        updated_at = ?
                    WHERE quote_uid = ?
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
                        approval_status = ?,
                        approval_note = ?,
                        approved_version_no = NULL,
                        approved_calc_quote_id = NULL,
                        approved_at = ?,
                        approved_by = ?,
                        updated_at = ?
                    WHERE quote_uid = ?
                    """,
                    (status, note, reviewed_at, actor, reviewed_at, q_uid),
                )
            _mark_admin_update_pending(conn, q_uid, now=reviewed_at)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
    _invalidate_admin_cache()
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
    """Mark a saved quote version as approved for business use."""
    return update_saved_quote_approval(
        quote_uid,
        approval_status="approved",
        approval_note=approval_note,
        version_no=version_no,
        reviewed_by=approved_by,
    )


def delete_quote_series(quote_uid: str) -> bool:
    """删除整条报价序列：明细、版本、文件元数据及磁盘上传文件；顺带清理遗留 saved_quotes 行。"""
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return False
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.delete_quote_series(q_uid)
    init_quote_storage()
    files_meta = list_quote_files_for_quote(q_uid)
    deleted = False
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            exists = conn.execute(
                "SELECT 1 FROM quotes WHERE quote_uid = ?", (q_uid,)
            ).fetchone()
            if exists:
                conn.execute("DELETE FROM quote_items WHERE quote_uid = ?", (q_uid,))
                conn.execute("DELETE FROM quote_versions WHERE quote_uid = ?", (q_uid,))
                conn.execute(
                    "DELETE FROM quote_files WHERE quote_uid = ? OR quote_id = ?",
                    (q_uid, q_uid),
                )
                conn.execute("DELETE FROM quotes WHERE quote_uid = ?", (q_uid,))
                try:
                    conn.execute("DELETE FROM saved_quotes WHERE quote_id = ?", (q_uid,))
                except sqlite3.Error:
                    pass
                conn.commit()
                deleted = True
        finally:
            conn.close()
    if not deleted:
        return False
    _invalidate_admin_cache()
    for rec in files_meta:
        fs_path = resolve_stored_file_path(str(rec.get("stored_path") or ""))
        if fs_path:
            try:
                fs_path.unlink(missing_ok=True)
            except OSError:
                pass
    return True


def admin_delete_quotes_by_ids(
    quote_ids: list[Any],
    *,
    max_items: int = 300,
) -> dict[str, Any]:
    """按 UID 批量删除（与单条 DELETE 等价）。单次上限 max_items。"""
    if not isinstance(quote_ids, list):
        return {"deleted": 0, "failed": [], "requested": 0}
    uniq: list[str] = []
    seen: set[str] = set()
    for x in quote_ids[: max(1, min(int(max_items), 500))]:
        s = str(x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    deleted = 0
    failed: list[str] = []
    for qid in uniq:
        if delete_quote_series(qid):
            deleted += 1
        else:
            failed.append(qid)
    return {"deleted": deleted, "failed": failed, "requested": len(uniq)}


def admin_delete_all_matching_list_filters(
    *,
    search_q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    version_min: int | None = None,
    status: str | None = None,
    batch_limit: int = 200,
    max_rounds: int = 5000,
) -> tuple[int, list[str]]:
    """按后台列表同款筛选条件分批删除直至删完。batches offset 始终为 0（删后顶上移）。"""
    failed: list[str] = []
    deleted_total = 0
    rounds = 0
    lim = max(1, min(int(batch_limit), 500))
    while rounds < max_rounds:
        rounds += 1
        items, _ = list_saved_quotes_summaries(
            limit=lim,
            offset=0,
            search_q=search_q,
            date_from=date_from,
            date_to=date_to,
            version_min=version_min,
            status=status,
        )
        if not items:
            break
        batch_deleted = 0
        for it in items:
            qid = str(it.get("quote_id") or "").strip()
            if not qid:
                continue
            if delete_quote_series(qid):
                deleted_total += 1
                batch_deleted += 1
            else:
                failed.append(qid)
        if batch_deleted == 0:
            break
    return deleted_total, failed


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
    """后台列表：关键词、日期区间、最少版本数、状态（normal/warn/risk）、业务员筛选。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.list_saved_quotes_summaries(
            limit=limit,
            offset=offset,
            search_q=search_q,
            date_from=date_from,
            date_to=date_to,
            version_min=version_min,
            status=status,
            sales_user_q=sales_user_q,
        )
    init_quote_storage()
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))

    conds: list[str] = ["1 = 1"]
    params: list[Any] = []

    sq = str(search_q or "").strip()
    if sq:
        term = f"%{sq}%"
        conds.append(
            "(quote_uid LIKE ? OR IFNULL(product_name,'') LIKE ? OR IFNULL(sheet_original_name,'') LIKE ?)"
        )
        params.extend([term, term, term])

    df = str(date_from or "").strip()[:10]
    if df:
        conds.append("substr(IFNULL(latest_saved_at,''), 1, 10) >= ?")
        params.append(df)

    dt_to = str(date_to or "").strip()[:10]
    if dt_to:
        conds.append("substr(IFNULL(latest_saved_at,''), 1, 10) <= ?")
        params.append(dt_to)

    if version_min is not None:
        try:
            vmin = max(1, int(version_min))
            conds.append("latest_version_no >= ?")
            params.append(vmin)
        except (TypeError, ValueError):
            pass

    suq = str(sales_user_q or "").strip()
    if suq:
        owner_term = f"%{suq}%"
        conds.append(
            "(IFNULL(sales_user_id,'') LIKE ? OR IFNULL(sales_user_name,'') LIKE ?)"
        )
        params.extend([owner_term, owner_term])

    st = str(status or "").strip().lower()
    if st == "risk":
        conds.append(
            "(tier1_cost_before_margin IS NULL OR IFNULL(material_total, 0) <= 0)"
        )
    elif st == "warn":
        conds.append(
            "(tier1_cost_before_margin IS NOT NULL AND IFNULL(material_total, 0) > 0)"
        )
        conds.append(
            """EXISTS (
                SELECT 1 FROM quote_items qi
                WHERE qi.quote_uid = quotes.quote_uid
                  AND qi.version_no = quotes.latest_version_no
                  AND (qi.calc_note IS NULL OR TRIM(IFNULL(qi.calc_note, '')) = '')
            )"""
        )
    elif st == "normal":
        conds.append(
            "(tier1_cost_before_margin IS NOT NULL AND IFNULL(material_total, 0) > 0)"
        )
        conds.append(
            """NOT EXISTS (
                SELECT 1 FROM quote_items qi
                WHERE qi.quote_uid = quotes.quote_uid
                  AND qi.version_no = quotes.latest_version_no
                  AND (qi.calc_note IS NULL OR TRIM(IFNULL(qi.calc_note, '')) = '')
            )"""
        )

    where_sql = " AND ".join(conds)

    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            total_row = conn.execute(
                f"SELECT COUNT(*) FROM quotes WHERE {where_sql}",
                params,
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            rows = conn.execute(
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
                LIMIT ? OFFSET ?
                """,
                (*params, lim, off),
            ).fetchall()
        finally:
            conn.close()
    items = [dict(r) for r in rows]
    return items, total


def list_saved_quotes_changes_since(
    since: str,
    *,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """增量变更：返回 ``latest_saved_at`` 严格大于 ``since`` 的归档摘要（后台轮询）。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.list_saved_quotes_changes_since(since, limit=limit)
    since_norm = str(since or "").strip()
    if not since_norm:
        return [], 0
    init_quote_storage()
    lim = max(1, min(int(limit), 100))
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            count_row = conn.execute(
                "SELECT COUNT(*) FROM quotes WHERE latest_saved_at > ?",
                (since_norm,),
            ).fetchone()
            new_count = int(count_row[0]) if count_row else 0
            rows = conn.execute(
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
                WHERE latest_saved_at > ?
                ORDER BY latest_saved_at DESC
                LIMIT ?
                """,
                (since_norm, lim),
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows], new_count


def get_admin_dashboard_stats() -> dict[str, Any]:
    """驾驶舱汇总（不改变明细接口）：全库聚合。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.get_admin_dashboard_stats()
    init_quote_storage()
    global _DASHBOARD_CACHE
    now = time.monotonic()
    if _DASHBOARD_CACHE is not None:
        ts, cached = _DASHBOARD_CACHE
        if now - ts <= _DASHBOARD_CACHE_TTL_SEC:
            out = dict(cached)
            out["cache"] = {"hit": True, "ttl_sec": _DASHBOARD_CACHE_TTL_SEC}
            return out
    row: sqlite3.Row | None = None
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_quotes,
                    SUM(
                        CASE
                            WHEN substr(IFNULL(latest_saved_at,''), 1, 10) = date('now')
                            THEN 1 ELSE 0
                        END
                    ) AS today_new,
                    AVG(material_total) AS avg_material_total,
                    AVG(tier1_cost_before_margin) AS avg_tier1_cost_before_margin,
                    MAX(latest_saved_at) AS latest_saved_at,
                    (
                        SELECT AVG(
                            CAST(json_extract(qv.quote_json, '$.tiers[0].exw_price') AS REAL)
                        )
                        FROM quotes q
                        INNER JOIN quote_versions qv
                          ON qv.quote_uid = q.quote_uid
                         AND qv.version_no = q.latest_version_no
                        WHERE json_valid(qv.quote_json)
                    ) AS avg_tier1_exw
                FROM quotes
                """
            ).fetchone()
        finally:
            conn.close()

    def _f(v: Any) -> float | None:
        if v is None:
            return None
        try:
            return round(float(v), 4)
        except (TypeError, ValueError):
            return None

    rd = dict(row) if row else {}
    result = {
        "total_quotes": int(rd.get("total_quotes") or 0),
        "today_new": int(rd.get("today_new") or 0),
        "avg_material_total": _f(rd.get("avg_material_total")),
        "avg_tier1_cost_before_margin": _f(rd.get("avg_tier1_cost_before_margin")),
        "avg_tier1_exw": _f(rd.get("avg_tier1_exw")),
        "latest_saved_at": str(rd.get("latest_saved_at") or "") or None,
    }
    _DASHBOARD_CACHE = (now, dict(result))
    result["cache"] = {"hit": False, "ttl_sec": _DASHBOARD_CACHE_TTL_SEC}
    return result


def get_saved_quote_admin_bundle(
    quote_uid: str, *, version_no: int | None = None
) -> dict[str, Any] | None:
    """后台详情：指定版本或最新版本 + 版本列表 + 文件。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        bundle = postgres_impl.get_saved_quote_admin_bundle(quote_uid, version_no=version_no)
    else:
        bundle = _get_saved_quote_admin_bundle_sqlite(quote_uid, version_no=version_no)
    if bundle and isinstance(bundle.get("quote"), dict):
        enrich_quote_sales_fields(bundle["quote"])
    return bundle


def _get_saved_quote_admin_bundle_sqlite(
    quote_uid: str, *, version_no: int | None = None
) -> dict[str, Any] | None:
    init_quote_storage()
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return None
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            qrow = conn.execute(
                "SELECT * FROM quotes WHERE quote_uid = ?", (q_uid,)
            ).fetchone()
            if not qrow:
                return None
            meta = dict(qrow)

            want_ver = version_no
            if want_ver is None:
                want_ver = int(meta.get("latest_version_no") or 1)

            vrow = conn.execute(
                """
                SELECT * FROM quote_versions
                WHERE quote_uid = ? AND version_no = ?
                """,
                (q_uid, want_ver),
            ).fetchone()
            if not vrow:
                vrow = conn.execute(
                    """
                    SELECT * FROM quote_versions
                    WHERE quote_uid = ?
                    ORDER BY version_no DESC LIMIT 1
                    """,
                    (q_uid,),
                ).fetchone()
            if not vrow:
                return None

            vdict = dict(vrow)
            raw_json = vdict.get("quote_json") or "{}"
            try:
                quote_obj = json.loads(raw_json)
            except json.JSONDecodeError:
                quote_obj = {}

            irows = conn.execute(
                """
                SELECT line_no, name, spec, usage, unit_price, amount, amount_text,
                       source, calc_note, kb_hit
                FROM quote_items
                WHERE quote_uid = ? AND version_no = ?
                ORDER BY line_no ASC
                """,
                (q_uid, int(vdict["version_no"])),
            ).fetchall()
            items_db = [dict(r) for r in irows]

            vsum_rows = conn.execute(
                """
                SELECT version_no, calc_quote_id, saved_at, intent
                FROM quote_versions
                WHERE quote_uid = ?
                ORDER BY version_no DESC
                """,
                (q_uid,),
            ).fetchall()
            versions = [dict(r) for r in vsum_rows]
            latest_ver = int(meta.get("latest_version_no") or int(vdict["version_no"]) or 1)
            system_quote: dict[str, Any] | None = None
            if latest_ver > 1:
                system_quote = _load_quote_version_object(conn, q_uid, 1)
            elif isinstance(quote_obj, dict):
                system_quote = quote_obj
        finally:
            conn.close()

    files = list_quote_files_for_quote(q_uid)
    sel_ver = int(vdict["version_no"])
    meta_out = {
        **meta,
        "selected_version_no": sel_ver,
        "selected_calc_quote_id": vdict.get("calc_quote_id"),
    }
    reconcile_admin_quote_detail_rows(quote_obj, items_db)
    from material_spec_usage_enricher import enrich_quote_detail_rows

    st_text = str(meta.get("structure_text") or meta.get("structure_text_snapshot") or "")
    ps = meta.get("product_size") if isinstance(meta.get("product_size"), dict) else None
    enrich_quote_detail_rows(
        quote_obj,
        structure_text=st_text,
        product_size=ps,
    )
    enrich_quote_piece_area_on_read(quote_obj, items_db)
    from material_detail_display import enrich_quote_material_detail_display

    enrich_quote_material_detail_display(
        quote_obj,
        structure_text=st_text,
        product_size=ps,
    )
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
    """按材料名/规格检索历史报价明细（最新版本），供 QA 答疑。"""
    q = str(keyword or "").strip()
    if not q or len(q) < 2:
        return []
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.search_quote_items_by_keyword(q, limit=limit)
    init_quote_storage()
    lim = max(1, min(int(limit), 20))
    term = f"%{q}%"
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT qi.name, qi.spec, qi.unit_price, qi.amount, qi.amount_text,
                       q.product_name, q.latest_saved_at AS saved_at, q.quote_uid
                FROM quote_items qi
                INNER JOIN quotes q ON q.quote_uid = qi.quote_uid
                    AND qi.version_no = q.latest_version_no
                WHERE IFNULL(qi.name, '') LIKE ?
                   OR IFNULL(qi.spec, '') LIKE ?
                ORDER BY q.latest_saved_at DESC
                LIMIT ?
                """,
                (term, term, lim),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def _quote_owner_sales_user_id(conn: sqlite3.Connection, quote_uid: str) -> str:
    row = conn.execute(
        "SELECT sales_user_id FROM quotes WHERE quote_uid = ? LIMIT 1",
        (quote_uid,),
    ).fetchone()
    if not row:
        return ""
    return str(row[0] or "").strip()


def _quote_sales_hidden_at(conn: sqlite3.Connection, quote_uid: str) -> str:
    row = conn.execute(
        "SELECT sales_hidden_at FROM quotes WHERE quote_uid = ? LIMIT 1",
        (quote_uid,),
    ).fetchone()
    if not row:
        return ""
    return str(row[0] or "").strip()


def _sales_quote_visible_sql() -> str:
    return "(sales_hidden_at IS NULL OR sales_hidden_at = '')"


def sales_user_can_access_quote(quote_uid: str, sales_user_id: str) -> bool:
    """业务员侧访问控制：须为本人名下且未软删。未绑定 sales_user_id 的历史报价不对业务员开放。"""
    from quote_storage.db_common import sales_user_owns_quote

    q_uid = str(quote_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid:
        return False
    if not sid:
        return False
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.sales_user_can_access_quote(q_uid, sid)
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        try:
            if _quote_sales_hidden_at(conn, q_uid):
                return False
            owner = _quote_owner_sales_user_id(conn, q_uid)
        finally:
            conn.close()
    return sales_user_owns_quote(owner, sid)


def batch_hide_quotes_for_sales_user(
    sales_user_id: str,
    quote_uids: list[Any],
    *,
    max_items: int = 50,
) -> dict[str, Any]:
    """业务员侧批量隐藏报价（软删除，不影响管理员后台数据）。"""
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.batch_hide_quotes_for_sales_user(
            sales_user_id,
            quote_uids,
            max_items=max_items,
        )
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
    now = _utc_now_iso()
    deleted = 0
    not_found: list[str] = []
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            for uid in uniq:
                row = conn.execute(
                    """
                    SELECT quote_uid, sales_user_id, sales_hidden_at
                    FROM quotes WHERE quote_uid = ? LIMIT 1
                    """,
                    (uid,),
                ).fetchone()
                if not row:
                    not_found.append(uid)
                    continue
                owner = str(row["sales_user_id"] or "").strip()
                from quote_storage.db_common import sales_user_owns_quote

                if not sales_user_owns_quote(owner, sid):
                    not_found.append(uid)
                    continue
                if str(row["sales_hidden_at"] or "").strip():
                    deleted += 1
                    continue
                conn.execute(
                    """
                    UPDATE quotes SET sales_hidden_at = ?, updated_at = ?
                    WHERE quote_uid = ?
                    """,
                    (now, now, uid),
                )
                deleted += 1
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "deleted": deleted, "not_found": not_found}


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
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE quotes SET
                    sales_user_id = CASE
                        WHEN sales_user_id IS NULL OR sales_user_id = '' THEN ?
                        ELSE sales_user_id
                    END,
                    sales_user_name = CASE
                        WHEN (sales_user_name IS NULL OR sales_user_name = '') AND ? != ''
                        THEN ?
                        ELSE sales_user_name
                    END,
                    updated_at = ?
                WHERE quote_uid = ?
                """,
                (sid, sname, sname, _utc_now_iso(), q_uid),
            )
            conn.commit()
        finally:
            conn.close()


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
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.save_quote_chat_message(
            q_uid,
            role,
            content,
            message_id=message_id,
            metadata=metadata,
            created_at=created_at,
        )
    mid = str(message_id or "").strip() or uuid.uuid4().hex
    r = str(role or "system").strip().lower() or "system"
    body = str(content or "")
    meta_json = ""
    if isinstance(metadata, dict) and metadata:
        try:
            meta_json = json.dumps(metadata, ensure_ascii=False, default=str)
        except TypeError:
            meta_json = "{}"
    ts = str(created_at or "").strip() or _utc_now_iso()
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO quote_chat_messages (
                    message_id, quote_series_uid, role, content, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    quote_series_uid = excluded.quote_series_uid,
                    role = excluded.role,
                    content = excluded.content,
                    metadata_json = excluded.metadata_json,
                    created_at = excluded.created_at
                """,
                (mid, q_uid, r, body, meta_json or None, ts),
            )
            conn.commit()
        finally:
            conn.close()
    return mid


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
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.upsert_quote_chat_messages(
            q_uid,
            messages,
            sales_user_id=sales_user_id,
            sales_user_name=sales_user_name,
        )
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


def list_quote_chat_messages(quote_series_uid: str, *, limit: int = 500) -> list[dict[str, Any]]:
    q_uid = str(quote_series_uid or "").strip()
    if not q_uid:
        return []
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.list_quote_chat_messages(q_uid, limit=limit)
    init_quote_storage()
    lim = max(1, min(int(limit), 1000))
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT message_id, quote_series_uid, role, content, metadata_json, created_at
                FROM quote_chat_messages
                WHERE quote_series_uid = ?
                ORDER BY created_at ASC, message_id ASC
                LIMIT ?
                """,
                (q_uid, lim),
            ).fetchall()
        finally:
            conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        rd = dict(row)
        meta: dict[str, Any] = {}
        raw_meta = rd.pop("metadata_json", None)
        if raw_meta:
            try:
                parsed = json.loads(raw_meta)
                if isinstance(parsed, dict):
                    meta = parsed
            except json.JSONDecodeError:
                meta = {}
        out.append(
            {
                "message_id": rd.get("message_id"),
                "quote_series_uid": rd.get("quote_series_uid"),
                "role": rd.get("role"),
                "content": rd.get("content") or "",
                "metadata": meta,
                "created_at": rd.get("created_at"),
            }
        )
    return out


def _latest_amount_text_from_quote_row(row: dict[str, Any]) -> str:
    try:
        tier1 = float(row.get("tier1_cost_before_margin") or 0.0)
    except (TypeError, ValueError):
        tier1 = 0.0
    if tier1 > 0:
        return f"¥{tier1:.2f}"
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
    sid = str(sales_user_id or "").strip()
    if not sid:
        return []
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.list_my_quotes_for_sales_user(
            sid,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
    init_quote_storage()
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    filt = str(status_filter or "").strip().lower()
    params: list[Any] = [sid]
    where = f"sales_user_id = ? AND {_sales_quote_visible_sql()}"
    if filt in {"pending", "approved", "rejected"}:
        where += " AND approval_status = ?"
        params.append(filt)
    params.extend([lim, off])
    with _DB_LOCK:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"""
                SELECT quote_uid, latest_calc_quote_id, product_name, sheet_original_name,
                       created_at, updated_at, material_total, tier1_cost_before_margin,
                       approval_status, approval_note, approved_by, approved_at,
                       sales_user_id, sales_user_name,
                       admin_update_status, admin_update_at, admin_update_viewed_at
                FROM quotes
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
        finally:
            conn.close()
    items: list[dict[str, Any]] = []
    for row in rows:
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


def get_my_quote_session_detail(
    quote_series_uid: str,
    sales_user_id: str,
) -> dict[str, Any] | None:
    q_uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not q_uid or not sid:
        return None
    if not sales_user_can_access_quote(q_uid, sid):
        return None
    bundle = get_saved_quote_admin_bundle(q_uid)
    if not bundle:
        return None
    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    quote_obj = bundle.get("quote") if isinstance(bundle.get("quote"), dict) else {}
    if isinstance(quote_obj, dict):
        merge_public_approval_fields(quote_obj, q_uid)
        quote_obj.setdefault("quote_series_uid", q_uid)
    approval = get_saved_quote_approval_public(q_uid)
    messages = list_quote_chat_messages(q_uid)
    files = list_quote_files_for_quote(q_uid)
    admin_feedback = build_admin_feedback_public(meta, files)
    return {
        "quote_series_uid": q_uid,
        "quote_id": meta.get("latest_calc_quote_id") or quote_obj.get("quote_id"),
        "sales_user_id": meta.get("sales_user_id") or "",
        "sales_user_name": meta.get("sales_user_name") or "",
        "product_name": meta.get("product_name") or quote_obj.get("product_name") or "",
        "sheet_original_name": meta.get("sheet_original_name") or "",
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "latest_quote_result": quote_obj,
        "approval_status": approval.get("approval_status") or meta.get("approval_status") or "pending",
        "approval_comment": approval.get("approval_note") or meta.get("approval_note") or "",
        "approved_by": approval.get("approved_by") or "",
        "approved_at": approval.get("approved_at") or "",
        "approval": approval,
        "admin_feedback": admin_feedback,
        "messages": messages,
    }


def approval_notice_message_id(quote_uid: str) -> str:
    """审批会话通知的稳定 message_id，重复保存时 upsert 而非重复插入。"""
    q_uid = str(quote_uid or "").strip()
    return f"approval-notice:{q_uid}" if q_uid else ""


def record_approval_chat_notification(quote_uid: str, approval_result: dict[str, Any]) -> None:
    q_uid = str(quote_uid or "").strip()
    if not q_uid or not isinstance(approval_result, dict):
        return
    message_id = approval_notice_message_id(q_uid)
    if not message_id:
        return
    status = str(approval_result.get("approval_status") or "pending").strip().lower()
    note = str(approval_result.get("approval_note") or "").strip()
    by = str(approval_result.get("approved_by") or "").strip()
    at = str(approval_result.get("approved_at") or "").strip()
    if status == "approved":
        content = "管理员已通过此报价。"
    elif status == "rejected":
        content = f"管理员驳回：{note}" if note else "管理员已驳回此报价。"
    elif status == "pending":
        content = "报价已重新提交，等待管理员审批。"
    else:
        content = f"审批状态更新：{status}"
    save_quote_chat_message(
        q_uid,
        "admin",
        content,
        message_id=message_id,
        metadata={
            "type": "approval_notice",
            "approval_status": status,
            "approval_note": note,
            "approved_by": by,
            "approved_at": at,
        },
    )


# 兼容旧测试名
def archive_quote_snapshot(
    quote_id: str,
    *,
    sheet_original_name: str,
    quote_result: dict[str, Any],
) -> None:
    """兼容：等价于单次算价入库（series = calc id）。"""
    bid = str(quote_id or "").strip()
    qr = dict(quote_result)
    if not str(qr.get("quote_id") or "").strip():
        qr["quote_id"] = bid
    finalize_quote_persistence(
        quote_series_uid=bid,
        quote_result=qr,
        uploaded_sheet=None,
        sheet_original_display_name=sheet_original_name,
    )
