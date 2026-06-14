"""Parse the structured "需求表(填写区)" template used by the business.

The template is NOT a BOM table. It is a fixed layout with seven labelled
sections (A. 客户与报价信息 / B. 产品规格 / C. 材料与配件 / D. 工艺 /
E. 模具与开料成本 / F. 数量阶梯 / G. 包装与装箱). Each section has a header
row followed by a single value row. Materials are spread across section C as
a wide row (外料 / 里料 / 加固辅料 / 拉链 / 扣具 / 织带 / 绳带 …) instead of
being listed one-per-row. Section B's "结构说明" cell is free-form Chinese
prose that often embeds extra material names and inline prices like
"3.2oz DCH（450元/码）".

This parser converts that template into a normalised view that downstream
code (price KB lookup, LLM completion, quote engine) can consume.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

from material_row_dedupe import _mentions_dch_or_dcf, _mentions_xpac
from structure_usage import piece_count_usage_from_cell_note
from sheet_parser import (
    SheetParseError,
    detect_section_marker,
    normalize_rows,
    parse_piece_count_from_usage,
    parse_rows_from_bytes,
    parse_sheet_xml_rows,
    parse_xls_all_sheets_normalized,
    read_sheet_entries,
    read_shared_strings,
    row_get,
    row_is_quantity_tier_header,
    row_looks_like_horizontal_param_header,
    split_quantity_from_material_name,
)


SECTION_LETTERS = ("A", "B", "C", "D", "E", "F", "G")


# Map fuzzy header tokens we see in section C to canonical material roles.
# Keys are normalised header tokens (lower-cased, brackets removed, no
# whitespace) and values are the role label we attach to extracted materials.
SECTION_C_ROLE_MAP: dict[str, str] = {
    "外料": "外料",
    "外料标准名编码": "外料",
    "里料": "里料",
    "里料标准名编码": "里料",
    "加固辅料": "辅料",
    "加固辅料多选": "辅料",
    "拉链类型": "拉链",
    "拉头类型": "拉头",
    "扣具等级": "扣具",
    "肩带织带类型": "肩带",
    "肩带/织带类型": "肩带",
    "肩带织带": "肩带",
    "织带": "织带",
    "织带1": "织带",
    "织带2": "织带",
    "绳带": "绳带",
    "拉片": "拉片",
    "拉片类型": "拉片",
    "内部网袋": "辅料",
    "内里网袋": "辅料",
    "盖内网袋": "辅料",
    "内袋": "辅料",
}

# Headers in section C that are descriptive (color, length, level …) but do
# not themselves point to a purchasable material. We still capture their
# values for context but never emit them as material rows.
SECTION_C_NON_MATERIAL_HEADERS = {
    "外料颜色",
    "里料颜色",
    "拉链颜色",
    "防水等级",
    "肩带长度",
    "肩带长度cm",
}


# Inline price pattern: catches "(450元/码)" / "（240元/码）" / ", 14元/码" /
# "用量1.5码,0.55元/码" style fragments.
INLINE_PRICE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*元?\s*(?:/|每)\s*(码²|码|个|套|件|条|米|m|y|pcs|pc|pair|set|hset)",
    re.IGNORECASE,
)

EXCEL_ERROR_VALUES = {
    "#div/0!",
    "#n/a",
    "#name?",
    "#null!",
    "#num!",
    "#ref!",
    "#value!",
}


def wants_fob_from_price_type(value: Any) -> bool:
    """A 区「价格类型」：仅当单元格文字里明确出现 FOB 时才报 FOB 价；空或仅写出厂/EXW 不报。"""
    t = str(value or "").strip().upper()
    if not t:
        return False
    return "FOB" in t


def include_fob_preference_from_user_prompt(text: Any) -> bool | None:
    """聊天/上传说明里对 FOB 的显式偏好。None 表示不覆盖 payload['include_fob']。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    u = raw.upper()
    tl = raw.lower()
    has_fob = "FOB" in u or "离岸" in raw
    has_exw = "EXW" in u or "exw" in tl
    if has_fob:
        return True
    if has_exw:
        return False
    return None


# Fields in section A that map directly to quote engine settings.
A_KEY_TO_SETTING = {
    "利润率": "gross_margin_rate",
    "利润率pct": "gross_margin_rate",
    # 管理损耗率：按物料合计比例摊到单件（与 quote_engine management_loss_rate 对齐）
    "管理损耗率": "management_loss_rate",
    "管理费率": "management_loss_rate",
    "物料管理费": "management_loss_rate",
    "管理费pct": "management_loss_rate",
    # 单件杂费定额（元/件），优先于按比例
    "单件杂费": "system_overhead_fixed",
    "杂费元": "system_overhead_fixed",
    "系统杂费": "system_overhead_fixed",
    "汇率": "fx_usd_rmb",
    "币种": "currency",
    "incoterms": "incoterms",
    "报价口径": "price_unit_basis",
    "价格类型": "price_type",
    "价格类型出厂fob": "price_type",
    "是否含税13": "vat_included",
    "客户名称": "customer_name",
    "国家": "country",
}


@dataclass
class Material:
    role: str           # 外料 / 里料 / 拉链 …
    name: str           # 用户填写的标准名/编码
    spec: str = ""      # 规格（颜色/型号/尺寸等）— 来自相邻列
    note: str = ""      # 用户在结构说明里追加的备注
    inline_price: str = ""   # 结构说明里抓出来的单价文本，未必在标价表内
    source: str = "demand_form"   # demand_form / structure_inline
    # 辅表中「报价明细」表：计算方式 + 报价用量（优先于模型估 1 套/1 码）
    quoted_usage: str = ""
    calc_method: str = ""
    sheet_amount_unit: str = ""
    quantity_source: str = ""


@dataclass
class DemandParseResult:
    file_name: str
    sheet_name: str
    sections: dict[str, dict[str, str]] = field(default_factory=dict)
    materials: list[Material] = field(default_factory=list)
    structure_text: str = ""
    # 仅显式结构字段可驱动推断；标准需求表模板下为空（结构说明/备注不生成 BOM）
    structure_inference_text: str = ""
    field_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    is_demand_template: bool = True
    inline_prices: list[dict[str, str]] = field(default_factory=list)
    quantities: tuple[int, ...] = ()
    quote_settings: dict[str, Any] = field(default_factory=dict)
    product_name: str = ""
    product_type: str = ""
    product_size: dict[str, float] = field(default_factory=dict)
    reference_prices: list[dict[str, Any]] = field(default_factory=list)
    gross_margin_by_quantity: dict[int, float] = field(default_factory=dict)
    raw_row_count: int = 0
    # 与同工作簿内「物料展开/BOM」等辅 sheet（简单 BOM 版式）合并后记录名称，便于对账。
    auxiliary_bom_sheet_names: tuple[str, ...] = ()
    embedded_image_count: int = 0
    structure_gap_hints: list[dict[str, Any]] = field(default_factory=list)
    # (mime, base64 无 data: 前缀)，仅供 Kimi 多模态；勿写入 to_dict。
    structure_vision_images: tuple[tuple[str, str], ...] = field(default_factory=tuple, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "sheet_name": self.sheet_name,
            "sections": self.sections,
            "materials": [vars(m) for m in self.materials],
            "structure_text": self.structure_text,
            "structure_inference_text": self.structure_inference_text,
            "field_sources": self.field_sources,
            "is_demand_template": self.is_demand_template,
            "inline_prices": self.inline_prices,
            "quantities": list(self.quantities),
            "quote_settings": self.quote_settings,
            "product_name": self.product_name,
            "product_type": self.product_type,
            "product_size": self.product_size,
            "reference_prices": self.reference_prices,
            "gross_margin_by_quantity": {str(k): v for k, v in self.gross_margin_by_quantity.items()},
            "raw_row_count": self.raw_row_count,
            "auxiliary_bom_sheet_names": list(self.auxiliary_bom_sheet_names),
            "embedded_image_count": self.embedded_image_count,
            "structure_gap_hints": self.structure_gap_hints,
        }


def is_demand_template(rows: list[list[str]]) -> bool:
    """Return True when rows look like the "需求表(填写区)" template.

    Heuristic: at least two distinct section markers from A-G appear in the
    first 40 rows.
    """
    seen: set[str] = set()
    for row in rows[:40]:
        marker = detect_section_marker(row)
        if marker is None:
            continue
        letter = marker[0].upper()
        if letter in SECTION_LETTERS:
            seen.add(letter)
        if len(seen) >= 2:
            return True
    return False


def parse_demand_from_rows(
    rows: list[list[str]],
    *,
    file_name: str = "",
    sheet_name: str = "",
    is_demand_template: bool = True,
) -> DemandParseResult:
    sections = _extract_sections(rows)
    from demand_field_sources import build_field_source_map, build_structure_inference_text

    field_sources = build_field_source_map(sections)
    structure_text = sections.get("B", {}).get("结构说明", "")
    structure_inference_text = build_structure_inference_text(
        sections,
        is_demand_template=is_demand_template,
    )
    section_materials = _extract_materials_from_section_c(sections.get("C", {}))
    materials = list(section_materials)
    inline_prices: list[dict[str, str]] = []
    # 标准需求表：结构说明/备注不得解析为正式 BOM 物料（仅 C/D 等显式字段）
    if not is_demand_template:
        inline_prices, structure_inline_materials = _extract_inline_prices(structure_text)
        materials = _add_missing_outer_material_from_structure_inline(
            materials,
            structure_inline_materials,
            sections.get("C", {}),
        )
    quantities = _extract_quantities(sections.get("F", {}), rows=rows)
    reference_prices = _extract_reference_prices(rows) + _extract_sheet_material_subtotal_anchors(
        rows
    )
    quote_settings = _extract_quote_settings(sections.get("A", {}))
    if (
        "management_loss_rate" not in quote_settings
        and "system_overhead_fixed" not in quote_settings
        and _looks_like_salesperson_hand_cost_sheet(rows)
    ):
        quote_settings["management_loss_rate"] = 0.05
        quote_settings["management_loss_rate_rule"] = "salesperson_hand_cost_default_5pct"
    quote_settings["include_fob"] = wants_fob_from_price_type(quote_settings.get("price_type"))
    proc_fee, proc_locked, proc_rule = resolve_demand_processing_fee(sections, structure_text)
    if proc_fee is not None:
        quote_settings["processing_fee"] = proc_fee
    if proc_locked:
        quote_settings["processing_fee_locked"] = True
    if proc_rule:
        quote_settings["processing_fee_rule"] = proc_rule
    proc_cap = _small_soft_bag_processing_fee_cap(sections.get("B", {}), structure_text)
    if proc_cap is not None:
        quote_settings["processing_fee_cap"] = proc_cap
        quote_settings["processing_fee_cap_rule"] = "small_soft_bag_guardrail"
    cx_lab = structure_complexity_label_from_section_b(sections.get("B", {}))
    if cx_lab:
        quote_settings["structure_complexity"] = cx_lab
    sec_b = sections.get("B", {}) or {}
    # B 区：报价卡标题优先「名称/款号」，空则用「类别/类型」（避免回落到前端默认占位如「城市日行 28L」）
    sku = _section_b_pick(sec_b, "产品名称款号", "产品名称", "品名款号", "款式名称")
    pcat = _section_b_pick(sec_b, "产品类别", "类别")
    ptype = _section_b_pick(sec_b, "产品类型", "类型")
    product_name = (sku or pcat or ptype).strip()
    product_type = (ptype or pcat).strip()
    product_size = _extract_product_size(sec_b)

    gross_margin_by_quantity: dict[int, float] = {}
    for ref in reference_prices:
        rq = ref.get("quantity")
        rm = ref.get("margin")
        if rq is not None and rm is not None:
            try:
                gross_margin_by_quantity.setdefault(int(rq), float(rm))
            except (TypeError, ValueError):
                pass
    gross_margin_by_quantity.update(_extract_tier_margins_from_section_f(sections.get("F", {})))

    structure_gap_hints: list[dict[str, Any]] = []
    if is_demand_template and structure_text.strip():
        try:
            from structure_gap_hints import build_structure_gap_hints

            structure_gap_hints = build_structure_gap_hints(
                structure_text,
                [vars(m) for m in materials],
                demand_template=True,
            )
        except Exception:
            structure_gap_hints = []

    _normalize_materials_embedded_quantity(materials)

    return DemandParseResult(
        file_name=file_name,
        sheet_name=sheet_name,
        sections=sections,
        materials=materials,
        structure_text=structure_text,
        structure_inference_text=structure_inference_text,
        field_sources=field_sources,
        is_demand_template=is_demand_template,
        inline_prices=inline_prices,
        quantities=quantities,
        quote_settings=quote_settings,
        product_name=product_name,
        product_type=product_type,
        product_size=product_size,
        reference_prices=reference_prices,
        gross_margin_by_quantity=gross_margin_by_quantity,
        raw_row_count=len(rows),
        auxiliary_bom_sheet_names=(),
        embedded_image_count=0,
        structure_gap_hints=structure_gap_hints,
    )


