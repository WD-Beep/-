"""从需求表「结构说明」中抽取用量（码/米），优先于模型默认的「每行 1 码」。"""
from __future__ import annotations

import os
import re
from typing import Any

# ── 尺寸几何推导（可被环境变量微调，无需改代码）──────────────────────────
def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


SHELL_SURFACE_MULT = _env_float("QUOTE_GEOM_SHELL_MULT", 1.32)
FRONT_PANEL_MULT = _env_float("QUOTE_GEOM_FRONT_PANEL_MULT", 1.15)
# 历史里布占比（已弃用全包里布路径）；仅作环境变量兼容读取，勿再乘到全包里布
LINING_SHELL_RATIO = _env_float("QUOTE_GEOM_LINING_AREA_RATIO", 0.22)
LINING_BODY_AREA_FACTOR = _env_float("QUOTE_GEOM_LINING_BODY_SEAM_FACTOR", 1.0)
PEVA_SHELL_RATIO = _env_float("QUOTE_GEOM_PEVA_AREA_RATIO", 0.32)
ZIPPER_OPENING_FRAC = _env_float("QUOTE_GEOM_ZIPPER_OPENING_FRAC", 1.0)  # 1.0=整圈袋口近似
ZIPPER_EXTRA_M = _env_float("QUOTE_GEOM_ZIPPER_EXTRA_M", 0.10)
WEBBING_EXTRA_M = _env_float("QUOTE_GEOM_WEBBING_EXTRA_M", 0.18)
BINDING_EDGE_MULT = _env_float("QUOTE_GEOM_BINDING_EDGE_MULT", 2.65)  # 相对顶部周长的包边总长系数
SMALL_BAG_MAIN_MIN_YD = _env_float("QUOTE_GEOM_SMALL_BAG_MAIN_MIN_YD", 0.32)
SMALL_BAG_LINING_MIN_YD = _env_float("QUOTE_GEOM_SMALL_BAG_LINING_MIN_YD", 0.28)
SMALL_BAG_LINING_MIN_M2 = _env_float("QUOTE_GEOM_SMALL_BAG_LINING_MIN_M2", 0.32)
SMALL_BAG_ZIPPER_EXTRA_CM = _env_float("QUOTE_GEOM_SMALL_BAG_ZIPPER_EXTRA_CM", 2.0)
WEBBING_SEW_ALLOWANCE_CM = _env_float("QUOTE_GEOM_WEBBING_SEW_ALLOWANCE_CM", 5.0)

_YARD_METERS = 0.9144  # m → 线性码换算
_ROLL_WIDTH_RE = re.compile(
    r"(?:幅宽|门幅|宽幅)\s*[：:]?\s*(\d+)\s*(?:CM|厘米|cm)?",
    re.I,
)

# 从片段中剔涨价表达式，避免把「12 元/码」里的数字当成用量
_PRICE_CLUTTER = re.compile(
    r"\d+(?:\.\d+)?\s*元\s*/\s*(?:码²|码|米|个|套|件|条|PCS|pcs|PC|m|Y)\b",
    re.IGNORECASE,
)
_BRACKET_PRICE = re.compile(r"[（(][^）)]*\d+(?:\.\d+)?\s*元[^）)]*[)）]")

# 显式用量：约1.5码、用量：0.4米、单层0.25码²
_EXPLICIT_USAGE = re.compile(
    r"(?:用量|约|各|每片|每件|单层|幅宽)?\s*(\d+(?:\.\d+)?)\s*(码²|㎡|m²|码|yd²|yd|米|m)\b",
    re.IGNORECASE,
)


def _split_structure_segments(text: str) -> list[str]:
    t = (text or "").replace("\r\n", "\n").strip()
    if not t:
        return []
    chunks: list[str] = []
    for ln in t.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        # 单行里用分号/编号拆成小段，便于把「拉链…米」等对到具体物料名
        if "；" in ln or ";" in ln:
            parts = re.split(r"[；;]", ln)
            for p in parts:
                p = p.strip()
                if p:
                    chunks.append(p)
            continue
        # 枚举：「1．外料 xxx  2．里料 xxx」
        numbered = re.split(r"(?<=[.。])\s*(?=\d+\s*[、:：.．])", ln)
        if len(numbered) > 1:
            for p in numbered:
                p = p.strip()
                if p:
                    chunks.append(p)
            continue
        chunks.append(ln)
    return chunks if chunks else [t]


def _strip_for_usage_parse(segment: str) -> str:
    s = _BRACKET_PRICE.sub(" ", segment)
    s = _PRICE_CLUTTER.sub(" ", s)
    s = re.sub(r"/\s*(?:码|米|个|套)\b", " ", s, flags=re.I)
    return s


def _valid_usage_float(num: float, unit: str) -> bool:
    u_raw = str(unit or "").strip()
    if num <= 0:
        return False
    ul = u_raw.lower()
    # 面积单价常见按 码² / ㎡ 报价
    if "²" in u_raw or "㎡" in u_raw or "m²" == ul or "yd²" in ul:
        return 0.005 <= num <= 80.0
    if "码" in u_raw and "²" not in u_raw:
        return 0.02 <= num <= 8.0
    if "米" in u_raw or ul == "m" or ul == "yd":
        return 0.02 <= num <= 30.0
    return False


def _is_missing_usage(text: str) -> bool:
    t = (text or "").strip()
    return t == "" or t == "-"


def _extract_usage_candidates(clean_seg: str) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    seen: set[tuple[float, str]] = set()
    for m in _EXPLICIT_USAGE.finditer(clean_seg):
        n, u = float(m.group(1)), m.group(2)
        if _valid_usage_float(n, u):
            key = (round(n, 4), u)
            if key not in seen:
                seen.add(key)
                out.append((n, u))
    for m in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(码²|㎡|m²|码|yd²|yd|米|m)\b",
        clean_seg,
        flags=re.I,
    ):
        n, u = float(m.group(1)), m.group(2)
        if _valid_usage_float(n, u):
            key = (round(n, 4), u)
            if key not in seen:
                seen.add(key)
                out.append((n, u))
    return out


