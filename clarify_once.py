from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from quote_agent.parser import _parse_price_patch
from quote_engine import row_unit_alignment_hints


@dataclass(frozen=True)
class ClarifySpec:
    reason: str
    message: str
    missing_fields: tuple[str, ...]


def build_clarify_response(spec: ClarifySpec) -> dict[str, Any]:
    return {
        "quote_ready": False,
        "intent": "CLARIFY",
        "reply_type": "clarify_question",
        "assistant_message": spec.message,
        "missing_fields": list(spec.missing_fields),
        "clarify_reason": spec.reason,
    }


def detect_request_clarify(
    user_text: str,
    *,
    has_upload: bool,
    has_active_quote: bool,
    route_reason: str = "",
) -> ClarifySpec | None:
    text = str(user_text or "").strip()
    reason = str(route_reason or "")

    if "explain_needs_active_quote" in reason:
        return ClarifySpec(
            "explain_needs_active_quote",
            "请先生成或打开一份报价，我才能解释当前报价的计算过程。",
            ("active_quote",),
        )

    if "patch_missing_target" in reason or (
        has_active_quote and is_vague_patch_without_target(text)
    ):
        return ClarifySpec(
            "patch_missing_target",
            _vague_patch_clarify_message(text),
            ("patch_target", "unit_price"),
        )

    if not has_upload and not has_active_quote and _looks_like_insufficient_new_quote(text):
        return ClarifySpec(
            "quote_inputs_incomplete",
            "请补充产品、数量和主要材料，或直接上传 BOM/需求表后我再报价。",
            ("upload_or_bom", "quantity", "spec_or_unit_price"),
        )

    if reason.startswith("needs_clarification:") or reason.startswith("low_confidence:"):
        if has_active_quote:
            return ClarifySpec(
                "follow_up_unclear",
                "您是想了解价格构成、调整配置重新报价，还是咨询材料/工艺？请补一句目标。",
                ("intent_choice",),
            )
        return ClarifySpec(
            "quote_context_missing",
            "您是想生成报价、咨询材料/工艺，还是了解价格构成？如果要报价，请上传 BOM 或说明产品、数量和主要材料。",
            ("intent_choice", "upload_or_bom", "quantity", "material"),
        )

    return None


def detect_pre_quote_clarify(payload: dict[str, Any]) -> ClarifySpec | None:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items:
        user_text = str(
            payload.get("message_text")
            or payload.get("user_prompt")
            or payload.get("prompt")
            or ""
        ).strip()
        if user_text and _looks_like_insufficient_new_quote(user_text):
            return ClarifySpec(
                "quote_inputs_incomplete",
                "请补充产品、数量和主要材料，或直接上传 BOM/需求表后我再报价。",
                ("upload_or_bom", "quantity", "spec_or_unit_price"),
            )
        return None

    unit_spec = _first_unit_mismatch(items)
    if unit_spec:
        return unit_spec

    kb_spec = _first_kb_ambiguous(items)
    if kb_spec:
        return kb_spec

    return None


def clarify_from_agent_error(message: str) -> dict[str, Any] | None:
    msg = str(message or "").strip()
    if not msg:
        return None
    if "目标" in msg and ("不明确" in msg or "缺少" in msg):
        return build_clarify_response(
            ClarifySpec("patch_target_missing", msg, ("patch_target", "material_name")),
        )
    if "当前没有报价" in msg or "active quote" in msg.lower():
        return build_clarify_response(
            ClarifySpec("active_quote_missing", msg, ("active_quote",)),
        )
    return None