def parse_demand_from_payload(payload: dict[str, Any]) -> DemandParseResult:
    if not isinstance(payload, dict):
        raise SheetParseError("Uploaded payload must be an object.")
    file_name = str(payload.get("name") or "").strip()
    file_base64 = str(payload.get("content_base64") or "").strip()
    if not file_name or not file_base64:
        raise SheetParseError("Missing file name or content.")

    import base64
    try:
        file_bytes = base64.b64decode(file_base64, validate=True)
    except Exception as error:
        raise SheetParseError("Failed to decode file content.") from error

    suffix = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    extras_simple: list[Material] = []
    extras_detail: list[Material] = []
    merged_aux_names: list[str] = []
    merged_detail_names: list[str] = []
    if suffix == "xlsx":
        sheet_name, rows = _pick_demand_sheet(file_bytes)
        extras_detail, merged_detail_names = collect_quotation_detail_materials_from_xlsx(
            file_bytes, sheet_name, file_name=file_name
        )
        extras_embedded = materials_from_rows_quotation_detail_block(rows, sheet_slug=sheet_name)
        if extras_embedded:
            extras_detail = extend_materials_dedupe_by_name(extras_detail, extras_embedded)
            tag = f"{sheet_name.strip() or '工作表'}·内嵌报价明细"
            if tag not in merged_detail_names:
                merged_detail_names.append(tag)
        extras_simple, merged_aux_names = collect_auxiliary_bom_materials_from_xlsx(
            file_bytes, sheet_name, file_name=file_name
        )
    elif suffix == "xls":
        sheets_data = parse_xls_all_sheets_normalized(file_bytes)
        sheet_name, rows = pick_best_demand_sheet_rows(sheets_data)
        extras_detail, merged_detail_names = [], []
        extras_simple, merged_aux_names = [], []
        extras_embedded = materials_from_rows_quotation_detail_block(rows, sheet_slug=sheet_name)
        if extras_embedded:
            extras_detail = extend_materials_dedupe_by_name(extras_detail, extras_embedded)
            tag = f"{sheet_name.strip() or '工作表'}·内嵌报价明细"
            if tag not in merged_detail_names:
                merged_detail_names.append(tag)
    else:
        parsed_sheet, _ = parse_rows_from_bytes(
            file_name=file_name,
            file_bytes=file_bytes,
            preferred_sheet=str(payload.get("sheet_name") or "").strip(),
        )
        sheet_name, rows = parsed_sheet.sheet_name, parsed_sheet.rows

    merged = parse_demand_from_rows(rows, file_name=file_name, sheet_name=sheet_name)
    names_all: list[str] = []
    if extras_detail:
        merged.materials = extend_materials_dedupe_by_name(merged.materials, extras_detail)
        merged.materials = absorb_quotation_detail_into_demand_fabric_rows(merged.materials)
        names_all.extend(merged_detail_names)
    if extras_simple:
        merged.materials = extend_materials_dedupe_by_name(merged.materials, extras_simple)
        names_all.extend(merged_aux_names)
    if names_all:
        merged.auxiliary_bom_sheet_names = tuple(names_all)
    _normalize_materials_embedded_quantity(merged.materials)
    if suffix == "xlsx":
        from xlsx_rich_context import augment_demand_structure_from_xlsx_bytes, list_embedded_images_from_xlsx_bytes

        merged.structure_text, merged.structure_vision_images = augment_demand_structure_from_xlsx_bytes(
            file_bytes,
            merged.structure_text,
            priority_sheet_name=sheet_name,
        )
        try:
            merged.embedded_image_count = len(list_embedded_images_from_xlsx_bytes(file_bytes))
        except Exception:
            merged.embedded_image_count = 0
    return merged


def pick_best_demand_sheet_rows(
    sheets_data: list[tuple[str, list[list[str]]]],
) -> tuple[str, list[list[str]]]:
    """在多张工作表中选出最像「需求表(填写区)」的一张（与 xlsx 选表逻辑一致）。"""
    if not sheets_data:
        raise SheetParseError("No worksheet found.")
    candidates: list[tuple[int, int, int, str, list[list[str]]]] = []
    for sheet_name, rows in sheets_data:
        name_score = _demand_name_score(sheet_name)
        title_section_count = _count_titled_section_markers(rows)
        non_empty = sum(1 for row in rows if any(cell.strip() for cell in row))
        candidates.append((name_score, title_section_count, non_empty, sheet_name, rows))
    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    _, _, _, name, rows = candidates[0]
    return name, rows


def _pick_demand_sheet(file_bytes: bytes) -> tuple[str, list[list[str]]]:
    """Open the workbook, score each sheet against the demand-template
    heuristic, and return the rows of the highest-scoring one. Falls back
    to the largest sheet if nothing looks like a demand template."""
    import io
    import zipfile

    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as error:
        raise SheetParseError("Invalid XLSX file format.") from error

    shared_strings = read_shared_strings(archive)
    sheets = read_sheet_entries(archive)
    if not sheets:
        raise SheetParseError("No worksheet found in XLSX file.")

    sheets_data: list[tuple[str, list[list[str]]]] = []
    for sheet_name, sheet_xml in sheets:
        rows = normalize_rows(parse_sheet_xml_rows(sheet_xml, shared_strings))
        sheets_data.append((sheet_name, rows))
    return pick_best_demand_sheet_rows(sheets_data)


_DEMAND_NAME_KEYWORDS = ("需求表", "填写区", "业务报价")


def _demand_name_score(sheet_name: str) -> int:
    name = sheet_name.strip().lower()
    return sum(1 for kw in _DEMAND_NAME_KEYWORDS if kw.lower() in name)


def _count_titled_section_markers(rows: list[list[str]]) -> int:
    """Only count section markers whose title looks like "X. <words>".

    The field-mapping sheet has rows like ['A', '客户名称', ...] which
    detect_section_marker also returns; those should not count here.
    """
    import re as _re
    title_pattern = _re.compile(r"^\s*([A-Ga-g])\s*[\.．、:：]\s*\S+")
    seen: set[str] = set()
    for row in rows[:60]:
        first = row_get(row, 0).strip()
        if title_pattern.match(first):
            seen.add(first[0].upper())
    return len(seen & set(SECTION_LETTERS))


def _extract_sections(rows: list[list[str]]) -> dict[str, dict[str, str]]:
    """Walk rows, locate each "X. ..." marker, then read header+value pairs.

    Within a section, support horizontal blocks of「表头行 + 多条值行」；同一列
    多行取值用分号合并，空值不覆盖已有值。
    """
    sections: dict[str, dict[str, str]] = {}
    cursor = 0
    while cursor < len(rows):
        marker = detect_section_marker(rows[cursor])
        if marker is None:
            cursor += 1
            continue
        letter = marker[0].upper()
        if letter not in SECTION_LETTERS:
            cursor += 1
            continue
        next_marker_index = _find_next_section_index(rows, cursor + 1)
        section_rows = rows[cursor + 1 : next_marker_index]
        merged = _zip_headers_to_values(section_rows)
        if merged:
            bucket = sections.setdefault(letter, {})
            for key, value in merged.items():
                if not value:
                    continue
                prev = str(bucket.get(key) or "").strip()
                if prev and prev != value:
                    if value not in prev.split(";"):
                        bucket[key] = f"{prev}; {value}"
                elif not prev:
                    bucket[key] = value
        cursor = next_marker_index
    _merge_implicit_quantity_section(sections, rows)
    return sections


def _merge_implicit_quantity_section(sections: dict[str, dict[str, str]], rows: list[list[str]]) -> None:
    """无 F. 标题时，从「数量1/数量2… + 下一行数值」补全 F 区。"""
    implicit = _extract_implicit_quantity_section(rows)
    if not implicit:
        return
    bucket = sections.setdefault("F", {})
    for key, value in implicit.items():
        if not value:
            continue
        prev = str(bucket.get(key) or "").strip()
        if prev:
            continue
        bucket[key] = value


def _extract_implicit_quantity_section(rows: list[list[str]]) -> dict[str, str]:
    for idx, row in enumerate(rows):
        if not row_is_quantity_tier_header(row):
            continue
        value_idx = _next_nonempty_row_index(rows, idx + 1)
        if value_idx is None:
            continue
        value_row = rows[value_idx]
        if row_is_quantity_tier_header(value_row) or detect_section_marker(value_row) is not None:
            continue
        zipped = _zip_single_header_value_row(row, value_row)
        if zipped:
            return zipped
    return {}


def _next_nonempty_row_index(rows: list[list[str]], start: int) -> int | None:
    for idx in range(start, len(rows)):
        if _row_has_content(rows[idx]):
            return idx
    return None


