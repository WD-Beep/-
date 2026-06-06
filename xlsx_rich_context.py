"""Extract hyperlinks & embedded images from .xlsx for richer structure context.

Links are appended as plain text for the LLM.
可选：`QUOTE_FETCH_HYPERLINKS=1` 时由 hyperlink_fetch 拉取外链正文摘要并入（默认关闭）。
Images get optional vision payloads (mime + base64) when enabled downstream.
"""

from __future__ import annotations

import base64
import io
import os
import posixpath
import zipfile
from dataclasses import dataclass
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from hyperlink_fetch import format_fetched_hyperlink_excerpts
from sheet_parser import SheetParseError, read_sheet_paths_entries


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _rid_from_hyperlink_attrib(attrib: dict[str, str]) -> str | None:
    for k, v in attrib.items():
        if k.endswith("}id") or k == "r:id":
            return str(v).strip() or None
    return None


@dataclass(frozen=True)
class SheetHyperlink:
    sheet_name: str
    cell_ref: str
    target: str
    display: str


_HYPERLINK_REL_MARKER = "hyperlink"


def extract_hyperlinks_from_xlsx_bytes(file_bytes: bytes) -> list[SheetHyperlink]:
    """Parse OOXML hyperlink relationships from every worksheet."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise SheetParseError("Invalid XLSX file format.") from exc

    try:
        triples = read_sheet_paths_entries(archive)
    except SheetParseError:
        return []

    out: list[SheetHyperlink] = []
    for sheet_name, sheet_path, sheet_xml in triples:
        rel_path = posixpath.join(posixpath.dirname(sheet_path), "_rels", posixpath.basename(sheet_path) + ".rels")
        rid_target: dict[str, tuple[str, str]] = {}
        if rel_path in archive.namelist():
            try:
                rel_root = ET.fromstring(archive.read(rel_path))
            except ET.ParseError:
                rel_root = None
            if rel_root is not None:
                for node in rel_root.iter():
                    if _local_tag(node.tag) != "Relationship":
                        continue
                    rid = (node.attrib.get("Id") or "").strip()
                    typ = (node.attrib.get("Type") or "").strip().lower()
                    tgt_raw = (node.attrib.get("Target") or "").strip()
                    mode = (node.attrib.get("TargetMode") or "").strip()
                    if not rid or not tgt_raw:
                        continue
                    if _HYPERLINK_REL_MARKER not in typ:
                        continue
                    tgt = unquote(tgt_raw.replace("\\", "/"))
                    rid_target[rid] = (tgt, mode)

        try:
            root = ET.fromstring(sheet_xml)
        except ET.ParseError:
            continue

        for elem in root.iter():
            if _local_tag(elem.tag) != "hyperlinks":
                continue
            for child in elem:
                if _local_tag(child.tag) != "hyperlink":
                    continue
                ref = (child.attrib.get("ref") or "").strip().upper()
                if not ref:
                    continue
                rid = _rid_from_hyperlink_attrib(dict(child.attrib))
                display = (child.attrib.get("display") or "").strip()
                if not rid or rid not in rid_target:
                    continue
                tgt, mode = rid_target[rid]
                tgt_clean = tgt.strip()
                if not tgt_clean:
                    continue
                # Skip pure internal workbook jumps unless fragment-only location
                if tgt_clean.startswith("#"):
                    url = f"(工作簿内跳转){tgt_clean}"
                elif tgt_clean.lower().startswith(("http://", "https://")):
                    url = tgt_clean
                elif tgt_clean.lower().startswith("mailto:"):
                    url = tgt_clean
                else:
                    # Relative external targets occasionally stored without scheme
                    if mode.lower() == "external" and tgt_clean.startswith("/"):
                        url = tgt_clean
                    else:
                        url = tgt_clean

                out.append(SheetHyperlink(sheet_name=sheet_name, cell_ref=ref, target=url, display=display))

    # Dedupe same sheet+cell+target
    seen: set[tuple[str, str, str]] = set()
    uniq: list[SheetHyperlink] = []
    for h in out:
        key = (h.sheet_name, h.cell_ref, h.target)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    return uniq


def list_embedded_images_from_xlsx_bytes(file_bytes: bytes) -> list[tuple[str, bytes]]:
    """Return [(member_path_lower_for_suffix, raw_bytes), ...] under xl/media/."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        return []

    rows: list[tuple[str, bytes]] = []
    for name in archive.namelist():
        if not name.startswith("xl/media/") or name.endswith("/"):
            continue
        low = name.lower()
        if not low.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            continue
        try:
            blob = archive.read(name)
        except KeyError:
            continue
        if not blob:
            continue
        rows.append((name, blob))
    rows.sort(key=lambda x: x[0].lower())
    return rows


