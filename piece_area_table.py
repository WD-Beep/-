"""裁片面积核算归档；完整裁片表时作为主料/里布㎡用量的共用面积基准。"""
from __future__ import annotations

import re
from typing import Any

from structure_usage import _dims_lwh_cm, _has_box_dims, _roll_width_cm

_PIECE_NAME_KEYS = (
    "前片",
    "后片",
    "底片",
    "侧片",
    "顶片",
    "盖片",
    "拉链",
    "弧形",
    "前幅",
    "后幅",
    "侧围",
    "围片",
)

_BAG_HINTS = ("包", "袋", "背包", "篮球", "旅行", "收纳", "斜挎", "手提", "双肩")

_EXPLICIT_PIECE_LINE = re.compile(
    r"(?P<name>前片|后片|底片|侧片(?:[（(]\s*\d+\s*片\s*[)）])?|顶片|"
    r"拉链[^，,；;\n]{0,8}盖|拉链弧形盖|前幅|后幅|侧围|围片)"
    r"\s*[：:，,\s]*"
    r"(?P<size>[\d.]+(?:\s*[×xX*]\s*[\d.]+)+(?:\s*[×xX*]\s*\d+)?|估算|约[\d.]+)?"
    r"(?:\s*[，,；;\s]\s*(?:数量|×|x)\s*(?P<qty>\d+(?:\.\d+)?(?:组|片)?))?",
    re.I,
)

_LWH_TRIPLE_RE = re.compile(
    r"(?:成品|尺寸|规格|约)?[\s：:（(]*"
    r"(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米|mm|MM|毫米)?",
    re.I,
)

_LWH_CN_RE = re.compile(
    r"长\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米|mm|MM|毫米)?.*?"
    r"宽\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米|mm|MM|毫米)?.*?"
    r"高\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米|mm|MM|毫米)?",
    re.I | re.S,
)

_LOSS_RATE_RE = re.compile(
    r"(?:加?\s*)?(?:损耗|耗损)\s*(\d+(?:\.\d+)?)\s*(?:％|%)"
    r"|(\d+(?:\.\d+)?)\s*(?:％|%)\\s*(?:损耗|耗损)",
    re.I,
)

_YARD_PER_METER = 1.0936

_ROW_TEXT_KEYS = ("calc_note", "calc_method", "spec", "usage", "name", "ai_reason")

# 完整长方体软包裁片（几何推断基准）
_CORE_BOX_PIECE_MARKERS = ("前片", "后片", "底片", "侧片")

# 仅局部 explicit 片段，不能单独替代完整几何推断
_PARTIAL_EXPLICIT_MARKERS = (
    "拉链",
    "盖片",
    "盖",
    "侧袋",
    "口袋",
    "提手",
    "背垫",
    "织唛",
    "标",
)


def _fmt_dim(n: float) -> str:
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:g}"


def _fmt_size_label(l: float, w: float, h: float) -> str:
    return f"{_fmt_dim(l)}×{_fmt_dim(w)}×{_fmt_dim(h)}cm"


def _row_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _ROW_TEXT_KEYS:
        val = str(row.get(key) or "").strip()
        if val and val != "-":
            parts.append(val)
    return " ".join(parts)


def _collect_item_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """合并 detail_rows / items / quote_items，避免 items 空 calc_note 覆盖 detail_rows。"""
    merged: list[dict[str, Any]] = []
    by_line: dict[int, dict[str, Any]] = {}

    def _merge_into(line_no: int, row: dict[str, Any]) -> None:
        if line_no <= 0:
            line_no = len(by_line) + 1
        base = by_line.get(line_no, {})
        out = dict(base)
        for key in ("name", "spec", "usage", "unit_price", "amount", "amount_text", "source"):
            val = row.get(key)
            if val is not None and str(val).strip() not in ("", "-"):
                out[key] = val
        for key in ("calc_note", "calc_method"):
            val = str(row.get(key) or "").strip()
            if not val:
                continue
            prev = str(out.get(key) or "").strip()
            if not prev or len(val) > len(prev):
                out[key] = val
        by_line[line_no] = out

    for src_key in ("detail_rows", "items"):
        src = payload.get(src_key)
        if not isinstance(src, list):
            continue
        for idx, row in enumerate(src):
            if not isinstance(row, dict):
                continue
            try:
                ln = int(row.get("line_no") or idx + 1)
            except (TypeError, ValueError):
                ln = idx + 1
            _merge_into(ln, row)

    for ln in sorted(by_line.keys()):
        merged.append(by_line[ln])
    return merged