def _zip_single_header_value_row(header_row: list[str], value_row: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for idx, header in enumerate(header_row):
        key = _normalise_key(header)
        if not key:
            continue
        value = row_get(value_row, idx).strip()
        if not value or _is_excel_error_value(value):
            continue
        result[key] = value
    return result


def _find_next_section_index(rows: list[list[str]], start: int) -> int:
    for idx in range(start, len(rows)):
        if detect_section_marker(rows[idx]) is not None:
            return idx
    return len(rows)


def _zip_headers_to_values(section_rows: list[list[str]]) -> dict[str, str]:
    """Pair horizontal header row(s) with one or more value rows, column-by-column."""
    result: dict[str, str] = {}
    for header_row, value_rows in _split_section_header_value_blocks(section_rows):
        for idx, header in enumerate(header_row):
            key = _normalise_key(header)
            if not key:
                continue
            collected: list[str] = []
            for value_row in value_rows:
                value = row_get(value_row, idx).strip()
                if not value or _is_excel_error_value(value):
                    continue
                collected.append(value)
            if not collected:
                continue
            merged_val = "; ".join(collected)
            prev = str(result.get(key) or "").strip()
            if prev:
                parts = [p.strip() for p in prev.split(";") if p.strip()]
                for piece in collected:
                    if piece not in parts:
                        parts.append(piece)
                result[key] = "; ".join(parts)
            else:
                result[key] = merged_val
    return result


def _split_section_header_value_blocks(
    section_rows: list[list[str]],
) -> list[tuple[list[str], list[list[str]]]]:
    blocks: list[tuple[list[str], list[list[str]]]] = []
    idx = 0
    while idx < len(section_rows):
        row = section_rows[idx]
        if not _row_has_content(row):
            idx += 1
            continue
        if not _row_looks_like_section_header_row(row, section_rows, idx):
            idx += 1
            continue
        header_row = row
        idx += 1
        value_rows: list[list[str]] = []
        while idx < len(section_rows):
            candidate = section_rows[idx]
            if not _row_has_content(candidate):
                idx += 1
                continue
            if _row_looks_like_section_header_row(candidate, section_rows, idx):
                break
            if detect_section_marker(candidate) is not None:
                break
            if row_is_quantity_tier_header(candidate):
                break
            value_rows.append(candidate)
            idx += 1
        if value_rows:
            blocks.append((header_row, value_rows))
    return blocks


def _row_looks_like_section_header_row(
    row: list[str],
    section_rows: list[list[str]],
    row_index: int,
) -> bool:
    if detect_section_marker(row) is not None or row_is_quantity_tier_header(row):
        return False
    if not _row_is_header_label_row(row):
        return False
    nxt = _next_nonempty_row_index(section_rows, row_index + 1)
    if nxt is None:
        return False
    next_row = section_rows[nxt]
    if detect_section_marker(next_row) is not None or row_is_quantity_tier_header(next_row):
        return False
    return _row_is_data_value_row(next_row) or not _row_is_header_label_row(next_row)


def _looks_like_demand_data_value(text: str) -> bool:
    """需求表「值行」特征：含规格/数量/单价等，而非列标题。"""
    raw = str(text or "").strip()
    if not raw or _is_excel_error_value(raw):
        return False
    if re.search(
        r"\d+\s*[DdTt]|#\d|\d+(?:\.\d+)?\s*(?:mm|cm)|\d+(?:\.\d+)?\s*码|/\s*码|\*\s*\d|\*\d",
        raw,
        re.I,
    ):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return True
    if any(sep in raw for sep in ("，", ",", "；", ";", "+", "、", "＋")) and len(raw) > 5:
        return True
    if len(raw) >= 8 and any(k in raw for k in ("防水", "PU", "PEVA", "EPE", "尼龙", "涤纶", "牛津", "织带", "DCH", "DCF")):
        return True
    return False


def _looks_like_demand_header_label(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw or len(raw) > 48:
        return False
    if _looks_like_demand_data_value(raw):
        return False
    if detect_section_marker([raw]) is not None:
        return False
    if row_is_quantity_tier_header([raw]):
        return False
    key = _normalise_key(raw)
    if not key:
        return False
    if key in SECTION_C_NON_MATERIAL_HEADERS or key in SECTION_C_ROLE_MAP:
        return True
    header_suffixes = (
        "类型",
        "等级",
        "颜色",
        "编码",
        "标准名",
        "长度",
        "说明",
        "方式",
        "备注",
        "选",
        "分摊",
        "费用",
        "是否",
        "装箱",
        "外箱",
        "包装",
        "数量",
        "利润率",
        "毛利率",
        "复杂",
        "模具",
        "刀模",
        "注塑",
        "注塑",
        "摊",
    )
    if any(s in raw for s in header_suffixes):
        return True
    bare_roles = (
        "外料",
        "里料",
        "拉链",
        "拉头",
        "拉片",
        "扣具",
        "织带",
        "肩带",
        "绳带",
        "辅料",
        "加固辅料",
        "logo方式",
        "logo工艺",
        "工艺备注",
        "特殊工艺备注",
        "单个包装",
        "外箱类型",
        "装箱量",
        "外箱尺寸",
        "产品类型",
        "产品名称",
        "品名款号",
        "客户名称",
        "业务员编号",
        "国家",
        "币种",
    )
    if raw in bare_roles or key in {_normalise_key(x) for x in bare_roles}:
        return True
    if re.search(r"[\(（].*(?:标准名|编码).*[\)）]", raw):
        return True
    if raw.lower() in {"l(cm)", "w(cm)", "h(cm)", "lcm", "wcm", "hcm"}:
        return True
    if row_looks_like_horizontal_param_header([raw]) and len(raw) <= 16:
        return True
    return False


def _row_is_header_label_row(row: list[str]) -> bool:
    cells = [str(c or "").strip() for c in row if str(c or "").strip()]
    if not cells:
        return False
    labels = sum(1 for c in cells if _looks_like_demand_header_label(c))
    if labels >= 2 and labels >= max(2, int(len(cells) * 0.5)):
        return True
    return bool(row_looks_like_horizontal_param_header(row) and labels >= 2)


def _row_is_data_value_row(row: list[str]) -> bool:
    cells = [str(c or "").strip() for c in row if str(c or "").strip()]
    if not cells:
        return False
    data_hits = sum(1 for c in cells if _looks_like_demand_data_value(c))
    if data_hits >= 1 and data_hits >= max(1, int(len(cells) * 0.34)):
        return True
    if not _row_is_header_label_row(row):
        return any(not _looks_like_demand_header_label(c) for c in cells)
    return False


def _row_has_content(row: list[str]) -> bool:
    return any(str(cell).strip() for cell in row)


def _normalise_key(text: str) -> str:
    if text is None:
        return ""
    cleaned = str(text).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[（）()\[\]【】%]", "", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace("/", "").replace("\\", "")
    cleaned = cleaned.replace(",", "").replace("，", "")
    cleaned = cleaned.replace(":", "").replace("：", "")
    cleaned = cleaned.replace(".", "").replace("。", "")
    return cleaned.lower()


def _section_b_pick(section_b: dict[str, str], *header_candidates: str) -> str:
    """按需求表表头可能出现的多种写法取值（键与 `_zip_headers_to_values` 一致为 normalised）。"""
    for label in header_candidates:
        key = _normalise_key(label)
        if not key:
            continue
        v = (section_b.get(key) or "").strip()
        if v:
            return v
    return ""


_NAME_KEYWORDS_HINTING_FULL_DESCRIPTION = (
    "拉链", "扣", "织带", "绳", "布", "料", "革", "ev", "pu", "pvc",
    "tpu", "尼龙", "涤纶", "棉", "皮", "网",
)

# C 区外料/里料逗号后常见「性状/视觉效果」短语，不是第二种主料（如 B260172「亮面折光效果」）
_FABRIC_VISUAL_DESCRIPTOR_RE = re.compile(
    r"^(?:亮面|哑光|磨砂|反光|折光|透光|亮光|亚光|仿[尼龙棉皮革]|"
    r"表面|轻微|手感|色泽|颜色|撞色)(?:效果|处理|涂层|折射)?$",
    re.I,
)


def _looks_like_fabric_name_not_descriptor(chunk: str) -> bool:
    """判断 C 区逗号分隔片段是否为可单独计价的物料名（而非外料格内的性状说明）。"""
    c = str(chunk or "").strip()
    if not c or len(c) < 2:
        return False
    compact = re.sub(r"\s+", "", c)
    if _FABRIC_VISUAL_DESCRIPTOR_RE.match(compact):
        return False
    if _DENIER_OR_THREAD_LEAD.match(c) or _THREAD_T_LEAD.match(c):
        return True
    if any(kw in c for kw in _NAME_KEYWORDS_HINTING_FULL_DESCRIPTION):
        return True
    if re.search(r"\d+\s*[DdT]", c, re.I):
        return True
    # 无布/料/纱等称谓，且含「效果/亮光/折光」等 → 视为上一段外料的说明
    if len(c) <= 14 and any(
        t in c for t in ("效果", "亮光", "折光", "反光", "亮面", "哑光", "防水", "防泼水")
    ):
        return False
    return True


_PURE_LENGTH_OR_DIM_METADATA = re.compile(
    r"^(?:约|大约|≈)?[-─—~～]*"
    r"\d+(?:\.\d+)?"
    r"(?:\s*[-~]\s*\d+(?:\.\d+)?)?"
    r"\s*(?:cm|mm|CM|MM|厘米|毫米|m|M|米|码|yd|YD)?"
    r"(?:粗|宽|厚|直径|径|长)?$",
    re.I,
)
_PURE_PLANAR_DIM_METADATA = re.compile(
    r"^\d+(\.\d+)?\s*[*xX×]\s*\d+(\.\d+)?\s*(CM|MM|M|米|码|码²)?$",
    re.I,
)


def _chunk_has_material_substance(chunk: str) -> bool:
    """片段除尺寸/长度外是否仍含可计价物料称谓（如 EPE保温棉、5#拉链）。"""
    c = str(chunk or "").strip()
    if not c:
        return False
    if any(kw in c for kw in _NAME_KEYWORDS_HINTING_FULL_DESCRIPTION):
        return True
    if re.search(r"\d+\s*#|\d+\s*号", c):
        return True
    if _DENIER_OR_THREAD_LEAD.match(c) or _THREAD_T_LEAD.match(c):
        return True
    if re.search(r"\b(?:EPE|EVA|PEVA|XPE)\b", c, re.I):
        return True
    return False


def _looks_like_length_or_dimension_metadata(chunk: str) -> bool:
    """纯长度/尺寸描述，不能作为独立材料名（如 约1.3m、约---1.3m、140*90CM）。"""
    c = str(chunk or "").strip()
    if not c:
        return False
    if _chunk_has_material_substance(c):
        return False
    compact = re.sub(r"\s+", "", c)
    for candidate in (compact, c):
        if _PURE_LENGTH_OR_DIM_METADATA.fullmatch(candidate):
            return True
        if _PURE_PLANAR_DIM_METADATA.fullmatch(candidate):
            return True
    return False


def _looks_like_strap_spec_descriptor(chunk: str) -> bool:
    """肩带/织带单元格逗号后的粗细/长度片段（如「约0.8cm粗」「约1.3m」），不是第二种物料。"""
    return _looks_like_length_or_dimension_metadata(chunk)


def _section_c_strap_spec_from_value(role: str, raw_value: str) -> str:
    """从肩带/织带单元格的规格描述片段提取尺寸（如 0.8cm）。"""
    if role not in ("肩带", "织带", "绳带"):
        return ""
    for part in _split_multi_value(raw_value):
        if not _looks_like_strap_spec_descriptor(part):
            continue
        _name, spec, *_rest = _split_name_spec_inline(part)
        if spec:
            return spec
    return ""


def _section_c_strap_length_from_value(role: str, raw_value: str) -> str:
    """从肩带/织带/绳带单元格提取长度描述，写入 quoted_usage。"""
    if role not in ("肩带", "织带", "绳带"):
        return ""
    for part in _split_multi_value(raw_value):
        if _looks_like_length_or_dimension_metadata(part):
            return part.strip()
    return ""


def _is_section_c_non_material_header(raw_key: str) -> bool:
    """C 区描述性/用量元数据列，不生成独立材料行。"""
    key = str(raw_key or "").strip()
    if not key:
        return True
    if key in SECTION_C_NON_MATERIAL_HEADERS:
        return True
    compact = re.sub(r"\s+", "", key)
    if re.search(r"(?:长度|宽度|高度|厚度|周长)(?:cm|mm|CM|MM)?$", compact):
        if any(token in compact for token in ("肩带", "织带", "绳", "绑带", "背带")):
            return True
    if compact.endswith("颜色") and any(
        token in compact for token in ("外料", "里料", "拉链", "肩带", "织带")
    ):
        return True
    return False


def _split_section_c_material_chunks(role: str, raw_value: str) -> list[str]:
    """外料/里料：逗号仅保留可计价主料片段；性状短语由调用方写入上一行 note。"""
    parts = _split_multi_value(raw_value)
    if role in ("外料", "里料"):
        return [p for p in parts if _looks_like_fabric_name_not_descriptor(p)]
    if role in ("肩带", "织带", "绳带"):
        return [p for p in parts if not _looks_like_strap_spec_descriptor(p)]
    return parts


def _section_c_trailing_descriptors(role: str, raw_value: str) -> list[str]:
    """外料/里料单元格内、逗号后的性状说明（非第二主料）。"""
    if role not in ("外料", "里料"):
        return []
    return [
        p.strip()
        for p in _split_multi_value(raw_value)
        if p.strip() and not _looks_like_fabric_name_not_descriptor(p)
    ]


def _looks_like_short_enum_value(value: str) -> bool:
    """Decide whether a section-C cell value is a short enum like '5号' or
    '塑胶标准' that needs to be combined with its role to form a meaningful
    material name."""
    if not value:
        return False
    if len(value) > 6:
        return False
    lowered = value.lower()
    return not any(kw in lowered for kw in _NAME_KEYWORDS_HINTING_FULL_DESCRIPTION)


def _inject_shoulder_strap_length_from_section_c(
    materials: list[Material],
    section_c: dict[str, str],
) -> None:
    """「肩带长度」「肩带长度cm」与「肩带/织带类型」同排，应锁定肩带行用量（元数据列原被跳过未进 BOM）。"""
    lr = (section_c.get("肩带长度") or section_c.get("肩带长度cm") or "").strip()
    if not lr:
        return
    if not re.search(
        r"(?:cm|mm|毫米|厘米|米|(?<![a-z])m(?![a-z])|码|yd|y)\b",
        lr,
        re.I,
    ):
        lr = f"{lr}cm"
    for m in materials:
        if m.role != "肩带":
            continue
        if str(getattr(m, "quoted_usage", "") or "").strip():
            continue
        if piece_count_usage_from_cell_note(str(m.note or "")):
            continue
        m.quoted_usage = lr
        return


def _normalize_materials_embedded_quantity(materials: list[Material]) -> None:
    """需求表材料名内嵌数量拆到 quoted_usage，避免脏名进入报价/KB。"""
    for m in materials:
        clean, qty, src = split_quantity_from_material_name(str(m.name or "").strip())
        if not src or not clean:
            continue
        m.name = clean
        if qty:
            name_count = parse_piece_count_from_usage(qty)
            exist_count = parse_piece_count_from_usage(m.quoted_usage) if m.quoted_usage else None
            if exist_count is None or (name_count is not None and exist_count != name_count):
                m.quoted_usage = qty
                m.quantity_source = src


def _resolve_section_c_role(raw_key: str) -> str | None:
    role = SECTION_C_ROLE_MAP.get(raw_key)
    if role:
        return role
    raw = str(raw_key or "")
    if "拉片" in raw:
        return "拉片"
    if "网袋" in raw:
        return "辅料"
    if "肩带" in raw or "织带" in raw:
        return "织带"
    if "拉链" in raw:
        return "拉链"
    if "拉头" in raw:
        return "拉头"
    if "扣具" in raw or "扣" in raw:
        return "扣具"
    if "绳" in raw or "绑带" in raw:
        return "绳带"
    if "外料" in raw or "主面料" in raw:
        return "外料"
    if "里料" in raw or "内衬" in raw or "内里" in raw:
        return "里料"
    if "辅料" in raw or "加固" in raw:
        return "辅料"
    return None


def _extract_materials_from_section_c(section_c: dict[str, str]) -> list[Material]:
    """Walk section C key/value pairs and pick out the rows that name a
    purchasable material (外料 / 里料 / 拉链 / 扣具 / 织带 / 绳带 …)."""
    materials: list[Material] = []
    seen: set[tuple[str, str]] = set()

    for raw_key, raw_value in section_c.items():
        if _is_section_c_non_material_header(raw_key):
            continue
        role = _resolve_section_c_role(raw_key)
        if role is None:
            continue
        chunks = _split_section_c_material_chunks(role, raw_value)
        trailing_desc = _section_c_trailing_descriptors(role, raw_value)
        strap_extra_spec = _section_c_strap_spec_from_value(role, raw_value)
        strap_inline_length = _section_c_strap_length_from_value(role, raw_value)
        for chunk in chunks:
            name, spec, note, inline = _split_name_spec_inline(chunk)
            if not name:
                continue
            if _looks_like_length_or_dimension_metadata(name):
                continue
            if _is_excel_error_value(name):
                continue
            q_piece = piece_count_usage_from_cell_note(note)
            eff_note = "" if q_piece else note
            if _looks_like_short_enum_value(name):
                # "5号" → "5号拉链", "塑胶标准" → "塑胶标准扣具" — gives
                # downstream KB lookup and LLM enough semantic anchor.
                if role not in name:
                    name = f"{name}{role}"
            key = (role, name)
            if key in seen:
                continue
            seen.add(key)
            materials.append(
                Material(
                    role=role,
                    name=name,
                    spec=spec or strap_extra_spec or _spec_from_section_c(section_c, raw_key),
                    note=eff_note,
                    inline_price=inline,
                    source="demand_form",
                    quoted_usage=q_piece or strap_inline_length or "",
                )
            )
        if trailing_desc and materials and materials[-1].role == role:
            tail = "；".join(trailing_desc)
            prev = materials[-1]
            prev.note = (
                f"{prev.note}；{tail}".strip("；") if str(prev.note or "").strip() else tail
            )
    _inject_shoulder_strap_length_from_section_c(materials, section_c)
    return materials


def _squeeze_material_name_key(name: str) -> str:
    """用于结构说明料子与 C 区去重合并（忽略空白与大小写）。"""
    return re.sub(r"\s+", "", str(name or "").strip().lower())


def _merge_section_c_with_structure_inline(
    section_materials: list[Material],
    structure_inline_materials: list[Material],
) -> list[Material]:
    """C 区为主；结构说明中带价单列出的料子补足 BOM，减轻漏行误差。"""
    out: list[Material] = list(section_materials)
    existing = {_squeeze_material_name_key(m.name) for m in section_materials if m.name.strip()}
    for m in structure_inline_materials:
        sk = _squeeze_material_name_key(m.name)
        if len(sk) < 3:
            continue
        matched = _match_existing_material_for_inline(sk, section_materials)
        if matched is not None:
            if m.inline_price and (not matched.inline_price or matched.inline_price == "-"):
                matched.inline_price = m.inline_price
            if m.note and not matched.note:
                matched.note = m.note
            continue
        if sk in existing:
            continue
        existing.add(sk)
        out.append(m)
    return out


def _match_existing_material_for_inline(
    inline_key: str,
    section_materials: list[Material],
) -> Material | None:
    """Bind inline-price fragments back to C-section rows.

    A fixed-width look-behind can occasionally leave a tail like
    "D塔丝隆格子布" for a C-row material named "600D塔丝隆格子布".  Treat
    that as the same material, but keep the match narrow so short generic
    snippets such as "YKK" do not get absorbed by unrelated composite rows.
    """
    if len(inline_key) < 4:
        return None
    best: Material | None = None
    best_len = -1
    for material in section_materials:
        existing_key = _squeeze_material_name_key(material.name)
        if not existing_key:
            continue
        if existing_key == inline_key:
            return material
        if len(existing_key) < 4:
            continue
        if existing_key.endswith(inline_key) or inline_key.endswith(existing_key):
            if len(existing_key) > best_len:
                best = material
                best_len = len(existing_key)
    return best


def _section_c_outer_material_missing(section_c: dict[str, str]) -> bool:
    for key, value in section_c.items():
        k = str(key or "")
        if not ("\u5916\u6599" in k or "\u4e3b\u9762\u6599" in k or "outer" in k.lower()):
            continue
        text = str(value or "").strip()
        if not text or _is_excel_error_value(text) or text in {"-", "/", "\u2014"}:
            return True
        return False
    return not any(m.role == "\u5916\u6599" for m in [])


def _clean_structure_outer_name(name: str) -> str:
    text = str(name or "").strip()
    text = re.sub(r"[\(\uff08]\s*(?:\u4e3b\u4f53\u9762\u6599|\u4e3b\u9762\u6599|\u5916\u6599|\u5916\u5c42).*?$", "", text).strip()
    text = re.sub(r"[\(\uff08]\s*$", "", text).strip()
    return text


def _looks_like_outer_inline_material(material: Material) -> bool:
    name = str(material.name or "").strip()
    note = str(material.note or "").strip()
    blob = f"{name} {note}"
    if not name or _is_spurious_structure_inline_name(name):
        return False
    if any(x in blob for x in ("\u5185\u886c", "\u91cc\u6599", "\u91cc\u5e03", "\u5185\u91cc")):
        return False
    if any(x in blob for x in ("\u4ec5\u7528\u4e8e", "\u5e95\u90e8\u8d34\u7247", "\u5e95\u7247", "\u8d34\u7247")):
        return False
    if any(x in blob for x in ("\u4e3b\u4f53\u9762\u6599", "\u4e3b\u9762\u6599", "\u5916\u6599", "\u5916\u5c42")):
        return True
    return bool(re.search(r"x[-\s]?pac|xpac|vx21|ultra|dcf|dch", blob, re.I))


def _add_missing_outer_material_from_structure_inline(
    materials: list[Material],
    structure_inline_materials: list[Material],
    section_c: dict[str, str],
) -> list[Material]:
    if any(m.role == "\u5916\u6599" for m in materials):
        return materials
    if not _section_c_outer_material_missing(section_c):
        return materials
    for material in structure_inline_materials:
        if not _looks_like_outer_inline_material(material):
            continue
        name = _clean_structure_outer_name(material.name)
        if not name:
            continue
        out = list(materials)
        out.insert(
            0,
            Material(
                role="\u5916\u6599",
                name=name,
                spec=material.spec or "",
                note=material.note or "",
                inline_price=material.inline_price or "",
                source="structure_inline_outer_fallback",
            ),
        )
        return out
    return materials


def augment_materials_from_structure_keywords(
    structure_text: str,
    materials: list[Material],
) -> list[Material]:
    """根据结构说明中的关键词补足 C 区未写的常见辅料/夹层（减轻 BOM 漏行导致的物料低估）。"""
    blob = str(structure_text or "").strip()
    if not blob:
        return materials
    existing = {_squeeze_material_name_key(m.name) for m in materials if m.name.strip()}
    seen_new: set[str] = set()
    additions: list[Material] = []

    specs: tuple[tuple[re.Pattern[str], str, str], ...] = (
        (re.compile(r"包边(?:带|条)?|捆边(?:带)?|捆条|滚边带"), "辅料", "包边带"),
        (re.compile(r"PEVA|铝箔复合|镀铝膜|铝塑|铝膜(?:复合)?"), "里料", "PEVA复合铝膜"),
        (re.compile(r"三明治(?:网)?(?:布|料)|3d\s*mesh", re.I), "辅料", "三明治网布"),
        (re.compile(r"无纺布|针棉|补强布"), "辅料", "补强无纺布"),
        (re.compile(r"胶粘|双面胶|热熔胶|胶(?:条|边)"), "辅料", "胶粘辅料"),
        (re.compile(r"织唛|主唛|洗唛|洗水唛|皮标"), "辅料", "织唛洗唛标牌"),
        (re.compile(r"自封袋|OPP袋|包装袋|透明胶袋|胶袋"), "辅料", "包装袋"),
        (re.compile(r"内里复合|内里夹棉"), "里料", "内里复合材料"),
    )
    for rx, role, label in specs:
        if not rx.search(blob):
            continue
        sk = _squeeze_material_name_key(label)
        if len(sk) < 2:
            continue
        if sk in existing or sk in seen_new:
            continue
        seen_new.add(sk)
        additions.append(
            Material(
                role=role,
                name=label,
                spec="",
                note="",
                inline_price="",
                source="structure_keyword",
            )
        )

    return materials + additions


def _spec_from_section_c(section_c: dict[str, str], material_key: str) -> str:
    """For a known material header, peek at the adjacent "颜色" header for
    extra spec context (e.g. "外料颜色" → "粉色")."""
    color_key = f"{material_key}颜色"
    return section_c.get(color_key, "").strip()


def _split_multi_value(text: str) -> list[str]:
    if not text:
        return []
    # Treat explicit connectors as multi-material separators so one cell can
    # expand into multiple BOM rows (e.g. "#5尼龙拉链+YKK防水拉链").
    parts = re.split(r"[;；,+，、]+", text)
    return [part.strip() for part in parts if part.strip()]


def _split_name_spec_inline(chunk: str) -> tuple[str, str, str, str]:
    """Pull a material name, spec hint, inline note and inline price from
    a single value cell.

    Examples handled:
        "5号YKK防水拉链（7.5元/码）"
        "1寸坑纹尼龙织带（用量1.5码,0.55元/码）"
        "600D牛津布"
    """
    if not chunk:
        return "", "", "", ""
    note = ""
    inline = ""
    bracket_match = re.search(r"[（(]([^（()）]+)[)）]", chunk)
    if bracket_match:
        note = bracket_match.group(1).strip()
        chunk_clean = (chunk[: bracket_match.start()] + chunk[bracket_match.end():]).strip()
        price_match = INLINE_PRICE_PATTERN.search(note)
        if price_match:
            inline = price_match.group(0)
    else:
        chunk_clean = chunk.strip()

    name = chunk_clean.strip().strip("、,，")
    # 匹配顺序：先「小数+单位」再「整数+单位」，避免 0.8cm 被 \b 切成 8cm（句点在 Python re 中不是 \w）
    spec = ""
    for pat in (
        r"\d+\.\d+\s*(?:cm|mm|CM|MM|英寸|inch|寸|码|米|m|M)",
        r"(?<![.\d])(\d+)\s*(?:cm|mm|CM|MM|英寸|inch|寸|码|米|m|M)",
        r"\d+\s*#",
        r"\d+\s*号",
    ):
        m = re.search(pat, name, re.I)
        if m:
            spec = m.group(0).strip()
            break
    return name, spec, note, inline


def _is_excel_error_value(value: object) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    if compact in EXCEL_ERROR_VALUES:
        return True
    return bool(re.fullmatch(r"#(?:name\?|value!|ref!|div/0!|n/a|num!|null!)", compact, re.I))


_LEADING_TRIM_PATTERN = re.compile(
    r"^(用量|约|大约|每个用|表面|材料|用|外层|内里|内层|底部|顶部|后幅|前幅|双肩)[:：]?\s*"
)
_SECTION_NUMBER_PATTERN = re.compile(r"^[0-9一二三四五六七八九十]+\s*[\.、:：]?\s*")
# 600D / 75D / 290T 等旦数与线密度写法；开头数字不是「1、2.」这类章节序号
_DENIER_OR_THREAD_LEAD = re.compile(
    r"^\d+(?:\.\d+)?\s*[Dd](?:[^0-9]|$)",
    re.I,
)
_THREAD_T_LEAD = re.compile(
    r"^\d+(?:\.\d+)?\s*T(?:[^0-9]|$)",
    re.I,
)


def _strip_leading_section_marker(fragment: str) -> str:
    """去掉「1、」「2.」式章节头；禁止误删 600D/290T 等面料常见前缀数字。"""
    frag = str(fragment or "").strip()
    if not frag:
        return frag
    if _DENIER_OR_THREAD_LEAD.match(frag) or _THREAD_T_LEAD.match(frag):
        return frag
    return _SECTION_NUMBER_PATTERN.sub("", frag).strip()


# 「幅宽137CM」「宽幅145cm」一类纯尺码，不是物料名
_DIM_ONLY_STRUCTURE_INLINE = re.compile(
    r"^(幅宽|门幅|宽幅|长|宽|高|厚|深|直径|周长)"
    r"[:：]?(\d+(?:\.\d+)?)(?:cm|mm|毫米|厘米|CM|MM|英寸|inch)?$",
    re.I,
)


def _is_spurious_structure_inline_name(name: str) -> bool:
    """剔除截取产生的假物料名（纯尺码格、括号断层、单价头等），避免进入 BOM 合并列表。"""
    n = str(name or "").strip()
    if len(n) < 3:
        return True

    compact = re.sub(r"\s+", "", n)

    if _DIM_ONLY_STRUCTURE_INLINE.match(compact):
        return True

    if _looks_like_length_or_dimension_metadata(compact):
        return True

    # 仅从「括号价」断层里切出的「+)配件」拼接头
    if re.match(r"^[+＋]", n.strip()):
        return True
    if re.search(r"[)）]\s*\+", n):
        return True

    # 以「数字+元/+单位」开头的单价残渣，而非物料称谓
    if re.match(r"^\d+(?:\.\d+)?\s*元\s*[/／]", n):
        return True
    if re.fullmatch(
        r"(?:价格|单价|成本|成本参考|价格参考|参考价|报价)\s*(?:为|是|约|大概)?",
        compact,
    ):
        return True

    closes = n.count(")") + n.count("）")
    opens = n.count("(") + n.count("（")
    if closes > opens:
        return True

    return False


def _extract_inline_prices(text: str) -> tuple[list[dict[str, str]], list[Material]]:
    """Walk the free-form 结构说明 paragraph and capture '<material> +
    <price>/<unit>' pairs.

    Strategy: find every price match, then look back from the same sentence
    the price for the closest material-like leading phrase. This handles
    fragments split across commas, brackets and line breaks better than
    a simple sentence split.
    """
    if not text:
        return [], []

    prices: list[dict[str, str]] = []
    materials: list[Material] = []
    seen_names: set[str] = set()
    for price_match in INLINE_PRICE_PATTERN.finditer(text):
        price_text = price_match.group(0)
        leading_window = _inline_price_leading_window(text, price_match.start())
        leading = _trim_leading_for_inline(leading_window)
        if not leading:
            continue
        if _is_spurious_structure_inline_name(leading):
            continue
        if leading in seen_names:
            continue
        seen_names.add(leading)
        prices.append({"name": leading, "unit_price": price_text, "source": "structure_inline"})
        materials.append(
            Material(
                role="结构说明",
                name=leading,
                spec="",
                note=leading_window.strip(),
                inline_price=price_text,
                source="structure_inline",
            )
        )
    return prices, materials


def _inline_price_leading_window(text: str, price_start: int) -> str:
    """Return enough same-sentence text before a price to avoid name truncation."""
    floor = max(0, price_start - 120)
    boundary = max(
        text.rfind("\n", floor, price_start),
        text.rfind("\r", floor, price_start),
        text.rfind("。", floor, price_start),
        text.rfind("；", floor, price_start),
        text.rfind(";", floor, price_start),
    )
    if boundary >= floor:
        floor = boundary + 1
    return text[floor:price_start]


def _trim_leading_for_inline(leading_window: str) -> str:
    """从左至右解析「括号价」左邻文本，析出物料称谓（会先去掉章节序号等噪声）。"""
    fragment = leading_window
    fragment = re.split(r"[\n。;；]", fragment)[-1]
    fragment = fragment.rstrip("（() :：、,，·")
    price_intro_pos = min(
        [p for p in (fragment.find("价格为"), fragment.find("价格"), fragment.find("单价为"), fragment.find("单价"), fragment.find("成本参考"), fragment.find("成本")) if p >= 0],
        default=-1,
    )
    if price_intro_pos > 0:
        fragment = fragment[:price_intro_pos].strip("（() :：、,，·").strip()
        last_split = max(
            fragment.rfind(":"),
            fragment.rfind("："),
        )
    else:
        last_split = max(
            fragment.rfind(","),
            fragment.rfind("，"),
            fragment.rfind("("),
            fragment.rfind("（"),
            fragment.rfind(":"),
            fragment.rfind("："),
        )
    if last_split >= 0:
        fragment = fragment[last_split + 1 :]
    fragment = fragment.strip("（() :：、,，·").strip()
    fragment = fragment.lstrip("+＋)）-/").strip()
    fragment = _strip_leading_section_marker(fragment)
    for marker in ("价格为", "价格", "单价为", "单价", "成本参考", "成本", "参考价", "报价"):
        pos = fragment.find(marker)
        if pos > 0:
            fragment = fragment[:pos].strip("（() :：、,，·").strip()
            break
    fragment = _LEADING_TRIM_PATTERN.sub("", fragment).strip()
    fragment = re.sub(r"\s*[（(](或.*?)[)）]\s*", "", fragment).strip()
    if len(fragment) < 2:
        return ""
    if not re.search(r"[A-Za-z一-鿿0-9]", fragment):
        return ""
    return fragment


def _parse_loose_margin_rate(text: str) -> float | None:
    """Parse a cell like '35', '35%', '0.35' into 0..1."""
    match = re.search(r"-?\d+(?:\.\d+)?", str(text or "").strip())
    if not match:
        return None
    value = float(match.group(0))
    if value > 1:
        value = value / 100.0
    if value < 0:
        return None
    return min(0.99, value)


def _extract_tier_margins_from_section_f(section_f: dict[str, str]) -> dict[int, float]:
    """Pair F 区「数量k」与「利润率k/毛利率k」列，得到数量 -> 毛利率(0-1)。

    表头经 _normalise_key 后形如 数量1、利润率1、毛利率2。
    """
    if not section_f:
        return {}
    slot_qty: dict[str, str] = {}
    slot_margin: dict[str, float] = {}
    for key, value in section_f.items():
        if not key or not value:
            continue
        mq = re.match(r"^数量(\d+)$", key)
        if mq:
            digit = re.search(r"\d+", str(value))
            if digit:
                slot_qty[mq.group(1)] = digit.group(0)
            continue
        mm = re.match(r"^(?:利润率|毛利率|利率)(\d+)$", key)
        if mm:
            parsed = _parse_loose_margin_rate(value)
            if parsed is not None:
                slot_margin[mm.group(1)] = parsed
    out: dict[int, float] = {}
    for slot, qty_s in slot_qty.items():
        if slot not in slot_margin:
            continue
        try:
            out[int(qty_s)] = slot_margin[slot]
        except ValueError:
            continue
    return out


def _extract_quantities(
    section_f: dict[str, str],
    *,
    rows: list[list[str]] | None = None,
) -> tuple[int, ...]:
    quantities: list[int] = []
    sources: list[dict[str, str]] = []
    if section_f:
        sources.append(section_f)
    if rows:
        implicit = _extract_implicit_quantity_section(rows)
        if implicit:
            sources.append(implicit)
    for src in sources:
        for key, value in src.items():
            if not str(key or "").startswith("数量"):
                continue
            match = re.search(r"\d+", str(value))
            if match:
                quantities.append(int(match.group(0)))
    quantities = sorted(set(quantities))
    return tuple(quantities)


def _extract_quote_settings(section_a: dict[str, str]) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for raw_key, value in section_a.items():
        for key_pattern, setting_key in A_KEY_TO_SETTING.items():
            if key_pattern in raw_key:
                settings[setting_key] = value
                break
    margin_value = settings.get("gross_margin_rate")
    if isinstance(margin_value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", margin_value)
        if match:
            num = float(match.group(0))
            settings["gross_margin_rate"] = num / 100 if num > 1 else num

    mlr = settings.get("management_loss_rate")
    if isinstance(mlr, str):
        mm = re.search(r"-?\d+(?:\.\d+)?", mlr.strip())
        if mm:
            num = float(mm.group(0))
            settings["management_loss_rate"] = num / 100 if num > 1 else num
    elif isinstance(mlr, (int, float)) and float(mlr) > 1:
        settings["management_loss_rate"] = float(mlr) / 100.0

    sfx = settings.get("system_overhead_fixed")
    if isinstance(sfx, str):
        sm = re.search(r"-?\d+(?:\.\d+)?", sfx.strip())
        if sm:
            settings["system_overhead_fixed"] = round(float(sm.group(0)), 2)
        else:
            settings.pop("system_overhead_fixed", None)
    elif isinstance(sfx, (int, float)):
        settings["system_overhead_fixed"] = round(float(sfx), 2)
    return settings


_REF_PRICE_PATTERN = re.compile(
    r"(\d+)\s*[个件]?\s*[:：]?\s*"
    r"成本\s*[:：]?\s*([\d.]+)\s*元?"
    r".*?"
    r"(?:利润率\s*(?:按)?\s*([\d.]+)\s*%)?\s*"
    r"报价\s*[:：]?\s*([\d.]+)\s*元?"
)


def _extract_reference_prices(rows: list[list[str]]) -> list[dict[str, Any]]:
    """Pull salesperson-written cost/quote checkpoints from any cell, e.g.
    "500个：成本：361.78元  利润率按35%报价：557元".

    Such lines often live below section G as a self-check, with no fixed
    column. We scan every cell for the pattern and return a structured list
    so the engine can show "reference vs computed" side-by-side.
    """
    found: list[dict[str, Any]] = []
    seen_qty: set[int] = set()
    for row in rows:
        for cell in row:
            text = str(cell or "").strip()
            if not text or "成本" not in text or "报价" not in text:
                continue
            m = _REF_PRICE_PATTERN.search(text)
            if m is None:
                continue
            try:
                qty = int(m.group(1))
                cost = float(m.group(2))
                margin = float(m.group(3)) / 100 if m.group(3) else None
                quote = float(m.group(4))
            except (TypeError, ValueError):
                continue
            if qty in seen_qty:
                continue
            seen_qty.add(qty)
            found.append(
                {
                    "quantity": qty,
                    "cost": round(cost, 2),
                    "margin": margin,
                    "quote": round(quote, 2),
                    "source_text": text,
                }
            )
    found.sort(key=lambda d: d["quantity"])
    return found


_SPLIT_COST_RE = re.compile(r"成本\s*([0-9]+(?:\.[0-9]+)?)\s*$", re.I)
_SPLIT_QUOTE_RE = re.compile(r"([0-9]+)\s*[个件]\s*报\s*价\s*([0-9]+(?:\.[0-9]+)?)\s*元?", re.I)


def _looks_like_salesperson_hand_cost_sheet(rows: list[list[str]]) -> bool:
    """Detect the common yellow-cell hand calculation block.

    These demand templates often carry a salesperson's hand cost such as
    "成本13.73" and "1000个报价19.9元" in separate cells. In that business
    convention the overhead is normally a material-management loss rate,
    not the engine's fixed 4 RMB/pc default.
    """
    has_cost = False
    has_quote = False
    for row in rows:
        for cell in row:
            text = str(cell or "").replace("\n", "").replace(" ", "").strip()
            if not text or len(text) > 60:
                continue
            if _SPLIT_COST_RE.search(text):
                has_cost = True
            if _SPLIT_QUOTE_RE.search(text):
                has_quote = True
            if has_cost and has_quote:
                return True
    return False


_AUX_BOM_SHEET_NAME_KEYWORDS = (
    "物料明细",
    "物料展开",
    "材料明细",
    "材料表",
    "展开料",
    "料单",
    "报价明细",
    "成本展开",
    "bom",
)


def _aux_bom_sheet_name_hit(sheet_name: str) -> bool:
    name = sheet_name.strip().lower()
    return any(kw in name for kw in _AUX_BOM_SHEET_NAME_KEYWORDS)


def _parse_money_number_token(tok: str) -> float | None:
    cleaned = tok.replace(",", "").replace("，", "").strip()
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except (TypeError, ValueError):
        return None


def _extract_sheet_material_subtotal_anchors(rows: list[list[str]]) -> list[dict[str, Any]]:
    """从手写区格子抓取「底料 / 物料合计」等单行金额锚点（不含件数梯度那种整句）。"""
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("底料", re.compile(r"底料\s*[：:=＝]?\s*([\d,.]+)", re.I)),
        ("物料合计", re.compile(r"物料\s*合计\s*[：:=＝]?\s*([\d,.]+)", re.I)),
        ("物料小计", re.compile(r"物料\s*小计\s*[：:=＝]?\s*([\d,.]+)", re.I)),
        ("材料合计", re.compile(r"材料\s*合计\s*[：:=＝]?\s*([\d,.]+)", re.I)),
        ("材料小计", re.compile(r"材料\s*小计\s*[：:=＝]?\s*([\d,.]+)", re.I)),
    )
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for row in rows:
        for cell in row:
            text = str(cell or "").strip()
            if len(text) > 140:
                continue
            if _REF_PRICE_PATTERN.search(text):
                continue
            compact = text.replace(" ", "")
            for label, rx in patterns:
                match = rx.search(compact)
                if not match:
                    continue
                amount = _parse_money_number_token(match.group(1))
                if amount is None or amount <= 0:
                    continue
                key = (label, amount)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "kind": "sheet_material_subtotal",
                        "anchor_label": label,
                        "material_subtotal": amount,
                        "source_text": text,
                    }
                )
    return out


