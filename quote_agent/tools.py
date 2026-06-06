"""Local tools used by the quote agent nodes.

This module wraps existing deterministic quote functions. It deliberately does
not contain LLM price calculation.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from extra_material_calc import apply_material_substitution, find_target_row_index
from follow_up_merge import merge_follow_up_text
from missing_data_enricher import enrich_missing_quote_data
from price_kb import get_price_kb
from quote_engine import calculate_quote
from quote_explain import (
    build_explain_response_payload,
    build_local_quote_explanation_text,
    build_process_explainer_payload,
)

_PACKAGING_NAME_RE = re.compile(
    r"包装|OPP|胶袋|自封袋|纸箱|纸盒|纸卡|吊牌|标贴|封箱|包装袋|外箱|箱子|Packing|pe袋",
    re.IGNORECASE,
)
_DIGIT_RE = re.compile(r"-?\d+(?:\.\d+)?")


def build_process_payload(quote_result: dict[str, Any]) -> dict[str, Any]:
    return build_process_explainer_payload(quote_result or {})


def build_local_explanation(quote_result: dict[str, Any], user_question: str) -> str:
    return build_local_quote_explanation_text(quote_result or {}, user_question=user_question)


def build_explain_response(
    quote_result: dict[str, Any],
    user_question: str,
    *,
    llm_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """报价解释模式：只读上一单结果，不调用 calculate_quote。"""
    sync = None
    if isinstance(quote_result, dict):
        raw = quote_result.get("price_kb_sync")
        if isinstance(raw, dict):
            sync = raw
    return build_explain_response_payload(
        quote_result or {},
        user_question=user_question,
        price_kb_sync=sync,
        llm_status=llm_status,
    )


def apply_substitution_to_payload(
    payload: dict[str, Any],
    user_message: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None, {"error": "当前报价没有可替换的物料明细，请先完成一次有效报价。"}, {}
    holder: dict[str, Any] = {}
    try:
        kb = get_price_kb()
    except Exception:
        kb = None
    new_items, meta = apply_material_substitution(
        list(items),
        user_message,
        kb=kb,
        llm_status_holder=holder,
    )
    if new_items is None:
        return None, dict(meta or {}), holder
    out = copy.deepcopy(payload)
    out["items"] = new_items
    return out, dict(meta or {}), holder


def patch_payload_params(
    payload: dict[str, Any],
    user_message: str,
    understood: dict[str, Any],
) -> dict[str, Any]:
    out = merge_follow_up_text(user_message, payload)
    q = understood.get("quantity")
    if q is not None:
        try:
            out["quantities"] = [int(q)]
        except (TypeError, ValueError):
            pass
    margin = understood.get("gross_margin_rate")
    if margin is not None:
        try:
            out["gross_margin_rate"] = float(margin)
        except (TypeError, ValueError):
            pass
    return out


def build_param_patch_meta(
    before_payload: dict[str, Any],
    after_payload: dict[str, Any],
    understood: dict[str, Any],
) -> dict[str, Any]:
    q = understood.get("quantity")
    if q is None:
        return {}
    old_q = _first_payload_quantity(before_payload)
    try:
        new_q = int(q)
    except (TypeError, ValueError):
        return {}
    return {
        "patch_type": "quantity",
        "target": "quantity",
        "target_label": "数量",
        "target_row": "数量阶梯",
        "old_value": old_q,
        "new_value": new_q,
        "delta": new_q - old_q if old_q else None,
    }


def apply_price_patch_to_payload(
    payload: dict[str, Any],
    price_patch: object,
    base_quote_result: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Apply a local unit-price patch to a copied payload for trial recalculation."""
    if not isinstance(price_patch, dict):
        return None, {"error": "没有识别到要改哪个单价。"}
    target = str(price_patch.get("target") or "").strip().lower()
    try:
        value = float(price_patch.get("value"))
    except (TypeError, ValueError):
        return None, {"error": "没有识别到有效的新单价。"}
    if value <= 0:
        return None, {"error": "新单价必须大于 0。"}

    out = copy.deepcopy(payload or {})
    if target == "processing_fee":
        old_value = _payload_float(out, "processing_fee", _first_tier_number(base_quote_result, "processing_fee", 12.0))
        out["processing_fee"] = round(value, 4)
        return out, {
            "patch_type": "processing_fee",
            "target": target,
            "target_label": "加工费",
            "target_row": "加工费",
            "old_value": old_value,
            "new_value": round(value, 4),
            "old_amount": old_value,
            "new_amount": round(value, 4),
            "delta": round(value - old_value, 2),
            "old_unit_price": f"{old_value:g}元/件",
            "new_unit_price": f"{value:g}元/件",
        }

    if target == "mold_allocation_quantity":
        qty = int(round(value))
        if qty <= 0:
            return None, {"error": "模具分摊数量必须大于 0。"}
        old_q = _first_payload_quantity(out) or int(_first_tier_number(base_quote_result, "quantity", 0))
        out["quantities"] = [qty]
        return out, {
            "patch_type": "mold_allocation_quantity",
            "target": target,
            "target_label": "模具分摊数量",
            "target_row": "模具分摊数量",
            "old_value": old_q,
            "new_value": qty,
            "delta": qty - old_q if old_q else None,
            "old_unit_price": f"{old_q}件" if old_q else "",
            "new_unit_price": f"{qty}件",
        }

    if target == "material_unit_price":
        return _apply_material_unit_price_patch(out, price_patch, value)

    if target != "packaging":
        return None, {"error": "这类单价暂时还不能自动试算，请说明要改的物料行。"}

    label = str(price_patch.get("label") or "包装/箱子").strip()
    base_rows = (
        base_quote_result.get("detail_rows")
        if isinstance(base_quote_result, dict) and isinstance(base_quote_result.get("detail_rows"), list)
        else []
    )
    old_unit, old_amount = _first_packaging_price_from_rows(base_rows)

    items = out.get("items")
    if isinstance(items, list):
        matches = [i for i, row in enumerate(items) if isinstance(row, dict) and _PACKAGING_NAME_RE.search(str(row.get("name") or ""))]
        if len(matches) > 1:
            names = "、".join(str(items[i].get("name") or "") for i in matches[:3] if isinstance(items[i], dict))
            return None, {"error": f"找到多条包装相关物料（{names}），请说明要改外箱还是单个包装袋。"}
        if len(matches) == 1:
            idx = matches[0]
            row = copy.deepcopy(items[idx])
            old_unit = str(row.get("unit_price") or old_unit or "")
            try:
                old_amount = float(row.get("amount") or old_amount or 0.0)
            except (TypeError, ValueError):
                old_amount = old_amount or 0.0
            qty = _usage_count(row.get("usage")) or 1.0
            row["unit_price"] = f"{value:g}元/个"
            row["amount"] = round(value * qty, 2)
            row["amount_ai"] = False
            row["unit_price_ai"] = False
            row["calc_note"] = f"用户追问试算：{label}单价改为 {value:g}元/个。"
            items[idx] = row
            out["items"] = items
            return out, {
                "patch_type": "packaging_unit_price",
                "target": target,
                "target_label": str(row.get("name") or label),
                "target_row": str(row.get("name") or label),
                "source": "item_row",
                "row_index": idx,
                "old_unit_price": old_unit,
                "old_amount": old_amount,
                "new_unit_price": f"{value:g}元/个",
                "new_amount": row["amount"],
                "old_value": old_amount,
                "new_value": row["amount"],
                "delta": round(float(row["amount"]) - float(old_amount or 0.0), 2),
            }

    if not old_unit and not old_amount:
        return None, {"error": "上一单里没有找到包装费/纸箱/外箱行，请确认要把哪一项改为这个单价。"}
    out["packaging_addon_per_piece"] = value
    return out, {
        "patch_type": "packaging_unit_price",
        "target": target,
        "target_label": label,
        "target_row": label,
        "source": "packaging_addon_per_piece",
        "old_unit_price": old_unit or "",
        "old_amount": old_amount,
        "new_unit_price": f"{value:g}元/个",
        "new_amount": round(value, 2),
        "old_value": old_amount,
        "new_value": round(value, 2),
        "delta": round(value - float(old_amount or 0.0), 2),
    }


