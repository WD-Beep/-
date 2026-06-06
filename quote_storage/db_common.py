"""报价库共用小工具（无循环依赖）。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-()\u4e00-\u9fff]+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize_quote_result(quote_result: dict[str, Any]) -> tuple[str, str, float, float | None]:
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


def sales_user_owns_quote(owner: str, sales_user_id: str) -> bool:
    """业务员只能访问明确绑定到自己名下的报价（空 owner 视为未归属，不可访问）。"""
    sid = str(sales_user_id or "").strip()
    if not sid:
        return False
    o = str(owner or "").strip()
    if not o:
        return False
    return o == sid


def sanitize_original_name(name: str) -> str:
    base = Path(str(name or "").strip()).name
    if not base or base in {".", ".."}:
        return "upload.bin"
    base = _SAFE_NAME_RE.sub("_", base)
    return base[:180] if len(base) > 180 else base
