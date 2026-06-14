"""报价单展示内容清洗：描述字段与产品图筛选（不影响计价）。"""
from __future__ import annotations

import base64
import re
from typing import Any

# 整块删除的内部附录标题
_INTERNAL_BLOCK_MARKERS = (
    "【工作簿嵌入图片】",
    "【工作簿内超链接",
    "【附图说明】",
)

# 按行删除：问题X描述 + 冒号/空格 + 任意正文
_INTERNAL_LINE_PATTERNS = (
    re.compile(r"^问题[一二三四五六七八九十\d]+描述(?:[：:\s]|$).*$", re.I),
    re.compile(r"^问题[一二三四五六七八九十\d]+[：:\s].*$", re.I),
    re.compile(r"^背景指向.*$", re.I),
    re.compile(r"^图片说明(?:[：:\s]|$).*$", re.I),
    re.compile(r"^.*工作簿嵌入.*$", re.I),
    re.compile(r"^.*未向模型附带图像.*$", re.I),
    re.compile(r"^.*体积超限或未启用视觉.*$", re.I),
    re.compile(r"^.*解析过程.*$", re.I),
    re.compile(r"^.*调试文本.*$", re.I),
)

# 报价单款式图：仅接受明确产品/人工来源（Excel 匿名嵌入图默认拒绝）
TRUSTED_IMAGE_ROLES = frozenset(
    {
        "product_main",
        "product_style",
        "style_image",
        "bag_image",
        "manual_style",
        "user_upload",
        "agent_product",
        "product_row",
    }
)

_SHEET_EMBED_SOURCES = frozenset(
    {
        "sheet_embed",
        "sales_sheet",
        "admin_calculated",
        "admin_corrected",
        "excel_embed",
    }
)

_SOURCE_PATH_REJECT = re.compile(
    r"(qr|qrcode|logo|icon|watermark|stamp|条码|二维码|截图|screenshot|table|sheet|"
    r"工艺|尺寸表|说明图|文字|bom|物料|清单|明细|参数|spec|worksheet|excel|"
    r"bill[\s_-]?of[\s_-]?materials?|material[\s_-]?list|grid|清单表|规格表|参数表)",
    re.I,
)

_NON_PRODUCT_IMAGE_KEYWORDS = re.compile(
    r"(packag(?:e|ing)?|包装|label|标签|吊牌|hang[\s_-]?tag|material|材料|"
    r"size[\s_-]?chart|尺寸|dimension|spec[\s_-]?chart|chart|图表|"
    r"payment|pay(?:ment)?|付款|bank|银行|account|账号|收款|"
    r"receipt|小票|invoice|发票|ticket|票据|"
    r"barcode|条码|说明图|工艺|文字图|截图|screenshot|capture|"
    r"qrcode|qr[\s_-]?code|二维码|other|杂项|"
    r"bom|物料清单|材料表|明细表|清单表|参数表|规格表|"
    r"bill[\s_-]?of[\s_-]?materials?|material[\s_-]?list|worksheet|"
    r"excel[\s_-]?table|table[\s_-]?screenshot|grid|单元格|cell[\s_-]?grid)",
    re.I,
)

_PRODUCT_IMAGE_KEYWORDS = re.compile(
    r"(product|main|style|bag|款式|主图|product[\s_-]?main|style[\s_-]?image|bag[\s_-]?image)",
    re.I,
)

_REJECTED_IMAGE_ROLES = frozenset(
    {
        "packaging",
        "label",
        "material",
        "size",
        "chart",
        "payment",
        "bank",
        "qrcode",
        "screenshot",
        "other",
        "logo",
        "watermark",
        "stamp",
        "size_chart",
        "material_sample",
        "payment_info",
        "bank_info",
        "document",
        "table",
        "sheet",
    }
)

_MIN_EDGE_PX = 72
_MIN_AREA_PX = 80 * 80
_MAX_ASPECT_RATIO = 3.8
_TINY_MAX_EDGE = 110
_TINY_MAX_BYTES = 28_000

_PDF_DESC_MAX_LINES = 14
_PDF_DESC_MAX_CHARS = 1400
_PDF_DESC_OMISSION = "（其余结构说明已从报价单正文省略，详见确认版技术资料。）"


def _decode_image_blob(item: dict[str, Any]) -> bytes:
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