def calculate_local_quote(
    payload: dict[str, Any],
    *,
    apply_output_gate: Any = None,
) -> dict[str, Any]:
    enriched_payload, enrichment_report = enrich_missing_quote_data(payload)
    quote = calculate_quote(enriched_payload)
    quote["missing_data_enrichment"] = enrichment_report
    if apply_output_gate is not None:
        apply_output_gate(quote, enriched_payload)
    return quote


def has_effective_material_pricing(items: object) -> bool:
    if not isinstance(items, list) or not items:
        return False
    for row in items:
        if not isinstance(row, dict):
            continue
        try:
            if float(row.get("amount") or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
        if re.search(r"\d", str(row.get("unit_price") or "")):
            return True
    return False


def suggest_alternatives(query: str, payload: dict[str, Any], user_message: str) -> str:
    items = payload.get("items")
    target_name = ""
    if isinstance(items, list):
        dict_items = [r for r in items if isinstance(r, dict)]
        idx = find_target_row_index(dict_items, user_message)
        if idx is not None and 0 <= idx < len(dict_items):
            target_name = str(dict_items[idx].get("name") or "").strip()
    entries: list[Any] = []
    try:
        kb = get_price_kb()
        entries = kb.suggest_entries_for_query(query or target_name or "材料", limit=6)
    except Exception:
        entries = []
    lines = ["可以，先不覆盖当前报价。我给两个可落地的替代方向："]
    picked: list[str] = []
    for ent in entries:
        name = str(getattr(ent, "raw_name", "") or "").strip()
        price = str(getattr(ent, "raw_price", "") or "").strip()
        if name:
            label = f"{name}{f'（{price}）' if price else ''}"
            if label not in picked:
                picked.append(label)
        if len(picked) >= 2:
            break
    if not picked:
        picked = [
            "同规格涤纶/牛津布：通常更稳、更容易采购，适合控成本。",
            "较高D数尼龙或防水涂层布：质感和强度更好，但要复核单价和交期。",
        ]
    for i, item in enumerate(picked[:2], start=1):
        lines.append(f"{i}. {item}")
    lines.append("要我按其中某一个试算，可以直接说「用第1个试算500件」。")
    return "\n".join(lines)


def status_with_plan(state: dict[str, Any]) -> dict[str, Any]:
    status = dict(state.get("llm_status") or {})
    status["agent"] = "langgraph_quote_agent"
    status["understood"] = state.get("understood") or {}
    status["agent_actions"] = state.get("actions") or []
    return status


def quote_metadata(state: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    actions = list(state.get("actions") or [])
    mode = str(state.get("commit_mode") or "none")
    base = state.get("base_quote_result") or {}
    meta = {
        "agent_workflow": True,
        "mode": mode,
        "tools": actions,
        "base_quote_id": state.get("quote_id"),
        "cost_delta_per_piece": _cost_delta(base, quote),
    }
    working = state.get("working_payload") if isinstance(state.get("working_payload"), dict) else {}
    if mode == "trial":
        meta["is_extra_calc"] = True
        meta["calc_quantity"] = (
            working.get("quantities", [None])[0]
            if isinstance(working.get("quantities"), list)
            else None
        )
        meta["original_quantity"] = _original_reference_quantity(base, state.get("base_payload") or {})
    mat = state.get("material_meta") if isinstance(state.get("material_meta"), dict) else {}
    if mat:
        meta.update(
            {
                "is_extra_material_calc": "substitute_material" in actions,
                "old_material_label": mat.get("old_material_label"),
                "new_material_label": mat.get("new_material_label") or mat.get("query_phrase"),
                "material_total_delta": round(_material_total(quote) - _material_total(base), 2),
            }
        )
    price_patch = state.get("price_patch_meta") if isinstance(state.get("price_patch_meta"), dict) else {}
    if price_patch:
        meta.update(
            {
                "is_price_patch_calc": "patch_unit_price" in actions,
                "price_patch_target": price_patch.get("target"),
                "price_patch_target_label": price_patch.get("target_label"),
                "price_patch_old_unit_price": price_patch.get("old_unit_price"),
                "price_patch_new_unit_price": price_patch.get("new_unit_price"),
                "price_patch_old_amount": price_patch.get("old_amount"),
                "price_patch_new_amount": price_patch.get("new_amount"),
            }
        )
    param_patch = state.get("param_patch_meta") if isinstance(state.get("param_patch_meta"), dict) else {}
    if param_patch:
        meta.update(
            {
                "is_param_patch_calc": "patch_params" in actions,
                "param_patch_target": param_patch.get("target"),
                "param_patch_old_value": param_patch.get("old_value"),
                "param_patch_new_value": param_patch.get("new_value"),
            }
        )
    return meta


def build_quote_patch(state: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    base = state.get("base_quote_result") if isinstance(state.get("base_quote_result"), dict) else {}
    old_cost = _first_tier_cost(base)
    new_cost = _first_tier_cost(quote)
    meta = state.get("price_patch_meta") if isinstance(state.get("price_patch_meta"), dict) else {}
    if not meta:
        meta = state.get("param_patch_meta") if isinstance(state.get("param_patch_meta"), dict) else {}
    if not meta:
        return {}
    patch = {
        "patch_type": meta.get("patch_type") or meta.get("target") or "quote_patch",
        "target_row": meta.get("target_row") or meta.get("target_label") or meta.get("target") or "",
        "old_value": meta.get("old_value", meta.get("old_amount", meta.get("old_unit_price"))),
        "new_value": meta.get("new_value", meta.get("new_amount", meta.get("new_unit_price"))),
        "delta": meta.get("delta"),
        "original_cost": old_cost,
        "new_cost": new_cost,
        "cost_delta": round(new_cost - old_cost, 2),
        "original_cost_text": _money(old_cost),
        "new_cost_text": _money(new_cost),
        "cost_delta_text": _signed_money(new_cost - old_cost),
    }
    for key in ("old_unit_price", "new_unit_price", "old_amount", "new_amount", "target", "source", "row_index"):
        if key in meta:
            patch[key] = meta.get(key)
    return patch


def build_patch_message(quote_patch: dict[str, Any]) -> str:
    if not quote_patch:
        return ""
    label = str(quote_patch.get("target_row") or "该项")
    ptype = str(quote_patch.get("patch_type") or "")
    old_cost = quote_patch.get("original_cost_text") or _money(quote_patch.get("original_cost"))
    new_cost = quote_patch.get("new_cost_text") or _money(quote_patch.get("new_cost"))
    delta = quote_patch.get("cost_delta_text") or _signed_money(quote_patch.get("cost_delta") or 0)
    prefix = "已基于上一单做局部试算（未覆盖正式报价、未写入价格库）"
    if ptype == "packaging_unit_price":
        old_pack = _money(quote_patch.get("old_amount"))
        new_pack = _money(quote_patch.get("new_amount"))
        return (
            f"{prefix}：{label}。"
            f"原包装费 {old_pack}/件，现包装费 {new_pack}/件；"
            f"原单包系统成本 {old_cost}/件，新单包系统成本 {new_cost}/件，差额 {delta}/件。"
        )
    if ptype == "quantity":
        old_q = quote_patch.get("old_value")
        new_q = quote_patch.get("new_value")
        return (
            f"{prefix}：{label} {old_q}件 -> {new_q}件；"
            f"原单包系统成本 {old_cost}/件，新单包系统成本 {new_cost}/件，差额 {delta}/件。"
        )
    if ptype == "processing_fee":
        old_fee = quote_patch.get("old_unit_price", quote_patch.get("old_value"))
        new_fee = quote_patch.get("new_unit_price", quote_patch.get("new_value"))
        return (
            f"{prefix}：{label} {old_fee} -> {new_fee}；"
            f"原单包系统成本 {old_cost}/件，新单包系统成本 {new_cost}/件，差额 {delta}/件。"
        )
    if ptype == "material_unit_price":
        old_value = quote_patch.get("old_unit_price", quote_patch.get("old_value"))
        new_value = quote_patch.get("new_unit_price", quote_patch.get("new_value"))
        old_amt = _money(quote_patch.get("old_amount"))
        new_amt = _money(quote_patch.get("new_amount"))
        return (
            f"{prefix}：{label} 单价 {old_value} -> {new_value}（行金额 {old_amt} -> {new_amt}）；"
            f"原单包系统成本 {old_cost}/件，新单包系统成本 {new_cost}/件，差额 {delta}/件。"
        )
    old_value = quote_patch.get("old_unit_price", quote_patch.get("old_value"))
    new_value = quote_patch.get("new_unit_price", quote_patch.get("new_value"))
    return (
        f"{prefix}：{label} {old_value} -> {new_value}；"
        f"原单包系统成本 {old_cost}/件，新单包系统成本 {new_cost}/件，差额 {delta}/件。"
    )


def material_total(result: dict[str, Any]) -> float:
    return _material_total(result)


def _material_total(result: dict[str, Any]) -> float:
    try:
        return float(result.get("material_total") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _tier_unit_cost(tier: object) -> float:
    if not isinstance(tier, dict):
        return 0.0
    try:
        return float(tier.get("cost_before_margin") or tier.get("total_cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _cost_delta(old_result: dict[str, Any], new_result: dict[str, Any]) -> float:
    old_tiers = old_result.get("tiers") if isinstance(old_result.get("tiers"), list) else []
    new_tiers = new_result.get("tiers") if isinstance(new_result.get("tiers"), list) else []
    old_cost = _tier_unit_cost(old_tiers[0]) if old_tiers else 0.0
    new_cost = _tier_unit_cost(new_tiers[0]) if new_tiers else 0.0
    return round(new_cost - old_cost, 2)


def _usage_count(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        n = float(m.group(1))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _first_packaging_price_from_rows(rows: object) -> tuple[str, float]:
    if not isinstance(rows, list):
        return "", 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not _PACKAGING_NAME_RE.search(str(row.get("name") or "")):
            continue
        unit = str(row.get("unit_price") or "").strip()
        try:
            amount = float(row.get("amount") or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        return unit, amount
    return "", 0.0


def _original_reference_quantity(last_res: dict[str, Any], base_payload: dict[str, Any]) -> int:
    tiers = last_res.get("tiers") if isinstance(last_res.get("tiers"), list) else []
    if tiers and isinstance(tiers[0], dict):
        try:
            return int(tiers[0].get("quantity") or 0)
        except (TypeError, ValueError):
            pass
    raw_q = base_payload.get("quantities") if isinstance(base_payload, dict) else None
    if isinstance(raw_q, (list, tuple)) and raw_q:
        try:
            return int(raw_q[0])
        except (TypeError, ValueError):
            pass
    return 0


def _payload_float(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(payload.get(key) if payload.get(key) not in (None, "") else default)
    except (TypeError, ValueError):
        return float(default or 0.0)


def _parse_price_number(value: object) -> float:
    m = _DIGIT_RE.search(str(value or "").replace(",", ""))
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except (TypeError, ValueError):
        return 0.0


def _first_payload_quantity(payload: dict[str, Any]) -> int:
    raw = payload.get("quantities") if isinstance(payload, dict) else None
    if isinstance(raw, (list, tuple)) and raw:
        try:
            return int(raw[0])
        except (TypeError, ValueError):
            return 0
    return 0


def _first_tier_number(result: dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    tiers = result.get("tiers") if isinstance(result, dict) and isinstance(result.get("tiers"), list) else []
    if tiers and isinstance(tiers[0], dict):
        try:
            return float(tiers[0].get(key) if tiers[0].get(key) not in (None, "") else default)
        except (TypeError, ValueError):
            return float(default or 0.0)
    return float(default or 0.0)


def _first_tier_cost(result: dict[str, Any] | None) -> float:
    tiers = result.get("tiers") if isinstance(result, dict) and isinstance(result.get("tiers"), list) else []
    if tiers and isinstance(tiers[0], dict):
        return _tier_unit_cost(tiers[0])
    return 0.0


def _money(value: object) -> str:
    try:
        return f"{float(value):.2f}元"
    except (TypeError, ValueError):
        return "0.00元"


def _signed_money(value: object) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:+.2f}元"


def _normalize_match_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _material_row_matches(row: dict[str, Any], label: str) -> bool:
    lab = _normalize_match_text(label)
    hay = _normalize_match_text(f"{row.get('name', '')} {row.get('spec', '')}")
    if not lab or _PACKAGING_NAME_RE.search(hay):
        return False
    if lab in hay:
        return True
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9#\-\+/.]{2,}|[\u4e00-\u9fff]{2,}", label)]
    return bool(tokens) and all(t in hay for t in tokens)


def _apply_material_unit_price_patch(
    payload: dict[str, Any],
    price_patch: dict[str, Any],
    value: float,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    label = str(price_patch.get("label") or "").strip()
    if not label:
        return None, {"error": "没有识别到要改哪个材料。"}
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None, {"error": "当前报价没有可试算的物料明细。"}
    matches = [i for i, row in enumerate(items) if isinstance(row, dict) and _material_row_matches(row, label)]
    if not matches:
        return None, {"error": f"上一单明细里没有找到「{label}」这一行，请确认要改哪个材料。"}
    if len(matches) > 1:
        names = "、".join(str(items[i].get("name") or "") for i in matches[:4] if isinstance(items[i], dict))
        return None, {"error": f"找到多条可能匹配「{label}」的物料（{names}），请说得更具体一点。"}
    idx = matches[0]
    row = copy.deepcopy(items[idx])
    old_unit = str(row.get("unit_price") or "").strip()
    old_amount = _payload_float(row, "amount", 0.0)
    old_price = _parse_price_number(old_unit)
    unit = str(price_patch.get("unit") or "元/件").strip() or "元/件"
    new_unit = f"{value:g}{unit}" if unit.startswith("元") else f"{value:g}{unit}"
    if old_price > 0 and old_amount > 0:
        new_amount = round(old_amount * (value / old_price), 2)
    else:
        qty = _usage_count(row.get("usage")) or 1.0
        new_amount = round(value * qty, 2)
    row["unit_price"] = new_unit
    row["amount"] = new_amount
    row["amount_ai"] = False
    row["unit_price_ai"] = False
    row["calc_note"] = f"用户追问试算：{label} 单价改为 {new_unit}。"
    items[idx] = row
    payload["items"] = items
    return payload, {
        "patch_type": "material_unit_price",
        "target": "material_unit_price",
        "target_label": str(row.get("name") or label),
        "target_row": str(row.get("name") or label),
        "row_index": idx,
        "old_unit_price": old_unit,
        "new_unit_price": new_unit,
        "old_amount": old_amount,
        "new_amount": new_amount,
        "old_value": old_amount,
        "new_value": new_amount,
        "delta": round(new_amount - old_amount, 2),
    }
