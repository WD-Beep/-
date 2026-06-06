"""报价单表头/客户资料：保存、回填、同客户历史建议（不写价格知识库）。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from quote_upload_storage import (
    _DB_LOCK,
    _connect,
    _utc_now_iso,
    configured_quote_db_backend,
    ensure_quote_db_backend_supported,
    init_quote_storage,
    sales_user_can_access_quote,
)

# 与前端 qs* / PDF pv* 一致的 meta 键
QUOTE_SHEET_META_KEYS: tuple[str, ...] = (
    "co_name",
    "co_phone",
    "co_addr",
    "quote_no",
    "seller_contact",
    "seller_email",
    "cust_name",
    "cust_contact",
    "cust_phone",
    "cust_addr",
    "quote_date_iso",
    "sample_required",
    "sample_fee",
    "sample_lead_time",
)

_META_SAVED_ONLY_KEYS = frozenset({"sample_required", "sample_fee", "sample_lead_time"})
_SAMPLE_REQUIRED_VALUES = frozenset({"yes", "no", "pending"})

_CUSTOMER_PROFILE_KEYS: tuple[str, ...] = (
    "cust_contact",
    "cust_phone",
    "cust_addr",
    "seller_email",
)

_DEFAULT_CO: dict[str, str] = {
    "co_name": "深圳市栢博旅游用品有限公司",
    "co_phone": "0755-28223791",
    "co_addr": "广东省深圳市龙岗区平湖街道宝能智创谷B栋A单元6A01",
}

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_HASH_QUOTE_NO_RE = re.compile(r"^BJ-\d{8}-[0-9a-f]{8}$", re.I)
_INTERNAL_QUOTE_NO_RE = re.compile(r"^[0-9a-f]{8,}$", re.I)


def _first_str(*candidates: Any) -> str:
    for value in candidates:
        text = str(value or "").strip()
        if text and text != "-":
            return text
    return ""


def normalize_customer_key(cust_name: Any) -> str:
    raw = str(cust_name or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"\s+", "", raw)


def normalize_sample_required(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _SAMPLE_REQUIRED_VALUES:
        return text
    alias = {
        "需要打样": "yes",
        "不需要打样": "no",
        "待确认": "pending",
        "y": "yes",
        "n": "no",
        "p": "pending",
    }
    return alias.get(text, "")


def normalize_meta_text_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"null", "undefined", "nan"}:
        return ""
    return text


def normalize_meta_payload(raw: Any) -> dict[str, str]:
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, str] = {}
    for key in QUOTE_SHEET_META_KEYS:
        if key == "sample_required":
            out[key] = normalize_sample_required(src.get(key))
        elif key in {"sample_fee", "sample_lead_time"}:
            out[key] = normalize_meta_text_value(src.get(key))
        else:
            out[key] = str(src.get(key) or "").strip()
    return out


def resolve_sample_pdf_display(
    meta: dict[str, str] | None, *, lang: str = "cn"
) -> dict[str, Any]:
    """客户 PDF 打样区展示（与前端 syncSamplePdfPreview 一致）。"""
    block = normalize_meta_payload(meta or {})
    fee = block.get("sample_fee") or ""
    lead = block.get("sample_lead_time") or ""
    return {
        "show_status": False,
        "status_text": "",
        "show_fee": bool(fee),
        "show_lead": bool(lead),
        "fee_text": fee,
        "lead_text": lead,
    }


def format_sample_required_label(value: Any) -> str:
    """后台/表单展示用中文标签。"""
    text = normalize_sample_required(value)
    if text == "yes":
        return "需要打样"
    if text == "no":
        return "不需要打样"
    if text == "pending":
        return "待确认"
    return "待确认"


def extract_sample_meta_from_quote(quote: dict[str, Any] | None) -> dict[str, str]:
    """从报价对象读取打样三字段（含 legacy 镜像键）。"""
    if not isinstance(quote, dict):
        return {"sample_required": "", "sample_fee": "", "sample_lead_time": ""}
    saved = extract_saved_meta(quote)
    return {
        "sample_required": saved.get("sample_required") or "",
        "sample_fee": saved.get("sample_fee") or "",
        "sample_lead_time": saved.get("sample_lead_time") or "",
    }


def validate_sample_export_meta(meta: dict[str, str] | None) -> dict[str, Any]:
    """导出前打样信息：不阻断导出，仅归一化并返回 PDF 展示快照。"""
    block = normalize_meta_payload(meta or {})
    required = block.get("sample_required") or ""
    return {
        "ok": True,
        "sample_required": required,
        "pdf_cn": resolve_sample_pdf_display(block, lang="cn"),
        "pdf_en": resolve_sample_pdf_display(block, lang="en"),
    }


def extract_saved_meta(quote: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(quote, dict):
        return {k: "" for k in QUOTE_SHEET_META_KEYS}
    block = quote.get("quote_sheet_meta")
    if isinstance(block, dict):
        saved = normalize_meta_payload(block)
        if any(saved.values()):
            return saved
    legacy = {
        "co_name": _first_str(quote.get("sheet_co_name")),
        "co_phone": _first_str(quote.get("sheet_co_phone")),
        "co_addr": _first_str(quote.get("sheet_co_addr")),
        "quote_no": _first_str(quote.get("quote_sheet_no"), quote.get("quote_no")),
        "seller_contact": _first_str(quote.get("sheet_seller_contact"), quote.get("sales_name")),
        "seller_email": _first_str(quote.get("seller_email"), quote.get("sales_email")),
        "cust_name": _first_str(quote.get("customer_name"), quote.get("cust_name")),
        "cust_contact": _first_str(quote.get("customer_contact"), quote.get("cust_contact")),
        "cust_phone": _first_str(quote.get("customer_phone"), quote.get("cust_phone")),
        "cust_addr": _first_str(quote.get("customer_address"), quote.get("cust_addr")),
        "quote_date_iso": _first_str(quote.get("quote_sheet_date")),
    }
    return normalize_meta_payload(legacy)


def quote_no_manual_from_saved(quote: dict[str, Any] | None) -> bool:
    if not isinstance(quote, dict):
        return False
    block = quote.get("quote_sheet_meta")
    if isinstance(block, dict) and block.get("quote_no_manual") is True:
        return True
    return bool(quote.get("quote_sheet_no_manual") is True)


def merge_meta_for_prefill(
    *,
    inferred: dict[str, str],
    saved: dict[str, str],
    history: dict[str, str] | None,
    defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    """优先级：当前报价已保存 > 推断 > 同客户历史 > 默认公司资料 > 空。"""
    hist = normalize_meta_payload(history or {})
    base = normalize_meta_payload(defaults or _DEFAULT_CO)
    inf = normalize_meta_payload(inferred)
    sav = normalize_meta_payload(saved)
    out: dict[str, str] = {}
    for key in QUOTE_SHEET_META_KEYS:
        if key in _META_SAVED_ONLY_KEYS:
            out[key] = _first_str(sav.get(key), inf.get(key))
        else:
            out[key] = _first_str(sav.get(key), inf.get(key), hist.get(key), base.get(key))
    return out


def _stable_quote_no_sequence(
    quote: dict[str, Any], detail: dict[str, Any] | None = None
) -> int:
    """同一报价系列稳定序号 001–999，避免随机 hash 后缀。"""
    det = detail if isinstance(detail, dict) else {}
    q = quote if isinstance(quote, dict) else {}
    seed = _first_str(
        det.get("quote_series_uid"),
        q.get("quote_series_uid"),
        det.get("quote_id"),
        q.get("quote_id"),
        det.get("latest_calc_quote_id"),
    )
    if not seed:
        return 1
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return (int(digest[:6], 16) % 999) + 1


def auto_quote_no(quote: dict[str, Any], detail: dict[str, Any] | None = None) -> str:
    """客户可读自动编号：BJ-YYYYMMDD-001（不用 UUID/hash 后缀）。"""
    det = detail if isinstance(detail, dict) else {}
    q = quote if isinstance(quote, dict) else {}
    for cand in (
        q.get("quote_id"),
        det.get("quote_id"),
        det.get("latest_calc_quote_id"),
    ):
        text = str(cand or "").strip()
        if text and not _UUID_RE.match(text) and not is_internal_customer_quote_no(text):
            return text
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = _stable_quote_no_sequence(q, det)
    return f"BJ-{day}-{seq:03d}"


def is_internal_customer_quote_no(text: Any) -> bool:
    """客户 PDF 不可展示的编号：UUID、纯 hash、旧版 BJ-date-hash。"""
    s = str(text or "").strip()
    if not s:
        return True
    if _UUID_RE.match(s):
        return True
    if _HASH_QUOTE_NO_RE.match(s):
        return True
    if _INTERNAL_QUOTE_NO_RE.match(s.replace("-", "")) and len(s.replace("-", "")) >= 16:
        return True
    return False


def sanitize_customer_quote_no(
    text: Any,
    *,
    quote: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
) -> str:
    """客户可见报价编号：手动/业务编号优先，内部 id 替换为可读自动编号。"""
    s = str(text or "").strip()
    if s and not is_internal_customer_quote_no(s):
        return s
    return auto_quote_no(quote or {}, detail)


def build_prefill_meta(
    detail: dict[str, Any],
    quote: dict[str, Any],
    *,
    sales_user_id: str = "",
    inferred: dict[str, str] | None = None,
) -> dict[str, str]:
    """合并推断、已保存、客户历史与公司默认，生成报价单表头 meta。"""
    inf = normalize_meta_payload(inferred or {})
    saved = extract_saved_meta(quote)
    cust_for_hist = _first_str(saved.get("cust_name"), inf.get("cust_name"))
    history = lookup_customer_profile(sales_user_id, cust_for_hist)
    merged = merge_meta_for_prefill(
        inferred=inf,
        saved=saved,
        history=history,
        defaults=_DEFAULT_CO,
    )
    merged["quote_no"] = resolve_quote_no_for_prefill(
        quote=quote,
        detail=detail,
        merged=merged,
        saved=saved,
    )
    if not _first_str(merged.get("quote_date_iso")):
        merged["quote_date_iso"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return merged


def resolve_quote_no_for_prefill(
    *,
    quote: dict[str, Any],
    detail: dict[str, Any] | None,
    merged: dict[str, str],
    saved: dict[str, str],
) -> str:
    if quote_no_manual_from_saved(quote) and _first_str(saved.get("quote_no")):
        manual = _first_str(saved.get("quote_no"))
        if not is_internal_customer_quote_no(manual):
            return manual
    existing = _first_str(merged.get("quote_no"))
    uid = str((detail or {}).get("quote_series_uid") or "").strip()
    if existing:
        if uid and existing == uid:
            return auto_quote_no(quote, detail)
        if is_internal_customer_quote_no(existing):
            return auto_quote_no(quote, detail)
        return existing
    return auto_quote_no(quote, detail)


def _mirror_meta_to_quote_root(quote_obj: dict[str, Any], meta: dict[str, str]) -> None:
    if not isinstance(quote_obj, dict) or not isinstance(meta, dict):
        return
    quote_obj["quote_sheet_meta"] = dict(meta)
    mapping = {
        "cust_name": ("customer_name", "cust_name"),
        "cust_contact": ("customer_contact", "cust_contact"),
        "cust_phone": ("customer_phone", "cust_phone"),
        "cust_addr": ("customer_address", "cust_addr"),
        "seller_email": ("seller_email", "sales_email"),
        "quote_no": ("quote_sheet_no", "quote_no"),
        "seller_contact": ("sheet_seller_contact",),
        "co_name": ("sheet_co_name",),
        "co_phone": ("sheet_co_phone",),
        "co_addr": ("sheet_co_addr",),
        "quote_date_iso": ("quote_sheet_date",),
        "sample_required": ("quote_sheet_sample_required", "sample_required"),
        "sample_fee": ("quote_sheet_sample_fee", "sample_fee"),
        "sample_lead_time": ("quote_sheet_sample_lead_time", "sample_lead_time"),
    }
    for src_key, targets in mapping.items():
        val = str(meta.get(src_key) or "").strip()
        if not val:
            continue
        for tkey in targets:
            quote_obj[tkey] = val


def carry_forward_quote_sheet_meta(
    quote_uid: str, quote_result: dict[str, Any]
) -> None:
    """新算价版本写入前保留上一版的报价单客户资料。"""
    prev = _load_latest_quote_object(quote_uid)
    if not prev:
        return
    prev_meta = extract_saved_meta(prev)
    if not any(prev_meta.values()) and not quote_no_manual_from_saved(prev):
        return
    block = prev.get("quote_sheet_meta") if isinstance(prev.get("quote_sheet_meta"), dict) else {}
    merged_block = dict(block) if isinstance(block, dict) else {}
    merged_block.update(prev_meta)
    if quote_no_manual_from_saved(prev):
        merged_block["quote_no_manual"] = True
    merged_block["updated_at"] = _utc_now_iso()
    quote_result["quote_sheet_meta"] = merged_block
    _mirror_meta_to_quote_root(quote_result, prev_meta)


def ensure_customer_profile_table(conn: sqlite3.Connection) -> None:
    conn.execute(
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
        """
    )