def _format_usage(num: float, unit_raw: str) -> str:
    ur = str(unit_raw or "").strip()
    ul = ur.lower()
    qdisp = f"{round(float(num), 2):.2f}"
    # 规范化展示单位（与 kimi_client._looks_like_usage_quantity_text 对齐）
    if "²" in ur or "㎡" in ur or ul in {"m²", "yd²"} or ur.lower() == "yd":
        udisp = "码²" if "码" in ur or "yd" in ul else "㎡"
        return f"{qdisp}{udisp}"
    if "米" in ur or ul == "m":
        return f"{qdisp}米"
    return f"{qdisp}码"


# C 区格子里括号备注常见「用量1.5码」「约0.35码²」或与单价同写
_CELL_USAGE_BLOB_PATTERN = re.compile(
    r"(?:用量|单件(?:用)?量|每件(?:用)?量|用料|面积约|单层|幅宽)"
    r"\s*[：:.]?\s*(\d+(?:\.\d+)?)\s*(码²|㎡|m²|码|yd|米|m)\b",
    re.I,
)


_PIECE_COUNT_CELL = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(个|只|粒|颗|枚|PCS|pcs|Pc|PC|件)\s*$",
    re.I,
)
_PIECE_COUNT_PREFIX = re.compile(
    r"^(?:用量|单件(?:用)?量|每件(?:用)?量|数量)\s*[：:.]?\s*(\d+(?:\.\d+)?)\s*"
    r"(个|只|粒|颗|枚|PCS|pcs|Pc|PC|件)\s*$",
    re.I,
)


def piece_count_usage_from_cell_note(note: str) -> str | None:
    """C 区单元格括号里纯件数文案，如「3个」「2PCS」，用于锁定拉链头/五金颗数。"""
    t = str(note or "").strip()
    if not t:
        return None
    m = _PIECE_COUNT_CELL.fullmatch(t)
    if not m:
        m = _PIECE_COUNT_PREFIX.fullmatch(t)
    if not m:
        return None
    num = float(m.group(1))
    _ = str(m.group(2) or "").strip()
    if not (0 < num <= 5000):
        return None
    num_s = str(int(num)) if num == int(num) else str(num).rstrip("0").rstrip(".")
    # 明细表/UI 常以 PCS 展示件数，与拉链米数区分
    return f"{num_s}PCS"


def usage_hint_from_bracket(note: str, inline_hint: str) -> str | None:
    """从需求表单元格括号说明 / 标价尾巴上抽用量，先于结构说明段落匹配。"""
    blob = f"{note or ''} {inline_hint or ''}".strip()
    if not blob:
        return None
    pc_usage = piece_count_usage_from_cell_note(blob)
    if pc_usage:
        return pc_usage
    clean = _strip_for_usage_parse(blob)
    m = _CELL_USAGE_BLOB_PATTERN.search(clean)
    if m:
        n, u = float(m.group(1)), m.group(2)
        if _valid_usage_float(n, u):
            return _format_usage(n, u)
    cands = _extract_usage_candidates(clean)
    if not cands:
        return None
    n0, u0 = cands[0]
    return _format_usage(n0, u0)


def _name_tokens(name: str) -> set[str]:
    s = (name or "").strip()
    if not s:
        return set()
    tok: set[str] = set()
    patterns = [
        r"FJ[- ]?[A-Z0-9*]+",
        r"\d+[#＃][\u4e00-\u9fffA-Za-z0-9]{0,8}",
        r"\d+D",
        r"PEVA|X[- ]?PAC|XPAC|YKK|210D|400D|尼龙|涤纶|水洗|网布|织带|拉链|拉头|捆边|包边|细纹|前舱|主仓|开口",
        r"[\u4e00-\u9fff]{2,5}",
    ]
    for pat in patterns:
        for m in re.finditer(pat, s, re.I):
            g = m.group(0).strip()
            if len(g) >= 2:
                tok.add(g.upper() if g.isascii() else g)
    return {t for t in tok if len(t) >= 2}


def _segment_score(name: str, segment: str) -> int:
    toks = _name_tokens(name)
    if not toks:
        return 0
    seg_l = segment.lower()
    score = 0
    for t in toks:
        if len(t) >= 2 and t.lower() in seg_l:
            score += 2 if len(t) >= 3 else 1
        elif len(t) >= 4 and t[:4].lower() in seg_l:
            score += 1
    if re.search(r"5\s*#|#5", name, re.I) and re.search(r"5\s*#|#?\s*5\s*号", segment, re.I):
        score += 3
    if "fj-114" in name.lower() and "fj-114" in seg_l:
        score += 3
    if "peva" in name.lower() and "peva" in seg_l:
        score += 3
    if "210d" in name.lower() and "210" in seg_l and "涤纶" in seg_l:
        score += 2
    return score


def _parse_body_dimensions_cm(text: str) -> dict[str, float]:
    """从「长22cm,宽12cm，高20cm」补 L/W/H（厘米）。"""
    out: dict[str, float] = {}
    if not text:
        return out
    m = re.search(
        r"长\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米).*?"
        r"宽\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米).*?"
        r"高\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)",
        text,
        re.I | re.S,
    )
    if m:
        out["LCM"] = float(m.group(1))
        out["WCM"] = float(m.group(2))
        out["HCM"] = float(m.group(3))
    return out


def _merge_product_size(
    base: dict[str, float] | None,
    structure_text: str,
) -> dict[str, float]:
    merged = dict(base or {})
    extra = _parse_body_dimensions_cm(structure_text)
    for k, v in extra.items():
        if v > 0 and (k not in merged or float(merged.get(k) or 0) <= 0):
            merged[k] = v
    return merged


def _dims_lwh_cm(product_size: dict[str, float] | None) -> tuple[float, float, float]:
    ps = product_size or {}
    l_ = float(ps.get("LCM") or ps.get("lcm") or 0)
    w_ = float(ps.get("WCM") or ps.get("wcm") or 0)
    h_ = float(ps.get("HCM") or ps.get("hcm") or 0)
    return l_, w_, h_


def _has_box_dims(product_size: dict[str, float] | None) -> bool:
    l_, w_, h_ = _dims_lwh_cm(product_size)
    return l_ > 0 and w_ > 0 and h_ > 0


