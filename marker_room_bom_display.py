"""板房排刀用量表：后台 BOM 明细展示数据整理（不参与计价）。"""
from __future__ import annotations

import math
import re
from typing import Any

from material_spec_usage_enricher import (
    is_dynamic_rule_usage_token,
    is_explicit_bom_usage_row,
    is_missing_spec_usage_value,
)
from material_spec_usage_enricher import _parse_bool_flag as _usage_ai_flag
from piece_area_table import build_piece_area_calculation, normalize_piece_area_display

_YARD_PER_METER = 1.0936
_DIM_PAIR_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)(?:\s*[×xX*]\s*(\d+(?:\.\d+)?))?",
    re.I,
)
_PIECE_COUNT_IN_LABEL_RE = re.compile(r"[（(]\s*(\d+)\s*片\s*[)）]")
_QTY_PIECES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*片", re.I)
_ROLL_WIDTH_RE = re.compile(
    r"(?:幅宽|门幅|宽幅)\s*[：:]?\s*(\d{2,3})|(\d{2,3})\s*[*×xX]\s*\d+",
    re.I,
)
_ZIP_TRIM_RE = re.compile(r"拉链|拉头|zip", re.I)
_HARDWARE_RE = re.compile(
    r"扣|垫|提手|工艺|包装|纸箱|胶袋|外箱|挂钩|织标|魔术贴|缝纫线|拉链",
    re.I,
)
_FABRIC_RE = re.compile(
    r"牛津|涤纶|里布|无纺|帆布|色丁|塔夫|提花|主布|面料|尼龙布|网布|斜纹|平纹|色织|外料|里料",
    re.I,
)


def _safe_display(value: object, fallback: str = "待核") -> str:
    if value is None:
        return fallback
    if isinstance(value, float):
        if not math.isfinite(value):
            return fallback
        if abs(value - round(value)) < 1e-6:
            return str(int(round(value)))
        return f"{value:g}"
    s = str(value).strip()
    if not s or s.lower() in ("null", "undefined", "nan", "none"):
        return fallback
    if is_dynamic_rule_usage_token(s):
        return fallback
    return s


def _usage_unit(usage: str) -> str:
    u = str(usage or "")
    if re.search(r"码|yd", u, re.I):
        return "码"
    if re.search(r"㎡|m²|m2|平米", u, re.I):
        return "㎡"
    if re.search(r"米|m\b", u, re.I) and "平米" not in u:
        return "米"
    if re.search(r"个|套|条|对|卷|张", u):
        m = re.search(r"(个|套|条|对|卷|张)", u)
        return m.group(1) if m else ""
    return ""


def _parse_amount(row: dict[str, Any]) -> str:
    raw = row.get("amount_text")
    if raw is not None and str(raw).strip():
        return _safe_display(raw, "-")
    try:
        n = float(row.get("amount"))
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(n):
        return "-"
    return f"{n:.2f}"


