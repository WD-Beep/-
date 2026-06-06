"""管理员修正收件箱：BOM 差异摘要、修正类型、状态文案。"""
from __future__ import annotations

from typing import Any


ADMIN_UPDATE_STATUS_HANDLED = "handled"

CORRECTION_PROBLEM_TYPE_OPTIONS: dict[str, str] = {
    "missing_fields": "业务员原表缺字段",
    "unclear_usage": "用量不清楚",
    "bad_unit_price": "单价不合理",
    "bad_material_name": "材料名称不规范",
    "unclear_tier_qty": "数量/阶梯价不明确",
    "incomplete_structure": "结构描述不完整",
    "agent_recognition_error": "agent 识别错误",
    "agent_cost_bias": "agent 成本计算偏差",
    "other": "其他",
}

_BOM_DIFF_FIELDS: tuple[tuple[str, str], ...] = (
    ("spec", "规格"),
    ("usage", "用量"),
    ("unit_price", "单价"),
    ("calc_note", "计算方式"),
    ("amount_text", "小计"),
)


def admin_update_status_label_cn(status: str) -> str:
    key = str(status or "").strip().lower()
    if key == "pending_view":
        return "未读"
    if key == "viewed":
        return "已查看"
    if key == ADMIN_UPDATE_STATUS_HANDLED:
        return "已处理"
    return "—"


def normalize_bom_row(raw: dict[str, Any] | None) -> dict[str, str]:
    item = raw if isinstance(raw, dict) else {}
    amount_raw = item.get("amount_text")
    if amount_raw in (None, ""):
        amt = item.get("amount")
        amount_raw = f"{amt}" if amt not in (None, "") else "-"
    calc = str(item.get("calc_note") or item.get("calc_method") or item.get("calc_note_text") or "").strip()
    return {
        "name": str(item.get("name") or "").strip(),
        "spec": str(item.get("spec") or "-").strip() or "-",
        "usage": str(item.get("usage") or "-").strip() or "-",
        "unit_price": str(item.get("unit_price") or "-").strip() or "-",
        "calc_note": calc or "—",
        "amount_text": str(amount_raw or "-").strip() or "-",
    }


def extract_detail_rows_from_quote(quote_obj: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(quote_obj, dict):
        return []
    rows = quote_obj.get("detail_rows")
    if not isinstance(rows, list):
        items = quote_obj.get("items")
        rows = items if isinstance(items, list) else []
    out: list[dict[str, str]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        norm = normalize_bom_row(raw)
        if norm["name"]:
            out.append(norm)
    return out


def compute_bom_diff_summary(
    original_rows: list[dict[str, Any] | dict[str, str]],
    corrected_rows: list[dict[str, Any] | dict[str, str]],
) -> dict[str, Any]:
    orig = [normalize_bom_row(r) for r in original_rows if normalize_bom_row(r)["name"]]
    corr = [normalize_bom_row(r) for r in corrected_rows if normalize_bom_row(r)["name"]]
    orig_map = {r["name"]: r for r in orig}
    corr_map = {r["name"]: r for r in corr}

    added: list[dict[str, str]] = []
    removed: list[dict[str, str]] = []
    changed: list[dict[str, str]] = []
    lines: list[str] = []

    for name, old in orig_map.items():
        if name not in corr_map:
            summary = f"删除：{name}"
            removed.append({"name": name, "summary": summary})
            lines.append(summary)
            continue
        new = corr_map[name]
        parts: list[str] = []
        for field, label in _BOM_DIFF_FIELDS:
            if old.get(field) != new.get(field):
                parts.append(f"{label} {old.get(field)} -> {new.get(field)}")
        if parts:
            summary = f"{name}：{' · '.join(parts)}"
            changed.append({"name": name, "summary": summary})
            lines.append(summary)

    for name, new in corr_map.items():
        if name in orig_map:
            continue
        summary = f"新增：{name} 用量{new.get('usage')}，{new.get('unit_price')}"
        added.append({"name": name, "summary": summary})
        lines.append(summary)

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "lines": lines,
        "has_changes": bool(added or removed or changed),
    }


def build_correction_types(
    *,
    has_visual_correction: bool,
    has_calculated_sheet: bool,
    has_correction_note: bool,
    has_corrected_sheet: bool,
    approval_status: str = "",
) -> list[str]:
    types: list[str] = []
    if has_visual_correction:
        types.append("bom_visual")
    if has_calculated_sheet:
        types.append("calculated_sheet")
    if has_correction_note:
        types.append("correction_note")
    if has_corrected_sheet:
        types.append("corrected_sheet")
    ast = str(approval_status or "").strip().lower()
    if ast == "rejected":
        types.append("approval_rejected")
    elif ast == "approved":
        types.append("approval_approved")
    return types


def normalize_correction_problem_types(raw: Any) -> list[str]:
    if isinstance(raw, list):
        keys = [str(x).strip() for x in raw if str(x).strip()]
    else:
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            import json

            parsed = json.loads(text)
            keys = [str(x).strip() for x in parsed] if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            keys = []
    allowed = set(CORRECTION_PROBLEM_TYPE_OPTIONS)
    out: list[str] = []
    for key in keys:
        if key in allowed and key not in out:
            out.append(key)
    return out


def correction_problem_types_label_cn(keys: list[str]) -> list[str]:
    labels: list[str] = []
    for key in normalize_correction_problem_types(keys):
        label = CORRECTION_PROBLEM_TYPE_OPTIONS.get(key)
        if label:
            labels.append(label)
    return labels


def correction_types_label_cn(types: list[str]) -> str:
    labels: list[str] = []
    mapping = {
        "bom_visual": "BOM 可视化修正",
        "calculated_sheet": "管理员自算表格",
        "correction_note": "修正说明",
        "corrected_sheet": "修正版附件",
        "approval_rejected": "审批驳回",
        "approval_approved": "审批通过",
    }
    for key in types:
        text = mapping.get(str(key))
        if text:
            labels.append(text)
    if not labels:
        return "管理员修正"
    if len(labels) == 1:
        return labels[0]
    return "多种混合"
