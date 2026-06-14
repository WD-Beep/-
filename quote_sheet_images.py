"""报价单产品图：从 Excel 嵌入图提取、落盘与映射到产品明细行。"""

from __future__ import annotations

import base64
import io
import json
import posixpath
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from quote_sheet_content import (
    IMAGE_TYPE_PRODUCT,
    annotate_sheet_embed_image_item,
    filter_product_image_items,
    filter_product_image_url_map,
    is_acceptable_product_image_bytes,
    is_quote_sheet_display_image_url,
    product_image_score,
)
from xlsx_rich_context import _mime_for_media_path, list_embedded_images_from_xlsx_bytes

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PRODUCT_IMAGES_ROOT = DATA_DIR / "quote_product_images"

_ROLE_SALES = "sales_sheet"
_ROLE_ADMIN = "admin_corrected"
_ROLE_ADMIN_CALCULATED = "admin_calculated"
_MAX_IMAGE_BYTES = 600_000
_MAX_IMAGES = 10


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _drawing_rels_rid_to_media(archive: zipfile.ZipFile, drawing_path: str) -> dict[str, str]:
    rel_path = posixpath.join(
        posixpath.dirname(drawing_path),
        "_rels",
        posixpath.basename(drawing_path) + ".rels",
    )
    if rel_path not in archive.namelist():
        return {}
    try:
        root = ET.fromstring(archive.read(rel_path))
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}
    for node in root.iter():
        if _local_tag(node.tag) != "Relationship":
            continue
        rid = (node.attrib.get("Id") or "").strip()
        tgt = (node.attrib.get("Target") or "").strip().replace("\\", "/")
        if rid and tgt:
            out[rid] = tgt
    return out


def _anchor_row_rid_extent(anchor_elem: ET.Element) -> tuple[int | None, str | None, float | None]:
    row_ix: int | None = None
    embed_rid: str | None = None
    aspect: float | None = None
    for child in anchor_elem.iter():
        tag = _local_tag(child.tag)
        if tag == "from":
            for sub in child:
                if _local_tag(sub.tag) == "row":
                    try:
                        row_ix = int((sub.text or "0").strip())
                    except ValueError:
                        row_ix = 0
        if tag == "ext":
            try:
                cx = float(child.attrib.get("cx") or 0)
                cy = float(child.attrib.get("cy") or 0)
            except (TypeError, ValueError):
                cx, cy = 0.0, 0.0
            if cy > 0 and cx > 0:
                aspect = cx / cy
        if tag == "blip":
            for k, v in child.attrib.items():
                if k.endswith("}embed") or k == "embed":
                    embed_rid = str(v).strip() or None
    return row_ix, embed_rid, aspect


def _anchor_extent_ok(aspect: float | None) -> bool:
    if aspect is None:
        return True
    if aspect > 4.5 or aspect < 0.22:
        return False
    return True


def _finalize_sheet_embed_candidates(
    raw: list[tuple[int, str, bytes]],
) -> list[dict[str, Any]]:
    """全部候选图先标注类型，再筛 product_photo 并按得分排序。"""
    annotated: list[dict[str, Any]] = []
    for row_ix, path, blob in raw:
        mime = _mime_for_media_path(path)
        if mime == "application/octet-stream":
            continue
        item = annotate_sheet_embed_image_item(
            {
                "row_index": row_ix,
                "sheet_row": row_ix,
                "mime_type": mime,
                "data_base64": base64.b64encode(blob).decode("ascii"),
                "source_path": path,
            }
        )
        annotated.append(item)

    product_items = [
        item
        for item in annotated
        if item.get("image_type") == IMAGE_TYPE_PRODUCT or item.get("product_image") is True
    ]
    product_items = filter_product_image_items(product_items)
    product_items.sort(
        key=lambda x: (
            -product_image_score(x),
            int(x.get("sheet_row", x.get("row_index")) or 0),
        )
    )
    return product_items[:_MAX_IMAGES]


