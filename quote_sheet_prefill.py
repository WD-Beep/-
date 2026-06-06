"""报价记录 / 管理员修正 → 生成报价单表单预填数据。"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Any

from quote_sheet_content import brief_customer_description_for_quote_sheet
from quote_sheet_images import (
    _ROLE_ADMIN,
    _ROLE_ADMIN_CALCULATED,
    _ROLE_SALES,
    load_sheet_product_images,
    merge_product_images_by_priority,
    persist_sheet_product_images,
)
from sales_rep_fields import extract_sales_fields, pick_section_value
from quote_upload_storage import (
    categorize_quote_files,
    get_my_quote_session_detail,
    list_quote_files_for_quote,
    resolve_stored_file_path,
    sales_user_can_access_quote,
)

_DEFAULT_CO = {
    "co_name": "深圳市栢博旅游用品有限公司",
    "co_phone": "0755-28223791",
    "co_addr": "广东省深圳市龙岗区平湖街道宝能智创谷B栋A单元6A01",
}

_MAX_PRODUCT_ROWS = 10

# 客户报价单/PDF 包装列：剔除内部口径词（不影响后台物料明细与计价）
_INTERNAL_PACK_FRAGMENT_RE = re.compile(
    r"系统估算|系统推断|系统推算|系统近似|AI估算|AI推断|本地兜底|推理待核|推断待核",
    re.I,
)
_INTERNAL_PACK_ONLY_RE = re.compile(
    r"^(?:系统估算|系统推断|系统推算|系统近似|AI估算|AI推断|本地兜底|推断|估算|待核|推理待核|—|-|/|\s*)+$",
    re.I,
)
_PACK_QTY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:个|套|条|张|件|只|卷|米|码|㎡|m²)", re.I)
_FOB_SIGNAL_RE = re.compile(r"\bFOB\b", re.I)


def _first_str(*candidates: Any) -> str:
    for value in candidates:
        text = str(value or "").strip()
        if text and text != "-":
            return text
    return ""


def _parse_number(text: Any) -> float | None:
    raw = str(text or "").strip()
    if not raw or raw == "-":
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", raw.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _format_money(n: float) -> str:
    return f"{n:.2f}"


def _compose_size_for_sheet(dims: str, piece_part: str = "") -> str:
    """客户报价单尺寸列：仅成品尺寸，不拼接裁片/部位。"""
    del piece_part
    return _first_str(dims)


def _sanitize_pack_fragment(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw or raw in ("-", "—"):
        return ""
    if _INTERNAL_PACK_ONLY_RE.match(raw):
        return ""
    cleaned = _INTERNAL_PACK_FRAGMENT_RE.sub("", raw).strip()
    cleaned = re.sub(r"^[（(]\s*[)）]\s*", "", cleaned).strip()
    cleaned = re.sub(r"\s*/\s*$", "", cleaned).strip()
    if not cleaned or _INTERNAL_PACK_ONLY_RE.match(cleaned):
        return ""
    return cleaned


def sanitize_customer_pack_display(text: Any) -> str:
    """客户报价单/PDF 包装列：仅保留真实包装描述，禁止内部估算词补位。"""
    raw = str(text or "").strip()
    if not raw or raw in ("-", "—", "/"):
        return ""
    parts = re.split(r"\s*/\s*", raw)
    kept: list[str] = []
    for part in parts:
        frag = _sanitize_pack_fragment(part)
        if frag and frag not in kept:
            kept.append(frag)
    return " / ".join(kept)


def _pack_from_quote_meta(quote: dict[str, Any]) -> str:
    """业务员表/产品元数据中的包装字段（优先于系统估算行）。"""
    for key in (
        "customer_pack",
        "pack_text",
        "packaging_text",
        "packaging",
        "pack",
        "packing",
    ):
        out = sanitize_customer_pack_display(_first_str(quote.get(key)))
        if out:
            return out
    qp = quote.get("quote_params") if isinstance(quote.get("quote_params"), dict) else {}
    for key in ("包装", "包装方式", "packaging", "pack", "packing"):
        out = sanitize_customer_pack_display(_first_str(qp.get(key)))
        if out:
            return out
    sections = quote.get("qp_sections") if isinstance(quote.get("qp_sections"), dict) else {}
    for label in ("包装", "包装方式", "Packaging", "packaging"):
        out = sanitize_customer_pack_display(pick_section_value(sections, label))
        if out:
            return out
    return ""


def _pack_text_from_quote(quote: dict[str, Any]) -> str:
    direct = _pack_from_quote_meta(quote)
    if direct:
        return direct

    rows = quote.get("detail_rows")
    if not isinstance(rows, list):
        return ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        if "包装" not in name and "纸箱" not in name and "胶袋" not in name and "opp" not in name.lower():
            continue
        if row.get("_usage_display_inferred"):
            usage = ""
        else:
            usage = _sanitize_pack_fragment(_first_str(row.get("usage")))
        if row.get("_spec_display_inferred"):
            spec = ""
        else:
            spec = _sanitize_pack_fragment(_first_str(row.get("spec")))
        pieces = [p for p in (spec, usage) if p]
        if pieces:
            deduped: list[str] = []
            for p in pieces:
                if p not in deduped:
                    deduped.append(p)
            return " / ".join(deduped)
        m = _PACK_QTY_RE.search(name)
        if m:
            return m.group(0).strip()
    return ""


def is_fob_quote_for_sheet(quote: dict[str, Any], detail: dict[str, Any] | None = None) -> bool:
    """检测是否应按 FOB 英文报价单模板导出（不改计价）。"""
    if not isinstance(quote, dict):
        return False
    if quote.get("include_fob") is False:
        return False

    product: dict[str, Any] = {}
    if isinstance(detail, dict) and isinstance(detail.get("product"), dict):
        product = detail["product"]

    blob_parts: list[str] = []
    for src in (quote, product):
        if not isinstance(src, dict):
            continue
        for key in (
            "price_type",
            "trade_term",
            "incoterm",
            "quote_term",
            "price_terms",
            "requirements",
            "user_requirements",
            "customer_requirements",
            "remarks",
            "note",
            "structure_text",
            "structure_text_snapshot",
        ):
            val = str(src.get(key) or "").strip()
            if val:
                blob_parts.append(val)
    blob = " ".join(blob_parts)
    if _FOB_SIGNAL_RE.search(blob) or "离岸" in blob:
        return True

    pt = _first_str(quote.get("price_type"), product.get("price_type")).upper()
    if "FOB" in pt:
        return True

    if quote.get("include_fob") is True:
        return True

    tiers = quote.get("tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            if tier.get("fob_price") is not None and str(tier.get("fob_price") or "").strip():
                return True
            if str(tier.get("fob_price_usd_text") or "").strip():
                return True
    return False


def _prepare_quote_for_sheet(quote: dict[str, Any]) -> None:
    """预填前补齐规格/用量/裁片展示字段（不改计价）。"""
    if not isinstance(quote, dict):
        return
    st = str(
        quote.get("structure_text_snapshot") or quote.get("structure_text") or ""
    ).strip()
    ps = quote.get("product_size") if isinstance(quote.get("product_size"), dict) else None
    from material_spec_usage_enricher import enrich_quote_detail_rows

    enrich_quote_detail_rows(quote, structure_text=st, product_size=ps)
    if not quote.get("piece_area_calculation"):
        try:
            from piece_area_table import attach_piece_area_calculation

            attach_piece_area_calculation(quote)
        except Exception:
            pass
    from material_detail_display import enrich_quote_material_detail_display

    enrich_quote_material_detail_display(quote, structure_text=st, product_size=ps)


def _size_text_from_quote(quote: dict[str, Any]) -> str:
    direct = _first_str(
        quote.get("product_size_text"),
        quote.get("size_text"),
    )
    if direct:
        return direct
    ps = quote.get("product_size")
    if isinstance(ps, dict):
        parts = []
        for k in ("length", "width", "height", "L", "W", "H"):
            v = ps.get(k)
            if v is not None and str(v).strip():
                parts.append(str(v).strip())
        if len(parts) >= 3:
            return "×".join(parts[:3]) + "cm"
        if parts:
            return "×".join(parts)
    if isinstance(ps, str):
        return ps.strip()
    return ""


def _tier_has_unit_price(tier: dict[str, Any]) -> bool:
    if not isinstance(tier, dict):
        return False
    for key in (
        "exw_unit_price_text",
        "exw_price_text",
        "unit_exw_text",
        "exw_price",
        "taxed_price",
        "taxed_price_text",
        "cost_before_margin",
        "total_cost",
        "fob_price",
        "fob_price_text",
    ):
        val = tier.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text and text not in ("-", "—"):
            return True
    return False


def _quote_usd_cny_rate(quote: dict[str, Any] | None) -> float:
    q = quote if isinstance(quote, dict) else {}
    for src in (q, q.get("settings") if isinstance(q.get("settings"), dict) else {}):
        if not isinstance(src, dict):
            continue
        for key in ("usd_cny_rate", "usd_rate", "exchange_rate"):
            n = _parse_number(src.get(key))
            if n is not None and n > 1e-6:
                return n
    return 7.15


def _quote_fob_yuan_per_pc(quote: dict[str, Any] | None) -> float:
    q = quote if isinstance(quote, dict) else {}
    for src in (q, q.get("settings") if isinstance(q.get("settings"), dict) else {}):
        if not isinstance(src, dict):
            continue
        for key in ("fob_yuan_per_pc", "fob_addition_per_piece", "fob_addon_yuan"):
            n = _parse_number(src.get(key))
            if n is not None and n >= 0:
                return n
    return 4.0


def _tier_pick_number(tier: dict[str, Any], *keys: str) -> float | None:
    if not isinstance(tier, dict):
        return None
    for key in keys:
        n = _parse_number(tier.get(key))
        if n is not None:
            return n
    return None


def _tier_fob_display_fields(
    tier: dict[str, Any],
    qty_n: float | None,
    quote: dict[str, Any] | None = None,
) -> dict[str, str]:
    """客户 FOB 展示价（与出厂 EXW 分列，不参与出厂单价列）。"""
    empty = {
        "fob_price": "",
        "fob_price_text": "",
        "fob_price_usd": "",
        "fob_price_usd_text": "",
        "fob_total": "",
        "fob_total_usd": "",
    }
    if not isinstance(tier, dict):
        return empty
    fob_rmb = _tier_pick_number(
        tier,
        "fob_price_text",
        "fob_price",
        "fob_unit_price",
        "unit_price_fob",
    )
    fob_usd = _tier_pick_number(
        tier,
        "fob_price_usd",
        "unit_price_usd",
        "price_usd",
        "unitPriceUsd",
        "usd_unit_price",
    )
    usd_text = str(tier.get("fob_price_usd_text") or "").strip()
    if fob_usd is None and usd_text:
        fob_usd = _parse_number(usd_text)
    if fob_rmb is None:
        exw = _tier_pick_number(
            tier,
            "exw_price_text",
            "exw_price",
            "exw_unit_price_text",
            "unit_exw_text",
            "taxed_price_text",
            "taxed_price",
        )
        if exw is None:
            exw = _tier_unit_price_from_tier(tier)
            exw = _parse_number(exw) if exw else None
        if exw is not None:
            fob_rmb = exw + _quote_fob_yuan_per_pc(quote)
    rate = _quote_usd_cny_rate(quote)
    if fob_usd is None and fob_rmb is not None and rate > 1e-6:
        fob_usd = fob_rmb / rate
    fob_total_usd = _tier_pick_number(
        tier,
        "fob_total_usd",
        "total_usd",
        "fob_amount",
        "amount_usd",
        "totalAmountUsd",
        "usd_total",
    )
    out = dict(empty)
    if fob_rmb is not None:
        out["fob_price"] = _format_money(fob_rmb)
        out["fob_total"] = _format_money(qty_n * fob_rmb) if qty_n is not None else ""
    out["fob_price_text"] = str(tier.get("fob_price_text") or "").strip()
    if fob_usd is not None:
        out["fob_price_usd"] = _format_money(fob_usd)
        usd_rounded = _parse_number(out["fob_price_usd"])
        if fob_total_usd is None and qty_n is not None and usd_rounded is not None:
            fob_total_usd = qty_n * usd_rounded
        out["fob_total_usd"] = (
            _format_money(fob_total_usd) if fob_total_usd is not None else ""
        )
    elif fob_total_usd is not None:
        out["fob_total_usd"] = _format_money(fob_total_usd)
    out["fob_price_usd_text"] = usd_text
    return out


def _tier_taxed_unit_price(tier: dict[str, Any]) -> str:
    """客户 PDF「含税价」列：仅读取 tier 含税字段，不回退 EXW。"""
    if not isinstance(tier, dict):
        return ""
    text = str(tier.get("taxed_price_text") or "").strip()
    n = _parse_number(text) if text else None
    if n is not None:
        return _format_money(n)
    n = _parse_number(tier.get("taxed_price"))
    if n is not None:
        return _format_money(n)
    return ""


def _tier_unit_price_from_tier(tier: dict[str, Any]) -> str:
    """从单档 tier 解析出厂/EXW 每件单价（不含 FOB，避免 FOB PDF 误用加价兜底）。"""
    if not isinstance(tier, dict):
        return ""
    for key in ("exw_unit_price_text", "exw_price_text", "unit_exw_text", "taxed_price_text"):
        n = _parse_number(tier.get(key))
        if n is not None:
            return _format_money(n)
    for key in ("exw_price", "taxed_price"):
        n = _parse_number(tier.get(key))
        if n is not None:
            return _format_money(n)
    cost = _parse_number(tier.get("cost_before_margin") or tier.get("total_cost"))
    if cost is not None:
        margin = _parse_number(tier.get("margin_rate"))
        if margin is not None and 0 <= margin < 1:
            return _format_money(cost / max(0.01, 1 - margin))
        return _format_money(cost)
    return ""


def _unit_price_from_sales_checkpoints(quote: dict[str, Any], qty: float | None) -> str:
    if qty is None:
        return ""
    raw = quote.get("sales_sheet_checkpoints")
    if not isinstance(raw, list):
        return ""
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if _parse_number(entry.get("quantity")) != qty:
            continue
        for key in ("computed_exw_quote_pc", "computed_exw_quote_text"):
            n = _parse_number(entry.get(key))
            if n is not None:
                return _format_money(n)
    return ""


def _tier_unit_price(tier: dict[str, Any], quote: dict[str, Any]) -> str:
    """报价单单价：tier → 对账检查点 → 其它档位 → 报价根字段。"""
    price = _tier_unit_price_from_tier(tier)
    if price:
        return price
    qty = _parse_number(tier.get("quantity")) if isinstance(tier, dict) else None
    price = _unit_price_from_sales_checkpoints(quote, qty)
    if price:
        return price
    for cand in _tiers_list(quote):
        price = _tier_unit_price_from_tier(cand)
        if price:
            return price
    for key in ("exw_unit_price_text", "exw_price_text", "exw_price"):
        n = _parse_number(quote.get(key))
        if n is not None:
            return _format_money(n)
    return ""


def _preferred_tier_index(tiers: list[dict[str, Any]]) -> int:
    """与后台报价卡片一致：优先 500 件档，否则取中间档。"""
    for i, tier in enumerate(tiers):
        if _parse_number(tier.get("quantity")) == 500:
            return i
    if len(tiers) >= 2:
        return 1
    return 0


def _resolve_row_tier(
    quote: dict[str, Any],
    variant: dict[str, Any] | None,
    tier_hint: dict[str, Any] | None,
) -> dict[str, Any]:
    hint = tier_hint if isinstance(tier_hint, dict) else {}
    if _tier_has_unit_price(hint):
        return hint
    picked = _pick_primary_tier(quote, variant)
    if _tier_has_unit_price(picked):
        return picked
    qty_hint = _parse_number(hint.get("quantity")) or _parse_number(_tier_qty_text(hint))
    for cand in _tiers_list(quote, variant):
        if qty_hint is not None and _parse_number(cand.get("quantity")) == qty_hint and _tier_has_unit_price(cand):
            return cand
    for cand in _tiers_list(quote, variant):
        if _tier_has_unit_price(cand):
            return cand
    return picked or hint


def _tier_qty_text(tier: dict[str, Any]) -> str:
    if not isinstance(tier, dict):
        return ""
    qn = _parse_number(tier.get("quantity"))
    if qn is not None:
        return str(int(qn) if qn == int(qn) else qn)
    return _first_str(tier.get("quantity_text"), tier.get("quantity"))


def _tiers_list(quote: dict[str, Any], variant: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if isinstance(variant, dict):
        qr = variant.get("quote_result")
        if isinstance(qr, dict):
            raw = qr.get("tiers")
            if isinstance(raw, list):
                return [t for t in raw if isinstance(t, dict)]
        raw = variant.get("tiers")
        if isinstance(raw, list):
            return [t for t in raw if isinstance(t, dict)]
    raw = quote.get("tiers")
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]
    return []


def _pick_primary_tier(quote: dict[str, Any], variant: dict[str, Any] | None = None) -> dict[str, Any]:
    """单款产品多档数量报价时只取一档（首选/默认档），不展开为多行。"""
    tiers = _tiers_list(quote, variant)
    if not tiers:
        return {}

    scope = variant if isinstance(variant, dict) else quote
    for key in ("selected_tier_index", "primary_tier_index", "tier_index"):
        idx = _parse_number(scope.get(key) if isinstance(scope, dict) else None)
        if idx is not None and 0 <= int(idx) < len(tiers):
            return tiers[int(idx)]

    dt = quote.get("default_tier")
    if isinstance(dt, dict):
        ref = _parse_number(dt.get("quantity"))
        if ref is not None:
            for tier in tiers:
                if _parse_number(tier.get("quantity")) == ref:
                    return tier
        if dt.get("exw_price") is not None or dt.get("exw_price_text"):
            return dt

    cb = quote.get("cost_bridge")
    if isinstance(cb, dict):
        ref = _parse_number(cb.get("tier_quantity_ref"))
        if ref is not None:
            for tier in tiers:
                if _parse_number(tier.get("quantity")) == ref:
                    return tier

    pref_ix = _preferred_tier_index(tiers)
    pref = tiers[pref_ix]
    if _tier_has_unit_price(pref):
        return pref

    settings = quote.get("settings")
    if isinstance(settings, dict):
        quantities = settings.get("quantities")
        if isinstance(quantities, list) and quantities:
            q0 = _parse_number(quantities[0])
            if q0 is not None:
                for tier in tiers:
                    if _parse_number(tier.get("quantity")) == q0:
                        return tier

    for tier in tiers:
        if _tier_has_unit_price(tier):
            return tier
    return tiers[pref_ix] if tiers else {}


def _variant_context(variant: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(variant, dict):
        return {}
    qr = variant.get("quote_result")
    if isinstance(qr, dict):
        return {**variant, **qr}
    return variant


def _source_row_from_obj(obj: dict[str, Any] | None) -> int | None:
    if not isinstance(obj, dict):
        return None
    for key in ("source_row", "sheet_row", "excel_row", "row_index"):
        parsed = _parse_number(obj.get(key))
        if parsed is not None and parsed >= 0:
            return int(parsed)
    return None


def _product_line_specs(quote: dict[str, Any]) -> list[dict[str, Any]]:
    """每个真实产品/尺寸变体一行；同一款的多个数量档不展开为多行。"""
    specs: list[dict[str, Any]] = []
    variants = quote.get("size_variants")
    if isinstance(variants, list) and len(variants) > 1:
        for variant in variants[:_MAX_PRODUCT_ROWS]:
            if not isinstance(variant, dict):
                continue
            tier = _pick_primary_tier(quote, variant)
            specs.append(
                {
                    "tier": tier,
                    "variant": variant,
                    "source_row": _source_row_from_obj(variant) or _source_row_from_obj(tier),
                }
            )
        if specs:
            return specs

    tier = _pick_primary_tier(quote, None)
    return [
        {
            "tier": tier,
            "variant": None,
            "source_row": _source_row_from_obj(quote) or _source_row_from_obj(tier),
        }
    ]


def _pick_image_for_line(image_map: dict[int, str], row_index: int, product_count: int) -> str:
    url = image_map.get(row_index) or ""
    if url:
        return url
    if product_count == 1 and image_map:
        return image_map.get(0) or next(iter(image_map.values()), "")
    return ""


def _product_row(
    *,
    quote: dict[str, Any],
    tier: dict[str, Any] | None,
    row_index: int,
    image_map: dict[int, str],
    product_count: int,
    variant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    vquote = _variant_context(variant) if isinstance(variant, dict) else quote
    t = _resolve_row_tier(quote, variant, tier if isinstance(tier, dict) else None)
    name = _first_str(vquote.get("product_name"), quote.get("product_name"), "产品")
    dims = _size_text_from_quote(vquote) or _size_text_from_quote(quote)
    if isinstance(variant, dict):
        vsize = _first_str(variant.get("size_label"), variant.get("product_size_text"))
        if vsize:
            dims = vsize
    size = _compose_size_for_sheet(dims)
    pack_raw = _pack_text_from_quote(vquote) or _pack_text_from_quote(quote)
    pack = sanitize_customer_pack_display(pack_raw)
    qty = _tier_qty_text(t)
    price = _tier_unit_price(t, quote)
    qty_n = _parse_number(qty)
    price_n = _parse_number(price)
    total = ""
    if qty_n is not None and price_n is not None:
        total = _format_money(qty_n * price_n)
    fob_fields = _tier_fob_display_fields(t, qty_n, quote)
    taxed_price = _tier_taxed_unit_price(t) if isinstance(t, dict) else ""
    rows_for_desc: list[dict[str, Any]] | None = None
    st_for_desc = ""
    for src in (vquote, quote):
        if not isinstance(src, dict):
            continue
        if rows_for_desc is None:
            for key in ("detail_rows", "items"):
                dr = src.get(key)
                if isinstance(dr, list) and dr:
                    rows_for_desc = [r for r in dr if isinstance(r, dict)]
                    break
        if not st_for_desc:
            st_for_desc = str(
                src.get("structure_text_snapshot") or src.get("structure_text") or ""
            ).strip()
    desc = brief_customer_description_for_quote_sheet(
        product_name=name,
        detail_rows=rows_for_desc,
        structure_text=st_for_desc,
    )
    return {
        "line_order": row_index,
        "name": name,
        "size": size,
        "desc": desc,
        "pack": pack,
        "qty": qty,
        "price": price,
        "total": total,
        "note": "",
        "taxed_price": taxed_price,
        "taxed_price_text": str(t.get("taxed_price_text") or "").strip() if isinstance(t, dict) else "",
        "image_data_url": _pick_image_for_line(image_map, row_index, product_count),
        **fob_fields,
    }


def _rows_from_quote(quote: dict[str, Any], image_map: dict[int, str]) -> list[dict[str, Any]]:
    _prepare_quote_for_sheet(quote)
    specs = _product_line_specs(quote)
    product_count = max(1, len(specs))
    return [
        _product_row(
            quote=quote,
            tier=spec.get("tier"),
            row_index=ix,
            image_map=image_map,
            product_count=product_count,
            variant=spec.get("variant"),
        )
        for ix, spec in enumerate(specs)
    ]


def _image_blob_from_item(item: dict[str, Any]) -> bytes:
    b64 = str(item.get("data_base64") or "").strip()
    if b64:
        try:
            return base64.b64decode(b64, validate=True)
        except Exception:
            return b""
    url = str(item.get("data_url") or "").strip()
    if "," in url and url.startswith("data:"):
        try:
            return base64.b64decode(url.split(",", 1)[1], validate=True)
        except Exception:
            return b""
    return b""


def _best_trusted_product_image_url(candidates: list[dict[str, Any]]) -> str:
    """单款产品：仅在已标记/可信来源的产品图中选得分最高的一张。"""
    from quote_sheet_content import filter_product_image_items, product_image_score

    trusted = filter_product_image_items(candidates or [])
    if not trusted:
        return ""
    best = max(trusted, key=product_image_score)
    return _first_str(best.get("data_url"))


def _quote_images_from_object(quote: dict[str, Any]) -> list[dict[str, Any]]:
    raw = quote.get("product_row_images")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for seq, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        url = _first_str(item.get("data_url"), item.get("image_url"), item.get("imageUrl"))
        if not url.startswith("data:"):
            continue
        prod_ix = item.get("product_line", item.get("line_order"))
        if prod_ix is None:
            prod_ix = item.get("row_index", seq)
        role = str(item.get("image_role") or item.get("role") or "").strip().lower()
        if not role and not item.get("product_image"):
            continue
        if role and role not in (
            "product_main",
            "product_style",
            "style_image",
            "bag_image",
            "agent_product",
            "product_row",
        ):
            continue
        out.append(
            {
                "row_index": int(prod_ix),
                "product_line": int(prod_ix),
                "data_url": url,
                "mime_type": str(item.get("mime_type") or "image/png"),
                "image_role": role or "agent_product",
                "from_agent_product": True,
            }
        )
    return out


def _persist_sheet_images_if_needed(
    quote_uid: str,
    role: str,
    file_rec: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    images = load_sheet_product_images(quote_uid, role)
    if images or not file_rec:
        return images
    path = resolve_stored_file_path(str(file_rec.get("stored_path") or ""))
    if not path or path.suffix.lower() != ".xlsx":
        return images
    persist_sheet_product_images(
        quote_uid,
        role,
        path.read_bytes(),
        original_name=str(file_rec.get("original_name") or ""),
    )
    return load_sheet_product_images(quote_uid, role)


def _load_images_for_prefill(
    quote_uid: str,
    *,
    quote: dict[str, Any],
    files: list[dict[str, Any]] | None,
    prefer_admin: bool,
    product_specs: list[dict[str, Any]],
) -> dict[int, str]:
    cat = categorize_quote_files(list(files or []))
    sales_list = cat.get("sales") if isinstance(cat.get("sales"), list) else []
    sales_rec = sales_list[-1] if sales_list else None
    admin_rec = cat.get("admin_corrected")
    admin_calc_rec = cat.get("admin_calculated")

    sales_images = _persist_sheet_images_if_needed(quote_uid, _ROLE_SALES, sales_rec)
    admin_calc_images = _persist_sheet_images_if_needed(
        quote_uid, _ROLE_ADMIN_CALCULATED, admin_calc_rec
    )
    admin_images: list[dict[str, Any]] = []
    if prefer_admin:
        admin_images = _persist_sheet_images_if_needed(quote_uid, _ROLE_ADMIN, admin_rec)

    product_count = max(1, len(product_specs))
    product_source_rows = [spec.get("source_row") for spec in product_specs]

    image_map = merge_product_images_by_priority(
        sales_images=sales_images,
        admin_calculated_images=admin_calc_images,
        quote_images=_quote_images_from_object(quote),
        admin_images=admin_images if prefer_admin else None,
        product_count=product_count,
        product_source_rows=product_source_rows,
    )
    if product_count == 1 and not image_map.get(0):
        pool: list[dict[str, Any]] = []
        if prefer_admin:
            pool.extend(admin_images)
        pool.extend(_quote_images_from_object(quote))
        pool.extend(sales_images)
        pool.extend(admin_calc_images)
        fallback = _best_trusted_product_image_url(pool)
        if fallback:
            image_map[0] = fallback
    return image_map


def _resolve_quote_for_source(
    detail: dict[str, Any],
    source: str,
) -> tuple[dict[str, Any], bool]:
    fb = detail.get("admin_feedback") if isinstance(detail.get("admin_feedback"), dict) else {}
    src = str(source or "record").strip().lower()
    if src in ("admin_corrected", "admin", "correction"):
        corr = fb.get("admin_corrected_quote_result")
        if isinstance(corr, dict) and corr:
            return corr, True
    quote = detail.get("latest_quote_result")
    if isinstance(quote, dict) and quote:
        return quote, False
    return {}, False


def _quote_param_sections(*sources: dict[str, Any] | None) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        qp = src.get("quote_params")
        if not isinstance(qp, dict):
            continue
        for sec in qp.values():
            if isinstance(sec, dict):
                sections.append(sec)
    return sections


def _pick_from_qp_sections(sections: list[dict[str, Any]], *keys: str) -> str:
    for sec in sections:
        val = pick_section_value(sec, *keys)
        if val:
            return val
    return ""


def _meta_from_detail(detail: dict[str, Any], quote: dict[str, Any]) -> dict[str, str]:
    qp_sections = _quote_param_sections(detail, quote)
    sales_fields = extract_sales_fields(quote.get("quote_params"))

    from quote_sheet_meta import sanitize_customer_quote_no

    quote_no = sanitize_customer_quote_no(
        _first_str(
            quote.get("quote_no"),
            quote.get("quote_sheet_no"),
            _pick_from_qp_sections(qp_sections, "报价编号", "quote_no", "编号"),
            quote.get("quote_id")
            if str(quote.get("quote_id") or "").strip()
            and not str(quote.get("quote_id") or "").strip().startswith("calc-")
            else "",
            detail.get("quote_id")
            if str(detail.get("quote_id") or "").strip()
            and not str(detail.get("quote_id") or "").strip().startswith("calc-")
            else "",
        ),
        quote=quote,
        detail=detail,
    )
    seller = _first_str(
        sales_fields.get("sales_name"),
        _pick_from_qp_sections(
            qp_sections,
            "业务员姓名",
            "业务员",
            "salesperson",
            "sales_name",
        ),
        detail.get("sales_user_name"),
        quote.get("sales_name"),
        sales_fields.get("sales_display"),
    )
    seller_email = _first_str(
        quote.get("seller_email"),
        quote.get("sales_email"),
        _pick_from_qp_sections(qp_sections, "E-mail", "email", "邮箱", "电子邮箱", "业务员邮箱"),
    )
    date_raw = _first_str(
        detail.get("approved_at"),
        detail.get("updated_at"),
        quote.get("saved_at"),
        quote.get("quoted_at"),
        _pick_from_qp_sections(qp_sections, "报价时间", "报价日期", "quote_date"),
    )
    quote_date = ""
    if date_raw:
        quote_date = date_raw.replace("Z", "").split("T")[0][:10]
    if not quote_date:
        quote_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    cust_name = _first_str(
        quote.get("customer_name"),
        quote.get("cust_name"),
        _pick_from_qp_sections(
            qp_sections,
            "客户名称",
            "客户",
            "customer_name",
            "cust_name",
        ),
    )
    cust_contact = _first_str(
        quote.get("customer_contact"),
        quote.get("cust_contact"),
        _pick_from_qp_sections(
            qp_sections,
            "客户联系人",
            "customer_contact",
            "cust_contact",
        ),
    )
    cust_phone = _first_str(
        quote.get("customer_phone"),
        quote.get("cust_phone"),
        _pick_from_qp_sections(
            qp_sections,
            "客户联系电话",
            "联系电话",
            "customer_phone",
            "cust_phone",
        ),
    )
    cust_addr = _first_str(
        quote.get("customer_address"),
        quote.get("cust_addr"),
        _pick_from_qp_sections(
            qp_sections,
            "客户公司地址",
            "公司地址",
            "客户地址",
            "customer_address",
            "cust_addr",
        ),
    )

    return {
        "co_name": _first_str(_DEFAULT_CO.get("co_name")),
        "co_phone": _first_str(_DEFAULT_CO.get("co_phone")),
        "co_addr": _first_str(_DEFAULT_CO.get("co_addr")),
        "quote_no": quote_no,
        "seller_contact": seller,
        "seller_email": seller_email,
        "cust_name": cust_name,
        "cust_contact": cust_contact,
        "cust_phone": cust_phone,
        "cust_addr": cust_addr,
        "quote_date_iso": quote_date,
    }




def build_quote_sheet_prefill_payload(
    quote_series_uid: str,
    sales_user_id: str,
    *,
    source: str = "record",
) -> dict[str, Any] | None:
    uid = str(quote_series_uid or "").strip()
    sid = str(sales_user_id or "").strip()
    if not uid or not sid or not sales_user_can_access_quote(uid, sid):
        return None

    detail = get_my_quote_session_detail(uid, sid)
    if not detail:
        return None

    quote, used_admin = _resolve_quote_for_source(detail, source)
    if not quote:
        return None

    product_specs = _product_line_specs(quote)
    files = list_quote_files_for_quote(uid)
    image_map = _load_images_for_prefill(
        uid,
        quote=quote,
        files=files,
        prefer_admin=used_admin,
        product_specs=product_specs,
    )
    rows = _rows_from_quote(quote, image_map)
    from quote_sheet_meta import build_prefill_meta

    meta = build_prefill_meta(
        detail,
        quote,
        sales_user_id=sid,
        inferred=_meta_from_detail(detail, quote),
    )

    usd_rate = quote.get("usd_cny_rate") or quote.get("settings", {}).get("usd_cny_rate")
    fob_yuan = quote.get("fob_yuan_per_pc") or quote.get("settings", {}).get("fob_yuan_per_pc")

    product_obj = detail.get("product") if isinstance(detail.get("product"), dict) else {}
    fob_quote = is_fob_quote_for_sheet(quote, detail)
    return {
        "ok": True,
        "source": "admin_corrected" if used_admin else "record",
        "quote_series_uid": uid,
        "meta": meta,
        "rows": rows,
        "usd_cny_rate": usd_rate,
        "fob_yuan_per_pc": fob_yuan,
        "product_name": _first_str(quote.get("product_name"), detail.get("product_name")),
        "fob_quote": fob_quote,
        "suggested_export_lang": "en" if fob_quote else "cn",
        "include_fob": quote.get("include_fob"),
        "price_type": _first_str(quote.get("price_type"), product_obj.get("price_type")),
    }


def map_quote_record_to_quotation_form(record: dict[str, Any]) -> dict[str, Any]:
    return record if isinstance(record, dict) else {}


def map_admin_correction_to_quotation_form(record: dict[str, Any]) -> dict[str, Any]:
    return map_quote_record_to_quotation_form(record)