def extend_materials_dedupe_by_name(primary: list[Material], additions: list[Material]) -> list[Material]:
    """辅 sheet 补行：按物料名字归一化去重（与结构说明补足策略一致）。"""
    merged = list(primary)
    keys = {_squeeze_material_name_key(m.name) for m in primary if str(m.name or "").strip()}
    for m in additions:
        sk = _squeeze_material_name_key(m.name)
        if len(sk) < 2:
            continue
        if sk in keys:
            continue
        keys.add(sk)
        merged.append(m)
    return merged


def _fabric_family_token_for_merge(name: str) -> str:
    """将「DCF外料 / 主面料DCF / 1.43oz …」归为同一主料族，便于细表并入 C 格。"""
    sk = _squeeze_material_name_key(name)
    if not sk:
        return ""
    compact = sk.replace(".", "").replace("№", "")
    if any(
        x in compact
        for x in (
            "dcf",
            "dch",
            "143oz",
            "143",
            "32oz",
            "粗苯",
        )
    ):
        return "DYNEEMA_FAB"
    if "xpac" in compact or "vx21" in compact or "x-pac" in str(name).replace(" ", "").lower():
        return "XPAC"
    return ""


_PLACEHOLDER_QUOT_USAGE = re.compile(
    r"^\s*(1\s*套|1\s*[Pp][Cc][Ss]?|1\s*件|1(?:\.0)?\s*码|1\s*[Mm]|1\s*米)\s*$",
    re.I,
)


