from __future__ import annotations

import base64
import io
import re
import zipfile
from typing import Any
from xml.etree import ElementTree


def enrich_items_with_sheet_media_hints(
    uploaded_sheet: dict[str, Any],
    sheet_name: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Add non-invasive hints from xlsx hyperlinks/images into item calc_note.

    Backward-compatible behavior:
    - If row-level anchor is unavailable, falls back to workbook-level summary.
    - Return schema remains unchanged.
    """
    if not isinstance(uploaded_sheet, dict) or not isinstance(items, list) or not items:
        return {"links": 0, "image_anchors": 0, "applied": 0}
    file_name = str(uploaded_sheet.get("name") or "").strip().lower()
    if not file_name.endswith(".xlsx"):
        return {"links": 0, "image_anchors": 0, "applied": 0}
    raw = str(uploaded_sheet.get("content_base64") or "").strip()
    if not raw:
        return {"links": 0, "image_anchors": 0, "applied": 0}
    try:
        file_bytes = base64.b64decode(raw, validate=True)
    except Exception:
        return {"links": 0, "image_anchors": 0, "applied": 0}

    link_rows, image_rows = _extract_sheet_media_hints(file_bytes, sheet_name)
    if not link_rows and not image_rows:
        return {"links": 0, "image_anchors": 0, "applied": 0}

    global_links = [u for _, u in link_rows]
    global_summary = _build_media_summary(global_links, len(image_rows))
    if not global_summary and not link_rows and not image_rows:
        return {"links": len(global_links), "image_anchors": len(image_rows), "applied": 0}

    applied = 0
    for row in items:
        if not isinstance(row, dict):
            continue
        src_row = _to_int(row.get("source_row"))
        row_summary = _build_row_media_summary(src_row, link_rows, image_rows)
        summary = row_summary or global_summary
        if not summary:
            continue
        existing = str(row.get("calc_note") or "").strip()
        if summary in existing:
            continue
        row["calc_note"] = f"{existing}；{summary}" if existing else summary
        applied += 1
    return {"links": len(global_links), "image_anchors": len(image_rows), "applied": applied}


def _build_media_summary(link_hints: list[str], image_count: int) -> str:
    parts: list[str] = []
    if link_hints:
        shown = "；".join(link_hints[:2])
        parts.append(f"表格含链接线索：{shown}")
    if image_count > 0:
        parts.append(f"表格含图片锚点共{image_count}处，可结合图片款式确认规格与工艺后复核成本")
    return "；".join(parts)


def _extract_sheet_media_hints(
    file_bytes: bytes, preferred_sheet: str
) -> tuple[list[tuple[int, str]], set[int]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        return [], set()
    sheets = _read_sheet_entries(archive)
    if not sheets:
        return [], set()
    sheet = _pick_sheet(sheets, preferred_sheet)
    if sheet is None:
        return [], set()
    sheet_path, sheet_xml = sheet
    links = _read_hyperlinks(archive, sheet_path, sheet_xml)
    image_rows = _read_image_anchor_rows(archive, sheet_path, sheet_xml)
    return links, image_rows


def _pick_sheet(
    sheets: list[tuple[str, str, bytes]],
    preferred_sheet: str,
) -> tuple[str, bytes] | None:
    target = preferred_sheet.strip().lower()
    if target:
        for name, path, xml in sheets:
            if name.strip().lower() == target:
                return path, xml
    if sheets:
        _, path, xml = sheets[0]
        return path, xml
    return None


def _read_sheet_entries(archive: zipfile.ZipFile) -> list[tuple[str, str, bytes]]:
    workbook_path = "xl/workbook.xml"
    rels_path = "xl/_rels/workbook.xml.rels"
    if workbook_path not in archive.namelist() or rels_path not in archive.namelist():
        return []
    wb_root = ElementTree.fromstring(archive.read(workbook_path))
    rel_root = ElementTree.fromstring(archive.read(rels_path))
    wb_ns = _nsmap(wb_root)
    rel_ns = _nsmap(rel_root)
    rel_idx: dict[str, str] = {}
    for node in rel_root.findall(".//rel:Relationship", rel_ns):
        rel_id = node.attrib.get("Id", "")
        target = node.attrib.get("Target", "").lstrip("/")
        if rel_id and target:
            rel_idx[rel_id] = f"xl/{target}" if not target.startswith("xl/") else target
    out: list[tuple[str, str, bytes]] = []
    for sheet in wb_root.findall(".//main:sheets/main:sheet", wb_ns):
        name = sheet.attrib.get("name", "").strip() or "Sheet"
        rel_id = (
            sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            or sheet.attrib.get("r:id")
            or ""
        )
        path = rel_idx.get(rel_id, "")
        if path and path in archive.namelist():
            out.append((name, path, archive.read(path)))
    return out


def _read_hyperlinks(
    archive: zipfile.ZipFile, sheet_path: str, sheet_xml: bytes
) -> list[tuple[int, str]]:
    root = ElementTree.fromstring(sheet_xml)
    ns = _nsmap(root)
    rel_path = _sheet_rels_path(sheet_path)
    rel_map: dict[str, str] = {}
    if rel_path in archive.namelist():
        rel_root = ElementTree.fromstring(archive.read(rel_path))
        rel_ns = _nsmap(rel_root)
        for rel in rel_root.findall(".//rel:Relationship", rel_ns):
            rel_id = rel.attrib.get("Id", "")
            target = rel.attrib.get("Target", "")
            if rel_id and target:
                rel_map[rel_id] = target
    links: list[tuple[int, str]] = []
    for node in root.findall(".//main:hyperlinks/main:hyperlink", ns):
        rid = (
            node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            or node.attrib.get("r:id")
            or ""
        )
        url = rel_map.get(rid, "").strip()
        if _is_url(url):
            row_no = _row_from_a1_ref(str(node.attrib.get("ref", "")).strip())
            links.append((row_no, url))
    uniq: list[tuple[int, str]] = []
    seen = set()
    for row_no, url in links:
        key = (row_no, url)
        if key not in seen:
            seen.add(key)
            uniq.append(key)
    return [(r, _normalize_link_hint(u)) for r, u in uniq[:20]]


def _read_image_anchor_rows(archive: zipfile.ZipFile, sheet_path: str, sheet_xml: bytes) -> set[int]:
    root = ElementTree.fromstring(sheet_xml)
    ns = _nsmap(root)
    rel_path = _sheet_rels_path(sheet_path)
    if rel_path not in archive.namelist():
        return set()
    rel_root = ElementTree.fromstring(archive.read(rel_path))
    rel_ns = _nsmap(rel_root)
    drawing_targets: list[str] = []
    for rel in rel_root.findall(".//rel:Relationship", rel_ns):
        typ = rel.attrib.get("Type", "")
        if typ.endswith("/drawing"):
            target = rel.attrib.get("Target", "").lstrip("/")
            drawing_targets.append(target if target.startswith("xl/") else f"xl/{target}")
    image_rows: set[int] = set()
    for dpath in drawing_targets:
        if dpath not in archive.namelist():
            continue
        droot = ElementTree.fromstring(archive.read(dpath))
        dns = _nsmap(droot)
        for anchor in droot.findall(".//main:twoCellAnchor", dns) + droot.findall(".//main:oneCellAnchor", dns):
            frm = anchor.find("main:from", dns)
            if frm is None:
                continue
            row_node = frm.find("main:row", dns)
            if row_node is None:
                continue
            try:
                image_rows.add(int(row_node.text or "0") + 1)
            except ValueError:
                continue
    return image_rows


def _sheet_rels_path(sheet_path: str) -> str:
    return re.sub(r"(?i)^xl/worksheets/(.+)\.xml$", r"xl/worksheets/_rels/\1.xml.rels", sheet_path)


def _normalize_link_hint(url: str) -> str:
    short = url.strip()
    if len(short) > 80:
        short = short[:77] + "..."
    return short


def _is_url(value: str) -> bool:
    text = (value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _row_from_a1_ref(ref: str) -> int:
    m = re.search(r"(\d+)", str(ref or ""))
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _build_row_media_summary(
    source_row: int,
    link_rows: list[tuple[int, str]],
    image_rows: set[int],
) -> str:
    if source_row <= 0:
        return ""
    near_links: list[str] = []
    for row_no, url in link_rows:
        if row_no <= 0:
            continue
        if abs(row_no - source_row) <= 3 and url not in near_links:
            near_links.append(url)
    image_near = any(abs(int(r) - source_row) <= 2 for r in image_rows)
    if not near_links and not image_near:
        return ""
    parts: list[str] = []
    if near_links:
        parts.append(f"结构参考链接：{'；'.join(near_links[:2])}")
    if image_near:
        parts.append("本行附近含结构图片锚点，可按图复核裁片与工艺拆分")
    return "；".join(parts)


def _nsmap(root: ElementTree.Element) -> dict[str, str]:
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[1 : root.tag.index("}")]
    return {
        "main": namespace,
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