def _shell_surface_m2(l_cm: float, w_cm: float, h_cm: float) -> float:
    """外轮廓展开面积的粗近似：以大面周长 × 袋深为主（软包），避免长方体表面积量级过小."""
    lw = float(l_cm) * float(w_cm)
    lh = float(l_cm) * float(h_cm)
    wh = float(w_cm) * float(h_cm)
    box_m2 = max(8e-4, 2.0 * (lw + lh + wh) / 1_000_000.0)
    perim_m = 2.0 * (float(l_cm) + float(w_cm)) / 100.0
    depth_m = float(h_cm) / 100.0
    tube_k = _env_float("QUOTE_GEOM_TUBE_DEPTH_K", 2.35)
    tube_m2 = max(1e-4, tube_k * perim_m * depth_m)
    merged = round(max(box_m2 * SHELL_SURFACE_MULT * 1.08, tube_m2), 5)
    gmult = _env_float("QUOTE_GEOM_GLOBAL_YIELD_MULT", 1.05)
    return round(merged * max(1.0, gmult), 5)


def _front_face_m2(l_cm: float, w_cm: float) -> float:
    return round(FRONT_PANEL_MULT * 2.0 * l_cm * w_cm / 1_000_000.0, 5)


def _resolve_piece_area_calculation(
    piece_area_calculation: dict[str, Any] | None,
    *,
    product_size: dict[str, float] | None,
    structure_text: str,
    items: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if isinstance(piece_area_calculation, dict):
        try:
            from piece_area_table import _is_complete_piece_area_calc

            if _is_complete_piece_area_calc(piece_area_calculation):
                return piece_area_calculation
        except ImportError:
            return piece_area_calculation
    if not items and not _has_box_dims(product_size):
        return None
    try:
        from piece_area_table import attach_piece_area_calculation

        ctx: dict[str, Any] = {
            "product_size": product_size or {},
            "structure_text_snapshot": structure_text,
            "items": items or [],
        }
        return attach_piece_area_calculation(ctx)
    except Exception:
        return None


def _shared_body_fabric_area_m2(
    l_cm: float,
    w_cm: float,
    h_cm: float,
    piece_calc: dict[str, Any] | None,
) -> tuple[float, str, float | None]:
    """主料与全包里布共用的㎡基准：完整裁片表优先，否则包身外包络。"""
    shell = _shell_surface_m2(l_cm, w_cm, h_cm)
    try:
        from piece_area_table import _is_complete_piece_area_calc, body_piece_area_m2_with_loss

        if _is_complete_piece_area_calc(piece_calc):
            piece_m2 = body_piece_area_m2_with_loss(piece_calc)
            if piece_m2 is not None and piece_m2 > 0:
                return round(piece_m2, 5), "piece", shell
    except ImportError:
        pass
    return shell, "shell", None


def _body_area_basis_note(
    body_m2: float,
    basis: str,
    shell_ref: float | None,
    l_cm: float,
    w_cm: float,
    h_cm: float,
) -> str:
    if basis == "piece":
        note = f"裁片面积表合计（含损耗）≈{body_m2:.3f}㎡"
        if shell_ref is not None and shell_ref > body_m2 * 1.05:
            note += f"，包身外包络参考≈{shell_ref:.3f}㎡"
        return note
    return (
        f"包身外包络≈{body_m2:.3f}㎡（成品{l_cm:.0f}×{w_cm:.0f}×{h_cm:.0f}cm，"
        f"展开系数{SHELL_SURFACE_MULT:g}量级）"
    )


def _name_join_for_match(name: str, spec: str) -> str:
    return f"{name or ''} {spec or ''}".strip()


def _roll_width_cm(structure_or_row_blob: str) -> float:
    blob = structure_or_row_blob or ""
    m = _ROLL_WIDTH_RE.search(blob)
    if not m:
        return 0.0
    try:
        val = float(m.group(1))
    except ValueError:
        return 0.0
    return val if 20 < val <= 260 else 0.0


def _unit_price_signals_area(price: str) -> bool:
    p = str(price or "").strip()
    pl = p.lower()
    return "码²" in p or "㎡" in p or "m²" in pl


def _unit_price_signals_roll_linear_yards(price: str) -> bool:
    p = str(price or "").strip()
    if not p or _unit_price_signals_area(p):
        return False
    pl = p.lower()
    if "/y" in pl or "/yd" in pl:
        return True
    return bool(re.search(r"(?:/\s*|元\s*/\s*)码\b", p) and "码²" not in p)


def _price_is_bare_number(price: str) -> bool:
    """知识库常见「单价参考」仅数字：主料线性码时需要门幅才可折算."""
    p = str(price or "").strip().replace(",", "").replace("，", "")
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", p))


def _effective_roll_width_cm(blob: str, *, allow_default: bool) -> float:
    w = _roll_width_cm(blob or "")
    if w > 0:
        return w
    if allow_default:
        dw = _env_float("QUOTE_GEOM_DEFAULT_ROLL_CM", 150)
        return dw if 20 < dw <= 260 else 150.0
    return 0.0


def _is_small_soft_bag(product_size: dict[str, float] | None, structure_text: str = "") -> bool:
    if not _has_box_dims(product_size):
        return False
    l_, w_, h_ = _dims_lwh_cm(product_size)
    largest = max(l_, w_, h_)
    smallest = min(l_, w_, h_)
    text = structure_text or ""
    bag_hint = any(k in text for k in ("斜挎", "小包", "腰包", "收纳包", "便当", "午餐", "手拿", "零钱"))
    return largest <= 32 and smallest <= 16 and (bag_hint or (l_ * w_ * h_) <= 7000)


def _yard_usage_floor_for_small_bag(raw_yds: float, minimum: float) -> float:
    if raw_yds <= 0:
        return minimum
    return round(max(raw_yds, minimum), 4)


def _small_bag_zipper_usage(row: dict[str, Any], ps: dict[str, float], structure_text: str) -> str | None:
    if not _is_small_soft_bag(ps, structure_text):
        return None
    l_, w_, _ = _dims_lwh_cm(ps)
    zipper_cm = max(18.0, min(36.0, max(l_, w_) + SMALL_BAG_ZIPPER_EXTRA_CM))
    price = str(row.get("unit_price") or "").strip()
    if _unit_price_signals_roll_linear_yards(price) or _price_is_bare_number(price):
        return _format_usage(round(zipper_cm / 100.0 / _YARD_METERS, 4), "码")
    return f"{round(zipper_cm / 100.0, 3)}米"


def _cm_length_usage_from_row(row: dict[str, Any]) -> str | None:
    blob = " ".join(
        str(row.get(k) or "")
        for k in ("usage", "spec", "calc_note", "calc_method", "name")
    )
    if not blob.strip():
        return None
    m = re.search(
        r"(?:约|大约|长度|长)?\s*(\d+(?:\.\d+)?)\s*[-~～至到]\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)",
        blob,
    )
    if m:
        hi = max(float(m.group(1)), float(m.group(2)))
        return f"{round((hi + WEBBING_SEW_ALLOWANCE_CM) / 100.0, 2):.2f}米"
    m = re.search(r"(?:约|大约|长度|长)?\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)\s*(?:长)?", blob)
    if m:
        cm = float(m.group(1))
        if 10 <= cm <= 400:
            return f"{round((cm + WEBBING_SEW_ALLOWANCE_CM) / 100.0, 2):.2f}米"
    return None


_PLACEHOLDER_1YD = re.compile(r"^[~～≈]?\s*1(?:\.0)?\s*码\s*$", re.I)
_PLACEHOLDER_1YD2 = re.compile(r"^[~～≈]?\s*1(?:\.0)?\s*码²\s*$", re.I)
_PLACEHOLDER_1SET = re.compile(r"^[~～≈]?\s*1(?:\.0)?\s*(?:套|SET)\s*$", re.I)
_PLACEHOLDER_1PCS = re.compile(r"^[~～≈]?\s*1(?:\.0)?\s*(?:个|只|PCS|PC)\s*$", re.I)
_HAS_NUM_UNIT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:码²|㎡|m²|码|yd|米|m|条|套|个|只|PCS|PC)\b",
    re.I,
)