def lookup_customer_profile(
    sales_user_id: str, cust_name: str
) -> dict[str, str]:
    sid = str(sales_user_id or "").strip()
    key = normalize_customer_key(cust_name)
    if not sid or not key:
        return {}
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.lookup_customer_profile(sid, cust_name)
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        try:
            ensure_customer_profile_table(conn)
            row = conn.execute(
                """
                SELECT cust_contact, cust_phone, cust_addr, seller_email
                FROM quote_customer_profiles
                WHERE sales_user_id = ? AND customer_key = ?
                LIMIT 1
                """,
                (sid, key),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return {}
    return normalize_meta_payload(
        {
            "cust_contact": row[0] if not isinstance(row, sqlite3.Row) else row["cust_contact"],
            "cust_phone": row[1] if not isinstance(row, sqlite3.Row) else row["cust_phone"],
            "cust_addr": row[2] if not isinstance(row, sqlite3.Row) else row["cust_addr"],
            "seller_email": row[3] if not isinstance(row, sqlite3.Row) else row["seller_email"],
        }
    )


def upsert_customer_profile(
    sales_user_id: str, meta: dict[str, str]
) -> None:
    sid = str(sales_user_id or "").strip()
    cust_name = str(meta.get("cust_name") or "").strip()
    key = normalize_customer_key(cust_name)
    if not sid or not key:
        return
    payload = normalize_meta_payload(meta)
    if not any(str(payload.get(k) or "").strip() for k in _CUSTOMER_PROFILE_KEYS):
        return
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        postgres_impl.upsert_customer_profile(sid, meta)
        return
    init_quote_storage()
    now = _utc_now_iso()
    with _DB_LOCK:
        conn = _connect()
        try:
            ensure_customer_profile_table(conn)
            conn.execute(
                """
                INSERT INTO quote_customer_profiles (
                    sales_user_id, customer_key, cust_name,
                    cust_contact, cust_phone, cust_addr, seller_email, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sales_user_id, customer_key) DO UPDATE SET
                    cust_name = excluded.cust_name,
                    cust_contact = CASE WHEN excluded.cust_contact != '' THEN excluded.cust_contact ELSE cust_contact END,
                    cust_phone = CASE WHEN excluded.cust_phone != '' THEN excluded.cust_phone ELSE cust_phone END,
                    cust_addr = CASE WHEN excluded.cust_addr != '' THEN excluded.cust_addr ELSE cust_addr END,
                    seller_email = CASE WHEN excluded.seller_email != '' THEN excluded.seller_email ELSE seller_email END,
                    updated_at = excluded.updated_at
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
        finally:
            conn.close()


def _load_latest_quote_object(quote_uid: str) -> dict[str, Any] | None:
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        return None
    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.load_latest_quote_object(q_uid)
    init_quote_storage()
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT quote_json FROM quote_versions
                WHERE quote_uid = ?
                ORDER BY version_no DESC
                LIMIT 1
                """,
                (q_uid,),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    try:
        raw = row[0] if not isinstance(row, sqlite3.Row) else row["quote_json"]
        obj = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def save_quote_sheet_meta(
    quote_series_uid: str,
    sales_user_id: str,
    meta_payload: dict[str, Any],
    *,
    quote_no_manual: bool | None = None,
) -> dict[str, Any]:
    """保存到最新 quote_versions.quote_json.quote_sheet_meta。"""
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

    ensure_quote_db_backend_supported()
    if configured_quote_db_backend() == "postgres":
        from quote_storage import postgres_impl

        return postgres_impl.save_quote_sheet_meta(
            q_uid,
            sid,
            meta,
            quote_no_manual=manual_flag,
        )

    init_quote_storage()
    now = _utc_now_iso()
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT version_no, quote_json FROM quote_versions
                WHERE quote_uid = ?
                ORDER BY version_no DESC
                LIMIT 1
                """,
                (q_uid,),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "not_found", "message": "报价记录不存在。"}
            ver = int(row[0] if not isinstance(row, sqlite3.Row) else row["version_no"])
            try:
                raw_json = row[1] if not isinstance(row, sqlite3.Row) else row["quote_json"]
                quote_obj = json.loads(raw_json or "{}")
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

            payload_json = json.dumps(quote_obj, ensure_ascii=False, default=str)
            conn.execute(
                """
                UPDATE quote_versions SET quote_json = ?
                WHERE quote_uid = ? AND version_no = ?
                """,
                (payload_json, q_uid, ver),
            )
            conn.execute(
                "UPDATE quotes SET updated_at = ? WHERE quote_uid = ?",
                (now, q_uid),
            )
            conn.commit()
        finally:
            conn.close()

    upsert_customer_profile(sid, meta)
    return {"ok": True, "quote_series_uid": q_uid, "meta": meta}
