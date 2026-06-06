"""后台 BOM 编辑后重算并入库（新版本）。"""
from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from quote_engine import calculate_quote

_QTY_RE = re.compile(r"(\d+)\s*个")
_MARGIN_RE = re.compile(r"([\d.]+)\s*%?")
_BOM_MEASURE_RE = re.compile(
    r"^\s*"
    r"(?P<sign>[+-])?"
    r"(?P<num>"
    r"\d+\.\d+"
    r"|\d+"
    r"|\.\d+"
    r")"
    r"(?P<unit>.*)?"
    r"\s*$",
)
_KNOWN_LATIN_UNIT_TOKENS = frozenset(
    {
        "m",
        "cm",
        "mm",
        "kg",
        "g",
        "mg",
        "pcs",
        "pc",
        "pair",
        "yd",
        "yd2",
        "m2",
    }
)
_COUNT_BASED_UNIT_TOKENS = frozenset(
    {
        "个",
        "只",
        "件",
        "套",
        "条",
        "对",
        "pcs",
        "pc",
        "piece",
        "pair",
    }
)


def _is_empty_bom_usage(text: str) -> bool:
    s = str(text or "").strip()
    return not s or s in ("-", "—")


def _unit_text_candidates(unit: str, unit_price: str) -> list[str]:
    out: list[str] = []
    for raw in (unit, unit_price):
        s = str(raw or "").strip()
        if not s or s in ("-", "—"):
            continue
        out.append(s)
        m = _BOM_MEASURE_RE.match(s)
        if m:
            tail = str(m.group("unit") or "").strip()
            if tail:
                out.append(tail)
        for sep in ("/", "／"):
            if sep in s:
                out.append(s.split(sep)[-1].strip())
        cleaned = re.sub(r"^[元￥$€]+/?", "", s).strip()
        if cleaned:
            out.append(cleaned)
    return out


def is_count_based_unit(unit: str = "", unit_price: str = "") -> bool:
    """计件类单位：个/只/件/套/条/对/pcs/pc/piece/pair。"""
    for cand in _unit_text_candidates(unit, unit_price):
        lower = cand.lower()
        for tok in _COUNT_BASED_UNIT_TOKENS:
            if tok in lower:
                return True
    return False


def _default_count_usage(unit: str, unit_price: str) -> str:
    for tok in ("个", "只", "件", "套", "条", "对"):
        if not is_count_based_unit(unit, unit_price):
            break
        for cand in _unit_text_candidates(unit, unit_price):
            if tok in cand:
                return f"1{tok}"
    return "1"


def parse_bom_measure_value(text: str) -> float | None:
    """从单价/用量文本解析 leading 数值；非法格式返回 None。"""
    err = _validate_bom_measure_text(text, allow_empty=True)
    if err:
        return None
    s = str(text or "").strip()
    if not s or s in ("-", "—"):
        return None
    m = _BOM_MEASURE_RE.match(s)
    if not m:
        return None
    sign = m.group("sign") or ""
    num_str = m.group("num") or ""
    try:
        val = float(f"{sign}{num_str}")
    except (TypeError, ValueError):
        return None
    if not (val == val and abs(val) != float("inf")):  # NaN / inf
        return None
    return val


def _validate_bom_measure_text(text: str, *, allow_empty: bool = False) -> str | None:
    """返回错误文案；合法则 None。允许「数字 + 单位」，拒绝 abc / 1abc / 2..3 等。"""
    s = str(text or "").strip()
    if not s or s in ("-", "—"):
        return None if allow_empty else "不能为空"
    m = _BOM_MEASURE_RE.match(s)
    if not m:
        return "须为有效数字或「数字+单位」"
    sign = m.group("sign") or ""
    num_str = m.group("num") or ""
    unit = str(m.group("unit") or "")
    if ".." in num_str or num_str.count(".") > 1:
        return "须为有效数字或「数字+单位」"
    try:
        val = float(f"{sign}{num_str}")
    except (TypeError, ValueError):
        return "须为有效数字或「数字+单位」"
    if not (val == val and abs(val) != float("inf")):
        return "须为有效数字或「数字+单位」"
    if re.search(r"\d", unit):
        return "须为有效数字或「数字+单位」"
    letters_only = re.sub(r"[\s.\-/²°%￥$€]", "", unit)
    if letters_only and re.fullmatch(r"[a-zA-Z]+", letters_only):
        if letters_only.lower() not in _KNOWN_LATIN_UNIT_TOKENS:
            return "须为有效数字或「数字+单位」"
    return None


def _parse_quantities_from_text(text: str, fallback: list[int]) -> list[int]:
    nums = [int(m.group(1)) for m in _QTY_RE.finditer(str(text or ""))]
    out = [n for n in nums if n > 0]
    return out or list(fallback)


def _parse_margin_rate(text: str, fallback: float) -> float:
    s = str(text or "").strip()
    if not s:
        return fallback
    m = _MARGIN_RE.search(s.replace("，", ","))
    if not m:
        return fallback
    try:
        v = float(m.group(1))
    except (TypeError, ValueError):
        return fallback
    if v > 1:
        v = v / 100.0
    if 0 <= v < 1:
        return v
    return fallback


