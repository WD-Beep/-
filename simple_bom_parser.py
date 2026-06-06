"""Parser for the second "类型 / 说明 / 宽幅 / 单价" BOM template.

This is a different worksheet shape than the 7-section "需求表(填写区)"
template handled by ``demand_parser``. Each row already lists ONE material
plus its unit price written by the salesperson, so the price KB lookup is
optional — we only need the LLM to estimate per-piece usage.

Layout (B260128 example):
  R1  | 图片 | 报价资料B260128
  R2  |     | 类型     | 说明                     | 宽幅   | 单价
  R3  |     | 尺寸     | 长150mm，高110mm，厚度80mm
  R4  |     | 面料(正面) | 0.4mm 透明 PVC          | 122CM | 含印刷23元/码
  ...
  R17 |     | 报价毛利率 | 0.3
  R19 |     | 数量     | 500
  R20 |     |         |                         |       | ai算出成本价19元
  R22 |     |         |                         |       | 最终报价27元

We:
  * detect a header row containing both 类型 / 单价 in the first ~5 rows
  * walk subsequent rows; classify each by 类型 → either material or metadata
  * pull product size, quantity, margin, processing fee from metadata rows
  * pull "ai算出成本价 / 最终报价" lines as reference_prices
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sheet_parser import (
    SheetParseError,
    normalize_rows,
    parse_sheet_xml_rows,
    read_sheet_entries,
    read_shared_strings,
    row_get,
    simple_bom_material_candidates,
)


# Type-cell tokens that map directly to a material role for KB lookup.
# Anything not in this map AND not in METADATA_TYPES is treated as a generic
# material with role = the type text itself.
TYPE_TO_ROLE: dict[str, str] = {
    "面料": "外料",
    "面料正面": "外料",
    "面料正面材料": "外料",
    "面料背面": "外料",
    "面料背面材料": "外料",
    "里布": "里料",
    "里料": "里料",
    "围边": "辅料",
    "围边侧围": "辅料",
    "侧围": "辅料",
    "拉链": "拉链",
    "拉头": "拉头",
    "挂扣": "扣具",
    "扣具": "扣具",
    "肩带": "肩带",
    "织带": "织带",
    "绳带": "绳带",
    "手腕带": "织带",
    "手腕带尺寸": "织带",
    "包装": "包装",
    "胶水": "辅料",
    "印刷工艺": "工艺",
}

# Type-cell tokens that produce settings instead of BOM rows.
METADATA_TYPES = {
    "尺寸",
    "颜色",
    "数量",
    "报价毛利率",
    "毛利率",
    "加工费",
    "结构说明",
}

# Reference-price patterns inside any cell.
_REF_COST_PATTERN = re.compile(r"成本(?:价)?\s*[:：]?\s*([\d.]+)\s*元?")
_REF_QUOTE_PATTERN = re.compile(r"(?:最终)?报价\s*[:：]?\s*([\d.]+)\s*元?")


@dataclass
class SimpleBomMaterial:
    type: str           # 原始的类型文本（"面料(正面材料)"）
    role: str           # 归一化角色（外料/里料/拉链…）
    name: str           # 取自"说明"列
    spec: str           # 宽幅，如 "122CM"
    unit_price: str     # 单价文本，如 "23元/码"，可能多组件
    note: str = ""


@dataclass
class SimpleBomParseResult:
    file_name: str
    sheet_name: str
    materials: list[SimpleBomMaterial] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    structure_text: str = ""
    quote_settings: dict[str, Any] = field(default_factory=dict)
    quantities: tuple[int, ...] = ()
    product_size: dict[str, float] = field(default_factory=dict)
    product_name: str = ""
    reference_prices: list[dict[str, Any]] = field(default_factory=list)
    raw_row_count: int = 0


def is_simple_bom_template(rows: list[list[str]]) -> bool:
    return _find_header_row(rows) is not None


def parse_simple_bom_from_payload(payload: dict[str, Any]) -> SimpleBomParseResult:
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

    sheet_name, rows = _pick_simple_bom_sheet(file_bytes)
    return parse_simple_bom_from_rows(rows, file_name=file_name, sheet_name=sheet_name)


def parse_simple_bom_from_rows(
    rows: list[list[str]],
    *,
    file_name: str = "",
    sheet_name: str = "",
) -> SimpleBomParseResult:
    header_index = _find_header_row(rows)
    if header_index is None:
        raise SheetParseError("Simple BOM header (类型/说明/.../单价) not found.")

    column_map = _build_column_map(rows[header_index])
    materials: list[SimpleBomMaterial] = []
    metadata: dict[str, str] = {}
    reference_prices: list[dict[str, Any]] = []
    structure_text = ""

    for row in rows[header_index + 1 :]:
        type_text = _cell(row, column_map, "type").strip()
        desc_text = _cell(row, column_map, "desc").strip()
        spec_text = _cell(row, column_map, "spec").strip()
        price_text = _cell(row, column_map, "price").strip()

        # Reference price lines (R20/R22 in B260128) often live in the price
        # column with no type/desc.
        if not type_text and not desc_text and price_text:
            ref = _parse_reference_price_text(price_text)
            if ref:
                reference_prices.append(ref)
            continue

        if not type_text:
            continue

        normalised_type = _normalise_type(type_text)

        if normalised_type == "结构说明":
            structure_text = desc_text
            continue
        if normalised_type in METADATA_TYPES:
            metadata[normalised_type] = desc_text or price_text
            continue

        if not desc_text and not price_text:
            continue

        role = TYPE_TO_ROLE.get(normalised_type, normalised_type or "材料")
        for cand in simple_bom_material_candidates(
            name=desc_text or type_text,
            spec=spec_text,
            unit_price=price_text,
        ):
            materials.append(
                SimpleBomMaterial(
                    type=type_text,
                    role=role,
                    name=str(cand.get("name") or "").strip() or (desc_text or type_text),
                    spec=str(cand.get("spec") or spec_text or "-").strip() or "-",
                    unit_price=str(cand.get("unit_price") or price_text or "").strip(),
                    note="",
                )
            )

    quote_settings = _settings_from_metadata(metadata)
    product_size = _size_from_metadata(metadata.get("尺寸", ""))
    quantities = _quantities_from_metadata(metadata.get("数量", ""))
    product_name = _infer_product_name(rows)

    return SimpleBomParseResult(
        file_name=file_name,
        sheet_name=sheet_name,
        materials=materials,
        metadata=metadata,
        structure_text=structure_text,
        quote_settings=quote_settings,
        quantities=quantities,
        product_size=product_size,
        product_name=product_name,
        reference_prices=reference_prices,
        raw_row_count=len(rows),
    )


def _pick_simple_bom_sheet(file_bytes: bytes) -> tuple[str, list[list[str]]]:
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

    best_name = sheets[0][0]
    best_rows: list[list[str]] = []
    best_score = -1
    for sheet_name, sheet_xml in sheets:
        rows = normalize_rows(parse_sheet_xml_rows(sheet_xml, shared_strings))
        if _find_header_row(rows) is not None:
            non_empty = sum(1 for r in rows if any(c.strip() for c in r))
            if non_empty > best_score:
                best_score = non_empty
                best_name, best_rows = sheet_name, rows
    if not best_rows:
        # Fall back to the first sheet so the caller can still see something.
        first_name, first_xml = sheets[0]
        return first_name, normalize_rows(parse_sheet_xml_rows(first_xml, shared_strings))
    return best_name, best_rows


def _find_header_row(rows: list[list[str]]) -> int | None:
    """Return the index of the row that holds both 类型 and 单价 column labels."""
    for idx, row in enumerate(rows[:8]):
        cells = [str(c or "").strip() for c in row]
        joined = " ".join(cells)
        if "类型" in joined and "单价" in joined and ("说明" in joined or "宽幅" in joined):
            return idx
    return None


def _build_column_map(header_row: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        text = str(cell or "").strip()
        if not text:
            continue
        if "类型" in text:
            mapping.setdefault("type", idx)
        elif "说明" in text or "材料" in text or "名称" in text:
            mapping.setdefault("desc", idx)
        elif "宽幅" in text or "规格" in text or "尺寸" in text:
            mapping.setdefault("spec", idx)
        elif "单价" in text or "价格" in text:
            mapping.setdefault("price", idx)
    return mapping


def _cell(row: list[str], column_map: dict[str, int], key: str) -> str:
    idx = column_map.get(key)
    if idx is None:
        return ""
    return row_get(row, idx)


def _normalise_type(text: str) -> str:
    cleaned = re.sub(r"[（）()\[\]【】/\\,，:：. ]+", "", text)
    return cleaned


def _parse_reference_price_text(text: str) -> dict[str, Any] | None:
    cost_match = _REF_COST_PATTERN.search(text)
    quote_match = _REF_QUOTE_PATTERN.search(text)
    if not cost_match and not quote_match:
        return None
    result: dict[str, Any] = {"source_text": text.strip()}
    if cost_match:
        try:
            result["cost"] = round(float(cost_match.group(1)), 2)
        except ValueError:
            pass
    if quote_match:
        try:
            result["quote"] = round(float(quote_match.group(1)), 2)
        except ValueError:
            pass
    return result if result.keys() - {"source_text"} else None


def _settings_from_metadata(metadata: dict[str, str]) -> dict[str, Any]:
    settings: dict[str, Any] = {}

    margin_text = metadata.get("报价毛利率") or metadata.get("毛利率") or ""
    margin_match = re.search(r"-?\d+(?:\.\d+)?", margin_text)
    if margin_match:
        value = float(margin_match.group(0))
        settings["gross_margin_rate"] = value / 100 if value > 1 else value

    processing_text = metadata.get("加工费", "")
    processing_match = re.search(r"\d+(?:\.\d+)?", processing_text)
    if processing_match:
        settings["processing_fee"] = float(processing_match.group(0))

    return settings


def _size_from_metadata(text: str) -> dict[str, float]:
    """Parse "长150mm，高110mm，厚度80mm" / "150*110*80mm" style strings."""
    if not text:
        return {}
    size: dict[str, float] = {}
    for tag, key in (("长", "LCM"), ("宽", "WCM"), ("高", "HCM"), ("厚", "WCM")):
        match = re.search(rf"{tag}(?:度)?\s*[:：]?\s*(\d+(?:\.\d+)?)", text)
        if match and key not in size:
            value = float(match.group(1))
            if "mm" in text.lower():
                value /= 10  # mm → cm
            size[key] = value
    if size:
        return size
    # 150*110*80 mm fallback
    triple = re.search(r"(\d+(?:\.\d+)?)\s*[*×x]\s*(\d+(?:\.\d+)?)\s*[*×x]\s*(\d+(?:\.\d+)?)", text)
    if triple:
        l, w, h = (float(triple.group(i)) for i in (1, 2, 3))
        if "mm" in text.lower():
            l, w, h = l / 10, w / 10, h / 10
        size = {"LCM": l, "WCM": w, "HCM": h}
    return size


def _quantities_from_metadata(text: str) -> tuple[int, ...]:
    if not text:
        return ()
    nums = [int(m.group(0)) for m in re.finditer(r"\d+", text)]
    if not nums:
        return ()
    return tuple(sorted(set(nums)))


def _infer_product_name(rows: list[list[str]]) -> str:
    """The first row often carries the file label like '报价资料B260128'."""
    for row in rows[:3]:
        for cell in row:
            text = str(cell or "").strip()
            if not text:
                continue
            if re.search(r"B\d{4,}", text):
                return text
    return ""