def is_fabric_detail_row(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    name = str(row.get("name") or "")
    if _ZIP_TRIM_RE.search(name) and not _FABRIC_RE.search(name):
        return False
    if _HARDWARE_RE.search(name) and not _FABRIC_RE.search(name):
        return False
    blob = f"{name} {row.get('spec') or ''}"
    return bool(_FABRIC_RE.search(blob))


def is_auxiliary_detail_row(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    return not is_fabric_detail_row(row)


def _fabric_role_label(name: str, spec: str = "") -> str:
    blob = f"{name} {spec}"
    if re.search(r"里布|里料|内里|内衬", blob):
        return "里料"
    if _FABRIC_RE.search(blob):
        return "外料"
    return "面料"


def _piece_part_key(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _piece_matches_part_filter(piece_name: str, piece_part: str) -> bool:
    pp = str(piece_part or "").strip()
    if not pp or pp in ("待核", "未拆分", "-", "—"):
        return True
    pn = str(piece_name or "")
    tokens = re.split(r"[；;、,/]+", pp)
    for tok in tokens:
        t = tok.strip()
        if not t:
            continue
        core = re.sub(r"[（(].*[)）]", "", t).strip()
        if core and core in pn:
            return True
        if core and core in pp and len(core) >= 2:
            return True
    return False


def _status_badges(row: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    if row.get("_anomaly_pending_review") or row.get("_anomaly_flags"):
        badges.append("待核")
    if row.get("_anomaly_auto_fixed") or str(row.get("correction_rule_source") or "") == "anomaly_auto_fix":
        if "自动修正" not in badges:
            badges.append("自动修正")
    if is_explicit_bom_usage_row(row):
        badges.append("BOM明确")
    elif _usage_ai_flag(row, "usage_ai") or row.get("_usage_display_inferred"):
        badges.append("AI推断")
    if not badges:
        badges.append("正常")
    return badges


def _infer_roll_width_cm(row: dict[str, Any], quote: dict[str, Any], pac: dict[str, Any] | None) -> float | None:
    if isinstance(pac, dict):
        rw = pac.get("roll_width_cm")
        try:
            v = float(rw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    spec = str(row.get("spec") or "")
    m = _ROLL_WIDTH_RE.search(spec)
    if m:
        g = m.group(1) or m.group(2)
        if g:
            return float(g)
    blob = " ".join(
        str(quote.get(k) or "")
        for k in ("structure_text_snapshot", "structure_text", "product_name")
    )
    m2 = _ROLL_WIDTH_RE.search(blob)
    if m2:
        g = m2.group(1) or m2.group(2)
        if g:
            return float(g)
    return None


def _parse_piece_dims(size_text: str) -> tuple[str, str, str, str]:
    raw = str(size_text or "").strip()
    if not raw or raw in ("估算", "待核", "-", "—"):
        return "待核", "待核", "待核", "待核"
    m = _DIM_PAIR_RE.search(raw.replace("*", "×"))
    if not m:
        return "待核", "待核", "待核", "待核"
    a, b = m.group(1), m.group(2)
    c = m.group(3)
    length = _safe_display(a, "待核")
    width = _safe_display(b, "待核")
    occ_l, occ_w = length, width
    if c:
        occ_l = _safe_display(c, occ_l)
    return length, width, occ_l, occ_w


def _piece_qty_display(qty_text: str, piece_name: str) -> str:
    qty = str(qty_text or "").strip()
    m = _QTY_PIECES_RE.search(qty)
    if m:
        return _safe_display(m.group(1), "1")
    m2 = _PIECE_COUNT_IN_LABEL_RE.search(piece_name)
    if m2:
        return _safe_display(m2.group(1), "2")
    if "侧片" in piece_name and "2" in piece_name:
        return "2"
    if qty and re.fullmatch(r"\d+(?:\.\d+)?", qty):
        return _safe_display(qty, "1")
    return "1"


def _cm2_to_usage_value(cm2: float, unit: str, roll_cm: float | None) -> str:
    if cm2 <= 0 or not math.isfinite(cm2):
        return "待核"
    m2 = cm2 / 10_000.0
    if unit == "码":
        if not roll_cm or roll_cm <= 0:
            return "待核"
        len_m = m2 / (roll_cm / 100.0)
        yards = len_m * _YARD_PER_METER
        return f"{yards:.4f}"
    if unit == "米":
        if not roll_cm or roll_cm <= 0:
            return f"{m2:.4f}"
        len_m = m2 / (roll_cm / 100.0)
        return f"{len_m:.4f}"
    return f"{m2:.4f}"


def _resolve_piece_area(quote: dict[str, Any]) -> dict[str, Any] | None:
    pac = quote.get("piece_area_calculation")
    if isinstance(pac, dict) and isinstance(pac.get("rows"), list) and pac["rows"]:
        return normalize_piece_area_display(pac) or pac
    built = build_piece_area_calculation(quote)
    if built:
        return normalize_piece_area_display(built) or built
    return None


def _piece_rows_for_material(
    piece_calc: dict[str, Any] | None,
    *,
    piece_part: str,
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(piece_calc, dict):
        return [], "未拆分"
    rows_in = piece_calc.get("rows")
    if not isinstance(rows_in, list):
        return [], "未拆分"
    out: list[dict[str, Any]] = []
    for raw in rows_in:
        if not isinstance(raw, dict) or raw.get("is_total"):
            continue
        piece = str(raw.get("piece") or "").strip()
        if not piece:
            continue
        if not _piece_matches_part_filter(piece, piece_part):
            continue
        out.append(raw)
    if not out:
        return [], "未拆分"
    pending = any(
        str(r.get("size_text") or "").strip() in ("", "估算", "待核", "-")
        or r.get("inferred")
        for r in out
    )
    return out, ("待核" if pending else "ok")


def _build_piece_display_rows(
    piece_rows: list[dict[str, Any]],
    *,
    unit: str,
    roll_cm: float | None,
    loss_pct: float | None,
) -> list[dict[str, Any]]:
    display: list[dict[str, Any]] = []
    loss = loss_pct if loss_pct is not None and loss_pct > 0 else 15.0
    for raw in piece_rows:
        piece_name = str(raw.get("piece") or "").strip() or "待核"
        length, width, occ_l, occ_w = _parse_piece_dims(str(raw.get("size_text") or ""))
        qty = _piece_qty_display(str(raw.get("qty_text") or ""), piece_name)
        try:
            total_cm2 = float(raw.get("total_area_cm2") or 0)
        except (TypeError, ValueError):
            total_cm2 = 0.0
        with_loss = total_cm2 * (1.0 + loss / 100.0) if total_cm2 > 0 else 0.0
        single = _cm2_to_usage_value(with_loss, unit, roll_cm)
        display.append(
            {
                "piece_name": piece_name,
                "length": length,
                "width": width,
                "occupied_length": occ_l,
                "occupied_width": occ_w,
                "qty": qty,
                "single_marker_usage": single,
                "loss_pct": "",
                "total_marker_usage": "",
                "unit": "",
                "unit_price": "",
                "amount": "",
                "badges": [],
                "is_piece_row": True,
            }
        )
    return display


def _build_fabric_group(
    row: dict[str, Any],
    *,
    quote: dict[str, Any],
    piece_calc: dict[str, Any] | None,
    group_index: int,
) -> dict[str, Any]:
    name = _safe_display(row.get("name"), "-")
    usage_raw = str(row.get("usage") or "").strip()
    if is_missing_spec_usage_value(usage_raw) or is_dynamic_rule_usage_token(usage_raw):
        usage_display = "待核"
    else:
        usage_display = usage_raw
    unit = _usage_unit(usage_display) or "㎡"
    roll_cm = _infer_roll_width_cm(row, quote, piece_calc)
    roll_w = _safe_display(roll_cm, "待核") if roll_cm else "待核"
    marker_w = (
        _safe_display(round(roll_cm * 0.99, 2), roll_w)
        if roll_cm and roll_cm > 0
        else roll_w
    )
    loss_pct_val = None
    if isinstance(piece_calc, dict):
        try:
            loss_pct_val = float(piece_calc.get("loss_rate_pct"))
        except (TypeError, ValueError):
            loss_pct_val = None
    loss_display = (
        f"{loss_pct_val:g}%"
        if loss_pct_val is not None and loss_pct_val > 0
        else "待核"
    )
    piece_part = str(row.get("piece_part") or "").strip()
    piece_rows, split_status = _piece_rows_for_material(piece_calc, piece_part=piece_part)
    badges = _status_badges(row)
    piece_lines = [
        _piece_part_label(r) for r in piece_rows if str(r.get("piece") or "").strip()
    ]
    piece_set_label = "；".join(piece_lines) if piece_lines else (piece_part or "未拆分")

    sub_rows = _build_piece_display_rows(
        piece_rows,
        unit=unit,
        roll_cm=roll_cm,
        loss_pct=loss_pct_val,
    )
    table_rows: list[dict[str, Any]] = []
    for i, pr in enumerate(sub_rows):
        table_rows.append(
            {
                **pr,
                "material_name": name if i == 0 else "",
                "roll_width": roll_w if i == 0 else "",
                "marker_width": marker_w if i == 0 else "",
                "loss_pct": loss_display if i == 0 else "",
                "total_marker_usage": usage_display if i == 0 else "",
                "unit": unit if i == 0 else "",
                "unit_price": _safe_display(row.get("unit_price"), "-") if i == 0 else "",
                "amount": _parse_amount(row) if i == 0 else "",
                "badges": badges if i == 0 else [],
                "is_group_start": i == 0,
                "is_group_end": i == len(sub_rows) - 1,
                "group_index": group_index,
                "material_type": _fabric_role_label(name, str(row.get("spec") or "")),
                "piece_set_key": _piece_part_key(piece_part),
                "piece_set_label": piece_set_label if i == 0 else "",
                "split_status": split_status if i == 0 else "",
            }
        )
    if not table_rows:
        table_rows.append(
            {
                "material_name": name,
                "roll_width": roll_w,
                "marker_width": marker_w,
                "piece_name": "未拆分",
                "length": "待核",
                "width": "待核",
                "occupied_length": "待核",
                "occupied_width": "待核",
                "qty": "-",
                "single_marker_usage": "待核",
                "loss_pct": loss_display,
                "total_marker_usage": usage_display,
                "unit": unit,
                "unit_price": _safe_display(row.get("unit_price"), "-"),
                "amount": _parse_amount(row),
                "badges": badges,
                "is_group_start": True,
                "is_group_end": True,
                "group_index": group_index,
                "material_type": _fabric_role_label(name, str(row.get("spec") or "")),
                "piece_set_key": _piece_part_key(piece_part),
                "piece_set_label": piece_part or "未拆分",
                "split_status": "未拆分",
                "is_piece_row": False,
            }
        )
    return {
        "group_id": f"fabric-{group_index}",
        "material_name": name,
        "material_type": _fabric_role_label(name, str(row.get("spec") or "")),
        "piece_set_key": _piece_part_key(piece_part),
        "piece_set_label": piece_set_label,
        "split_status": split_status,
        "rows": table_rows,
    }


def _piece_part_label(piece_row: dict[str, Any]) -> str:
    piece = str(piece_row.get("piece") or "").strip()
    qty = str(piece_row.get("qty_text") or "").strip()
    if _PIECE_COUNT_IN_LABEL_RE.search(piece):
        return piece
    m = _QTY_PIECES_RE.search(qty)
    if m and "（" not in piece:
        return f"{piece}（{int(float(m.group(1)))}片）"
    if "侧片" in piece and "片" not in piece:
        return f"{piece}（2片）"
    return piece


def _build_auxiliary_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    name = _safe_display(row.get("name"), "-")
    usage = str(row.get("usage") or "").strip()
    if is_missing_spec_usage_value(usage) or is_dynamic_rule_usage_token(usage):
        usage = "待核"
    unit = _usage_unit(usage) or _safe_display(row.get("unit"), "-")
    piece_part = str(row.get("piece_part") or "").strip() or "-"
    return {
        "group_id": f"aux-{index}",
        "material_name": name,
        "material_type": "辅料",
        "roll_width": "-",
        "marker_width": "-",
        "piece_name": piece_part if piece_part not in ("", "-") else name,
        "length": "-",
        "width": "-",
        "occupied_length": "-",
        "occupied_width": "-",
        "qty": _piece_qty_display("", name) if re.search(r"\d+\s*个", usage) else "-",
        "single_marker_usage": usage,
        "loss_pct": "-",
        "total_marker_usage": usage,
        "unit": unit,
        "unit_price": _safe_display(row.get("unit_price"), "-"),
        "amount": _parse_amount(row),
        "badges": _status_badges(row),
        "is_group_start": True,
        "is_group_end": True,
        "group_index": index,
        "piece_set_key": "",
        "piece_set_label": "",
        "split_status": "auxiliary",
        "is_piece_row": False,
        "is_auxiliary": True,
    }


MARKER_ROOM_COLUMNS = (
    "物料名称",
    "幅宽",
    "排刀幅宽",
    "部位名称",
    "长度",
    "宽度",
    "占用长度",
    "占用宽度",
    "件数",
    "单件排刀用量",
    "损耗%",
    "物料排刀总用量",
    "单位",
    "物料单价",
    "物料金额",
    "异常/待核",
)


def build_marker_room_bom_table(quote: dict[str, Any] | None) -> dict[str, Any]:
    """从报价归档构建板房排刀用量表（展示用）。"""
    if not isinstance(quote, dict):
        return {"columns": list(MARKER_ROOM_COLUMNS), "rows": [], "fabric_groups": [], "auxiliary_rows": []}

    detail_rows: list[dict[str, Any]] = []
    for key in ("detail_rows", "items"):
        src = quote.get(key)
        if isinstance(src, list):
            for raw in src:
                if isinstance(raw, dict):
                    detail_rows.append(dict(raw))

    piece_calc = _resolve_piece_area(quote)
    fabric_groups: list[dict[str, Any]] = []
    auxiliary_rows: list[dict[str, Any]] = []
    flat_rows: list[dict[str, Any]] = []

    fabric_idx = 0
    aux_idx = 0
    for row in detail_rows:
        if str(row.get("name") or "").strip() in ("", "-"):
            continue
        if row.get("exclude_from_cost") or str(row.get("recognition_status") or "") == "ignored":
            continue
        if is_fabric_detail_row(row):
            grp = _build_fabric_group(row, quote=quote, piece_calc=piece_calc, group_index=fabric_idx)
            fabric_groups.append(grp)
            flat_rows.extend(grp["rows"])
            fabric_idx += 1
        elif is_auxiliary_detail_row(row):
            ar = _build_auxiliary_row(row, aux_idx)
            auxiliary_rows.append(ar)
            flat_rows.append(ar)
            aux_idx += 1

    return {
        "columns": list(MARKER_ROOM_COLUMNS),
        "rows": flat_rows,
        "fabric_groups": fabric_groups,
        "auxiliary_rows": auxiliary_rows,
        "piece_area_attached": piece_calc is not None,
    }


def enrich_quote_marker_room_bom_table(quote_obj: dict[str, Any]) -> None:
    """后台读取报价时附加板房表（不写库、不改计价）。"""
    if not isinstance(quote_obj, dict):
        return
    quote_obj["marker_room_bom_table"] = build_marker_room_bom_table(quote_obj)
