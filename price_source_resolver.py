"""报价单价来源优先级与边界说明。

查价顺序（无业务价时才向下回退）：
  1. sheet  — 本次上传表格/需求表 inline 价
  2. manual — 本次人工编辑价
  3. override — 管理员确认且质量合格的新价覆盖层（price_overrides.jsonl）
  4. kb     — 正式知识库
  5. ai_estimate — AI/系统估算，须标记 unit_price_ai / pricing_review_required

硬性边界：
  - sheet/manual 存在时，override 与 kb 均不得覆盖本次业务价；仅可生成冲突候选。
  - pending / open / 待补充 / AUTO_PENDING_PRICE / AUTO_QUOTE_SYNC / 未确认候选
    不在本模块读取范围内，不得参与报价（见 price_learn_candidate.is_quote_blocking_learn_candidate）。
  - 垃圾名、异常价、特殊费用名不得进入 override 或正式库（kb_data_quality.judge_kb_insert_candidate）。
"""
from __future__ import annotations

from typing import Any

from sheet_parser import looks_like_valid_unit_price_text

PRICE_SOURCE_SHEET = "sheet"       # 本次表格价，最高优先级
PRICE_SOURCE_MANUAL = "manual"     # 本次人工编辑价，与 sheet 同级
PRICE_SOURCE_OVERRIDE = "override" # 管理员确认覆盖层，仅无业务价时生效
PRICE_SOURCE_KB = "kb"             # 正式知识库
PRICE_SOURCE_AI = "ai_estimate"  # AI/系统估算，须待复核
BUSINESS_PRICE_SOURCES = frozenset({PRICE_SOURCE_SHEET, PRICE_SOURCE_MANUAL})
AUTHORITATIVE_PRICE_SOURCES = frozenset(
    {PRICE_SOURCE_SHEET, PRICE_SOURCE_MANUAL, PRICE_SOURCE_OVERRIDE, PRICE_SOURCE_KB}
)


def has_business_unit_price(unit_price: object) -> bool:
    text = str(unit_price or "").strip()
    if not text or text in {"-", "—", "/"}:
        return False
    return looks_like_valid_unit_price_text(text)


def normalize_price_key(value: object) -> str:
    from price_admin_store import _norm_price

    return _norm_price(value)


def prices_norm_equal(left: object, right: object) -> bool:
    lk = normalize_price_key(left)
    rk = normalize_price_key(right)
    if not lk or not rk:
        return False
    return lk == rk


def prices_norm_conflict(left: object, right: object) -> bool:
    if not has_business_unit_price(left):
        return False
    rk = normalize_price_key(right)
    if not rk:
        return False
    return not prices_norm_equal(left, right)


