from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


DEFAULT_QUANTITIES = (300, 500, 1000)

_PACKAGING_ROW_NAME_RE = re.compile(
    r"\u5305\u88c5|OPP|\u80f6\u888b|\u81ea\u5c01\u888b|\u7eb8\u7bb1|\u7eb8\u76d2|"
    r"\u7eb8\u5361|\u540a\u724c|\u6807\u8d34|\u5c01\u7bb1|\u5305\u88c5\u888b|"
    r"\u5916\u7bb1|\u7bb1\u5b50|Packing|pe\u888b",
    re.IGNORECASE,
)

_CALC_NOTE_DROP_PHRASES = (
    "用量占位",
    "模型不可用",
    "恢复 Kimi",
    "仅为保证小计可算",
    "数据源不含",
    "用量为 AI 估计",
    "请以业务 BOM",
)

_CALC_NOTE_NOISE_PATTERNS = (
    r"^\s*(系统推算|系统近似|系统估算|本地兜底)[：:]\s*",
    r"[（(][^）)]*(未计排版损耗|细表排版损耗另计|非手工排版式|以业务细表为准)[^）)]*[）)]",
    r"(?:；|;)?\s*(未计排版损耗|细表排版损耗另计|以业务细表为准|请复核|建议复核)[^；。]*[；。]?",
)


def clean_calc_note_text(note: Any) -> str:
    """Keep the visible formula column business-facing, not engine-facing."""
    text = str(note or "").strip()
    if not text:
        return ""
    if any(phrase in text for phrase in _CALC_NOTE_DROP_PHRASES):
        return ""
    for pattern in _CALC_NOTE_NOISE_PATTERNS:
        text = re.sub(pattern, "", text).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip("；;。 ")
    return text[:260]


@dataclass(frozen=True)
class LineItem:
    name: str
    spec: str
    usage: str
    unit_price: str
    amount: float
    source: str = "kb"
    kb_hit: bool = False
    kb_auto_learned: bool = False
    spec_ai: bool = False
    usage_ai: bool = False
    unit_price_ai: bool = False
    amount_ai: bool = False
    calc_note: str = ""
    recognition_status: str = ""
    recognition_reason: str = ""
    raw_usage: str = ""
    raw_unit_price: str = ""
    usage_unit_kind: str = ""
    price_unit_kind: str = ""
    raw_quantity_unit: str = ""
    raw_price_unit: str = ""
    converted_quantity_unit: str = ""
    converted_price_unit: str = ""
    unit_converted: bool = False
    unit_conversion_basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        from display_number_format import format_numbers_in_display_text

        out = {
            "name": self.name,
            "spec": format_numbers_in_display_text(self.spec or "-"),
            "usage": format_numbers_in_display_text(self.usage or "-"),
            "unit_price": format_numbers_in_display_text(self.unit_price or "-"),
            "amount": round(self.amount, 2),
            "amount_text": format_money(self.amount),
            "source": normalize_source(self.source),
            "kb_hit": bool(self.kb_hit),
            "kb_auto_learned": bool(self.kb_auto_learned),
            "spec_ai": self.spec_ai,
            "usage_ai": self.usage_ai,
            "unit_price_ai": self.unit_price_ai,
            "amount_ai": self.amount_ai,
            "calc_note": clean_calc_note_text(self.calc_note),
            "calc_method": clean_calc_note_text(self.calc_note),
        }
        if self.recognition_status:
            out["recognition_status"] = self.recognition_status
        if self.recognition_reason:
            out["recognition_reason"] = self.recognition_reason
        if self.raw_usage:
            out["raw_usage"] = self.raw_usage
        if self.raw_unit_price:
            out["raw_unit_price"] = self.raw_unit_price
        if self.usage_unit_kind:
            out["usage_unit_kind"] = self.usage_unit_kind
        if self.price_unit_kind:
            out["price_unit_kind"] = self.price_unit_kind
        if self.raw_quantity_unit:
            out["raw_quantity_unit"] = self.raw_quantity_unit
        if self.raw_price_unit:
            out["raw_price_unit"] = self.raw_price_unit
        if self.converted_quantity_unit:
            out["converted_quantity_unit"] = self.converted_quantity_unit
        if self.converted_price_unit:
            out["converted_price_unit"] = self.converted_price_unit
        if self.unit_converted:
            out["unit_converted"] = True
        if self.unit_conversion_basis:
            out["unit_conversion_basis"] = self.unit_conversion_basis
        return out


@dataclass(frozen=True)
class QuoteSettings:
    product_name: str = "210D防撕裂尼龙包"
    mold_fee: float = 1000.0
    processing_fee: float = 12.0
    system_overhead: float = 4.0
    gross_margin_rate: float = 0.35
    fob_addition_per_piece: float = 4.0
    quantities: tuple[int, ...] = DEFAULT_QUANTITIES
    items: tuple[LineItem, ...] = field(default_factory=tuple)


