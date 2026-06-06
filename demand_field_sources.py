"""需求表字段来源分类：区分可生成 BOM 的显式字段 vs 仅作说明的备注字段。"""

from __future__ import annotations

import re
from typing import Any

# --- 字段来源类型 ---
EXPLICIT_MATERIAL_FIELD = "explicit_material_field"
EXPLICIT_ACCESSORY_FIELD = "explicit_accessory_field"
PROCESS_FIELD = "process_field"
PRODUCT_SPEC_FIELD = "product_spec_field"
STRUCTURE_NOTE_FIELD = "structure_note_field"
REMARK_FIELD = "remark_field"

# 结构件：无明确证据时不自动加入 BOM
GUARDED_STRUCTURE_COMPONENTS: frozenset[str] = frozenset(
    {
        "网袋",
        "隔层",
        "侧袋",
        "背垫",
        "提手",
        "内袋",
        "电脑仓",
        "腰封",
        "顶包",
        "翻盖",
        "前袋",
        "水壶袋",
    }
)

MIN_GUARDED_INFERENCE_CONFIDENCE = 0.88

_SECTION_B_NOTE_KEYS = frozenset(
    {
        "结构说明",
        "参考图片链接",
        "参考图片",
        "参考图链接",
        "参考链接",
        "补充说明",
        "备注",
        "成本要求",
        "成本参考",
        "价格参考",
        "客户备注",
    }
)

_SECTION_B_SPEC_KEYS = frozenset(
    {
        "产品类型",
        "产品类别",
        "类别",
        "类型",
        "产品名称款号",
        "产品名称",
        "品名款号",
        "款式名称",
        "结构复杂度",
        "lcm",
        "wcm",
        "hcm",
        "长",
        "宽",
        "高",
        "厚",
        "深",
        "成品尺寸",
        "尺寸",
        "产品尺寸",
    }
)

_SECTION_C_ACCESSORY_KEYS = frozenset(
    {
        "拉链类型",
        "拉头类型",
        "扣具等级",
        "肩带织带类型",
        "肩带",
        "织带",
        "绳带",
        "加固辅料",
        "加固辅料多选",
        "包边",
    }
)

_SECTION_C_MATERIAL_KEYS = frozenset(
    {
        "外料",
        "外料标准名编码",
        "里料",
        "里料标准名编码",
    }
)

_SECTION_C_REMARK_KEYS = frozenset(
    {
        "外料颜色",
        "里料颜色",
        "拉链颜色",
        "防水等级",
        "肩带长度",
        "肩带长度cm",
    }
)

_NOTE_SNIPPET_MARKERS = (
    "成本要控制",
    "成本参考",
    "价格参考",
    "控制在",
    "元以内",
    "工作簿内超链接",
    "工作簿嵌入图片",
    "辅助产品结构",
    "仅供参考",
    "模板",
    "示例",
    "规范",
    "两边可以",
    "可扣在一起",
    "大身面料",
    "参考图片",
)

_APPENDIX_MARKERS = (
    "【工作簿内超链接",
    "【工作簿嵌入图片",
)


def _norm_field_key(key: str) -> str:
    return re.sub(r"\s+", "", str(key or "").strip().lower())


def classify_demand_field(section_letter: str, field_key: str) -> str:
    """按区块与表头判定字段来源类型。"""
    letter = str(section_letter or "").strip().upper()
    key = _norm_field_key(field_key)

    if letter == "B":
        raw = str(field_key or "").strip()
        if raw in _SECTION_B_NOTE_KEYS or key in {_norm_field_key(k) for k in _SECTION_B_NOTE_KEYS}:
            return STRUCTURE_NOTE_FIELD
        if raw in _SECTION_B_SPEC_KEYS or key in {_norm_field_key(k) for k in _SECTION_B_SPEC_KEYS}:
            return PRODUCT_SPEC_FIELD
        if any(m in raw for m in ("参考", "备注", "说明", "成本", "图片", "链接")):
            return REMARK_FIELD
        return PRODUCT_SPEC_FIELD

    if letter == "C":
        raw = str(field_key or "").strip()
        if raw in _SECTION_C_REMARK_KEYS or key in {_norm_field_key(k) for k in _SECTION_C_REMARK_KEYS}:
            return REMARK_FIELD
        if raw in _SECTION_C_MATERIAL_KEYS or key in {_norm_field_key(k) for k in _SECTION_C_MATERIAL_KEYS}:
            return EXPLICIT_MATERIAL_FIELD
        if raw in _SECTION_C_ACCESSORY_KEYS or key in {_norm_field_key(k) for k in _SECTION_C_ACCESSORY_KEYS}:
            return EXPLICIT_ACCESSORY_FIELD
        if any(m in raw for m in ("外料", "里料", "拉链", "拉头", "扣具", "织带", "肩带", "绳带", "包边", "辅料")):
            if "颜色" in raw or "长度" in raw or "等级" in raw and "扣具" not in raw:
                return REMARK_FIELD
            if any(m in raw for m in ("外料", "里料")):
                return EXPLICIT_MATERIAL_FIELD
            return EXPLICIT_ACCESSORY_FIELD
        return REMARK_FIELD

    if letter == "D":
        return PROCESS_FIELD
    if letter in {"E", "F", "G"}:
        return PRODUCT_SPEC_FIELD
    if letter == "A":
        return REMARK_FIELD
    return REMARK_FIELD