def _needs_geometry_fill(row: dict[str, Any]) -> bool:
    """占位或缺失用量且未强行锁定时，可用尺寸/模板补全。"""
    if row.get("_skip_geometry_derive"):
        return False
    u = str(row.get("usage") or "").strip()
    if u in ("-", ""):
        return True
    if _HAS_NUM_UNIT.search(u) and not (
        _PLACEHOLDER_1YD.match(u)
        or _PLACEHOLDER_1YD2.match(u)
        or _PLACEHOLDER_1SET.match(u)
        or _PLACEHOLDER_1PCS.match(u)
    ):
        return False
    if _PLACEHOLDER_1YD.match(u) or _PLACEHOLDER_1YD2.match(u):
        return True
    if _PLACEHOLDER_1SET.match(u) or _PLACEHOLDER_1PCS.match(u):
        return True
    return False


_MAIN_FAB_PAT = re.compile(
    r"(外料|主面|主面料|外壳|底料|面料"
    r"|FJ|PT[- ]?\d+|DCF|DCH"
    r"|ULTRA|X[- ]?PAC|XPAC|VX\d+|粗苯"
    r"|尼龙布|水洗尼龙|牛津|格子布"
    r"|210D|400D|600D|弹道)",
    re.I,
)
_LINING_PAT = re.compile(r"(里料|里布|内里|内里布|\d*D?\s*(?:涤纶|涤|里)|内衬)", re.I)
_FRONT_POCKET_LINING_PAT = re.compile(r"(前舱|前身|前天|前门)", re.I)
_PEVA_PAT = re.compile(r"(PEVA|铝膜|复合膜|保温材料)", re.I)
_ZIP_PAT = re.compile(r"(拉链|拉链带|ZIP|ZIPPER)", re.I)
_WEBBING_PAT = re.compile(r"(织带|肩带|背带|拎带)", re.I)
_BINDING_PAT = re.compile(r"(包边|捆边|捆条|滚边)", re.I)
_PRINT_LABEL_PAT = re.compile(r"(印花|印刷|数码|丝印|皮标|LOGO|logo|标牌|织唛|洗唛|唛)", re.I)
_HARDWARE_ROW_PAT = re.compile(
    r"(弹簧圈|圈口扣|圆心弹簧|"
    r"口字扣|矩形扣|"  # 「口」「日」易被误切，单行写完整
    r"日字扣|梯扣|"  # 日字扣
    r"D扣|D环|马蹄扣|拉绊)",
    re.I,
)


def _effective_hardware_catalog(structure_text: str) -> dict[str, int]:
    """结构里显写颗数优先，否则按袋型关键字给默认套件。"""
    text = structure_text or ""
    base = _hardware_defaults_from_bag_keywords(text)
    for key, qty in _parse_hardware_counts_explicit(text).items():
        base[key] = qty
    return _normalize_hw_catalog({k: v for k, v in base.items() if v > 0})


def _hardware_defaults_from_bag_keywords(text: str) -> dict[str, int]:
    """按业务常见款给默认五金颗数（仅无显式数字时兜底）。"""
    out: dict[str, int] = {}
    if not text:
        return out
    if "便当" in text or ("午餐" in text and ("包" in text or "袋" in text)):
        # 与销售便签对齐的可调缺省（可用环境变量整体关掉：QUOTE_GEOM_DEFAULT_HW=0）
        if str(os.environ.get("QUOTE_GEOM_DEFAULT_HW", "1")).strip() not in (
            "0",
            "false",
            "no",
        ):
            out["圆心弹簧"] = 2
            out["D扣"] = 2
            out["口字扣"] = 4
            out["日字扣"] = 1
    return out


def _parse_hardware_counts_explicit(text: str) -> dict[str, int]:
    """从「口字扣4个」「2×口字扣」等句式抽颗数。"""
    out: dict[str, int] = {}
    t = text or ""
    if not t.strip():
        return out
    specs: list[tuple[str, re.Pattern[str]]] = [
        ("口字扣", re.compile(r"(?:口字扣|矩形扣)[^0-9\n]{0,14}(\d+)\s*[个颗只PCS]", re.I)),
        ("口字扣", re.compile(r"(\d+)\s*[×*x]\s*(?:口字扣|矩形扣)", re.I)),
        ("日字扣", re.compile(r"(?:日字扣|梯扣)[^0-9\n]{0,14}(\d+)\s*[个颗只PCS]", re.I)),
        ("日字扣", re.compile(r"(\d+)\s*[×*x]\s*(?:日字扣|梯扣)", re.I)),
        ("D扣", re.compile(r"(?:D扣|D环)[^0-9\n]{0,14}(\d+)\s*[个颗只PCS]", re.I)),
        ("D扣", re.compile(r"(\d+)\s*[×*x]\s*(?:D扣|D环)", re.I)),
        ("圆心弹簧", re.compile(r"(?:圆心弹簧圈口扣|圆心弹簧|弹簧圈(?:口)?扣)[^0-9\n]{0,24}(\d+)\s*[个颗只PCS]", re.I)),
        ("圆心弹簧", re.compile(r"(\d+)\s*[×*x]\s*(?:圆心弹簧|弹簧圈圈口扣|弹簧圈口扣)", re.I)),
        ("弹簧圈扣", re.compile(r"弹簧圈[^0-9\n]{0,14}(\d+)\s*[个颗只PCS]", re.I)),
    ]
    seen_spans: set[tuple[int, int]] = set()

    def _take(m: re.Match[str], canon: str) -> None:
        try:
            n = int(m.group(1))
        except (TypeError, IndexError, ValueError):
            return
        if n <= 0 or n > 999:
            return
        span = m.span()
        if span in seen_spans:
            return
        seen_spans.add(span)
        out[canon] = max(out.get(canon) or 0, n)

    for canon, rx in specs:
        for m in rx.finditer(t):
            _take(m, canon)
    return out


