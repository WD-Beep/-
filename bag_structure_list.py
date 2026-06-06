"""包类结构清单：从 structure_text 提取结构件，关联成本行，供报价结果与风控使用。"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol


class BagQuoteContextLike(Protocol):
    is_bag: bool
    bag_category: str
    complexity: str


def _norm(text: object) -> str:
    return str(text or "").strip().lower()


def _row_matches_any(text: str, terms: tuple[str, ...]) -> bool:
    low = _norm(text)
    return any(t.lower() in low for t in terms)


def _structure_mentions_keyword(struct: str, synonyms: tuple[str, ...]) -> bool:
    for s in synonyms:
        if s not in struct:
            continue
        if f"无{s}" in struct or f"不含{s}" in struct or f"没有{s}" in struct:
            continue
        return True
    return False

# 通用结构件目录（非订单硬编码；按 component-model 分类）
_STRUCTURE_CATALOG: tuple[dict[str, Any], ...] = (
    {"name": "肩带", "category": "carry", "category_label": "背负结构", "synonyms": ("肩带", "背带", "背负带"), "affects_cost": True},
    {"name": "背垫", "category": "carry", "category_label": "背负结构", "synonyms": ("背垫", "背板", "海绵背", "三明治网布"), "affects_cost": True},
    {"name": "腰封", "category": "carry", "category_label": "背负结构", "synonyms": ("腰封", "腰带"), "affects_cost": True},
    {"name": "顶包", "category": "external", "category_label": "外部结构", "synonyms": ("顶包", "顶袋", "顶盖仓"), "affects_cost": True},
    {"name": "翻盖", "category": "external", "category_label": "外部结构", "synonyms": ("翻盖", "盖片", "storm flap"), "affects_cost": True},
    {"name": "前袋", "category": "external", "category_label": "外部结构", "synonyms": ("前袋", "前仓", "正面袋"), "affects_cost": True},
    {"name": "侧袋", "category": "external", "category_label": "外部结构", "synonyms": ("侧袋", "侧仓", "侧兜"), "affects_cost": True},
    {"name": "网袋", "category": "external", "category_label": "外部结构", "synonyms": ("网袋", "网兜", "网布袋", "侧网袋"), "affects_cost": True},
    {"name": "水壶袋", "category": "external", "category_label": "外部结构", "synonyms": ("水壶袋", "水袋仓", "水瓶袋"), "affects_cost": True},
    {"name": "里布", "category": "internal", "category_label": "内部结构", "synonyms": ("里布", "里料", "内衬"), "affects_cost": True},
    {"name": "内袋", "category": "internal", "category_label": "内部结构", "synonyms": ("内袋", "拉链内袋"), "affects_cost": True},
    {"name": "电脑仓", "category": "internal", "category_label": "内部结构", "synonyms": ("电脑仓", "电脑隔层"), "affects_cost": True},
    {"name": "织带", "category": "accessory", "category_label": "辅料配件", "synonyms": ("织带", "尼龙带", "包边带"), "affects_cost": True},
    {"name": "插扣", "category": "accessory", "category_label": "辅料配件", "synonyms": ("插扣", "buckle", "扣具"), "affects_cost": True},
    {"name": "拉链", "category": "accessory", "category_label": "辅料配件", "synonyms": ("拉链", "zipper"), "affects_cost": True},
    {"name": "补强", "category": "functional", "category_label": "功能材料", "synonyms": ("补强", "补强片", "耐磨片"), "affects_cost": True},
    {"name": "弹力绳", "category": "accessory", "category_label": "辅料配件", "synonyms": ("弹力绳", "弹性绳", "shock cord"), "affects_cost": True},
)

_CATEGORY_ORDER = (
    "main_body",
    "external",
    "carry",
    "internal",
    "accessory",
    "functional",
    "process",
    "packaging",
    "amortization",
)


def _normalize_name(name: str) -> str:
    text = _norm(name)
    text = re.sub(r"[\s/\\+|·]+", "_", text)
    text = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "", text)
    return text or "unknown"


def _structure_id(category: str, name: str, source_text: str) -> str:
    norm_name = _normalize_name(name)
    src_hash = hashlib.sha1(source_text.encode("utf-8")).hexdigest()[:8]
    return f"{category}_{norm_name}_{src_hash}"


def _extract_source_snippet(structure_text: str, synonyms: tuple[str, ...]) -> tuple[str, float]:
    """返回命中原文片段与置信度（0~1）。"""
    struct = str(structure_text or "")
    if not struct.strip():
        return "", 0.0
    for line in re.split(r"[\n；;。]", struct):
        text = line.strip()
        if not text:
            continue
        for syn in synonyms:
            if syn not in text:
                continue
            if f"无{syn}" in text or f"不含{syn}" in text or f"没有{syn}" in text:
                continue
            confidence = 0.92 if syn == synonyms[0] else 0.85
            return text[:200], confidence
    if _structure_mentions_keyword(struct, synonyms):
        return struct[:120], 0.75
    return "", 0.0


def _link_cost_item_ids(rows: list[dict[str, Any]], synonyms: tuple[str, ...]) -> list[str]:
    ids: list[str] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        blob = " ".join(
            str(row.get(k) or "")
            for k in ("name", "role", "spec", "calc_note", "source_structure_desc")
        )
        if _row_matches_any(blob, synonyms):
            ids.append(f"row:{idx}")
    return ids


def _missing_fields_for_rows(rows: list[dict[str, Any]], cost_item_ids: list[str]) -> list[str]:
    if not cost_item_ids:
        return ["quantity", "spec", "material", "unit_price"]
    missing: set[str] = set()
    for cid in cost_item_ids:
        try:
            idx = int(str(cid).split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if idx < 0 or idx >= len(rows):
            continue
        row = rows[idx]
        if not isinstance(row, dict):
            continue
        usage = str(row.get("usage") or "").strip()
        spec = str(row.get("spec") or "").strip()
        price = str(row.get("unit_price") or "").strip()
        name = str(row.get("name") or "").strip()
        if usage in ("", "-", "—"):
            missing.add("quantity")
        if spec in ("", "-", "—"):
            missing.add("spec")
        if price in ("", "-", "—"):
            missing.add("unit_price")
        if not name:
            missing.add("material")
        if row.get("usage_ai"):
            missing.add("quantity")
        if row.get("unit_price_ai"):
            missing.add("unit_price")
    return sorted(missing)


def _estimate_status(rows: list[dict[str, Any]], cost_item_ids: list[str], *, affects_cost: bool) -> str:
    if not affects_cost:
        return "not_applicable"
    if not cost_item_ids:
        return "needs_manual"
    ai_any = False
    for cid in cost_item_ids:
        try:
            idx = int(str(cid).split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if idx < 0 or idx >= len(rows):
            continue
        row = rows[idx]
        if not isinstance(row, dict):
            continue
        if row.get("usage_ai") or row.get("unit_price_ai") or row.get("amount_ai") or row.get("ai_filled"):
            ai_any = True
            break
    return "ai_estimated" if ai_any else "exact"


def _risk_for_item(
    *,
    affects_cost: bool,
    cost_item_ids: list[str],
    estimate_status: str,
    missing_fields: list[str],
    user_status: str,
) -> tuple[str, str]:
    if user_status == "ignored":
        return "low", ""
    if user_status == "edited":
        if not cost_item_ids and affects_cost:
            return "high", "业务员标记需修改；仍无关联成本项"
        return "medium", "业务员标记需修改"
    if user_status == "confirmed" and cost_item_ids and estimate_status == "exact" and not missing_fields:
        return "low", "业务员已确认"
    if not affects_cost:
        return "low", ""
    if not cost_item_ids:
        return "high", "结构说明含该部件，但明细未见对应成本项"
    if estimate_status == "needs_manual":
        return "high", "结构件待补成本项"
    if estimate_status == "ai_estimated":
        reason = "关联成本项含 AI 估算字段"
        if missing_fields:
            reason += f"；缺少 {','.join(missing_fields)}"
        return "medium", reason
    if missing_fields:
        return "medium", f"关联成本项缺少 {','.join(missing_fields)}"
    return "low", ""


def _detected_components(structure_text: str) -> list[dict[str, Any]]:
    struct = str(structure_text or "")
    if not struct.strip():
        return []
    hits: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for comp in _STRUCTURE_CATALOG:
        synonyms = tuple(comp.get("synonyms") or ())
        if not _structure_mentions_keyword(struct, synonyms):
            continue
        source_text, confidence = _extract_source_snippet(struct, synonyms)
        category = str(comp.get("category") or "external")
        name = str(comp.get("name") or "")
        sid = _structure_id(category, name, source_text or name)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        hits.append(
            {
                "structure_id": sid,
                "name": name,
                "category": category,
                "category_label": str(comp.get("category_label") or category),
                "source_text": source_text,
                "extracted_confidence": round(confidence, 3),
                "affects_cost": bool(comp.get("affects_cost", True)),
                "synonyms": synonyms,
            }
        )
    hits.sort(key=lambda x: (_CATEGORY_ORDER.index(x["category"]) if x["category"] in _CATEGORY_ORDER else 99, x["name"]))
    return hits


def build_structure_item(
    comp: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    user_status: str = "pending",
    user_note: str = "",
) -> dict[str, Any]:
    synonyms = tuple(comp.get("synonyms") or ())
    cost_item_ids = _link_cost_item_ids(rows, synonyms)
    missing_fields = _missing_fields_for_rows(rows, cost_item_ids)
    affects_cost = bool(comp.get("affects_cost", True))
    estimate_status = _estimate_status(rows, cost_item_ids, affects_cost=affects_cost)
    risk_level, risk_reason = _risk_for_item(
        affects_cost=affects_cost,
        cost_item_ids=cost_item_ids,
        estimate_status=estimate_status,
        missing_fields=missing_fields,
        user_status=user_status,
    )
    return {
        "structure_id": comp["structure_id"],
        "name": comp["name"],
        "category": comp["category"],
        "category_label": comp.get("category_label") or comp["category"],
        "source_text": comp.get("source_text") or "",
        "extracted_confidence": comp.get("extracted_confidence", 0.0),
        "affects_cost": affects_cost,
        "cost_item_ids": cost_item_ids,
        "missing_fields": missing_fields,
        "estimate_status": estimate_status,
        "risk_level": risk_level,
        "risk_reason": risk_reason,
        "user_status": user_status,
        "user_note": user_note or "",
    }


def build_bag_structure_checklist(
    *,
    ctx: BagQuoteContextLike,
    structure_text: str,
    detail_rows: list[dict[str, Any]],
    existing_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成包类结构清单；非包类返回空壳。"""
    if not ctx.is_bag:
        return {
            "version": 1,
            "is_bag_product": False,
            "complexity": ctx.complexity,
            "items": [],
            "summary": _empty_summary(),
        }

    user_by_id: dict[str, dict[str, str]] = {}
    if existing_items:
        for item in existing_items:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("structure_id") or "").strip()
            if not sid:
                continue
            user_by_id[sid] = {
                "user_status": str(item.get("user_status") or "pending"),
                "user_note": str(item.get("user_note") or ""),
            }

    detected = _detected_components(structure_text)
    items: list[dict[str, Any]] = []
    for comp in detected:
        sid = comp["structure_id"]
        override = user_by_id.get(sid, {})
        items.append(
            build_structure_item(
                comp,
                detail_rows,
                user_status=override.get("user_status", "pending"),
                user_note=override.get("user_note", ""),
            )
        )

    return {
        "version": 1,
        "is_bag_product": True,
        "bag_category": ctx.bag_category,
        "complexity": ctx.complexity,
        "items": items,
        "summary": _summarize_items(items),
    }


