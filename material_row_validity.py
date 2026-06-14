"""物料候选有效性校验：拆分组合配件、过滤说明句、标记识别状态。"""

from __future__ import annotations

import re
from typing import Any

from sheet_parser import (
    MATERIAL_QTY_PHRASE_PATTERN,
    contains_any,
    looks_like_material_description_sentence,
    looks_like_valid_unit_price_text,
    normalize_text,
    parse_piece_count_from_usage,
    quantity_phrase_count,
    should_drop_upload_name,
    split_concatenated_material_name,
    split_quantity_from_material_name,
)

RECOGNITION_MATCHED = "matched"
RECOGNITION_CANDIDATE = "candidate_review"
RECOGNITION_IGNORED = "ignored"
RECOGNITION_SPLIT = "split"

MATERIAL_DESC_FORBIDDEN_PREFIXES = (
    "外侧使用",
    "内侧为",
    "内侧使用",
    "加宽肩带",
    "大容量单主仓",
    "用于",
    "说明",
    "结构",
)
MATERIAL_DESC_WEAK_KEYWORDS = (
    "使用",
    "外侧",
    "内侧",
    "主面料",
    "结构",
    "加宽",
    "固定",
    "调节",
    "下方",
    "上有",
    "口袋",
    "容量",
)
PART_ROLE_PREFIXES = ("肩带", "织带", "背板", "里布", "外料", "里料", "袋口", "主仓", "胸带")
STRONG_MATERIAL_HINTS = (
    "插扣",
    "拉链",
    "拉头",
    "织带",
    "网布",
    "尼龙",
    "涤纶",
    "d扣",
    "梯扣",
    "猪鼻扣",
    "扣具",
    "牛津",
    "帆布",
    "dcf",
    "tpu",
    "pvc",
    "ripstop",
    "面料",
    "外料",
    "里料",
)

_PAREN_CLUE_RE = re.compile(r"[（(]([^）)]+)")


def _starts_with_forbidden_prefix(text: str) -> bool:
    normalized = normalize_text(text)
    for prefix in MATERIAL_DESC_FORBIDDEN_PREFIXES:
        if text.startswith(prefix) or normalized.startswith(normalize_text(prefix)):
            return True
    return False


def extract_material_clue_from_parenthetical(text: str) -> str:
    match = _PAREN_CLUE_RE.search(str(text or ""))
    if not match:
        return ""
    clue = str(match.group(1) or "").strip(" ，,")
    if not clue or len(clue) < 2:
        return ""
    if contains_any(normalize_text(clue), STRONG_MATERIAL_HINTS + ("网布", "织带", "面料", "尼龙")):
        return clue
    return ""


def _is_inferred_or_structure_pending_row(row: dict[str, Any], name: str) -> bool:
    """包类结构提取/推理待核成本行，不得当作说明文字忽略。"""
    from material_inference import is_inferred_cost_row

    if is_inferred_cost_row(row):
        return True
    if bool(row.get("from_bag_structure_extraction")):
        return True
    if str(row.get("structure_id") or "").strip():
        return True
    text = str(name or "").strip()
    return "结构待核" in text


_PIECE_OR_STRUCTURE_NAMES = frozenset(
    {
        "前片",
        "后片",
        "底片",
        "侧片",
        "侧片（2片）",
        "拉链弧形盖",
        "前袋",
        "网袋",
        "隔层",
    }
)


def is_ignored_material_text(name: str) -> tuple[bool, str]:
    text = str(name or "").strip()
    if "结构待核" in text:
        return False, ""
    if text in _PIECE_OR_STRUCTURE_NAMES:
        return True, "裁片/部位名称，不作为材料计价"
    if not text or should_drop_upload_name(text):
        return True, "空行或表头噪声"
    if _starts_with_forbidden_prefix(text):
        return True, "疑似结构/部位说明，不作为物料计价"
    if looks_like_material_description_sentence(text):
        return True, "疑似结构/工艺说明，不作为物料计价"
    normalized = normalize_text(text)
    if (text.endswith(")") or text.endswith("）")) and contains_any(normalized, MATERIAL_DESC_WEAK_KEYWORDS):
        return True, "疑似不完整说明句，不作为物料计价"
    return False, ""


def is_part_description_candidate(name: str) -> tuple[bool, str]:
    text = str(name or "").strip()
    if not text:
        return False, ""
    if ("(" in text or "（" in text) and any(role in text for role in PART_ROLE_PREFIXES):
        clue = extract_material_clue_from_parenthetical(text)
        reason = "部件说明混合文本，需人工确认"
        if clue:
            reason = f"{reason}（材质线索：{clue}）"
        return True, reason
    if any(text.startswith(role) for role in PART_ROLE_PREFIXES) and contains_any(
        normalize_text(text),
        MATERIAL_DESC_WEAK_KEYWORDS,
    ):
        return True, "部件说明混合文本，需人工确认"
    return False, ""


