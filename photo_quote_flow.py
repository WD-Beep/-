"""包款图片 + 尺寸文字 → BOM 草稿 → 现有报价流程。"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from intent_router import has_explicit_product_dimensions
from material_inference import SOURCE_IMAGE
from prompt_intent import user_prompt_has_quote_intent

PHOTO_INFERENCE_NOTE = "图片推理，需人工复核"
SOURCE_USER_EXPLICIT = "user_explicit"

_DIM_TRIPLE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:厘米|公分|cm)?\s*(?:×|[xX\*])\s*"
    r"(\d+(?:\.\d+)?)\s*(?:厘米|公分|cm)?\s*(?:×|[xX\*])\s*(\d+(?:\.\d+)?)",
    re.I,
)
_QTY_RE = re.compile(r"(\d+)\s*(?:个|件|pcs|PC|套)", re.I)
_FABRIC_RE = re.compile(
    r"(210[Dd]?[^，,；;\s]{0,12}(?:涤纶|尼龙|牛津|帆布)?|"
    r"[^，,；;\s]{0,8}(?:涤纶|尼龙|牛津|帆布|塔丝隆|里布|里料)[^，,；;\s]{0,12})",
    re.I,
)
_LINING_RE = re.compile(r"(有里布|无里布|不要里布|不含里布|里布|里料)", re.I)
_ZIPPER_RE = re.compile(r"拉链", re.I)
_STRAP_RE = re.compile(r"(肩带|背带|手提|手挽|织带)", re.I)
_HARDWARE_RE = re.compile(r"(扣具|五金|D扣|插扣|日字扣|调节扣|勾扣|扣[^具])", re.I)
_PACKAGING_RE = re.compile(r"(包装|OPP|纸箱|胶袋)", re.I)


def composer_vision_images(payload: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    raw = (payload or {}).get("_composer_vision_images")
    if not raw:
        return ()
    if isinstance(raw, tuple):
        return tuple(raw)
    if isinstance(raw, list):
        return tuple(raw)
    return ()


def is_photo_quote_candidate(user_text: str, *, has_uploaded_sheet: bool, vision_count: int) -> bool:
    if has_uploaded_sheet or vision_count <= 0:
        return False
    text = str(user_text or "").strip()
    if not text:
        return False
    return user_prompt_has_quote_intent(text) or bool(re.search(r"报价|多少钱|核算", text, re.I))


def parse_quantity_from_text(user_text: str) -> int | None:
    m = _QTY_RE.search(str(user_text or ""))
    if not m:
        return None
    try:
        q = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return q if q > 0 else None


def parse_product_size_from_text(user_text: str) -> dict[str, Any]:
    m = _DIM_TRIPLE_RE.search(str(user_text or ""))
    if not m:
        return {}
    try:
        return {
            "LCM": float(m.group(1)),
            "WCM": float(m.group(2)),
            "HCM": float(m.group(3)),
            "unit": "cm",
        }
    except (TypeError, ValueError):
        return {}


def assess_photo_quote_prerequisites(user_text: str) -> tuple[bool, list[str], dict[str, Any]]:
    """返回 (ready, missing_labels, parsed_user_fields)。"""
    text = str(user_text or "").strip()
    fields: dict[str, Any] = {
        "product_size": parse_product_size_from_text(text),
        "product_size_text": "",
        "quantity": parse_quantity_from_text(text),
        "fabric_text": "",
        "lining_text": "",
        "has_lining": None,
        "zipper_mentioned": bool(_ZIPPER_RE.search(text)),
        "strap_mentioned": bool(_STRAP_RE.search(text)),
        "hardware_mentioned": bool(_HARDWARE_RE.search(text)),
        "packaging_mentioned": bool(_PACKAGING_RE.search(text)),
    }
    fm = _FABRIC_RE.search(text)
    if fm:
        fields["fabric_text"] = str(fm.group(1) or "").strip()
    lm = _LINING_RE.search(text)
    if lm:
        lt = str(lm.group(1) or "").strip()
        fields["lining_text"] = lt
        if re.search(r"无里布|不要里布|不含里布", lt):
            fields["has_lining"] = False
        else:
            fields["has_lining"] = True
    if fields["product_size"]:
        ps = fields["product_size"]
        fields["product_size_text"] = f"{ps.get('LCM')}×{ps.get('WCM')}×{ps.get('HCM')}cm"

    missing: list[str] = []
    if not fields["product_size"]:
        missing.append("成品长宽高（厘米，如 37×12×17cm）")
    if not fields["quantity"]:
        missing.append("订购数量（如 500 个）")
    if not fields["fabric_text"] and not re.search(r"面料|主料|布料", text, re.I):
        missing.append("主面料/材质要求（如 210D 涤纶）")
    if fields["has_lining"] is None and not re.search(r"里布|里料", text, re.I):
        missing.append("是否有里布（有/无）")
    if not fields["zipper_mentioned"]:
        missing.append("拉链要求（数量或位置，如 主拉链+前袋拉链）")
    if not fields["strap_mentioned"]:
        missing.append("肩带/手提/织带要求")
    if not fields["hardware_mentioned"] and not fields["packaging_mentioned"]:
        missing.append("扣具/五金或包装要求（可写「常规」）")

    return (not missing, missing, fields)


def build_photo_quote_clarify_response(missing: list[str], user_text: str = "") -> dict[str, Any]:
    items = [str(x).strip() for x in (missing or []) if str(x).strip()]
    lead = "已收到包款图片。"
    if not items:
        lead = "已收到包款图片，请补充报价所需信息。"
    else:
        lead += "请先补充：" + "、".join(items) + "。"
    return {
        "quote_ready": False,
        "reply_type": "photo_quote_clarify",
        "intent": "PHOTO_QUOTE_CLARIFY",
        "assistant_message": lead,
        "missing_fields": items,
        "user_text_echo": str(user_text or "").strip()[:400],
    }


def mark_image_inferred_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["source_type"] = SOURCE_IMAGE
    out["inferred_by_ai"] = True
    out["pricing_review_required"] = True
    out["needs_human_confirm"] = True
    out["needs_manual_confirm"] = True
    out["recognition_status"] = "candidate_review"
    out["usage_ai"] = True
    out["unit_price_ai"] = True
    out["amount_ai"] = bool(out.get("amount_ai"))
    out["source"] = "ai"
    out["kb_hit"] = False
    reason = str(out.get("recognition_reason") or "包款图片视觉识别").strip()
    out["recognition_reason"] = reason
    cn = str(out.get("calc_note") or "").strip()
    if PHOTO_INFERENCE_NOTE not in cn:
        out["calc_note"] = f"{cn}；{PHOTO_INFERENCE_NOTE}" if cn else PHOTO_INFERENCE_NOTE
    return out


def mark_user_explicit_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["source_type"] = SOURCE_USER_EXPLICIT
    out["user_specified"] = True
    out["inferred_by_ai"] = False
    out.pop("pricing_review_required", None)
    out.setdefault("source", "user")
    out.setdefault("recognition_status", "matched")
    out.setdefault("recognition_reason", "用户文字明确要求")
    cn = str(out.get("calc_note") or "").strip()
    if cn and "用户输入" not in cn:
        out["calc_note"] = f"{cn}（用户输入）"
    elif not cn:
        out["calc_note"] = "用户文字明确要求"
    return out


def _norm_name_key(name: str) -> str:
    text = re.sub(r"[（(].*?[）)]", "", str(name or ""))
    return re.sub(r"\s+", "", text).lower()


def build_user_explicit_bom_rows(user_text: str, user_fields: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fabric = str(user_fields.get("fabric_text") or "").strip()
    if fabric:
        rows.append(
            mark_user_explicit_row(
                {
                    "name": fabric if "面料" in fabric or "布" in fabric else f"{fabric}（外料）",
                    "role": "外料",
                    "spec": "-",
                    "usage": "-",
                    "unit_price": "-",
                    "amount": 0.0,
                }
            )
        )
    if user_fields.get("has_lining") is True:
        lining_name = str(user_fields.get("lining_text") or "里布").strip()
        if lining_name in {"有里布", "里布", "里料"}:
            lining_name = "里布"
        rows.append(
            mark_user_explicit_row(
                {
                    "name": lining_name if "里" in lining_name else f"{lining_name}（里布）",
                    "role": "里料",
                    "spec": "-",
                    "usage": "-",
                    "unit_price": "-",
                    "amount": 0.0,
                }
            )
        )
    text = str(user_text or "")
    if _ZIPPER_RE.search(text):
        for label in _extract_zipper_labels(text):
            rows.append(
                mark_user_explicit_row(
                    {
                        "name": label,
                        "role": "拉链",
                        "spec": "-",
                        "usage": "-",
                        "unit_price": "-",
                        "amount": 0.0,
                    }
                )
            )
    if _STRAP_RE.search(text):
        strap_name = "肩带"
        if re.search(r"手提|手挽", text):
            strap_name = "手提带"
        elif re.search(r"织带", text):
            strap_name = "织带"
        rows.append(
            mark_user_explicit_row(
                {
                    "name": strap_name,
                    "role": "织带/肩带",
                    "spec": "-",
                    "usage": "-",
                    "unit_price": "-",
                    "amount": 0.0,
                }
            )
        )
    if _PACKAGING_RE.search(text) or re.search(r"常规包装", text):
        rows.append(
            mark_user_explicit_row(
                {
                    "name": "包装辅料",
                    "role": "包装",
                    "spec": "-",
                    "usage": "-",
                    "unit_price": "-",
                    "amount": 0.0,
                }
            )
        )
    return rows


def _extract_zipper_labels(text: str) -> list[str]:
    text = str(text or "")
    patterns = ("主拉链", "前袋拉链", "侧袋拉链", "内袋拉链")
    labels: list[str] = []
    for pat in patterns:
        if pat in text:
            labels.append(pat)
    if not labels and _ZIPPER_RE.search(text):
        labels.append("拉链")
    seen: set[str] = set()
    out: list[str] = []
    for raw in labels:
        key = _norm_name_key(raw)
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return out


def _vision_rows_from_payload(obj: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_items = obj.get("items")
    if not isinstance(raw_items, list):
        return rows
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        row = mark_image_inferred_row(
            {
                "name": name,
                "role": str(raw.get("role") or "辅料").strip() or "辅料",
                "spec": str(raw.get("spec") or "-").strip() or "-",
                "usage": str(raw.get("usage") or "-").strip() or "-",
                "unit_price": str(raw.get("unit_price") or "-").strip() or "-",
                "amount": raw.get("amount") if raw.get("amount") is not None else 0.0,
                "recognition_reason": str(raw.get("reason") or raw.get("vision_note") or "包款图片识别").strip(),
            }
        )
        rows.append(row)
    return rows


def _build_structure_text_from_vision(obj: dict[str, Any], user_text: str) -> str:
    parts: list[str] = []
    bag_type = str(obj.get("bag_type") or obj.get("product_type") or "").strip()
    if bag_type:
        parts.append(f"包型：{bag_type}")
    summary = str(obj.get("structure_summary") or obj.get("reply_plain") or "").strip()
    if summary:
        parts.append(summary)
    detected = obj.get("detected") if isinstance(obj.get("detected"), dict) else {}
    if detected:
        for key, label in (
            ("main_fabric_clue", "主料线索"),
            ("lining_clue", "里布线索"),
            ("zipper_count", "拉链数量"),
            ("pocket_count", "口袋数量"),
            ("shoulder_strap", "肩带"),
            ("top_handle", "手提"),
            ("hardware_clues", "五金"),
            ("packaging_clue", "包装"),
            ("process_clue", "工艺"),
        ):
            val = detected.get(key)
            if val in (None, "", [], False):
                continue
            if isinstance(val, list):
                val = "、".join(str(x) for x in val if str(x).strip())
            parts.append(f"{label}：{val}")
    user = str(user_text or "").strip()
    if user:
        parts.append(f"用户补充：{user[:500]}")
    parts.append("【图片来源】用户上传包款参考图，以下结构项含图片推理，需人工复核。")
    return "\n".join(parts)


def build_rule_based_vision_result(user_text: str, user_fields: dict[str, Any]) -> dict[str, Any]:
    """无视觉 API 时的规则兜底（测试/离线）。"""
    text = str(user_text or "")
    bag_type = "斜挎包" if "斜挎" in text else ("双肩包" if "双肩" in text else "包袋")
    items: list[dict[str, Any]] = []
    if re.search(r"前袋|插袋|侧袋", text):
        items.append({"name": "前袋/插袋（图片结构推断）", "role": "辅料", "vision_note": "文字+结构推断"})
    if re.search(r"拉头|拉片", text):
        items.append({"name": "拉链拉头（图片结构推断）", "role": "拉头", "vision_note": "结构推断"})
    elif _ZIPPER_RE.search(text):
        items.append({"name": "拉链拉头（图片结构推断）", "role": "拉头", "vision_note": "结构推断"})
    if _HARDWARE_RE.search(text):
        items.append({"name": "扣具/五金（图片结构推断）", "role": "扣具", "vision_note": "结构推断"})
    return {
        "product_name": bag_type,
        "bag_type": bag_type,
        "structure_summary": f"根据用户描述识别为{bag_type}，具体裁片以图片复核为准。",
        "detected": {
            "zipper_count": len(_extract_zipper_labels(text)) or (1 if _ZIPPER_RE.search(text) else 0),
            "shoulder_strap": bool(_STRAP_RE.search(text)),
            "packaging_clue": "常规包装" if _PACKAGING_RE.search(text) or "常规包装" in text else "",
        },
        "items": items,
        "vision_mode": "rule_fallback",
    }


def extract_photo_bom_via_vision(
    vision_images: tuple[tuple[str, str], ...],
    user_text: str,
    user_fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """调用视觉模型；失败时规则兜底。返回 (vision_obj, status)。"""
    status: dict[str, Any] = {"vision_attempt": True}
    if not vision_images:
        status["error"] = "no_images"
        return build_rule_based_vision_result(user_text, user_fields), status

    if os.environ.get("PHOTO_QUOTE_FORCE_RULE_VISION", "").strip().lower() in {"1", "true", "yes"}:
        status["vision_mode"] = "rule_forced"
        return build_rule_based_vision_result(user_text, user_fields), status

    try:
        from quotation_agent.moonshot_client import (
            chat_completions_multimodal_user,
            default_vision_model,
            moonshot_api_key,
        )
    except ImportError:
        status["vision_fallback"] = "import_error"
        return build_rule_based_vision_result(user_text, user_fields), status

    if not moonshot_api_key():
        status["vision_fallback"] = "missing_api_key"
        return build_rule_based_vision_result(user_text, user_fields), status

    schema_hint = (
        "只输出一个 JSON 对象（无 Markdown）。字段：\n"
        '{"product_name":"","bag_type":"","structure_summary":"",'
        '"detected":{"main_fabric_clue":"","lining_clue":"","zipper_count":0,'
        '"pocket_count":0,"shoulder_strap":true,"top_handle":false,'
        '"hardware_clues":[],"packaging_clue":"","process_clue":""},'
        '"items":[{"name":"","role":"","spec":"","usage":"","unit_price":"","reason":""}]}\n'
        "items 为 BOM 草稿：包型、口袋、拉链、肩带/织带、扣具、包装/工艺等；"
        "看不清的写 reason；不要编造单价。"
    )
    task = (
        "你是箱包 OEM 结构识别助手。用户上传包款照片并补充文字需求。"
        "请识别：包型、主体结构、面料/里布线索、拉链数量、口袋数量、"
        "肩带/手提/织带、扣具五金、包装/工艺提示，并输出 BOM 草稿 items。\n"
        + schema_hint
        + "\n用户文字：\n"
        + str(user_text or "")[:1200]
    )
    pairs = [(mime, b64) for mime, b64 in vision_images if str(b64 or "").strip()]
    try:
        raw = chat_completions_multimodal_user(
            text=task,
            images_b64=pairs[:4],
            model=os.environ.get("PHOTO_QUOTE_VISION_MODEL")
            or os.environ.get("QUOTATION_AGENT_VISION_MODEL")
            or default_vision_model(),
            temperature=0.35,
            max_tokens=4096,
            timeout_sec=120,
        )
        obj = _extract_json_object(raw)
        if not obj:
            status["vision_fallback"] = "parse_error"
            return build_rule_based_vision_result(user_text, user_fields), status
        status["vision_mode"] = "llm"
        return obj, status
    except Exception as exc:  # noqa: BLE001
        status["vision_fallback"] = "request_failed"
        status["vision_error"] = str(exc)[:200]
        return build_rule_based_vision_result(user_text, user_fields), status


def _extract_json_object(text: str) -> dict[str, Any]:
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("\n", 1)
        if len(parts) == 2 and "```" in parts[1]:
            t = parts[1].rsplit("```", 1)[0].strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        obj = json.loads(t[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def merge_photo_bom_draft(
    user_rows: list[dict[str, Any]],
    vision_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in list(user_rows) + list(vision_rows):
        if not isinstance(row, dict):
            continue
        key = _norm_name_key(str(row.get("name") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(dict(row))
    return merged


def run_photo_quote_pipeline(
    vision_images: tuple[tuple[str, str], ...],
    user_text: str,
    user_fields: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], str, dict[str, Any]]:
    """返回 (items, meta, structure_text, status)。"""
    vision_obj, status = extract_photo_bom_via_vision(vision_images, user_text, user_fields)
    user_rows = build_user_explicit_bom_rows(user_text, user_fields)
    vision_rows = _vision_rows_from_payload(vision_obj)
    items = merge_photo_bom_draft(user_rows, vision_rows)
    structure_text = _build_structure_text_from_vision(vision_obj, user_text)
    product_name = str(vision_obj.get("product_name") or vision_obj.get("bag_type") or "").strip()
    if not product_name:
        product_name = "定制包袋"
    meta = {
        "photo_quote_flow": True,
        "product_name": product_name,
        "vision_summary": str(vision_obj.get("structure_summary") or "").strip(),
        "vision_mode": status.get("vision_mode") or status.get("vision_fallback") or "",
        "user_explicit_count": sum(1 for r in items if r.get("source_type") == SOURCE_USER_EXPLICIT),
        "image_inferred_count": sum(1 for r in items if r.get("source_type") == SOURCE_IMAGE),
    }
    status["item_count"] = len(items)
    return items, meta, structure_text, status


def summarize_photo_quote_sources(items: list[dict[str, Any]] | None) -> dict[str, int]:
    rows = [r for r in (items or []) if isinstance(r, dict)]
    kb = sum(1 for r in rows if r.get("kb_hit"))
    user_n = sum(1 for r in rows if r.get("source_type") == SOURCE_USER_EXPLICIT)
    img_n = sum(1 for r in rows if r.get("source_type") == SOURCE_IMAGE)
    ai_n = sum(
        1
        for r in rows
        if r.get("source_type") not in {SOURCE_USER_EXPLICIT, SOURCE_IMAGE}
        and (r.get("unit_price_ai") or r.get("usage_ai") or r.get("inferred_by_ai"))
    )
    return {
        "user_explicit_count": user_n,
        "image_inferred_count": img_n,
        "kb_count": kb,
        "ai_estimate_count": ai_n,
    }


def preserve_photo_row_source_markers(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """LLM 补全后保留图片/用户来源标记。"""
    by_key = {
        _norm_name_key(str(r.get("name") or "")): r
        for r in before
        if isinstance(r, dict) and _norm_name_key(str(r.get("name") or ""))
    }
    out: list[dict[str, Any]] = []
    for row in after:
        if not isinstance(row, dict):
            continue
        nr = dict(row)
        prev = by_key.get(_norm_name_key(str(nr.get("name") or "")))
        if isinstance(prev, dict):
            st = str(prev.get("source_type") or "").strip()
            if st == SOURCE_IMAGE:
                nr = mark_image_inferred_row({**prev, **nr})
            elif st == SOURCE_USER_EXPLICIT:
                nr = mark_user_explicit_row({**prev, **nr})
        out.append(nr)
    return out


def build_photo_quote_data_notice(meta: dict[str, Any] | None) -> str:
    if not isinstance(meta, dict):
        return ""
    parts: list[str] = []
    u = int(meta.get("user_explicit_count") or 0)
    i = int(meta.get("image_inferred_count") or 0)
    k = int(meta.get("kb_count") or 0)
    if u:
        parts.append(f"用户明确输入 {u} 项")
    if i:
        parts.append(f"图片推断 {i} 项（需复核）")
    if k:
        parts.append(f"价格库 {k} 项")
    if not parts:
        return ""
    return "数据来源：" + "；".join(parts) + "。"