def _empty_summary() -> dict[str, int]:
    return {
        "total": 0,
        "costed": 0,
        "pending_confirm": 0,
        "possible_leak": 0,
        "ignored": 0,
    }


def _summarize_items(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = _empty_summary()
    summary["total"] = len(items)
    for item in items:
        user_status = str(item.get("user_status") or "pending")
        if user_status == "ignored":
            summary["ignored"] += 1
            continue
        if item.get("cost_item_ids"):
            summary["costed"] += 1
        else:
            summary["possible_leak"] += 1
        if item.get("estimate_status") in {"needs_manual", "ai_estimated"} or item.get("risk_level") in {"medium", "high"}:
            summary["pending_confirm"] += 1
    return summary


def patch_structure_checklist_user_items(
    checklist: dict[str, Any],
    patches: list[dict[str, Any]],
) -> dict[str, Any]:
    """合并业务员对结构项的确认/忽略/需修改标记（轻量，不重算报价）。"""
    if not isinstance(checklist, dict):
        return checklist
    if not patches:
        return checklist
    patch_by_id: dict[str, dict[str, str]] = {}
    for p in patches:
        if not isinstance(p, dict):
            continue
        sid = str(p.get("structure_id") or "").strip()
        if not sid:
            continue
        status = str(p.get("user_status") or "pending").strip()
        if status not in {"pending", "confirmed", "ignored", "edited"}:
            continue
        patch_by_id[sid] = {
            "user_status": status,
            "user_note": str(p.get("user_note") or "").strip(),
        }
    if not patch_by_id:
        return checklist
    out = dict(checklist)
    items: list[dict[str, Any]] = []
    for item in checklist.get("items") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        sid = str(row.get("structure_id") or "").strip()
        if sid in patch_by_id:
            row["user_status"] = patch_by_id[sid]["user_status"]
            if patch_by_id[sid]["user_note"]:
                row["user_note"] = patch_by_id[sid]["user_note"]
        items.append(row)
    out["items"] = items
    out["summary"] = _summarize_items(items)
    return out


def merge_structure_checklist_patches(
    existing_patches: list[dict[str, Any]] | None,
    new_patch: dict[str, Any],
) -> list[dict[str, Any]]:
    sid = str(new_patch.get("structure_id") or "").strip()
    if not sid:
        return list(existing_patches or [])
    merged = [p for p in (existing_patches or []) if str(p.get("structure_id") or "") != sid]
    merged.append(
        {
            "structure_id": sid,
            "user_status": str(new_patch.get("user_status") or "pending"),
            "user_note": str(new_patch.get("user_note") or "").strip(),
        }
    )
    return merged


def structure_checklist_high_codes(checklist: dict[str, Any]) -> list[str]:
    """结构件存在但无成本项 → HIGH 风险码。"""
    if not checklist.get("is_bag_product"):
        return []
    codes: list[str] = []
    for item in checklist.get("items") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("affects_cost"):
            continue
        if str(item.get("user_status") or "") == "ignored":
            continue
        if item.get("cost_item_ids"):
            continue
        codes.append("bag_structure_missing_cost")
    return codes


VALID_STRUCTURE_USER_STATUSES = frozenset({"pending", "confirmed", "ignored", "edited"})


def patch_structure_checklist_item(
    checklist: dict[str, Any],
    *,
    structure_id: str,
    user_status: str,
    user_note: str = "",
) -> dict[str, Any]:
    """更新结构件用户状态（轻量 PATCH，不重算报价）。"""
    out = dict(checklist or {})
    status = str(user_status or "").strip()
    if status not in VALID_STRUCTURE_USER_STATUSES:
        raise ValueError(f"invalid user_status: {user_status}")
    sid = str(structure_id or "").strip()
    if not sid:
        raise ValueError("missing structure_id")
    items: list[dict[str, Any]] = []
    found = False
    for raw in out.get("items") or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if str(item.get("structure_id") or "") == sid:
            found = True
            item["user_status"] = status
            if user_note:
                item["user_note"] = str(user_note)[:500]
            risk_level, risk_reason = _risk_for_item(
                affects_cost=bool(item.get("affects_cost", True)),
                cost_item_ids=list(item.get("cost_item_ids") or []),
                estimate_status=str(item.get("estimate_status") or ""),
                missing_fields=list(item.get("missing_fields") or []),
                user_status=status,
            )
            item["risk_level"] = risk_level
            item["risk_reason"] = risk_reason
        items.append(item)
    if not found:
        raise ValueError(f"structure_id not found: {structure_id}")
    out["items"] = items
    out["summary"] = _summarize_items(items)
    out["user_dirty"] = True
    return out