def _normalize_hw_catalog(cat: dict[str, int]) -> dict[str, int]:
    """合并同源键（弹簧圈扣 → 圆心弹簧颗数累加语义上取最大）。"""
    if not cat:
        return {}
    out = dict(cat)
    if "弹簧圈扣" in out:
        qq = max(out.get("圆心弹簧") or 0, out.pop("弹簧圈扣"))
        out["圆心弹簧"] = max(out.get("圆心弹簧") or 0, qq)
    return {k: v for k, v in out.items() if v > 0}


def _hardware_qty_from_row(hint: str, hw_cat: dict[str, int]) -> int | None:
    if not hw_cat:
        return None
    h = hint or ""

    def has(*keys: str) -> bool:
        return any(k in h for k in keys)

    if ("口字扣" in h or "矩形扣" in h) and hw_cat.get("口字扣"):
        return hw_cat["口字扣"]
    if "日字扣" in h or "梯扣" in h:
        return hw_cat.get("日字扣")
    if "D扣" in h or "D环" in h:
        return hw_cat.get("D扣")
    if has("圆心", "弹簧圈", "圈口扣") and hw_cat.get("圆心弹簧"):
        return hw_cat["圆心弹簧"]
    # 兜底：英文名
    return None


def _calc_note_safe_to_fill(existing: str) -> bool:
    t = str(existing or "").strip()
    if not t:
        return True
    trivial = (
        "请对照",
        "AI 估算",
        "AI估计",
        "未载入",
        "数据源不含",
        "未见「计算方式」",
        "构件分项未载入",
        "用量为 AI",
        "本条用量",
        "占位",
    )
    low = t.lower()
    return any(k.lower() in low for k in trivial)


def _explain_geometry_calc_note(
    row: dict[str, Any],
    geo_usage: str,
    ps: dict[str, float],
    structure_blob: str,
    piece_calc: dict[str, Any] | None = None,
) -> str:
    """几何推导用量时给出可核对的一句话（对齐「单个用量·算法」摘要），非业务员排版损耗."""
    nh = _name_join_for_match(str(row.get("name") or ""), str(row.get("spec") or "")).strip()
    if not nh or not _has_box_dims(ps):
        return ""
    l_, w_, h_ = _dims_lwh_cm(ps)
    upt = str(row.get("unit_price") or "").strip()
    blob = f"{structure_blob or ''}\n{nh}".strip()

    if _PEVA_PAT.search(nh):
        shell = _shell_surface_m2(l_, w_, h_)
        pv = round(max(0.055, shell * PEVA_SHELL_RATIO), 4)
        return (
            f"PEVA按包身外包络≈{shell:.3f}㎡×覆盖系数{PEVA_SHELL_RATIO:.2f}"
            f"≈{pv:.3f}㎡，取{geo_usage}"
        )

    if _LINING_PAT.search(nh) and (_FRONT_POCKET_LINING_PAT.search(nh)):
        fv = max(0.04, _front_face_m2(l_, w_) * 0.55)
        if _is_small_soft_bag(ps, structure_blob):
            fv = max(fv, SMALL_BAG_LINING_MIN_M2)
        return (
            f"前舱里布按正面{l_:.0f}×{w_:.0f}cm×覆盖系数取样，面积约{fv:.3f}㎡，取{geo_usage}"
        )

    if _LINING_PAT.search(nh) and ("拉链" not in nh):
        body_m2, basis, shell_ref = _shared_body_fabric_area_m2(l_, w_, h_, piece_calc)
        seam_k = min(1.08, max(1.0, LINING_BODY_AREA_FACTOR))
        fv2 = max(0.05, body_m2 * seam_k)
        if _is_small_soft_bag(ps, structure_blob):
            if _unit_price_signals_roll_linear_yards(upt) or _price_is_bare_number(upt):
                return f"里布按小包内衬裁片、翻口和缝份最低取量，取{geo_usage}"
            fv2 = max(fv2, SMALL_BAG_LINING_MIN_M2)
        basis_note = _body_area_basis_note(body_m2, basis, shell_ref, l_, w_, h_)
        seam_txt = f"×缝份系数{seam_k:g}" if abs(seam_k - 1.0) > 0.01 else ""
        return (
            f"里布与主料共用{basis_note}{seam_txt}≈{fv2:.3f}㎡，取{geo_usage}"
        )

    if _MAIN_FAB_PAT.search(nh) and not _ZIP_PAT.search(nh):
        body_m2, basis, shell_ref = _shared_body_fabric_area_m2(l_, w_, h_, piece_calc)
        bare = _price_is_bare_number(upt)
        lin_ex = _unit_price_signals_roll_linear_yards(upt)
        if _unit_price_signals_area(upt) and not (lin_ex or bare):
            basis_note = _body_area_basis_note(body_m2, basis, shell_ref, l_, w_, h_)
            return f"主料按{basis_note}，按㎡单价核对"
        wm = _roll_width_cm(blob)
        bare = _price_is_bare_number(upt)
        lin_ex = _unit_price_signals_roll_linear_yards(upt)
        wm_eff = wm if wm > 0 else (
            _effective_roll_width_cm(blob, allow_default=bare or lin_ex)
        )
        if lin_ex or bare:
            if wm_eff <= 0:
                wm_eff = _effective_roll_width_cm(blob, allow_default=True)
            len_m = max(1e-6, body_m2 / (wm_eff / 100.0))
            yds = len_m / _YARD_METERS
            tag = "默认门幅" if wm <= 0 else "门幅"
            basis_note = _body_area_basis_note(body_m2, basis, shell_ref, l_, w_, h_)
            if _is_small_soft_bag(ps, structure_blob):
                floored = _yard_usage_floor_for_small_bag(yds, SMALL_BAG_MAIN_MIN_YD)
                if floored > yds + 0.01:
                    return (
                        f"主料{basis_note}÷{tag}{wm_eff:.0f}cm≈{round(yds, 4)}码；"
                        f"小包裁片分散、缝份和排版损耗按最低取量，取{geo_usage}"
                    )
            return (
                f"主料按{basis_note}÷{tag}{wm_eff:.0f}cm"
                f"≈{len_m:.3f}m÷0.9144≈{round(yds, 4)}码，取{geo_usage}"
            )

    if "拉链" in nh or ("zip" in nh.lower()):
        if _is_small_soft_bag(ps, structure_blob):
            zipper_cm = max(18.0, min(36.0, max(l_, w_) + SMALL_BAG_ZIPPER_EXTRA_CM))
            return f"拉链按小包主开口有效长度≈{zipper_cm:.0f}cm，加端部余量后取{geo_usage}"
        zm = ZIPPER_OPENING_FRAC * 2.0 * (l_ + w_) / 100.0 + ZIPPER_EXTRA_M
        zm = round(max(0.12, zm), 3)
        return (
            f"拉链按袋口周长≈2×({l_:.0f}+{w_:.0f})cm×开口系数{ZIPPER_OPENING_FRAC:g}"
            f"+端部余量{ZIPPER_EXTRA_M:g}m≈{zm}米，取{geo_usage}"
        )

    if _WEBBING_PAT.search(nh):
        explicit_cm = _cm_length_usage_from_row(row)
        if explicit_cm:
            return f"织带按表内长度区间换算为米并加车缝余量，取{geo_usage}"
        wm = round(max(0.35, 2.0 * (l_ + h_) / 100.0 + WEBBING_EXTRA_M), 3)
        return (
            f"织带/背带按背负相关边≈2×({l_:.0f}+{h_:.0f})cm+接缝余量≈{wm}米，取{geo_usage}"
        )

    if _BINDING_PAT.search(nh):
        top = 2.0 * (l_ + w_) / 100.0
        bm = round(max(0.45, BINDING_EDGE_MULT * top), 3)
        return (
            f"包边按袋口周长≈2×({l_:.0f}+{w_:.0f})cm×包边系数{BINDING_EDGE_MULT:g}"
            f"≈{bm}米，取{geo_usage}"
        )

    if _HARDWARE_ROW_PAT.search(nh):
        return f"五金颗数按结构说明枚举/成套位置核对，取{geo_usage}"

    return ""