def _is_placeholder_quotation_usage(text: str) -> bool:
    u = str(text or "").strip()
    if not u:
        return True
    return bool(_PLACEHOLDER_QUOT_USAGE.match(u))


def absorb_quotation_detail_into_demand_fabric_rows(materials: list[Material]) -> list[Material]:
    """细表中带「报价用量」的 DCF 等行并入需求表主料行，去掉重复整码计价。"""
    detail_ix = [
        i
        for i, m in enumerate(materials)
        if str(m.source or "").startswith("bom_detail:")
        and str(getattr(m, "quoted_usage", "") or "").strip()
    ]
    if not detail_ix:
        return materials
    removals: set[int] = set()
    for di in detail_ix:
        if di in removals:
            continue
        dm = materials[di]
        tok_d = _fabric_family_token_for_merge(dm.name)
        if not tok_d:
            continue
        absorbed = False
        for pi, pm in enumerate(materials):
            if pi == di or pi in removals:
                continue
            if str(pm.source or "").startswith("bom_detail:"):
                continue
            if _fabric_family_token_for_merge(pm.name) != tok_d:
                continue
            pq = str(getattr(pm, "quoted_usage", "") or "").strip()
            have_real_usage = pq and not _is_placeholder_quotation_usage(pq)
            if have_real_usage:
                # C 格已填实用量时仍并入细表「计算方式」，并去掉重复的细表主料行
                if dm.calc_method and not str(getattr(pm, "calc_method", "") or "").strip():
                    pm.calc_method = dm.calc_method.strip()
                if dm.sheet_amount_unit and not str(getattr(pm, "sheet_amount_unit", "") or "").strip():
                    pm.sheet_amount_unit = dm.sheet_amount_unit.strip()
                removals.add(di)
                absorbed = True
                break
            pm.quoted_usage = dm.quoted_usage.strip()
            if dm.calc_method:
                pm.calc_method = dm.calc_method.strip()
            if dm.sheet_amount_unit:
                pm.sheet_amount_unit = dm.sheet_amount_unit.strip()
            if dm.inline_price and (not pm.inline_price or pm.inline_price == "-"):
                pm.inline_price = dm.inline_price
            removals.add(di)
            absorbed = True
            break
        if not absorbed:
            continue
    if not removals:
        return materials
    return [m for i, m in enumerate(materials) if i not in removals]