def build_field_source_map(sections: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for letter, fields in (sections or {}).items():
        if not isinstance(fields, dict):
            continue
        sec: dict[str, str] = {}
        for fk, fv in fields.items():
            if not str(fv or "").strip():
                continue
            sec[str(fk)] = classify_demand_field(letter, str(fk))
        if sec:
            out[str(letter)] = sec
    return out


def build_structure_inference_text(
    sections: dict[str, dict[str, str]],
    *,
    is_demand_template: bool = True,
) -> str:
    """
    仅拼接可驱动结构推断的显式字段。
    标准需求表模板下返回空串：结构说明/参考图/备注不得生成 BOM。
    """
    if is_demand_template:
        return ""
    parts: list[str] = []
    for letter, fields in (sections or {}).items():
        if not isinstance(fields, dict):
            continue
        for fk, fv in fields.items():
            src = classify_demand_field(letter, str(fk))
            if src in {STRUCTURE_NOTE_FIELD, REMARK_FIELD}:
                continue
            text = str(fv or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def split_structure_context_text(structure_text: str) -> tuple[str, str]:
    """将富文本拆为「可推断正文」与「附录/备注块」。"""
    raw = str(structure_text or "").strip()
    if not raw:
        return "", ""
    cut_at = len(raw)
    for marker in _APPENDIX_MARKERS:
        idx = raw.find(marker)
        if idx >= 0:
            cut_at = min(cut_at, idx)
    main = raw[:cut_at].strip()
    appendix = raw[cut_at:].strip() if cut_at < len(raw) else ""
    return main, appendix


def is_remark_like_snippet(text: object) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    if any(m in s for m in _NOTE_SNIPPET_MARKERS):
        return True
    if any(m in s for m in _APPENDIX_MARKERS):
        return True
    if re.search(r"成本\D{0,8}\d+\s*元", s):
        return True
    return False


def resolve_inference_structure_text(
    *,
    structure_text: str = "",
    structure_inference_text: str | None = None,
    demand_template: bool = False,
) -> str:
    """包类管线用于结构清单/推理的文本源。"""
    if demand_template:
        return ""
    if structure_inference_text is not None:
        return str(structure_inference_text or "").strip()
    main, _ = split_structure_context_text(structure_text)
    if is_remark_like_snippet(main):
        return ""
    return main.strip()


def collect_structure_note_hints(
    structure_text: str,
    *,
    demand_template: bool = False,
    items: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """从结构说明/备注识别可能缺项（简版）；完整 schema 见 structure_gap_hints。"""
    from structure_gap_hints import collect_structure_note_hints as _collect

    return _collect(structure_text, demand_template=demand_template, items=items)


def should_add_guarded_structure_component(
    component_name: str,
    *,
    confidence: float,
    source_snippet: str,
    demand_template: bool = False,
) -> bool:
    """结构件是否允许自动加入 BOM。"""
    name = str(component_name or "").strip()
    if name not in GUARDED_STRUCTURE_COMPONENTS:
        return True
    if demand_template:
        return False
    if is_remark_like_snippet(source_snippet):
        return False
    return float(confidence) >= MIN_GUARDED_INFERENCE_CONFIDENCE


def material_row_source_type(demand_source: str, role: str = "") -> str:
    ds = str(demand_source or "").strip()
    rl = str(role or "").strip()
    if ds in {"structure_inline", "structure_keyword", "structure_inline_outer_fallback"}:
        return STRUCTURE_NOTE_FIELD
    if rl in {"外料", "里料"}:
        return EXPLICIT_MATERIAL_FIELD
    if rl in {"拉链", "拉头", "扣具", "织带", "肩带", "绳带", "辅料"}:
        return EXPLICIT_ACCESSORY_FIELD
    if ds == "demand_form":
        if rl in {"外料", "里料"}:
            return EXPLICIT_MATERIAL_FIELD
        return EXPLICIT_ACCESSORY_FIELD
    return REMARK_FIELD