def _collect_context_blobs(payload: dict[str, Any]) -> list[str]:
    blobs: list[str] = []
    for key in (
        "structure_text_snapshot",
        "structure_text",
        "structure",
        "product_structure",
        "product_size_text",
        "size_text",
        "product_type",
        "product_name",
        "product_description",
        "structure_description",
    ):
        val = str(payload.get(key) or "").strip()
        if val:
            blobs.append(val)

    checklist = payload.get("structure_checklist")
    if isinstance(checklist, dict):
        for item in checklist.get("items") or []:
            if not isinstance(item, dict):
                continue
            for key in ("label", "name", "structure_name", "user_note", "note"):
                val = str(item.get(key) or "").strip()
                if val:
                    blobs.append(val)

    inf = payload.get("material_inference_report")
    if isinstance(inf, dict):
        for key in ("structure_summary", "vision_summary", "notes"):
            val = str(inf.get(key) or "").strip()
            if val:
                blobs.append(val)

    for row in _collect_item_rows(payload):
        blobs.append(_row_text(row))

    return blobs


def _parse_lwh_from_text(blob: str) -> tuple[float, float, float] | None:
    text = str(blob or "").strip()
    if not text:
        return None
    m = _LWH_TRIPLE_RE.search(text)
    if m:
        a, b, c = float(m.group(1)), float(m.group(2)), float(m.group(3))
        if "mm" in text.lower() or "毫米" in text:
            a, b, c = a / 10.0, b / 10.0, c / 10.0
        if min(a, b, c) > 0:
            return a, b, c
    m2 = _LWH_CN_RE.search(text)
    if m2:
        a, b, c = float(m2.group(1)), float(m2.group(2)), float(m2.group(3))
        if "mm" in text.lower() or "毫米" in text:
            a, b, c = a / 10.0, b / 10.0, c / 10.0
        return a, b, c
    labeled = _parse_lwh_labeled_any_order(text)
    if labeled:
        return labeled
    return None


def _parse_lwh_labeled_any_order(text: str) -> tuple[float, float, float] | None:
    """解析「高度 : 45 cm，长度 : 32 cm，宽度 : 19 cm」等任意顺序标注。"""
    vals: dict[str, float] = {}
    patterns = (
        (r"长度\s*[：:]\s*(\d+(?:\.\d+)?)", "l"),
        (r"宽度\s*[：:]\s*(\d+(?:\.\d+)?)", "w"),
        (r"高度\s*[：:]\s*(\d+(?:\.\d+)?)", "h"),
        (r"长\s*[：:]\s*(\d+(?:\.\d+)?)", "l"),
        (r"宽\s*[：:]\s*(\d+(?:\.\d+)?)", "w"),
        (r"高\s*[：:]\s*(\d+(?:\.\d+)?)", "h"),
    )
    for pat, key in patterns:
        if key in vals:
            continue
        m = re.search(pat, text, re.I)
        if m:
            vals[key] = float(m.group(1))
    if len(vals) == 3:
        return vals["l"], vals["w"], vals["h"]
    return None


def _normalize_lwh(payload: dict[str, Any]) -> tuple[float, float, float] | None:
    ps = payload.get("product_size")
    if isinstance(ps, dict) and _has_box_dims(ps):
        l_, w_, h_ = _dims_lwh_cm(ps)
        if l_ > 0 and w_ > 0 and h_ > 0:
            return l_, w_, h_

    for blob in _collect_context_blobs(payload):
        got = _parse_lwh_from_text(blob)
        if got:
            return got
    return None


def _parse_loss_rate_pct(text_blob: str) -> float | None:
    text = text_blob or ""
    for m in _LOSS_RATE_RE.finditer(text):
        raw = m.group(1) or m.group(2)
        if not raw:
            continue
        try:
            val = float(raw)
        except ValueError:
            continue
        if 0 < val <= 80:
            return val
    return None


def _infer_roll_width_cm(payload: dict[str, Any]) -> float | None:
    for blob in _collect_context_blobs(payload):
        w = _roll_width_cm(blob)
        if w > 0:
            return w
    for row in _collect_item_rows(payload):
        spec = str(row.get("spec") or "")
        m = re.search(r"(\d{2,3})\s*[*×xX]\s*\d+\s*(?:CM|cm|厘米)?", spec)
        if m:
            val = float(m.group(1))
            if 20 < val <= 260:
                return val
    return None