def _looks_like_valid_material_candidate(name: str) -> bool:
    normalized = normalize_text(name)
    if contains_any(normalized, STRONG_MATERIAL_HINTS):
        return True
    if quantity_phrase_count(name) >= 1:
        return True
    return len(normalized) <= 12 and any(ch in name for ch in ("扣", "链", "带", "布", "料", "标"))


def classify_material_row(
    name: str,
    *,
    kb_hit: bool = False,
    unit_price: str = "-",
) -> tuple[str, str]:
    if kb_hit:
        if looks_like_valid_unit_price_text(unit_price):
            return RECOGNITION_MATCHED, "知识库命中"
        return RECOGNITION_CANDIDATE, "知识库已匹配名称但缺有效单价，待补价/待确认"
    is_part, part_reason = is_part_description_candidate(name)
    if is_part:
        return RECOGNITION_CANDIDATE, part_reason
    ignored, reason = is_ignored_material_text(name)
    if ignored:
        return RECOGNITION_IGNORED, reason
    if _looks_like_valid_material_candidate(name):
        return RECOGNITION_CANDIDATE, "未命中知识库，疑似有效材料/配件，待人工确认"
    if len(normalize_text(name)) >= 8 and contains_any(normalize_text(name), MATERIAL_DESC_WEAK_KEYWORDS):
        return RECOGNITION_IGNORED, "疑似说明文字，不作为物料计价"
    return RECOGNITION_CANDIDATE, "未命中知识库，待人工确认"


def _usage_from_qty_name(name: str) -> str:
    _, usage, _ = split_quantity_from_material_name(name)
    if usage:
        return usage
    match = MATERIAL_QTY_PHRASE_PATTERN.search(str(name or ""))
    if match:
        return match.group(0).strip()
    return "-"


def apply_embedded_quantity_to_row(row: dict[str, Any]) -> dict[str, Any]:
    """材料名内嵌数量拆到 usage；名称数量优先于错误的 1 个/占位用量。"""
    if not isinstance(row, dict):
        return row
    name = str(row.get("name") or "").strip()
    if not name:
        return row
    clean, qty, src = split_quantity_from_material_name(name)
    if not src or not clean:
        return row

    nr = dict(row)
    nr["name"] = clean
    nr["_original_name_with_qty"] = name
    if qty:
        existing = str(nr.get("usage") or "-").strip()
        name_count = parse_piece_count_from_usage(qty)
        exist_count = parse_piece_count_from_usage(existing)
        should_apply = existing in {"", "-", "—", "个"} or exist_count is None
        if name_count is not None and exist_count is not None and exist_count != name_count:
            should_apply = True
            nr["quantity_corrected_from_name"] = True
        if should_apply:
            nr["usage"] = qty
            nr["quantity_source"] = src
            nr["usage_ai"] = False
            nr.pop("amount", None)
            nr.pop("amount_ai", None)
    return nr


def _apply_cost_flags(row: dict[str, Any], status: str) -> None:
    if status == RECOGNITION_IGNORED:
        row["exclude_from_cost"] = True
        row["amount_in_cost"] = False
    elif status in {RECOGNITION_CANDIDATE, RECOGNITION_SPLIT}:
        if row_is_quotable_for_cost(row):
            row["exclude_from_cost"] = False
            row["amount_in_cost"] = True
        else:
            row["exclude_from_cost"] = True
            row["amount_in_cost"] = False
            row["kb_auto_learned"] = False
    else:
        row.setdefault("exclude_from_cost", False)
        row.setdefault("amount_in_cost", True)