def materials_from_rows_quotation_detail_block(
    rows: list[list[str]],
    *,
    sheet_slug: str,
) -> list[Material]:
    """同一张需求表里若另有「报价用量+计算方式」报价明细区块，一并解析。"""
    from quotation_detail_table import (
        find_quotation_detail_header_row,
        parse_quotation_detail_rows,
        quotation_detail_rows_to_material_dicts,
    )

    hi = find_quotation_detail_header_row(rows)
    if hi is None:
        return []
    dr_list = parse_quotation_detail_rows(rows, header_index=hi)
    if not dr_list:
        return []
    slug_base = (sheet_slug or "").strip() or "(main)"
    out: list[Material] = []
    for blob in quotation_detail_rows_to_material_dicts(dr_list, sheet_slug=slug_base):
        out.append(
            Material(
                role=str(blob["role"]),
                name=str(blob["name"]),
                spec=str(blob.get("spec") or "-"),
                note=str(blob.get("note") or ""),
                inline_price=str(blob.get("inline_price") or ""),
                source=str(blob["source"]),
                quoted_usage=str(blob.get("quoted_usage") or ""),
                calc_method=str(blob.get("calc_method") or ""),
                sheet_amount_unit=str(blob.get("sheet_amount_unit") or ""),
            )
        )
    return out


def collect_quotation_detail_materials_from_xlsx(
    file_bytes: bytes,
    main_sheet_name: str,
    *,
    file_name: str = "",
    scan_all_sheets: bool = False,
) -> tuple[list[Material], list[str]]:
    from quotation_detail_table import (
        find_quotation_detail_header_row,
        parse_quotation_detail_rows,
        quotation_detail_rows_to_material_dicts,
    )

    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        return [], []

    shared_strings = read_shared_strings(archive)
    sheets = read_sheet_entries(archive)
    main_norm = (main_sheet_name or "").strip()
    out: list[Material] = []
    names: list[str] = []

    for sheet_name, sheet_xml in sheets:
        if not scan_all_sheets:
            if main_norm and sheet_name.strip() == main_norm:
                continue
        rows = normalize_rows(parse_sheet_xml_rows(sheet_xml, shared_strings))
        hi = find_quotation_detail_header_row(rows)
        if hi is None:
            continue
        dr_list = parse_quotation_detail_rows(rows, header_index=hi)
        if not dr_list:
            continue
        slug = sheet_name.strip() or "(detail)"
        for blob in quotation_detail_rows_to_material_dicts(dr_list, sheet_slug=slug):
            out.append(
                Material(
                    role=str(blob["role"]),
                    name=str(blob["name"]),
                    spec=str(blob.get("spec") or "-"),
                    note=str(blob.get("note") or ""),
                    inline_price=str(blob.get("inline_price") or ""),
                    source=str(blob["source"]),
                    quoted_usage=str(blob.get("quoted_usage") or ""),
                    calc_method=str(blob.get("calc_method") or ""),
                    sheet_amount_unit=str(blob.get("sheet_amount_unit") or ""),
                )
            )
        names.append(sheet_name)

    return out, names


def enrichment_calc_maps_from_materials(materials: list[Material]) -> tuple[dict[str, str], dict[str, str]]:
    """名称归一化 / 主料族 → 最长的「计算方式」文案。"""
    name_best: dict[str, str] = {}
    name_score: dict[str, int] = {}
    fam_best: dict[str, str] = {}
    fam_score: dict[str, int] = {}

    for m in materials:
        calc = str(m.calc_method or "").strip()
        if not calc:
            continue

        nk = _squeeze_material_name_key(m.name)
        if len(nk) >= 2:
            sc = len(calc)
            if sc > name_score.get(nk, -1):
                name_score[nk] = sc
                name_best[nk] = calc

        ft = _fabric_family_token_for_merge(m.name)
        if ft:
            sc = len(calc)
            if sc > fam_score.get(ft, -1):
                fam_score[ft] = sc
                fam_best[ft] = calc

    return name_best, fam_best


def _is_placeholder_calc_note_text(note: object) -> bool:
    """与 server._is_generic_calc_note 对齐：模型/引擎占位「计算方式」可被明细表或结构说明覆盖。"""
    text = str(note or "").strip()
    if not text:
        return True
    hints = (
        "未见「计算方式」",
        "数据源不含「计算方式」",
        "用量为 ai 估计",
        "小计=单价×用量",
        "面料类：",
        "配件类：",
        "面积类单价：",
        "请按袋口/开孔",
        "请以业务 bom",
        "分项说明未带入",
        "粗略估用量",
        "本条用量为 ai 估算",
        "请以业务员 bom",
        "构件分项未载入",
        "按表内用量×单价",
        "若要按开孔",
    )
    lowered = text.lower()
    return any(h.lower() in lowered for h in hints)


_MEASURE_HINT_RE = re.compile(
    r"(?:"
    r"\d+(?:\.\d+)?\s*(?:cm|CM|mm|MM|码(?!²)|％|%)"
    r"|(?:圆周|周长|袋口|通道|侧缝)[^。；\n]{0,14}?\d+(?:\.\d+)?\s*(?:cm|CM|mm|MM|码)?"
    r")",
)
_BOM_SHAPE_KEYWORDS = (
    "侧片",
    "底片",
    "压胶",
    "圆周",
    "周长",
    "袋口",
    "通道",
    "侧缝",
    "损耗",
    "耗损",
    "展开",
    "余量",
    "摊销",
    "同面料",
    "几处",
)


def sentence_bom_style_score(sentence: str) -> int:
    """越高越接近业务员细表「构件+取样+数字+损耗」口径（区别于说明文/套话）。"""
    s = str(sentence or "").strip()
    if not s:
        return -20
    if _is_placeholder_calc_note_text(s):
        return -15
    sc = 0
    if _MEASURE_HINT_RE.search(s):
        sc += 5
    if re.search(r"\d+\s*(?:％|%)", s):
        sc += 3
    if "+" in s or "＋" in s:
        sc += 2
    for k in _BOM_SHAPE_KEYWORDS:
        if k in s:
            sc += 1
    narrative = (
        ("采用" in s or "设置了" in s or "置于" in s)
        and not _MEASURE_HINT_RE.search(s)
        and "+" not in s
    )
    if narrative:
        sc -= 8
    if len(s) > 130 and not _MEASURE_HINT_RE.search(s) and ("+" not in s and "＋" not in s):
        sc -= 4
    return sc


def calc_note_looks_like_bom_sheet(note: str) -> bool:
    """与图二一致的「分项+取样关系+损耗/余量」细表措辞（非免责套话、非长篇说明文）。"""
    t = str(note or "").strip()
    if not t or _is_placeholder_calc_note_text(t):
        return False
    if _MEASURE_HINT_RE.search(t):
        return True
    if re.search(r"\d+\s*(?:％|%)", t) and any(k in t for k in ("损耗", "耗损")):
        return True
    if ("+" in t or "＋" in t) and any(k in t for k in ("侧片", "底片", "压胶", "圆周", "周长", "袋口")):
        return True
    if any(k in t for k in ("按要求计算", "见工艺", "见纸样")) and len(t) <= 48:
        return True
    return False


def should_prefer_calc_note_incoming(existing: str, incoming: str) -> bool:
    """合并 Kimi / 摘录文案时：优先保留已像图二的行，占位与说明文可被更「细表化」条目替换。"""
    ex = str(existing or "").strip()
    inc = str(incoming or "").strip()
    if not inc:
        return False
    if not ex:
        return True
    if _is_placeholder_calc_note_text(ex):
        if not _is_placeholder_calc_note_text(inc):
            return True
        return sentence_bom_style_score(inc) > sentence_bom_style_score(ex)
    if _is_placeholder_calc_note_text(inc):
        return False
    ex_bom = calc_note_looks_like_bom_sheet(ex)
    inc_bom = calc_note_looks_like_bom_sheet(inc)
    if ex_bom and not inc_bom:
        return False
    if inc_bom and not ex_bom:
        return True
    if inc_bom and ex_bom:
        ex_m = bool(_MEASURE_HINT_RE.search(ex))
        in_m = bool(_MEASURE_HINT_RE.search(inc))
        if in_m and not ex_m:
            return True
        if sentence_bom_style_score(inc) > sentence_bom_style_score(ex) + 1:
            return True
        return False
    return sentence_bom_style_score(inc) > sentence_bom_style_score(ex)


def _split_structure_text_chunks(structure_text: str) -> list[str]:
    parts = re.split(r"[\n\r]+|[；;]+", structure_text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 10]


