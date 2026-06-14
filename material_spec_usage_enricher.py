"""物料规格与用量补全（展示层）与权威来源解析（计价层）。"""
from __future__ import annotations

import logging
import math
import re

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from typing import Any

from admin_bom_recalc import _default_count_usage, is_count_based_unit

_MISSING_LITERALS = frozenset(
    {
        "",
        "-",
        "—",
        "–",
        "null",
        "undefined",
        "none",
        "nan",
        "n/a",
        "na",
        "/",
    }
)

# 来源层级：admin > raw/sheet/bom > primary > calc_note > inferred
TIER_ADMIN = "admin"
TIER_RAW = "raw"
TIER_PRIMARY = "primary"
TIER_CALC_NOTE = "calc_note"
TIER_INFERRED = "inferred"
TIER_MISSING = "missing"

TRUSTED_SPEC_TIERS = frozenset({TIER_ADMIN, TIER_RAW, TIER_PRIMARY, TIER_CALC_NOTE})
TRUSTED_USAGE_TIERS = frozenset({TIER_ADMIN, TIER_RAW, TIER_PRIMARY, TIER_CALC_NOTE})

ADMIN_SPEC_KEYS = (
    "admin_corrected_spec",
    "corrected_spec",
    "admin_spec",
)
ADMIN_USAGE_KEYS = (
    "admin_corrected_usage",
    "corrected_usage",
    "admin_usage",
)
RAW_SPEC_KEYS = (
    "raw_spec",
    "original_spec",
    "sheet_spec",
    "bom_spec",
    "source_spec",
)
RAW_USAGE_KEYS = (
    "raw_usage",
    "original_usage",
    "sheet_usage",
    "bom_usage",
    "source_usage",
)
PRIMARY_SPEC_KEYS = ("spec", "规格", "尺寸", "型号", "材质规格")
PRIMARY_USAGE_KEYS = ("usage", "用量", "amount_used", "qty", "数量")

_DYNAMIC_USAGE_TOKENS = frozenset({"__SHARED_BODY_M2__", "__AUTO__"})

_PLACEHOLDER_USAGE_RE = re.compile(
    r"^[~～≈]?\s*1(?:\.0)?\s*(?:码²|㎡|m²|码|yd|套|SET|组|个|只|PCS|PC)\s*$",
    re.I,
)
_INTERNAL_USAGE_RE = re.compile(
    r"系统估算|系统推断|系统推算|AI估算|AI推断|推断待核|推理待核|本地兜底",
    re.I,
)

_GENERIC_SPEC_BLOCKLIST = frozenset(
    {
        "按表内面料规格",
        "常规辅料规格",
        "常规面料规格",
    }
)

_DIM_RE = re.compile(
    r"^\d+(\.\d+)?\s*[*xX×]\s*\d+(\.\d+)?\s*(CM|MM|M|米|码|码²|㎡|m²)?$",
    re.IGNORECASE,
)
_SPEC_FROM_NOTE = re.compile(
    r"(?:规格|尺寸|型号|材质规格)[：:\s]\s*([^\n；;]+)",
    re.IGNORECASE,
)
_USAGE_FROM_NOTE = re.compile(
    r"(?:用量|数量)[：:\s]\s*([^\n；;]+)",
    re.IGNORECASE,
)
_QTY_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(码²|㎡|m²|平方米|码|米|m|yd|个|只|件|套|条|对|卷|张|包)\b",
    re.IGNORECASE,
)
_PAREN_RE = re.compile(r"[（(]([^）)]+)[）)]")
_DENIER_RE = re.compile(r"\b(\d{2,4}[dD])\b")
_SIZE_IN_NAME_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*[*xX×]\s*\d+(?:\.\d+)?\s*(?:CM|MM|M|厘米|mm|cm|米|码|码²|㎡|m²)?)",
    re.IGNORECASE,
)
_FABRIC_SPEC_IN_NAME = re.compile(
    r"(\d{2,4}[dD]\s*(?:牛津|尼龙|涤纶|帆布|格子|涂层|PU|PVC|pu|pvc)(?:布|面料)?)",
    re.IGNORECASE,
)
_FABRIC_KEYWORDS = (
    "牛津布",
    "牛津",
    "帆布",
    "尼龙布",
    "尼龙",
    "涤纶布",
    "涤纶",
    "pu涂",
    "pvc涂",
    "涂层布",
    "格子布",
    "格子",
    "面料",
    "外料",
    "里布",
    "里料",
    "布料",
    "dcf",
    "dch",
    "x-pac",
    "xpac",
)