def apply_material_validity_layer(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """展开组合配件、过滤垃圾说明句，并写入 recognition_status / recognition_reason。"""
    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        row = apply_embedded_quantity_to_row(row)
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        kb_hit = bool(row.get("kb_hit"))
        if _is_inferred_or_structure_pending_row(row, name):
            nr = dict(row)
            nr.setdefault("from_bag_structure_extraction", True)
            nr.setdefault("recognition_status", RECOGNITION_CANDIDATE)
            nr.setdefault(
                "recognition_reason",
                "包类结构清单提取的待补成本项，需由模型或人工补齐单价后参与报价",
            )
            _apply_cost_flags(nr, str(nr.get("recognition_status") or RECOGNITION_CANDIDATE))
            out.append(nr)
            continue
        split_names = split_concatenated_material_name(name)
        if len(split_names) >= 2:
            for idx, split_name in enumerate(split_names):
                nr = dict(row)
                nr["name"] = split_name
                nr["recognition_status"] = RECOGNITION_SPLIT
                nr["recognition_reason"] = "由组合配件文本拆分"
                nr["_source_combined_name"] = name
                if idx > 0:
                    nr["unit_price"] = "-"
                    nr["amount"] = 0.0
                    nr["kb_hit"] = False
                    nr["kb_score"] = 0.0
                    nr.pop("kb_matched_name", None)
                    nr.pop("kb_matched_spec", None)
                qty_usage = _usage_from_qty_name(split_name)
                if qty_usage != "-" and str(nr.get("usage") or "-").strip() in {"", "-", "—"}:
                    nr["usage"] = qty_usage
                split_kb_hit = kb_hit and idx == 0
                split_unit_price = str(nr.get("unit_price") or "-").strip()
                sub_status, sub_reason = classify_material_row(
                    split_name,
                    kb_hit=split_kb_hit,
                    unit_price=split_unit_price,
                )
                if sub_status == RECOGNITION_IGNORED and (
                    _looks_like_valid_material_candidate(split_name)
                    or quantity_phrase_count(split_name) >= 1
                ):
                    nr["recognition_status"] = RECOGNITION_SPLIT
                    nr["recognition_reason"] = f"已拆分；{sub_reason}（待补价/待确认）"
                elif sub_status == RECOGNITION_IGNORED:
                    nr["recognition_status"] = RECOGNITION_IGNORED
                    nr["recognition_reason"] = sub_reason
                elif sub_status == RECOGNITION_CANDIDATE:
                    nr["recognition_status"] = RECOGNITION_SPLIT
                    nr["recognition_reason"] = f"已拆分；{sub_reason}"
                elif split_kb_hit and looks_like_valid_unit_price_text(split_unit_price):
                    nr["recognition_status"] = RECOGNITION_SPLIT
                    nr["recognition_reason"] = "由组合配件文本拆分；首项知识库命中"
                _apply_cost_flags(nr, str(nr.get("recognition_status") or ""))
                out.append(nr)
            continue

        status, reason = classify_material_row(
            name,
            kb_hit=kb_hit,
            unit_price=str(row.get("unit_price") or "-"),
        )
        nr = dict(row)
        nr["recognition_status"] = status
        nr["recognition_reason"] = reason
        clue = extract_material_clue_from_parenthetical(name)
        if clue:
            nr["material_clue"] = clue
        _apply_cost_flags(nr, status)
        out.append(nr)
    return out


def confirm_material_candidates_for_quote(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """用户确认结构后，待确认项可参与正式报价（已忽略项仍排除）。"""
    staged: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        nr = dict(row)
        status = str(nr.get("recognition_status") or "").strip()
        if status == RECOGNITION_IGNORED:
            nr["exclude_from_cost"] = True
            nr["amount_in_cost"] = False
        elif status in {RECOGNITION_CANDIDATE, RECOGNITION_SPLIT}:
            nr["recognition_confirmed"] = True
            if row_is_quotable_for_cost(nr):
                nr["exclude_from_cost"] = False
                nr["amount_in_cost"] = True
            else:
                nr["exclude_from_cost"] = True
                nr["amount_in_cost"] = False
        staged.append(nr)
    return promote_quotable_rows_for_quote(staged)


def should_skip_knowledge_learn_row(row: dict[str, Any]) -> bool:
    from material_inference import is_inferred_cost_row

    if is_inferred_cost_row(row):
        return True
    status = str(row.get("recognition_status") or "").strip()
    if status in {RECOGNITION_IGNORED, RECOGNITION_CANDIDATE, RECOGNITION_SPLIT}:
        return True
    if bool(row.get("exclude_from_cost")):
        return True
    return False


def recognition_status_label(status: str) -> str:
    mapping = {
        RECOGNITION_MATCHED: "已匹配",
        RECOGNITION_CANDIDATE: "待确认",
        RECOGNITION_IGNORED: "已忽略",
        RECOGNITION_SPLIT: "已拆分",
    }
    return mapping.get(str(status or "").strip(), "")


_MISSING_QUOTE_FIELD_TEXT = {"", "-", "—", "无", "空", "none", "null", "nan"}
_PENDING_RECOGNITION_STATUSES = frozenset({RECOGNITION_CANDIDATE, RECOGNITION_SPLIT})


def is_missing_quote_field_text(value: object) -> bool:
    text = str(value or "").strip().lower()
    return not text or text in _MISSING_QUOTE_FIELD_TEXT


def structure_gap_row_ready_for_cost(row: dict[str, Any]) -> bool:
    """结构缺项行是否已具备参与计价的用量与单价。"""
    if not bool(row.get("from_structure_gap_hint")):
        return True
    usage_ok = not is_missing_quote_field_text(row.get("usage"))
    price_ok = looks_like_valid_unit_price_text(str(row.get("unit_price") or ""))
    return usage_ok and price_ok


def _is_missing_quote_field_text(value: object) -> bool:
    return is_missing_quote_field_text(value)


def _row_active_for_formal_quote(row: dict[str, Any]) -> bool:
    if bool(row.get("deleted")):
        return False
    if bool(row.get("exclude_from_cost")):
        return False
    status = str(row.get("recognition_status") or "").strip()
    return status != RECOGNITION_IGNORED


def row_has_ai_estimate_pricing(row: dict[str, Any]) -> bool:
    """AI/规则已补全用量与单价，可继续报价但需管理员复核。"""
    if not isinstance(row, dict):
        return False
    has_ai_flag = any(bool(row.get(k)) for k in ("usage_ai", "unit_price_ai", "amount_ai"))
    if not has_ai_flag and not bool(row.get("pricing_review_required")):
        return False
    return structure_gap_row_ready_for_cost(row)


def row_has_valid_unit_price_for_quote(row: dict[str, Any]) -> bool:
    return looks_like_valid_unit_price_text(str(row.get("unit_price") or ""))


def row_has_valid_usage_for_quote(row: dict[str, Any]) -> bool:
    return not is_missing_quote_field_text(row.get("usage"))


def row_has_persisted_amount(row: dict[str, Any]) -> bool:
    try:
        val = float(row.get("amount") or 0)
    except (TypeError, ValueError):
        return False
    return val > 0.001


def usage_from_calc_note_row(row: dict[str, Any]) -> str:
    """从 calc_note / calc_method 提取可计价用量片段。"""
    from material_spec_usage_enricher import _QTY_UNIT_RE, _parse_calc_note_fields

    calc = str(row.get("calc_note") or row.get("calc_method") or "").strip()
    if not calc:
        return ""
    _, cn_usage = _parse_calc_note_fields(calc)
    if cn_usage and not is_missing_quote_field_text(cn_usage):
        return cn_usage.strip()
    hits = _QTY_UNIT_RE.findall(calc)
    if hits:
        n, u = hits[-1]
        return f"{n}{u}".strip()
    return ""


def _row_name_is_length_metadata(name: str) -> bool:
    from demand_parser import _looks_like_length_or_dimension_metadata

    return _looks_like_length_or_dimension_metadata(str(name or "").strip())


def row_usage_derivable_for_quote(row: dict[str, Any]) -> bool:
    derived = usage_from_calc_note_row(row)
    if not derived:
        return False
    from material_spec_usage_enricher import usage_is_billable_quantity

    return usage_is_billable_quantity(derived)


def row_is_quotable_for_cost(row: dict[str, Any]) -> bool:
    """具备有效单价，且有用量/小计/可解析 calc 用量 → 可参与物料合计。"""
    if not isinstance(row, dict) or bool(row.get("deleted")):
        return False
    name = str(row.get("name") or "").strip()
    if not name or _row_name_is_length_metadata(name):
        return False
    status = str(row.get("recognition_status") or "").strip()
    if status == RECOGNITION_IGNORED:
        return False
    if not row_has_valid_unit_price_for_quote(row):
        return False
    if row_has_valid_usage_for_quote(row):
        from material_spec_usage_enricher import usage_is_billable_quantity

        usage = str(row.get("usage") or "").strip()
        if usage_is_billable_quantity(usage):
            return True
    if row_has_persisted_amount(row):
        return True
    return row_usage_derivable_for_quote(row)


def row_exclusion_reasons_for_quote(row: dict[str, Any]) -> list[str]:
    """未参与物料合计的原因（用于结果页提示，不阻断待确认展示）。"""
    if not isinstance(row, dict) or bool(row.get("deleted")):
        return ["已删除"]
    name = str(row.get("name") or "").strip()
    if not name:
        return ["缺少物料名"]
    if _row_name_is_length_metadata(name):
        return ["长度/尺寸描述，非独立物料"]
    status = str(row.get("recognition_status") or "").strip()
    if status == RECOGNITION_IGNORED:
        return [str(row.get("recognition_reason") or "已忽略")]
    if row_is_quotable_for_cost(row):
        return []
    reasons: list[str] = []
    if status in _PENDING_RECOGNITION_STATUSES:
        reasons.append("待确认")
    if not row_has_valid_unit_price_for_quote(row):
        reasons.append("缺少单价")
    if not row_has_persisted_amount(row):
        if not row_has_valid_usage_for_quote(row):
            reasons.append("缺少用量")
        else:
            from material_spec_usage_enricher import usage_is_billable_quantity

            usage = str(row.get("usage") or "").strip()
            if not usage_is_billable_quantity(usage):
                reasons.append("用量不可用（如尺寸被误当数量）")
        if not row_usage_derivable_for_quote(row) and not row_has_valid_usage_for_quote(row):
            if "缺少用量" not in reasons:
                reasons.append("计算方式无法解析用量")
    if not reasons:
        reasons.append("未满足计价条件")
    return reasons


def parse_bool_local(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def promote_quotable_rows_for_quote(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """结构确认后：可计价行参与合计；待确认仅作风险提示。"""
    out: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        status = str(row.get("recognition_status") or "").strip()
        if status == RECOGNITION_IGNORED:
            row["exclude_from_cost"] = True
            row["amount_in_cost"] = False
        elif row_is_quotable_for_cost(row):
            row["exclude_from_cost"] = False
            row["amount_in_cost"] = True
            if status in _PENDING_RECOGNITION_STATUSES or status == RECOGNITION_SPLIT:
                row["recognition_confirmed"] = True
        out.append(row)
    return out


def build_quote_participation_summary(
    source_items: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """对比源 BOM 与已计价明细，列出参与/未参与及原因。"""
    included_keys: set[str] = set()
    included: list[dict[str, str]] = []
    for dr in detail_rows:
        if not isinstance(dr, dict):
            continue
        name = str(dr.get("name") or "").strip()
        if not name:
            continue
        key = normalize_text(name)
        included_keys.add(key)
        included.append({"name": name, "status": "已参与报价"})

    excluded: list[dict[str, Any]] = []
    for raw in source_items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        key = normalize_text(name)
        if key in included_keys:
            continue
        reasons = row_exclusion_reasons_for_quote(raw)
        if not reasons:
            continue
        excluded.append({"name": name, "reasons": reasons})

    return {
        "included_count": len(included),
        "excluded_count": len(excluded),
        "included": included[:80],
        "excluded": excluded[:80],
    }


def summarize_structure_quote_gaps(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """列出正式报价前仍缺字段或待确认的行（不含已删除/已忽略）。"""
    gaps: list[dict[str, Any]] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict) or not _row_active_for_formal_quote(raw):
            continue
        if row_has_ai_estimate_pricing(raw):
            continue
        name = str(raw.get("name") or "").strip() or f"第{idx + 1}行"
        reasons: list[str] = []
        status = str(raw.get("recognition_status") or "").strip()
        if status in _PENDING_RECOGNITION_STATUSES and not bool(raw.get("pricing_review_required")):
            reasons.append("待确认")
        if _is_missing_quote_field_text(raw.get("spec")):
            reasons.append("规格为空")
        if _is_missing_quote_field_text(raw.get("usage")):
            reasons.append("用量为空")
        unit_price = str(raw.get("unit_price") or "").strip()
        if _is_missing_quote_field_text(unit_price) or not looks_like_valid_unit_price_text(unit_price):
            reasons.append("缺单价")
        if reasons:
            gaps.append({"index": idx, "name": name, "reasons": reasons})
    return gaps


def validate_structure_items_for_formal_quote(
    items: list[dict[str, Any]],
    *,
    allow_estimate: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """结构确认后正式报价前的兜底校验。"""
    gaps = summarize_structure_quote_gaps(items)
    pending_count = sum(1 for g in gaps if "待确认" in g.get("reasons", []))
    missing_price_count = sum(1 for g in gaps if "缺单价" in g.get("reasons", []))
    ai_estimate_count = sum(1 for r in items if isinstance(r, dict) and row_has_ai_estimate_pricing(r))
    summary: dict[str, Any] = {
        "gaps": gaps,
        "gap_count": len(gaps),
        "pending_count": pending_count,
        "missing_price_count": missing_price_count,
    }
    if ai_estimate_count:
        summary["ai_estimate_count"] = ai_estimate_count
    if not gaps:
        return True, summary
    if allow_estimate:
        summary["estimate_allowed"] = True
        return True, summary
    count = len(gaps)
    sample_names = "、".join(str(g.get("name") or "").strip() for g in gaps[:3] if g.get("name"))
    tail = f"（{sample_names}）" if sample_names else ""
    summary["message"] = (
        f"还有 {count} 行物料未确认或信息不完整{tail}，请先补全或删除后再生成正式报价。"
    )
    return False, summary