def is_vague_patch_without_target(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    patch = _parse_price_patch(s)
    if patch:
        target = str(patch.get("target") or "")
        label = str(patch.get("label") or "").strip()
        if target != "material_unit_price":
            return False
        if label and not _is_patch_verb_only(label):
            return False
    has_price = bool(re.search(r"\d+(?:\.\d+)?\s*(?:元|块|人民币|rmb|\$)", s, re.I))
    has_patch_verb = bool(re.search(r"(改|换|调|变|设置|设为|改成|换成|改为)", s))
    has_clear_target = bool(
        re.search(r"(拉链|织带|面料|里料|布|扣|五金|包装|加工|logo|印刷|纸箱|材料)", s, re.I)
    )
    return has_price and has_patch_verb and not has_clear_target


def _vague_patch_clarify_message(text: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)", str(text or ""))
    if m:
        return f"你要把哪个材料或费用项改成 {m.group(1)}？请说明物料名称或费用项。"
    return "请说明要修改哪个材料或费用项，例如“拉链改成5元/米”。"


def _looks_like_insufficient_new_quote(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    asks_quote = bool(re.search(r"(报价|算价|多少钱|成本|价格)", s))
    has_quantity = bool(re.search(r"\d+\s*(个|件|只|pcs|套)", s, re.I))
    has_upload_hint = bool(re.search(r"(bom|表格|需求表|xlsx|文件)", s, re.I))
    return asks_quote and not has_quantity and not has_upload_hint


def _first_unit_mismatch(items: list[Any]) -> ClarifySpec | None:
    for row in items:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "-").strip()
        usage = str(row.get("usage") or "")
        unit_price = str(row.get("unit_price") or "")
        hints = row_unit_alignment_hints(usage, unit_price)
        if not hints:
            continue
        if _is_auto_convertible_unit_pair(usage, unit_price):
            continue
        return ClarifySpec(
            "unit_usage_mismatch",
            f"“{name}”的用量单位和单价口径可能不一致：{hints[0]} 请统一单位或说明折算方式。",
            ("usage_unit", "unit_price_unit"),
        )
    return None


def _first_kb_ambiguous(items: list[Any]) -> ClarifySpec | None:
    try:
        from price_kb import get_price_kb

        kb = get_price_kb()
    except Exception:
        return None

    for row in items:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name or len(name) < 2 or row.get("kb_hit"):
            continue
        spec = str(row.get("spec") or "").strip()
        ranked = kb.lookup_ranked(name, spec, limit=3)
        if len(ranked) < 2:
            continue
        top, second = ranked[0], ranked[1]
        if top.score - second.score > 0.06:
            continue
        a = f"{top.entry.raw_name}（{top.entry.raw_spec or '-'}）{top.entry.raw_price}"
        b = f"{second.entry.raw_name}（{second.entry.raw_spec or '-'}）{second.entry.raw_price}"
        return ClarifySpec(
            "price_kb_ambiguous",
            f"“{name}”匹配到多个相近物料：{a}；{b}。请补充规格或确认单价。",
            ("material_name", "spec", "unit_price"),
        )
    return None


def _is_patch_verb_only(label: str) -> bool:
    return str(label or "").strip() in {"改", "换", "调", "设置", "设为", "改成", "改为", "换成"}


def _is_auto_convertible_unit_pair(usage_raw: Any, unit_price_raw: Any) -> bool:
    usage = str(usage_raw or "")
    price = str(unit_price_raw or "")
    if not usage or not price:
        return False

    usage_low = usage.lower()
    price_low = price.lower()
    price_norm = price_low.replace("／", "/").replace("每", "/")

    usage_is_sqm = (
        ("㎡" in usage)
        or ("m²" in usage_low)
        or ("m2" in usage_low)
        or ("平方米" in usage)
    )
    price_is_linear_yard = bool(re.search(r"/\s*(码|yd|yard)\b", price_norm))
    price_is_square_yard = ("码²" in price) or ("yd²" in price_low) or ("sqyd" in price_low)
    if usage_is_sqm and price_is_linear_yard and not price_is_square_yard:
        return True

    usage_has_cm = bool(re.search(r"\d+(?:\.\d+)?\s*(厘米|cm)\b", usage, re.I))
    price_is_per_meter = bool(re.search(r"/\s*(米|m)\b", price_norm))
    price_is_per_cm = bool(re.search(r"/\s*(厘米|cm)\b", price_norm, re.I))
    if usage_has_cm and price_is_per_meter and not price_is_per_cm:
        return True

    return False