def extract_embedded_images_with_rows_from_xlsx_bytes(
    file_bytes: bytes,
) -> list[dict[str, Any]]:
    """从 xlsx 提取嵌入图；row_index 为工作表锚点行号（0-based）。"""
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        return []

    picked: list[tuple[int, str, bytes]] = []
    drawing_paths = sorted(
        n for n in archive.namelist() if n.startswith("xl/drawings/drawing") and n.endswith(".xml")
    )
    for drawing_path in drawing_paths:
        rel_map = _drawing_rels_rid_to_media(archive, drawing_path)
        if not rel_map:
            continue
        try:
            root = ET.fromstring(archive.read(drawing_path))
        except ET.ParseError:
            continue
        for elem in root.iter():
            tag = _local_tag(elem.tag)
            if tag not in ("twoCellAnchor", "oneCellAnchor", "absoluteAnchor"):
                continue
            row_ix, rid, aspect = _anchor_row_rid_extent(elem)
            if not rid or rid not in rel_map:
                continue
            if not _anchor_extent_ok(aspect):
                continue
            media_rel = rel_map[rid].lstrip("/")
            if media_rel.startswith("../"):
                media_rel = media_rel[3:]
            if not media_rel.startswith("xl/"):
                media_rel = posixpath.normpath(posixpath.join("xl", media_rel))
            if media_rel not in archive.namelist():
                alt = "xl/" + media_rel.split("xl/", 1)[-1] if "xl/" in media_rel else media_rel
                if alt in archive.namelist():
                    media_rel = alt
                else:
                    continue
            try:
                blob = archive.read(media_rel)
            except KeyError:
                continue
            if not blob or len(blob) > _MAX_IMAGE_BYTES:
                continue
            sheet_row = row_ix if row_ix is not None else len(picked)
            picked.append((sheet_row, media_rel, blob))

    if picked:
        seen: set[tuple[int, str]] = set()
        uniq: list[tuple[int, str, bytes]] = []
        for row_ix, path, blob in sorted(picked, key=lambda x: (x[0], x[1].lower())):
            key = (row_ix, path)
            if key in seen:
                continue
            seen.add(key)
            uniq.append((row_ix, path, blob))
        return _finalize_sheet_embed_candidates(uniq)

    fallback = list_embedded_images_from_xlsx_bytes(file_bytes)
    raw_fallback: list[tuple[int, str, bytes]] = []
    for seq, (path, blob) in enumerate(fallback[: _MAX_IMAGES * 3]):
        if len(blob) > _MAX_IMAGE_BYTES:
            continue
        raw_fallback.append((seq, path, blob))
    return _finalize_sheet_embed_candidates(raw_fallback)


def _manifest_path(quote_uid: str, role: str) -> Path:
    safe_uid = re.sub(r"[^\w\-]", "_", str(quote_uid or "").strip())[:120]
    safe_role = re.sub(r"[^\w\-]", "_", str(role or "").strip())[:40]
    return PRODUCT_IMAGES_ROOT / safe_uid / f"{safe_role}.json"


def _image_file_path(quote_uid: str, role: str, sheet_row: int, ext: str) -> Path:
    safe_uid = re.sub(r"[^\w\-]", "_", str(quote_uid or "").strip())[:120]
    safe_role = re.sub(r"[^\w\-]", "_", str(role or "").strip())[:40]
    return PRODUCT_IMAGES_ROOT / safe_uid / safe_role / f"row_{int(sheet_row)}{ext}"