def infer_price_source(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return PRICE_SOURCE_AI
    explicit = str(row.get("price_source") or "").strip()
    if explicit in {
        PRICE_SOURCE_SHEET,
        PRICE_SOURCE_MANUAL,
        PRICE_SOURCE_OVERRIDE,
        PRICE_SOURCE_KB,
        PRICE_SOURCE_AI,
    }:
        return explicit
    if has_business_unit_price(row.get("unit_price")):
        src = str(row.get("demand_source") or row.get("field_source_type") or "").strip()
        if src in {"manual", "user_edit", "admin_edit"}:
            return PRICE_SOURCE_MANUAL
        return PRICE_SOURCE_SHEET
    if bool(row.get("override_hit")) and has_business_unit_price(row.get("unit_price")):
        return PRICE_SOURCE_OVERRIDE
    if bool(row.get("kb_hit")) and has_business_unit_price(row.get("unit_price")):
        return PRICE_SOURCE_KB
    if bool(row.get("unit_price_ai")):
        return PRICE_SOURCE_AI
    legacy = str(row.get("source") or "").strip().lower()
    if legacy == "kb" and has_business_unit_price(row.get("unit_price")):
        return PRICE_SOURCE_KB
    if legacy == "ai":
        return PRICE_SOURCE_AI
    return PRICE_SOURCE_AI


def stamp_business_price_fields(
    row: dict[str, Any],
    unit_price: object,
    *,
    price_source: str = PRICE_SOURCE_SHEET,
) -> None:
    text = str(unit_price or "").strip()
    if has_business_unit_price(text):
        row["unit_price"] = text
        row["unit_price_ai"] = False
        row["price_source"] = price_source
        row["pricing_review_required"] = False


def merge_override_lookup_into_row(
    row: dict[str, Any],
    *,
    override_fields: dict[str, object],
    override_display_price: str,
) -> dict[str, object]:
    """在缺业务价时合并已确认覆盖层价格。"""
    merged: dict[str, object] = dict(row)
    merged.update(override_fields)
    merged.update(
        {
            "unit_price": override_display_price,
            "unit_price_ai": False,
            "kb_hit": False,
            "override_hit": True,
            "price_source": PRICE_SOURCE_OVERRIDE,
            "source": "kb",
            "pricing_review_required": False,
        }
    )
    return merged


def merge_kb_lookup_into_row(
    row: dict[str, Any],
    *,
    material_name: str,
    kb_fields: dict[str, object],
    kb_display_price: str,
    kb_rejected: bool = False,
    kb_reject_reason: str = "",
    reference_price: str = "",
    reference_label: str = "kb",
) -> dict[str, object]:
    """在已有业务行上合并查价结果；业务价始终优先。"""
    merged: dict[str, object] = dict(row)
    merged.update(kb_fields)

    existing = str(row.get("unit_price") or "").strip()
    has_business = has_business_unit_price(existing)
    business_source = infer_price_source(row)
    if business_source in BUSINESS_PRICE_SOURCES or has_business:
        business_source = business_source if business_source in BUSINESS_PRICE_SOURCES else PRICE_SOURCE_SHEET
        merged["unit_price"] = existing
        merged["unit_price_ai"] = False
        merged["price_source"] = business_source
        merged["kb_hit"] = False
        merged["override_hit"] = False
        merged["source"] = business_source if business_source == PRICE_SOURCE_MANUAL else "kb"
        if kb_rejected:
            merged["kb_price_rejected"] = True
            merged["kb_reject_reason"] = kb_reject_reason
            merged["pricing_review_required"] = True
        elif reference_price and prices_norm_conflict(existing, reference_price):
            merged["price_conflict_required"] = True
            if reference_label == "override":
                merged["override_reference_price"] = reference_price
            else:
                merged["kb_reference_price"] = reference_price
            merged["pricing_review_required"] = True
        return merged

    if kb_rejected:
        merged.update(
            {
                "unit_price": "-",
                "unit_price_ai": True,
                "kb_hit": False,
                "override_hit": False,
                "kb_score": 0.0,
                "price_source": PRICE_SOURCE_AI,
                "source": "ai",
                "kb_price_rejected": True,
                "kb_reject_reason": kb_reject_reason,
                "pricing_review_required": True,
            }
        )
        return merged

    merged.update(
        {
            "unit_price": kb_display_price,
            "unit_price_ai": False,
            "kb_hit": True,
            "override_hit": False,
            "price_source": PRICE_SOURCE_KB,
            "source": "kb",
            "pricing_review_required": False,
        }
    )
    return merged


def apply_confirmed_price_lookup(
    row: dict[str, Any],
    *,
    material_name: str,
    spec: str = "-",
    kb_fields: dict[str, object] | None = None,
    kb_display_price: str = "",
    kb_rejected: bool = False,
    kb_reject_reason: str = "",
    role: str = "",
    usage: str = "",
) -> dict[str, object]:
    """统一查价：业务价 > 覆盖层 > 正式 KB > 拒绝/待 AI。

    待审核候选（pending/open）不会进入此函数；仅读取已确认覆盖层。
    """
    from price_admin_store import lookup_confirmed_price_override
    from price_kb import format_material_unit_price_text

    base_row = dict(row)
    if not base_row.get("unit_price"):
        base_row["unit_price"] = "-"

    existing = str(base_row.get("unit_price") or "").strip()
    if has_business_unit_price(existing):
        ref_price = ""
        ref_label = "kb"
        override_hit = lookup_confirmed_price_override(material_name, spec)
        if override_hit is not None:
            ref_price = format_material_unit_price_text(
                str(override_hit.get("price") or ""),
                name=material_name,
                spec=spec,
                usage=usage,
                role=role,
                preserve_stored_price=True,
            )
            ref_label = "override"
        elif kb_display_price:
            ref_price = kb_display_price
        return merge_kb_lookup_into_row(
            base_row,
            material_name=material_name,
            kb_fields=kb_fields or {},
            kb_display_price=kb_display_price,
            kb_rejected=kb_rejected,
            kb_reject_reason=kb_reject_reason,
            reference_price=ref_price,
            reference_label=ref_label,
        )

    override_hit = lookup_confirmed_price_override(material_name, spec)
    if override_hit is not None:
        display_price = format_material_unit_price_text(
            str(override_hit.get("price") or ""),
            name=material_name,
            spec=spec,
            usage=usage,
            role=role,
            preserve_stored_price=True,
        )
        override_fields = {
            "override_matched_name": str(override_hit.get("material_name") or material_name),
            "override_matched_spec": str(override_hit.get("spec") or spec),
            "override_id": str(override_hit.get("override_id") or ""),
        }
        merged = merge_override_lookup_into_row(
            {**base_row, **(kb_fields or {})},
            override_fields=override_fields,
            override_display_price=display_price,
        )
        if kb_display_price and prices_norm_conflict(display_price, kb_display_price):
            merged["price_conflict_required"] = True
            merged["kb_reference_price"] = kb_display_price
            merged["pricing_review_required"] = True
        return merged

    return merge_kb_lookup_into_row(
        base_row,
        material_name=material_name,
        kb_fields=kb_fields or {},
        kb_display_price=kb_display_price,
        kb_rejected=kb_rejected,
        kb_reject_reason=kb_reject_reason,
    )


def row_unit_price_is_authoritative(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    ps = infer_price_source(row)
    if ps in BUSINESS_PRICE_SOURCES:
        return has_business_unit_price(row.get("unit_price"))
    if ps == PRICE_SOURCE_OVERRIDE and bool(row.get("override_hit")):
        return has_business_unit_price(row.get("unit_price"))
    if ps == PRICE_SOURCE_KB and bool(row.get("kb_hit")):
        return has_business_unit_price(row.get("unit_price"))
    return False