def _image_dimensions(blob: bytes) -> tuple[int, int] | None:
    if len(blob) < 24:
        return None
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(blob[16:20], "big")
        h = int.from_bytes(blob[20:24], "big")
        if w > 0 and h > 0:
            return w, h
        return None
    if blob[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(blob):
            if blob[i] != 0xFF:
                i += 1
                continue
            marker = blob[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h = int.from_bytes(blob[i + 5 : i + 7], "big")
                w = int.from_bytes(blob[i + 7 : i + 9], "big")
                if w > 0 and h > 0:
                    return w, h
                return None
            if i + 3 >= len(blob):
                break
            seg_len = int.from_bytes(blob[i + 2 : i + 4], "big")
            if seg_len < 2:
                break
            i += 2 + seg_len
    return None


def image_label_text(item: dict[str, Any]) -> str:
    """合并文件路径/文件名/角色标签等用于关键词判定（不含内部来源枚举如 sheet_embed）。"""
    if not isinstance(item, dict):
        return ""
    parts: list[str] = []
    for key in (
        "source_path",
        "file_name",
        "original_name",
        "image_role",
        "source_role",
        "tags",
        "caption",
    ):
        val = item.get(key)
        if val is None:
            continue
        if isinstance(val, (list, tuple)):
            parts.extend(str(x) for x in val if x)
        else:
            parts.append(str(val))
    return " ".join(parts).strip().lower()


def has_non_product_image_keywords(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if _SOURCE_PATH_REJECT.search(s):
        return True
    return bool(_NON_PRODUCT_IMAGE_KEYWORDS.search(s))


def has_product_image_keywords(text: str) -> bool:
    return bool(_PRODUCT_IMAGE_KEYWORDS.search(str(text or "")))


IMAGE_TYPE_PRODUCT = "product_photo"
IMAGE_TYPE_BOM = "bom_table"
IMAGE_TYPE_SPEC = "spec_table"
IMAGE_TYPE_UNKNOWN = "unknown"


def _png_unfilter_scanline(filter_type: int, row: list[int], prev: list[int], bpp: int) -> list[int]:
    out = row[:]
    if filter_type == 0:
        return out
    if filter_type == 1:
        for i in range(len(out)):
            left = out[i - bpp] if i >= bpp else 0
            out[i] = (out[i] + left) & 0xFF
        return out
    if filter_type == 2:
        for i in range(len(out)):
            out[i] = (out[i] + prev[i]) & 0xFF
        return out
    if filter_type == 3:
        for i in range(len(out)):
            left = out[i - bpp] if i >= bpp else 0
            up = prev[i]
            out[i] = (out[i] + ((left + up) // 2)) & 0xFF
        return out
    # Paeth
    for i in range(len(out)):
        left = out[i - bpp] if i >= bpp else 0
        up = prev[i]
        up_left = prev[i - bpp] if i >= bpp else 0
        p = left + up - up_left
        pa = abs(p - left)
        pb = abs(p - up)
        pc = abs(p - up_left)
        nearest = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
        out[i] = (out[i] + nearest) & 0xFF
    return out


def _decode_png_rgb_matrix(blob: bytes) -> list[list[tuple[int, int, int]]] | None:
    import struct
    import zlib

    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    width = height = 0
    bit_depth = 0
    color_type = 0
    idat_parts: list[bytes] = []
    palette: list[tuple[int, int, int]] = []
    while pos + 8 <= len(blob):
        length = int.from_bytes(blob[pos : pos + 4], "big")
        ctype = blob[pos + 4 : pos + 8]
        data = blob[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, *_rest = struct.unpack(">IIBBBBB", data)
        elif ctype == b"PLTE":
            palette = [tuple(data[i : i + 3]) for i in range(0, len(data), 3)]
        elif ctype == b"IDAT":
            idat_parts.append(data)
        elif ctype == b"IEND":
            break
    if not idat_parts or width <= 0 or height <= 0 or bit_depth != 8:
        return None
    bpp_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    bpp = bpp_map.get(color_type)
    if not bpp:
        return None
    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except zlib.error:
        return None
    stride = width * bpp
    if len(raw) < height * (1 + stride):
        return None
    rgb_rows: list[list[tuple[int, int, int]]] = []
    offset = 0
    prev = [0] * stride
    for _y in range(height):
        filter_type = raw[offset]
        offset += 1
        scan = list(raw[offset : offset + stride])
        offset += stride
        scan = _png_unfilter_scanline(filter_type, scan, prev, bpp)
        prev = scan[:]
        row_rgb: list[tuple[int, int, int]] = []
        if color_type == 2:
            for x in range(width):
                i = x * 3
                row_rgb.append((scan[i], scan[i + 1], scan[i + 2]))
        elif color_type == 0:
            for x in range(width):
                g = scan[x]
                row_rgb.append((g, g, g))
        elif color_type == 3 and palette:
            for x in range(width):
                idx = scan[x]
                row_rgb.append(palette[idx] if idx < len(palette) else (255, 255, 255))
        else:
            return None
        rgb_rows.append(row_rgb)
    return rgb_rows


def _downsample_luma_grid(
    rgb_rows: list[list[tuple[int, int, int]]],
    max_side: int = 96,
) -> list[list[int]]:
    h = len(rgb_rows)
    w = len(rgb_rows[0]) if h else 0
    if w <= 0 or h <= 0:
        return []
    scale = max(w, h) / max(1, max_side)
    tw = max(8, int(round(w / scale)))
    th = max(8, int(round(h / scale)))
    grid: list[list[int]] = []
    for tr in range(th):
        sr = min(h - 1, int(tr * h / th))
        row: list[int] = []
        for tc in range(tw):
            sc = min(w - 1, int(tc * w / tw))
            r, g, b = rgb_rows[sr][sc]
            row.append(int(0.299 * r + 0.587 * g + 0.114 * b))
        grid.append(row)
    return grid


def _image_luma_grid(blob: bytes, max_side: int = 96) -> list[list[int]] | None:
    rgb = _decode_png_rgb_matrix(blob)
    if not rgb:
        return None
    return _downsample_luma_grid(rgb, max_side=max_side)


def _row_edge_density(row: list[int], threshold: int = 38) -> float:
    if len(row) < 2:
        return 0.0
    hits = sum(1 for i in range(1, len(row)) if abs(row[i] - row[i - 1]) >= threshold)
    return hits / (len(row) - 1)


def _col_edge_density(grid: list[list[int]], col: int, threshold: int = 38) -> float:
    if len(grid) < 2:
        return 0.0
    hits = sum(
        1 for r in range(1, len(grid)) if abs(grid[r][col] - grid[r - 1][col]) >= threshold
    )
    return hits / (len(grid) - 1)


def _table_grid_score(grid: list[list[int]]) -> float:
    """0~1：越高越像 Excel/BOM 表格截图（网格线 + 文字块 + 白底）。"""
    h = len(grid)
    w = len(grid[0]) if h else 0
    if h < 8 or w < 8:
        return 0.0
    pixels = h * w
    white = sum(1 for r in range(h) for c in range(w) if grid[r][c] >= 232)
    dark = sum(1 for r in range(h) for c in range(w) if grid[r][c] <= 120)
    white_ratio = white / pixels
    text_ratio = dark / pixels

    h_line_rows = sum(1 for r in range(h) if _row_edge_density(grid[r]) >= 0.22)
    v_line_cols = sum(1 for c in range(w) if _col_edge_density(grid, c) >= 0.20)

    dense_text_rows = 0
    for r in range(h):
        dr = sum(1 for c in range(w) if grid[r][c] <= 130) / w
        if 0.06 <= dr <= 0.42 and _row_edge_density(grid[r]) >= 0.10:
            dense_text_rows += 1

    score = 0.0
    if h_line_rows >= max(5, int(h * 0.08)) and v_line_cols >= max(3, int(w * 0.06)):
        score += 0.55
    elif h_line_rows >= max(7, int(h * 0.12)):
        score += 0.35
    if white_ratio >= 0.38 and text_ratio >= 0.04:
        score += 0.15
    if dense_text_rows >= max(6, int(h * 0.10)):
        score += 0.20
    if h_line_rows >= 8 and v_line_cols >= 5 and white_ratio >= 0.30:
        score += 0.15
    return min(1.0, score)


def _text_dense_document_score(grid: list[list[int]]) -> float:
    """0~1：白底密集文字行（BOM/物料表截图，网格线不明显时也倾向文档）。"""
    h = len(grid)
    w = len(grid[0]) if h else 0
    if h < 8 or w < 8:
        return 0.0
    pixels = h * w
    white = sum(1 for r in range(h) for c in range(w) if grid[r][c] >= 228)
    white_ratio = white / pixels

    text_rows = 0
    for r in range(h):
        dark = sum(1 for c in range(w) if grid[r][c] <= 145) / w
        if 0.05 <= dark <= 0.42 and _row_edge_density(grid[r], threshold=28) >= 0.07:
            text_rows += 1

    text_row_ratio = text_rows / h
    top_band = max(1, h // 3)
    bot_start = max(top_band, h * 2 // 3)
    top_text = 0
    bot_text = 0
    for r in range(h):
        dark = sum(1 for c in range(w) if grid[r][c] <= 145) / w
        if 0.05 <= dark <= 0.42 and _row_edge_density(grid[r], threshold=28) >= 0.07:
            if r < top_band:
                top_text += 1
            elif r >= bot_start:
                bot_text += 1
    score = 0.0
    if white_ratio >= 0.40 and text_row_ratio >= 0.10:
        score += 0.40
    if text_rows >= max(8, int(h * 0.12)):
        score += 0.30
    if white_ratio >= 0.48 and text_row_ratio >= 0.18:
        score += 0.25
    if top_text < 2 or bot_text < 2:
        score *= 0.42
    body_score = _product_body_score(grid)
    if body_score >= 0.16:
        score = max(0.0, score - body_score * 0.85)
    return min(1.0, score)


def _product_body_score(grid: list[list[int]]) -> float:
    """0~1：中心区域存在较大非文字块（产品主体），表格密集文字则偏低。"""
    h = len(grid)
    w = len(grid[0]) if h else 0
    if h < 8 or w < 8:
        return 0.0
    y0, y1 = int(h * 0.18), int(h * 0.82)
    x0, x1 = int(w * 0.18), int(w * 0.82)
    center_vals = [grid[r][c] for r in range(y0, y1) for c in range(x0, x1)]
    if not center_vals:
        return 0.0
    center_mean = sum(center_vals) / len(center_vals)
    corner_vals = (
        [grid[r][c] for r in range(h) for c in range(w) if r < h // 5 or r >= h * 4 // 5 or c < w // 5 or c >= w * 4 // 5]
    )
    corner_mean = sum(corner_vals) / max(1, len(corner_vals))
    contrast = abs(center_mean - corner_mean)
    dark_center = sum(1 for v in center_vals if v <= 165) / len(center_vals)
    if contrast >= 18 and dark_center >= 0.12:
        blob_bonus = 0.18 if dark_center > 0.72 and contrast >= 35 else 0.0
        return min(1.0, contrast / 55.0 + min(dark_center, 0.72) * 0.35 + blob_bonus)
    return 0.0


def looks_like_table_grid_image(blob: bytes) -> bool:
    grid = _image_luma_grid(blob)
    if not grid:
        return False
    if _table_grid_score(grid) >= 0.40:
        return True
    return _text_dense_document_score(grid) >= 0.55


def classify_embedded_image_bytes(
    blob: bytes,
    *,
    source_path: str = "",
) -> str:
    """候选图类型：product_photo / bom_table / spec_table / unknown。"""
    label = str(source_path or "")
    if label and has_non_product_image_keywords(label):
        if re.search(r"bom|物料|清单|明细|material[\s_-]?list", label, re.I):
            return IMAGE_TYPE_BOM
        return IMAGE_TYPE_SPEC

    dims = _image_dimensions(blob)
    if not dims or not blob or len(blob) < 200:
        return IMAGE_TYPE_UNKNOWN
    w, h = dims

    if looks_like_document_screenshot(w, h):
        short, long = min(w, h), max(w, h)
        return IMAGE_TYPE_SPEC if long / max(short, 1) < 2.15 else IMAGE_TYPE_BOM

    grid = _image_luma_grid(blob)
    table_score = _table_grid_score(grid) if grid else 0.0
    text_doc_score = _text_dense_document_score(grid) if grid else 0.0
    body_score = _product_body_score(grid) if grid else 0.0

    if body_score >= 0.18 and table_score < 0.38 and text_doc_score < 0.48:
        if has_product_image_keywords(label) or body_score >= 0.20:
            return IMAGE_TYPE_PRODUCT

    if table_score >= 0.40:
        return IMAGE_TYPE_BOM
    if text_doc_score >= 0.42 and body_score < 0.14:
        return IMAGE_TYPE_BOM

    if not looks_like_bag_product_photo(w, h):
        return IMAGE_TYPE_UNKNOWN

    if has_product_image_keywords(label) and body_score >= 0.10 and text_doc_score < 0.35:
        return IMAGE_TYPE_PRODUCT
    if body_score >= 0.22 and table_score < 0.18 and text_doc_score < 0.28:
        return IMAGE_TYPE_PRODUCT
    if body_score >= 0.16 and table_score < 0.12 and text_doc_score < 0.22:
        return IMAGE_TYPE_PRODUCT
    if table_score >= 0.22 or (text_doc_score >= 0.32 and body_score < 0.12):
        return IMAGE_TYPE_BOM
    return IMAGE_TYPE_UNKNOWN


def looks_like_bag_product_photo(w: int, h: int) -> bool:
    """Excel 嵌入图几何特征：形似包款主图（非横条表格/说明截图）。"""
    if w <= 0 or h <= 0:
        return False
    if looks_like_document_screenshot(w, h):
        return False
    short, long = min(w, h), max(w, h)
    ratio = long / max(short, 1)
    if ratio > 2.75 or ratio < 0.42:
        return False
    area = w * h
    if area > 480_000 and ratio > 1.55:
        return False
    return True


def sheet_embed_product_style_annotation(
    blob: bytes,
    *,
    source_path: str = "",
) -> dict[str, Any] | None:
    """解析阶段：明显包图则标记为 product_style（供报价单信任来源使用）。"""
    if source_path and has_non_product_image_keywords(source_path):
        return None
    image_type = classify_embedded_image_bytes(blob, source_path=source_path)
    if image_type != IMAGE_TYPE_PRODUCT:
        return None
    if not is_acceptable_product_image_bytes(blob, source_path=source_path):
        return None
    dims = _image_dimensions(blob)
    if not dims:
        return None
    w, h = dims
    if not looks_like_bag_product_photo(w, h):
        return None
    return {
        "image_role": "product_style",
        "image_type": IMAGE_TYPE_PRODUCT,
        "product_image": True,
        "sheet_embed_product_detected": True,
    }


def annotate_sheet_embed_image_item(item: dict[str, Any]) -> dict[str, Any]:
    """为 Excel 嵌入图条目附加来源标记；形似包图时标记 product_style。"""
    row = dict(item)
    row.setdefault("from_sheet_embed", True)
    row.setdefault("image_source", "sheet_embed")
    blob = _decode_image_blob(row)
    source_path = str(row.get("source_path") or row.get("file_name") or "")
    image_type = classify_embedded_image_bytes(blob, source_path=source_path)
    row["image_type"] = image_type
    if image_type in (IMAGE_TYPE_BOM, IMAGE_TYPE_SPEC):
        row["product_image"] = False
        row["image_role"] = image_type
        return row
    ann = sheet_embed_product_style_annotation(blob, source_path=source_path)
    if ann:
        row.update(ann)
    else:
        row.setdefault("product_image", False)
    return row


def looks_like_document_screenshot(w: int, h: int) -> bool:
    """大尺寸表格/文字/说明类横条截图（即便比例不算极端也拒绝）。"""
    if w <= 0 or h <= 0:
        return False
    short, long = min(w, h), max(w, h)
    ratio = long / max(short, 1)
    area = w * h
    if long >= 680 and short <= 450 and ratio >= 1.55:
        return True
    if long >= 520 and short <= 300 and ratio >= 1.95:
        return True
    if area >= 280_000 and ratio >= 1.75:
        return True
    if long >= 900 and short <= 520:
        return True
    return False


def is_acceptable_product_image_bytes(
    blob: bytes,
    *,
    source_path: str = "",
) -> bool:
    if not blob or len(blob) < 200:
        return False
    path = str(source_path or "")
    if path and has_non_product_image_keywords(path):
        return False
    dims = _image_dimensions(blob)
    if not dims:
        return False
    w, h = dims
    if looks_like_document_screenshot(w, h):
        return False
    if looks_like_table_grid_image(blob):
        return False
    short, long = min(w, h), max(w, h)
    if short < _MIN_EDGE_PX:
        return False
    if w * h < _MIN_AREA_PX:
        return False
    if long / max(short, 1) > _MAX_ASPECT_RATIO:
        return False
    if long <= _TINY_MAX_EDGE and len(blob) <= _TINY_MAX_BYTES:
        return False
    return True


def _image_role(item: dict[str, Any]) -> str:
    return str(
        item.get("image_role")
        or item.get("image_source")
        or item.get("source_role")
        or ""
    ).strip().lower()


def is_trusted_quote_sheet_image_source(item: dict[str, Any]) -> bool:
    """来源是否允许进入报价单「款式图片」列（与像素校验解耦）。"""
    if not isinstance(item, dict):
        return False
    image_type = str(item.get("image_type") or "").strip().lower()
    if image_type in (IMAGE_TYPE_BOM, IMAGE_TYPE_SPEC):
        return False
    label_text = image_label_text(item)
    if has_non_product_image_keywords(label_text):
        return False
    if item.get("user_uploaded") or item.get("manual_style_image"):
        return True
    role = _image_role(item)
    if role in _REJECTED_IMAGE_ROLES:
        return False
    if role in TRUSTED_IMAGE_ROLES:
        return True
    if item.get("from_agent_product") and role in TRUSTED_IMAGE_ROLES:
        return True
    if item.get("product_image") is True:
        return True
    # Excel 嵌入：仅接受解析阶段已标记的包图/款式图
    if item.get("from_sheet_embed"):
        return bool(
            item.get("product_image")
            or item.get("sheet_embed_product_detected")
            or role in TRUSTED_IMAGE_ROLES
        )
    if role in _SHEET_EMBED_SOURCES:
        return False
    if item.get("sheet_row") is not None and not role:
        return False
    return False


def is_trusted_quote_sheet_image_item(item: dict[str, Any]) -> bool:
    if not is_trusted_quote_sheet_image_source(item):
        return False
    blob = _decode_image_blob(item)
    return is_acceptable_product_image_bytes(
        blob,
        source_path=str(item.get("source_path") or item.get("file_name") or ""),
    )


def product_image_score(item: dict[str, Any]) -> float:
    label_text = image_label_text(item)
    if has_non_product_image_keywords(label_text):
        return -1.0
    role = _image_role(item)
    if role in _REJECTED_IMAGE_ROLES:
        return -1.0
    image_type = str(item.get("image_type") or "").strip().lower()
    if image_type in (IMAGE_TYPE_BOM, IMAGE_TYPE_SPEC):
        return -1.0
    if image_type and image_type != IMAGE_TYPE_PRODUCT and not item.get("product_image"):
        if not is_trusted_quote_sheet_image_item(item):
            return -1.0
    if not is_trusted_quote_sheet_image_item(item):
        return -1.0
    blob = _decode_image_blob(item)
    dims = _image_dimensions(blob)
    if not dims:
        return -1.0
    w, h = dims
    if not looks_like_bag_product_photo(w, h):
        return -1.0
    if looks_like_table_grid_image(blob):
        return -1.0
    short, long = min(w, h), max(w, h)
    ratio_penalty = 0.85 if long / max(short, 1) > 2.2 else 1.0
    score = float(w * h) * ratio_penalty
    grid = _image_luma_grid(blob)
    if grid:
        body = _product_body_score(grid)
        score += body * 400_000.0
        score -= _table_grid_score(grid) * 600_000.0
    if has_product_image_keywords(label_text):
        score += 500_000.0
    return score


def filter_product_image_items(
    items: list[dict[str, Any]],
    *,
    rule_ctx: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """报价单可用产品图：明确来源 + 像素/文档截图校验。"""
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            from quote_correction_learning import evaluate_product_image_item

            trusted, hits = evaluate_product_image_item(item, rule_ctx or {})
            if hits:
                from dataclasses import asdict

                item = dict(item)
                item["_correction_rule_image_hits"] = [asdict(h) for h in hits]
            if not trusted:
                continue
        except Exception:
            if product_image_score(item) < 0:
                continue
        score = product_image_score(item)
        if score < 0:
            continue
        scored.append((score, item))
    scored.sort(key=lambda x: (-x[0], int(x[1].get("sheet_row", x[1].get("row_index")) or 0)))
    return [item for _, item in scored]


def is_acceptable_product_image_item(item: dict[str, Any]) -> bool:
    return is_trusted_quote_sheet_image_item(item)


def is_quote_sheet_display_image_url(url: str) -> bool:
    """已入选 URL：像素/文档截图/包款几何校验（不含用户手动上传豁免）。"""
    u = str(url or "").strip()
    if not u.startswith("data:"):
        return False
    blob = _decode_image_blob({"data_url": u})
    if not is_acceptable_product_image_bytes(blob):
        return False
    dims = _image_dimensions(blob)
    if not dims:
        return False
    return looks_like_bag_product_photo(dims[0], dims[1])


def is_acceptable_product_image_url(url: str) -> bool:
    return is_quote_sheet_display_image_url(url)


def filter_product_image_url_map(url_map: dict[int, str]) -> dict[int, str]:
    return {
        int(k): v
        for k, v in (url_map or {}).items()
        if v and is_quote_sheet_display_image_url(str(v))
    }


def _strip_internal_blocks(text: str) -> str:
    out = str(text or "")
    for marker in _INTERNAL_BLOCK_MARKERS:
        while marker in out:
            start = out.find(marker)
            if start < 0:
                break
            end = out.find("\n\n【", start + len(marker))
            if end < 0:
                end = len(out)
            else:
                next_block = out.find("【", start + 1)
                if next_block >= 0 and next_block < end:
                    end = next_block
            out = (out[:start] + out[end:]).strip()
    return out


def _is_internal_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if any(p.match(s) for p in _INTERNAL_LINE_PATTERNS):
        return True
    if re.match(r"^问题[一二三四五六七八九十\d]+描述", s, re.I):
        return True
    return False


def sanitize_quote_sheet_description(text: object, *, max_chars: int = 0) -> str:
    """客户报价单「描述」：去掉解析/问答/嵌入图说明等内部文案。"""
    raw = str(text or "").replace("\r\n", "\n").strip()
    if not raw:
        return ""
    raw = _strip_internal_blocks(raw)
    lines: list[str] = []
    for line in raw.split("\n"):
        s = line.strip()
        if not s:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if _is_internal_line(s):
            continue
        if s in {"-", "—", "null", "undefined", "NaN", "nan"}:
            continue
        lines.append(s)
    merged = "\n".join(lines).strip()
    while "\n\n\n" in merged:
        merged = merged.replace("\n\n\n", "\n\n")
    if max_chars > 0 and len(merged) > max_chars:
        merged = merged[: max_chars - 1].rstrip() + "…"
    return merged


def customer_description_for_quote_sheet(
    text: object,
    *,
    max_lines: int = _PDF_DESC_MAX_LINES,
    max_chars: int = _PDF_DESC_MAX_CHARS,
) -> str:
    """报价单/PDF 用可读摘要：先清洗，再按行数/字数友好截断并明示省略。"""
    cleaned = sanitize_quote_sheet_description(text, max_chars=0)
    if not cleaned:
        return ""
    lines = [ln for ln in cleaned.split("\n") if ln.strip()]
    if not lines:
        return ""

    truncated = False
    kept: list[str] = []
    char_count = 0
    for ln in lines:
        add_len = len(ln) + (1 if kept else 0)
        if max_chars > 0 and char_count + add_len > max_chars:
            truncated = True
            break
        if max_lines > 0 and len(kept) >= max_lines:
            truncated = True
            break
        kept.append(ln)
        char_count += add_len

    if truncated and _PDF_DESC_OMISSION not in kept:
        kept.append(_PDF_DESC_OMISSION)
    return "\n".join(kept)


_PDF_BRIEF_DESC_MAX_CHARS = 100
_MAX_MAIN_MATERIAL_ITEMS = 3
_MAX_LINING_ITEMS = 2

_MAIN_FABRIC_KEYS = (
    "主料",
    "外料",
    "面料",
    "牛津",
    "尼龙布",
    "尼龙格子",
    "格子布",
    "涤塔夫",
    "塔丝隆",
    "帆布",
    "无纺布",
    "DCF",
    "粗苯",
    "Ultra",
    "外布",
    "袋身主料",
    "围布",
    "涤纶",
    "尼龙",
    "网布",
    "网格",
    "PU",
    "PVC",
)

_LINING_KEYS = (
    "里布",
    "里料",
    "内里",
    "内衬",
)

_EXCLUDE_FABRIC_KEYS = (
    "里料",
    "里布",
    "拉链",
    "拉头",
    "织带",
    "绳带",
    "肩带",
    "扣具",
    "包装",
    "纸箱",
    "胶水",
    "印刷",
    "工艺",
    "费用",
    "加工",
)

_BANNED_BRIEF_DESC_RE = re.compile(
    r"裁片|系统估算|AI估算|系统推断|计算方式|内部推断|本地兜底|"
    r"问题[一二三四五六七八九十\d]+描述|背景指向|图片说明|工作簿嵌入|"
    r"前片|后片|底片|侧片|推断待核|推理待核|推断|待核",
    re.I,
)

_MAIN_MATERIAL_PENDING_CN = "主料待确认"

_ROLE_PREFIX_RE = re.compile(r"^(主料|外料|面料|袋身主料|外布)[：:\s\-/、]*", re.I)

_MAIN_MAT_LINE_RE = re.compile(
    r"(?:主体?面料|主料|外料|袋身主料)[：:\s]+(.+)",
    re.I,
)

_LINING_LINE_RE = re.compile(
    r"(?:里布|里料|内里|内衬)[：:\s]+(.+)",
    re.I,
)

_WIDTH_HINT_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:cm|CM|厘米|码|yd|YD))",
    re.I,
)


def _normalize_material_label(name: str, spec: str = "") -> str:
    raw = str(name or "").strip()
    if not raw or _BANNED_BRIEF_DESC_RE.search(raw):
        return ""
    if re.fullmatch(r"(主料|外料|面料|袋身主料)", raw):
        raw = str(spec or "").strip()
    raw = _ROLE_PREFIX_RE.sub("", raw).strip()
    if not raw or _BANNED_BRIEF_DESC_RE.search(raw):
        return ""
    for sep in ("；", ";", "，", ",", "（", "(", "/", "、"):
        if sep in raw:
            raw = raw.split(sep, 1)[0].strip()
    if len(raw) > 36:
        raw = raw[:35].rstrip() + "…"
    return raw


def _material_display_label(name: str, spec: str = "") -> str:
    mat = _normalize_material_label(name, spec)
    if not mat:
        return ""
    sp = str(spec or "").strip()
    if not sp or sp in ("-", "—") or _BANNED_BRIEF_DESC_RE.search(sp):
        return mat
    if sp == mat or sp in mat:
        return mat
    wm = _WIDTH_HINT_RE.search(sp)
    if wm and wm.group(1) not in mat and len(sp) <= 18:
        return f"{mat} {wm.group(1)}"
    if len(sp) <= 14 and not _BANNED_BRIEF_DESC_RE.search(sp):
        if any(k in sp for k in ("D", "d", "牛津", "尼龙", "涤纶", "帆布", "PU", "PVC")):
            return sp
    return mat


def _is_lining_row(name: str) -> bool:
    n = str(name or "").strip()
    if not n or _BANNED_BRIEF_DESC_RE.search(n):
        return False
    return any(k in n for k in _LINING_KEYS)


def _is_main_fabric_row(name: str) -> bool:
    n = str(name or "").strip()
    if not n or _BANNED_BRIEF_DESC_RE.search(n):
        return False
    if any(k in n for k in _EXCLUDE_FABRIC_KEYS):
        return False
    return any(k in n for k in _MAIN_FABRIC_KEYS)


def _dedupe_material_labels(labels: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in labels:
        label = str(raw or "").strip()
        if not label:
            continue
        key = re.sub(r"\s+", "", label.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def extract_materials_for_quote_sheet(
    detail_rows: list[dict[str, Any]] | None,
    structure_text: str = "",
) -> dict[str, list[str]]:
    """从物料行/结构短行提取主料与里布（多条、去重），不解析结构长文。"""
    mains: list[str] = []
    linings: list[str] = []
    if isinstance(detail_rows, list):
        for row in detail_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            spec = str(row.get("spec") or "").strip()
            if _is_lining_row(name):
                label = _material_display_label(name, spec)
                if label:
                    linings.append(label)
                continue
            if _is_main_fabric_row(name):
                label = _material_display_label(name, spec)
                if label:
                    mains.append(label)
    for line in str(structure_text or "").replace("\r\n", "\n").split("\n")[:12]:
        s = line.strip()
        if not s or _BANNED_BRIEF_DESC_RE.search(s) or len(s) > 80:
            continue
        for pattern, bucket in (
            (_LINING_LINE_RE, linings),
            (_MAIN_MAT_LINE_RE, mains),
        ):
            m = pattern.match(s)
            if not m:
                continue
            label = _normalize_material_label(m.group(1))
            if label:
                bucket.append(label)
    return {
        "main": _dedupe_material_labels(mains)[:_MAX_MAIN_MATERIAL_ITEMS],
        "lining": _dedupe_material_labels(linings)[:_MAX_LINING_ITEMS],
    }


def extract_main_material_for_quote_sheet(
    detail_rows: list[dict[str, Any]] | None,
    structure_text: str = "",
) -> str:
    """兼容旧调用：返回第一条主料。"""
    mats = extract_materials_for_quote_sheet(detail_rows, structure_text)
    return mats["main"][0] if mats["main"] else ""


def _strip_desc_punctuation(text: str) -> str:
    """客户描述列：去掉句末符号，保留正文冒号/顿号/分号。"""
    s = str(text or "").strip()
    while s and s[-1] in "。.!！?？;；,，":
        s = s[:-1].rstrip()
    return s


def _format_materials_desc(mats: dict[str, list[str]]) -> str:
    parts: list[str] = []
    if mats.get("main"):
        parts.append("主料：" + "、".join(mats["main"]))
    if mats.get("lining"):
        parts.append("里布：" + "、".join(mats["lining"]))
    if not parts:
        return ""
    return _strip_desc_punctuation("；".join(parts))


def brief_customer_description_for_quote_sheet(
    *,
    product_name: str = "",
    detail_rows: list[dict[str, Any]] | None = None,
    structure_text: str = "",
) -> str:
    """客户报价单描述：仅主料（名称列已含包型）；禁止结构长文/裁片/系统估算。"""
    del product_name
    mats = extract_materials_for_quote_sheet(detail_rows, structure_text)
    desc = _format_materials_desc(mats)
    if not desc:
        desc = _MAIN_MATERIAL_PENDING_CN
    if _BANNED_BRIEF_DESC_RE.search(desc):
        desc = _MAIN_MATERIAL_PENDING_CN
    desc = _strip_desc_punctuation(desc)
    if len(desc) > _PDF_BRIEF_DESC_MAX_CHARS:
        desc = desc[: _PDF_BRIEF_DESC_MAX_CHARS - 1].rstrip() + "…"
    return desc


def minimal_png_bytes(width: int = 120, height: int = 120) -> bytes:
    """生成最小合法 RGB PNG（测试与夹具用）。"""
    return _rgb_png_from_pixel_fn(width, height, lambda _x, _y: (200, 210, 220))


def _rgb_png_from_pixel_fn(
    width: int,
    height: int,
    pixel_fn,
) -> bytes:
    import struct
    import zlib

    w = max(8, int(width))
    h = max(8, int(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw_rows: list[bytes] = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            r, g, b = pixel_fn(x, y)
            row.extend((int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF))
        raw_rows.append(bytes(row))
    raw = b"".join(raw_rows)
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def table_screenshot_png_bytes(
    width: int = 320,
    height: int = 240,
    *,
    rows: int = 14,
    cols: int = 10,
) -> bytes:
    """生成带网格线与单元格文字块的表格型 PNG（测试 BOM 表截图过滤）。"""

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        row_h = max(1, height // max(1, rows))
        col_w = max(1, width // max(1, cols))
        if y % row_h == 0 or x % col_w == 0:
            return (45, 45, 45)
        cell_x, cell_y = x // col_w, y // row_h
        if (cell_x + cell_y) % 2 == 0 and (x % col_w > 5 and y % row_h > 7):
            if (x + y * 3) % 11 < 3:
                return (25, 25, 25)
        return (255, 255, 255)

    return _rgb_png_from_pixel_fn(width, height, pixel)


def dense_text_bom_png_bytes(width: int = 200, height: int = 220) -> bytes:
    """白底多行文字块、无清晰网格线（测试 BOM 物料表误判为包图）。"""

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        line_h = max(8, height // 18)
        band = y % line_h
        if band < max(2, line_h // 4) and (x * 5 + y * 3) % 13 < 4:
            return (35, 35, 35)
        return (255, 255, 255)

    return _rgb_png_from_pixel_fn(width, height, pixel)


def product_like_png_bytes(width: int = 160, height: int = 200) -> bytes:
    """生成白底 + 中心产品色块的 PNG（测试包款实物图优先）。"""

    cx, cy = width / 2.0, height / 2.0

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        dx = (x - cx) / max(1.0, width * 0.30)
        dy = (y - cy) / max(1.0, height * 0.36)
        if dx * dx + dy * dy < 1.0:
            return (72, 108, 148)
        return (248, 248, 248)

    return _rgb_png_from_pixel_fn(width, height, pixel)
