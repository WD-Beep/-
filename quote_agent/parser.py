"""Hybrid intent parser for quote follow-up messages.

Rules are the deterministic baseline. An optional Moonshot/KIMI planner may
patch the structured fields, but quote truth is never calculated by the model.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from extra_material_calc import extract_substitution_query
from follow_up_merge import parse_extra_calc_quantity
from intent_router import looks_like_material_substitution


_EXPLAIN_RE = re.compile(
    r"(怎么算|如何算|咋算|怎样算|怎么来的|从哪来|哪来的|计算过程|过程拆解|成本构成|公式|明细怎么来|差距最大|差最多)",
    re.I,
)
_BUSINESS_COMPARE_RE = re.compile(
    r"(业务员|业务算|销售算|手算|对方|和你算|跟你算|差在哪|差多少|相差)",
    re.I,
)
_WHY_RE = re.compile(r"(为什么|为何|为啥|怎么会|不一样|不一致|对不上|差在哪|差异|误差|相差|口径)", re.I)
_ALT_RE = re.compile(r"(替代方案|备选|替代料|替换方案|不合适|不适合|两个|2个|两种|2种)", re.I)
_TRIAL_RE = re.compile(
    r"(试算|试试|看看|看下|临时|先试|先算|不要覆盖|不覆盖|别覆盖|暂时|如果|假设|要是)",
    re.I,
)
_COMMIT_RE = re.compile(
    r"(以这个(?:数量|材料|方案)?为准|以此(?:数量|材料|方案)?为准|按这个报价|就按这个|就按这|"
    r"作为主报价|确认|提交|覆盖主报价|这单就按|本单就按|这次就按|直接按|确定用)",
    re.I,
)
_SAVE_PRICE_KB_RE = re.compile(r"(?:保存|写入|记|录入).{0,6}价格库", re.I)
_QTY_COMMIT_RE = re.compile(r"(?:改成|改为|变更为|调到|调至)\s*(\d{1,7})\s*件?", re.I)
_QTY_RE = re.compile(r"(?<!\d)(\d{1,7})\s*件")
_MARGIN_RE = re.compile(
    r"(?:"
    r"(?:毛利率|毛利|利润率)\s*(?:改|调|设|为|成|到|至|[:：])?\s*(\d{1,2}(?:\.\d+)?)\s*%"
    r"|"
    r"(\d{1,2}(?:\.\d+)?)\s*%\s*(?:的)?\s*(?:毛利率|毛利|利润率)"
    r")"
)
_CALC_RE = re.compile(r"(算|核算|重算|再算|报价|多少钱|什么价|啥价|价格|单价)", re.I)
_PRICE_PATCH_TARGETS = {
    "packaging": re.compile(r"(箱子|纸箱|外箱|包装箱|包装盒|包装袋|包装费|胶袋|opp袋|OPP|PE袋|纸盒)", re.I),
}
_PRICE_PATCH_RE = re.compile(
    r"(?P<label>箱子|纸箱|外箱|包装箱|包装盒|包装袋|包装费|胶袋|opp袋|OPP|PE袋|纸盒)"
    r".{0,12}?"
    r"(?:换成|换|改成|改为|改|调到|调至|按|变成|用)?\s*"
    r"(?P<price>\d+(?:\.\d+)?)\s*"
    r"(?:元|块|RMB|rmb)?\s*(?:/|每)?\s*(?:个|只|pcs?|PCS|件)?",
    re.I,
)
_PROCESSING_FEE_PATCH_RE = re.compile(
    r"加工费.{0,8}?(?:改成|改为|改|调到|调至|按|按到|算|为)?\s*"
    r"(?P<price>\d+(?:\.\d+)?)\s*(?:元|块|RMB|rmb)?",
    re.I,
)
_MOLD_ALLOC_PATCH_RE = re.compile(
    r"(?:模具|开模).{0,10}?(?:分摊|摊销|均摊|摊).{0,8}?"
    r"(?:数量)?(?:改成|改为|改|调到|调至|按|按到|为)?\s*"
    r"(?P<qty>\d{1,7})\s*(?:件|个|pcs|PCS)?",
    re.I,
)
_MATERIAL_PRICE_PATCH_RE = re.compile(
    r"(?P<label>[A-Za-z0-9#\-\+/.]{2,24}|[\u4e00-\u9fffA-Za-z0-9#\-\+/.]{2,24})"
    r".{0,8}?(?:单价)?(?:改成|改为|改|调到|调至|按|按到|换成|为)?\s*"
    r"(?P<price>\d+(?:\.\d+)?)\s*"
    r"(?:元\s*)?(?P<unit>(?:/|每)?\s*(?:码|米|个|只|套|件|kg|KG|公斤|磅|平方|码²|m2|㎡)|一码|一米|一个|一件)?",
    re.I,
)
_PROCESSING_FEE_SHORT_RE = re.compile(
    r"加工费\s*(?:按|为|是|算)?\s*(?P<price>\d+(?:\.\d+)?)\s*(?:元|块|RMB|rmb)?(?:\s*算)?",
    re.I,
)


def understand_message(message: str, *, has_pending_trial: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (understanding, planner_status)."""
    parsed = _rule_understand(message, has_pending_trial=has_pending_trial)
    llm_patch, planner_status = _optional_llm_understand(message, parsed)
    if llm_patch:
        parsed = _merge_understanding(parsed, llm_patch)
    return parsed, planner_status