def persist_sheet_product_images(
    quote_uid: str,
    role: str,
    file_bytes: bytes,
    *,
    original_name: str = "",
) -> list[dict[str, Any]]:
    """解析 xlsx 嵌入图并落盘；row_index 保留工作表锚点行号。"""
    q_uid = str(quote_uid or "").strip()
    r = str(role or _ROLE_SALES).strip() or _ROLE_SALES
    if not q_uid or not file_bytes:
        return []
    suffix = Path(str(original_name or "")).suffix.lower()
    if suffix not in (".xlsx",):
        return []

    extracted = extract_embedded_images_with_rows_from_xlsx_bytes(file_bytes)
    if not extracted:
        return []

    entries: list[dict[str, Any]] = []
    for item in extracted:
        sheet_row = int(item.get("sheet_row", item.get("row_index")) or 0)
        mime = str(item.get("mime_type") or "image/png")
        b64 = str(item.get("data_base64") or "").strip()
        if not b64:
            continue
        try:
            blob = base64.b64decode(b64, validate=True)
        except Exception:
            continue
        ext = ".png" if "png" in mime else ".jpg" if "jpeg" in mime or mime.endswith("jpg") else ".webp"
        dest = _image_file_path(q_uid, r, sheet_row, ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        data_url = f"data:{mime};base64,{b64}"
        entry = annotate_sheet_embed_image_item(
            {
                "row_index": sheet_row,
                "sheet_row": sheet_row,
                "mime_type": mime,
                "file_name": dest.name,
                "data_url": data_url,
                "data_base64": b64,
                "source_path": str(item.get("source_path") or ""),
            }
        )
        entries.append(entry)

    manifest = {
        "quote_uid": q_uid,
        "role": r,
        "updated_at": _utc_now_iso(),
        "images": [{k: v for k, v in e.items() if k != "data_url"} for e in entries],
    }
    mp = _manifest_path(q_uid, r)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return entries


def load_sheet_product_images(quote_uid: str, role: str) -> list[dict[str, Any]]:
    q_uid = str(quote_uid or "").strip()
    r = str(role or "").strip()
    if not q_uid or not r:
        return []
    mp = _manifest_path(q_uid, r)
    if not mp.is_file():
        return []
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[dict[str, Any]] = []
    for item in manifest.get("images") or []:
        if not isinstance(item, dict):
            continue
        sheet_row = int(item.get("sheet_row", item.get("row_index")) or 0)
        mime = str(item.get("mime_type") or "image/png")
        fname = str(item.get("file_name") or "").strip()
        ext = Path(fname).suffix if fname else ".png"
        dest = _image_file_path(q_uid, r, sheet_row, ext)
        if not dest.is_file() and fname:
            legacy = dest.parent / fname
            if legacy.is_file():
                dest = legacy
        if not dest.is_file():
            continue
        try:
            blob = dest.read_bytes()
        except OSError:
            continue
        if len(blob) > _MAX_IMAGE_BYTES:
            continue
        b64 = base64.b64encode(blob).decode("ascii")
        row_meta = {
            "row_index": sheet_row,
            "sheet_row": sheet_row,
            "mime_type": mime,
            "data_url": f"data:{mime};base64,{b64}",
            "data_base64": b64,
            "file_name": fname or dest.name,
            "source_path": str(item.get("source_path") or ""),
            "from_sheet_embed": bool(item.get("from_sheet_embed", True)),
        }
        for key in (
            "image_role",
            "product_image",
            "sheet_embed_product_detected",
            "image_source",
            "image_type",
        ):
            if item.get(key) is not None:
                row_meta[key] = item[key]
        annotated = annotate_sheet_embed_image_item(row_meta)
        if annotated.get("image_type") not in (None, IMAGE_TYPE_PRODUCT) and not annotated.get(
            "product_image"
        ):
            continue
        if not filter_product_image_items([annotated]):
            continue
        out.append(annotated)
    return sorted(out, key=lambda x: int(x.get("sheet_row", x.get("row_index")) or 0))


def _data_url_from_image_item(item: dict[str, Any]) -> str:
    url = str(item.get("data_url") or "").strip()
    if url.startswith("data:"):
        return url
    b64 = str(item.get("data_base64") or "").strip()
    if not b64:
        return ""
    mime = str(item.get("mime_type") or "image/png")
    return f"data:{mime};base64,{b64}"


def images_by_sheet_row(images: list[dict[str, Any]]) -> dict[int, str]:
    """表格嵌入图：键为工作表锚点行号；同行多图取面积最大且通过产品图筛选的一张。"""
    by_row: dict[int, list[dict[str, Any]]] = {}
    for item in filter_product_image_items(images or []):
        key = int(item.get("sheet_row", item.get("row_index")) or 0)
        by_row.setdefault(key, []).append(item)
    out: dict[int, str] = {}
    for key, items in by_row.items():
        from quote_sheet_content import product_image_score

        best_item = max(items, key=product_image_score)
        url = _data_url_from_image_item(best_item)
        if url:
            out[key] = url
    return out


def normalize_sheet_images_to_product_map(
    sheet_images: list[dict[str, Any]],
    product_count: int,
    *,
    product_source_rows: list[int | None] | None = None,
) -> dict[int, str]:
    """将表格锚点行号映射到产品明细行索引 0..product_count-1。"""
    pc = max(1, min(int(product_count or 1), _MAX_IMAGES))
    by_sheet = images_by_sheet_row(sheet_images)
    if not by_sheet:
        return {}

    sources: list[int | None] = list(product_source_rows or [])
    while len(sources) < pc:
        sources.append(None)

    result: dict[int, str] = {}
    used_sheet_rows: set[int] = set()

    for prod_ix in range(pc):
        src_row = sources[prod_ix]
        if src_row is None:
            continue
        if src_row in by_sheet and src_row not in used_sheet_rows:
            result[prod_ix] = by_sheet[src_row]
            used_sheet_rows.add(src_row)

    remaining = sorted(
        (sheet_row, url) for sheet_row, url in by_sheet.items() if sheet_row not in used_sheet_rows
    )
    unfilled = [i for i in range(pc) if i not in result]
    for prod_ix, (sheet_row, url) in zip(unfilled, remaining):
        result[prod_ix] = url
        used_sheet_rows.add(sheet_row)

    if pc == 1 and 0 not in result and remaining:
        result[0] = remaining[0][1]

    return result


def _merge_marked_sheet_embeds_into(
    merged: dict[int, str],
    images: list[dict[str, Any]] | None,
    product_count: int,
    *,
    product_source_rows: list[int | None] | None = None,
    overwrite: bool = False,
) -> None:
    """合并解析阶段已标记为 product_style 的 Excel 嵌入图。"""
    trusted = filter_product_image_items(images or [])
    if not trusted:
        return
    norm = normalize_sheet_images_to_product_map(
        trusted,
        product_count,
        product_source_rows=product_source_rows,
    )
    for prod_ix, url in norm.items():
        if not is_quote_sheet_display_image_url(url):
            continue
        if overwrite or prod_ix not in merged:
            merged[prod_ix] = url


def merge_product_images_by_priority(
    *,
    admin_images: list[dict[str, Any]] | None = None,
    quote_images: list[dict[str, Any]] | None = None,
    admin_calculated_images: list[dict[str, Any]] | None = None,
    sales_images: list[dict[str, Any]] | None = None,
    product_count: int = 1,
    product_source_rows: list[int | None] | None = None,
) -> dict[int, str]:
    """
    报价单款式图：Agent/人工图优先；Excel 仅采用解析阶段标记为 product_style 的包图。
    未标记的匿名嵌入图（表格截图等）不进入报价单。
    """
    pc = max(1, min(int(product_count or 1), _MAX_IMAGES))
    merged: dict[int, str] = {}
    rows = product_source_rows

    _merge_marked_sheet_embeds_into(merged, sales_images, pc, product_source_rows=rows)
    _merge_marked_sheet_embeds_into(
        merged, admin_calculated_images, pc, product_source_rows=rows, overwrite=True
    )
    _merge_marked_sheet_embeds_into(
        merged, admin_images, pc, product_source_rows=rows, overwrite=True
    )

    for item in filter_product_image_items(quote_images or []):
        url = str(item.get("data_url") or item.get("image_url") or "").strip()
        if not url.startswith("data:"):
            continue
        prod_ix = int(item.get("product_line", item.get("line_order", item.get("row_index"))) or 0)
        if 0 <= prod_ix < pc and is_quote_sheet_display_image_url(url):
            merged[prod_ix] = url

    return filter_product_image_url_map(merged)