def _area_row(
    piece: str,
    size_text: str,
    qty_text: str,
    unit_area: float,
    *,
    is_total: bool = False,
    inferred: bool = False,
) -> dict[str, Any]:
    total = round(unit_area, 2) if is_total else round(unit_area * _qty_multiplier(qty_text), 2)
    row: dict[str, Any] = {
        "piece": piece,
        "size_text": size_text,
        "qty_text": qty_text,
        "unit_area_cm2": round(unit_area, 2) if not is_total else "",
        "total_area_cm2": total,
        "is_total": is_total,
    }
    if inferred:
        row["inferred"] = True
    return row


def _qty_multiplier(qty_text: str) -> float:
    t = str(qty_text or "").strip()
    if not t:
        return 1.0
    if t.endswith("组"):
        m_grp = re.search(r"(\d+(?:\.\d+)?)", t)
        if m_grp:
            return max(1.0, float(m_grp.group(1)))
        return 1.0
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if not m:
        return 1.0
    try:
        return max(1.0, float(m.group(1)))
    except ValueError:
        return 1.0


def _bag_context_text(payload: dict[str, Any]) -> str:
    return "\n".join(_collect_context_blobs(payload))


def _needs_zipper_cover(payload: dict[str, Any], structure_text: str) -> bool:
    blob = _bag_context_text(payload).lower()
    if "拉链" in blob or "zip" in blob:
        return True
    for row in _collect_item_rows(payload):
        name = str(row.get("name") or "")
        if "拉链" in name or "zip" in name.lower():
            return True
    if any(h in blob for h in _BAG_HINTS):
        return True
    return bool(structure_text.strip())


def _estimate_zipper_cover_area(l: float, w: float, h: float) -> float:
    if max(l, w, h) <= 35:
        return 200.0
    return round(max(120.0, min(420.0, 0.45 * (l + w) * h)), 2)


def _derive_box_pieces(
    l: float,
    w: float,
    h: float,
    payload: dict[str, Any],
    *,
    structure_text: str = "",
    inferred: bool = True,
) -> list[dict[str, Any]]:
    """由成品 L×W×H 推导常见软包裁片面积。"""
    front_unit = round(w * h, 2)
    bottom_unit = round(l * w, 2)
    side_single = round(h * w, 2)
    rows: list[dict[str, Any]] = [
        _area_row("前片", f"{_fmt_dim(w)}×{_fmt_dim(h)}", "1片", front_unit, inferred=inferred),
        _area_row("后片", f"{_fmt_dim(w)}×{_fmt_dim(h)}", "1片", front_unit, inferred=inferred),
        _area_row("底片", f"{_fmt_dim(l)}×{_fmt_dim(w)}", "1片", bottom_unit, inferred=inferred),
        _area_row(
            "侧片（2片）",
            f"{_fmt_dim(h)}×{_fmt_dim(w)}",
            "2片",
            side_single,
            inferred=inferred,
        ),
    ]
    if _needs_zipper_cover(payload, structure_text):
        est = _estimate_zipper_cover_area(l, w, h)
        label = "拉链弧形盖（推理待核）" if inferred else "拉链弧形盖"
        rows.append(_area_row(label, "估算", "1", est, inferred=inferred))
    return rows