@dataclass(frozen=True)
class ResolvedField:
    value: str
    tier: str


def is_dynamic_rule_usage_token(text: object) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if s in _DYNAMIC_USAGE_TOKENS:
        return True
    return s.startswith("__") and s.endswith("__")


def is_placeholder_usage_value(text: object) -> bool:
    s = str(text or "").strip()
    if is_missing_spec_usage_value(s):
        return True
    if _PLACEHOLDER_USAGE_RE.match(s):
        return True
    if s in ("一套", "1套", "1组", "一组"):
        return True
    if _INTERNAL_USAGE_RE.search(s):
        return True
    return False


def _parse_bool_flag(row: dict[str, Any], key: str) -> bool:
    raw = row.get(key)
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def is_explicit_bom_usage_row(row: dict[str, Any]) -> bool:
    """原始 BOM/上传表明确填写的用量（非 AI/占位/规则改写）。"""
    if not isinstance(row, dict):
        return False
    if _parse_bool_flag(row, "usage_ai"):
        return False
    if row.get("_usage_display_inferred"):
        return False
    src = str(row.get("correction_rule_source") or "").strip()
    if src in ("anomaly_auto_fix", "correction_rule", "structure_usage"):
        return False
    usage = str(row.get("usage") or "").strip()
    if is_missing_spec_usage_value(usage) or is_placeholder_usage_value(usage):
        return False
    if is_dynamic_rule_usage_token(usage):
        return False
    if row.get("_bom_usage_locked"):
        return True
    if row.get("_sheet_usage_lock"):
        return True
    if _first_from_keys(row, RAW_USAGE_KEYS):
        return True
    src = str(row.get("source") or "").strip().lower()
    if src in ("bom", "sheet", "upload", "sales_sheet"):
        return True
    # 上传表仅填 usage、无 AI/展示推断/规则改写痕迹 → 视为明确 BOM
    return bool(usage)


def is_usage_eligible_for_auto_fix(row: dict[str, Any]) -> bool:
    """仅 AI 推断、缺失、占位或几何/规则推断用量允许自动改写。"""
    if not isinstance(row, dict):
        return False
    if _first_from_keys(row, ADMIN_USAGE_KEYS):
        return False
    if is_explicit_bom_usage_row(row):
        return False
    if _parse_bool_flag(row, "usage_ai"):
        return True
    if row.get("_usage_display_inferred"):
        return True
    usage = str(row.get("usage") or "").strip()
    if is_missing_spec_usage_value(usage) or is_placeholder_usage_value(usage):
        return True
    src = str(row.get("correction_rule_source") or "").strip()
    if src in ("structure_usage", "correction_rule"):
        return True
    calc = str(row.get("calc_note") or row.get("calc_method") or "")
    if re.search(r"里布占比|×\s*0\.22", calc, re.I):
        return True
    if re.fullmatch(r"0\.2[0-5]\s*㎡", usage, re.I):
        return True
    return False


_ROW_LEARNING_META_KEYS = (
    "raw_usage",
    "bom_usage",
    "sheet_usage",
    "source_usage",
    "_bom_usage_locked",
    "_sheet_usage_lock",
    "correction_rule_id",
    "correction_rule_source",
    "_anomaly_pending_review",
    "_anomaly_flags",
    "_anomaly_suggested_usage",
    "_anomaly_auto_fixed",
    "price_source",
    "rule_applied",
    "learning_rule_source",
    "override_id",
    "evidence",
    "override_hit",
)


