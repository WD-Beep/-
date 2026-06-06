"""包类 skill 全流程：结构提取 → 结构确认 → 成本拆解 → 报价 → 风控。"""

from __future__ import annotations

from typing import Any

from bag_quote_costing import (
    BagQuoteContext,
    _LEAK_KEYWORDS,
    detect_bag_product,
    resolve_bag_quote_skill,
)
from bag_structure_list import (
    _STRUCTURE_CATALOG,
    _row_matches_any,
    _structure_mentions_keyword,
    build_bag_structure_checklist,
    structure_checklist_high_codes,
)
from material_inference import (
    SOURCE_STRUCTURE,
    build_inferred_candidate_row,
    merge_material_inference_candidates,
)


def _catalog_for_name(name: str) -> dict[str, Any] | None:
    for comp in _STRUCTURE_CATALOG:
        if comp.get("name") == name:
            return comp
    return None


def find_structure_extraction_leaks(structure_text: str, checklist: dict[str, Any]) -> list[dict[str, str]]:
    """结构说明里出现的标准结构词未进入结构清单 → 提取漏项。"""
    struct = str(structure_text or "")
    if not struct.strip():
        return []
    extracted_names = {
        str(item.get("name") or "").strip()
        for item in (checklist.get("items") or [])
        if isinstance(item, dict)
    }
    leaks: list[dict[str, str]] = []
    for label, synonyms in _LEAK_KEYWORDS:
        if not _structure_mentions_keyword(struct, synonyms):
            continue
        if label in extracted_names:
            continue
        leaks.append(
            {
                "keyword": label,
                "reason": f"结构说明含「{label}」但未进入结构清单（提取漏项）",
                "severity": "high",
                "code": "bag_structure_extraction_leak",
            }
        )
    return leaks


def pipeline_high_codes(structure_text: str, checklist: dict[str, Any]) -> list[str]:
    codes = list(structure_checklist_high_codes(checklist))
    for leak in find_structure_extraction_leaks(structure_text, checklist):
        codes.append(str(leak.get("code") or "bag_structure_extraction_leak"))
    return sorted(set(codes))


def _rows_match_structure(rows: list[dict[str, Any]], synonyms: tuple[str, ...]) -> bool:
    for row in rows:
        if not isinstance(row, dict):
            continue
        blob = " ".join(str(row.get(k) or "") for k in ("name", "role", "calc_note", "source_structure_desc"))
        if _row_matches_any(blob, synonyms):
            return True
    return False


def build_structure_cost_candidates(
    checklist: dict[str, Any],
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """为结构清单中尚无成本行的结构件生成待核候选行（供确认/LLM 补全）。"""
    rows = [r for r in items if isinstance(r, dict)]
    new_rows: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    for item in checklist.get("items") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("affects_cost"):
            continue
        if str(item.get("user_status") or "") == "ignored":
            continue
        comp = _catalog_for_name(str(item.get("name") or ""))
        synonyms = tuple(comp.get("synonyms") or ()) if comp else (str(item.get("name") or ""),)
        if _rows_match_structure(rows + new_rows, synonyms):
            continue
        sid = str(item.get("structure_id") or "")
        source = str(item.get("source_text") or "")[:120]
        row = build_inferred_candidate_row(
            component_name=str(item.get("name") or ""),
            source_type=SOURCE_STRUCTURE,
            source_snippet=source or str(item.get("name") or ""),
            structure_id=sid,
            category_label=str(item.get("category_label") or item.get("category") or ""),
        )
        row["recognition_reason"] = f"包类结构清单提取：{source or '待补用量/单价'}"
        new_rows.append(row)
        meta.append({"structure_id": sid, "name": item.get("name"), "candidate_row_name": row["name"]})
    return new_rows, meta


def build_bag_structure_llm_addon(checklist: dict[str, Any]) -> str:
    items = checklist.get("items") if isinstance(checklist.get("items"), list) else []
    if not items:
        return ""
    lines = [
        "\n【包类结构清单 · 必须逐项拆解成本】",
        "以下结构件来自结构说明提取，报价 rows 必须为每一项提供可计成本行（或明确待核标记）：",
    ]
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('name')} | 模块={item.get('category_label') or item.get('category')} "
            f"| 来源={str(item.get('source_text') or '')[:80]} "
            f"| structure_id={item.get('structure_id')} "
            f"| 缺字段={','.join(item.get('missing_fields') or []) or '无'} "
            f"| 需确认={'是' if item.get('estimate_status') in {'needs_manual', 'ai_estimated'} else '否'}"
        )
    lines.append(
        "规则：不得遗漏清单内结构件；缺尺寸/单价时 usage_ai 或 unit_price_ai=true 并在 calc_note 写依据；"
        "name 或 role 须能对应 structure_id。"
    )
    lines.append(
        "特别要求：input.rows 中 from_bag_structure_extraction=true 或名称含“结构待核”的行，是系统已提取出的真实待补成本项，"
        "不得忽略、不得保留 unit_price 为 '-'。请按常见市场辅料/工艺价格给出业务可复核的估算单价，"
        "同时标记 unit_price_ai=true、amount_ai=true，并在 calc_note 写明“市场估算，需人工复核”。"
    )
    lines.append(
        "对 recognition_status='split' 或带 _source_combined_name 的已拆分行也一样处理：它们是从组合文本中拆出的独立成本项，"
        "如 unit_price 为 '-' 或缺失，需补市场估算单价、计算 amount，并标记 unit_price_ai=true、amount_ai=true；不要因为拆分来源就忽略。"
    )
    leaks = checklist.get("extraction_leaks") or []
    if leaks:
        lines.append("警告：以下结构词可能提取漏项，请优先补齐：" + "、".join(str(x.get("keyword") or "") for x in leaks[:6]))
    return "\n".join(lines) + "\n"