def _parse_explicit_pieces(structure_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not structure_text:
        return rows
    for line in re.split(r"[\n\r；;]+", structure_text):
        line = line.strip()
        if not line or not any(k in line for k in _PIECE_NAME_KEYS):
            continue
        # 物料行如「#5尼龙拉链」不是裁片表行
        if re.search(r"尼龙拉链|拉链带|拉链头|拉头|元/条|元/码|元/㎡", line, re.I):
            continue
        m = _EXPLICIT_PIECE_LINE.search(line)
        if not m:
            continue
        name = str(m.group("name") or "").strip()
        size_raw = str(m.group("size") or "").strip()
        qty_raw = str(m.group("qty") or "1").strip() or "1"
        if size_raw in {"估算", ""}:
            unit = 200.0
            size_show = "估算"
        else:
            nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", size_raw.replace("×", "x"))]
            if len(nums) >= 2:
                unit = round(nums[0] * nums[1] * (nums[2] if len(nums) >= 3 else 1.0), 2)
                size_show = size_raw.replace("*", "×").replace("x", "×").replace("X", "×")
            else:
                continue
        rows.append(_area_row(name, size_show, qty_raw, unit, inferred=False))
    return rows


def _piece_name_key(name: str) -> str:
    n = str(name or "").strip()
    for marker in _CORE_BOX_PIECE_MARKERS:
        if marker in n:
            return marker
    if "拉链" in n and ("盖" in n or "弧形" in n):
        return "拉链弧形盖"
    if "盖" in n:
        return "盖片"
    return n


def _explicit_has_core_box(explicit: list[dict[str, Any]]) -> bool:
    keys = {_piece_name_key(str(r.get("piece") or "")) for r in explicit}
    return all(any(m in k for k in keys) for m in _CORE_BOX_PIECE_MARKERS)


def _explicit_is_partial_only(explicit: list[dict[str, Any]]) -> bool:
    if not explicit:
        return False
    if _explicit_has_core_box(explicit):
        return False
    return all(
        any(p in str(r.get("piece") or "") for p in _PARTIAL_EXPLICIT_MARKERS)
        for r in explicit
    )


def _dedupe_explicit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = _piece_name_key(str(row.get("piece") or ""))
        dedupe_key = f"{key}|{row.get('size_text')}|{row.get('total_area_cm2')}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(row)
    return out


def _merge_geometry_and_explicit(
    geometry_rows: list[dict[str, Any]],
    explicit_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """几何基础裁片 + 合理 explicit 补充，避免重复拉链盖/盖片。"""
    merged = list(geometry_rows)
    existing = {_piece_name_key(str(r.get("piece") or "")) for r in merged}
    for row in explicit_rows:
        key = _piece_name_key(str(row.get("piece") or ""))
        if key in existing:
            continue
        if key in _CORE_BOX_PIECE_MARKERS:
            continue
        if key == "拉链弧形盖" and "拉链弧形盖" in existing:
            continue
        merged.append(row)
        existing.add(key)
    return merged


def body_piece_area_m2_with_loss(
    calc: dict[str, Any] | None,
    *,
    loss_pct: float | None = None,
) -> float | None:
    """裁片表非合计行面积之和，加损耗后换算为㎡。"""
    if not isinstance(calc, dict):
        return None
    rows = calc.get("rows")
    if not isinstance(rows, list):
        return None
    total_cm2 = sum(
        float(r.get("total_area_cm2") or 0)
        for r in rows
        if not r.get("is_total")
    )
    if total_cm2 <= 0:
        return None
    loss = loss_pct
    if loss is None:
        raw_loss = calc.get("loss_rate_pct")
        loss = float(raw_loss) if raw_loss is not None else 15.0
    with_loss = total_cm2 * (1.0 + float(loss) / 100.0)
    return round(with_loss / 10_000.0, 5)


def _is_complete_piece_area_calc(calc: dict[str, Any] | None) -> bool:
    if not isinstance(calc, dict):
        return False
    rows = calc.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    names = [str(r.get("piece") or "") for r in rows if not r.get("is_total")]
    return all(any(marker in name for name in names) for marker in _CORE_BOX_PIECE_MARKERS)


def _build_notes(
    total_cm2: float,
    *,
    loss_pct: float | None,
    roll_cm: float | None,
    review_hint: str = "",
) -> list[str]:
    notes: list[str] = []
    if review_hint:
        notes.append(review_hint)
    if total_cm2 <= 0:
        return notes
    loss = loss_pct if loss_pct is not None else 15.0
    with_loss = round(total_cm2 * (1.0 + loss / 100.0), 2)
    m2 = round(with_loss / 10_000.0, 4)
    notes.append(
        f"加损耗{loss:g}%：{round(total_cm2, 2):g} × {1 + loss / 100:.4g} = "
        f"{with_loss:g} cm² = {m2:g} m²"
    )
    if roll_cm and roll_cm > 0:
        len_m = round(m2 / (roll_cm / 100.0), 4)
        yards = round(len_m * _YARD_PER_METER, 4)
        notes.append(
            f"门幅{roll_cm:g}cm → 所需长度 = {m2:g} ÷ {roll_cm / 100:g} = {len_m:g} m"
        )
        notes.append(f"换算码：{len_m:g} × {_YARD_PER_METER:g} = {yards:g} 码")
    return notes


def build_piece_area_calculation(payload: dict[str, Any]) -> dict[str, Any] | None:
    """从归档 payload 构建裁片面积核算表；无足够数据时返回 None。"""
    if not isinstance(payload, dict):
        return None

    context = _bag_context_text(payload)
    structure_text = str(
        payload.get("structure_text_snapshot") or payload.get("structure_text") or ""
    ).strip()
    if not structure_text and context:
        structure_text = context[:2000]

    dims = _normalize_lwh(payload)
    explicit = _dedupe_explicit_rows(
        _parse_explicit_pieces(structure_text) + _parse_explicit_pieces(context)
    )

    rows: list[dict[str, Any]]
    source = "geometry_derived"
    review_hint = "部分裁片由结构说明/面料核算/尺寸推断生成，推理待核，请对照纸样复核。"

    if dims:
        l_, w_, h_ = dims
        geometry_rows = _derive_box_pieces(
            l_, w_, h_, payload, structure_text=structure_text, inferred=True
        )
        if explicit and not _explicit_is_partial_only(explicit) and _explicit_has_core_box(explicit):
            rows = explicit
            source = "structure_text_parsed"
            review_hint = ""
        elif explicit:
            rows = _merge_geometry_and_explicit(geometry_rows, explicit)
            source = "geometry_merged" if explicit else "geometry_derived"
        else:
            rows = geometry_rows
    elif explicit and len(explicit) >= 2 and not _explicit_is_partial_only(explicit):
        rows = explicit
        source = "structure_text_parsed"
        review_hint = ""
    elif explicit:
        rows = explicit
        source = "structure_text_parsed"
        review_hint = "局部裁片来自结构说明解析，推理待核，请对照纸样复核。"
    else:
        return None

    total = round(
        sum(float(r.get("total_area_cm2") or 0) for r in rows if not r.get("is_total")),
        2,
    )
    if total <= 0:
        return None

    rows.append(
        {
            "piece": "合计",
            "size_text": "",
            "qty_text": "",
            "unit_area_cm2": "",
            "total_area_cm2": total,
            "is_total": True,
        }
    )

    size_label = ""
    if dims:
        size_label = _fmt_size_label(*dims)
    elif str(payload.get("product_size_text") or "").strip():
        size_label = str(payload.get("product_size_text")).strip()
        if not size_label.lower().endswith("cm"):
            size_label = f"{size_label}cm"

    loss_pct = _parse_loss_rate_pct(context)
    roll_cm = _infer_roll_width_cm(payload)

    return {
        "version": 1,
        "source": source,
        "inferred": source in ("geometry_derived", "geometry_merged"),
        "product_size_label": size_label,
        "rows": rows,
        "total_area_cm2": total,
        "loss_rate_pct": loss_pct,
        "roll_width_cm": roll_cm,
        "notes": _build_notes(
            total,
            loss_pct=loss_pct,
            roll_cm=roll_cm,
            review_hint=review_hint,
        ),
    }


def _should_rebuild_piece_area(existing: dict[str, Any] | None) -> bool:
    """已有归档但不完整（如仅拉链盖）时需重建。"""
    if not isinstance(existing, dict):
        return True
    rows = existing.get("rows")
    if not isinstance(rows, list) or not rows:
        return True
    return not _is_complete_piece_area_calc(existing)


_PIECE_COUNT_IN_LABEL_RE = re.compile(r"[（(]\s*(\d+)\s*片\s*[)）]")
_GROUP_QTY_RE = re.compile(r"^\s*(?:1\s*组|一组|\d+\s*组)\s*$", re.I)


def _normalize_piece_area_row_display(row: dict[str, Any]) -> dict[str, Any]:
    """展示层：数量用「片」，禁止「组」；侧片拆成单面积×片数。"""
    if not isinstance(row, dict) or row.get("is_total"):
        return row
    out = dict(row)
    piece = str(out.get("piece") or "").strip()
    qty = str(out.get("qty_text") or "").strip()
    size = str(out.get("size_text") or "").strip()
    unit = out.get("unit_area_cm2")
    total = out.get("total_area_cm2")
    try:
        unit_f = float(unit) if unit not in ("", None) else 0.0
    except (TypeError, ValueError):
        unit_f = 0.0
    try:
        total_f = float(total) if total not in ("", None) else 0.0
    except (TypeError, ValueError):
        total_f = 0.0

    piece_count = 1
    m_pc = _PIECE_COUNT_IN_LABEL_RE.search(piece)
    if m_pc:
        piece_count = max(1, int(m_pc.group(1)))
    elif any(k in piece for k in ("侧片", "左右片", "双侧")):
        piece_count = 2

    if _GROUP_QTY_RE.match(qty) or qty.endswith("组"):
        qty = f"{piece_count}片"
        out["qty_text"] = qty

    if "×2" in size.replace("*", "×").replace("x", "×"):
        nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", size.replace("×", "x"))]
        if len(nums) >= 2:
            single = round(nums[0] * nums[1], 2)
            out["size_text"] = f"{_fmt_dim(nums[0])}×{_fmt_dim(nums[1])}"
            unit_f = single
            out["unit_area_cm2"] = single
            total_f = round(single * piece_count, 2)
            out["total_area_cm2"] = total_f
    elif unit_f > 0 and piece_count > 1 and (total_f <= 0 or abs(total_f - unit_f) < 0.01):
        total_f = round(unit_f * piece_count, 2)
        out["total_area_cm2"] = total_f
        if unit_f > 0 and piece_count > 1:
            out["unit_area_cm2"] = round(total_f / piece_count, 2)

    if qty and not qty.endswith("片") and re.fullmatch(r"\d+(?:\.\d+)?", qty):
        out["qty_text"] = f"{int(float(qty))}片" if float(qty) == int(float(qty)) else f"{qty}片"

    return out


def normalize_piece_area_display(calc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(calc, dict):
        return calc
    rows_in = calc.get("rows")
    if not isinstance(rows_in, list):
        return calc
    rows_out: list[dict[str, Any]] = []
    sum_total = 0.0
    for raw in rows_in:
        if not isinstance(raw, dict):
            continue
        row = _normalize_piece_area_row_display(raw)
        rows_out.append(row)
        if not row.get("is_total"):
            try:
                sum_total += float(row.get("total_area_cm2") or 0)
            except (TypeError, ValueError):
                pass
    for row in rows_out:
        if row.get("is_total"):
            row["total_area_cm2"] = round(sum_total, 2)
    out = dict(calc)
    out["rows"] = rows_out
    out["total_area_cm2"] = round(sum_total, 2)
    return out


def attach_piece_area_calculation(payload: dict[str, Any]) -> dict[str, Any] | None:
    """写入 payload['piece_area_calculation']；返回构建结果或 None。"""
    if not isinstance(payload, dict):
        return None
    existing = payload.get("piece_area_calculation")
    if isinstance(existing, dict) and not _should_rebuild_piece_area(existing):
        return existing
    built = build_piece_area_calculation(payload)
    if built:
        payload["piece_area_calculation"] = normalize_piece_area_display(built) or built
    else:
        payload.pop("piece_area_calculation", None)
    return payload.get("piece_area_calculation")


def enrich_quote_piece_area_on_read(quote_obj: dict[str, Any], items: list[dict[str, Any]] | None = None) -> None:
    """后台详情读取时补全历史归档缺失的裁片面积表（不写库）。"""
    if not isinstance(quote_obj, dict):
        return
    existing = quote_obj.get("piece_area_calculation")
    if isinstance(existing, dict) and not _should_rebuild_piece_area(existing):
        quote_obj["piece_area_calculation"] = (
            normalize_piece_area_display(existing) or existing
        )
        return

    ctx = dict(quote_obj)
    if isinstance(items, list) and items:
        db_items = list(items)
        dr = ctx.get("detail_rows")
        if isinstance(dr, list) and dr:
            imap: dict[int, dict[str, Any]] = {}
            for idx, row in enumerate(dr):
                if isinstance(row, dict):
                    try:
                        ln = int(row.get("line_no") or idx + 1)
                    except (TypeError, ValueError):
                        ln = idx + 1
                    imap[ln] = row
            for idx, row in enumerate(db_items):
                if not isinstance(row, dict):
                    continue
                try:
                    ln = int(row.get("line_no") or idx + 1)
                except (TypeError, ValueError):
                    ln = idx + 1
                base = imap.get(ln, {})
                merged = dict(base)
                for k, v in row.items():
                    if v is None or (isinstance(v, str) and not str(v).strip()):
                        continue
                    if k in ("calc_note", "calc_method"):
                        prev = str(merged.get(k) or "").strip()
                        nv = str(v).strip()
                        if not prev or len(nv) > len(prev):
                            merged[k] = nv
                    elif k not in merged or merged.get(k) in (None, "", "-"):
                        merged[k] = v
                imap[ln] = merged
            ctx["detail_rows"] = [imap[k] for k in sorted(imap.keys())]
        ctx["items"] = db_items

    attach_piece_area_calculation(ctx)
    if ctx.get("piece_area_calculation"):
        quote_obj["piece_area_calculation"] = (
            normalize_piece_area_display(ctx["piece_area_calculation"])
            or ctx["piece_area_calculation"]
        )