def _sentence_has_structure_geometry(sentence: str) -> bool:
    keys = (
        "侧片",
        "圆筒",
        "底片",
        "压胶",
        "袋口",
        "圆周",
        "周长",
        "损耗",
        "耗损",
        "拼接",
        "开口",
        "通道",
        "抽绳",
        "打结",
        "+",
        "＋",
        "×",
        "展开",
        "贴合",
        "收纳",
        "卷口",
        "主仓",
        "前置",
        "前舱",
        "贴片",
        "防水拉",
        "防水层",
        "紧固",
        "收口",
        "夹层",
        "内里",
        "三明治",
        "三明治网",
        "三明治布",
        "肩带贴",
        "贴面",
    )
    if any(k in sentence for k in keys):
        return True
    if re.search(r"\d\s*(?:cm|CM|mm|MM|米|码)", sentence):
        return True
    # 「物料名：共N个 / 总长度…」类辅料用量说明（B260169 等需求表结构块）
    if re.match(r"^[^：:\n]{2,32}[：:]", sentence) and re.search(
        r"(?:共\s*\d+\s*个|总长度|总长约|用量约|\d\s*(?:cm|CM|mm|MM|米|码))",
        sentence,
    ):
        return True
    return False


def _structure_geometry_sentences(structure_text: str) -> list[str]:
    out: list[str] = []
    for chunk in _split_structure_text_chunks(structure_text):
        if _sentence_has_structure_geometry(chunk):
            out.append(chunk[:320])
    return out


def _structure_sentence_leading_label(sentence: str) -> str:
    """结构句冒号前的主语，如「仿尼龙织带：总长度…」→「仿尼龙织带」。"""
    s = str(sentence or "").strip()
    m = re.match(r"^([^：:\n]{2,32}?)[：:]", s)
    if m:
        return m.group(1).strip()
    return ""


def _score_structure_label_for_name(name: str, label: str) -> int:
    """带冒号主语的句子与 BOM 行名称的专名匹配分。"""
    nm = str(name or "").strip()
    lb = str(label or "").strip()
    if not nm or not lb:
        return 0
    if lb in nm or nm in lb:
        return 30
    if "YKK" in lb.upper() and "YKK" in nm.upper():
        return 28
    if "拉链" in lb and "拉链" in nm and "织带" not in nm:
        return 22
    if any(k in lb for k in ("织带", "背带", "坑带", "绑绳")) and any(
        k in nm for k in ("织带", "背带", "坑带", "肩带", "绳带")
    ):
        return 28
    if any(k in lb for k in ("扣具", "插扣", "日字扣", "POM", "D型", "三角")) and any(
        k in nm for k in ("扣", "多耐福")
    ):
        return 26
    if "拉头" in lb and "拉头" in nm:
        return 26
    if "X-PAC" in lb.upper() and ("X-PAC" in nm.upper() or "XPAC" in nm.upper()):
        return 26
    if "内衬" in lb and any(k in nm for k in ("里料", "内衬", "210D", "涤纶", "尼龙")):
        return 18
    return 0


def _structure_label_blocks_name(name: str, label: str) -> bool:
    """句子已点名另一物料族时，禁止挂到当前行。"""
    nm = str(name or "").strip()
    lb = str(label or "").strip()
    if not nm or not lb:
        return False
    if _score_structure_label_for_name(nm, lb) >= 20:
        return False
    is_zipper = "拉链" in nm and "织带" not in nm
    is_webbing = any(k in nm for k in ("织带", "坑带", "背带", "肩带", "绳带")) and "拉链" not in nm
    is_slider = "拉头" in nm
    is_buckle = any(k in nm for k in ("扣", "多耐福"))
    label_webbing = any(k in lb for k in ("织带", "背带", "坑带", "绑绳", "绳带"))
    label_zipper = "拉链" in lb or "YKK" in lb.upper()
    label_buckle = any(k in lb for k in ("扣具", "插扣", "日字扣", "POM", "D型", "三角"))
    label_slider = "拉头" in lb
    if label_webbing and (is_zipper or is_slider):
        return True
    if label_zipper and is_webbing:
        return True
    if label_buckle and not is_buckle:
        return True
    if label_slider and not is_slider:
        return True
    return False


def _preassign_labeled_structure_sentences(
    rows: list[Any],
    sentences: list[str],
) -> tuple[dict[int, str], set[str]]:
    """优先把「物料名：…」结构句绑定到同名/同族行，避免被其它行抢占。"""
    preassigned: dict[int, str] = {}
    used: set[str] = set()
    for sent in sentences:
        label = _structure_sentence_leading_label(sent)
        if not label or sent in used:
            continue
        best_i = -1
        best_sc = 0
        for i, raw in enumerate(rows):
            if not isinstance(raw, dict) or i in preassigned:
                continue
            nm = str(raw.get("name") or "")
            sc = _score_structure_label_for_name(nm, label)
            if sc > best_sc:
                best_sc = sc
                best_i = i
        if best_i >= 0 and best_sc >= 20:
            preassigned[best_i] = sent
            used.add(sent)
    return preassigned, used


def _score_structure_sentence_for_name(name: str, sentence: str) -> int:
    score = 0
    nm = name.strip()
    su_u = sentence.upper()
    su_l = sentence.lower()
    label = _structure_sentence_leading_label(sentence)
    if label:
        if _structure_label_blocks_name(nm, label):
            return -40
        label_sc = _score_structure_label_for_name(nm, label)
        if label_sc:
            score += label_sc
    is_zipper_like = any(k in nm for k in ("拉链", "拉头", "拉片"))
    is_webbing_like = any(k in nm for k in ("织带", "坑带", "背带", "绳带"))
    # 避免「收纳系统…拉链…」长段套到拉头/织带等非主拉链行
    if "拉头" in nm or ("拉片" in nm and "拉头" not in nm):
        if any(k in sentence for k in ("拉头", "拉链头")):
            score += 12
        elif re.search(r"(?<![链])拉片", sentence):
            score += 8
        elif re.search(r"[三二三四五六七八九十两]\s*个|[\d.]+\s*[Pp][Cc]", sentence):
            if any(k in sentence for k in ("拉头", "拉链头", "拉片")) or re.search(
                r"拉头[^。，；]{0,12}[三二三四五六七八九十两\d]\s*个", sentence
            ):
                score += 5
        if "拉头" in nm and any(
            k in sentence for k in ("主仓", "隔层", "收纳区", "平板电脑", "网兜结构")
        ) and "拉头" not in sentence:
            score -= 18
        if "收纳" in sentence and "系统" in sentence and "拉头" not in sentence:
            score -= 10
        if label and _structure_label_blocks_name(nm, label):
            score -= 20
    if is_webbing_like and "拉头" not in nm:
        if any(k in sentence for k in ("织带", "背带", "坑带", "束口", "扣固定")):
            score += 8
        if "拉链" in sentence and ("织带" not in sentence and "背带" not in sentence and "收紧" not in sentence):
            score -= 6
    if "ULTRA" in nm.upper() and "ULTRA" in su_u:
        score += 10
    elif "ULTRA" in nm.upper() and any(k in sentence for k in ("侧片", "底片", "圆筒", "压胶", "展开")):
        score += 7
    if _mentions_xpac(nm):
        if _mentions_xpac(sentence) or "VX21" in su_u or "VX42" in su_u:
            score += 10
    if _mentions_dch_or_dcf(nm) and _mentions_dch_or_dcf(sentence):
        score += 10
    if "拉链" in nm and ("拉链" in sentence or "防水拉" in sentence):
        if not (label and any(k in label for k in ("织带", "背带", "坑带", "绑绳"))):
            if not (label and _structure_label_blocks_name(nm, label)):
                score += 8
    if "绳" in nm and "拉链" not in nm and "绳" in sentence:
        score += 6
    if any(k in nm for k in ("扣", "多耐福")) and any(k in sentence for k in ("扣", "抽绳", "束口")):
        score += 5
    if score == 0 and any(k in nm for k in ("面料", "主料", "辅料", "外料")):
        if any(k in sentence for k in ("侧片", "底片", "圆筒", "压胶", "裁片", "展开")):
            score += 4
    if "尼龙" in nm and is_webbing_like and not is_zipper_like and any(k in sentence for k in ("织带", "坑带", "背带")):
        score += 5
    if ("胶" in nm or "glue" in su_l) and ("缝" in sentence or "圆周" in sentence or "cm" in su_l):
        score += 4
    return score


def _pick_structure_sentence_for_material(
    name: str,
    sentences: list[str],
    *,
    skip: set[str] | None = None,
) -> str:
    sk = skip or set()
    best = ""
    best_sc = 0
    for sent in sentences:
        if sent in sk:
            continue
        label = _structure_sentence_leading_label(sent)
        if label and _structure_label_blocks_name(name, label):
            continue
        bom_sc = sentence_bom_style_score(sent)
        sc = _score_structure_sentence_for_name(name, sent) + max(0, bom_sc)
        # 构件名弱匹配但句子本身已是「尺寸+分项」细表措辞时仍可采纳
        if sc <= 0 and bom_sc < 4:
            continue
        if sc > best_sc or (sc == best_sc and len(sent) > len(best)):
            best_sc = sc
            best = sent
    if not best:
        return ""
    if best_sc >= 3 or sentence_bom_style_score(best) >= 5:
        return best
    return ""


def _merge_calc_note_dedupe(existing: str, incoming: str) -> str:
    """表格明细与结构说明重叠时只保留一条完整表述。"""
    a = existing.strip()
    b = incoming.strip()
    if not b:
        return a[:260]
    if not a:
        return b[:260]

    def norm(x: str) -> str:
        return re.sub(r"\s+", "", x)

    na, nb = norm(a), norm(b)
    if nb in na:
        return a[:260]
    if na in nb:
        return b[:260]
    return a[:260]


def enrich_items_calc_note_from_structure(
    rows: list[dict[str, Any]],
    structure_text: str,
) -> list[dict[str, Any]]:
    """从「结构说明」抽取构件分拆句写入 calc_note；与表格已有「计算方式」去重合并。"""
    sentences = _structure_geometry_sentences(structure_text)
    if not sentences:
        return rows
    preassigned, used = _preassign_labeled_structure_sentences(rows, sentences)
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(rows):
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        r = dict(raw)
        have = str(r.get("calc_note") or r.get("calc_method") or "").strip()
        # 已为图二细表措辞时不再混入结构说明长句，以免污染「计算方式」列。
        if calc_note_looks_like_bom_sheet(have):
            out.append(r)
            continue

        pick = preassigned.get(idx, "")
        if not pick:
            pick = _pick_structure_sentence_for_material(
                str(r.get("name") or ""),
                sentences,
                skip=used,
            )
        if pick and sentence_bom_style_score(pick) < 1 and len(pick) > 72:
            lb = _structure_sentence_leading_label(pick)
            if not (
                lb
                and _score_structure_label_for_name(str(r.get("name") or ""), lb) >= 20
            ):
                pick = ""

        if not pick:
            out.append(r)
            continue
        used.add(pick)

        if not have or _is_placeholder_calc_note_text(have):
            r["calc_note"] = pick[:260]
        else:
            if should_prefer_calc_note_incoming(have, pick[:260]):
                r["calc_note"] = pick[:260]
            else:
                r["calc_note"] = _merge_calc_note_dedupe(have, pick)
        out.append(r)
    return out


def enrich_quote_item_rows_with_quotation_calc(
    rows: list[dict[str, Any]],
    materials: list[Material],
) -> list[dict[str, Any]]:
    """把报价明细 workbook 解析出的文案补进 BOM items（占位/空文案可被覆盖）。"""
    if not rows or not materials:
        return rows
    name_best, fam_best = enrichment_calc_maps_from_materials(materials)
    if not name_best and not fam_best:
        return rows

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        r = dict(row)
        have = str(r.get("calc_note") or r.get("calc_method") or "").strip()
        if have and not _is_placeholder_calc_note_text(have):
            out.append(r)
            continue
        nm = str(r.get("name") or "").strip()
        nk = _squeeze_material_name_key(nm)
        injected = ""
        if nk:
            injected = name_best.get(nk, "")
        if not injected:
            ftok = _fabric_family_token_for_merge(nm)
            if ftok:
                injected = fam_best.get(ftok, "")
        if not injected and len(nk) >= 4:
            best_sub = ""
            best_sub_len = 0
            for dk, dv in name_best.items():
                if len(dk) < 4:
                    continue
                if dk in nk or nk in dk:
                    if len(dv) > best_sub_len:
                        best_sub_len = len(dv)
                        best_sub = dv
            injected = best_sub
        if injected:
            r["calc_note"] = injected
        out.append(r)
    return out