def merge_row_learning_metadata(
    detail_rows: list[Any],
    source_items: Any,
) -> None:
    """把 payload items 上的 BOM/异常标记合并进 detail_rows（parse 后 enrich 前）。"""
    if not isinstance(detail_rows, list) or not isinstance(source_items, list):
        return
    by_name: dict[str, dict[str, Any]] = {}
    for raw in source_items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if name:
            by_name[name] = raw
    for dr in detail_rows:
        if not isinstance(dr, dict):
            continue
        src = by_name.get(str(dr.get("name") or "").strip())
        if not src:
            continue
        for key in _ROW_LEARNING_META_KEYS:
            if key in src and src[key] is not None:
                dr[key] = src[key]


def stamp_trusted_bom_source_fields(items: Any) -> int:
    """在规则/异常扫描前锁定 BOM 明确用量到 raw_usage/bom_usage/sheet_usage。"""
    if not isinstance(items, list):
        return 0
    stamped = 0
    for row in items:
        if not isinstance(row, dict):
            continue
        if not is_explicit_bom_usage_row(row):
            continue
        usage = str(row.get("usage") or "").strip()
        for key in RAW_USAGE_KEYS:
            if not str(row.get(key) or "").strip():
                row[key] = usage
        row["_bom_usage_locked"] = True
        stamped += 1
    return stamped


def purge_dynamic_usage_placeholders(items: Any) -> int:
    """防止 __SHARED_BODY_M2__ 等动态令牌泄漏到计价/展示。"""
    if not isinstance(items, list):
        return 0
    fixed = 0
    for row in items:
        if not isinstance(row, dict):
            continue
        usage = str(row.get("usage") or "").strip()
        if not is_dynamic_rule_usage_token(usage):
            continue
        fallback = _first_from_keys(row, RAW_USAGE_KEYS) or "-"
        row["usage"] = fallback
        fixed += 1
    return fixed


def is_missing_spec_usage_value(text: object) -> bool:
    if text is None:
        return True
    if isinstance(text, float):
        if not math.isfinite(text):
            return True
        return False
    s = str(text).strip()
    if not s:
        return True
    if s.lower() in _MISSING_LITERALS:
        return True
    return False


def _clean_display_value(text: object) -> str:
    if is_missing_spec_usage_value(text):
        return ""
    s = str(text).strip()
    if s in _GENERIC_SPEC_BLOCKLIST:
        return ""
    return s


def looks_like_dimension(text: str) -> bool:
    return bool(_DIM_RE.match(str(text or "").strip()))


def usage_is_billable_quantity(text: str) -> bool:
    """用量是否可作为数量×单价参与计价（排除纯尺寸/长度描述）。"""
    val = str(text or "").strip()
    if is_missing_spec_usage_value(val):
        return False
    if looks_like_dimension(val):
        return False
    if re.match(r"^约", val):
        try:
            from demand_parser import _looks_like_length_or_dimension_metadata

            if _looks_like_length_or_dimension_metadata(val):
                return False
        except ImportError:
            pass
    return True


