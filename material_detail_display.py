"""报价详情物料明细展示：裁片/部位、规格、用量（不改小计/计价逻辑）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from material_spec_usage_enricher import (
    _fabric_spec_from_name,
    _is_fabric_material,
    is_missing_spec_usage_value,
    resolve_usage_from_row,
)

_SET_USAGE_RE = re.compile(r"^\s*1\s*套\s*$", re.I)
_TRAILING_SET_RE = re.compile(r"(\d+(?:\.\d+)?)\s*套\b", re.I)

_INFERENCE_SUFFIX_RE = re.compile(r"[（(]\s*推理待核\s*[)）]")
_PIECE_COUNT_IN_NAME_RE = re.compile(r"[（(]\s*(\d+)\s*片\s*[)）]")
_GROUP_MARK_RE = re.compile(r"组")
_GROUP_SUFFIX_IN_PIECE_RE = re.compile(r"[（(]\s*(?:1\s*组|一组)\s*[)）]")
_DIM_IN_TEXT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*[×xX*]\s*\d+(?:\.\d+)?(?:\s*[×xX*]\s*\d+(?:\.\d+)?)?\s*(?:cm|CM|厘米|㎡|m²|码)?",
    re.I,
)
_INTERNAL_PIECE_TOKENS = ("估算", "推理待核", "待核", "系统估算", "AI估算")
_PIECE_PART_NAME_MARKERS = ("前片", "后片", "底片", "侧片", "拉链弧形盖", "顶片", "盖片")


@dataclass(frozen=True)
class _DisplayCtx:
    structure_text: str
    product_size: dict[str, Any]
    size_spec_text: str
    piece_rows: tuple[dict[str, Any], ...]
    fabric_piece_part_summary: str
    fabric_piece_size_summary: str


def _strip_inference_suffix(name: str) -> str:
    return _INFERENCE_SUFFIX_RE.sub("", str(name or "")).strip()


def _fmt_lwh_spec(product_size: dict[str, Any] | None, structure_text: str = "") -> str:
    ps = product_size if isinstance(product_size, dict) else {}
    parts: list[str] = []
    for label, keys in (
        ("高度", ("height", "H", "h", "height_cm", "HCM", "hcm")),
        ("长度", ("length", "L", "l", "length_cm", "LCM", "lcm")),
        ("宽度", ("width", "W", "w", "width_cm", "WCM", "wcm")),
    ):
        for key in keys:
            val = ps.get(key)
            if val is None or str(val).strip() in ("", "-"):
                continue
            try:
                n = float(val)
            except (TypeError, ValueError):
                continue
            if n > 0:
                parts.append(f"{label}{n:g}cm")
                break
    if parts:
        return "，".join(parts)
    blob = str(structure_text or "")
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)?",
        blob,
        re.I,
    )
    if m:
        h, l, w = float(m.group(1)), float(m.group(2)), float(m.group(3))
        return f"高度{h:g}cm，长度{l:g}cm，宽度{w:g}cm"
    return "结构尺寸待核对"


def _piece_display_size(row: dict[str, Any]) -> str:
    """裁片表 size_text；缺失时用估算/待核，避免空白或 '-'。"""
    raw = str(row.get("size_text") or "").strip()
    if raw and not is_missing_spec_usage_value(raw):
        if raw in ("估算", "待核"):
            return raw
        return raw
    if row.get("inferred"):
        return "估算"
    return "待核"


def _piece_name_for_display(piece_raw: str, qty_text: str) -> str:
    """裁片展示名：片数写入名称，禁止出现「组」。"""
    piece = _strip_inference_suffix(str(piece_raw or ""))
    piece = _GROUP_SUFFIX_IN_PIECE_RE.sub("", piece).strip()
    if not piece:
        return ""

    if _PIECE_COUNT_IN_NAME_RE.search(piece):
        return piece

    qty = str(qty_text or "").strip()
    if _GROUP_MARK_RE.search(qty):
        if any(k in piece for k in ("侧片", "左右片", "双侧")):
            return piece if "（" in piece else f"{piece}（2片）"
        m = re.search(r"(\d+)\s*片", qty)
        if m and int(m.group(1)) > 1:
            return f"{piece}（{int(m.group(1))}片）"
        return piece

    m = re.search(r"(\d+)\s*片", qty)
    if m and int(m.group(1)) > 1 and "（" not in piece:
        return f"{piece}（{int(m.group(1))}片）"

    if re.fullmatch(r"\d+", qty):
        n = int(qty)
        if n > 1 and "（" not in piece:
            return f"{piece}（{n}片）"
        return piece

    if any(k in piece for k in ("侧片", "左右片", "双侧")) and "（" not in piece:
        return f"{piece}（2片）"

    return piece


def _piece_part_name_only(row: dict[str, Any]) -> str:
    """裁片/部位列：仅部位名与片数，不含尺寸/估算。"""
    if not isinstance(row, dict) or row.get("is_total"):
        return ""
    return _piece_name_for_display(
        str(row.get("piece") or ""),
        str(row.get("qty_text") or ""),
    )


def _piece_size_line(row: dict[str, Any]) -> str:
    """规格/尺寸列用：部位 + 尺寸，如「前片 19×45」。"""
    if not isinstance(row, dict) or row.get("is_total"):
        return ""
    piece_name = _piece_part_name_only(row)
    if not piece_name:
        return ""
    size = _piece_display_size(row)
    if size in ("估算", "待核"):
        return f"{piece_name} {size}"
    if size and "×" in size:
        return f"{piece_name} {size}"
    m = _PIECE_COUNT_IN_NAME_RE.search(piece_name)
    if m and not size:
        base = piece_name[: m.start()].strip()
        return f"{base} {m.group(1)}片"
    return piece_name


def _fabric_piece_part_summary(piece_rows: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    for row in piece_rows:
        if not isinstance(row, dict) or row.get("is_total"):
            continue
        label = _piece_part_name_only(row)
        if label:
            labels.append(label)
    return "；".join(labels)


def _fabric_piece_size_summary(piece_rows: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    for row in piece_rows:
        if not isinstance(row, dict) or row.get("is_total"):
            continue
        label = _piece_size_line(row)
        if label:
            labels.append(label)
    return "；".join(labels)


def _looks_like_piece_manifest(text: str) -> bool:
    """整包裁片尺寸清单（禁止写入非主料行的规格/裁片列）。"""
    s = str(text or "").strip()
    if not s:
        return False
    hits = sum(1 for m in _PIECE_PART_NAME_MARKERS if m in s)
    if hits >= 2:
        return True
    if hits >= 1 and ("；" in s or ";" in s) and _DIM_IN_TEXT_RE.search(s):
        return True
    return False


def _inference_mark_spec(name: str) -> str:
    raw = str(name or "")
    if "系统估算" in raw or "系统推断" in raw:
        return "系统估算"
    if any(k in raw for k in ("推理待核", "推断待核", "AI估算", "待核")):
        return "推理待核"
    if _INFERENCE_SUFFIX_RE.search(raw):
        return "推理待核"
    return ""


def _rule_piece_part_label(clean_name: str) -> str:
    """非主料：裁片/部位仅显示物料对应部位标签。"""
    clean = _strip_inference_suffix(clean_name)
    if not clean:
        return "待核"
    rules: list[tuple[tuple[str, ...], str]] = [
        (("侧袋", "侧兜"), "侧袋"),
        (("背垫", "背板"), "背垫"),
        (("提手", "手挽"), "提手"),
        (("隔层", "夹层", "分隔"), "隔层"),
        (("工艺费", "加工费", "车缝费"), "工艺费"),
        (("拉头", "拉鍊头", "slider"), "拉链拉头"),
        (("拉链", "zipper", "zip"), "拉链"),
        (("插扣", "梯扣", "猪鼻", "d扣", "d环", "扣具", "buckle"), "扣具"),
        (("挂钩", "hook"), "挂钩"),
        (("织标", "布标", "唛", "贴标"), "织标"),
        (("魔术贴", "velcro"), "魔术贴"),
        (("缝纫线", "thread"), "缝纫线"),
        (("织带", "webbing", "肩带", "背带"), "织带"),
        (("纸箱", "外箱"), "外箱包装"),
        (("胶袋", "pe袋", "包装袋"), "包装袋"),
        (("包装",), "包装"),
    ]
    for keys, label in rules:
        if any(k in clean for k in keys):
            return label
    return clean


def _piece_part_has_pollution(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if any(tok in s for tok in _INTERNAL_PIECE_TOKENS):
        return True
    if _DIM_IN_TEXT_RE.search(s):
        return True
    if re.search(r"\d+(?:\.\d+)?\s*(?:㎡|m²|米|码|个|条)", s):
        return True
    return False


def _count_in_structure(structure_text: str, patterns: tuple[str, ...], default: int) -> int:
    blob = str(structure_text or "")
    for pat in patterns:
        m = re.search(pat, blob, re.I)
        if m:
            try:
                return max(1, int(float(m.group(1))))
            except (ValueError, IndexError):
                return max(1, default)
    return default


def _infer_usage_for_name(name: str, unit_price: str, *, structure_text: str) -> str:
    clean = _strip_inference_suffix(name)
    blob = f"{clean} {unit_price}".lower()

    if any(k in clean for k in ("侧袋", "侧兜", "side pocket")):
        if re.search(r"双侧袋|两个侧袋|2\s*个侧袋|侧袋\s*2", structure_text, re.I):
            return "2个"
        n = _count_in_structure(structure_text, (r"侧袋\s*(\d+)", r"(\d+)\s*个侧袋"), 1)
        return f"{n}个"
    if "背垫" in clean:
        return "1片"
    if "隔层" in clean or "夹层" in clean:
        return "1片"
    if "提手" in clean:
        return "2条" if re.search(r"双提手|2\s*条提手|两条提手", structure_text, re.I) else "1条"
    if any(k in clean for k in ("工艺费", "加工费", "车缝", "丝印", "热转印", "刺绣")):
        return "1项"
    if "拉头" in clean or "slider" in blob:
        z = _count_in_structure(structure_text, (r"拉链\s*(\d+)", r"(\d+)\s*条拉链"), 1)
        return f"{max(1, z)}个"
    if any(k in clean for k in ("插扣", "梯扣", "猪鼻", "d扣", "d环", "调节扣", "扣具", "buckle")):
        hardware_count = _count_in_structure(structure_text, (r"扣具\s*(\d+)", r"D环\s*(\d+)"), 2)
        return f"{hardware_count}个"
    if "挂钩" in clean or "hook" in blob:
        return "1个"
    if any(k in clean for k in ("织标", "布标", "唛", "贴标", "label")):
        return "1个"
    if "魔术贴" in clean or "velcro" in blob:
        return "1条"
    if "缝纫线" in clean and "线" in clean:
        return "1卷"
    if "拉链" in clean or "zipper" in blob or "zip" in blob:
        return "1条"
    if any(k in clean for k in ("织带", "webbing", "肩带", "背带")):
        return "1.72米" if "1.72" in unit_price else "1米"
    if any(k in clean for k in ("绳", "cord", "弹力")):
        return "0.3米"
    if any(k in clean for k in ("纸箱", "外箱")):
        return "1个外纸箱"
    if any(k in clean for k in ("胶袋", "pe袋", "包装袋")):
        return "1个包装袋"
    if any(k in clean for k in ("包装", "packaging")):
        return "1个"
    if _is_fabric_material(clean, blob):
        if re.search(r"码²|㎡|m²", unit_price, re.I):
            return "0.2㎡"
        if re.search(r"元\s*/\s*码|/码", unit_price, re.I):
            return "0.83码"
        return "0.3码"
    if re.search(r"元\s*/\s*米|/米", unit_price, re.I):
        return "1米"
    if re.search(r"元\s*/\s*码|/码", unit_price, re.I):
        return "1码"
    if re.search(r"元\s*/\s*条|/条", unit_price, re.I):
        return "1条"
    if re.search(r"元\s*/\s*个|/个", unit_price, re.I):
        return "1个"
    return "1个"


def _normalize_usage_display(
    name: str,
    usage: str,
    unit_price: str,
    *,
    structure_text: str,
) -> tuple[str, bool]:
    from material_inference import is_inference_pending_name, pending_inference_usage_label

    raw = str(usage or "").strip()
    if is_inference_pending_name(name):
        if not raw or raw in ("-", "—") or _SET_USAGE_RE.match(raw) or raw in ("一套", "1组", "一组"):
            repl = pending_inference_usage_label(name, {"usage": raw})
            return repl, True
        m = _TRAILING_SET_RE.search(raw)
        if m and not any(k in name for k in ("包装", "纸箱", "胶袋")):
            repl = pending_inference_usage_label(name, {"usage": raw})
            return repl, repl != raw
    if not raw or raw in ("-", "—"):
        return _infer_usage_for_name(name, unit_price, structure_text=structure_text), True
    if _SET_USAGE_RE.match(raw) or raw in ("一套",):
        return _infer_usage_for_name(name, unit_price, structure_text=structure_text), True
    m = _TRAILING_SET_RE.search(raw)
    if m and not any(k in name for k in ("包装", "纸箱", "胶袋")):
        repl = _infer_usage_for_name(name, unit_price, structure_text=structure_text)
        return repl, repl != raw
    return raw, False


def _resolve_piece_part(name: str, row: dict[str, Any], ctx: _DisplayCtx) -> str:
    clean = _strip_inference_suffix(name)
    if not clean:
        return "待核"

    if not _is_fabric_material(clean, clean):
        label = _rule_piece_part_label(clean)
        if label and not _looks_like_piece_manifest(label):
            return label
        return _rule_piece_part_label(clean)

    for pr in ctx.piece_rows:
        if pr.get("is_total"):
            continue
        piece = _strip_inference_suffix(str(pr.get("piece") or ""))
        if piece and (piece in clean or clean in piece):
            return _piece_part_name_only(pr)

    rules: list[tuple[tuple[str, ...], str]] = [
        (("侧袋", "侧兜"), "侧袋"),
        (("背垫", "背板"), "背垫"),
        (("提手", "手挽"), "提手"),
        (("隔层", "夹层", "分隔"), "隔层"),
        (("工艺费", "加工费", "车缝费"), "工艺工序"),
        (("拉头", "拉鍊头", "slider"), "拉链拉头"),
        (("拉链", "zipper", "zip"), "拉链"),
        (("插扣", "梯扣", "猪鼻", "d扣", "d环", "扣具", "buckle"), "扣具"),
        (("挂钩", "hook"), "挂钩"),
        (("织标", "布标", "唛", "贴标"), "织标"),
        (("魔术贴", "velcro"), "魔术贴"),
        (("缝纫线", "thread"), "缝纫线"),
        (("织带", "webbing", "肩带", "背带"), "织带"),
        (("纸箱", "外箱"), "外箱包装"),
        (("胶袋", "pe袋", "包装袋"), "包装袋"),
        (("包装",), "包装"),
    ]
    for keys, label in rules:
        if any(k in clean for k in keys):
            return label

    if _is_fabric_material(clean, clean):
        if ctx.fabric_piece_part_summary:
            return ctx.fabric_piece_part_summary
        return "主料裁片 待核"

    return clean


def _zipper_spec_display(name: str, spec: str) -> str:
    from material_spec_usage_enricher import _zipper_display_spec

    s = str(spec or "").strip()
    if s and not is_missing_spec_usage_value(s):
        return s
    return _zipper_display_spec(name, {})


def _ensure_display_spec(name: str, spec: str, row: dict[str, Any], ctx: _DisplayCtx) -> str:
    del ctx
    s = str(spec or "").strip()
    if _looks_like_piece_manifest(s):
        s = ""
    clean = _strip_inference_suffix(name)
    blob = f"{clean} {s}".lower()

    inf = _inference_mark_spec(name)
    if inf:
        return inf

    if any(k in clean for k in ("拉链", "zipper")) and "拉头" not in clean:
        return _zipper_spec_display(name, s)

    if _is_fabric_material(clean, blob):
        if s and not is_missing_spec_usage_value(s) and not _looks_like_piece_manifest(s):
            return s
        fs = _fabric_spec_from_name(name)
        if fs:
            return fs
        return clean[:48] if clean else "主料规格待核"

    if s and not is_missing_spec_usage_value(s) and not _looks_like_piece_manifest(s):
        return s

    from material_spec_usage_enricher import _infer_display_spec

    return _infer_display_spec(name, row)


def _build_ctx(
    quote_obj: dict[str, Any],
    *,
    structure_text: str = "",
    product_size: dict[str, Any] | None = None,
) -> _DisplayCtx:
    st = str(
        structure_text
        or quote_obj.get("structure_text_snapshot")
        or quote_obj.get("structure_text")
        or ""
    ).strip()
    ps = product_size if isinstance(product_size, dict) else quote_obj.get("product_size")
    if not isinstance(ps, dict):
        ps = {}
    pac = quote_obj.get("piece_area_calculation")
    piece_rows: list[dict[str, Any]] = []
    if isinstance(pac, dict) and isinstance(pac.get("rows"), list):
        piece_rows = [r for r in pac["rows"] if isinstance(r, dict)]
    return _DisplayCtx(
        structure_text=st,
        product_size=ps,
        size_spec_text=_fmt_lwh_spec(ps, st),
        piece_rows=tuple(piece_rows),
        fabric_piece_part_summary=_fabric_piece_part_summary(piece_rows),
        fabric_piece_size_summary=_fabric_piece_size_summary(piece_rows),
    )


def enrich_material_row_display(
    row: dict[str, Any],
    *,
    ctx: _DisplayCtx,
) -> dict[str, Any]:
    if not isinstance(row, dict):
        return row
    name = str(row.get("name") or "").strip()
    if not name or row.get("exclude_from_cost"):
        return row

    unit_price = str(row.get("unit_price") or "").strip()
    auth_usage = resolve_usage_from_row(row).value
    usage_out, usage_changed = _normalize_usage_display(
        name,
        str(row.get("usage") or auth_usage),
        unit_price,
        structure_text=ctx.structure_text,
    )
    if usage_changed or _SET_USAGE_RE.match(str(row.get("usage") or "").strip()):
        row["_usage_display_inferred"] = True
    row["usage"] = usage_out

    spec_out = _ensure_display_spec(name, str(row.get("spec") or ""), row, ctx)
    piece_out = _resolve_piece_part(name, row, ctx)
    if _looks_like_piece_manifest(piece_out) or _piece_part_has_pollution(piece_out):
        if _is_fabric_material(name, name):
            piece_out = _fabric_piece_part_summary(list(ctx.piece_rows)) or piece_out
        else:
            piece_out = _rule_piece_part_label(_strip_inference_suffix(name))
    row["spec"] = spec_out
    row["piece_part"] = piece_out
    return row


def quote_sheet_piece_part_text(quote_obj: dict[str, Any]) -> str:
    """报价单 PDF「尺寸」列附带的裁片/部位摘要（需先 enrich detail_rows）。"""
    if not isinstance(quote_obj, dict):
        return ""
    ctx = _build_ctx(quote_obj)
    labels: list[str] = []
    seen: set[str] = set()
    for raw in quote_obj.get("detail_rows") or []:
        if not isinstance(raw, dict):
            continue
        pp = str(raw.get("piece_part") or "").strip()
        if not pp or pp in ("-", "—") or pp in seen:
            continue
        seen.add(pp)
        labels.append(pp)
    return "；".join(labels[:16])


def enrich_quote_material_detail_display(
    quote_obj: dict[str, Any] | None,
    *,
    structure_text: str = "",
    product_size: dict[str, Any] | None = None,
) -> None:
    if not isinstance(quote_obj, dict):
        return
    ctx = _build_ctx(quote_obj, structure_text=structure_text, product_size=product_size)
    dr = quote_obj.get("detail_rows")
    if not isinstance(dr, list):
        return
    out: list[dict[str, Any]] = []
    for raw in dr:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        enrich_material_row_display(row, ctx=ctx)
        out.append(row)
    quote_obj["detail_rows"] = out