def _try_derive_geometry_usage(
    row: dict[str, Any],
    product_size: dict[str, float] | None,
    hw_cat: dict[str, int],
    structure_blob: str = "",
    piece_calc: dict[str, Any] | None = None,
) -> str | None:
    if not _has_box_dims(product_size):
        return None
    l_, w_, h_ = _dims_lwh_cm(product_size)
    hint_raw = _name_join_for_match(str(row.get("name") or ""), str(row.get("spec") or ""))
    if not hint_raw.strip():
        return None
    nh = hint_raw.strip()

    if _PEVA_PAT.search(nh):
        shell = _shell_surface_m2(l_, w_, h_)
        pv = round(max(0.055, shell * PEVA_SHELL_RATIO), 4)
        return _format_usage(pv, "㎡")

    if _LINING_PAT.search(nh) and (_FRONT_POCKET_LINING_PAT.search(nh)):
        fv = round(max(0.04, _front_face_m2(l_, w_) * 0.55), 5)
        if _is_small_soft_bag(product_size, structure_blob):
            fv = max(fv, SMALL_BAG_LINING_MIN_M2)
        return _format_usage(fv, "㎡")

    if _LINING_PAT.search(nh) and ("拉链" not in nh):
        body_m2, _, _ = _shared_body_fabric_area_m2(l_, w_, h_, piece_calc)
        seam_k = min(1.08, max(1.0, LINING_BODY_AREA_FACTOR))
        fv2 = round(max(0.05, body_m2 * seam_k), 5)
        if _is_small_soft_bag(product_size, structure_blob):
            upt = str(row.get("unit_price") or "").strip()
            if _unit_price_signals_roll_linear_yards(upt) or _price_is_bare_number(upt):
                return _format_usage(SMALL_BAG_LINING_MIN_YD, "码")
            fv2 = max(fv2, SMALL_BAG_LINING_MIN_M2)
        return _format_usage(fv2, "㎡")

    if _MAIN_FAB_PAT.search(nh) and not _ZIP_PAT.search(nh):
        upt = str(row.get("unit_price") or "").strip()
        body_m2, _, _ = _shared_body_fabric_area_m2(l_, w_, h_, piece_calc)
        blob = f"{structure_blob or ''}\n{nh}".strip()
        bare = _price_is_bare_number(upt)
        lin_ex = _unit_price_signals_roll_linear_yards(upt)
        if _unit_price_signals_area(upt) and not (lin_ex or bare):
            return _format_usage(body_m2, "㎡")
        wm = _roll_width_cm(blob)
        wm_eff = wm if wm > 0 else _effective_roll_width_cm(blob, allow_default=bare or lin_ex)
        if lin_ex or bare:
            if wm_eff <= 0:
                wm_eff = _effective_roll_width_cm(blob, allow_default=True)
            len_m = max(1e-6, body_m2 / (wm_eff / 100.0))
            yds = len_m / _YARD_METERS
            if _is_small_soft_bag(product_size, structure_blob):
                yds = _yard_usage_floor_for_small_bag(yds, SMALL_BAG_MAIN_MIN_YD)
            if 0.025 <= yds <= 50:
                return _format_usage(round(yds, 4), "码")
        return None

    if "拉链" in nh or ("zip" in nh.lower()):
        small_zipper = _small_bag_zipper_usage(row, product_size or {}, structure_blob)
        if small_zipper:
            return small_zipper
        zm = ZIPPER_OPENING_FRAC * 2.0 * (l_ + w_) / 100.0 + ZIPPER_EXTRA_M
        zm = round(max(0.12, zm), 3)
        return f"{zm}米"

    if _WEBBING_PAT.search(nh):
        explicit_cm = _cm_length_usage_from_row(row)
        if explicit_cm:
            return explicit_cm
        wm = round(max(0.35, 2.0 * (l_ + h_) / 100.0 + WEBBING_EXTRA_M), 3)
        return f"{wm}米"

    if _BINDING_PAT.search(nh):
        top = 2.0 * (l_ + w_) / 100.0
        bm = round(max(0.45, BINDING_EDGE_MULT * top), 3)
        return f"{bm}米"

    if _PRINT_LABEL_PAT.search(nh):
        qty = _print_label_yard_usage(l_, w_, h_, structure_blob)
        if qty is not None:
            return _format_usage(qty, "码")

    if _HARDWARE_ROW_PAT.search(nh):
        hc = _normalize_hw_catalog(dict(hw_cat))
        q = _hardware_qty_from_row(nh, hc)
        if q is not None and q > 0:
            return f"{q}个"
    return None