def apply_bag_quote_preparse(
    payload: dict[str, Any],
    *,
    structure_text: str,
    product_type: str = "",
    product_name: str = "",
    user_prompt: str = "",
) -> dict[str, Any]:
    """需求解析/结构确认前：识别包类 → 提取结构清单 → 补成本候选行。"""
    ctx = detect_bag_product(
        product_type=product_type,
        product_name=product_name,
        structure_text=structure_text,
        user_prompt=user_prompt,
    )
    if not ctx.is_bag:
        return {"active": False, "is_bag_product": False}

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    existing = payload.get("structure_checklist")
    existing_items = existing.get("items") if isinstance(existing, dict) else None

    checklist = build_bag_structure_checklist(
        ctx=ctx,
        structure_text=structure_text,
        detail_rows=items,
        existing_items=existing_items if isinstance(existing_items, list) else None,
    )
    leaks = find_structure_extraction_leaks(structure_text, checklist)
    checklist["extraction_leaks"] = leaks
    checklist["extraction_complete"] = not leaks and bool(checklist.get("items"))

    candidates, candidate_meta = build_structure_cost_candidates(checklist, items)
    if not payload.get("bag_structure_candidates_merged") and candidates:
        payload["items"] = list(items) + candidates
        payload["bag_structure_candidates_merged"] = True
        checklist["cost_candidates_added"] = candidate_meta
    elif payload.get("bag_structure_candidates_merged"):
        checklist["cost_candidates_added"] = checklist.get("cost_candidates_added") or []

    vision_text = str(payload.get("vision_analysis_text") or "").strip()
    if not vision_text and "附图" in structure_text:
        vision_text = structure_text
    image_present = bool(
        payload.get("_composer_vision_images")
        or payload.get("structure_vision_images")
        or payload.get("structure_vision_image_count")
        or "已作为附图" in structure_text
    )
    inference_report = merge_material_inference_candidates(
        payload,
        structure_text=structure_text,
        vision_text=vision_text,
        image_present=bool(image_present),
    )

    payload["structure_checklist"] = checklist
    payload["structure_items"] = checklist.get("items") or []
    skill = resolve_bag_quote_skill(
        product_type=product_type,
        product_name=product_name,
        structure_text=structure_text,
        user_prompt=user_prompt,
    )
    payload["bag_quote_skill"] = skill
    payload["bag_quote_pipeline"] = {
        "stage": "preparse",
        "is_bag_product": True,
        "complexity": ctx.complexity,
        "structure_item_count": len(checklist.get("items") or []),
        "cost_candidates_added": len(candidates),
        "inference_candidates_added": int(inference_report.get("candidates_added") or 0),
        "extraction_leak_count": len(leaks),
    }
    return {
        "active": True,
        "is_bag_product": True,
        "ctx": ctx,
        "checklist": checklist,
        "skill": skill,
        "candidates_added": len(candidates),
        "inference_report": inference_report,
        "extraction_leaks": leaks,
    }