def _detail_has_packaging_amount(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if not _PACKAGING_ROW_NAME_RE.search(str(row.get("name") or "")):
            continue
        try:
            amount = float(row.get("amount") or 0.0)
        except (TypeError, ValueError):
            continue
        if amount > 1e-6:
            return True
    return False


def _line_items_have_packaging_amount(items: tuple[LineItem, ...]) -> bool:
    return _detail_has_packaging_amount([{"name": item.name, "amount": item.amount} for item in items])


def _coerce_dimension_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if num > 0 else None
    text = str(value).strip()
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _numbers_from_dimension_text(text: str) -> list[float]:
    if not text:
        return []
    normalized = (
        str(text)
        .replace("\uff0a", "x")
        .replace("*", "x")
        .replace("\u00d7", "x")
        .replace("X", "x")
    )
    patterns = [
        r"(\d+(?:\.\d+)?)\s*(?:cm|\u5398\u7c73)?\s*x\s*(\d+(?:\.\d+)?)\s*(?:cm|\u5398\u7c73)?\s*x\s*(\d+(?:\.\d+)?)\s*(?:cm|\u5398\u7c73)?",
        r"\u957f\s*(\d+(?:\.\d+)?)\s*(?:cm|\u5398\u7c73)?.{0,8}\u9ad8\s*(\d+(?:\.\d+)?)\s*(?:cm|\u5398\u7c73)?.{0,8}(?:\u539a|\u5bbd)\s*(\d+(?:\.\d+)?)",
        r"L\s*(\d+(?:\.\d+)?).{0,8}W\s*(\d+(?:\.\d+)?).{0,8}H\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, normalized, flags=re.IGNORECASE)
        if m:
            return [float(x) for x in m.groups()]
    return []


def _collect_dimension_numbers(payload: dict[str, Any]) -> list[float]:
    dims: list[float] = []
    size = payload.get("product_size")
    if isinstance(size, dict):
        for key in (
            "length_cm",
            "width_cm",
            "height_cm",
            "LCM",
            "WCM",
            "HCM",
            "lcm",
            "wcm",
            "hcm",
            "L",
            "W",
            "H",
            "\u957f",
            "\u5bbd",
            "\u9ad8",
            "\u539a",
        ):
            num = _coerce_dimension_number(size.get(key))
            if num is not None:
                dims.append(num)
        if len(dims) >= 3:
            return dims[:3]
        for val in size.values():
            num = _coerce_dimension_number(val)
            if num is not None:
                dims.append(num)
                if len(dims) >= 3:
                    return dims[:3]
    elif isinstance(size, (list, tuple)):
        for val in size:
            num = _coerce_dimension_number(val)
            if num is not None:
                dims.append(num)
                if len(dims) >= 3:
                    return dims[:3]
    elif isinstance(size, str):
        dims.extend(_numbers_from_dimension_text(size))
        if len(dims) >= 3:
            return dims[:3]

    for key in ("structure_text_snapshot", "structure_description", "product_description", "product_size_text"):
        dims.extend(_numbers_from_dimension_text(str(payload.get(key) or "")))
        if len(dims) >= 3:
            return dims[:3]
    return dims[:3]


def _estimate_packaging_addon(payload: dict[str, Any]) -> tuple[float, str] | None:
    dims = _collect_dimension_numbers(payload)
    if len(dims) < 3:
        return None
    a, b, c = sorted(dims[:3], reverse=True)
    volume = a * b * c
    if a <= 25 and volume <= 5000:
        addon = 0.8
        size_band = "\u5c0f\u4ef6\u57fa\u7840\u5305\u88c5"
    elif a <= 40 and volume <= 18000:
        addon = 1.2
        size_band = "\u4e2d\u7b49\u5c3a\u5bf8\u57fa\u7840\u5305\u88c5"
    else:
        addon = 2.0
        size_band = "\u504f\u5927\u57fa\u7840\u5305\u88c5"
    note = (
        f"\u6309\u6210\u54c1\u5c3a\u5bf8\u7ea6 {dims[0]:g}x{dims[1]:g}x{dims[2]:g}cm "
        f"\u5224\u5b9a\u4e3a{size_band}\uff1b\u672a\u586b\u660e\u88c5\u7bb1\u6570\u65f6\u53ea\u4f30\u5355\u4ef6OPP/\u57fa\u7840\u5305\u88c5\uff0c"
        f"\u5f53\u524d\u4f30\u7b97 {addon:.2f} \u5143/\u4e2a\u3002"
    )
    return addon, note


def _maybe_append_packaging_addon(settings: QuoteSettings, payload: dict[str, Any]) -> QuoteSettings:
    if _line_items_have_packaging_amount(settings.items):
        return settings

    raw = payload.get("packaging_addon_per_piece")
    source = "ai"
    calc_note = ""
    if raw is not None and str(raw).strip() != "":
        try:
            addon = float(raw)
        except (TypeError, ValueError):
            return settings
        if addon <= 0:
            return settings
        source = "sheet"
        calc_note = "\u6309\u8868\u5185/\u4e1a\u52a1\u6307\u5b9a\u7684\u7eb8\u7bb1\u5305\u88c5\u8d39\u52a0\u8ba1\u3002"
        item_name = "\u5916\u7eb8\u7bb1/\u5305\u88c5\u8d39\uff08\u52a0\u8ba1\uff09"
    else:
        estimated = _estimate_packaging_addon(payload)
        if estimated is None:
            return settings
        addon, calc_note = estimated
        item_name = "\u5916\u7eb8\u7bb1/\u5305\u88c5\u8d39\uff08\u7cfb\u7edf\u4f30\u7b97\uff09"

    new_item = LineItem(
        name=item_name,
        spec="-",
        usage="1\u4e2a",
        unit_price=f"{addon:.2f}\u5143/\u4e2a",
        amount=round(addon, 2),
        source=source,
        kb_hit=False,
        unit_price_ai=(source == "ai"),
        amount_ai=(source == "ai"),
        calc_note=calc_note,
    )
    return QuoteSettings(
        product_name=settings.product_name,
        mold_fee=settings.mold_fee,
        processing_fee=settings.processing_fee,
        system_overhead=settings.system_overhead,
        gross_margin_rate=settings.gross_margin_rate,
        fob_addition_per_piece=settings.fob_addition_per_piece,
        quantities=settings.quantities,
        items=(*settings.items, new_item),
    )


def default_line_items() -> tuple[LineItem, ...]:
    return (
        LineItem(
            name="210D防撕裂尼龙格子布（大力马）",
            spec="210D",
            usage="1.310 码²",
            unit_price="80元/码²",
            amount=104.82,
            source="kb",
            kb_hit=True,
        ),
        LineItem(
            name="210D涤纶里布",
            spec="210D",
            usage="1.205 码²",
            unit_price="5元/码²",
            amount=6.03,
            source="kb",
            kb_hit=True,
        ),
        LineItem(
            name="5#防水拉链（主拉链+口袋）",
            spec="5#",
            usage="1套",
            unit_price="7.94元/套",
            amount=7.94,
            source="ai",
            spec_ai=True,
            usage_ai=True,
            unit_price_ai=True,
            amount_ai=True,
        ),
        LineItem(
            name="肩带+调节扣+D环",
            spec="-",
            usage="1套",
            unit_price="3.62元/套",
            amount=3.62,
            source="ai",
            spec_ai=True,
            usage_ai=True,
            unit_price_ai=True,
            amount_ai=True,
        ),
        LineItem(
            name="反光丝印标志",
            spec="-",
            usage="1处",
            unit_price="4元/处",
            amount=4.00,
            source="ai",
            spec_ai=True,
            usage_ai=True,
            unit_price_ai=True,
            amount_ai=True,
        ),
        LineItem(
            name="包装",
            spec="-",
            usage="1套",
            unit_price="1.50元/套",
            amount=1.50,
            source="kb",
            kb_hit=True,
        ),
    )


def format_money(value: float) -> str:
    from display_number_format import format_display_money_cny

    return format_display_money_cny(value)


def format_money_usd(value: float) -> str:
    from display_number_format import format_display_money_usd

    return format_display_money_usd(value)


VAT_ON_COST_RATE = 0.13


_SQYD_TO_M2 = 0.83612736
_YARD_TO_METER = 0.9144


def format_decimal(value: float, places: int = 4) -> str:
    text = f"{value:.{places}f}"
    return text.rstrip("0").rstrip(".")


def parse_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_REFERENCE_ONLY_LINE_RX = re.compile(
    r"^(?:"
    r"\u6210\u672c\u53c2\u8003(?:\u4ef7)?|"
    r"\u6210\u54c1\u5c3a\u5bf8|"
    r"\u5907\u6ce8|"
    r"\u8bf4\u660e|"
    r"\u5efa\u8bae|"
    r"\u53c2\u8003(?:\u8bf4\u660e|\u4fe1\u606f)?|"
    r"\u4ef7\u683c\u53c2\u8003|"
    r"\u5c3a\u5bf8\u8bf4\u660e"
    r")(?:[:\uff1a].*)?$"
)


def is_reference_only_line_name(name: str) -> bool:
    return bool(_REFERENCE_ONLY_LINE_RX.match(str(name or "").strip()))


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def parse_rate(value: Any, default: float) -> float:
    parsed = parse_float(value, default)
    if parsed > 1:
        parsed = parsed / 100.0
    if parsed < 0:
        return default
    if parsed >= 1:
        return 0.99
    return parsed


def parse_quantities(value: Any) -> tuple[int, ...]:
    """Accept a list/tuple of quantities from the payload; fall back to the
    fixed 300/500/1000 ladder when nothing usable is provided."""
    if not value:
        return DEFAULT_QUANTITIES
    if isinstance(value, str):
        raw = value.replace("，", ",")
        value = [p.strip() for p in raw.split(",") if p.strip()]
    if isinstance(value, (list, tuple)):
        cleaned: list[int] = []
        for item in value:
            try:
                num = int(float(item))
            except (TypeError, ValueError):
                continue
            if num > 0:
                cleaned.append(num)
        if cleaned:
            return tuple(sorted(set(cleaned)))
    return DEFAULT_QUANTITIES


def _margins_from_reference_prices(payload: dict[str, Any]) -> dict[int, float]:
    by_qty: dict[int, float] = {}
    raw = payload.get("reference_prices")
    if not isinstance(raw, list):
        return by_qty
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        q = entry.get("quantity")
        m = entry.get("margin")
        if q is None or m is None:
            continue
        try:
            qi = int(q)
            rate = float(m)
            by_qty[qi] = parse_rate(rate, 0.35)
        except (TypeError, ValueError):
            continue
    return by_qty


def _margins_from_quantity_map(payload: dict[str, Any]) -> dict[int, float]:
    raw = payload.get("gross_margin_by_quantity")
    if not isinstance(raw, dict):
        return {}
    out: dict[int, float] = {}
    for key, value in raw.items():
        try:
            qi = int(float(str(key)))
            out[qi] = parse_rate(value, 0.35)
        except (TypeError, ValueError):
            continue
    return out


def resolve_tier_margin_rates(
    payload: dict[str, Any],
    quantities: tuple[int, ...],
    default_rate: float,
) -> list[float]:
    """Return gross margin (0..1) for each quantity tier.

    Precedence:
    1. ``gross_margin_rates`` list aligned with ``quantities`` (same length).
    2. ``gross_margin_by_quantity`` and ``reference_prices[].margin`` by件数，
       后者为底、前者覆盖同档。
    3. ``default_rate``（来自单一 gross_margin_rate 配置）。
    """
    n = len(quantities)
    explicit = payload.get("gross_margin_rates")
    if isinstance(explicit, (list, tuple)) and len(explicit) == n:
        return [parse_rate(explicit[i], default_rate) for i in range(n)]

    by_qty: dict[int, float] = {}
    by_qty.update(_margins_from_reference_prices(payload))
    by_qty.update(_margins_from_quantity_map(payload))

    return [by_qty[q] if q in by_qty else default_rate for q in quantities]


def infer_source(spec_ai: bool, usage_ai: bool, unit_price_ai: bool, amount_ai: bool) -> str:
    if spec_ai or usage_ai or unit_price_ai or amount_ai:
        return "ai"
    return "kb"


def normalize_source(value: Any, fallback: str = "kb") -> str:
    text = str(value or "").strip().lower()
    if text in {"kb", "knowledge", "knowledge_base"}:
        return "kb"
    if text in {"ai", "model"}:
        return "ai"
    return "ai" if fallback == "ai" else "kb"


def _unit_dimension(kind: str) -> str:
    if kind in {"area_m2", "area_yd2"}:
        return "area"
    if kind in {"cm", "meter", "yard"}:
        return "length"
    if kind == "piece":
        return "quantity"
    if kind == "weight":
        return "weight"
    return ""


_UNIT_KIND_LABEL = {
    "area_m2": "㎡",
    "area_yd2": "码²",
    "cm": "cm",
    "meter": "米",
    "yard": "码",
    "piece": "个",
    "weight": "重量",
}


def _unit_kind_label(kind: str) -> str:
    return _UNIT_KIND_LABEL.get(kind, kind)


_UNIT_DIMENSION_LABEL = {
    "area": "面积",
    "length": "长度",
    "quantity": "数量",
    "weight": "重量",
    "volume": "体积",
}


def _unit_kinds_dimension_mismatch(usage_kind: str, price_kind: str) -> bool:
    if not usage_kind or not price_kind or usage_kind == price_kind:
        return False
    u_dim = _unit_dimension(usage_kind)
    p_dim = _unit_dimension(price_kind)
    if not u_dim or not p_dim:
        return False
    return u_dim != p_dim


def raw_unit_dimension_mismatch_hints(
    usage_raw: Any,
    unit_price_raw: Any,
    *,
    converted: bool = False,
) -> list[str]:
    """按单位维度（面积/长度/数量/重量等）判断用量与单价是否口径冲突。"""
    usage = str(usage_raw or "").strip()
    price = str(unit_price_raw or "").strip()
    if not usage or not price or usage in {"-", "—"} or price in {"-", "—"}:
        return []

    usage_kind = _usage_unit_kind(usage)
    price_kind = _price_unit_kind(price)
    if not _unit_kinds_dimension_mismatch(usage_kind, price_kind):
        return []

    if converted:
        return ["原始用量单位与单价单位口径不一致，虽已自动换算，但需要人工确认"]

    usage_dim = _unit_dimension(usage_kind)
    price_dim = _unit_dimension(price_kind)
    u_label = _UNIT_DIMENSION_LABEL.get(usage_dim, usage_dim)
    p_label = _UNIT_DIMENSION_LABEL.get(price_dim, price_dim)
    return [f"用量为{u_label}口径，单价为{p_label}口径；口径不一致，建议复核。"]


def row_unit_dimension_mismatch_from_kinds(
    usage_kind: Any,
    price_kind: Any,
    *,
    converted: bool = False,
) -> list[str]:
    uk = str(usage_kind or "").strip()
    pk = str(price_kind or "").strip()
    if not _unit_kinds_dimension_mismatch(uk, pk):
        return []
    if converted:
        return ["原始用量单位与单价单位口径不一致，虽已自动换算，但需要人工确认"]
    u_label = _UNIT_DIMENSION_LABEL.get(_unit_dimension(uk), uk)
    p_label = _UNIT_DIMENSION_LABEL.get(_unit_dimension(pk), pk)
    return [f"用量为{u_label}口径，单价为{p_label}口径；口径不一致，建议复核。"]


def row_unit_alignment_hints(usage_raw: Any, unit_price_raw: Any) -> list[str]:
    return raw_unit_dimension_mismatch_hints(usage_raw, unit_price_raw, converted=False)


def row_amount_crosscheck_hint(usage_raw: Any, unit_price_raw: Any, amount: float) -> str | None:
    usage = str(usage_raw or "").strip()
    price = str(unit_price_raw or "").strip()
    if not usage or not price or usage == "-" or price == "-":
        return None
    if row_unit_alignment_hints(usage, price):
        return None
    um = re.search(r"(\d+(?:\.\d+)?)", usage.replace(",", ""))
    pm = re.search(r"(\d+(?:\.\d+)?)", price.replace(",", ""))
    if not um or not pm:
        return None
    try:
        expected = float(um.group(1)) * float(pm.group(1))
        actual = float(amount or 0)
    except (TypeError, ValueError):
        return None
    if actual and abs(expected - actual) > max(2.5, abs(actual) * 0.12):
        return "用量×单价与小计差异较大，建议复核该行计算方式。"
    return None


def _first_number(value: Any) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", str(value or "").replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _usage_unit_kind(text: Any) -> str:
    raw = str(text or "").strip()
    low = raw.lower()
    if any(x in raw for x in ("㎡", "平方")) or "m²" in low or "m2" in low:
        return "area_m2"
    if "码²" in raw or "码2" in raw or "yd²" in low or "yd2" in low:
        return "area_yd2"
    if "cm" in low or "厘米" in raw:
        return "cm"
    if "米" in raw or re.search(r"\bm\b", low):
        return "meter"
    if "码" in raw or re.search(r"\byd?\b", low):
        return "yard"
    if re.search(r"个|只|粒|颗|枚|pcs|pc|套|条|件|处", raw, re.I):
        return "piece"
    if re.search(r"(?:千克|公斤|\bkg\b)", low):
        return "weight"
    if re.search(r"(?<![码])克", raw) or re.search(r"\bg\b(?!\w)", low):
        return "weight"
    return ""


def _price_unit_kind(text: Any) -> str:
    raw = str(text or "").strip()
    low = raw.lower()
    if any(x in raw for x in ("㎡", "平方")) or "m²" in low or "m2" in low:
        return "area_m2"
    if "码²" in raw or "码2" in raw or "yd²" in low or "yd2" in low:
        return "area_yd2"
    if "cm" in low or "厘米" in raw:
        return "cm"
    if "米" in raw or re.search(r"/\s*m\b", low):
        return "meter"
    if "码" in raw or re.search(r"/\s*y(?:d)?\b", low):
        return "yard"
    if re.search(r"个|只|粒|颗|枚|pcs|pc|套|条|件|处", raw, re.I):
        return "piece"
    if re.search(r"(?:千克|公斤|\bkg\b)", low):
        return "weight"
    if re.search(r"(?<![码])克", raw) or re.search(r"\bg\b(?!\w)", low):
        return "weight"
    return ""


def reconcile_row_amount_after_unit_price_change(
    row: dict[str, Any],
    *,
    old_unit_text: str = "",
    old_amount: float | None = None,
) -> None:
    """用户只改单价未改小计时，按旧单价比例缩放小计，或按用量/单件重算。"""
    new_unit = str(row.get("unit_price") or "").strip()
    new_p = _first_number(new_unit)
    if new_p is None or new_p <= 0:
        return
    if old_amount is None:
        try:
            old_amount = float(row.get("amount") or 0)
        except (TypeError, ValueError):
            old_amount = 0.0
    old_p = _first_number(old_unit_text)
    usage = str(row.get("usage") or "").strip()
    usage_qty = _first_number(usage) if usage not in ("", "-", "—") else None

    if old_p and old_p > 0 and old_amount and old_amount > 0:
        row["amount"] = round(float(old_amount) * new_p / old_p, 2)
    elif usage_qty is not None and usage_qty > 0:
        row["amount"] = round(new_p * usage_qty, 2)
    elif _price_unit_kind(new_unit) == "piece":
        row["amount"] = round(new_p, 2)
    else:
        row.pop("amount", None)
    row["amount_ai"] = False


def _recalculated_amount_and_price(
    usage: str,
    unit_price: str,
) -> tuple[float, str, str] | None:
    qty = _first_number(usage)
    price = _first_number(unit_price)
    if qty is None or price is None or qty <= 0 or price <= 0:
        return None

    usage_kind = _usage_unit_kind(usage)
    price_kind = _price_unit_kind(unit_price)
    if not usage_kind:
        return None

    display_price = unit_price
    note = ""
    effective_qty = qty

    if usage_kind == "area_m2" and price_kind in {"area_yd2", "yard"}:
        converted_price = price / _SQYD_TO_M2
        return round(converted_price * qty, 2), f"{format_decimal(converted_price)}元/㎡", "单位换算：按 1码²=0.83612736㎡ 折算单价后计算小计。"
    if usage_kind == "area_yd2" and price_kind == "area_m2":
        converted_price = price * _SQYD_TO_M2
        return round(converted_price * qty, 2), f"{format_decimal(converted_price)}元/码²", "单位换算：按 1码²=0.83612736㎡ 折算单价后计算小计。"
    if usage_kind == "cm" and price_kind == "meter":
        converted_price = price / 100.0
        return round(converted_price * qty, 2), f"{format_decimal(converted_price)}元/cm", "单位换算：米价折算为厘米价后计算小计。"
    if usage_kind == "meter" and price_kind == "cm":
        converted_price = price * 100.0
        return round(converted_price * qty, 2), f"{format_decimal(converted_price)}元/米", "单位换算：厘米价折算为米价后计算小计。"
    if usage_kind == "meter" and price_kind == "yard":
        effective_qty = qty / _YARD_TO_METER
        note = "单位换算：米用量折算为码后计算小计。"
    elif usage_kind == "yard" and price_kind == "meter":
        effective_qty = qty * _YARD_TO_METER
        note = "单位换算：码用量折算为米后计算小计。"
    elif price_kind and usage_kind != price_kind:
        if usage_kind == "piece" and price_kind == "piece":
            effective_qty = qty
        else:
            return None

    # 无单位单价按当前用量口径直接相乘；同单位也直接相乘。
    return round(price * effective_qty, 2), display_price, note


def _append_calc_note(existing: str, addition: str) -> str:
    base = str(existing or "").strip()
    add = str(addition or "").strip()
    if not add:
        return base
    if add in base:
        return base
    return f"{base}；{add}" if base else add


def parse_items(
    value: Any,
    *,
    structure_text: str = "",
    product_size: dict[str, Any] | None = None,
) -> tuple[LineItem, ...]:
    if not isinstance(value, list):
        return default_line_items()

    from material_spec_usage_enricher import (
        resolve_spec_from_row,
        row_has_valid_amount,
        spec_for_amount_calc,
        usage_for_amount_recalc,
    )

    items: list[LineItem] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        if parse_bool(row.get("exclude_from_cost"), False):
            continue
        rec_status = str(row.get("recognition_status") or "").strip()
        if rec_status == "ignored":
            continue
        if rec_status == "candidate_review" and not parse_bool(row.get("recognition_confirmed"), False):
            continue
        if is_reference_only_line_name(name):
            continue

        raw_spec = spec_for_amount_calc(row)
        raw_usage = usage_for_amount_recalc(row)
        unit_price = str(row.get("unit_price", row.get("单价参考", "-"))).strip() or "-"

        spec_ai = parse_bool(row.get("spec_ai"), False)
        usage_ai = parse_bool(row.get("usage_ai"), False)
        unit_price_ai = parse_bool(row.get("unit_price_ai"), False)
        amount_ai = parse_bool(row.get("amount_ai"), False)
        kb_hit = parse_bool(row.get("kb_hit"), False)
        kb_auto_learned = parse_bool(row.get("kb_auto_learned"), False)
        source = normalize_source(
            row.get("source"),
            infer_source(spec_ai, usage_ai, unit_price_ai, amount_ai),
        )
        auth_spec_res = resolve_spec_from_row(row)
        spec_moved_to_usage = raw_usage == "-" and looks_like_dimension(
            auth_spec_res.value or raw_spec
        )

        spec, usage = normalize_spec_usage(raw_spec, raw_usage)
        if spec_moved_to_usage:
            usage_ai = spec_ai
            spec_ai = False
        raw_usage_snapshot = usage
        raw_unit_price_snapshot = unit_price
        usage_unit_kind = _usage_unit_kind(usage)
        price_unit_kind = _price_unit_kind(unit_price)
        unit_converted = False
        unit_conversion_basis = ""
        calc_note = clean_calc_note_text(row.get("calc_note") or row.get("calc_method") or "")
        amount_value = parse_float(row.get("amount"), 0.0)
        recalculated = _recalculated_amount_and_price(usage, unit_price)
        if recalculated is not None:
            expected_amount, display_unit_price, calc_addition = recalculated
            if abs(expected_amount - amount_value) > 0.01:
                amount_value = expected_amount
                amount_ai = True
            if display_unit_price != unit_price:
                unit_converted = True
                unit_price = display_unit_price
            if calc_addition:
                calc_note = _append_calc_note(calc_note, calc_addition)
                if "单位换算" in calc_addition:
                    unit_converted = True
                    unit_conversion_basis = calc_addition
        elif usage in ("", "-", "—") and not row_has_valid_amount(row):
            piece_price = _first_number(unit_price)
            if _price_unit_kind(unit_price) == "piece" and piece_price is not None and piece_price > 0:
                if amount_value <= 0 or abs(amount_value - piece_price) > 0.02:
                    amount_value = round(piece_price, 2)
                    amount_ai = False

        converted_usage_kind = _usage_unit_kind(usage)
        converted_price_kind = _price_unit_kind(unit_price)
        raw_quantity_unit = _unit_kind_label(usage_unit_kind)
        raw_price_unit_label = _unit_kind_label(price_unit_kind)
        converted_quantity_unit = _unit_kind_label(converted_usage_kind)
        converted_price_unit = _unit_kind_label(converted_price_kind)

        items.append(
            LineItem(
                name=name,
                spec=spec,
                usage=usage,
                unit_price=unit_price,
                amount=amount_value,
                source=source,
                kb_hit=kb_hit,
                kb_auto_learned=kb_auto_learned,
                spec_ai=spec_ai,
                usage_ai=usage_ai,
                unit_price_ai=unit_price_ai,
                amount_ai=amount_ai,
                calc_note=calc_note,
                recognition_status=str(row.get("recognition_status") or "").strip(),
                recognition_reason=str(row.get("recognition_reason") or "").strip(),
                raw_usage=raw_usage_snapshot,
                raw_unit_price=raw_unit_price_snapshot,
                usage_unit_kind=usage_unit_kind,
                price_unit_kind=price_unit_kind,
                raw_quantity_unit=raw_quantity_unit,
                raw_price_unit=raw_price_unit_label,
                converted_quantity_unit=converted_quantity_unit,
                converted_price_unit=converted_price_unit,
                unit_converted=unit_converted,
                unit_conversion_basis=unit_conversion_basis,
            )
        )
    return tuple(items) or default_line_items()


def normalize_spec_usage(spec: str, usage: str) -> tuple[str, str]:
    spec_value = spec.strip() or "-"
    usage_value = usage.strip() or "-"
    if usage_value == "-" and looks_like_dimension(spec_value):
        return "-", spec_value
    return spec_value, usage_value


def looks_like_dimension(text: str) -> bool:
    pattern = r"^\d+(\.\d+)?\s*[*xX×]\s*\d+(\.\d+)?\s*(CM|MM|M|米|码|码²)?$"
    return bool(re.match(pattern, text.strip(), flags=re.IGNORECASE))


def packaging_fee_reference_hint(rows: list[dict[str, Any]]) -> str:
    if _detail_has_packaging_amount(rows):
        return ""
    return (
        "包装提示：本条核算明细中暂无包装物料金额（系统结果相当于未加计外箱/胶袋等费用）。"
        "市面纸箱常见约 6–8 元/个（随尺码与用纸档次浮动），可先按包装成品尺寸粗估选型；"
        "若需细化，可结合表里结构/规格/装箱等版面里的长×宽×高或其它尺寸描述，"
        "判断是否应增补一行包装盒或包装袋。"
    )


def _explain_handwritten_vs_agent_gap(gap_pc: float, *, ref_cost_before_margin: float) -> str:
    if abs(gap_pc) < 0.02:
        return "表内手写成本与系统同档毛利前成本一致。"
    direction = "高于" if gap_pc > 0 else "低于"
    return (
        f"系统核算{direction}表内手写成本约 {format_money(abs(gap_pc))}；"
        "常见原因包括 BOM 不完整、加工费/杂费口径不同，或表内仅写物料未含开模分摊。"
    )


def _explain_exw_quote_gap(quote_gap_pc: float | None) -> str:
    if quote_gap_pc is None or abs(quote_gap_pc) < 0.02:
        return ""
    direction = "高于" if quote_gap_pc > 0 else "低于"
    return f"系统 EXW 报价{direction}表内手写报价约 {format_money(abs(quote_gap_pc))}，请核对毛利率与加价口径。"


def build_sales_sheet_checkpoints(
    payload: dict[str, Any],
    tiers: list[dict[str, Any]],
    *,
    material_total: float,
) -> list[dict[str, Any]]:
    raw = payload.get("reference_prices")
    if not isinstance(raw, list) or not tiers:
        return []

    tier_by_qty: dict[int, dict[str, Any]] = {}
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        try:
            q = int(tier["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        tier_by_qty[q] = tier

    rows: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "sheet_material_subtotal":
            continue
        q_raw = entry.get("quantity")
        cost_raw = entry.get("cost")
        if q_raw is None or cost_raw is None:
            continue
        try:
            qty = int(q_raw)
            ref_cost = float(cost_raw)
        except (TypeError, ValueError):
            continue
        tier = tier_by_qty.get(qty)
        if tier is None:
            continue
        try:
            comp = float(tier.get("cost_before_margin") or 0.0)
        except (TypeError, ValueError):
            comp = 0.0
        gap = round(comp - ref_cost, 2)
        ref_quote_pc: float | None = None
        rq = entry.get("quote")
        if rq is not None:
            try:
                ref_quote_pc = float(rq)
            except (TypeError, ValueError):
                ref_quote_pc = None
        marg = entry.get("margin")
        ref_margin_text = ""
        if marg is not None:
            try:
                mf = float(marg)
                ref_margin_text = f"{mf * 100:.1f}%" if mf <= 1 else f"{mf:.1f}%"
            except (TypeError, ValueError):
                ref_margin_text = ""
        cq = tier.get("exw_price")
        try:
            comp_exw = float(cq) if cq is not None else None
        except (TypeError, ValueError):
            comp_exw = None
        quote_gap = None
        quote_gap_txt = ""
        if ref_quote_pc is not None and comp_exw is not None:
            quote_gap = round(comp_exw - ref_quote_pc, 2)
            quote_gap_txt = format_money(comp_exw - ref_quote_pc)

        rows.append(
            {
                "quantity": qty,
                "quantity_text": f"{qty}件",
                "source_text": str(entry.get("source_text") or "").strip(),
                "ref_cost_before_margin_pc": round(ref_cost, 4),
                "ref_cost_before_margin_text": format_money(ref_cost),
                "ref_quote_pc": round(ref_quote_pc, 2) if ref_quote_pc is not None else None,
                "ref_quote_text": format_money(ref_quote_pc) if ref_quote_pc is not None else "",
                "ref_margin_text": ref_margin_text or "-",
                "computed_cost_before_margin_pc": round(comp, 4),
                "computed_cost_before_margin_text": format_money(comp),
                "computed_exw_quote_pc": comp_exw,
                "computed_exw_quote_text": format_money(comp_exw) if comp_exw is not None else "",
                "gap_pc": gap,
                "gap_text": format_money(gap),
                "gap_exw_quote_pc": quote_gap,
                "gap_exw_quote_text": quote_gap_txt,
                "gap_explain_cn": _explain_handwritten_vs_agent_gap(gap, ref_cost_before_margin=ref_cost),
                "quote_gap_explain_cn": _explain_exw_quote_gap(quote_gap) if quote_gap is not None else "",
                "computed_material_only_pc": round(material_total, 4),
                "computed_material_only_text": format_money(material_total),
                "compare_hint": (
                    "表内「成本」通常为单件毛利前合计（物料+加工+杂费+开模分摊），"
                    "与摘要「单包系统成本」口径一致；与「物料合计」不同。"
                ),
            }
        )

    rows.sort(key=lambda r: int(r["quantity"]))
    return rows


def annotate_detail_rows_quote_accuracy(
    detail_rows: list[dict[str, Any]],
    cost_bridge: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    out: list[dict[str, Any]] = []
    unit_rows = 0
    amt_rows = 0
    for row in detail_rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        r = dict(row)
        usage_for_hint = r.get("raw_usage") or r.get("usage")
        price_for_hint = r.get("raw_unit_price") or r.get("unit_price")
        converted = bool(r.get("unit_converted"))
        uh = raw_unit_dimension_mismatch_hints(
            usage_for_hint,
            price_for_hint,
            converted=converted,
        )
        ah = row_amount_crosscheck_hint(
            r.get("usage"),
            r.get("unit_price"),
            float(r.get("amount") or 0.0),
        )
        bag: list[str] = [*uh]
        if ah:
            bag.append(ah)
            amt_rows += 1
        if uh:
            unit_rows += 1
        if bag:
            r["accuracy_hints"] = bag[:4]
        out.append(r)

    tails: list[str] = []
    anchor = cost_bridge.get("sheet_anchor_material_subtotal")
    if anchor is not None:
        try:
            gap = float(cost_bridge["sheet_anchor_vs_computed_material_gap"])
            aref = float(anchor)
        except (KeyError, TypeError, ValueError):
            gap, aref = 0.0, 0.0
        if abs(gap) >= max(12.0, abs(aref) * 0.07):
            label = str(cost_bridge.get("sheet_anchor_material_label") or "表内物料参考").strip()
            tails.append(
                f"对账提示：明细物料合计与本表「{label}」手写参考约差 "
                f"{format_money(round(gap, 2))}，"
                "多为 BOM 不完整或业务员单价未被系统采用。"
            )

    summary_chunks: list[str] = []
    if unit_rows:
        summary_chunks.append(f"准确性：{unit_rows} 行的用量×单价语义需人工核对口径。")
    if amt_rows:
        summary_chunks.append(
            f"粗算校验：{amt_rows} 行小计与「首数字×单价首数」差异较大（见各行 accuracy_hints）。"
        )

    tails = summary_chunks + tails
    return out, tails


def resolve_effective_system_overhead(
    payload: dict[str, Any],
    material_total: float,
    baseline_fixed: float,
) -> tuple[float, str]:
    sfx = payload.get("system_overhead_fixed")
    if sfx is not None and sfx != "":
        try:
            f = float(sfx)
            if f >= 0:
                return round(f, 2), "demand_fixed_yuan_per_pc"
        except (TypeError, ValueError):
            pass

    r = payload.get("management_loss_rate")
    if r is not None and r != "":
        try:
            rate = float(r)
            if rate > 1:
                rate = rate / 100.0
            if 0 <= rate <= 0.995:
                return round(max(0.0, material_total) * rate, 2), "demand_pct_of_material_total"
        except (TypeError, ValueError):
            pass

    sob = payload.get("system_overhead")
    if sob is not None and sob != "":
        try:
            f = float(sob)
            if f >= 0:
                return round(f, 2), "payload_system_overhead"
        except (TypeError, ValueError):
            pass

    return round(baseline_fixed, 2), "default_fixed_yuan_per_pc"


def _markdown_cell(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def build_settings(payload: dict[str, Any] | None = None) -> QuoteSettings:
    payload = payload or {}
    gross_margin_rate = parse_rate(
        payload.get("gross_margin_rate", payload.get("expected_margin_rate")),
        0.35,
    )
    return QuoteSettings(
        product_name=str(payload.get("product_name") or "210D防撕裂尼龙包").strip(),
        mold_fee=parse_float(payload.get("mold_fee"), 1000.0),
        processing_fee=parse_float(payload.get("processing_fee"), 12.0),
        system_overhead=parse_float(payload.get("system_overhead"), 4.0),
        gross_margin_rate=gross_margin_rate,
        fob_addition_per_piece=parse_float(payload.get("fob_addition"), 4.0),
        quantities=parse_quantities(payload.get("quantities")),
        items=parse_items(
            payload.get("items"),
            structure_text=str(
                payload.get("structure_text_snapshot") or payload.get("structure_text") or ""
            ),
            product_size=payload.get("product_size")
            if isinstance(payload.get("product_size"), dict)
            else None,
        ),
    )


def calculate_quote(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    from material_spec_usage_enricher import (
        purge_dynamic_usage_placeholders,
        stamp_trusted_bom_source_fields,
    )

    stamp_trusted_bom_source_fields(payload.get("items"))
    rule_hits: list[Any] = []
    try:
        from quote_correction_learning import apply_correction_rules_to_payload

        rule_hits = apply_correction_rules_to_payload(payload)
    except Exception:
        rule_hits = []
    purge_dynamic_usage_placeholders(payload.get("items"))
    try:
        from quote_anomaly_learning import scan_and_learn_from_quote

        scan_and_learn_from_quote(
            payload,
            quote_uid=str(payload.get("quote_uid") or payload.get("id") or ""),
            apply_auto_fix=True,
            record_history=bool(payload.get("quote_uid") or payload.get("id")),
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception("scan_and_learn_from_quote in calculate_quote")
    purge_dynamic_usage_placeholders(payload.get("items"))
    settings = _maybe_append_packaging_addon(build_settings(payload), payload)
    include_fob = parse_bool(payload.get("include_fob"), True)
    usd_cny = parse_float(payload.get("usd_cny_rate"), 7.15)
    if usd_cny is None or usd_cny <= 0:
        usd_cny = 7.15

    material_total = round(sum(item.amount for item in settings.items), 2)
    effective_overhead, overhead_rule = resolve_effective_system_overhead(
        payload, material_total, settings.system_overhead
    )
    tier_rates = resolve_tier_margin_rates(payload, settings.quantities, settings.gross_margin_rate)

    tiers = []
    for index, quantity in enumerate(settings.quantities):
        rate = tier_rates[index]
        margin_divisor = max(0.01, 1 - rate)
        mold_share = settings.mold_fee / quantity
        cost_before_margin = round(
            material_total + effective_overhead + settings.processing_fee + mold_share,
            2,
        )
        exw_rn = round(cost_before_margin / margin_divisor, 2)
        exw_usd = round(exw_rn / usd_cny, 2)
        exw_usd_text = format_money_usd(exw_usd)
        if include_fob:
            fob_price_val = exw_rn + settings.fob_addition_per_piece
            fob_rounded = round(fob_price_val, 2)
            fob_text = format_money(fob_rounded)
            fob_usd_v = round(float(fob_rounded) / usd_cny, 2)
            fob_usd_text = format_money_usd(fob_usd_v)
            taxed_price_val = None
            taxed_price_text_val = "FOB口径：不加税"
        else:
            fob_rounded = None  # type: ignore[assignment]
            fob_text = ""
            fob_usd_v = None  # type: ignore[assignment]
            fob_usd_text = ""
            taxed_price_val = round(cost_before_margin * (1.0 + VAT_ON_COST_RATE), 2)
            taxed_price_text_val = format_money(taxed_price_val)

        tiers.append(
            {
                "quantity": quantity,
                "quantity_text": f"{quantity}件",
                "mold_share": round(mold_share, 2),
                "mold_share_text": format_money(mold_share),
                "processing_fee": round(settings.processing_fee, 2),
                "processing_fee_text": format_money(settings.processing_fee),
                "system_overhead_applied": effective_overhead,
                "cost_before_margin": cost_before_margin,
                "cost_before_margin_text": format_money(cost_before_margin),
                "total_cost": cost_before_margin,
                "total_cost_text": format_money(cost_before_margin),
                "margin_rate": rate,
                "margin_rate_text": f"{rate * 100:.0f}%",
                "exw_price": exw_rn,
                "exw_price_text": format_money(exw_rn),
                "exw_price_usd": exw_usd,
                "exw_price_usd_text": exw_usd_text,
                "fob_price": fob_rounded,
                "fob_price_text": fob_text,
                "fob_price_usd": fob_usd_v,
                "fob_price_usd_text": fob_usd_text if include_fob else "",
                "include_fob": include_fob,
                "quote_formula": (
                    f"{format_money(cost_before_margin)} / (1 - {rate * 100:.0f}%) "
                    f"= {format_money(exw_rn)}"
                ),
                "tax_rate": VAT_ON_COST_RATE,
                "tax_rate_text": f"{int(round(VAT_ON_COST_RATE * 100))}%",
                "taxed_price": taxed_price_val,
                "taxed_price_text": taxed_price_text_val,
            }
        )

    default_tier = tiers[0]
    qty0 = settings.quantities[0] if settings.quantities else 300
    cost_bridge = {
        "tier_quantity_ref": qty0,
        "material_total": round(material_total, 2),
        "material_total_text": format_money(material_total),
        "processing_fee_per_pc": default_tier["processing_fee"],
        "processing_fee_text": default_tier["processing_fee_text"],
        "system_overhead_per_pc": effective_overhead,
        "system_overhead_rule": overhead_rule,
        "mold_share_per_pc": default_tier["mold_share"],
        "mold_share_text": default_tier["mold_share_text"],
        "addons_sum_per_pc": round(
            default_tier["processing_fee"] + effective_overhead + default_tier["mold_share"],
            2,
        ),
        "addons_sum_text": format_money(
            default_tier["processing_fee"] + effective_overhead + default_tier["mold_share"]
        ),
        "system_cost_text": default_tier["total_cost_text"],
    }
    if overhead_rule == "demand_pct_of_material_total" and material_total > 1e-6:
        mg_bundle = round(material_total + effective_overhead, 2)
        cost_bridge["management_loss_pct_on_material_display"] = round(
            effective_overhead / material_total * 100.0,
            2,
        )
        cost_bridge["material_bundle_incl_mgmt_on_material_total"] = mg_bundle
        cost_bridge["material_bundle_incl_mgmt_text"] = format_money(mg_bundle)

    _pick_anchor = None
    _pick_label = ""
    for entry in payload.get("reference_prices") or []:
        if not isinstance(entry, dict) or entry.get("kind") != "sheet_material_subtotal":
            continue
        amt = entry.get("material_subtotal")
        if amt is None:
            continue
        try:
            sheet_amt = float(amt)
        except (TypeError, ValueError):
            continue
        label = str(entry.get("anchor_label") or "").strip()
        if _pick_anchor is None:
            _pick_anchor, _pick_label = sheet_amt, label
            continue
        if "底料" in label and "底料" not in _pick_label:
            _pick_anchor, _pick_label = sheet_amt, label
    if _pick_anchor is not None:
        gap = round(material_total - _pick_anchor, 2)
        cost_bridge["sheet_anchor_material_subtotal"] = round(_pick_anchor, 2)
        cost_bridge["sheet_anchor_material_subtotal_text"] = format_money(_pick_anchor)
        cost_bridge["sheet_anchor_material_label"] = _pick_label or "表内锚点"
        cost_bridge["sheet_anchor_vs_computed_material_gap"] = gap
        cost_bridge["sheet_anchor_vs_computed_material_gap_text"] = format_money(gap)

    detail_rows = [item.to_dict() for item in settings.items]
    from material_spec_usage_enricher import enrich_material_rows, merge_row_learning_metadata

    merge_row_learning_metadata(detail_rows, payload.get("items"))
    st_blob = str(
        payload.get("structure_text_snapshot") or payload.get("structure_text") or ""
    ).strip()
    ps = payload.get("product_size") if isinstance(payload.get("product_size"), dict) else {}
    detail_rows = enrich_material_rows(
        detail_rows,
        structure_text=st_blob,
        product_size=ps,
    )
    detail_rows, notice_accuracy_tail = annotate_detail_rows_quote_accuracy(
        detail_rows, cost_bridge
    )
    data_notice = build_data_notice(detail_rows, accuracy_tails=notice_accuracy_tail)
    margins_uniform = len({round(r, 6) for r in tier_rates}) <= 1
    summary_margin_text = (
        f"{tier_rates[0] * 100:.0f}%"
        if margins_uniform
        else "按数量阶梯（各档见表内）"
    )
    tier_margin_summary = [
        {
            "quantity": settings.quantities[i],
            "margin_rate": tier_rates[i],
            "margin_rate_text": f"{tier_rates[i] * 100:.0f}%",
        }
        for i in range(len(settings.quantities))
    ]
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "product_name": settings.product_name,
        "material_total": round(material_total, 2),
        "material_total_text": format_money(material_total),
        "cost_bridge": cost_bridge,
        "system_cost": default_tier["total_cost"],
        "system_cost_text": default_tier["total_cost_text"],
        "sales_sheet_checkpoints": build_sales_sheet_checkpoints(
            payload,
            tiers,
            material_total=material_total,
        ),
        "usd_cny_rate": usd_cny,
        "settings": {
            "mold_fee": settings.mold_fee,
            "processing_fee": settings.processing_fee,
            "system_overhead": effective_overhead,
            "system_overhead_rule": overhead_rule,
            "system_overhead_config": settings.system_overhead,
            "gross_margin_rate": settings.gross_margin_rate,
            "gross_margin_rate_text": summary_margin_text,
            "gross_margin_uniform": margins_uniform,
            "gross_margin_tiers": tier_margin_summary,
            "fob_addition_per_piece": settings.fob_addition_per_piece,
            "include_fob": include_fob,
        },
        "detail_rows": detail_rows,
        "data_notice": data_notice,
        "summary_rows": [
            {
                "name": "物料合计",
                "spec": "按明细表汇总",
                "unit_price": "-",
                "amount": round(material_total, 2),
                "amount_text": format_money(material_total),
            },
            {
                "name": "单包系统成本",
                "spec": "按规则重算",
                "unit_price": "-",
                "amount": default_tier["total_cost"],
                "amount_text": default_tier["total_cost_text"],
            },
        ],
        "tiers": tiers,
        "include_fob": include_fob,
    }
    result["markdown"] = render_markdown(result)
    for key in ("anomaly_scan", "anomaly_auto_fixes", "correction_rule_applications"):
        val = payload.get(key)
        if val:
            result[key] = val
    apps = result.get("correction_rule_applications")
    if isinstance(apps, list) and apps:
        try:
            from quote_correction_learning import format_rule_notice_lines

            notices = format_rule_notice_lines(apps)
            if notices:
                dn = str(result.get("data_notice") or "").strip()
                extra = " ".join(notices)
                result["data_notice"] = f"{dn} {extra}".strip() if dn else extra
        except Exception:
            pass
    return result


def build_data_notice(
    detail_rows: list[dict[str, Any]],
    *,
    accuracy_tails: list[str] | None = None,
) -> str:
    missing_spec = sum(1 for row in detail_rows if row.get("spec") == "-")
    missing_usage = sum(1 for row in detail_rows if row.get("usage") == "-")
    ai_completed = sum(1 for row in detail_rows if normalize_source(row.get("source")) == "ai")
    if missing_spec == 0 and missing_usage == 0:
        base = f"数据完整：规格和用量已采集。AI补全数据 {ai_completed} 行。"
    else:
        base = (
            f"数据提醒：规格缺失 {missing_spec} 行，用量缺失 {missing_usage} 行。"
            f" AI补全数据 {ai_completed} 行。"
        )
    tails = accuracy_tails or []
    tails = [str(t).strip() for t in tails if isinstance(t, str) and str(t).strip()]
    pkg_hint = packaging_fee_reference_hint(detail_rows)
    if pkg_hint:
        tails.append(pkg_hint)
    if not tails:
        return base
    return base + " " + " ".join(tails)


def render_markdown(result: dict[str, Any]) -> str:
    inc_fob = bool(result.get("include_fob", True))
    usd_r = result.get("usd_cny_rate")
    try:
        usd_lbl = f"{float(usd_r):.4f}" if usd_r is not None else ""
    except (TypeError, ValueError):
        usd_lbl = ""
    fx_note = f"（美元兑人民币约 {usd_lbl}）" if usd_lbl else ""
    lines = [
        "### 明细数据表",
        "",
        "| 物料名称 | 计算方式 | 规格 | 用量 | 单价 | 小计 |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in result["detail_rows"]:
        source = normalize_source(row.get("source"))
        calc = _markdown_cell(str(row.get("calc_note") or row.get("calc_method") or "-"))
        spec = _markdown_cell(row["spec"])
        usage = _markdown_cell(row["usage"])
        unit_price = _markdown_cell(str(row.get("unit_price") or "-"))
        amount_text = with_ai_label(row["amount_text"], source == "ai")
        lines.append(
            f"| {_markdown_cell(row['name'])} | {calc} | {spec} | {usage} | {unit_price} | {amount_text} |"
        )

    if inc_fob:
        hdr = (
            "| 数量 | 开模均摊 | 加工费 | 成本价（毛利前） | 预计毛利率 | "
            f"毛利公式报价(EXW){fx_note} | FOB报价（+4元/件） | EXW(USD) | FOB(USD) |"
        )
        sep = "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    else:
        hdr = (
            "| 数量 | 开模均摊 | 加工费 | 成本价（毛利前） | 含税(13%，元/件) | 预计毛利率 | "
            f"毛利公式报价(EXW){fx_note} | EXW(USD) |"
        )
        sep = "|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines.extend(
        [
            "",
            "### 三档数量报价",
            "",
            hdr,
            sep,
        ]
    )
    for tier in result["tiers"]:
        if inc_fob:
            lines.append(
                "| "
                f"{tier['quantity_text']} | "
                f"{tier['mold_share_text']} | "
                f"{tier['processing_fee_text']} | "
                f"{tier['cost_before_margin_text']} | "
                f"{tier['margin_rate_text']} | "
                f"{tier['exw_price_text']} | "
                f"{tier['fob_price_text']} | "
                f"{tier.get('exw_price_usd_text', '')} | "
                f"{tier.get('fob_price_usd_text', '')} |"
            )
        else:
            lines.append(
                "| "
                f"{tier['quantity_text']} | "
                f"{tier['mold_share_text']} | "
                f"{tier['processing_fee_text']} | "
                f"{tier['cost_before_margin_text']} | "
                f"{tier.get('taxed_price_text', '')} | "
                f"{tier['margin_rate_text']} | "
                f"{tier['exw_price_text']} | "
                f"{tier.get('exw_price_usd_text', '')} |"
            )
    return "\n".join(lines)


def with_ai_label(value: str, is_ai: bool) -> str:
    _ = is_ai
    return value