def _print_label_yard_usage(l_: float, w_: float, h_: float, structure_blob: str) -> float | None:
    text = structure_blob or ""
    dims: list[tuple[float, float]] = []
    for m in re.finditer(
        r"(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)\s*(mm|MM|毫米|cm|CM|厘米)?",
        text,
    ):
        a, b = float(m.group(1)), float(m.group(2))
        unit = (m.group(3) or "").lower()
        if unit in {"mm", "毫米"}:
            a, b = a / 10.0, b / 10.0
        dims.append((a, b))
    if dims:
        a, b = _pick_print_dims_cm(dims, text)
        area_m2 = max(0.001, (a * b) / 10000.0)
    else:
        area_m2 = max(0.005, (l_ * h_) / 10000.0 * 0.55)
    yds = area_m2 / (1.5 * _YARD_METERS)
    return round(max(0.03, min(0.18, yds)), 4)


def _pick_print_dims_cm(dims: list[tuple[float, float]], text: str) -> tuple[float, float]:
    low = text.lower()
    if any(k in text for k in ("皮标", "小标", "标牌", "唛")):
        return min(dims, key=lambda pair: pair[0] * pair[1])
    if any(k in text for k in ("满版", "正面", "主图", "数码", "印花", "印刷")):
        product_like = [p for p in dims if 20 <= max(p) <= 60 and 5 <= min(p) <= 40]
        if product_like:
            return max(product_like, key=lambda pair: pair[0] * pair[1])
    return max(dims, key=lambda pair: pair[0] * pair[1])


def _pick_usage_for_role(
    role: str,
    segment: str,
    candidates: list[tuple[float, str]],
    *,
    product_size: dict[str, float] | None,
) -> str | None:
    if not candidates:
        return None
    rl = (role or "").lower()
    # 拉链：优先 米（结构说明常为「拉链开口 x 米」）
    if any(k in rl for k in ("拉链", "zip")):
        for n, u in candidates:
            ul = str(u).lower()
            if "米" in u or ul == "m":
                return _format_usage(n, "米")
        return _fallback_zipper_meters(role, product_size)
    # 织带 / 绳
    if any(k in rl for k in ("织带", "肩带", "绳", "webbing")):
        for n, u in candidates:
            if "码" in u:
                return _format_usage(n, "码")
        for n, u in candidates:
            if "米" in u:
                return _format_usage(n, "米")
    # 主料/布料：若有面积用量优先码² / ㎡（与标价单位一致时再算金额）
    if any(k in rl for k in ("外料", "里料", "辅料", "面料", "料")):
        for n, u in candidates:
            if "²" in u or "㎡" in u or str(u).lower() in {"m²", "yd²"}:
                return _format_usage(n, u)

    # 其余：优先线性码/M
    for n, u in candidates:
        if "码" in u and "²" not in u:
            return _format_usage(n, "码")
    for n, u in candidates:
        ul = str(u).lower()
        if "²" in u or "㎡" in u or ul in {"m²", "yd²"}:
            return _format_usage(n, u)
    for n, u in candidates:
        ul = str(u).lower()
        if "米" in u or ul == "m":
            return _format_usage(n, "米")
    n, u = candidates[0]
    return _format_usage(n, u)


def _fallback_zipper_meters(role: str, product_size: dict[str, float] | None) -> str | None:
    if not product_size:
        return None
    if not any(k in (role or "") for k in ("拉链", "zip")):
        return None
    l_ = float(product_size.get("LCM") or product_size.get("lcm") or 0)
    w_ = float(product_size.get("WCM") or product_size.get("wcm") or 0)
    if l_ <= 0 or w_ <= 0:
        return None
    m = ZIPPER_OPENING_FRAC * (2.0 * (l_ + w_) / 100.0) + ZIPPER_EXTRA_M
    if m < 0.15:
        return None
    return f"{round(m, 3)}米"


