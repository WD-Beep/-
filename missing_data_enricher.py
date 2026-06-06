"""报价前缺失数据补全。

第一版只做可追溯、低风险的确定性补全：
- 有用量和单价但小计缺失/为 0 时，计算 amount。
- 有成品尺寸且未显式包装费时，提示报价引擎按包装规则加计。

不在这里编造供应商单价；高风险缺失只记录到报告，留给知识库/人工复核。
"""
from __future__ import annotations

import copy
import re
from typing import Any

from quote_engine import _estimate_packaging_addon


_MISSING_TEXT = {"", "-", "—", "无", "空", "none", "null", "nan"}
_PACKAGING_NAME_RE = re.compile(
    r"包装|OPP|胶袋|自封袋|纸箱|纸盒|纸卡|吊牌|标贴|封箱|包装袋|外箱|Packing|pe袋",
    re.IGNORECASE,
)


def enrich_missing_quote_data(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (enriched_payload, report)."""
    out = copy.deepcopy(payload or {})
    rows = out.get("items")
    if not isinstance(rows, list):
        return out, _empty_report()

    report = _empty_report()
    enriched_rows: list[Any] = []
    for idx, raw in enumerate(rows):
        if not isinstance(raw, dict):
            enriched_rows.append(raw)
            continue
        row = dict(raw)
        name = str(row.get("name") or "").strip()
        usage = str(row.get("usage") or row.get("用量") or "").strip()
        unit_price = str(row.get("unit_price") or row.get("单价参考") or "").strip()
        amount_missing = _is_missing_amount(row.get("amount"))

        if amount_missing:
            calc = _calc_amount_from_usage_price(usage, unit_price)
            if calc is not None:
                row["amount"] = round(calc, 2)
                row["amount_ai"] = True
                row["source"] = "ai"
                row["ai_confidence"] = min(float(row.get("ai_confidence") or 0.82), 0.82)
                reason = "小计缺失：按已识别用量×单价自动补全，未改动用量和单价。"
                row["ai_reason"] = _append_reason(row.get("ai_reason"), reason)
                row["calc_note"] = _append_reason(row.get("calc_note"), f"{reason} 金额≈{calc:.2f}元。")
                report["filled"].append(
                    {
                        "row_index": idx,
                        "name": name,
                        "field": "amount",
                        "value": round(calc, 2),
                        "source": "deterministic_calc",
                        "confidence": 0.82,
                        "reason": reason,
                    }
                )
            elif not _is_missing_text(usage) or not _is_missing_text(unit_price):
                report["unresolved"].append(
                    {
                        "row_index": idx,
                        "name": name,
                        "field": "amount",
                        "reason": "小计缺失，但用量或单价单位无法安全相乘，未自动补。",
                    }
                )
        elif _truthy(row.get("amount_ai")):
            report["filled"].append(
                {
                    "row_index": idx,
                    "name": name,
                    "field": "amount",
                    "value": round(float(row.get("amount") or 0), 2),
                    "source": "upstream_amount_fill",
                    "confidence": float(row.get("ai_confidence") or 0.76),
                    "reason": "上游补全流程已补小计，本模块纳入缺失数据审计报告。",
                }
            )

        if _is_missing_text(usage):
            report["unresolved"].append(
                {
                    "row_index": idx,
                    "name": name,
                    "field": "usage",
                    "reason": "用量缺失，需要结构说明、尺寸或人工公式补充。",
                }
            )
        if _is_missing_text(unit_price):
            report["unresolved"].append(
                {
                    "row_index": idx,
                    "name": name,
                    "field": "unit_price",
                    "reason": "单价缺失，需要知识库、历史报价或供应商价补充。",
                }
            )
        enriched_rows.append(row)

    out["items"] = enriched_rows
    packaging = _maybe_prepare_packaging_estimate(out, enriched_rows)
    if packaging:
        report["filled"].append(packaging)
        out.setdefault("missing_data_flags", {})
        if isinstance(out["missing_data_flags"], dict):
            out["missing_data_flags"]["packaging_estimated"] = True

    report["filled_count"] = len(report["filled"])
    report["unresolved_count"] = len(report["unresolved"])
    report["enabled"] = True
    out["missing_data_enrichment"] = report
    return out, report


def _empty_report() -> dict[str, Any]:
    return {
        "enabled": False,
        "filled_count": 0,
        "unresolved_count": 0,
        "filled": [],
        "unresolved": [],
    }


def _is_missing_text(value: Any) -> bool:
    text = str(value or "").strip()
    return text.lower() in _MISSING_TEXT


def _is_missing_amount(value: Any) -> bool:
    if value is None or str(value).strip() == "":
        return True
    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        return True


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def _first_number(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", str(text or "").replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _calc_amount_from_usage_price(usage: str, unit_price: str) -> float | None:
    qty = _first_number(usage)
    price = _first_number(unit_price)
    if qty is None or price is None or qty <= 0 or price <= 0:
        return None
    converted = _convert_qty_to_price_unit(qty, usage, unit_price)
    if converted is not None:
        return converted * price
    usage_u = _unit_family(usage)
    price_u = _unit_family(unit_price)
    if usage_u and price_u and usage_u != price_u:
        return None
    return qty * price


def _unit_family(text: str) -> str:
    raw = str(text or "")
    tl = raw.lower()
    if "码²" in raw or "yd²" in tl or "㎡" in raw or "m²" in tl or "平方" in raw:
        return "area"
    if "cm" in tl or "厘米" in raw or "米" in raw or re.search(r"\bm\b", tl) or "码" in raw or "yd" in tl:
        return "length"
    if re.search(r"个|只|粒|颗|枚|pcs|pc|套|条|件|处", raw, re.I):
        return "piece"
    return ""


def _convert_qty_to_price_unit(qty: float, usage: str, unit_price: str) -> float | None:
    u = str(usage or "").lower()
    p = str(unit_price or "").lower()
    if ("cm" in u or "厘米" in usage) and ("米" in unit_price or re.search(r"/\s*m\b", p)):
        return qty / 100.0
    if ("米" in usage or re.search(r"\bm\b", u)) and ("cm" in p or "厘米" in unit_price):
        return qty * 100.0
    if ("码" in usage or "yd" in u) and ("米" in unit_price or re.search(r"/\s*m\b", p)):
        return qty * 0.9144
    if ("米" in usage or re.search(r"\bm\b", u)) and ("码" in unit_price or "yd" in p):
        return qty / 0.9144
    return None


def _append_reason(existing: Any, addition: str) -> str:
    old = str(existing or "").strip()
    add = str(addition or "").strip()
    if not old:
        return add
    if add and add not in old:
        return f"{old}；{add}"
    return old


def _maybe_prepare_packaging_estimate(payload: dict[str, Any], rows: list[Any]) -> dict[str, Any] | None:
    if _has_packaging_amount(rows):
        return None
    if str(payload.get("packaging_addon_per_piece") or "").strip():
        return None
    estimated = _estimate_packaging_addon(payload)
    if estimated is None:
        return None
    fee, note = estimated
    dims = []
    size = payload.get("product_size")
    if isinstance(size, dict):
        for key in ("length_cm", "width_cm", "height_cm"):
            val = size.get(key)
            if val is not None:
                dims.append(val)
    dim_text = "×".join(str(x) for x in dims[:3]) if len(dims) >= 3 else ""
    return {
        "row_index": None,
        "name": "外纸箱/包装费",
        "field": "packaging_addon_per_piece",
        "value": fee,
        "source": "size_rule",
        "confidence": 0.68,
        "reason": note
        or (
            f"明细未见包装金额，按成品尺寸约 {dim_text}cm 估算 OPP/基础包装费（与 quote_engine 口径一致）。"
        ),
    }


def _has_packaging_amount(rows: list[Any]) -> bool:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not _PACKAGING_NAME_RE.search(str(row.get("name") or "")):
            continue
        try:
            if float(row.get("amount") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _collect_size_numbers(size: Any) -> list[float]:
    vals: list[Any]
    if isinstance(size, dict):
        vals = [size.get(k) for k in ("length_cm", "width_cm", "height_cm", "L", "W", "H", "长", "宽", "高")]
        vals.extend(size.values())
    elif isinstance(size, (list, tuple)):
        vals = list(size)
    else:
        vals = [size]
    out: list[float] = []
    for val in vals:
        num = _first_number(str(val or ""))
        if num is not None and num > 0:
            out.append(num)
            if len(out) >= 3:
                return out[:3]
    return out