def _rule_understand(message: str, *, has_pending_trial: bool) -> dict[str, Any]:
    msg = (message or "").strip()
    quantity = _parse_quantity(msg)
    gross_margin = _parse_margin(msg)
    price_patch = _parse_price_patch(msg)
    raw_material_change = looks_like_material_substitution(msg)
    wants_process = bool(
        re.search(
            r"(怎么算|如何算|咋算|怎样算|计算过程|过程拆解|成本构成|公式|明细怎么来)",
            msg,
            re.I,
        )
    ) and not _BUSINESS_COMPARE_RE.search(msg)
    wants_explanation = bool(
        (
            _WHY_RE.search(msg)
            or _BUSINESS_COMPARE_RE.search(msg)
            or re.search(
                r"(怎么来的|从哪来|哪来的|差距最大|差最多|哪个.*(?:材料|物料).*(?:差距|差|大|贵))",
                msg,
                re.I,
            )
        )
        and not _has_param_signal(msg)
    )
    wants_alternatives = bool(_ALT_RE.search(msg))
    trial_requested = bool(_TRIAL_RE.search(msg))
    commit_requested = bool(_COMMIT_RE.search(msg) or _QTY_COMMIT_RE.search(msg))

    if trial_requested:
        commit_requested = False

    alt_only = (
        wants_alternatives
        and not _CALC_RE.search(msg)
        and quantity is None
        and gross_margin is None
    )
    material_for_calc = bool(raw_material_change and not alt_only)
    wants_explain_only = bool(
        wants_explanation
        and not material_for_calc
        and quantity is None
        and gross_margin is None
        and not price_patch
    )

    if material_for_calc or quantity is not None or gross_margin is not None or price_patch:
        trial_requested = trial_requested or not commit_requested

    has_direct_change = quantity is not None or gross_margin is not None or material_for_calc or bool(price_patch)
    return {
        "wants_process": wants_process,
        "wants_explanation": wants_explanation,
        "wants_explain_only": wants_explain_only,
        "material_change": material_for_calc,
        "material_query": _clean_material_query(extract_substitution_query(msg)) if raw_material_change else "",
        "quantity": quantity,
        "gross_margin_rate": gross_margin,
        "price_patch": price_patch,
        "trial_requested": trial_requested,
        "commit_requested": commit_requested,
        "wants_alternatives": wants_alternatives,
        "needs_clarification": False,
        "commit_pending_trial": commit_requested and not has_direct_change and has_pending_trial,
        "wants_save_to_price_kb": bool(_SAVE_PRICE_KB_RE.search(msg)),
        "raw": msg,
        "parser": "rules",
    }


