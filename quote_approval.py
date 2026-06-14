"""报价归档审批状态（quotes.approval_status）规范化与更新逻辑。"""
from __future__ import annotations

from typing import Any

APPROVAL_STATUSES = frozenset({"pending", "approved", "rejected"})

_STATUS_ALIASES: dict[str, str] = {
    "pending": "pending",
    "待核实": "pending",
    "待审批": "pending",
    "approved": "approved",
    "合格": "approved",
    "通过": "approved",
    "rejected": "rejected",
    "不合格": "rejected",
    "驳回": "rejected",
}


def normalize_approval_status(raw: object) -> str:
    key = str(raw or "").strip().lower()
    if key in APPROVAL_STATUSES:
        return key
    mapped = _STATUS_ALIASES.get(str(raw or "").strip())
    if mapped:
        return mapped
    mapped = _STATUS_ALIASES.get(key)
    if mapped:
        return mapped
    raise ValueError(
        "approval_status 无效，仅支持 pending（待核实）、approved（合格）、rejected（不合格）。"
    )


def normalize_approval_note(raw: object) -> str:
    return str(raw or "").strip()


_RESERVED_REVIEWER_NAMES = frozenset({"admin", "administrator"})


def normalize_reviewer_name(raw: object) -> str:
    """业务审核人姓名（非后台登录账号）；允许为空。"""
    return str(raw or "").strip()


def sanitize_public_reviewer_name(raw: object) -> str:
    """前台/归档展示：隐藏占位 admin，无姓名则空字符串。"""
    name = str(raw or "").strip()
    if not name or name.lower() in _RESERVED_REVIEWER_NAMES:
        return ""
    return name


def display_reviewer_name(raw: object) -> str:
    """后台展示：无有效姓名时显示「未填写」。"""
    name = sanitize_public_reviewer_name(raw)
    return name if name else "未填写"


def resolve_reviewer_name_from_request(body: dict[str, Any] | None) -> str:
    if not isinstance(body, dict):
        raise ValueError("请求体无效")
    raw = body.get("reviewer_name")
    if raw is None:
        raw = body.get("approved_by_name")
    if raw is None:
        raw = body.get("approved_by")
    return normalize_reviewer_name(raw)


def public_approval_snapshot(
    *,
    approval_status: object = "pending",
    approval_note: object = "",
    approved_at: object = "",
    approved_by: object = "",
) -> dict[str, str]:
    """前台只读：审批核实结果（不含版本/内部 ID）。"""
    try:
        status = normalize_approval_status(approval_status)
    except ValueError:
        status = "pending"
    return {
        "approval_status": status,
        "approval_note": normalize_approval_note(approval_note),
        "approved_at": str(approved_at or "").strip(),
        "approved_by": sanitize_public_reviewer_name(approved_by),
    }


def approval_result_payload(
    *,
    quote_uid: str,
    approval_status: str,
    approval_note: str,
    approved_version_no: int | None,
    approved_calc_quote_id: str | None,
    approved_at: str | None,
    approved_by: str | None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "quote_uid": quote_uid,
        "approval_status": approval_status,
        "approval_note": approval_note,
        "approved_version_no": approved_version_no,
        "approved_calc_quote_id": approved_calc_quote_id,
        "approved_at": approved_at,
        "approved_by": approved_by,
    }
