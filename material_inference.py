"""结构/图片推理补漏：Excel 未写全的材料、配件、工艺候选项（非确定数据）。"""

from __future__ import annotations

import re
from typing import Any

from bag_structure_list import (
    _detected_components,
    _extract_source_snippet,
    _row_matches_any,
    _structure_mentions_keyword,
)
from sheet_parser import normalize_text

INFERENCE_NOTE = "结构/图片推理，需人工复核"
SOURCE_STRUCTURE = "structure_inferred"
SOURCE_IMAGE = "image_inferred"
PENDING_INFERENCE_USAGE_FALLBACK = "待填数量"

_EXPLICIT_USAGE_IN_TEXT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:码²|码|m²|㎡|米|m|条|套|个|只|处|片|pcs|pc|pair|yd²|yd|cm|mm|厘米|毫米)",
    re.I,
)
_PENDING_USAGE_TEXT_RE = re.compile(r"^几[\u4e00-\u9fff]+$")


def is_inference_pending_name(name: object) -> bool:
    text = str(name or "")
    return any(k in text for k in ("推理待核", "结构待核", "推断待核"))


def is_pending_inference_usage_text(text: object) -> bool:
    s = str(text or "").strip()
    if not s or s in {PENDING_INFERENCE_USAGE_FALLBACK, "待确认", "-", "—"}:
        return True
    if _PENDING_USAGE_TEXT_RE.match(s):
        return True
    return False


