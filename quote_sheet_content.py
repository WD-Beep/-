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
    r"工艺|尺寸表|说明图|文字)",
    re.I,
)

_NON_PRODUCT_IMAGE_KEYWORDS = re.compile(
    r"(packag(?:e|ing)?|包装|label|标签|吊牌|hang[\s_-]?tag|material|材料|"
    r"size[\s_-]?chart|尺寸|dimension|spec[\s_-]?chart|chart|图表|"
    r"payment|pay(?:ment)?|付款|bank|银行|account|账号|收款|"
    r"receipt|小票|invoice|发票|ticket|票据|"
    r"barcode|条码|说明图|工艺|文字图|截图|screenshot|capture|"
    r"qrcode|qr[\s_-]?code|二维码|other|杂项)",
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
        "product_image": True,
        "sheet_embed_product_detected": True,
    }


def annotate_sheet_embed_image_item(item: dict[str, Any]) -> dict[str, Any]:
    """为 Excel 嵌入图条目附加来源标记；形似包图时标记 product_style。"""
    row = dict(item)
    row.setdefault("from_sheet_embed", True)
    row.setdefault("image_source", "sheet_embed")
    blob = _decode_image_blob(row)
    ann = sheet_embed_product_style_annotation(
        blob,
        source_path=str(row.get("source_path") or row.get("file_name") or ""),
    )
    if ann:
        row.update(ann)
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
    if not is_trusted_quote_sheet_image_item(item):
        return -1.0
    blob = _decode_image_blob(item)
    dims = _image_dimensions(blob)
    if not dims:
        return -1.0
    w, h = dims
    if not looks_like_bag_product_photo(w, h):
        return -1.0
    short, long = min(w, h), max(w, h)
    ratio_penalty = 0.85 if long / max(short, 1) > 2.2 else 1.0
    score = float(w * h) * ratio_penalty
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
    import struct
    import zlib

    w = max(8, int(width))
    h = max(8, int(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    row = b"\x00" + (b"\xc8\xd0\xe0" * w)
    raw = row * h
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