def validate_bom_edit_body(body: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """返回 (全局错误列表, 字段错误 field_key -> message)。"""
    global_errs: list[str] = []
    field_errs: dict[str, str] = {}
    if not isinstance(body, dict):
        return ["请求体须为 JSON 对象。"], field_errs

    product = body.get("product")
    if not isinstance(product, dict):
        global_errs.append("缺少 product 对象。")
        product = {}

    pname = str(product.get("product_name") or "").strip()
    if not pname:
        field_errs["product.product_name"] = "产品名称不能为空"

    items = body.get("items")
    if not isinstance(items, list) or not items:
        global_errs.append("至少保留一行物料。")
        return global_errs, field_errs

    active = 0
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            field_errs[f"items.{i}"] = "行数据无效"
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            field_errs[f"items.{i}.name"] = "物料名称不能为空"
            continue
        active += 1
        unit = str(raw.get("unit") or "").strip()
        up = str(raw.get("unit_price") or "").strip()
        usage = str(raw.get("usage") or "").strip()
        count_based = is_count_based_unit(unit, up)
        up_err = _validate_bom_measure_text(up, allow_empty=False)
        if up_err:
            field_errs[f"items.{i}.unit_price"] = f"单价{up_err}"
        usage_err = _validate_bom_measure_text(usage, allow_empty=count_based)
        if usage_err:
            field_errs[f"items.{i}.usage"] = f"用量{usage_err}"

    if active == 0 and not global_errs:
        global_errs.append("至少保留一行有效物料。")
    return global_errs, field_errs


def _normalize_items(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        unit = str(raw.get("unit") or "").strip()
        unit_price = str(raw.get("unit_price") or "-").strip() or "-"
        usage = str(raw.get("usage") or "-").strip() or "-"
        if is_count_based_unit(unit, unit_price) and _is_empty_bom_usage(usage):
            usage = _default_count_usage(unit, unit_price)
        row: dict[str, Any] = {
            "name": name,
            "spec": str(raw.get("spec") or "-").strip() or "-",
            "usage": usage,
            "unit_price": unit_price,
        }
        note = str(raw.get("calc_note") or raw.get("calc_method") or "").strip()
        if note:
            row["calc_note"] = note
            row["calc_method"] = note
        src = str(raw.get("source") or "").strip()
        if src:
            row["source"] = src
        if bool(raw.get("admin_confirm_ai_price")):
            row["source"] = "admin"
            row["unit_price_ai"] = False
            row["usage_ai"] = False
            row["amount_ai"] = False
            row["pricing_review_required"] = False
            row["admin_confirmed_price"] = True
        elif bool(raw.get("pricing_review_required")) or bool(raw.get("unit_price_ai")):
            row["pricing_review_required"] = bool(raw.get("pricing_review_required"))
            row["unit_price_ai"] = bool(raw.get("unit_price_ai"))
            row["usage_ai"] = bool(raw.get("usage_ai"))
        if unit and row["unit_price"] in ("-", "—", ""):
            row["unit_price"] = unit
        out.append(row)
    return out


def build_calc_payload_from_saved_quote(
    quote: dict[str, Any],
    *,
    product: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """从归档 quote_json + 编辑内容组装 calculate_quote 入参。"""
    q = quote if isinstance(quote, dict) else {}
    settings = q.get("settings") if isinstance(q.get("settings"), dict) else {}
    tiers = q.get("tiers") if isinstance(q.get("tiers"), list) else []
    fallback_qty = [300, 500, 1000]
    if tiers:
        fb = []
        for t in tiers:
            if isinstance(t, dict):
                try:
                    n = int(t.get("quantity") or 0)
                except (TypeError, ValueError):
                    n = 0
                if n > 0:
                    fb.append(n)
        if fb:
            fallback_qty = fb

    qty_text = str(product.get("quantities_text") or product.get("quantity_text") or "").strip()
    quantities = _parse_quantities_from_text(qty_text, fallback_qty)
    if isinstance(q.get("quantities"), list) and q.get("quantities") and not qty_text:
        try:
            quantities = [int(x) for x in q["quantities"] if int(x) > 0]
        except (TypeError, ValueError):
            pass

    margin_fb = float(settings.get("gross_margin_rate") or q.get("gross_margin_rate") or 0.35)
    margin_rate = _parse_margin_rate(
        str(product.get("margin_text") or product.get("margin_rate_text") or ""),
        margin_fb,
    )

    price_type = str(product.get("price_type") or "").strip().lower()
    include_fob = q.get("include_fob", True)
    if price_type in ("exw", "exw_vat", "exw-cost"):
        include_fob = False
    elif price_type in ("fob", "fob_shenzhen"):
        include_fob = True
    elif product.get("include_fob") is not None:
        include_fob = bool(product.get("include_fob"))

    payload: dict[str, Any] = {
        "product_name": str(product.get("product_name") or q.get("product_name") or "").strip(),
        "items": items,
        "quantities": quantities,
        "gross_margin_rate": margin_rate,
        "include_fob": include_fob,
        "mold_fee": q.get("mold_fee", settings.get("mold_fee")),
        "processing_fee": q.get("processing_fee", settings.get("processing_fee")),
        "system_overhead": q.get("system_overhead", settings.get("system_overhead")),
        "fob_addition": q.get("fob_addition", settings.get("fob_addition_per_piece")),
    }
    if q.get("management_loss_rate") is not None:
        payload["management_loss_rate"] = q.get("management_loss_rate")
    if q.get("system_overhead_fixed") is not None:
        payload["system_overhead_fixed"] = q.get("system_overhead_fixed")
    return payload


def merge_recalc_into_quote(base: dict[str, Any], calc: dict[str, Any], *, calc_quote_id: str) -> dict[str, Any]:
    """保留归档中的扩展字段，覆盖核算结果。"""
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(calc, dict):
        return out
    for key in (
        "material_total",
        "material_total_text",
        "system_cost",
        "system_cost_text",
        "detail_rows",
        "data_notice",
        "summary_rows",
        "tiers",
        "settings",
        "markdown",
        "generated_at",
        "include_fob",
    ):
        if key in calc:
            out[key] = calc[key]
    if calc.get("product_name"):
        out["product_name"] = calc["product_name"]
    out["quote_id"] = calc_quote_id
    out["intent"] = "ADMIN_BOM_EDIT"
    return out


def apply_product_meta_to_quote(quote: dict[str, Any], product: dict[str, Any]) -> None:
    """写入非核算字段（展示用）。"""
    if not isinstance(quote, dict) or not isinstance(product, dict):
        return
    if product.get("product_name"):
        quote["product_name"] = str(product["product_name"]).strip()
    for key, qkey in (
        ("product_model", "product_model"),
        ("product_size_text", "product_size_text"),
        ("structure_text", "structure_text"),
    ):
        val = str(product.get(key) or "").strip()
        if val:
            quote[qkey] = val
            if qkey == "structure_text":
                quote["structure_text_snapshot"] = val
    if product.get("include_tax") is not None:
        quote["include_tax"] = bool(product["include_tax"])
    qty_text = str(product.get("quantities_text") or "").strip()
    if qty_text:
        quote["quantity_text"] = qty_text


def admin_recalc_and_save_bom(
    quote_uid: str,
    body: dict[str, Any],
    *,
    sheet_original_name: str = "",
    admin_actor: str = "admin",
) -> dict[str, Any]:
    """校验 → 重算 → 新版本入库 → 返回 admin bundle。"""
    from quote_upload_storage import (
        get_saved_quote_admin_bundle,
        mark_admin_visual_correction_pending,
        save_quote_calculation,
    )

    global_errs, field_errs = validate_bom_edit_body(body)
    if global_errs or field_errs:
        return {
            "ok": False,
            "error": "validation_failed",
            "message": global_errs[0] if global_errs else "请修正标红字段。",
            "global_errors": global_errs,
            "field_errors": field_errs,
        }

    bundle = get_saved_quote_admin_bundle(quote_uid)
    if not bundle:
        return {"ok": False, "error": "not_found", "message": "报价不存在。"}

    quote = bundle.get("quote") if isinstance(bundle.get("quote"), dict) else {}
    old_quote_snapshot = copy.deepcopy(quote)
    old_items = list(bundle.get("items") or [])
    product = body.get("product") if isinstance(body.get("product"), dict) else {}
    items = _normalize_items(body.get("items") or [])

    payload = build_calc_payload_from_saved_quote(quote, product=product, items=items)
    calc = calculate_quote(payload)
    calc_id = str(uuid.uuid4())
    merged = merge_recalc_into_quote(quote, calc, calc_quote_id=calc_id)
    apply_product_meta_to_quote(merged, product)

    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    sheet_nm = sheet_original_name or str(meta.get("sheet_original_name") or "").strip()
    actor = str(body.get("reviewed_by") or admin_actor or "admin").strip() or "admin"

    save_quote_calculation(
        quote_uid=quote_uid,
        calc_quote_id=calc_id,
        sheet_original_display_name=sheet_nm,
        uploaded_sheet=None,
        quote_result=merged,
    )
    mark_admin_visual_correction_pending(quote_uid, actor)

    from quote_correction_learning import capture_learning_from_bom_save

    learning_status = capture_learning_from_bom_save(
        quote_uid,
        old_items=old_items,
        new_items=items,
        quote=merged,
        old_quote=old_quote_snapshot,
        new_product=product,
        corrected_by=actor,
    )

    fresh = get_saved_quote_admin_bundle(quote_uid)
    out: dict[str, Any] = {
        "ok": True,
        "message": "BOM 已保存，报价金额已更新",
        "calc_quote_id": calc_id,
        "bundle": fresh,
        "quote": merged,
        "learning_status": learning_status.to_dict(),
    }
    if not learning_status.ok:
        out["warning"] = "BOM 已保存，但修正历史未完整记录，请查看 learning_status"
    return out
