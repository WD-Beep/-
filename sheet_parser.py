from __future__ import annotations

import base64
import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    import xlrd
except ImportError:  # pragma: no cover
    xlrd = None  # type: ignore[assignment]


class SheetParseError(ValueError):
    pass


MAX_SHEET_BYTES = 20 * 1024 * 1024
# Keep high enough to avoid clipping legitimate BOM rows in complex sheets.
MAX_ITEMS = 1000
ALLOWED_ITEM_SECTIONS = {"c", "d"}

MATERIAL_SHEET_KEYWORDS = (
    "\u6750\u6599",
    "\u7269\u6599",
    "\u914d\u4ef6",
    "\u9762\u6599",
    "\u8f85\u6599",
    "cost",
    "material",
    "bom",
)

TITLE_KEYWORDS = (
    "\u9700\u6c42\u8868",
    "\u62a5\u4ef7\u8868",
    "\u586b\u5199\u8bf4\u660e",
    "\u7248\u672c",
    "v1.0",
    "v2.0",
    "\u8bf4\u660e",
)

SECTION_KEYWORDS = (
    "\u5ba2\u6237\u4e0e\u62a5\u4ef7",
    "\u5ba2\u6237\u4fe1\u606f",
    "\u62a5\u4ef7\u4fe1\u606f",
    "\u4ea7\u54c1\u89c4\u683c",
    "\u6750\u6599\u4e0e\u914d\u4ef6",
    "\u5de5\u827a",
    "\u6a21\u5177",
    "\u6570\u91cf\u9636\u68af",
)

HEADER_OR_CONFIG_KEYWORDS = (
    "\u7269\u6599\u540d\u79f0",
    "\u89c4\u683c/\u7528\u91cf",
    "\u89c4\u683c",
    "\u7528\u91cf",
    "\u5355\u4ef7\u53c2\u8003",
    "\u5c0f\u8ba1",
    "\u5ba2\u6237\u540d\u79f0",
    "\u4ea7\u54c1\u7c7b\u578b",
    "\u4ea7\u54c1\u540d\u79f0",
    "\u662f\u5426\u9700\u8981",
    "\u6570\u91cf\u9636\u68af",
    "quantity ladder",
    "quantity",
    "qty1",
    "qty2",
    "qty3",
    "logo\u65b9\u5f0f",
    "logo",
    "\u5f00\u6599\u6a21",
    "\u5200\u6a21",
)

PLACEHOLDER_VALUES = {"", "-", "--", "-/-", "/", "n/a", "na", "null", "none"}
SECTION_PREFIX_PATTERN = re.compile(r"^\s*[A-Fa-f]\s*[\.\uFF0E\u3001:\uFF1A]\s*")
CONFIG_METADATA_KEYWORDS = (
    "incoterm",
    "incoterms",
    "currency",
    "tax",
    "vat",
    "quote validity",
    "payment",
    "destination",
    "shipping",
    "trade term",
    "\u57ce\u5e02",
    "\u8d38\u6613\u6761\u6b3e",
    "\u5e01\u79cd",
    "\u8d27\u5e01",
    "\u542b\u7a0e",
    "\u662f\u5426\u542b\u7a0e",
    "\u7a0e\u7387",
    "\u4ed8\u6b3e\u65b9\u5f0f",
    "\u4ea4\u671f",
    "\u6709\u6548\u671f",
    "\u76ee\u7684\u6e2f",
    "\u8d77\u8fd0\u6e2f",
    "\u8fd0\u8f93\u65b9\u5f0f",
)

CONFIG_FIELD_HINTS = (
    "incoterm",
    "currency",
    "tax",
    "vat",
    "payment",
    "shipping",
    "\u57ce\u5e02",
    "\u6761\u6b3e",
    "\u5e01\u79cd",
    "\u542b\u7a0e",
    "\u7a0e",
    "\u4ed8\u6b3e",
    "\u4ea4\u671f",
    "\u6709\u6548\u671f",
    "\u8fd0\u8f93",
    "\u6e2f",
)

SECTION_ITEM_HINTS = (
    "\u6750\u6599",
    "\u7269\u6599",
    "\u914d\u4ef6",
    "\u5de5\u827a",
    "\u5916\u6599",
    "\u91cc\u6599",
    "\u62c9\u94fe",
)

MATERIAL_NAME_BLACKLIST_KEYWORDS = (
    "\u5ba2\u6237\u540d\u79f0",
    "\u5ba2\u6237\u90ae\u7bb1",
    "\u56fd\u5bb6",
    "\u5229\u6da6\u7387",
    "\u62a5\u4ef7\u53e3\u5f84",
    "\u6c47\u7387",
    "\u5907\u6ce8",
    "\u4ea7\u54c1\u7c7b\u578b",
    "\u4ea7\u54c1\u540d\u79f0",
    "l(cm)",
    "w(cm)",
    "h(cm)",
    "\u7ed3\u6784\u590d\u6742\u5ea6",
    "\u53c2\u8003\u56fe\u7247",
    "\u6570\u91cf\u9636\u68af",
    "\u6570\u91cf1",
    "\u6570\u91cf2",
    "\u6570\u91cf3",
    "\u662f\u5426\u9700\u8981\u5f00\u6599\u6a21",
    "\u57ce\u5e02",
    "incoterms",
    "incoterm",
    "\u5e01\u79cd",
    "\u662f\u5426\u542b\u7a0e",
    "vat_included",
    "customer_name",
    "country",
    "logo",
    "qty1",
    "qty2",
    "qty3",
)

# 表格「项目/物料名称」列里的备注型标签，不是真实材料名。
NON_MATERIAL_LABEL_NAME_RX = re.compile(
    r"^(?:成本参考(?:价)?|成品尺寸|备注|说明|建议|参考(?:说明|信息)|价格参考|尺寸说明)(?:[:：].*)?$",
    re.I,
)


def is_non_material_label_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    return bool(NON_MATERIAL_LABEL_NAME_RX.match(text))

CONFIG_SPEC_USAGE_KEYWORDS = (
    "customer_name",
    "country",
    "currency",
    "incoterm",
    "incoterms",
    "vat",
    "tax",
    "\u5ba2\u6237",
    "\u56fd\u5bb6",
    "\u5e01\u79cd",
    "\u542b\u7a0e",
    "\u5229\u6da6\u7387",
)

COLUMN_LABEL_HINT_KEYWORDS = (
    "标准名",
    "编码",
    "code",
    "颜色",
    "规格",
    "用量",
    "单价",
    "价格",
    "小计",
    "logo",
    "方式",
    "客户",
    "country",
    "currency",
    "incoterm",
    "数量阶梯",
    "是否需要",
)

MATERIAL_PAIR_LABEL_HINT_KEYWORDS = (
    "外料",
    "里料",
    "辅料",
    "配件",
    "面料",
    "网布",
    "拉链",
    "织带",
    "扣具",
    "插扣",
    "d环",
    "布标",
    "吊牌",
    "包装",
    "material",
    "fabric",
    "lining",
    "zipper",
    "webbing",
    "buckle",
    "accessory",
    "trim",
    "label",
)

MATERIAL_PAIR_LABEL_BLOCK_KEYWORDS = (
    "颜色",
    "色号",
    "单价",
    "价格",
    "金额",
    "小计",
    "数量",
    "用量",
    "耗量",
    "利润",
    "汇率",
    "币种",
    "incoterm",
    "国家",
    "客户",
    "备注",
    "说明",
    "方式",
    "是否",
    "customer",
    "country",
    "currency",
    "incoterm",
    "tax",
    "vat",
    "profit",
    "margin",
    "qty",
    "quantity",
    "color",
    "colour",
)

MATERIAL_PAIR_TECH_KEY_HINTS = (
    "material",
    "fabric",
    "lining",
    "zipper",
    "webbing",
    "buckle",
    "label",
    "accessory",
    "trim",
)

PRODUCT_NAME_KEYWORDS = (
    "产品名称",
    "产品名",
    "款式",
    "款号",
    "品名",
    "item_name",
    "product_name",
    "product",
    "style_name",
)

SINGLE_SECTION_LETTER_PATTERN = re.compile(r"^\s*[A-Fa-f]\s*$")
SECTION_TITLE_PATTERN = re.compile(r"^\s*([A-Fa-f])\s*[\.\uFF0E\u3001:\uFF1A]\s*(.*)$")
SECTION_GROUP_PATTERN = re.compile(r"^\s*([A-Fa-f])\s*组\s*(.*)$")
INVALID_UNIT_PRICE_VALUES = {"yes", "no", "true", "false", "\u662f", "\u5426"}

