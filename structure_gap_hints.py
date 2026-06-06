"""结构缺项识别与歧义物料归类：说明性字段只提示、不自动进正式 BOM。"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any

from demand_field_sources import STRUCTURE_NOTE_FIELD, split_structure_context_text

_CATEGORY_UNCERTAIN_FALLBACK = "未确定，请选择主料/里料/辅料/织带/五金/工艺"

_CATEGORY_TO_ROLE: dict[str, str] = {
    "主料": "外料",
    "里料": "里料",
    "辅料": "辅料",
    "织带": "织带",
    "五金": "五金",
    "工艺/人工": "工艺费",
    "海绵": "辅料",
    "网布": "辅料",
    "PE板": "辅料",
    "皮革": "辅料",
    "加固片": "辅料",
    "包边带": "织带",
    "车缝工艺": "工艺费",
    "贴合或车缝工艺": "工艺费",
}

_PROCESS_CATEGORY_LABELS = frozenset(
    {
        "工艺/人工",
        "车缝工艺",
        "贴合或车缝工艺",
        "贴合/车缝工艺",
    },
)

_ABSTRACT_CATEGORY_LABELS = frozenset({"主料", "辅料", "五金", "工艺/人工"})

# --- 结构说明关键词 → 缺项规则（不直接生成 BOM）---
_STRUCTURE_GAP_RULES: tuple[dict[str, Any], ...] = (
    {
        "id": "gap_mesh_pocket",
        "label": "网袋/侧袋",
        "keywords": ("网袋", "网兜", "侧袋", "外袋", "mesh", "侧网袋"),
        "cost_impact": "可能涉及网布、包边带、车缝工艺等额外用料与加工费",
        "bom_coverage_keywords": ("网袋", "网布", "mesh", "侧袋", "外袋", "网兜", "包边", "车缝", "侧网"),
        "suggested_direction": "网布、包边带、车缝工艺",
        "category_candidates": ("辅料", "网布", "包边带", "车缝工艺"),
        "suggested_category": "辅料",
        "category_confidence": 0.78,
    },
    {
        "id": "gap_partition",
        "label": "隔层",
        "keywords": ("隔层", "夹层", "分隔", "电脑隔层", "内隔"),
        "cost_impact": "可能增加隔层面料、海绵/PE板、车缝与裁片工时",
        "bom_coverage_keywords": ("隔层", "夹层", "分隔", "海绵", "pe板", "电脑仓", "内袋"),
        "suggested_direction": "隔层面料、海绵/PE板、车缝工艺",
        "category_candidates": ("里料", "海绵", "PE板", "车缝工艺"),
        "suggested_category": "里料",
        "category_confidence": 0.8,
    },
    {
        "id": "gap_back_pad",
        "label": "背垫",
        "keywords": ("背垫", "背板", "三明治网布", "背负垫"),
        "cost_impact": "可能涉及海绵、网布、背板材料及贴合/车缝工艺",
        "bom_coverage_keywords": ("背垫", "背板", "海绵", "网布", "背负", "三明治"),
        "suggested_direction": "海绵、网布背垫、贴合/车缝工艺",
        "category_candidates": ("海绵", "网布", "里料", "贴合或车缝工艺"),
        "suggested_category": "辅料",
        "category_confidence": 0.68,
    },
    {
        "id": "gap_handle",
        "label": "提手",
        "keywords": ("提手", "手提", "手挽"),
        "cost_impact": "可能涉及织带/皮革提手、加固片、车缝或五金",
        "bom_coverage_keywords": ("提手", "手提", "手挽", "织带", "加固"),
        "suggested_direction": "提手织带/皮革、加固片、车缝工艺",
        "category_candidates": ("织带", "皮革", "五金", "加固片", "车缝工艺"),
        "suggested_category": "织带",
        "category_confidence": 0.76,
    },
    {
        "id": "gap_shoulder_strap",
        "label": "肩带/背带",
        "keywords": ("肩带", "背带", "背负带", "可调节肩带"),
        "cost_impact": "肩带织带、扣具、垫肩及车缝工时可能单独计价",
        "bom_coverage_keywords": ("肩带", "背带", "织带", "扣具", "插扣", "垫肩"),
        "suggested_direction": "肩带织带、扣具、垫肩、车缝工艺",
        "category_candidates": ("织带", "五金", "辅料", "车缝工艺"),
        "suggested_category": "织带",
        "category_confidence": 0.72,
    },
    {
        "id": "gap_webbing",
        "label": "织带",
        "keywords": ("织带", "尼龙带", "包边带", "绳带"),
        "cost_impact": "织带通常按长度或件数计价，与主面料面积口径不同",
        "bom_coverage_keywords": ("织带", "尼龙带", "包边", "绳带", "肩带"),
        "suggested_direction": "织带/包边带（按长度或件数）",
        "category_candidates": ("织带", "包边带"),
        "suggested_category": "织带",
        "category_confidence": 0.85,
    },
    {
        "id": "gap_buckle",
        "label": "扣具",
        "keywords": ("扣具", "插扣", "日字扣", "梯扣", "d环"),
        "cost_impact": "扣具通常按件数计价，需确认规格与数量",
        "bom_coverage_keywords": ("扣具", "插扣", "日字", "梯扣", "d环", "拉头"),
        "suggested_direction": "扣具（按件数）",
        "category_candidates": ("五金",),
        "suggested_category": "五金",
        "category_confidence": 0.88,
    },
    {
        "id": "gap_binding",
        "label": "包边/加固",
        "keywords": ("包边", "加固", "补强", "耐磨片"),
        "cost_impact": "包边带、补强片及额外车缝可能增加辅料与工艺费",
        "bom_coverage_keywords": ("包边", "加固", "补强", "耐磨", "车缝"),
        "suggested_direction": "包边带、补强辅料、车缝工艺",
        "category_candidates": ("辅料", "织带", "工艺/人工"),
        "suggested_category": "辅料",
        "category_confidence": 0.7,
    },
    {
        "id": "gap_sewing",
        "label": "车缝/多层结构",
        "keywords": ("车缝", "多层结构", "可拆卸", "可调节", "两个包可扣在一起", "可扣在一起"),
        "cost_impact": "复杂车缝、多层结构或可调节机构可能提高加工费",
        "bom_coverage_keywords": ("车缝", "工艺", "加工", "多层", "可拆卸", "可调节", "扣在一起"),
        "suggested_direction": "车缝/特殊工艺费、相关辅料",
        "category_candidates": ("工艺/人工", "辅料"),
        "suggested_category": "工艺/人工",
        "category_confidence": 0.62,
    },
    {
        "id": "gap_print_heat",
        "label": "印刷/热压",
        "keywords": ("印刷", "热压", "丝印", "烫印", "热转印"),
        "cost_impact": "印刷/热压通常按工艺费或面积计价，与主料口径不同",
        "bom_coverage_keywords": ("印刷", "热压", "丝印", "烫印", "热转", "logo", "工艺"),
        "suggested_direction": "印刷/热压工艺费",
        "category_candidates": ("工艺/人工",),
        "suggested_category": "工艺/人工",
        "category_confidence": 0.82,
    },
)

# --- 歧义物料归类 ---
_AMBIGUOUS_CLASSIFIERS: tuple[dict[str, Any], ...] = (
    {
        "patterns": (r"外带反射", r"反光织带", r"织带反光"),
        "resolved_category": "辅料/织带",
        "calculation_basis": "按长度或件数",
        "confidence": 0.72,
        "needs_confirmation": True,
        "user_notice": (
            "系统识别为反光织带/辅料，按长度或件数计算，未按主面料面积计算。"
            "如实际是反光面料拼片或反光印刷，请人工调整。"
        ),
    },
    {
        "patterns": (r"反光条", r"反光贴", r"反光带"),
        "resolved_category": "反光材料",
        "calculation_basis": "按长度或件数",
        "confidence": 0.78,
        "needs_confirmation": True,
        "user_notice": (
            "系统识别为反光条/辅料，按长度或件数计算。"
            "如为面料拼片或印刷工艺，请人工调整。"
        ),
    },
    {
        "patterns": (r"反光面料", r"反光布", r"反光拼片", r"反光主料"),
        "resolved_category": "反光面料/主料",
        "calculation_basis": "按面积或用料",
        "confidence": 0.8,
        "needs_confirmation": False,
        "user_notice": "系统识别为反光面料/拼片，按面积或用料计算。",
    },
    {
        "patterns": (r"反光印刷", r"反光丝印", r"反光logo"),
        "resolved_category": "工艺费",
        "calculation_basis": "按工艺费",
        "confidence": 0.76,
        "needs_confirmation": True,
        "user_notice": "系统识别为反光工艺，按工艺费计算。",
    },
    {
        "patterns": (r"侧袋", r"外袋", r"网袋", r"网兜"),
        "resolved_category": "外部结构/辅料",
        "calculation_basis": "按件数或用料",
        "confidence": 0.65,
        "needs_confirmation": True,
        "user_notice": (
            "系统识别为侧袋/网袋类结构，可能涉及网布、包边或车缝。"
            "请确认是否已单独计入物料或工艺。"
        ),
    },
    {
        "patterns": (r"肩带", r"提手", r"背带"),
        "resolved_category": "辅料/织带",
        "calculation_basis": "按长度或件数",
        "confidence": 0.7,
        "needs_confirmation": True,
        "user_notice": (
            "系统识别为肩带/提手/背带类，按织带长度或件数计算。"
            "如已含在主面料裁片内，请人工核对。"
        ),
    },
    {
        "patterns": (r"包边", r"加固", r"车缝"),
        "resolved_category": "工艺费/辅料",
        "calculation_basis": "按工艺费或长度",
        "confidence": 0.68,
        "needs_confirmation": True,
        "user_notice": (
            "系统识别为包边/加固/车缝相关，可能按工艺费或辅料长度计价。"
            "请确认是否已单独列项。"
        ),
    },
)

_UNCERTAIN_REFLECTIVE = re.compile(r"外带反射|反光", re.I)


def _norm_blob(text: str) -> str:
    return str(text or "").strip()


def _bom_text_blob(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        if row.get("exclude_from_cost") or row.get("_structure_deleted"):
            continue
        for k in ("name", "spec", "role", "calc_note", "calc_method"):
            v = str(row.get(k) or "").strip()
            if v and v not in {"-", "—"}:
                parts.append(v)
    return " ".join(parts).lower()


def _find_keyword_in_blob(blob: str, keywords: tuple[str, ...]) -> str | None:
    low = blob.lower()
    for kw in keywords:
        if kw.lower() in low:
            if f"无{kw}" in blob or f"不含{kw}" in blob or f"没有{kw}" in blob:
                continue
            return kw
    return None


def _bom_covers_keywords(items: list[dict[str, Any]], coverage_keywords: tuple[str, ...]) -> tuple[bool, str]:
    blob = _bom_text_blob(items)
    if not blob:
        return False, "当前 BOM 为空或未解析到对应物料/工艺"
    hits = [kw for kw in coverage_keywords if kw.lower() in blob]
    if hits:
        return True, f"当前 BOM 已发现：{'、'.join(hits[:4])}"
    return False, f"当前 BOM 未发现：{'、'.join(coverage_keywords[:5])} 等"


def format_gap_category_hint_display(
    category_candidates: Sequence[str] | tuple[str, ...] | list[str],
    *,
    category_confidence: float = 0.0,
) -> str:
    """生成前端可直接展示的「建议归类」文案。"""
    candidates = [str(c).strip() for c in category_candidates if str(c).strip()]
    if not candidates:
        return f"建议归类：{_CATEGORY_UNCERTAIN_FALLBACK}"
    joined = " / ".join(candidates)
    conf = float(category_confidence or 0.0)
    if conf >= 0.75:
        return f"建议归类：{joined}"
    if conf >= 0.5:
        return f"建议归类：可能是 {joined}，请人工确认"
    return f"建议归类：{_CATEGORY_UNCERTAIN_FALLBACK}"


def build_gap_category_fields(rule: dict[str, Any]) -> dict[str, Any]:
    """从缺项规则提取建议归类字段。"""
    candidates = tuple(str(c).strip() for c in (rule.get("category_candidates") or ()) if str(c).strip())
    suggested = str(rule.get("suggested_category") or (candidates[0] if candidates else "")).strip()
    confidence = float(rule.get("category_confidence") or 0.0)
    material_hint = " / ".join(candidates) if candidates else ""
    return {
        "suggested_category": suggested,
        "category_candidates": list(candidates),
        "material_category_hint": material_hint,
        "category_confidence": round(confidence, 2),
        "category_needs_confirmation": confidence < 0.75,
        "category_hint_display": format_gap_category_hint_display(
            candidates,
            category_confidence=confidence,
        ),
    }


def category_label_to_role(category: str) -> str:
    """建议归类 → BOM role（用户可在表格中继续修改）。"""
    text = str(category or "").strip()
    return _CATEGORY_TO_ROLE.get(text, "辅料")


def build_gap_bom_name(hint: dict[str, Any]) -> str:
    """结构缺项行名称：有把握时附带材料类别提示。"""
    label = str(hint.get("detected_text") or hint.get("name") or "结构缺项").strip()
    candidates = [str(c).strip() for c in (hint.get("category_candidates") or []) if str(c).strip()]
    confidence = float(hint.get("category_confidence") or 0.0)
    if confidence < 0.75 or not candidates:
        return label
    material_hints = [
        c
        for c in candidates
        if c not in _PROCESS_CATEGORY_LABELS and c not in _ABSTRACT_CATEGORY_LABELS
    ]
    if not material_hints:
        material_hints = [c for c in candidates if c not in _PROCESS_CATEGORY_LABELS]
    if len(material_hints) >= 2:
        return f"{label}-{material_hints[0]}/{material_hints[1]}"
    if material_hints:
        return f"{label}-{material_hints[0]}"
    return label


def build_gap_bom_calc_note(hint: dict[str, Any]) -> str:
    """结构缺项行备注：保留建议归类，供用户核对与修改。"""
    direction = str(hint.get("suggested_direction") or "").strip()
    category_display = str(hint.get("category_hint_display") or "").strip()
    parts: list[str] = ["结构确认缺项"]
    if category_display:
        parts.append(category_display)
    if direction:
        parts.append(f"确认方向：{direction}")
    return "；".join(parts)


def build_structure_gap_hints(
    structure_text: str,
    items: list[dict[str, Any]] | None = None,
    *,
    demand_template: bool = False,
) -> list[dict[str, Any]]:
    """从结构说明/备注识别可能缺项，默认只提示、不参与金额。"""
    if not demand_template:
        return []
    main, appendix = split_structure_context_text(structure_text)
    blob = "\n".join(p for p in (main, appendix) if p).strip()
    if not blob:
        return []
    bom_items = [r for r in (items or []) if isinstance(r, dict)]
    hints: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for rule in _STRUCTURE_GAP_RULES:
        detected = _find_keyword_in_blob(blob, tuple(rule["keywords"]))
        if not detected:
            continue
        rid = str(rule["id"])
        if rid in seen_ids:
            continue
        seen_ids.add(rid)
        covered, coverage_detail = _bom_covers_keywords(bom_items, tuple(rule["bom_coverage_keywords"]))
        confirm_prompt = (
            f"请确认是否需要加入{rule['label']}相关物料或工艺"
            if not covered
            else f"结构说明提及{rule['label']}，请核对 BOM 是否已完整覆盖"
        )
        user_notice = (
            f"结构说明提到{detected}（{rule['label']}），{coverage_detail}。"
            f"{confirm_prompt}。"
        )
        if not covered:
            user_notice = (
                f"结构说明提到{detected}，但{coverage_detail}。"
                f"{confirm_prompt}；确认后可按「{rule['suggested_direction']}」方向加入。"
            )
        category_fields = build_gap_category_fields(rule)
        hints.append(
            {
                "id": rid,
                "detected_text": detected,
                "name": rule["label"],
                "snippet": blob[:160],
                "cost_impact_reason": str(rule["cost_impact"]),
                "bom_covered": covered,
                "bom_coverage_detail": coverage_detail,
                "user_confirm_prompt": confirm_prompt,
                "suggested_direction": str(rule["suggested_direction"]),
                "user_notice": user_notice,
                "participates_in_cost": False,
                "source": STRUCTURE_NOTE_FIELD,
                "needs_confirmation": not covered,
                "reason": user_notice,
                **category_fields,
            },
        )
    return hints


def collect_structure_note_hints(
    structure_text: str,
    *,
    demand_template: bool = False,
    items: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """兼容旧接口：返回简版 hints；完整 schema 见 build_structure_gap_hints。"""
    full = build_structure_gap_hints(structure_text, items, demand_template=demand_template)
    out: list[dict[str, str]] = []
    for h in full:
        out.append(
            {
                "name": str(h.get("name") or h.get("detected_text") or ""),
                "snippet": str(h.get("snippet") or "")[:120],
                "reason": str(h.get("user_notice") or h.get("reason") or ""),
                "source": str(h.get("source") or STRUCTURE_NOTE_FIELD),
            },
        )
    return out


def classify_ambiguous_material(
    name: str,
    *,
    spec: str = "",
    role: str = "",
    context: str = "",
) -> dict[str, Any] | None:
    """歧义物料归类说明；无法确定类别时返回低置信度需确认项。"""
    blob = " ".join(p for p in (name, spec, role, context) if str(p).strip()).strip()
    if not blob:
        return None
    low = blob.lower()
    best: dict[str, Any] | None = None
    best_conf = -1.0
    for rule in _AMBIGUOUS_CLASSIFIERS:
        for pat in rule["patterns"]:
            if re.search(pat, blob, re.I):
                conf = float(rule.get("confidence") or 0.5)
                if conf > best_conf:
                    best_conf = conf
                    best = {
                        "detected_text": blob[:120],
                        "resolved_category": str(rule["resolved_category"]),
                        "calculation_basis": str(rule["calculation_basis"]),
                        "user_notice": str(rule["user_notice"]),
                        "confidence": round(conf, 2),
                        "needs_confirmation": bool(rule.get("needs_confirmation")),
                        "participates_in_cost": True,
                    }
                break
    if best:
        return best
    if _UNCERTAIN_REFLECTIVE.search(blob):
        return {
            "detected_text": blob[:120],
            "resolved_category": "未确定",
            "calculation_basis": "待确认",
            "user_notice": "该项可能是面料、织带或反光工艺，请确认实际计价方式。",
            "confidence": 0.35,
            "needs_confirmation": True,
            "participates_in_cost": False,
        }
    return None


def enrich_row_ambiguous_classification(row: dict[str, Any], *, context: str = "") -> dict[str, Any]:
    """为物料行附加歧义归类说明（不改变计价）。"""
    if not isinstance(row, dict):
        return row
    name = str(row.get("name") or "").strip()
    if not name:
        return row
    cls = classify_ambiguous_material(
        name,
        spec=str(row.get("spec") or ""),
        role=str(row.get("role") or ""),
        context=context,
    )
    if not cls:
        return row
    out = dict(row)
    out["ambiguous_material_classification"] = cls
    if cls.get("needs_confirmation"):
        out["needs_manual_confirm"] = True
        hints = list(out.get("accuracy_hints") or [])
        notice = str(cls.get("user_notice") or "").strip()
        if notice and notice not in hints:
            hints.append(notice)
        out["accuracy_hints"] = hints
    return out


def enrich_items_ambiguous_classification(
    items: list[dict[str, Any]],
    *,
    context: str = "",
) -> list[dict[str, Any]]:
    return [enrich_row_ambiguous_classification(r, context=context) if isinstance(r, dict) else r for r in items]


def gap_hint_to_bom_row(hint: dict[str, Any]) -> dict[str, Any]:
    """用户确认缺项后生成正式 BOM 行（需补全用量/单价）。"""
    suggested_category = str(hint.get("suggested_category") or "").strip()
    role = category_label_to_role(suggested_category)
    calc_note = build_gap_bom_calc_note(hint)
    return {
        "name": build_gap_bom_name(hint),
        "role": role,
        "spec": "-",
        "usage": "-",
        "unit_price": "-",
        "amount": 0.0,
        "calc_note": calc_note,
        "suggested_category": suggested_category,
        "category_candidates": list(hint.get("category_candidates") or []),
        "material_category_hint": str(hint.get("material_category_hint") or ""),
        "category_hint_display": str(hint.get("category_hint_display") or ""),
        "category_needs_confirmation": bool(hint.get("category_needs_confirmation")),
        "confirmation_source": "structure_confirmed",
        "from_structure_gap_hint": True,
        "structure_gap_hint_id": str(hint.get("id") or ""),
        "exclude_from_cost": True,
        "amount_in_cost": False,
        "needs_manual_confirm": True,
        "recognition_status": "candidate_review",
        "recognition_reason": "结构缺项，待补用量/单价，暂不参与金额",
        "source": "structure_confirmed",
    }


def apply_confirmed_structure_gaps(
    items: list[dict[str, Any]],
    gap_hints: list[dict[str, Any]],
    confirmed_ids: list[str] | None,
) -> list[dict[str, Any]]:
    """将用户确认的缺项 ID 转为正式 BOM 行。"""
    if not confirmed_ids:
        return items
    id_set = {str(x).strip() for x in confirmed_ids if str(x).strip()}
    if not id_set:
        return items
    out = list(items)
    existing_ids = {
        str(r.get("structure_gap_hint_id") or "")
        for r in out
        if isinstance(r, dict) and r.get("from_structure_gap_hint")
    }
    for hint in gap_hints or []:
        if not isinstance(hint, dict):
            continue
        hid = str(hint.get("id") or "").strip()
        if hid not in id_set or hid in existing_ids:
            continue
        out.append(gap_hint_to_bom_row(hint))
    return out


def build_anomaly_review_hints(
    *,
    items: list[dict[str, Any]] | None = None,
    structure_text: str = "",
    gap_hints: list[dict[str, Any]] | None = None,
    processing_fee: float | None = None,
    material_total: float | None = None,
) -> list[dict[str, str]]:
    """价格偏低、BOM 过少、加工费偏高等人工复核提示。"""
    hints: list[dict[str, str]] = []
    bom_items = [r for r in (items or []) if isinstance(r, dict) and not r.get("exclude_from_cost")]
    costed = [r for r in bom_items if float(r.get("amount") or 0) > 0]
    if len(bom_items) <= 3 and structure_text.strip():
        hints.append(
            {
                "code": "bom_row_count_low",
                "user_notice": f"物料行仅 {len(bom_items)} 行，相对结构说明可能偏少，建议人工复核是否漏项。",
            },
        )
    uncovered = [h for h in (gap_hints or []) if isinstance(h, dict) and not h.get("bom_covered")]
    if uncovered:
        names = "、".join(str(h.get("detected_text") or h.get("name") or "") for h in uncovered[:4])
        hints.append(
            {
                "code": "structure_gap_uncovered",
                "user_notice": f"结构说明提及 {names}，但 BOM 可能未覆盖，请核对缺项提示。",
            },
        )
    try:
        pf = float(processing_fee) if processing_fee is not None else None
        mt = float(material_total) if material_total is not None else None
        if pf is not None and mt is not None and mt > 0 and pf > mt * 1.5:
            hints.append(
                {
                    "code": "processing_fee_high_vs_material",
                    "user_notice": "加工费明显高于物料费，请核对工艺项与结构复杂度是否匹配。",
                },
            )
    except (TypeError, ValueError):
        pass
    if costed and material_total is not None:
        try:
            mt_val = float(material_total)
            if mt_val > 0 and mt_val < 3.0 and len(bom_items) >= 2:
                hints.append(
                    {
                        "code": "material_total_suspicious_low",
                        "user_notice": "物料合计偏低，请核对用量、单价与是否漏算结构件。",
                    },
                )
        except (TypeError, ValueError):
            pass
    return hints


def merge_gap_hints_into_data_notice(base: str, gap_hints: list[dict[str, Any]] | None) -> str:
    """将未覆盖缺项摘要写入 data_notice。"""
    uncovered = [h for h in (gap_hints or []) if isinstance(h, dict) and not h.get("bom_covered")]
    if not uncovered:
        return base
    parts = [str(h.get("user_notice") or "")[:100] for h in uncovered[:3] if h.get("user_notice")]
    if not parts:
        return base
    extra = "结构缺项提示：" + "；".join(parts)
    return f"{base} {extra}".strip() if base else extra