def _first_from_keys(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key not in row:
            continue
        val = _clean_display_value(row.get(key))
        if val:
            return val
    return ""


def _parse_calc_note_fields(calc_note: str) -> tuple[str, str]:
    note = str(calc_note or "").strip()
    if not note:
        return "", ""
    spec = ""
    usage = ""
    m = _SPEC_FROM_NOTE.search(note)
    if m:
        spec = m.group(1).strip()
    m = _USAGE_FROM_NOTE.search(note)
    if m:
        usage = m.group(1).strip()
    if not usage:
        hits = _QTY_UNIT_RE.findall(note)
        if hits:
            n, u = hits[-1]
            usage = f"{n}{u}"
    return spec, usage


def _primary_spec_keys(row: dict[str, Any]) -> tuple[str, ...]:
    if row.get("_spec_display_inferred"):
        return ()
    return PRIMARY_SPEC_KEYS


def _primary_usage_keys(row: dict[str, Any]) -> tuple[str, ...]:
    if row.get("_usage_display_inferred"):
        return ()
    return PRIMARY_USAGE_KEYS


def resolve_spec_from_row(row: dict[str, Any]) -> ResolvedField:
    """按优先级解析可用于计价/对账的规格（不含展示层推断值）。"""
    val = _first_from_keys(row, ADMIN_SPEC_KEYS)
    if val:
        return ResolvedField(val, TIER_ADMIN)
    val = _first_from_keys(row, RAW_SPEC_KEYS)
    if val:
        return ResolvedField(val, TIER_RAW)
    val = _first_from_keys(row, _primary_spec_keys(row))
    if val:
        return ResolvedField(val, TIER_PRIMARY)
    calc = str(row.get("calc_note") or row.get("calc_method") or "")
    cn_spec, _ = _parse_calc_note_fields(calc)
    if cn_spec:
        return ResolvedField(cn_spec, TIER_CALC_NOTE)
    return ResolvedField("", TIER_MISSING)


def resolve_usage_from_row(row: dict[str, Any]) -> ResolvedField:
    """按优先级解析可用于计价/对账的用量（不含展示层推断值）。"""
    val = _first_from_keys(row, ADMIN_USAGE_KEYS)
    if val:
        return ResolvedField(val, TIER_ADMIN)
    val = _first_from_keys(row, RAW_USAGE_KEYS)
    if val:
        return ResolvedField(val, TIER_RAW)
    val = _first_from_keys(row, _primary_usage_keys(row))
    if val:
        return ResolvedField(val, TIER_PRIMARY)
    calc = str(row.get("calc_note") or row.get("calc_method") or "")
    _, cn_usage = _parse_calc_note_fields(calc)
    if cn_usage:
        return ResolvedField(cn_usage, TIER_CALC_NOTE)
    return ResolvedField("", TIER_MISSING)


def is_spec_trusted_for_calc(tier: str) -> bool:
    return tier in TRUSTED_SPEC_TIERS


def is_usage_trusted_for_calc(tier: str) -> bool:
    return tier in TRUSTED_USAGE_TIERS


def row_has_valid_amount(row: dict[str, Any]) -> bool:
    raw = row.get("amount")
    if raw is None or raw == "":
        return False
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return False
    return math.isfinite(val) and val > 0.001


def spec_for_amount_calc(row: dict[str, Any]) -> str:
    """计价路径使用的规格；不采用展示推断值。"""
    res = resolve_spec_from_row(row)
    return res.value or "-"


def usage_for_amount_recalc(row: dict[str, Any]) -> str:
    """计价重算用量×单价时使用的用量；推断补齐不参与重算。"""
    usage_res = resolve_usage_from_row(row)
    usage = usage_res.value

    if is_usage_trusted_for_calc(usage_res.tier) and usage:
        if usage_is_billable_quantity(usage):
            return usage
        return "-"

    if row_has_valid_amount(row):
        return "-"

    return "-"


def _is_fabric_material(name: str, blob: str) -> bool:
    text = f"{name} {blob}".lower()
    if any(k in text for k in _FABRIC_KEYWORDS):
        return True
    if _FABRIC_SPEC_IN_NAME.search(name or ""):
        return True
    if _DENIER_RE.search(name or "") and any(
        k in text for k in ("牛津", "尼龙", "涤纶", "帆布", "布", "面料")
    ):
        return True
    return False


def _fabric_spec_from_name(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    m = _FABRIC_SPEC_IN_NAME.search(text)
    if m:
        return m.group(1).strip()
    if _DENIER_RE.search(text):
        m2 = re.search(
            r"(\d{2,4}[dD][^\s，,;；]{0,16}(?:布|面料)?)",
            text,
            re.IGNORECASE,
        )
        if m2:
            return m2.group(1).strip()
    if _is_fabric_material(text, text) and len(text) <= 48:
        return text
    return ""


def _extract_spec_from_name(name: str) -> str:
    fabric = _fabric_spec_from_name(name)
    if fabric:
        return fabric
    text = str(name or "").strip()
    if not text:
        return ""
    for m in _PAREN_RE.finditer(text):
        inner = m.group(1).strip()
        if inner and not is_missing_spec_usage_value(inner):
            if looks_like_dimension(inner) or _DENIER_RE.search(inner) or len(inner) <= 48:
                return inner
    dm = _SIZE_IN_NAME_RE.search(text)
    if dm:
        return dm.group(1).strip()
    den = _DENIER_RE.search(text)
    if den:
        return den.group(1).upper()
    return ""


def _name_blob(row: dict[str, Any]) -> str:
    auth_spec = resolve_spec_from_row(row).value
    auth_usage = resolve_usage_from_row(row).value
    parts = [
        str(row.get("name") or ""),
        auth_spec,
        auth_usage,
        str(row.get("calc_note") or row.get("calc_method") or ""),
        str(row.get("material_clue") or ""),
    ]
    return " ".join(p.strip() for p in parts if p.strip()).lower()


def _is_zipper_material(name: str, blob: str = "") -> bool:
    text = f"{name} {blob}".lower()
    return any(k in text for k in ("拉链", "zipper", "zip")) and "拉头" not in name


def _zipper_display_spec(name: str, row: dict[str, Any]) -> str:
    """拉链类展示规格：保留型号，禁止 '/' 或空。"""
    clean = str(name or "").strip()
    clean = re.sub(r"[（(]\s*推理待核\s*[)）]", "", clean).strip()
    if not clean:
        return "待核"
    if re.search(r"#\s*5|5\s*#", clean, re.I):
        if "尼龙" in clean:
            return "#5尼龙拉链"
        return "#5拉链"
    if len(clean) <= 48 and not is_missing_spec_usage_value(clean):
        return clean
    if re.search(r"尼龙|nylon", clean, re.I):
        return "尼龙拉链"
    if re.search(r"树脂|金属|防水", clean, re.I):
        return clean[:48]
    unit_price = str(row.get("unit_price") or "")
    if re.search(r"元\s*/\s*条|/条", unit_price, re.I):
        return "1条"
    return "1条"


def _infer_display_spec(name: str, row: dict[str, Any]) -> str:
    from_name = _extract_spec_from_name(name)
    if from_name:
        return from_name
    blob = _name_blob(row)
    if _is_zipper_material(name, blob):
        return _zipper_display_spec(name, row)
    if _is_fabric_material(name, blob):
        fs = _fabric_spec_from_name(name)
        if fs:
            return fs
        n = str(name or "").strip()
        if n and len(n) <= 48:
            return n
    rules: list[tuple[tuple[str, ...], str]] = [
        (("拉头", "puller", "slider"), "普通拉头"),
        (("插扣", "梯扣", "猪鼻", "d扣", "d环", "调节扣", "buckle", "扣具"), "常规塑料扣具"),
        (("挂钩", "hook"), "常规挂钩"),
        (("缝纫线", "thread"), "常规缝纫线"),
        (("魔术贴", "velcro", "魔術貼"), "常规魔术贴"),
        (("织标", "布标", "唛", "label", "logo标", "贴标"), "常规织标"),
        (("包装袋", "胶袋", "pe袋", "纸箱", "外箱", "包装"), "常规包装袋"),
        (("织带", "webbing", "肩带", "背带", "提手带"), "常规织带"),
        (("拉链", "zipper", "zip"), "常规拉链"),
        (("弹力绳", "绳", "cord"), "常规绳带"),
        (("里布", "里料", "lining"), "常规里布"),
        (("海绵", "eva", "泡棉"), "常规海绵辅料"),
        (("补强", "加固"), "常规补强辅料"),
    ]
    for keys, label in rules:
        if any(k in blob for k in keys):
            return label
    clue = _clean_display_value(row.get("material_clue"))
    if clue and clue not in _GENERIC_SPEC_BLOCKLIST:
        return clue[:80]
    return "常规辅料规格"


def _usage_from_unit_price(unit_price: str) -> str:
    up = str(unit_price or "").strip()
    if is_count_based_unit("", up):
        return _default_count_usage("", up)
    if re.search(r"元\s*/\s*米|/米|元/米|per\s*m\b", up, re.I):
        return "1米"
    if re.search(r"元\s*/\s*码|/码|元/码|per\s*yd", up, re.I):
        return "1码"
    if re.search(r"元\s*/\s*码²|元\s*/\s*㎡|/码²|/㎡|m²|㎡", up, re.I):
        return "0.1㎡"
    if re.search(r"元\s*/\s*条|/条", up, re.I):
        return "1条"
    if re.search(r"元\s*/\s*套|/套", up, re.I):
        return ""
    if re.search(r"元\s*/\s*处|/处", up, re.I):
        return "1处"
    return ""


def _infer_display_usage(name: str, row: dict[str, Any], *, structure_text: str) -> str:
    blob = _name_blob(row)
    if any(k in blob for k in ("纸箱", "外箱")):
        return "1个外纸箱"
    if any(k in blob for k in ("包装袋", "胶袋", "pe袋")):
        return "1个包装袋"
    if "包装" in blob:
        return "1个"
    unit_price = str(row.get("unit_price") or "").strip()
    from_price = _usage_from_unit_price(unit_price)
    if from_price:
        return from_price

    if any(k in blob for k in ("拉头", "puller", "slider")):
        return "1个"
    if any(k in blob for k in ("插扣", "扣具", "buckle", "d扣", "d环", "调节扣", "梯扣", "猪鼻")):
        return "1个"
    if "挂钩" in blob or "hook" in blob:
        return "1个"
    if any(k in blob for k in ("织标", "布标", "唛", "label", "贴标")):
        return "1个"
    if any(k in blob for k in ("缝纫线", "thread")) and "线" in blob:
        return "1卷"
    if any(k in blob for k in ("魔术贴", "velcro")):
        return "1条"
    if any(k in blob for k in ("织带", "webbing", "肩带", "背带")):
        return "0.5米"
    if "拉链" in blob or "zipper" in blob:
        return "1条"
    if any(k in blob for k in ("绳", "cord", "弹力")):
        return "0.3米"
    if _is_fabric_material(name, blob):
        if re.search(r"码²|㎡|m²", unit_price, re.I):
            return "0.2㎡"
        return "0.3码"
    return "1个"


def usage_holds_dimension_with_empty_spec(
    auth_spec: ResolvedField,
    usage_text: str,
) -> bool:
    """尺寸已落在 usage、spec 无有效值：展示层 spec 保持 '-'（与计价 normalize 一致）。"""
    if not looks_like_dimension(usage_text):
        return False
    return is_missing_spec_usage_value(auth_spec.value)


def _merge_display_spec_usage(
    auth_spec: ResolvedField,
    auth_usage: ResolvedField,
    *,
    name: str,
    row: dict[str, Any],
    structure_text: str,
) -> tuple[str, str, bool, bool]:
    """返回展示用 spec/usage 及是否仅为推断补齐。"""
    spec = auth_spec.value
    usage = auth_usage.value
    spec_inferred = False
    usage_inferred = False

    if is_missing_spec_usage_value(usage) and looks_like_dimension(spec):
        return spec.strip() or "-", "-", False, False

    if usage_holds_dimension_with_empty_spec(auth_spec, usage):
        return "-", usage.strip(), False, False

    if is_missing_spec_usage_value(spec):
        spec = _extract_spec_from_name(name)
        if spec:
            spec_inferred = auth_spec.tier == TIER_MISSING
    if is_missing_spec_usage_value(spec):
        spec = _infer_display_spec(name, row)
        spec_inferred = True

    if is_missing_spec_usage_value(usage):
        usage = _infer_display_usage(name, row, structure_text=structure_text)
        usage_inferred = True

    return spec.strip(), usage.strip(), spec_inferred, usage_inferred


def enrich_material_row(
    row: dict[str, Any],
    *,
    structure_text: str = "",
    product_size: dict[str, Any] | None = None,
    product_name: str = "",
) -> dict[str, Any]:
    """仅补全展示字段 spec/usage，不改变 amount；推断用量标记为不参与计价重算。"""
    del product_size  # 展示推断暂不使用尺寸几何，避免与 structure_usage 重复
    if not isinstance(row, dict):
        return row
    name = str(row.get("name") or "").strip()
    if not name:
        return row
    if row.get("exclude_from_cost") or str(row.get("recognition_status") or "").strip() == "ignored":
        return row

    stamp_trusted_bom_source_fields([row])
    try:
        from quote_correction_learning import apply_correction_rules_to_row

        apply_correction_rules_to_row(
            row,
            {
                "structure_text": structure_text,
                "product_name": product_name,
            },
        )
        purge_dynamic_usage_placeholders([row])
    except Exception:
        logger.exception("apply_correction_rules_to_row failed name=%s", name)

    auth_spec = resolve_spec_from_row(row)
    auth_usage = resolve_usage_from_row(row)
    st = str(structure_text or "").strip()

    display_spec, display_usage, spec_inf, usage_inf = _merge_display_spec_usage(
        auth_spec,
        auth_usage,
        name=name,
        row=row,
        structure_text=st,
    )

    row["spec"] = display_spec
    row["usage"] = display_usage
    if spec_inf:
        row["_spec_display_inferred"] = True
    else:
        row.pop("_spec_display_inferred", None)
    if usage_inf:
        row["_usage_display_inferred"] = True
    else:
        row.pop("_usage_display_inferred", None)

    return row


def enrich_material_rows(
    rows: list[Any],
    *,
    structure_text: str = "",
    product_size: dict[str, Any] | None = None,
    product_name: str = "",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        enrich_material_row(
            row,
            structure_text=structure_text,
            product_size=product_size,
            product_name=product_name,
        )
        out.append(row)
    return out


def enrich_payload_material_spec_usage(payload: dict[str, Any] | None) -> None:
    if not isinstance(payload, dict):
        return
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return
    st = str(
        payload.get("structure_text_snapshot")
        or payload.get("structure_text")
        or ""
    ).strip()
    ps = payload.get("product_size") if isinstance(payload.get("product_size"), dict) else {}
    pn = str(payload.get("product_name") or "")
    payload["items"] = enrich_material_rows(
        items, structure_text=st, product_size=ps, product_name=pn
    )


def enrich_quote_detail_rows(
    quote_obj: dict[str, Any] | None,
    *,
    structure_text: str = "",
    product_size: dict[str, Any] | None = None,
) -> None:
    if not isinstance(quote_obj, dict):
        return
    dr = quote_obj.get("detail_rows")
    if not isinstance(dr, list) or not dr:
        return
    pn = str(quote_obj.get("product_name") or "")
    quote_obj["detail_rows"] = enrich_material_rows(
        dr,
        structure_text=structure_text,
        product_size=product_size,
        product_name=pn,
    )
    from material_detail_display import enrich_quote_material_detail_display

    enrich_quote_material_detail_display(
        quote_obj,
        structure_text=structure_text,
        product_size=product_size,
    )
    stamp_trusted_bom_source_fields(quote_obj.get("detail_rows"))
    stamp_trusted_bom_source_fields(quote_obj.get("items"))
    try:
        from quote_correction_learning import apply_learning_rules_to_quote

        apply_learning_rules_to_quote(quote_obj)
        purge_dynamic_usage_placeholders(quote_obj.get("detail_rows"))
        purge_dynamic_usage_placeholders(quote_obj.get("items"))
    except Exception:
        logger.exception("apply_learning_rules_to_quote failed")
    try:
        from quote_anomaly_learning import scan_and_learn_from_quote

        scan_and_learn_from_quote(
            quote_obj,
            quote_uid=str(quote_obj.get("quote_uid") or quote_obj.get("id") or ""),
            apply_auto_fix=True,
            record_history=bool(quote_obj.get("quote_uid") or quote_obj.get("id")),
        )
        purge_dynamic_usage_placeholders(quote_obj.get("detail_rows"))
        purge_dynamic_usage_placeholders(quote_obj.get("items"))
    except Exception:
        logger.exception("scan_and_learn_from_quote failed")