def apply_structure_usage_hints(
    items: list[dict[str, Any]],
    structure_text: str,
    *,
    product_size: dict[str, float] | None = None,
    piece_area_calculation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """写入 usage + _structure_usage_lock，供 Kimi 合并阶段锁定用量（覆盖模型改写）。

    逻辑顺序：
    1）按结构说明小段 + 物料名对齐，抽取显式「x 码/米」类用量；
    2）仍为占位「1 码/1 套」或缺失 —— 则用长×宽×高 + 袋型关键字做几何近似（面料面积、拉链/织带/包边米长、五金颗数）。
    """
    meta: dict[str, Any] = {"matched": 0, "geometry_matched": 0, "segments": 0}
    if not items:
        return meta
    st_raw = structure_text or ""
    ps = _merge_product_size(product_size, st_raw)
    hw_cat = _effective_hardware_catalog(st_raw)
    piece_calc = _resolve_piece_area_calculation(
        piece_area_calculation,
        product_size=ps,
        structure_text=st_raw,
        items=items,
    )
    segments = _split_structure_segments(st_raw.strip()) if st_raw.strip() else []
    meta["segments"] = len(segments)

    for row in items:
        if not isinstance(row, dict):
            continue
        if row.get("_sheet_usage_lock"):
            continue
        existing_u = str(row.get("usage") or "").strip()
        if row.get("_structure_usage_lock") and existing_u and not _is_missing_usage(existing_u):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        row_hint = _name_join_for_match(name, str(row.get("spec") or row.get("usage") or ""))
        if _WEBBING_PAT.search(row_hint):
            explicit_cm = _cm_length_usage_from_row(row)
            if explicit_cm:
                row["usage"] = explicit_cm
                row["_structure_usage_lock"] = True
                if _calc_note_safe_to_fill(str(row.get("calc_note") or "")):
                    row["calc_note"] = "织带按表内长度区间换算为米并加车缝余量"
                meta["matched"] += 1
                continue
        if not _needs_geometry_fill(row):
            continue

        resolved: str | None = None

        best_seg = ""
        best_sc = 0
        if segments:
            for seg in segments:
                sc = _segment_score(name, seg)
                if sc > best_sc:
                    best_sc = sc
                    best_seg = seg

        role = str(row.get("role") or "")
        if best_sc >= 1 and best_seg:
            clean = _strip_for_usage_parse(best_seg)
            cands = _extract_usage_candidates(clean)
            resolved = _pick_usage_for_role(role, best_seg, cands, product_size=ps)

        if resolved:
            row["usage"] = resolved
            row["_structure_usage_lock"] = True
            meta["matched"] += 1
            continue

        geo_u = _try_derive_geometry_usage(
            row, ps, hw_cat, structure_blob=st_raw, piece_calc=piece_calc
        )
        if geo_u:
            row["usage"] = geo_u
            row["_structure_usage_lock"] = True
            gnote = _explain_geometry_calc_note(
                row, geo_u, ps, st_raw, piece_calc=piece_calc
            )
            if gnote and _calc_note_safe_to_fill(str(row.get("calc_note") or "")):
                row["calc_note"] = gnote[:260]
            meta["geometry_matched"] += 1
    return meta


def tighten_small_bag_usage_amounts(
    items: list[dict[str, Any]],
    *,
    product_size: dict[str, float] | None = None,
    structure_text: str = "",
    piece_area_calculation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Correct oversized model usage for small pouch demand templates.

    The vision/LLM layer can occasionally turn local dimensions such as
    "152cm / 1套" or a single panel print into a whole-yard charge. For small
    bags with reliable L/W/H, use the same deterministic geometry helper as
    `apply_structure_usage_hints` and recompute amount from unit price.
    """
    meta = {"adjusted": 0, "facts": {}}
    if not items or not _has_box_dims(product_size):
        return meta
    l_, w_, h_ = _dims_lwh_cm(product_size)
    if max(l_, w_, h_) > 45:
        return meta
    ps = _merge_product_size(product_size, structure_text or "")
    hw_cat = _effective_hardware_catalog(structure_text or "")
    piece_calc = _resolve_piece_area_calculation(
        piece_area_calculation,
        product_size=ps,
        structure_text=structure_text or "",
        items=items,
    )
    meta["facts"] = _structure_fact_summary(ps, structure_text or "")
    for row in items:
        if not isinstance(row, dict) or row.get("_sheet_usage_lock"):
            continue
        if not _small_bag_row_needs_tightening(row):
            continue
        row_structure = _row_structure_context(row, structure_text or "")
        geo_u = _try_derive_geometry_usage(
            row, ps, hw_cat, structure_blob=row_structure, piece_calc=piece_calc
        )
        if not geo_u:
            continue
        prev_usage = str(row.get("usage") or "").strip()
        row["usage"] = geo_u
        row["usage_ai"] = True
        row["_structure_usage_lock"] = True
        amount = _amount_from_unit_price_and_usage(str(row.get("unit_price") or ""), geo_u)
        if amount is not None:
            row["amount"] = amount
            row["amount_ai"] = True
        gnote = _explain_geometry_calc_note(
            row, geo_u, ps, row_structure, piece_calc=piece_calc
        )
        if gnote:
            row["calc_note"] = gnote[:260]
        if prev_usage:
            row["ai_reason"] = f"小包几何复核：原用量「{prev_usage}」偏大，按产品尺寸重算为「{geo_u}」。"
        meta["adjusted"] += 1
    return meta


def _structure_fact_summary(product_size: dict[str, float], structure_text: str) -> dict[str, Any]:
    l_, w_, h_ = _dims_lwh_cm(product_size)
    dims = re.findall(
        r"(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)\s*(?:mm|MM|毫米|cm|CM|厘米)?",
        structure_text or "",
    )
    return {
        "product_lwh_cm": [round(l_, 2), round(w_, 2), round(h_, 2)],
        "inline_2d_dims_count": len(dims),
        "has_image_or_link_context": ("工作簿嵌入图片" in structure_text or "超链接" in structure_text),
    }


def _small_bag_row_needs_tightening(row: dict[str, Any]) -> bool:
    name = _name_join_for_match(str(row.get("name") or ""), str(row.get("spec") or ""))
    price = str(row.get("unit_price") or "").strip()
    usage = str(row.get("usage") or "").strip()
    amount = _floatish(row.get("amount"))
    unit = _floatish(_first_number_text(price))
    if not name or not price or price == "-":
        return False
    fabric_like = (
        _MAIN_FAB_PAT.search(name)
        or _LINING_PAT.search(name)
        or any(k in name for k in ("印花", "印刷", "皮标", "LOGO", "logo"))
    )
    if not fabric_like:
        return False
    if not (_unit_price_signals_roll_linear_yards(price) or _unit_price_signals_area(price) or "码" in price):
        return False
    if amount is not None and unit is not None and unit > 0 and amount / unit <= 0.9:
        return False
    if any(k in usage for k in ("套", "1套", "cm", "CM", "厘米", "码")):
        return True
    return bool(amount is not None and amount >= 3.0)


def _row_structure_context(row: dict[str, Any], structure_text: str) -> str:
    parts: list[str] = []
    for key in ("name", "role", "spec", "usage", "unit_price", "calc_note", "calc_method", "ai_reason"):
        val = str(row.get(key) or "").strip()
        if val and val != "-":
            parts.append(val)
    if structure_text:
        parts.append(structure_text)
    return "\n".join(parts)


def _first_number_text(text: str) -> str:
    m = re.search(r"-?\d+(?:\.\d+)?", str(text or ""))
    return m.group(0) if m else ""


def _floatish(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _amount_from_unit_price_and_usage(price_text: str, usage_text: str) -> float | None:
    unit = _floatish(_first_number_text(price_text))
    qty = _floatish(_first_number_text(usage_text))
    if unit is None or qty is None or unit <= 0 or qty <= 0:
        return None
    return round(unit * qty, 2)


def strip_structure_usage_markers(row: dict[str, Any]) -> None:
    row.pop("_structure_usage_lock", None)