def _mime_for_media_path(path: str) -> str:
    low = path.lower()
    if low.endswith(".png"):
        return "image/png"
    if low.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if low.endswith(".webp"):
        return "image/webp"
    if low.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


def _vision_budget_bytes() -> int:
    raw = os.environ.get("QUOTE_STRUCTURE_VISION_MAX_BYTES_PER_IMAGE", "").strip()
    if raw.isdigit():
        return max(50_000, min(int(raw), 2_000_000))
    return 520_000


def select_structure_vision_payloads(media: list[tuple[str, bytes]]) -> tuple[tuple[str, str], ...]:
    """Pick up to N images as (mime, base64_without_prefix) for multimodal APIs."""
    max_n = 4
    try:
        max_n = int(os.environ.get("QUOTE_STRUCTURE_VISION_MAX_IMAGES", "4").strip() or "4")
    except ValueError:
        max_n = 4
    max_n = max(0, min(max_n, 8))
    if max_n <= 0:
        return tuple()

    budget = _vision_budget_bytes()
    picked: list[tuple[str, str]] = []
    for path, blob in media:
        if len(blob) > budget:
            continue
        mime = _mime_for_media_path(path)
        if mime == "application/octet-stream":
            continue
        try:
            b64 = base64.b64encode(blob).decode("ascii")
        except Exception:
            continue
        picked.append((mime, b64))
        if len(picked) >= max_n:
            break
    return tuple(picked)


def format_hyperlink_appendix(links: list[SheetHyperlink], *, priority_sheet: str = "") -> str:
    if not links:
        return ""

    prio = priority_sheet.strip()
    sorted_links = sorted(
        links,
        key=lambda h: (0 if prio and h.sheet_name.strip() == prio else 1, h.sheet_name, h.cell_ref),
    )
    lines: list[str] = []
    for h in sorted_links[:40]:
        disp = f"（{h.display}）" if h.display else ""
        lines.append(f"- 「{h.sheet_name}」{h.cell_ref}{disp}: {h.target}")
    block = "\n".join(lines)
    return (
        "\n\n【工作簿内超链接 — 辅助产品结构 / 参考图 / 外链资料】\n"
        "正文「结构说明」若不够完整，请结合下列单元格绑定的 URL 语义推断口袋数量、开口位置、分层与辅料颗数；"
        "不得凭空捏造表中完全未暗示的细节。\n"
        f"{block}"
    )


def format_media_manifest(media: list[tuple[str, bytes]], vision_count: int) -> str:
    if not media:
        return ""
    names = ", ".join(posixpath.basename(p) for p, _ in media[:12])
    tail = " …" if len(media) > 12 else ""
    if vision_count > 0:
        vis_note = f"其中有 **{vision_count}** 张已作为附图传给模型（若有标注尺寸请优先采用）。"
    else:
        vis_note = (
            "当前未向模型附带图像二进制（体积超限或未启用视觉）；仅凭文件名提示可能存在附图。"
        )
    return (
        f"\n\n【工作簿嵌入图片】共 {len(media)} 张：{names}{tail}。\n"
        + vis_note
    )


def augment_demand_structure_from_xlsx_bytes(
    file_bytes: bytes,
    structure_text: str,
    *,
    priority_sheet_name: str = "",
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Merge hyperlink manifest (+ optional vision payloads) into structure_description."""
    links = extract_hyperlinks_from_xlsx_bytes(file_bytes)
    media = list_embedded_images_from_xlsx_bytes(file_bytes)

    vision_enabled = os.environ.get("QUOTE_KIMI_STRUCTURE_VISION", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    vision_parts: tuple[tuple[str, str], ...] = ()
    if vision_enabled and media:
        vision_parts = select_structure_vision_payloads(media)

    base = str(structure_text or "").strip()

    appendix = ""
    appendix += format_hyperlink_appendix(links, priority_sheet=priority_sheet_name)
    appendix += format_fetched_hyperlink_excerpts(links, duplicate_against_text=base)
    appendix += format_media_manifest(media, len(vision_parts))

    merged = (base + appendix).strip()
    return merged, vision_parts