def _optional_llm_understand(
    message: str,
    fallback: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    status = {"used": False, "error": "", "fallback": "rule"}
    if os.environ.get("QUOTATION_AGENT_USE_LLM_PLANNER", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None, status
    try:
        from quotation_agent.moonshot_client import chat_completions, default_text_model, moonshot_api_key

        if not moonshot_api_key():
            status["error"] = "missing_api_key"
            return None, status
        prompt = (
            "你是报价助手的意图解析器，只输出 JSON。不要计算价格。字段："
            "wants_process(bool), wants_explanation(bool), material_change(bool), material_query(str), "
            "quantity(int|null), gross_margin_rate(float|null), trial_requested(bool), "
            "commit_requested(bool), wants_alternatives(bool), needs_clarification(bool), "
            "price_patch(object|null: {target,label,field,value,unit})。"
            f"\n用户：{message}\n规则解析：{json.dumps(fallback, ensure_ascii=False)}"
        )
        raw = chat_completions(
            messages=[{"role": "user", "content": prompt}],
            model=os.environ.get("QUOTATION_AGENT_PLANNER_MODEL") or default_text_model(),
            temperature=0,
            max_tokens=700,
            timeout_sec=8,
        )
        data = _extract_json_object(raw)
        if data:
            status["used"] = True
            status["fallback"] = ""
            return data, status
    except Exception as exc:  # noqa: BLE001
        status["error"] = str(exc)
    return None, status


def _merge_understanding(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key in (
        "wants_process",
        "wants_explanation",
        "material_change",
        "material_query",
        "trial_requested",
        "commit_requested",
        "wants_alternatives",
        "needs_clarification",
    ):
        if key in patch:
            out[key] = patch[key]
    if isinstance(patch.get("price_patch"), dict):
        parsed_patch = _normalize_price_patch(patch["price_patch"])
        if parsed_patch:
            out["price_patch"] = parsed_patch
    if patch.get("quantity") is not None:
        try:
            out["quantity"] = int(patch["quantity"])
        except (TypeError, ValueError):
            pass
    if patch.get("gross_margin_rate") is not None:
        try:
            out["gross_margin_rate"] = float(patch["gross_margin_rate"])
        except (TypeError, ValueError):
            pass
    out["material_query"] = _clean_material_query(str(out.get("material_query") or ""))
    out["parser"] = "llm_plus_rules"
    return out


def _extract_json_object(text: str) -> dict[str, Any]:
    s = str(text or "")
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(s[start : end + 1])
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _parse_quantity(message: str) -> int | None:
    if re.search(r"(?:模具|开模).{0,12}(?:分摊|摊销|均摊|摊)", message or ""):
        return None
    q = parse_extra_calc_quantity(message)
    if q is not None:
        return q
    m = _QTY_RE.search(message or "")
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if n > 0 else None


def _parse_margin(message: str) -> float | None:
    m = _MARGIN_RE.search(message or "")
    if not m:
        return None
    try:
        v = float(next(x for x in m.groups() if x is not None))
    except ValueError:
        return None
    return v / 100.0 if v > 1 else v


def _parse_price_patch(message: str) -> dict[str, Any] | None:
    msg = str(message or "")
    m = _PRICE_PATCH_RE.search(msg)
    if m:
        label = str(m.group("label") or "").strip()
        try:
            value = float(m.group("price"))
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        target = ""
        for name, pat in _PRICE_PATCH_TARGETS.items():
            if pat.search(label):
                target = name
                break
        if target:
            return {
                "target": target,
                "label": label,
                "field": "unit_price",
                "value": value,
                "unit": "元/个",
            }

    m_proc = _PROCESSING_FEE_PATCH_RE.search(msg) or _PROCESSING_FEE_SHORT_RE.search(msg)
    if m_proc:
        try:
            value = float(m_proc.group("price"))
        except (TypeError, ValueError):
            return None
        if value >= 0:
            return {
                "target": "processing_fee",
                "label": "加工费",
                "field": "processing_fee",
                "value": value,
                "unit": "元/件",
            }

    m_mold = _MOLD_ALLOC_PATCH_RE.search(msg)
    if m_mold:
        try:
            value = int(m_mold.group("qty"))
        except (TypeError, ValueError):
            return None
        if value > 0:
            return {
                "target": "mold_allocation_quantity",
                "label": "模具分摊数量",
                "field": "quantity",
                "value": value,
                "unit": "件",
            }

    m_mat = _MATERIAL_PRICE_PATCH_RE.search(msg)
    if not m_mat:
        return None
    label = str(m_mat.group("label") or "").strip(" ，,。")
    if _PRICE_PATCH_TARGETS["packaging"].search(label) or "加工费" in label or "模具" in label:
        return None
    try:
        value = float(m_mat.group("price"))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    unit = _normalize_material_price_unit(str(m_mat.group("unit") or ""))
    return {
        "target": "material_unit_price",
        "label": label,
        "field": "unit_price",
        "value": value,
        "unit": unit,
    }


def _normalize_material_price_unit(raw: str) -> str:
    u = re.sub(r"\s+", "", str(raw or ""))
    if not u:
        return "元/件"
    if u.startswith("元"):
        return u
    mapping = {
        "一码": "元/码",
        "一米": "元/米",
        "一个": "元/个",
        "一件": "元/件",
        "/码": "元/码",
        "码": "元/码",
        "/米": "元/米",
        "米": "元/米",
        "/个": "元/个",
        "个": "元/个",
        "/件": "元/件",
        "件": "元/件",
    }
    for key, val in mapping.items():
        if u == key or u.endswith(key):
            return val
    return f"元/{u.lstrip('/')}"


def _normalize_price_patch(data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        value = float(data.get("value"))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    label = str(data.get("label") or data.get("target") or "").strip()
    target = str(data.get("target") or "").strip().lower()
    if target in {"processing_fee", "mold_allocation_quantity", "material_unit_price"}:
        return {
            "target": target,
            "label": label or target,
            "field": str(data.get("field") or ("quantity" if target == "mold_allocation_quantity" else "unit_price")),
            "value": value,
            "unit": str(data.get("unit") or ("件" if target == "mold_allocation_quantity" else "元/件")),
        }
    if target not in _PRICE_PATCH_TARGETS:
        for name, pat in _PRICE_PATCH_TARGETS.items():
            if pat.search(label):
                target = name
                break
    if target not in _PRICE_PATCH_TARGETS:
        return None
    return {
        "target": target,
        "label": label or target,
        "field": "unit_price",
        "value": value,
        "unit": str(data.get("unit") or "元/个"),
    }


def _has_param_signal(message: str) -> bool:
    return bool(
        _QTY_RE.search(message or "")
        or _MARGIN_RE.search(message or "")
        or _parse_price_patch(message or "")
        or looks_like_material_substitution(message or "")
    )


def _clean_material_query(text: str) -> str:
    cleaned = re.sub(r"^(如果|要是|假设)?\s*(换成|换|改成|改用|用)?", "", str(text or "").strip())
    cleaned = re.sub(r"(不合适|不适合|合不合适|适不适合)", "", cleaned)
    cleaned = re.sub(
        r"(试试|看看|看下|再帮我算下|帮我算下|再算|重算|报价|多少钱|多少|呢|吧|吗|以此为准|以这个为准)$",
        "",
        cleaned,
    )
    return cleaned.strip(" ，,。！？?")[:40]