def quotation_detail_materials_bundle_from_entire_xlsx(file_bytes: bytes) -> list[Material]:
    """遍历工作簿全部 Sheet（不按主表排除），抓取所有「报价明细」块。"""
    mats, _ = collect_quotation_detail_materials_from_xlsx(
        file_bytes,
        "",
        scan_all_sheets=True,
    )
    return mats


def collect_auxiliary_bom_materials_from_xlsx(
    file_bytes: bytes,
    main_sheet_name: str,
    *,
    file_name: str = "",
) -> tuple[list[Material], list[str]]:
    """扫描同工作簿内其它 sheet：简单 BOM 版式（类型/说明/单价）且不像另一张需求表的，并入物料清单。"""
    from simple_bom_parser import is_simple_bom_template, parse_simple_bom_from_rows

    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        return [], []

    shared_strings = read_shared_strings(archive)
    sheets = read_sheet_entries(archive)
    main_norm = (main_sheet_name or "").strip()
    extras: list[Material] = []
    merged_names: list[str] = []

    for sheet_name, sheet_xml in sheets:
        if sheet_name.strip() == main_norm:
            continue
        rows = normalize_rows(parse_sheet_xml_rows(sheet_xml, shared_strings))
        if not is_simple_bom_template(rows):
            continue
        markers = _count_titled_section_markers(rows)
        # 另一类「填写区」多节标题与需求表相像，markers 多时保守跳过。
        if markers >= 4:
            continue
        if markers >= 2 and not _aux_bom_sheet_name_hit(sheet_name):
            continue
        try:
            parsed = parse_simple_bom_from_rows(rows, file_name=file_name, sheet_name=sheet_name)
        except SheetParseError:
            continue
        if not parsed.materials:
            continue
        slug = sheet_name.strip() or "(sheet)"
        for sm in parsed.materials:
            extras.append(
                Material(
                    role=sm.role,
                    name=sm.name,
                    spec=sm.spec or "",
                    note="",
                    inline_price=sm.unit_price or "",
                    source=f"bom_sheet:{slug}",
                )
            )
        merged_names.append(sheet_name)

    return extras, merged_names


def map_complexity_text_to_processing_fee(raw: str) -> float | None:
    """需求表 B 区「结构复杂度」只作为加工费基准，不再直接锁死最终值。"""
    text = str(raw or "").strip()
    if not text:
        return None
    if any(k in text for k in ("户外", "特殊场景", "特种", "极端", "专业户外")):
        return 42.0
    if any(k in text for k in ("复杂", "高难度", "高难")):
        return 24.0
    if any(k in text for k in ("中等", "标准", "中度", "中级", "常规")):
        return 14.0
    if any(k in text for k in ("简单", "简易", "基础", "低难", "入门")):
        return 7.5
    return None


_COMPLEXITY_HEADER_HINTS = ("结构复杂度", "工艺难度", "难度", "款式难度", "加工难度")


def processing_fee_from_section_b_complexity(section_b: dict[str, str]) -> float | None:
    for key, val in section_b.items():
        if not val or not str(val).strip():
            continue
        k = str(key)
        if any(h in k for h in _COMPLEXITY_HEADER_HINTS):
            fee = map_complexity_text_to_processing_fee(val)
            if fee is not None:
                return fee
    return None


def structure_complexity_label_from_section_b(section_b: dict[str, str]) -> str:
    """B 区与难度相关的格子原文，供 Kimi 在「未锁加工费」时对齐区间或辅助判断。"""
    for key, val in section_b.items():
        if not val or not str(val).strip():
            continue
        k = str(key)
        if any(h in k for h in _COMPLEXITY_HEADER_HINTS):
            return str(val).strip()
    return ""


def resolve_demand_processing_fee(
    sections: dict[str, dict[str, str]],
    structure_text: str,
) -> tuple[float | None, bool, str]:
    """(fee, locked, rule_key)。

    加工费不再由「标准/中等」这类粗标签锁死；系统先按结构说明、配件和工艺
    做一版可追溯评估，再允许视觉/模型阶段继续修正。
    """
    explicit = extract_processing_fee_hint(sections, structure_text)
    assessed = assess_processing_fee_from_structure(sections, structure_text)
    if assessed is not None:
        return assessed, False, "structure_assessment"
    if explicit is not None:
        return explicit, False, "explicit_yuan_hint"
    fee_c = processing_fee_from_section_b_complexity(sections.get("B", {}))
    if fee_c is not None:
        return fee_c, False, "table_complexity_hint"
    return None, False, ""


def assess_processing_fee_from_structure(
    sections: dict[str, dict[str, str]],
    structure_text: str,
) -> float | None:
    """Score sewing/assembly difficulty from structure details and material slots."""
    section_b = sections.get("B", {}) or {}
    section_c = sections.get("C", {}) or {}
    section_d = sections.get("D", {}) or {}
    label = structure_complexity_label_from_section_b(section_b)
    base = map_complexity_text_to_processing_fee(label)
    blob = "\n".join(
        [
            str(structure_text or ""),
            " ".join(str(v or "") for v in section_b.values()),
            " ".join(str(v or "") for v in section_c.values()),
            " ".join(str(v or "") for v in section_d.values()),
        ]
    )
    if not blob.strip() and base is None:
        return None

    score = _processing_complexity_score(blob, section_c, section_d)
    if base is None:
        base = 10.0
    if base >= 40:
        fee = base + score * 0.75
        lo, hi = 40.0, 60.0
    elif base >= 22:
        fee = base + score * 0.85
        lo, hi = 20.0, 40.0
    elif base >= 12:
        fee = base + score * 0.30
        lo, hi = 10.0, 26.0
    else:
        fee = base + score * 0.45
        lo, hi = 5.0, 18.0

    # A "standard" label can still move into the low-complex range when the
    # actual structure has luggage-style opening, multiple inner systems, etc.
    if score >= 12 and fee < 21.0:
        fee = 21.0
    small_cap = _small_soft_bag_processing_fee_cap(section_b, structure_text)
    if small_cap is not None and fee > small_cap:
        fee = small_cap
    fee = max(lo, min(hi, fee))
    return round(fee * 2) / 2


def _small_soft_bag_processing_fee_cap(
    section_b: dict[str, str],
    structure_text: str,
) -> float | None:
    """Small pouch/sling styles should not be priced like luggage/backpacks.

    The description may list many hardware/strap details, but when the body is
    around 21x12x6cm the labor band is still a compact soft-bag band. Keep the
    cap as an upper guardrail only; explicit processing-fee hints still flow
    through resolve_demand_processing_fee separately.
    """
    size = _extract_product_size(section_b)
    if not size:
        return None
    vals = [float(v) for v in size.values() if float(v or 0) > 0]
    if len(vals) < 3:
        return None
    largest = max(vals)
    smallest = min(vals)
    volume = vals[0] * vals[1] * vals[2]
    blob = (
        str(structure_text or "")
        + " "
        + " ".join(str(v or "") for v in section_b.values())
    )
    small_hint = any(k in blob for k in ("斜挎", "腰包", "小包", "胸包", "手拿", "零钱", "收纳包"))
    luggage_hint = any(k in blob for k in ("双肩", "背包", "行李", "拉杆", "登山", "户外大包"))
    if largest <= 32 and smallest <= 16 and volume <= 9000 and small_hint and not luggage_hint:
        return 14.0
    return None


def _processing_complexity_score(
    blob: str,
    section_c: dict[str, str],
    section_d: dict[str, str],
) -> float:
    text = re.sub(r"\s+", "", str(blob or ""))
    score = 0.0
    weighted_patterns: tuple[tuple[str, float], ...] = (
        (r"180°|全开|行李舱|拉杆箱", 3.0),
        (r"环绕|绕整个包口|一圈|长拉链|主仓拉链", 2.0),
        (r"分层|隔层|主隔舱|收纳", 2.0),
        (r"内袋|口袋|插袋|拉链袋|小袋|网眼袋|网袋", 1.5),
        (r"背板|泡棉|垫带|肩垫|双肩", 2.5),
        (r"侧收缩|收缩带|调节扣|插扣", 1.5),
        (r"Molle|织带|绑带|固定带", 1.5),
        (r"加固|防磨|包边", 1.2),
        (r"丝印|LOGO|logo|标识", 1.0),
        (r"扣具|D环|方扣|拉头", 1.2),
        (r"复合|填充|泡棉填充|内含", 1.5),
    )
    for pattern, weight in weighted_patterns:
        if re.search(pattern, text, re.I):
            score += weight

    # Count repeated structure features, but cap each family to avoid runaway.
    repeated_terms: tuple[tuple[str, float, float], ...] = (
        ("拉链", 0.4, 2.0),
        ("织带", 0.35, 1.6),
        ("扣", 0.25, 1.5),
        ("袋", 0.25, 1.5),
    )
    for term, each, cap in repeated_terms:
        score += min(cap, text.count(term) * each)

    material_slots = 0
    for key, value in section_c.items():
        if not str(value or "").strip():
            continue
        k = str(key)
        if any(h in k for h in ("外料", "里料", "拉链", "拉头", "扣具", "织带", "肩带", "包边")):
            material_slots += 1
    score += min(3.0, material_slots * 0.35)

    craft_hits = 0
    for value in section_d.values():
        v = str(value or "")
        if v.strip():
            craft_hits += len([p for p in re.split(r"[;；,，/、\s]+", v) if p.strip()])
    score += min(2.0, craft_hits * 0.6)
    return score


# Free-text hints for quote engine overrides (¥/pc) often embedded only in prose.
_PROCESSING_FEE_PATTERNS = (
    re.compile(r"加工费\D{0,16}(\d+(?:\.\d+)?)\s*元\s*[/／]?\s*件"),
    re.compile(r"加工费\D{0,16}(\d+(?:\.\d+)?)\s*元"),
    re.compile(r"单件加工费\D{0,10}(\d+(?:\.\d+)?)\s*元?"),
)


def extract_processing_fee_hint(
    sections: dict[str, dict[str, str]],
    structure_text: str,
) -> float | None:
    """若结构说明或各区块写有「加工费 … 元/件」，覆盖引擎默认加工费以减少与手算表偏差。"""
    parts: list[str] = []
    if structure_text and str(structure_text).strip():
        parts.append(str(structure_text))
    for sec in sections.values():
        for key, val in sec.items():
            if not val or not str(val).strip():
                continue
            text_k = str(key or "")
            text_v = str(val)
            if "加工费" in text_k or "加工费" in text_v:
                parts.append(f"{text_k} {text_v}")
    blob = "\n".join(parts)
    for pat in _PROCESSING_FEE_PATTERNS:
        match = pat.search(blob)
        if match:
            try:
                v = float(match.group(1))
                if 0 < v < 5000:
                    return round(v, 2)
            except ValueError:
                continue
    for sec in sections.values():
        for key, val in sec.items():
            if "加工费" not in str(key) or not val:
                continue
            num = re.search(r"(\d+(?:\.\d+)?)", str(val))
            if num:
                try:
                    v = float(num.group(1))
                    if 0 < v < 5000:
                        return round(v, 2)
                except ValueError:
                    continue
    return None


def compute_mold_fee_from_sections(sections: dict[str, dict[str, str]]) -> float:
    """Sum the three "X模具费用" cells in section E into a single number.
    Returns 0.0 when section E is missing or empty so the caller can keep
    the engine default."""
    section_e = sections.get("E", {})
    if not section_e:
        return 0.0
    candidate_keys = (
        "开料模刀模费用rmb", "开料模刀模费用",
        "五金模具费用rmb", "五金模具费用",
        "塑胶模具费用rmb", "塑胶模具费用",
    )
    total = 0.0
    for key in candidate_keys:
        value = section_e.get(key)
        if not value:
            continue
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        if match:
            total += float(match.group(0))
    return total


def _extract_product_size(section_b: dict[str, str]) -> dict[str, float]:
    size: dict[str, float] = {}
    aliases: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("LCM", ("lcm", "l(cm)", "l", "长", "长度", "成品长")),
        ("WCM", ("wcm", "w(cm)", "w", "宽", "厚", "深", "宽度", "厚度")),
        ("HCM", ("hcm", "h(cm)", "h", "高", "高度", "成品高")),
    )

    def norm(text: object) -> str:
        return re.sub(r"[\s_（）()\-／/]+", "", str(text or "").strip().lower())

    norm_map = {norm(k): v for k, v in section_b.items()}
    for out_key, keys in aliases:
        for key in keys:
            value = norm_map.get(norm(key), "")
            match = re.search(r"-?\d+(?:\.\d+)?", str(value))
            if match:
                size[out_key] = float(match.group(0))
                break
    return size
