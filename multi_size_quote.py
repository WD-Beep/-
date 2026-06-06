"""多尺寸报价：共用 BOM/单价，按尺寸分别推算用量并 calculate_quote。"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

from piece_area_table import attach_piece_area_calculation
from size_variants import enrich_payload_size_variants, extract_size_variants_from_payload
from structure_usage import apply_structure_usage_hints, tighten_small_bag_usage_amounts

_SIZE_SENSITIVE_RE = re.compile(
    r"面料|里料|外料|内料|主料|辅布|牛津|尼龙|涤纶|帆布|PU|皮料|"
    r"拉链|织带|包边|滚边|捆条|绳|带|zip|webbing",
    re.I,
)


def _is_size_sensitive_row(row: dict[str, Any]) -> bool:
    if row.get("_sheet_usage_lock"):
        return False
    name = str(row.get("name") or "")
    return bool(_SIZE_SENSITIVE_RE.search(name))


def _reset_size_sensitive_usage(items: list[dict[str, Any]]) -> None:
    for row in items:
        if not isinstance(row, dict):
            continue
        if row.get("_sheet_usage_lock"):
            continue
        if not (_is_size_sensitive_row(row) or row.get("_structure_usage_lock")):
            continue
        row["usage"] = "-"
        row["amount"] = 0.0
        row.pop("_structure_usage_lock", None)
        cn = str(row.get("calc_note") or "")
        if any(k in cn for k in ("几何", "面积", "裁片", "长宽高", "结构推算", "系统近似")):
            row["calc_note"] = ""


def _structure_text_from_payload(payload: dict[str, Any]) -> str:
    for key in ("structure_text_snapshot", "structure_text", "structure", "product_structure"):
        val = str(payload.get(key) or "").strip()
        if val:
            return val
    return ""


def _compact_variant_result(full: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "material_total",
        "processing_fee",
        "system_overhead",
        "mold_fee",
        "tiers",
        "detail_rows",
        "items",
        "cost_bridge",
        "default_tier",
        "piece_area_calculation",
        "product_size",
        "product_size_text",
        "pricing_gate",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in full:
            out[k] = copy.deepcopy(full[k])
    return out


def calculate_quote_with_size_variants(
    payload: dict[str, Any],
    calculate_quote_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """单尺寸走原逻辑；多尺寸分别计算并写入 size_variants。"""
    if not isinstance(payload, dict):
        return calculate_quote_fn(payload or {})

    variants = extract_size_variants_from_payload(payload)
    if len(variants) < 2:
        return calculate_quote_fn(payload)

    template_items = payload.get("_size_variant_items_template")
    if not isinstance(template_items, list) or not template_items:
        template_items = copy.deepcopy(payload.get("items") or [])

    structure_text = _structure_text_from_payload(payload)
    variant_outputs: list[dict[str, Any]] = []

    for variant in variants:
        v_payload = copy.deepcopy(payload)
        ps = dict(variant.get("product_size") or {})
        v_payload["product_size"] = ps
        if str(variant.get("size_text") or "").strip():
            v_payload["product_size_text"] = str(variant.get("size_text")).strip()
        v_payload["items"] = copy.deepcopy(template_items)
        _reset_size_sensitive_usage(v_payload["items"])
        apply_structure_usage_hints(v_payload["items"], structure_text, product_size=ps)
        tighten_small_bag_usage_amounts(
            v_payload["items"],
            product_size=ps,
            structure_text=structure_text,
        )
        result = calculate_quote_fn(v_payload)
        attach_piece_area_calculation(result)
        variant_outputs.append(
            {
                "label": str(variant.get("label") or "").strip() or str(variant.get("size_text") or "尺寸"),
                "size_text": str(variant.get("size_text") or "").strip(),
                "product_size": ps,
                "quote_result": _compact_variant_result(result),
            }
        )

    primary = copy.deepcopy(variant_outputs[0]["quote_result"])
    primary["size_variants"] = copy.deepcopy(variant_outputs)
    primary["multi_size"] = True
    primary["product_size"] = dict(variant_outputs[0].get("product_size") or {})
    if str(variant_outputs[0].get("size_text") or "").strip():
        primary["product_size_text"] = str(variant_outputs[0].get("size_text")).strip()
    return primary


def prepare_payload_for_multi_size(payload: dict[str, Any]) -> None:
    """解析后注入 size_variants（多尺寸时 product_size 指向第一档）。"""
    enrich_payload_size_variants(payload)