HEADER_ALIASES = {
    "name": {
        "name",
        "item",
        "itemname",
        "material",
        "materialname",
        "\u7269\u6599",
        "\u7269\u6599\u540d\u79f0",
        "\u6750\u6599",
        "\u540d\u79f0",
        "\u54c1\u540d",
    },
    "spec": {
        "spec",
        "specification",
        "\u89c4\u683c",
        "\u578b\u53f7",
        "\u95e8\u5e45",
        "\u514b\u91cd",
    },
    "usage": {
        "usage",
        "qty",
        "quantity",
        "\u7528\u91cf",
        "\u8017\u91cf",
        "\u6570\u91cf",
    },
    "unit_price": {
        "unitprice",
        "price",
        "unit_price",
        "\u5355\u4ef7",
        "\u5355\u4ef7\u53c2\u8003",
        "\u91c7\u8d2d\u4ef7",
        "\u4ef7\u683c",
    },
    "amount": {
        "amount",
        "subtotal",
        "cost",
        "total",
        "\u91d1\u989d",
        "\u5c0f\u8ba1",
        "\u6210\u672c",
        "\u5408\u8ba1",
    },
}
DEFAULT_COLUMN_ORDER = {
    "name": 0,
    "spec": 1,
    "usage": 2,
    "unit_price": 3,
    "amount": 4,
}
FIXED_UPLOAD_COLUMN_ORDER = {
    "name": 0,
    "spec": 1,
    "usage": -1,
    "unit_price": 2,
    "amount": 3,
}
FIXED_UPLOAD_COLUMN_ORDER_WITH_USAGE = {
    "name": 0,
    "spec": 1,
    "usage": 2,
    "unit_price": 3,
    "amount": 4,
}
FIXED_HEADER_KEYWORDS = (
    "物料名称",
    "材料名称",
    "物料",
    "规格",
    "用量",
    "规格/用量",
    "单价",
    "单价参考",
    "小计",
)
UPLOAD_NAME_DROP_KEYWORDS = (
    "图片",
    "报价资料",
    "填写说明",
    "版本",
)
PURE_NUMBER_TEXT_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?$")
PURE_PRICE_TEXT_PATTERN = re.compile(
    r"^\s*(?:￥|¥)?\s*-?\d+(?:\.\d+)?\s*(?:元)?\s*(?:/\s*[\u4e00-\u9fffA-Za-z0-9#]+)?\s*$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedSheet:
    sheet_name: str
    rows: list[list[str]]
    sheet_row_counts: dict[str, int] | None = None


@dataclass(frozen=True)
class ExtractionResult:
    items: list[dict[str, Any]]
    filtered_count: int
    data_row_count: int
    header_index: int | None
    scan_summary: dict[str, int]


@dataclass(frozen=True)
class RowScanResult:
    items: list[dict[str, Any]]
    filtered_count: int


def parse_sheet_items_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SheetParseError("Uploaded payload must be an object.")

    file_name = str(payload.get("name") or "").strip()
    file_base64 = str(payload.get("content_base64") or "").strip()
    preferred_sheet = str(payload.get("sheet_name") or "").strip()
    start_row = _parse_start_row(payload.get("start_row"))

    if not file_name:
        raise SheetParseError("Missing file name.")
    if not file_base64:
        raise SheetParseError("Missing file content.")

    try:
        file_bytes = base64.b64decode(file_base64, validate=True)
    except Exception as error:
        raise SheetParseError("Failed to decode file content.") from error

    if not file_bytes:
        raise SheetParseError("Uploaded file is empty.")
    if len(file_bytes) > MAX_SHEET_BYTES:
        raise SheetParseError("Uploaded file is too large. Limit is 5MB.")

    parsed_sheet, all_row_count = parse_rows_from_bytes(
        file_name=file_name,
        file_bytes=file_bytes,
        preferred_sheet=preferred_sheet,
    )
    extraction = rows_to_items(parsed_sheet.rows, start_row=start_row)
    fallback_rows = rows_to_items_raw(parsed_sheet.rows, start_row=start_row)
    merged_items = extraction.items
    if not merged_items and rows_have_pricing_signals(parsed_sheet.rows):
        merged_items = fallback_rows.items
    quote_params = extract_quote_parameters(parsed_sheet.rows)
    non_empty_row_count = sum(1 for row in parsed_sheet.rows if any(cell.strip() for cell in row))
    sheet_product_name = infer_sheet_product_name(quote_params, parsed_sheet.rows)
    if not merged_items:
        raise SheetParseError("No valid material rows were recognized. Please check sheet structure or set start_row.")

    sheet_row_counts = parsed_sheet.sheet_row_counts or {}
    fallback_summary = {
        "fallback_used": 1 if not extraction.items and bool(fallback_rows.items) else 0,
        "raw_items": len(fallback_rows.items),
        "raw_filtered": fallback_rows.filtered_count,
    }
    scan_summary = dict(extraction.scan_summary or {})
    scan_summary.update(fallback_summary)

    return {
        "file_name": file_name,
        "sheet_name": parsed_sheet.sheet_name,
        "row_count": all_row_count,
        "sheet_row_counts": sheet_row_counts,
        "non_empty_row_count": non_empty_row_count,
        "data_row_count": extraction.data_row_count,
        "item_count": len(merged_items),
        "filtered_count": max(extraction.filtered_count, fallback_rows.filtered_count),
        "scan_summary": scan_summary,
        "start_row": start_row,
        "sheet_product_name": sheet_product_name,
        "quote_params": quote_params,
        "items": merged_items,
    }


def parse_rows_from_bytes(
    *,
    file_name: str,
    file_bytes: bytes,
    preferred_sheet: str = "",
) -> tuple[ParsedSheet, int]:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".csv":
        rows = parse_delimited_rows(file_bytes=file_bytes, delimiter=",")
        return ParsedSheet(sheet_name="CSV", rows=rows), len(rows)
    if suffix == ".tsv":
        rows = parse_delimited_rows(file_bytes=file_bytes, delimiter="\t")
        return ParsedSheet(sheet_name="TSV", rows=rows), len(rows)
    if suffix == ".xlsx":
        return parse_xlsx_rows(file_bytes=file_bytes, preferred_sheet=preferred_sheet)
    if suffix == ".xls":
        return parse_xls_rows(file_bytes=file_bytes, preferred_sheet=preferred_sheet)
    raise SheetParseError("Only .xlsx/.xls/.csv/.tsv files are supported.")


def parse_delimited_rows(*, file_bytes: bytes, delimiter: str) -> list[list[str]]:
    last_error: Exception | None = None
    decoded_text = ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            decoded_text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError as error:
            last_error = error
    else:
        raise SheetParseError("Unable to detect text encoding. Please use UTF-8 or GBK.") from last_error

    reader = csv.reader(io.StringIO(decoded_text), delimiter=delimiter)
    return normalize_rows([list(map(clean_cell_text, row)) for row in reader])


def parse_xlsx_rows(*, file_bytes: bytes, preferred_sheet: str = "") -> tuple[ParsedSheet, int]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as error:
        raise SheetParseError("Invalid XLSX file format.") from error

    shared_strings = read_shared_strings(archive)
    sheets = read_sheet_entries(archive)
    if not sheets:
        raise SheetParseError("No worksheet found in XLSX file.")

    preferred_sheet_normalized = preferred_sheet.strip().lower()
    parsed_sheets: list[ParsedSheet] = []
    total_rows = 0
    sheet_row_counts: dict[str, int] = {}

    for sheet_name, sheet_xml in sheets:
        rows = normalize_rows(parse_sheet_xml_rows(sheet_xml, shared_strings))
        parsed_sheets.append(ParsedSheet(sheet_name=sheet_name, rows=rows))
        total_rows += len(rows)
        sheet_row_counts[sheet_name] = len(rows)

    if preferred_sheet_normalized:
        for parsed in parsed_sheets:
            if parsed.sheet_name.strip().lower() == preferred_sheet_normalized:
                return ParsedSheet(
                    sheet_name=parsed.sheet_name,
                    rows=parsed.rows,
                    sheet_row_counts=sheet_row_counts,
                ), total_rows

    best_sheet = choose_best_sheet(parsed_sheets)
    return ParsedSheet(
        sheet_name=best_sheet.sheet_name,
        rows=best_sheet.rows,
        sheet_row_counts=sheet_row_counts,
    ), total_rows


def _xls_cell_as_text(book: Any, sheet: Any, rowx: int, colx: int) -> str:
    """将 xlrd 单元格转为与 xlsx 路径一致的清洗后字符串。"""
    if xlrd is None:
        return ""
    try:
        ctype = sheet.cell_type(rowx, colx)
        val = sheet.cell_value(rowx, colx)
    except IndexError:
        return ""
    if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if ctype == xlrd.XL_CELL_TEXT:
        return clean_cell_text(str(val))
    if ctype == xlrd.XL_CELL_BOOLEAN:
        return clean_cell_text("TRUE" if val else "FALSE")
    if ctype == xlrd.XL_CELL_ERROR:
        return ""
    if ctype == xlrd.XL_CELL_NUMBER:
        if isinstance(val, float):
            if val == int(val):
                return clean_cell_text(str(int(val)))
            return clean_cell_text(f"{val:.12g}".rstrip("0").rstrip("."))
        return clean_cell_text(str(val))
    return clean_cell_text(str(val))


def parse_xls_all_sheets_normalized(file_bytes: bytes) -> list[tuple[str, list[list[str]]]]:
    """读取整本 .xls，返回 [(工作表名, normalize_rows 后的行列)], 顺序与簿内一致。"""
    if xlrd is None:
        raise SheetParseError("读取 .xls 需要安装依赖：pip install xlrd")
    if not file_bytes:
        raise SheetParseError("Uploaded file is empty.")
    try:
        book = xlrd.open_workbook(file_contents=file_bytes, formatting_info=False)
    except Exception as error:
        tip = ""
        blob = file_bytes[:8]
        if blob.startswith(b"PK\x03\x04"):
            tip = "（该文件实为 .xlsx，请改用 .xlsx 扩展名上传）"
        raise SheetParseError(f"无法解析 Excel .xls 文件{tip}：{error}") from error

    out: list[tuple[str, list[list[str]]]] = []
    for sheet_name in book.sheet_names():
        sh = book.sheet_by_name(sheet_name)
        rows: list[list[str]] = []
        for rx in range(sh.nrows):
            ncols = sh.row_len(rx)
            row = [_xls_cell_as_text(book, sh, rx, cx) for cx in range(ncols)]
            rows.append(row)
        out.append((sheet_name, normalize_rows(rows)))
    return out


def parse_xls_rows(*, file_bytes: bytes, preferred_sheet: str = "") -> tuple[ParsedSheet, int]:
    """解析 .xls（Excel 97-2003），选表逻辑与 parse_xlsx_rows 一致（仅无内嵌图/超链）。"""
    tuples = parse_xls_all_sheets_normalized(file_bytes)
    if not tuples:
        raise SheetParseError("No worksheet found in XLS file.")

    parsed_sheets = [ParsedSheet(sheet_name=name, rows=rows) for name, rows in tuples]
    sheet_row_counts = {name: len(rows) for name, rows in tuples}
    total_rows = sum(sheet_row_counts.values())
    preferred_sheet_normalized = preferred_sheet.strip().lower()
    if preferred_sheet_normalized:
        for name, rows in tuples:
            if name.strip().lower() == preferred_sheet_normalized:
                return (
                    ParsedSheet(
                        sheet_name=name,
                        rows=rows,
                        sheet_row_counts=sheet_row_counts,
                    ),
                    total_rows,
                )

    best_sheet = choose_best_sheet(parsed_sheets)
    return (
        ParsedSheet(
            sheet_name=best_sheet.sheet_name,
            rows=best_sheet.rows,
            sheet_row_counts=sheet_row_counts,
        ),
        total_rows,
    )


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return []

    root = ElementTree.fromstring(archive.read(path))
    ns = nsmap(root)
    shared: list[str] = []
    for si in root.findall(".//main:si", ns):
        text_nodes = si.findall(".//main:t", ns)
        shared.append("".join(node.text or "" for node in text_nodes))
    return shared


def read_sheet_entries(archive: zipfile.ZipFile) -> list[tuple[str, bytes]]:
    workbook_path = "xl/workbook.xml"
    rels_path = "xl/_rels/workbook.xml.rels"
    if workbook_path not in archive.namelist() or rels_path not in archive.namelist():
        raise SheetParseError("XLSX workbook structure is incomplete.")

    workbook_root = ElementTree.fromstring(archive.read(workbook_path))
    rels_root = ElementTree.fromstring(archive.read(rels_path))
    workbook_ns = nsmap(workbook_root)
    rels_ns = nsmap(rels_root)

    rel_index: dict[str, str] = {}
    for node in rels_root.findall(".//rel:Relationship", rels_ns):
        rel_id = node.attrib.get("Id", "")
        target = node.attrib.get("Target", "").lstrip("/")
        if rel_id and target:
            if target.startswith("worksheets/"):
                rel_index[rel_id] = f"xl/{target}"
            elif target.startswith("xl/"):
                rel_index[rel_id] = target
            else:
                rel_index[rel_id] = f"xl/{target}"

    sheets: list[tuple[str, bytes]] = []
    for sheet in workbook_root.findall(".//main:sheets/main:sheet", workbook_ns):
        name = sheet.attrib.get("name", "").strip() or "Sheet"
        relation_id = (
            sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            or sheet.attrib.get("r:id")
            or ""
        )
        sheet_path = rel_index.get(relation_id)
        if not sheet_path or sheet_path not in archive.namelist():
            continue
        sheets.append((name, archive.read(sheet_path)))
    return sheets


def read_sheet_paths_entries(archive: zipfile.ZipFile) -> list[tuple[str, str, bytes]]:
    """Return [(sheet_display_name, zip_internal_xml_path, sheet_xml_bytes), ...]."""
    workbook_path = "xl/workbook.xml"
    rels_path = "xl/_rels/workbook.xml.rels"
    if workbook_path not in archive.namelist() or rels_path not in archive.namelist():
        raise SheetParseError("XLSX workbook structure is incomplete.")

    workbook_root = ElementTree.fromstring(archive.read(workbook_path))
    rels_root = ElementTree.fromstring(archive.read(rels_path))
    workbook_ns = nsmap(workbook_root)
    rels_ns = nsmap(rels_root)

    rel_index: dict[str, str] = {}
    for node in rels_root.findall(".//rel:Relationship", rels_ns):
        rel_id = node.attrib.get("Id", "")
        target = node.attrib.get("Target", "").lstrip("/")
        if rel_id and target:
            if target.startswith("worksheets/"):
                rel_index[rel_id] = f"xl/{target}"
            elif target.startswith("xl/"):
                rel_index[rel_id] = target
            else:
                rel_index[rel_id] = f"xl/{target}"

    sheets: list[tuple[str, str, bytes]] = []
    for sheet in workbook_root.findall(".//main:sheets/main:sheet", workbook_ns):
        name = sheet.attrib.get("name", "").strip() or "Sheet"
        relation_id = (
            sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            or sheet.attrib.get("r:id")
            or ""
        )
        sheet_path = rel_index.get(relation_id)
        if not sheet_path or sheet_path not in archive.namelist():
            continue
        sheets.append((name, sheet_path, archive.read(sheet_path)))
    return sheets


def choose_best_sheet(parsed_sheets: list[ParsedSheet]) -> ParsedSheet:
    def score_sheet(sheet: ParsedSheet) -> tuple[int, int]:
        extraction = rows_to_items(sheet.rows, start_row=None)
        keyword_bonus = 20 if contains_material_keyword(sheet.sheet_name) else 0
        non_empty_rows = sum(1 for row in sheet.rows if any(cell for cell in row))
        return (len(extraction.items) * 10 + keyword_bonus, non_empty_rows)

    return max(parsed_sheets, key=score_sheet)


def contains_material_keyword(name: str) -> bool:
    text = name.strip().lower()
    return any(keyword.lower() in text for keyword in MATERIAL_SHEET_KEYWORDS)


def parse_sheet_xml_rows(sheet_xml: bytes, shared_strings: list[str]) -> list[list[str]]:
    root = ElementTree.fromstring(sheet_xml)
    ns = nsmap(root)
    rows: list[list[str]] = []

    for row in root.findall(".//main:sheetData/main:row", ns):
        values: dict[int, str] = {}
        for cell in row.findall("main:c", ns):
            cell_ref = cell.attrib.get("r", "")
            column_index = column_index_from_ref(cell_ref)
            cell_type = cell.attrib.get("t", "")
            value = ""

            if cell_type == "inlineStr":
                node = cell.find("main:is/main:t", ns)
                value = node.text if node is not None else ""
            else:
                value_node = cell.find("main:v", ns)
                raw_value = value_node.text if value_node is not None else ""
                if cell_type == "s":
                    try:
                        value = shared_strings[int(raw_value)]
                    except Exception:
                        value = ""
                else:
                    value = raw_value or ""

            values[column_index] = clean_cell_text(value)

        if not values:
            rows.append([])
            continue

        max_index = max(values)
        row_values = [values.get(idx, "") for idx in range(max_index + 1)]
        rows.append(row_values)

    return rows


def rows_to_items(rows: list[list[str]], *, start_row: int | None) -> ExtractionResult:
    if not rows:
        return ExtractionResult(
            items=[],
            filtered_count=0,
            data_row_count=0,
            header_index=None,
            scan_summary={},
        )

    legacy_result = rows_to_items_legacy(rows, start_row=start_row)
    fixed_header_index = None if start_row is not None else find_fixed_header_index(rows)
    if start_row is not None or fixed_header_index is not None:
        data_start = max(0, start_row - 1) if start_row is not None else fixed_header_index + 1
        data_rows = rows[data_start:]
        base_filtered_count = sum(1 for row in rows[:data_start] if any(cell.strip() for cell in row))
        fixed_column_map = choose_fixed_column_map(rows, fixed_header_index, data_rows)
        fixed_scan = scan_rows_by_fixed_columns(data_rows=data_rows, column_map=fixed_column_map)
        merged_items = merge_extracted_items(fixed_scan.items, legacy_result.items)
        if merged_items:
            fixed_filtered_count = base_filtered_count + fixed_scan.filtered_count
            scan_summary: dict[str, int] = {
                "fixed_mode": 1,
                "fixed_items": len(fixed_scan.items),
                "legacy_items": len(legacy_result.items),
                "merged_items": len(merged_items),
                "fixed_dropped_rows": fixed_scan.filtered_count,
                "legacy_filtered_rows": legacy_result.filtered_count,
            }
            if fixed_column_map is FIXED_UPLOAD_COLUMN_ORDER_WITH_USAGE:
                scan_summary["fixed_template_with_usage"] = 1
            return ExtractionResult(
                items=merged_items,
                filtered_count=max(fixed_filtered_count, legacy_result.filtered_count),
                data_row_count=max(len(data_rows), legacy_result.data_row_count),
                header_index=fixed_header_index if fixed_header_index is not None else legacy_result.header_index,
                scan_summary=scan_summary,
            )
        # If fixed-column extraction produced nothing, keep old parser output.

    return legacy_result


def rows_to_items_legacy(rows: list[list[str]], *, start_row: int | None) -> ExtractionResult:
    header_index, column_map = find_header_and_column_map(rows, start_row=start_row)
    if start_row is not None:
        data_rows = rows[start_row - 1 :]
    elif header_index is not None and column_map["has_header"]:
        data_rows = rows[header_index + 1 :]
    else:
        data_rows = rows

    base_filtered_count = 0
    if start_row is None and header_index is not None:
        # Count non-empty lines before/at header as filtered noise lines.
        base_filtered_count += sum(1 for row in rows[: header_index + 1] if any(cell.strip() for cell in row))

    section_mode = start_row is None and has_section_structure(rows)
    initial_section_letter = ""
    initial_section_title = ""
    if section_mode and header_index is not None:
        initial_section_letter, initial_section_title = last_section_before_index(rows, header_index)

    strict_scan = scan_rows_for_items(
        data_rows=data_rows,
        column_map=column_map,
        section_mode=section_mode,
        initial_section_letter=initial_section_letter,
        initial_section_title=initial_section_title,
        require_unit_price=True,
        strict_spec_descriptor=True,
    )

    # Fallback for key-value style sheets that omit unit price during upload.
    relaxed_scan = scan_rows_for_items(
        data_rows=data_rows,
        column_map=column_map,
        section_mode=section_mode,
        initial_section_letter=initial_section_letter,
        initial_section_title=initial_section_title,
        require_unit_price=False,
        strict_spec_descriptor=False,
    )
    structured_slot_names = {
        normalize_text(str(item.get("name") or ""))
        for item in [*strict_scan.items, *relaxed_scan.items]
        if str(item.get("name") or "").strip()
    }
    pair_scan = scan_rows_for_material_pairs(
        data_rows=data_rows,
        section_mode=section_mode,
        initial_section_letter=initial_section_letter,
        initial_section_title=initial_section_title,
        excluded_slot_names=structured_slot_names,
    )
    selected_scan = merge_row_scan_results(strict_scan, relaxed_scan, pair_scan)
    scan_summary = {
        "strict_items": len(strict_scan.items),
        "relaxed_items": len(relaxed_scan.items),
        "pair_items": len(pair_scan.items),
        "merged_items": len(selected_scan.items),
    }

    return ExtractionResult(
        items=selected_scan.items,
        filtered_count=base_filtered_count + selected_scan.filtered_count,
        data_row_count=len(data_rows),
        header_index=header_index,
        scan_summary=scan_summary,
    )


def rows_to_items_raw(rows: list[list[str]], *, start_row: int | None) -> RowScanResult:
    if start_row is not None:
        data_start = max(0, start_row - 1)
    else:
        fixed_header_index = find_fixed_header_index(rows)
        data_start = fixed_header_index + 1 if fixed_header_index is not None else 0
    data_rows = rows[data_start:]
    filtered_count = 0
    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for row in data_rows:
        mapped_4 = map_row_values(row, FIXED_UPLOAD_COLUMN_ORDER)
        mapped_5 = map_row_values(row, FIXED_UPLOAD_COLUMN_ORDER_WITH_USAGE)
        mapped = mapped_4
        if looks_like_valid_unit_price_text(str(mapped_5.get("unit_price") or "")):
            mapped = mapped_5

        name = str(mapped.get("name") or "").strip()
        if not name or is_placeholder(name):
            filtered_count += 1
            continue
        if should_drop_upload_name(name) or is_pure_numeric_text(name) or looks_like_pure_price_text(name):
            filtered_count += 1
            continue

        spec = str(mapped.get("spec") or "").strip() or "-"
        usage = str(mapped.get("usage") or "").strip() or "-"
        unit_price = str(mapped.get("unit_price") or "").strip() or "-"
        amount = parse_amount(str(mapped.get("amount") or "")) or 0.0
        unit_price_valid = looks_like_valid_unit_price_text(unit_price)
        if amount <= 0:
            unit_price_value = parse_amount(unit_price) or 0.0
            usage_source = usage if usage != "-" else spec
            usage_qty = parse_usage_quantity(usage_source) or 0.0
            if unit_price_value > 0 and usage_qty > 0:
                amount = round(unit_price_value * usage_qty, 2)
        if amount <= 0 and not unit_price_valid:
            filtered_count += 1
            continue

        expanded_rows = expand_material_row_candidates(
            name=name,
            spec=spec,
            usage=usage,
            unit_price=unit_price,
            amount=round(amount, 2),
        )
        row_added = False
        for candidate_name, candidate_spec, candidate_usage, candidate_unit_price, candidate_amount in expanded_rows:
            key = f"{normalize_text(candidate_name)}|{normalize_text(candidate_spec)}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            row_added = True
            items.append(
                {
                    "name": candidate_name,
                    "spec": candidate_spec,
                    "usage": candidate_usage,
                    "unit_price": candidate_unit_price,
                    "amount": round(candidate_amount, 2),
                    "source": "kb",
                    "spec_ai": False,
                    "usage_ai": False,
                    "unit_price_ai": False,
                    "amount_ai": False,
                }
            )
            if len(items) >= MAX_ITEMS:
                break
        if not row_added:
            filtered_count += 1
        if len(items) >= MAX_ITEMS:
            break

    return RowScanResult(items=items, filtered_count=filtered_count)


def rows_have_pricing_signals(rows: list[list[str]]) -> bool:
    for row in rows:
        if not isinstance(row, list):
            continue
        for cell in row:
            text = str(cell or "").strip()
            if not text:
                continue
            if looks_like_quantity_ladder_value(normalize_text(text)):
                continue
            if looks_like_valid_unit_price_text(text):
                return True
            value = parse_amount(text)
            if value is not None and value > 0:
                return True
    return False


def find_fixed_header_index(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        if row_looks_like_fixed_header(row):
            return idx
    return None


def row_looks_like_fixed_header(row: list[str]) -> bool:
    cells = [normalize_text(row_get(row, idx)) for idx in range(4)]
    if not any(cells):
        return False
    joined = " ".join(cells)
    hits = 0
    for keyword in FIXED_HEADER_KEYWORDS:
        if keyword.lower() in joined:
            hits += 1
    return hits >= 2 and ("物料" in joined or "材料" in joined or "name" in joined)


def choose_fixed_column_map(
    rows: list[list[str]],
    header_index: int | None,
    data_rows: list[list[str]],
) -> dict[str, int]:
    max_row_width = max((len(row) for row in data_rows[: min(8, len(data_rows))]), default=0)
    if header_index is not None:
        header_row = rows[header_index]
        joined_header = " ".join(normalize_text(cell) for cell in header_row if str(cell).strip())
        if "规格/用量" in joined_header or "规格用量" in joined_header:
            return FIXED_UPLOAD_COLUMN_ORDER
        if len(header_row) <= 4 or max_row_width <= 4:
            return FIXED_UPLOAD_COLUMN_ORDER
        if "用量" in joined_header and ("单价" in joined_header or "价格" in joined_header):
            return FIXED_UPLOAD_COLUMN_ORDER_WITH_USAGE

    # If data rows look like [name, spec, usage, price, amount], use 5-column template.
    candidate_rows = data_rows[: min(8, len(data_rows))]
    usage_like_hits = 0
    price_like_hits = 0
    for row in candidate_rows:
        usage_candidate = row_get(row, 2).strip()
        price_candidate = row_get(row, 3).strip()
        if parse_usage_quantity(usage_candidate):
            usage_like_hits += 1
        if (parse_amount(price_candidate) or 0.0) > 0:
            price_like_hits += 1
    if usage_like_hits >= 1 and price_like_hits >= 1:
        return FIXED_UPLOAD_COLUMN_ORDER_WITH_USAGE
    return FIXED_UPLOAD_COLUMN_ORDER


def merge_extracted_items(
    primary_items: list[dict[str, Any]],
    secondary_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_items: list[dict[str, Any]] = []
    item_index: dict[str, int] = {}

    for source_items in (primary_items, secondary_items):
        for item in source_items:
            if not isinstance(item, dict):
                continue
            normalized = normalize_merged_item(item)
            if normalized is None:
                continue
            name = str(normalized.get("name") or "").strip()
            spec = str(normalized.get("spec") or "").strip() or "-"
            if not name:
                continue
            key = f"{normalize_text(name)}|{normalize_text(spec)}"
            existing_pos = item_index.get(key)
            if existing_pos is None:
                item_index[key] = len(merged_items)
                merged_items.append(normalized)
                continue
            existing = merged_items[existing_pos]
            if score_item_quality(normalized) > score_item_quality(existing):
                merged_items[existing_pos] = normalized

    return merged_items


def normalize_merged_item(item: dict[str, Any]) -> dict[str, Any] | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    if should_drop_upload_name(name):
        return None
    if is_pure_numeric_text(name):
        return None
    if looks_like_pure_price_text(name):
        return None

    spec = str(item.get("spec") or "").strip() or "-"
    usage = str(item.get("usage") or "-").strip() or "-"
    unit_price = str(item.get("unit_price") or "").strip() or "-"
    amount_value = parse_amount(str(item.get("amount") or "")) or 0.0
    lowered_unit_price = normalize_text(unit_price)
    if lowered_unit_price in INVALID_UNIT_PRICE_VALUES:
        unit_price = "-"

    # Keep price-bearing rows and genuine pair-extracted rows (name-like value with '-' price/amount)
    # but block structural label rows.
    if (parse_amount(unit_price) or 0.0) <= 0 and amount_value <= 0:
        normalized_name = normalize_text(name)
        if contains_any(normalized_name, HEADER_OR_CONFIG_KEYWORDS):
            return None
        if looks_like_technical_key(name):
            return None

    normalized_item = dict(item)
    normalized_item["name"] = name
    normalized_item["spec"] = spec
    normalized_item["usage"] = usage
    normalized_item["unit_price"] = unit_price
    normalized_item["amount"] = round(amount_value, 2)
    return normalized_item


def scan_rows_by_fixed_columns(*, data_rows: list[list[str]], column_map: dict[str, int]) -> RowScanResult:
    filtered_count = 0
    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for row in data_rows:
        mapped = map_row_values(row, column_map)
        if not is_valid_fixed_upload_row(mapped):
            filtered_count += 1
            continue

        spec_value = mapped["spec"] or "-"
        usage_value = mapped["usage"] or "-"
        unit_price = mapped["unit_price"] or "-"
        amount_value = round(mapped["amount"], 2)
        if amount_value <= 0:
            unit_price_value = parse_amount(unit_price) or 0.0
            usage_source = usage_value if usage_value != "-" else spec_value
            usage_qty = parse_usage_quantity(usage_source) or 0.0
            if unit_price_value > 0 and usage_qty > 0:
                amount_value = round(unit_price_value * usage_qty, 2)

        expanded_rows = expand_material_row_candidates(
            name=mapped["name"],
            spec=spec_value,
            usage=usage_value,
            unit_price=unit_price,
            amount=amount_value,
        )
        row_added = False
        for candidate_name, candidate_spec, candidate_usage, candidate_unit_price, candidate_amount in expanded_rows:
            dedupe_key = f"{normalize_text(candidate_name)}|{normalize_text(candidate_spec)}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            row_added = True
            items.append(
                {
                    "name": candidate_name,
                    "spec": candidate_spec,
                    "usage": candidate_usage,
                    "unit_price": candidate_unit_price,
                    "amount": candidate_amount,
                    "source": "kb",
                    "spec_ai": False,
                    "usage_ai": False,
                    "unit_price_ai": False,
                    "amount_ai": False,
                }
            )
            if len(items) >= MAX_ITEMS:
                break
        if not row_added:
            filtered_count += 1
        if len(items) >= MAX_ITEMS:
            break

    return RowScanResult(items=items, filtered_count=filtered_count)


def is_valid_fixed_upload_row(mapped: dict[str, Any]) -> bool:
    name = str(mapped.get("name") or "").strip()
    spec = str(mapped.get("spec") or "").strip()
    unit_price = str(mapped.get("unit_price") or "").strip()
    amount_value = float(mapped.get("amount") or 0.0)
    joined = normalize_text(" ".join([name, spec, unit_price]))

    if not name or is_placeholder(name):
        return False
    if should_drop_upload_name(name):
        return False
    if is_pure_numeric_text(name):
        return False
    if looks_like_pure_price_text(name):
        return False
    if looks_like_material_description_sentence(name):
        return False
    if contains_any(joined, HEADER_OR_CONFIG_KEYWORDS):
        return False

    lowered_unit_price = normalize_text(unit_price)
    if lowered_unit_price in INVALID_UNIT_PRICE_VALUES:
        return False

    has_unit_price = looks_like_valid_unit_price_text(unit_price)
    if not has_unit_price:
        return False
    return True


def should_drop_upload_name(name: str) -> bool:
    normalized_name = normalize_text(name)
    if not normalized_name:
        return True
    if is_non_material_label_name(name):
        return True
    if any(keyword.lower() in normalized_name for keyword in UPLOAD_NAME_DROP_KEYWORDS):
        return True
    return False


def is_pure_numeric_text(text: str) -> bool:
    return PURE_NUMBER_TEXT_PATTERN.fullmatch(str(text or "").strip()) is not None


def looks_like_pure_price_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if "元" not in value and "¥" not in value and "￥" not in value:
        return False
    return PURE_PRICE_TEXT_PATTERN.fullmatch(value) is not None


def looks_like_valid_unit_price_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    numeric_value = parse_amount(value) or 0.0
    if numeric_value <= 0:
        return False
    normalized = normalize_text(value)
    if normalized in INVALID_UNIT_PRICE_VALUES:
        return False

    compact = value.replace(",", "").replace(" ", "")
    if re.fullmatch(r"-?\d+(?:\.\d+)?", compact):
        return True
    if any(symbol in value for symbol in ("元", "¥", "￥", "$")):
        return True
    if "/" in value:
        suffix = value.split("/", 1)[1].strip()
        if suffix and len(suffix) <= 12:
            return True
    if re.search(r"\b(cny|rmb|usd|eur)\b", normalized):
        return True
    return False

def scan_rows_for_items(
    *,
    data_rows: list[list[str]],
    column_map: dict[str, Any],
    section_mode: bool,
    initial_section_letter: str,
    initial_section_title: str,
    require_unit_price: bool,
    strict_spec_descriptor: bool,
) -> RowScanResult:
    filtered_count = 0
    current_section_letter = initial_section_letter
    current_section_title = initial_section_title
    items: list[dict[str, Any]] = []

    for row in data_rows:
        marker = detect_section_marker(row)
        if marker is not None:
            current_section_letter, current_section_title = marker
            filtered_count += 1
            continue

        if section_mode:
            if not current_section_letter:
                filtered_count += 1
                continue
            if not section_allows_material(current_section_letter, current_section_title):
                filtered_count += 1
                continue

        mapped = map_row_values(row, column_map)
        mapped["section_letter"] = current_section_letter
        mapped["section_title"] = current_section_title
        mapped["allow_split_name"] = True
        if not is_valid_material_row(
            mapped,
            require_unit_price=require_unit_price,
            strict_spec_descriptor=strict_spec_descriptor,
        ):
            filtered_count += 1
            continue

        spec_value, usage_value = normalize_material_spec_usage(mapped["spec"], mapped["usage"])

        for candidate_name, candidate_spec, candidate_usage, candidate_unit_price, candidate_amount in (
            expand_material_row_candidates(
                name=mapped["name"],
                spec=spec_value,
                usage=usage_value,
                unit_price=mapped["unit_price"] or "-",
                amount=round(mapped["amount"], 2),
            )
        ):
            items.append(
                {
                    "name": candidate_name,
                    "spec": candidate_spec,
                    "usage": candidate_usage,
                    "unit_price": candidate_unit_price,
                    "amount": round(candidate_amount, 2),
                    "source": "kb",
                    "spec_ai": False,
                    "usage_ai": False,
                    "unit_price_ai": False,
                    "amount_ai": False,
                }
            )
            if len(items) >= MAX_ITEMS:
                break
        if len(items) >= MAX_ITEMS:
            break

    return RowScanResult(items=items, filtered_count=filtered_count)


def scan_rows_for_material_pairs(
    *,
    data_rows: list[list[str]],
    section_mode: bool,
    initial_section_letter: str,
    initial_section_title: str,
    excluded_slot_names: set[str] | None = None,
) -> RowScanResult:
    filtered_count = 0
    current_section_letter = initial_section_letter
    current_section_title = initial_section_title
    items: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    excluded_slot_names = excluded_slot_names or set()

    for row in data_rows:
        marker = detect_section_marker(row)
        if marker is not None:
            current_section_letter, current_section_title = marker
            filtered_count += 1
            continue

        if section_mode:
            if not current_section_letter:
                filtered_count += 1
                continue
            if not section_allows_material(current_section_letter, current_section_title):
                filtered_count += 1
                continue

        if not row_contains_material_pair_signature(row):
            filtered_count += 1
            continue

        row_added = False
        for idx in range(0, max(0, len(row) - 1)):
            label = row_get(row, idx).strip()
            if not label:
                continue
            if not is_material_pair_label(label):
                continue
            if looks_like_technical_key(label):
                # Skip machine keys such as "outer_material" and use the
                # neighboring human-readable label/value pair instead.
                continue
            slot_name = simplify_material_slot(label)
            normalized_slot_name = normalize_text(slot_name)
            if normalized_slot_name and normalized_slot_name in excluded_slot_names:
                continue
            value = find_material_pair_value(row, idx)
            if not value:
                continue

            spec_value = slot_name if is_probable_material_slot_name(slot_name) else "-"
            split_values = split_material_pair_values(value)
            for display_name in split_values:
                normalized_name = normalize_text(display_name)
                if normalized_name in seen_names:
                    continue
                seen_names.add(normalized_name)

                items.append(
                    {
                        "name": display_name,
                        "spec": spec_value,
                        "usage": "-",
                        "unit_price": "-",
                        "amount": 0.0,
                        "source": "kb",
                        "spec_ai": False,
                        "usage_ai": False,
                        "unit_price_ai": False,
                        "amount_ai": False,
                    }
                )
                row_added = True
                if len(items) >= MAX_ITEMS:
                    break
            if len(items) >= MAX_ITEMS:
                break
        if len(items) >= MAX_ITEMS:
            break
        if not row_added:
            filtered_count += 1

    return RowScanResult(items=items, filtered_count=filtered_count)


def merge_row_scan_results(*scans: RowScanResult) -> RowScanResult:
    merged_items: list[dict[str, Any]] = []
    item_index: dict[str, int] = {}
    filtered_candidates = [scan.filtered_count for scan in scans]

    for scan in scans:
        for item in scan.items:
            key = normalize_text(item.get("name", ""))
            if not key:
                continue
            existing_pos = item_index.get(key)
            if existing_pos is None:
                item_index[key] = len(merged_items)
                merged_items.append(item)
                continue

            existing = merged_items[existing_pos]
            if score_item_quality(item) > score_item_quality(existing):
                merged_items[existing_pos] = item

    return RowScanResult(
        items=merged_items,
        filtered_count=min(filtered_candidates) if filtered_candidates else 0,
    )


def score_item_quality(item: dict[str, Any]) -> int:
    score = 0
    unit_price = str(item.get("unit_price", "")).strip()
    spec = str(item.get("spec", "")).strip()
    usage = str(item.get("usage", "")).strip()
    amount = parse_amount(str(item.get("amount", ""))) or 0.0

    if amount > 0:
        score += 8
    if unit_price and not is_placeholder(unit_price):
        score += 4
    if spec and not is_placeholder(spec):
        score += 2
    if usage and not is_placeholder(usage):
        score += 2
    return score


def has_section_structure(rows: list[list[str]]) -> bool:
    for row in rows:
        if detect_section_marker(row) is not None:
            return True
    return False


def last_section_before_index(rows: list[list[str]], index: int) -> tuple[str, str]:
    if index <= 0:
        return "", ""
    for cursor in range(index - 1, -1, -1):
        marker = detect_section_marker(rows[cursor])
        if marker is not None:
            return marker
    return "", ""


def detect_section_marker(row: list[str]) -> tuple[str, str] | None:
    first = row_get(row, 0).strip()
    second = row_get(row, 1).strip()
    if not first:
        return None

    matched = SECTION_TITLE_PATTERN.match(first)
    if matched:
        letter = matched.group(1).lower()
        title = matched.group(2).strip()
        return letter, title

    matched_group = SECTION_GROUP_PATTERN.match(first)
    if matched_group:
        letter = matched_group.group(1).lower()
        title = matched_group.group(2).strip() or second
        return letter, title

    if SINGLE_SECTION_LETTER_PATTERN.match(first) and second:
        return first.lower(), second

    return None


def section_allows_material(section_letter: str, section_title: str) -> bool:
    normalized_letter = normalize_text(section_letter)
    if normalized_letter in ALLOWED_ITEM_SECTIONS:
        return True
    normalized_title = normalize_text(section_title)
    return contains_any(normalized_title, SECTION_ITEM_HINTS)


_PARAM_LABEL_HINTS = (
    "名称",
    "编号",
    "国家",
    "城市",
    "币种",
    "利润率",
    "含税",
    "业务员",
    "incoterms",
    "汇率",
    "价格",
    "交期",
    "有效期",
    "产品",
    "结构",
    "数量",
    "规格",
    "类型",
    "logo",
    "工艺",
)

_PARAM_HEADER_SUFFIXES = (
    "名称",
    "编号",
    "率",
    "要求",
    "类型",
    "说明",
    "内容",
    "方式",
    "口径",
    "汇率",
    "币种",
    "等级",
    "选",
    "复杂程度",
)


def _looks_like_param_label(text: str) -> bool:
    t = str(text or "").strip()
    if not t or is_placeholder(t):
        return False
    if SECTION_TITLE_PATTERN.match(t) or SECTION_PREFIX_PATTERN.match(t):
        return False
    if SINGLE_SECTION_LETTER_PATTERN.match(t):
        return False
    nt = normalize_text(t)
    if re.fullmatch(r"[\d.]+", nt):
        return False
    if nt in {"l", "w", "h"} or "(cm)" in nt:
        return True
    if nt == "product_name":
        return True
    if any(s in t for s in _PARAM_HEADER_SUFFIXES):
        return True
    if contains_any(nt, _PARAM_LABEL_HINTS):
        return True
    return False


def _looks_like_horizontal_param_header(row: list[str]) -> bool:
    labels = [str(c or "").strip() for c in row if _looks_like_param_label(str(c or ""))]
    return len(labels) >= 2


def _row_has_nonempty_cell(row: list[str]) -> bool:
    return any(str(cell or "").strip() for cell in row)


def _next_horizontal_value_row_index(rows: list[list[str]], header_index: int) -> int | None:
    """Return the value row immediately after a horizontal header (blank rows only in between)."""
    for idx in range(header_index + 1, len(rows)):
        if not _row_has_nonempty_cell(rows[idx]):
            continue
        if detect_section_marker(rows[idx]) is not None:
            return None
        return idx
    return None


def _looks_like_horizontal_param_values(header_row: list[str], value_row: list[str]) -> bool:
    header_labels = sum(1 for c in header_row if _looks_like_param_label(str(c or "")))
    value_labels = sum(1 for c in value_row if _looks_like_param_label(str(c or "")))
    if header_labels >= 2 and value_labels >= header_labels:
        return False
    if _looks_like_horizontal_param_header(value_row):
        label_like = value_labels
        non_empty = sum(1 for c in value_row if str(c or "").strip())
        if label_like >= 2 and label_like >= max(1, non_empty - 1):
            return False
    paired = 0
    for idx, header in enumerate(header_row):
        ht = str(header or "").strip()
        if not ht or not _looks_like_param_label(ht):
            continue
        vt = str(row_get(value_row, idx)).strip()
        if vt and not is_placeholder(vt):
            paired += 1
    return paired >= 1


def _zip_horizontal_params(header_row: list[str], value_row: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    max_len = max(len(header_row), len(value_row))
    for idx in range(max_len):
        header = str(row_get(header_row, idx)).strip()
        if not header or not _looks_like_param_label(header):
            continue
        value = str(row_get(value_row, idx)).strip()
        if not value or is_placeholder(value):
            continue
        key = normalize_parameter_key(header)
        if key:
            out[key] = value
    return out


def extract_quote_parameters(rows: list[list[str]]) -> dict[str, dict[str, str]]:
    params: dict[str, dict[str, str]] = {}
    current_section_letter = ""
    current_section_title = ""
    row_index = 0
    row_count = len(rows)

    while row_index < row_count:
        row = rows[row_index]
        marker = detect_section_marker(row)
        if marker is not None:
            current_section_letter, current_section_title = marker
            row_index += 1
            continue

        if not current_section_letter:
            row_index += 1
            continue
        if section_allows_material(current_section_letter, current_section_title):
            row_index += 1
            continue

        if _looks_like_horizontal_param_header(row):
            value_idx = _next_horizontal_value_row_index(rows, row_index)
            if value_idx is not None:
                value_row = rows[value_idx]
                if _looks_like_horizontal_param_values(row, value_row):
                    section_key = current_section_letter.upper()
                    section_params = params.setdefault(section_key, {})
                    section_params.update(_zip_horizontal_params(row, value_row))
                    row_index = value_idx + 1
                    continue

        key = row_get(row, 0).strip()
        if not key:
            row_index += 1
            continue
        if is_placeholder(key):
            row_index += 1
            continue
        if SINGLE_SECTION_LETTER_PATTERN.match(key):
            row_index += 1
            continue
        if SECTION_PREFIX_PATTERN.match(key):
            row_index += 1
            continue

        value = pick_parameter_value(row)
        if not value:
            row_index += 1
            continue
        if is_placeholder(value):
            row_index += 1
            continue

        section_key = current_section_letter.upper()
        section_params = params.setdefault(section_key, {})
        normalized_key = normalize_parameter_key(key)
        if normalized_key:
            section_params[normalized_key] = value
        row_index += 1

    return params


def infer_sheet_product_name(quote_params: dict[str, dict[str, str]], rows: list[list[str]]) -> str:
    for section_params in quote_params.values():
        for key, value in section_params.items():
            key_text = normalize_text(key)
            if not key_text:
                continue
            if any(keyword in key_text for keyword in PRODUCT_NAME_KEYWORDS):
                candidate = str(value).strip()
                if is_probable_product_name(candidate):
                    return candidate

    for row in rows:
        for idx, cell in enumerate(row):
            key = str(cell or "").strip()
            if not key:
                continue
            key_text = normalize_text(key)
            if not any(keyword in key_text for keyword in PRODUCT_NAME_KEYWORDS):
                continue
            candidate = pick_first_meaningful_cell(row, start=idx + 1)
            if candidate and is_probable_product_name(candidate):
                return candidate
    return ""


def pick_first_meaningful_cell(row: list[str], *, start: int) -> str:
    for idx in range(start, len(row)):
        value = str(row_get(row, idx)).strip()
        if not value or is_placeholder(value):
            continue
        if looks_like_technical_key(value):
            continue
        return value
    return ""


def is_probable_product_name(value: str) -> bool:
    text = normalize_text(value)
    if not text:
        return False
    if contains_any(text, TITLE_KEYWORDS):
        return False
    if looks_like_technical_key(text):
        return False
    if len(text) < 2:
        return False
    return True


def pick_parameter_value(row: list[str]) -> str:
    trailing = [cell.strip() for cell in row[2:] if cell.strip()]
    if trailing:
        return trailing[0]
    fallback = [cell.strip() for cell in row[1:] if cell.strip()]
    if not fallback:
        return ""
    return fallback[0]


def normalize_parameter_key(key: str) -> str:
    cleaned = normalize_text(key)
    cleaned = cleaned.replace(" ", "_")
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned


def find_header_and_column_map(
    rows: list[list[str]], *, start_row: int | None
) -> tuple[int | None, dict[str, Any]]:
    if start_row is not None:
        default_map = dict(DEFAULT_COLUMN_ORDER)
        default_map["has_header"] = False
        return None, default_map

    for idx, row in enumerate(rows):
        if not any(cell.strip() for cell in row):
            continue
        column_map = build_column_map(row)
        if column_map["has_header"]:
            return idx, column_map

    default_map = dict(DEFAULT_COLUMN_ORDER)
    default_map["has_header"] = False
    return None, default_map


def build_column_map(header_row: list[str]) -> dict[str, Any]:
    normalized = [normalize_header(cell) for cell in header_row]
    mapped: dict[str, int] = {}

    for key, aliases in HEADER_ALIASES.items():
        for index, header in enumerate(normalized):
            if header in aliases:
                mapped[key] = index
                break

    # Header is considered valid only when material-name column is found and
    # at least one additional field column exists.
    has_header = "name" in mapped and len(mapped) >= 2
    if not has_header:
        mapped = dict(DEFAULT_COLUMN_ORDER)
    else:
        for key, default_index in DEFAULT_COLUMN_ORDER.items():
            mapped.setdefault(key, default_index)

    mapped["has_header"] = has_header
    return mapped


def map_row_values(row: list[str], column_map: dict[str, Any]) -> dict[str, Any]:
    name = row_get(row, column_map["name"]).strip()
    spec = row_get(row, column_map["spec"]).strip()
    usage = row_get(row, column_map["usage"]).strip()
    unit_price = row_get(row, column_map["unit_price"]).strip()
    amount_text = row_get(row, column_map["amount"]).strip()
    amount = parse_amount(amount_text)
    if amount is None:
        amount = 0.0
    return {
        "name": name,
        "spec": spec,
        "usage": usage,
        "unit_price": unit_price,
        "amount_text": amount_text,
        "amount": amount,
        "joined": " ".join(cell for cell in row if cell).strip(),
    }


def is_valid_material_row(
    mapped: dict[str, Any],
    *,
    require_unit_price: bool = True,
    strict_spec_descriptor: bool = True,
) -> bool:
    name = mapped["name"].strip()
    joined = mapped["joined"].strip()
    spec = mapped["spec"].strip()
    usage = mapped["usage"].strip()
    unit_price = mapped["unit_price"].strip()
    amount_text = mapped["amount_text"].strip()
    section_letter = str(mapped.get("section_letter", "")).strip()
    section_title = str(mapped.get("section_title", "")).strip()

    if not name:
        return False
    if is_placeholder(name):
        return False
    if is_non_material_label_name(name):
        return False
    if "标准名" in name and ("编码" in name or "code" in normalize_text(name)):
        return False
    if name.endswith("颜色"):
        return False
    if SINGLE_SECTION_LETTER_PATTERN.match(name):
        return False
    if SECTION_PREFIX_PATTERN.match(name):
        return False

    lowered_name = normalize_text(name)
    lowered_joined = normalize_text(joined)
    lowered_unit_price = normalize_text(unit_price)

    if section_letter and not section_allows_material(section_letter, section_title):
        return False
    if contains_any(lowered_joined, TITLE_KEYWORDS):
        return False
    if contains_any(lowered_joined, SECTION_KEYWORDS):
        return False
    if contains_any(lowered_name, HEADER_OR_CONFIG_KEYWORDS):
        return False
    if contains_any(lowered_name, MATERIAL_NAME_BLACKLIST_KEYWORDS):
        return False
    if looks_like_material_description_sentence(name):
        return False
    if contains_any(lowered_joined, CONFIG_METADATA_KEYWORDS):
        return False
    if is_obvious_concatenated_material_name(name) and not bool(mapped.get("allow_split_name")):
        return False

    if row_looks_like_column_label_row(name, spec, usage, unit_price, amount_text):
        return False
    if row_looks_like_header_or_config(name, spec, usage, unit_price, amount_text):
        return False
    if row_looks_like_non_material_setting(name, spec, usage, unit_price, amount_text):
        return False
    if is_empty_data_row(spec, usage, unit_price, amount_text):
        return False
    if not has_any_effective_data(spec, usage, unit_price, amount_text, mapped["amount"]):
        return False
    if is_placeholder(spec) and is_placeholder(usage):
        return False
    if strict_spec_descriptor and looks_like_config_descriptor(spec):
        return False
    if looks_like_config_descriptor(usage):
        return False
    if lowered_unit_price in INVALID_UNIT_PRICE_VALUES:
        return False

    unit_price_value = parse_amount(unit_price)
    if require_unit_price:
        if unit_price_value is None or unit_price_value <= 0:
            return False
    elif (
        unit_price_value is None
        and mapped["amount"] <= 0
        and is_placeholder(usage)
        and is_placeholder(spec)
    ):
        # Relaxed fallback still requires at least one meaningful value cell.
        return False
    return True


def row_looks_like_header_or_config(name: str, spec: str, usage: str, unit_price: str, amount_text: str) -> bool:
    cells = [name, spec, usage, unit_price, amount_text]
    header_like_hits = 0
    for cell in cells:
        normalized = normalize_text(cell)
        if not normalized:
            continue
        if contains_any(normalized, HEADER_OR_CONFIG_KEYWORDS):
            header_like_hits += 1
    return header_like_hits >= 2


def row_looks_like_column_label_row(
    name: str, spec: str, usage: str, unit_price: str, amount_text: str
) -> bool:
    cells = [name, spec, usage, unit_price, amount_text]
    non_empty = [cell.strip() for cell in cells if cell.strip() and not is_placeholder(cell)]
    if len(non_empty) < 2:
        return False

    label_hits = 0
    for cell in non_empty:
        normalized = normalize_text(cell)
        if contains_any(normalized, COLUMN_LABEL_HINT_KEYWORDS):
            label_hits += 1
            continue
        if ("标准名" in cell and ("编码" in cell or "code" in normalized)) or cell.endswith("颜色"):
            label_hits += 1
            continue
        if "_" in normalized and normalized.replace("_", "").isalnum():
            label_hits += 1

    slash_like_cells = sum(1 for cell in non_empty if "/" in cell or "\\" in cell)
    paren_like_cells = sum(1 for cell in non_empty if "(" in cell and ")" in cell)
    if paren_like_cells >= 1 and slash_like_cells >= 2:
        return True

    return label_hits >= max(2, len(non_empty) - 2)


def row_looks_like_non_material_setting(
    name: str, spec: str, usage: str, unit_price: str, amount_text: str
) -> bool:
    normalized_name = normalize_text(name)
    if normalized_name.startswith("\u662f\u5426"):
        return True
    if normalized_name.startswith("is ") or normalized_name.startswith("need "):
        return True
    if contains_any(normalized_name, CONFIG_FIELD_HINTS):
        return True

    if ("\uff1a" in name or ":" in name) and is_empty_data_row(spec, usage, unit_price, amount_text):
        return True

    value_fields = [spec, usage, unit_price, amount_text]
    filled_fields = [value for value in value_fields if not is_placeholder(value)]
    if len(filled_fields) != 1:
        return False
    if not is_placeholder(unit_price) or not is_placeholder(amount_text):
        return False

    setting_value = normalize_text(filled_fields[0])
    if setting_value in {"yes", "no", "\u662f", "\u5426", "cny", "usd", "eur", "fob", "exw", "ddp"}:
        return True
    if contains_any(normalized_name, CONFIG_FIELD_HINTS) and len(setting_value) <= 16:
        return True
    return False


def row_contains_material_pair_signature(row: list[str]) -> bool:
    non_empty = [str(cell).strip() for cell in row if str(cell).strip() and not is_placeholder(str(cell))]
    if len(non_empty) < 2:
        return False

    first = non_empty[0]
    second = non_empty[1]
    if (
        len(non_empty) <= 3
        and is_probable_material_slot_name(first)
        and looks_like_material_pair_value(second)
    ):
        return True

    for cell in non_empty:
        normalized = normalize_text(cell)
        if looks_like_technical_key(cell):
            return True
        if ("标准名" in cell and ("编码" in cell or "code" in normalized)) or "name/code" in normalized:
            return True

    return False


def is_material_pair_label(label: str) -> bool:
    normalized = normalize_text(label)
    if not normalized:
        return False
    name_code_hint = ("标准名" in label and "编码" in label) or ("name" in normalized and "code" in normalized)
    if ("/" in label or "\\" in label) and not name_code_hint:
        return False
    if contains_any(normalized, MATERIAL_PAIR_LABEL_BLOCK_KEYWORDS):
        return False
    if name_code_hint:
        return True
    if contains_any(normalized, MATERIAL_PAIR_LABEL_HINT_KEYWORDS):
        return True
    if looks_like_technical_key(label) and contains_any(normalized, MATERIAL_PAIR_TECH_KEY_HINTS):
        return True
    return False


def is_probable_material_slot_name(value: str) -> bool:
    text = normalize_text(value)
    if not text:
        return False
    if contains_any(text, MATERIAL_PAIR_LABEL_BLOCK_KEYWORDS):
        return False
    if contains_any(text, MATERIAL_PAIR_LABEL_HINT_KEYWORDS):
        return True
    if any(ch in value for ch in ("料", "布", "链", "带", "扣", "标", "包")):
        return True
    return False


def find_material_pair_value(row: list[str], label_index: int) -> str:
    max_index = min(len(row), label_index + 7)
    for cursor in range(label_index + 1, max_index):
        candidate = row_get(row, cursor).strip()
        if not candidate or is_placeholder(candidate):
            continue
        if cursor != label_index + 1 and is_material_pair_label(candidate):
            break
        if looks_like_technical_key(candidate):
            continue
        if not looks_like_material_pair_value(candidate):
            continue
        return candidate
    return ""


MATERIAL_VALUE_SPLIT_PATTERN = re.compile(r"[,\uFF0C;\uFF1B+\uFF0B]+")
MATERIAL_ACTION_DESC_KEYWORDS = (
    "\u5916\u4fa7\u4f7f\u7528",
    "\u5185\u4fa7\u4e3a",
    "\u7ed3\u6784",
    "\u7528\u4e8e",
    "\u8bf4\u660e",
    "\u5efa\u8bae",
    "\u5de5\u827a",
    "\u914d\u8272",
    "\u8c03\u6574",
    "\u56fa\u5b9a",
    "\u5305\u888b",
    "\u52a0\u5bbd",
    "\u5927\u5bb9\u91cf",
    "\u4e0b\u65b9",
    "\u4e0a\u6709",
    "\u53e3\u888b",
)
MATERIAL_DESC_FORBIDDEN_PREFIXES = (
    "\u5916\u4fa7\u4f7f\u7528",
    "\u5185\u4fa7\u4e3a",
    "\u5185\u4fa7\u4f7f\u7528",
    "\u52a0\u5bbd\u80a9\u5e26",
    "\u5927\u5bb9\u91cf\u5355\u4e3b\u4ed3",
)
STRONG_MATERIAL_NAME_TOKENS = (
    "\u63d2\u6263",
    "\u62c9\u94fe",
    "\u62c9\u5934",
    "\u7ec7\u5e26",
    "\u7f51\u5e03",
    "\u5c3c\u9f99",
    "\u6da4\u7eb6",
    "d\u6263",
    "\u68af\u6263",
    "\u731d\u9f3b\u6263",
    "\u725b\u6263",
    "\u725b\u7b4b",
)
MATERIAL_NAME_HINT_KEYWORDS = (
    "\u6599",
    "\u5e03",
    "\u7f51\u5e03",
    "\u62c9\u94fe",
    "\u7ec7\u5e26",
    "\u80a9\u5e26",
    "\u63d2\u6263",
    "\u65e5\u5b57\u6263",
    "d\u6263",
    "\u6263",
    "\u731d\u9f3b\u6263",
    "\u914d\u4ef6",
    "\u9f99\u867e\u6263",
    "fabric",
    "lining",
    "zipper",
    "webbing",
    "buckle",
    "accessory",
)
MATERIAL_NAME_CONNECTOR_KEYWORDS = (
    "\u548c",
    "\u53ca",
    "\u5e76",
    "\u642d\u914d",
    "\u4ee5\u53ca",
    "\u52a0",
    "\u3001",
    "+",
    "/",
)
MATERIAL_QTY_PHRASE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:\u4e2a|\u53ea|\u6761|\u9897|\u5957|pcs?|pc)",
    flags=re.IGNORECASE,
)


def split_material_pair_values(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []

    # Sales often mix delimiters in one cell; split them into individual items.
    parts = [part.strip() for part in MATERIAL_VALUE_SPLIT_PATTERN.split(raw) if part.strip()]
    if len(parts) <= 1:
        return [raw]

    valid_parts = [part for part in parts if looks_like_material_pair_value(part)]
    if valid_parts:
        return valid_parts
    return [raw]


def _looks_like_strong_material_token(normalized: str) -> bool:
    return contains_any(normalized, STRONG_MATERIAL_NAME_TOKENS)


def looks_like_material_description_sentence(value: str) -> bool:
    text = str(value or "").strip()
    normalized = normalize_text(text)
    if not normalized:
        return False
    for prefix in MATERIAL_DESC_FORBIDDEN_PREFIXES:
        if text.startswith(prefix) or normalized.startswith(normalize_text(prefix)):
            return True
    if ("(" in text or "\uff08" in text) and contains_any(
        normalized,
        ("\u5185\u4fa7", "\u5916\u4fa7", "\u4f7f\u7528", "\u7ed3\u6784", "\u52a0\u5bbd"),
    ):
        if not _looks_like_strong_material_token(normalized):
            return True
    if not contains_any(normalized, MATERIAL_ACTION_DESC_KEYWORDS):
        return False
    if quantity_phrase_count(value) > 0 and _looks_like_strong_material_token(normalized):
        return False
    if quantity_phrase_count(value) == 0 and len(normalized) >= 6:
        return True
    return not _looks_like_strong_material_token(normalized)


def quantity_phrase_count(value: str) -> int:
    return len(MATERIAL_QTY_PHRASE_PATTERN.findall(str(value or "")))


def is_obvious_concatenated_material_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    qty_count = quantity_phrase_count(text)
    if qty_count < 2:
        return False
    normalized = normalize_text(text)
    has_connector = contains_any(normalized, MATERIAL_NAME_CONNECTOR_KEYWORDS)
    return has_connector or len(text.replace(" ", "")) >= 12


def split_concatenated_material_name(name: str) -> list[str]:
    text = str(name or "").strip()
    if not is_obvious_concatenated_material_name(text):
        return []

    qty_matches = list(MATERIAL_QTY_PHRASE_PATTERN.finditer(text))
    if len(qty_matches) < 2:
        return []

    parts: list[str] = []
    cursor = 0
    for match in qty_matches:
        segment = text[cursor : match.end()].strip(" ,\uFF0C;\uFF1B+\uFF0B")
        cursor = match.end()
        if segment:
            parts.append(segment)
    tail = text[cursor:].strip(" ,\uFF0C;\uFF1B+\uFF0B")
    if tail and parts:
        parts[-1] = f"{parts[-1]} {tail}".strip()

    clean_parts: list[str] = []
    for part in parts:
        if quantity_phrase_count(part) != 1:
            continue
        if looks_like_material_description_sentence(part):
            continue
        if not contains_any(normalize_text(part), MATERIAL_NAME_HINT_KEYWORDS):
            continue
        clean_parts.append(part)
    return clean_parts


def expand_material_row_candidates(
    *,
    name: str,
    spec: str,
    usage: str,
    unit_price: str,
    amount: float,
) -> list[tuple[str, str, str, str, float]]:
    if looks_like_material_description_sentence(name):
        return []
    split_names = split_concatenated_material_name(name)
    if not split_names:
        return [(name, spec, usage, unit_price, amount)]

    expanded: list[tuple[str, str, str, str, float]] = []
    for idx, split_name in enumerate(split_names):
        if idx == 0:
            expanded.append((split_name, spec, usage, unit_price, amount))
            continue
        expanded.append((split_name, spec, "-", "-", 0.0))
    return expanded


def simple_bom_material_candidates(
    *,
    name: str,
    spec: str = "",
    unit_price: str = "",
    amount: float = 0.0,
) -> list[dict[str, Any]]:
    """Simple-BOM「说明」列：过滤结构说明句，并按数量词拆分拼接物料名。"""
    raw_name = str(name or "").strip()
    if not raw_name or should_drop_upload_name(raw_name):
        return []
    if looks_like_material_description_sentence(raw_name):
        return []
    spec_value = str(spec or "").strip() or "-"
    price_value = str(unit_price or "").strip() or "-"
    amt = round(float(amount or 0.0), 2)
    rows: list[dict[str, Any]] = []
    for candidate_name, candidate_spec, _usage, candidate_price, candidate_amount in expand_material_row_candidates(
        name=raw_name,
        spec=spec_value,
        usage="-",
        unit_price=price_value,
        amount=amt,
    ):
        rows.append(
            {
                "name": candidate_name,
                "spec": candidate_spec,
                "unit_price": candidate_price,
                "amount": round(float(candidate_amount or 0.0), 2),
            }
        )
    return rows


def looks_like_technical_key(value: str) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    if "_" in normalized and normalized.replace("_", "").isalnum():
        return True
    if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", normalized):
        return True
    if normalized.endswith(("_name", "_code", "_id", "_type", "_flag")):
        return True
    return False


def looks_like_material_pair_value(value: str) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    if is_placeholder(value):
        return False
    if contains_any(normalized, TITLE_KEYWORDS):
        return False
    if contains_any(normalized, SECTION_KEYWORDS):
        return False
    if contains_any(normalized, HEADER_OR_CONFIG_KEYWORDS):
        return False
    if contains_any(normalized, CONFIG_METADATA_KEYWORDS):
        return False
    if contains_any(normalized, MATERIAL_NAME_BLACKLIST_KEYWORDS):
        return False
    if contains_any(normalized, MATERIAL_PAIR_LABEL_BLOCK_KEYWORDS):
        return False
    if looks_like_material_description_sentence(value):
        return False
    if looks_like_quantity_ladder_value(normalized):
        return False
    if looks_like_config_descriptor(value):
        return False
    if re.fullmatch(r"-?\d+(\.\d+)?", normalized):
        return False
    if normalized in {"yes", "no", "true", "false", "是", "否"}:
        return False
    if normalized in {"black", "white", "red", "blue", "green", "gray", "grey"}:
        return False
    if contains_any(normalized, ("刺绣", "丝印", "烫印", "热转印")) and not re.search(r"[a-z0-9]", normalized):
        return False
    if normalized.endswith("色") and len(normalized) <= 4:
        return False
    return True


def looks_like_quantity_ladder_value(normalized: str) -> bool:
    if not normalized:
        return False
    if re.search(r"(qty|quantity|数量)", normalized):
        return True
    parts = [part.strip() for part in re.split(r"[\\/,\|，]+", normalized) if part.strip()]
    if len(parts) < 2:
        return False
    numeric_parts = [part for part in parts if re.fullmatch(r"\d+(?:\.\d+)?", part)]
    return len(numeric_parts) >= 2


def simplify_material_slot(label: str) -> str:
    text = label.strip()
    text = re.sub(r"\s*\(.*?\)\s*", "", text)
    text = re.sub(r"\s*（.*?）\s*", "", text)
    return text or "-"


def looks_like_config_descriptor(value: str) -> bool:
    normalized = normalize_text(value)
    if not normalized or normalized in PLACEHOLDER_VALUES:
        return False
    if contains_any(normalized, CONFIG_SPEC_USAGE_KEYWORDS):
        return True
    if "_" in normalized and normalized.replace("_", "").isalnum():
        return True
    return False


def is_empty_data_row(spec: str, usage: str, unit_price: str, amount_text: str) -> bool:
    values = [spec, usage, unit_price, amount_text]
    return all(is_placeholder(value) for value in values)


def normalize_material_spec_usage(spec: str, usage: str) -> tuple[str, str]:
    spec_value = str(spec or "").strip() or "-"
    usage_value = str(usage or "").strip() or "-"

    if is_placeholder(spec_value):
        spec_value = "-"
    if is_placeholder(usage_value):
        usage_value = "-"

    if looks_like_technical_key(spec_value):
        spec_value = "-"
    if looks_like_technical_key(usage_value):
        usage_value = "-"

    return spec_value, usage_value


def has_any_effective_data(
    spec: str, usage: str, unit_price: str, amount_text: str, amount_value: float
) -> bool:
    if any(not is_placeholder(value) for value in (spec, usage, unit_price, amount_text)):
        return True
    return amount_value != 0.0


def parse_amount(text: str) -> float | None:
    cleaned = text.strip()
    if not cleaned:
        return None

    candidate = cleaned.replace(",", "")
    candidate = re.sub(r"[^\d.\-]", "", candidate)
    if not candidate:
        return None
    try:
        return float(candidate)
    except ValueError:
        return None


def parse_usage_quantity(text: str) -> float | None:
    value = str(text or "").strip().lower()
    if not value:
        return None
    # Ignore quantity ladder-like text, e.g. 300/500/1000.
    if "/" in value and re.search(r"\d+\s*/\s*\d+", value):
        return None
    matched = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
    if matched is None:
        return None
    try:
        return float(matched.group(0))
    except ValueError:
        return None


def row_get(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return row[index]


def normalize_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned_rows: list[list[str]] = []
    for row in rows:
        trimmed = [clean_cell_text(cell) for cell in row]
        while trimmed and trimmed[-1] == "":
            trimmed.pop()
        cleaned_rows.append(trimmed)
    return cleaned_rows


def normalize_header(header: str) -> str:
    text = normalize_text(header)
    text = text.replace("_", "").replace(" ", "").replace("-", "")
    text = text.replace("（", "").replace("）", "").replace("(", "").replace(")", "")
    text = text.replace("/", "").replace("\\", "").replace("：", "").replace(":", "")
    return text


def normalize_text(text: str) -> str:
    return str(text or "").strip().lower()


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


def is_placeholder(value: str) -> bool:
    normalized = normalize_text(value)
    if normalized in PLACEHOLDER_VALUES:
        return True
    return normalized.replace(" ", "") in PLACEHOLDER_VALUES


def column_index_from_ref(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    if not letters:
        return 0
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(0, idx - 1)


def nsmap(root: ElementTree.Element) -> dict[str, str]:
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[1 : root.tag.index("}")]
    return {
        "main": namespace,
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }


def clean_cell_text(value: str) -> str:
    text = (value or "").replace("\u3000", " ").replace("\xa0", " ")
    return text.strip()


def _parse_start_row(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed
