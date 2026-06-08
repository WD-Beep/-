"""价格学习候选统一模型（待审核队列）。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

QUEUE_PRICE_EXCEPTIONS = "price_exceptions"
QUEUE_QUOTE_SYNC_SUGGESTIONS = "quote_sync_suggestions"
QUEUE_PENDING_AUTO_LEARN = "pending_auto_learn"

SOURCE_TYPES = frozenset(
    {
        "missing_price",
        "ai_estimate",
        "admin_correction",
        "price_conflict",
        "low_confidence",
        "smart_lookup_miss",
    }
)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

AUTO_CONFLICT_MARKER = "AUTO_PRICE_CONFLICT"
AUTO_PENDING_MARKER = "AUTO_PENDING_PRICE"
AUTO_SYNC_MARKER = "AUTO_QUOTE_SYNC"

# 待审核队列 exception_status（与 status 字段不同，legacy 兼容用）
EXCEPTION_STATUS_OPEN = "open"
EXCEPTION_STATUS_RESOLVED = "resolved"
EXCEPTION_STATUS_EXCLUDED = "excluded"

# 合并队列读取时视为「仍在待审」的 status 值
PENDING_REVIEW_STATUSES = frozenset(
    {
        STATUS_PENDING,
        "pending_review",
        EXCEPTION_STATUS_OPEN,
        "",
    }
)

# 这些 marker 的候选只进后台队列，不参与报价查价
QUOTE_BLOCKING_MARKERS = frozenset(
    {
        AUTO_PENDING_MARKER,
        AUTO_SYNC_MARKER,
        AUTO_CONFLICT_MARKER,
    }
)

def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_key(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _norm_price(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def infer_source_type(
    *,
    marker: str = "",
    row: dict[str, Any] | None = None,
    reason: str = "",
    explicit: str = "",
    has_price: bool = True,
) -> str:
    if explicit in SOURCE_TYPES:
        return explicit
    mk = str(marker or "").strip()
    if mk == AUTO_CONFLICT_MARKER or "价格冲突" in str(reason or ""):
        return "price_conflict"
    r = str(reason or "").lower()
    if "low_confidence" in r or "confidence" in r:
        return "low_confidence"
    if "smart_lookup" in r or "quality_review" in r or "auto_write_disabled" in r:
        return "smart_lookup_miss"
    src_row = row if isinstance(row, dict) else {}
    source = str(src_row.get("source") or "").strip().lower()
    if source in {"ai", "estimated", "estimate", "system", "fallback"}:
        return "ai_estimate"
    if src_row.get("unit_price_ai") or src_row.get("price_ai"):
        return "ai_estimate"
    if "ai" in r and ("估算" in reason or "estimate" in r):
        return "ai_estimate"
    if not has_price or mk == AUTO_PENDING_MARKER:
        return "missing_price"
    if mk == AUTO_SYNC_MARKER:
        return "missing_price"
    return "missing_price"


def candidate_status_to_exception_status(status: str) -> str:
    st = str(status or STATUS_PENDING).strip().lower()
    if st == STATUS_APPROVED:
        return EXCEPTION_STATUS_RESOLVED
    if st == STATUS_REJECTED:
        return EXCEPTION_STATUS_EXCLUDED
    return EXCEPTION_STATUS_OPEN


def exception_status_to_candidate_status(exception_status: str) -> str:
    st = str(exception_status or EXCEPTION_STATUS_OPEN).strip().lower()
    if st == EXCEPTION_STATUS_RESOLVED:
        return STATUS_APPROVED
    if st == EXCEPTION_STATUS_EXCLUDED:
        return STATUS_REJECTED
    return STATUS_PENDING


def is_open_exception_status(status: object) -> bool:
    return str(status or EXCEPTION_STATUS_OPEN).strip().lower() == EXCEPTION_STATUS_OPEN


def is_resolved_exception_status(status: object) -> bool:
    return str(status or "").strip().lower() == EXCEPTION_STATUS_RESOLVED


def is_quote_blocking_learn_candidate(row: dict[str, Any]) -> bool:
    """待审核/未确认候选：仅后台展示，不得参与报价查价或写入覆盖层。"""
    norm = normalize_learn_candidate(row)
    if str(norm.get("status") or STATUS_PENDING) != STATUS_PENDING:
        return False
    if is_open_exception_status(norm.get("exception_status")):
        return True
    marker = str(norm.get("marker") or "").strip()
    return marker in QUOTE_BLOCKING_MARKERS


def build_learn_candidate(
    *,
    material_name: str,
    spec: str = "-",
    old_price: str = "",
    new_price: str = "",
    source_type: str = "missing_price",
    confidence: float | None = None,
    quote_id: str = "",
    quote_version_id: str = "",
    product_name: str = "",
    operator: str = "system",
    note: str = "",
    reject_reason: str = "",
    status: str = STATUS_PENDING,
    marker: str = "",
    exception_reason: str = "",
    review_hint: str = "",
    raw_context: dict[str, Any] | None = None,
    candidate_id: str = "",
    created_at: str = "",
    updated_at: str = "",
    row: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    now = _now_str()
    cid = str(candidate_id or "").strip() or f"lc-{uuid.uuid4().hex[:12]}"
    st = str(status or STATUS_PENDING).strip().lower()
    if st not in {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED}:
        st = STATUS_PENDING
    src_type = infer_source_type(
        marker=marker,
        row=row,
        reason=reason or note,
        explicit=source_type,
        has_price=bool(str(new_price or "").strip()),
    )
    exc_status = candidate_status_to_exception_status(st)
    conf_val: float | None
    try:
        conf_val = round(float(confidence), 6) if confidence is not None else None
    except (TypeError, ValueError):
        conf_val = None
    ctx = dict(raw_context) if isinstance(raw_context, dict) else {}
    created = str(created_at or "").strip() or now
    updated = str(updated_at or "").strip() or now
    name = str(material_name or "").strip()
    spec_norm = str(spec or "").strip() or "-"
    price = str(new_price or "").strip()
    payload: dict[str, Any] = {
        "candidate_id": cid,
        "exception_id": cid,
        "material_name": name,
        "name": name,
        "spec": spec_norm,
        "old_price": str(old_price or "").strip(),
        "new_price": price,
        "price": price,
        "source_type": src_type,
        "confidence": conf_val,
        "quote_id": str(quote_id or "").strip(),
        "quote_version_id": str(quote_version_id or "").strip(),
        "product_name": str(product_name or "").strip(),
        "operator": str(operator or "").strip() or "system",
        "created_at": created,
        "updated_at": updated,
        "status": st,
        "exception_status": exc_status,
        "reject_reason": str(reject_reason or "").strip(),
        "note": str(note or "").strip(),
        "raw_context": ctx,
        "marker": str(marker or "").strip(),
        "exception_reason": str(exception_reason or "").strip(),
        "review_hint": str(review_hint or "").strip(),
        "updated_by": str(operator or "").strip() or "system",
        "source_quote_id": str(quote_id or "").strip(),
        "row_id": cid,
        "is_exception": True,
    }
    return payload


def normalize_learn_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """兼容 legacy price_exceptions.jsonl 与统一候选字段。"""
    if not isinstance(row, dict):
        row = {}
    cid = str(row.get("candidate_id") or row.get("exception_id") or "").strip()
    if not cid:
        cid = f"lc-{uuid.uuid4().hex[:12]}"
    name = str(row.get("material_name") or row.get("name") or "").strip()
    spec = str(row.get("spec") or "").strip() or "-"
    new_price = str(row.get("new_price") or row.get("price") or "").strip()
    old_price = str(row.get("old_price") or "").strip()
    st = str(row.get("status") or "").strip().lower()
    if st not in {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED}:
        st = exception_status_to_candidate_status(str(row.get("exception_status") or EXCEPTION_STATUS_OPEN))
    exc_status = candidate_status_to_exception_status(st)
    operator = str(row.get("operator") or row.get("updated_by") or "system").strip() or "system"
    quote_id = str(row.get("quote_id") or row.get("source_quote_id") or "").strip()
    source_type = infer_source_type(
        marker=str(row.get("marker") or ""),
        row=row,
        reason=str(row.get("exception_reason") or row.get("note") or ""),
        explicit=str(row.get("source_type") or ""),
        has_price=bool(new_price),
    )
    conf_raw = row.get("confidence")
    conf_val: float | None
    try:
        conf_val = round(float(conf_raw), 6) if conf_raw is not None and str(conf_raw).strip() != "" else None
    except (TypeError, ValueError):
        conf_val = None
    ctx = row.get("raw_context") if isinstance(row.get("raw_context"), dict) else {}
    now = _now_str()
    created = str(row.get("created_at") or row.get("updated_at") or "").strip() or now
    updated = str(row.get("updated_at") or "").strip() or now
    out = build_learn_candidate(
        candidate_id=cid,
        material_name=name,
        spec=spec,
        old_price=old_price,
        new_price=new_price,
        source_type=source_type,
        confidence=conf_val,
        quote_id=quote_id,
        quote_version_id=str(row.get("quote_version_id") or "").strip(),
        product_name=str(row.get("product_name") or "").strip(),
        operator=operator,
        note=str(row.get("note") or "").strip(),
        reject_reason=str(row.get("reject_reason") or "").strip(),
        status=st,
        marker=str(row.get("marker") or "").strip(),
        exception_reason=str(row.get("exception_reason") or "").strip(),
        review_hint=str(row.get("review_hint") or "").strip(),
        raw_context=ctx,
        created_at=created,
        updated_at=updated,
    )
    for key in (
        "resolved_at",
        "resolved_by",
        "excluded_at",
        "excluded_by",
        "approved_entry",
        "queue_source",
        "last_approve_error",
    ):
        if key in row and row.get(key) not in (None, ""):
            out[key] = row[key]
    if not out.get("exception_reason"):
        out["exception_reason"] = str(row.get("exception_reason") or "待人工确认")
    if not out.get("review_hint") or out["review_hint"] not in {"fixable", "exclude_suggest", "review"}:
        out["review_hint"] = str(row.get("review_hint") or "review")
    return out


def candidate_dedupe_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    norm = normalize_learn_candidate(row)
    return (
        _norm_key(norm.get("material_name")),
        _norm_key(norm.get("spec")),
        _norm_price(norm.get("new_price")),
        str(norm.get("source_type") or ""),
    )


def is_pending_candidate(row: dict[str, Any]) -> bool:
    norm = normalize_learn_candidate(row)
    return str(norm.get("status") or STATUS_PENDING) == STATUS_PENDING


def stable_legacy_candidate_id(prefix: str, *parts: object) -> str:
    blob = "|".join(str(p or "").strip().lower() for p in parts)
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
    return f"lc-{prefix}-{digest}"


def suggestion_row_to_candidate(row: dict[str, Any]) -> dict[str, Any]:
    name = str(row.get("name") or row.get("material_name") or "").strip()
    spec = str(row.get("spec") or "-").strip() or "-"
    price = str(row.get("price") or row.get("new_price") or "").strip()
    cid = str(row.get("candidate_id") or row.get("exception_id") or "").strip()
    if not cid:
        cid = stable_legacy_candidate_id("sugg", name, spec, price, row.get("queued_at"), row.get("source"))
    out = build_learn_candidate(
        candidate_id=cid,
        material_name=name,
        spec=spec,
        new_price=price,
        source_type=str(row.get("source_type") or "missing_price"),
        quote_id=str(row.get("quote_id") or row.get("source_quote_id") or ""),
        product_name=str(row.get("product_name") or ""),
        operator=str(row.get("updated_by") or row.get("operator") or "quote_auto_sync"),
        note=str(row.get("note") or "legacy quote_sync_suggestions 待审核"),
        marker=str(row.get("marker") or AUTO_SYNC_MARKER),
        raw_context={"legacy_queue": QUEUE_QUOTE_SYNC_SUGGESTIONS, "legacy_row": dict(row)},
    )
    out["queue_source"] = QUEUE_QUOTE_SYNC_SUGGESTIONS
    return out


def pending_auto_row_to_candidate(row: dict[str, Any]) -> dict[str, Any]:
    mat = row.get("material") if isinstance(row.get("material"), dict) else {}
    name = str(mat.get("name") or row.get("query") or "").strip()
    spec = str(mat.get("spec") or row.get("spec") or "-").strip() or "-"
    price = str(mat.get("price") or mat.get("unit_price") or "").strip()
    conf_raw = row.get("confidence")
    conf_val: float | None
    try:
        conf_val = round(float(conf_raw), 6) if conf_raw is not None else None
    except (TypeError, ValueError):
        conf_val = None
    reason = str(row.get("reason") or row.get("_pending_apply_error") or "")
    src_type = "low_confidence" if "low_confidence" in reason else "smart_lookup_miss"
    cid = str(row.get("candidate_id") or row.get("exception_id") or "").strip()
    if not cid:
        cid = stable_legacy_candidate_id("pending", name, spec, price, row.get("created_at"), conf_raw)
    out = build_learn_candidate(
        candidate_id=cid,
        material_name=name,
        spec=spec,
        new_price=price,
        source_type=src_type,
        confidence=conf_val,
        operator="pending_auto_learn",
        note=reason or "legacy pending_auto_learn 待审核",
        raw_context={"legacy_queue": QUEUE_PENDING_AUTO_LEARN, "legacy_row": dict(row)},
    )
    out["queue_source"] = QUEUE_PENDING_AUTO_LEARN
    return out