def extract_explicit_usage_from_row(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    for field in ("name", "usage", "_source_combined_name"):
        text = str(row.get(field) or "").strip()
        if not text:
            continue
        match = _EXPLICIT_USAGE_IN_TEXT_RE.search(text)
        if match:
            return match.group(0).strip()
    return ""


def pending_inference_usage_label(name: str, row: dict[str, Any] | None = None) -> str:
    """推理待核项默认用量：只给待确认单位，不用 1套/1组。"""
    row = row if isinstance(row, dict) else {}
    explicit = extract_explicit_usage_from_row({"name": name, **row})
    if explicit:
        return explicit
    clean = re.sub(r"[（(]\s*推理待核\s*[)）]", "", str(name or "")).strip()
    clean = re.sub(r"[（(]\s*结构待核\s*[)）]", "", clean).strip()
    blob = clean.lower()
    if any(k in clean for k in ("侧袋", "侧兜", "side pocket")):
        return "几个"
    if any(k in clean for k in ("背垫", "背板")):
        return "几片"
    if any(k in clean for k in ("隔层", "夹层", "分隔", "内袋", "贴片")):
        return "几片"
    if any(k in clean for k in ("前片", "后片", "底片", "侧片", "顶片", "盖片")):
        return "几片"
    if any(k in clean for k in ("提手", "手挽")):
        return "几条"
    if any(k in clean for k in ("肩带", "背带")) and "织带" not in clean:
        return "几条"
    if any(k in clean for k in ("包边", "织带", "webbing", "绳带", "松紧", "橡筋", "zipper", "拉链")):
        return "几米"
    if any(k in clean for k in ("拉头", "拉尾", "扣具", "插扣", "d扣", "d环", "调节扣", "梯扣", "猪鼻", "标牌", "五金", "buckle", "puller")):
        return "几个"
    if any(k in clean for k in ("工艺费", "加工费", "车缝", "印刷", "热压", "刺绣", "丝印", "热转印")):
        return "几道工序"
    if any(k in clean for k in ("包装", "纸箱", "外箱", "胶袋", "pe袋")):
        return "几个"
    if "套" in blob or "组" in blob:
        return PENDING_INFERENCE_USAGE_FALLBACK
    return PENDING_INFERENCE_USAGE_FALLBACK

# 扩展推理目录（通用词表，非订单硬编码）
_EXTRA_INFERENCE_COMPONENTS: tuple[dict[str, Any], ...] = (
    {
        "name": "拉头",
        "category": "accessory",
        "category_label": "辅料配件",
        "synonyms": ("拉头", "拉链头", "puller"),
        "affects_cost": True,
    },
    {
        "name": "拉尾",
        "category": "accessory",
        "category_label": "辅料配件",
        "synonyms": ("拉尾", "拉链尾", "zipper tail"),
        "affects_cost": True,
    },
    {
        "name": "透明PVC",
        "category": "functional",
        "category_label": "功能材料",
        "synonyms": ("透明pvc", "透明PVC", "pvc视窗", "PVC窗", "透明窗"),
        "affects_cost": True,
    },
    {
        "name": "包边",
        "category": "accessory",
        "category_label": "辅料配件",
        "synonyms": ("包边", "滚边", "binding"),
        "affects_cost": True,
    },
    {
        "name": "提手",
        "category": "carry",
        "category_label": "背负结构",
        "synonyms": ("提手", "手挽", "handle"),
        "affects_cost": True,
    },
    {
        "name": "隔层",
        "category": "internal",
        "category_label": "内部结构",
        "synonyms": ("隔层", "分隔层", "夹层"),
        "affects_cost": True,
    },
    {
        "name": "固定带",
        "category": "accessory",
        "category_label": "辅料配件",
        "synonyms": ("固定带", "绑带", "compression strap"),
        "affects_cost": True,
    },
    {
        "name": "扣具",
        "category": "accessory",
        "category_label": "辅料配件",
        "synonyms": ("扣具", "D扣", "日字扣", "梯扣", "调节扣"),
        "affects_cost": True,
    },
    {
        "name": "加固片",
        "category": "functional",
        "category_label": "功能材料",
        "synonyms": ("加固片", "补强片", "耐磨片"),
        "affects_cost": True,
    },
    {
        "name": "工艺费",
        "category": "process",
        "category_label": "工艺",
        "synonyms": ("工艺费", "加工费", "车缝费", "丝印", "热转印", "刺绣", "电压"),
        "affects_cost": True,
    },
)

_PROCESS_INFERENCE_RE = re.compile(
    r"(丝印|热转印|刺绣|电压|高频|车缝|打枣|打钉|贴合|防水压条|上胶)",
    re.I,
)


def is_inferred_cost_row(row: dict[str, Any]) -> bool:
    st = str(row.get("source_type") or "").strip()
    if st in {SOURCE_STRUCTURE, SOURCE_IMAGE}:
        return True
    return bool(row.get("inferred_by_ai"))


def is_excel_explicit_row(row: dict[str, Any]) -> bool:
    """表格明确列出的材料行（确定数据，非推理候选项）。"""
    if not isinstance(row, dict):
        return False
    if is_inferred_cost_row(row):
        return False
    if bool(row.get("from_bag_structure_extraction")) and (
        "结构待核" in str(row.get("name") or "") or "推理待核" in str(row.get("name") or "")
    ):
        return False
    if str(row.get("recognition_status") or "").strip() == "candidate_review" and bool(
        row.get("needs_human_confirm")
    ):
        if "推理" in str(row.get("name") or "") or "结构待核" in str(row.get("name") or ""):
            return False
    return bool(str(row.get("name") or "").strip())


def count_excel_explicit_rows(items: list[dict[str, Any]]) -> int:
    return sum(1 for r in items if is_excel_explicit_row(r))


def _items_cover_component(items: list[dict[str, Any]], synonyms: tuple[str, ...]) -> bool:
    for row in items:
        if not isinstance(row, dict):
            continue
        if is_inferred_cost_row(row):
            blob = " ".join(
                str(row.get(k) or "")
                for k in ("name", "role", "spec")
            )
        else:
            blob = " ".join(
                str(row.get(k) or "")
                for k in ("name", "role", "spec", "calc_note", "recognition_reason")
            )
        if _row_matches_any(blob, synonyms):
            return True
    return False


def _dedupe_key(name: str) -> str:
    text = str(name or "").strip()
    text = re.sub(r"[（(].*?[）)]", "", text)
    return normalize_text(text)


def build_inferred_candidate_row(
    *,
    component_name: str,
    source_type: str,
    source_snippet: str,
    structure_id: str = "",
    category_label: str = "",
) -> dict[str, Any]:
    label = "结构说明" if source_type == SOURCE_STRUCTURE else "产品附图/结构图"
    snippet = str(source_snippet or "").strip()[:120]
    row = {
        "name": f"{component_name}（推理待核）",
        "spec": "",
        "usage": "",
        "unit_price": "-",
        "amount": 0.0,
        "source_type": source_type,
        "inferred_by_ai": True,
        "needs_human_confirm": True,
        "needs_manual_confirm": True,
        "from_bag_structure_extraction": True,
        "recognition_status": "candidate_review",
        "recognition_reason": f"{label}推理：{snippet or component_name}",
        "calc_note": INFERENCE_NOTE,
        "exclude_from_cost": True,
        "amount_in_cost": False,
        "usage_ai": True,
        "unit_price_ai": True,
        "source": "ai",
        "kb_hit": False,
    }
    if structure_id:
        row["structure_id"] = structure_id
    if category_label:
        row["category_label"] = category_label
    if snippet:
        row["source_structure_desc"] = snippet
    from material_spec_usage_enricher import enrich_material_row

    enrich_material_row(row, structure_text=snippet)
    return row


def _all_detected_components(structure_text: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for comp in _detected_components(structure_text):
        name = str(comp.get("name") or "").strip()
        key = _dedupe_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(comp)
    for comp in _EXTRA_INFERENCE_COMPONENTS:
        synonyms = tuple(comp.get("synonyms") or ())
        if not _structure_mentions_keyword(structure_text, synonyms):
            continue
        name = str(comp.get("name") or "").strip()
        key = _dedupe_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        line_snippet, _conf = _extract_source_snippet(structure_text, synonyms)
        out.append(
            {
                "structure_id": "",
                "name": name,
                "category": comp.get("category"),
                "category_label": comp.get("category_label"),
                "source_text": line_snippet or name,
                "extracted_confidence": 0.72,
                "affects_cost": bool(comp.get("affects_cost", True)),
                "synonyms": synonyms,
            }
        )
    if _PROCESS_INFERENCE_RE.search(structure_text or ""):
        key = _dedupe_key("工艺费")
        if key and key not in seen:
            seen.add(key)
            out.append(
                {
                    "structure_id": "",
                    "name": "工艺费",
                    "category": "process",
                    "category_label": "工艺",
                    "source_text": _PROCESS_INFERENCE_RE.search(structure_text or "").group(0),
                    "extracted_confidence": 0.7,
                    "affects_cost": True,
                    "synonyms": ("工艺费", "丝印", "热转印", "刺绣"),
                }
            )
    return out


def _vision_suggests_extra_components(vision_text: str) -> list[str]:
    """从附图说明/视觉摘要中提取可能存在的部件名（规则层，不编价）。"""
    blob = str(vision_text or "").strip().lower()
    if not blob:
        return []
    hints: list[str] = []
    keyword_map = (
        ("网袋", ("网袋", "网兜", "mesh pocket")),
        ("侧袋", ("侧袋", "侧兜", "side pocket")),
        ("前袋", ("前袋", "前仓", "front pocket")),
        ("肩带", ("肩带", "strap", "shoulder")),
        ("提手", ("提手", "handle", "top handle")),
        ("拉链", ("拉链", "zipper", "zip")),
        ("里布", ("里布", "里料", "lining")),
        ("织带", ("织带", "webbing")),
        ("扣具", ("扣具", "buckle", "d扣", "插扣")),
    )
    for label, terms in keyword_map:
        if any(t in blob for t in terms):
            hints.append(label)
    return hints


def _snippet_for_inference(name: str, comp: dict[str, Any], structure_text: str) -> str:
    raw = str(comp.get("source_text") or "").strip()
    if raw and len(raw) <= 80 and raw != str(structure_text or "").strip()[:120]:
        return raw[:80]
    synonyms = tuple(comp.get("synonyms") or (name,))
    line, _ = _extract_source_snippet(structure_text, synonyms)
    return (line or name)[:80]


def infer_missing_cost_candidates(
    structure_text: str,
    items: list[dict[str, Any]],
    *,
    vision_text: str = "",
    image_present: bool = False,
    demand_template: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    根据结构说明 / 附图上下文，推理 Excel 未覆盖的成本候选项。
    返回 (candidate_rows, report)。
    """
    from demand_field_sources import should_add_guarded_structure_component

    rows = [r for r in items if isinstance(r, dict)]
    working = list(rows)
    new_rows: list[dict[str, Any]] = []
    added_meta: list[dict[str, str]] = []
    skipped_meta: list[dict[str, str]] = []
    existing_keys = {_dedupe_key(str(r.get("name") or "")) for r in working}
    inference_blob = str(structure_text or "").strip()
    if demand_template or not inference_blob:
        explicit_n = count_excel_explicit_rows(working)
        return [], {
            "candidates_added": 0,
            "added": [],
            "skipped_guarded": skipped_meta,
            "excel_explicit_row_count": explicit_n,
            "detected_structure_component_count": 0,
            "inferred_row_count": 0,
            "sparse_excel_risk": assess_excel_sparse_risk(
                structure_text=inference_blob,
                items=working,
                detected_component_count=0,
                image_present=image_present,
            ),
            "image_present": bool(image_present),
            "demand_template_suppressed": bool(demand_template),
        }

    for comp in _all_detected_components(inference_blob):
        if not comp.get("affects_cost"):
            continue
        name = str(comp.get("name") or "").strip()
        synonyms = tuple(comp.get("synonyms") or (name,))
        if _items_cover_component(working + new_rows, synonyms):
            continue
        key = _dedupe_key(name)
        if key in existing_keys:
            continue
        snippet = _snippet_for_inference(name, comp, inference_blob)
        confidence = float(comp.get("extracted_confidence") or 0.0)
        if not should_add_guarded_structure_component(
            name,
            confidence=confidence,
            source_snippet=snippet,
            demand_template=demand_template,
        ):
            skipped_meta.append({"name": name, "reason": "guarded_structure_low_evidence"})
            continue
        source_type = SOURCE_STRUCTURE
        if image_present and name in _vision_suggests_extra_components(vision_text):
            source_type = SOURCE_IMAGE
        row = build_inferred_candidate_row(
            component_name=name,
            source_type=source_type,
            source_snippet=snippet,
            structure_id=str(comp.get("structure_id") or ""),
            category_label=str(comp.get("category_label") or ""),
        )
        new_rows.append(row)
        existing_keys.add(key)
        added_meta.append({"name": name, "source_type": source_type})

    if image_present and not demand_template:
        for hint in _vision_suggests_extra_components(vision_text):
            key = _dedupe_key(hint)
            if key in existing_keys:
                continue
            synonyms = (hint,)
            if _items_cover_component(working + new_rows, synonyms):
                continue
            if _structure_mentions_keyword_safe(inference_blob, synonyms):
                continue
            vis_snippet = str(vision_text or "")[:120] or "产品附图/结构图"
            if not should_add_guarded_structure_component(
                hint,
                confidence=0.9,
                source_snippet=vis_snippet,
                demand_template=demand_template,
            ):
                skipped_meta.append({"name": hint, "reason": "guarded_structure_low_evidence"})
                continue
            row = build_inferred_candidate_row(
                component_name=hint,
                source_type=SOURCE_IMAGE,
                source_snippet=vis_snippet,
            )
            new_rows.append(row)
            existing_keys.add(key)
            added_meta.append({"name": hint, "source_type": SOURCE_IMAGE})

    explicit_n = count_excel_explicit_rows(working)
    detected_n = len(_all_detected_components(inference_blob))
    sparse_risk = assess_excel_sparse_risk(
        structure_text=inference_blob,
        items=working,
        detected_component_count=detected_n,
        image_present=image_present,
    )
    report = {
        "candidates_added": len(new_rows),
        "added": added_meta,
        "skipped_guarded": skipped_meta,
        "excel_explicit_row_count": explicit_n,
        "detected_structure_component_count": detected_n,
        "inferred_row_count": len(new_rows),
        "sparse_excel_risk": sparse_risk,
        "image_present": bool(image_present),
        "demand_template_suppressed": bool(demand_template),
    }
    return new_rows, report


def _structure_mentions_keyword_safe(struct: str, synonyms: tuple[str, ...]) -> bool:
    return _structure_mentions_keyword(str(struct or ""), synonyms)


def assess_excel_sparse_risk(
    *,
    structure_text: str,
    items: list[dict[str, Any]],
    detected_component_count: int,
    image_present: bool = False,
) -> dict[str, Any]:
    """结构/图片明显复杂但 Excel 材料行过少 → 风险提示。"""
    explicit_n = count_excel_explicit_rows(items)
    struct_len = len(str(structure_text or "").strip())
    complex_structure = detected_component_count >= 4 or struct_len >= 80
    has_images = bool(image_present)
    triggered = complex_structure and explicit_n <= max(2, detected_component_count // 3)
    if has_images and explicit_n <= 3 and detected_component_count >= 2:
        triggered = True
    return {
        "triggered": bool(triggered),
        "code": "excel_sparse_vs_structure_complex",
        "reason": (
            f"结构/图片提示约 {detected_component_count} 类部件，但 Excel 仅 {explicit_n} 行明确材料，"
            "存在漏计成本风险"
        ),
        "excel_explicit_rows": explicit_n,
        "detected_components": detected_component_count,
    }


def merge_material_inference_candidates(
    payload: dict[str, Any],
    *,
    structure_text: str,
    vision_text: str = "",
    image_present: bool = False,
    demand_template: bool = False,
) -> dict[str, Any]:
    """将推理候选项并入 payload.items（不覆盖已有 Excel 行）。"""
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    candidates, report = infer_missing_cost_candidates(
        structure_text,
        items,
        vision_text=vision_text,
        image_present=image_present,
        demand_template=demand_template,
    )
    if candidates and not payload.get("material_inference_merged"):
        payload["items"] = list(items) + candidates
        payload["material_inference_merged"] = True
    elif payload.get("material_inference_merged"):
        report["candidates_added"] = 0

    existing_report = payload.get("material_inference_report")
    if isinstance(existing_report, dict):
        report = {**existing_report, **report}
    payload["material_inference_report"] = report
    return report


def inference_high_risk_codes(report: dict[str, Any] | None, items: list[dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    if not isinstance(report, dict):
        report = {}
    sparse = report.get("sparse_excel_risk")
    if isinstance(sparse, dict) and sparse.get("triggered"):
        codes.append(str(sparse.get("code") or "excel_sparse_vs_structure_complex"))
    inferred_n = sum(1 for r in items if isinstance(r, dict) and is_inferred_cost_row(r))
    if inferred_n:
        codes.append("inferred_cost_candidates_pending")
    return sorted(set(codes))


def append_inferred_data_notice(base: str, items: list[dict[str, Any]]) -> str:
    inferred = [r for r in items if isinstance(r, dict) and is_inferred_cost_row(r)]
    if not inferred:
        return base
    tail = f"存在 {len(inferred)} 项结构/图片推理成本候选项，需人工复核后再对外报价。"
    base = str(base or "").strip()
    if tail in base:
        return base
    return f"{base} {tail}".strip() if base else tail
