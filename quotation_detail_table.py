"""_parse sheets shaped like「项目 | 计算方式 | 报价用量 | 单价 | 金额/个」

业务在独立 sheet（如「1.43oz DCF」）里写细算；须优先采「报价用量」列，避免 Agent 误用 1 套/1 码。
表头若为「计算方式」+「单位用量(具体算法)」双列时，合并写入 calc_method，贴近图二手写算式列。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sheet_parser import is_non_material_label_name, row_get


@dataclass(frozen=True)
class QuotationDetailRow:
    """一行展开料，来自业务报价细表。"""

    name: str  # 项目
    calc_method: str  # 计算方式（展示用）
    quoted_usage: str  # 报价用量（优先作为 BOM 用量）
    unit_price: str  # 单价原文
    amount_unit: str  # 金额/个 原文（可选，用于对账展示）


_SKIP_NAME_RX = re.compile(
    r"(加工费|刀模|模具摊|开模费|仅.*费|合计|小计|总计|利润|毛利率)",
    re.I,
)

_CALC_NOTE_MAX_CHARS = 2000


def _norm_header_cell(cell: object) -> str:
    return str(cell or "").replace("　", " ").strip()


def _looks_like_formula_usage_header(text: str) -> bool:
    """是否为「具体算法」类列（长算式）；此类列决不能当作数值用量列。"""
    t = text.strip().replace("（", "(").replace("）", ")")
    if not t:
        return False
    if "具体算法" in t or "具体算式" in t:
        return True
    # 「单位用量(具体算法…」与 WPS/Figure 2 对齐
    if ("单位用量" in t or "单位用料" in t) and "算法" in t:
        return True
    return False


def _score_qty_column_header(text: str) -> int:
    """用量列分值；若为具体算法列须返回负分。"""
    t = text.strip().replace("　", " ")
    if not t:
        return -1
    if _looks_like_formula_usage_header(t):
        return -1
    if "报价用量" in t:
        return 100
    if "折合用量" in t or ("折合" in t and "用量" in t):
        return 92
    if "定额用量" in t or ("定额" in t and "用量" in t):
        return 91
    if "单位用料" in t:
        return 82
    # 「单位用量」若未注明具体算法列，常为长文案格，不参与数值用量列竞争（避免整格算式被选成用量）。
    if t == "单位用量" or t.replace("　", "").strip() == "单位用量":
        return -1
    if t == "用量" or (t.endswith("用量") and "报价" not in t and len(t) <= 18):
        return 72
    if "用料" in t and "计价" not in t and len(t) <= 12:
        return 62
    return -1


def _row_joined_cells(header_row: list[str]) -> str:
    parts = [_norm_header_cell(x) for x in header_row if _norm_header_cell(x)]
    return " ".join(parts)


def row_looks_like_quotation_detail_header(header_row: list[str]) -> bool:
    """表头是否具有「明细报价块」语义（项目 + 计价 + 用量 + 算法/计算说明）."""
    joined = _row_joined_cells(header_row)
    if not joined:
        return False
    if "单价" not in joined:
        # 部份表仅用「物料单价」「含税单价」，仍须有金额类列
        if "金额" not in joined:
            price_like = ("物料单价" in joined) or ("含税单价" in joined) or ("元/" in joined)
            if not price_like:
                return False

    qty_scores = [_score_qty_column_header(_norm_header_cell(c)) for c in header_row]
    qty_ok = any(s >= 40 for s in qty_scores if s is not None) or "报价用量" in joined
    calc_ok = any(
        "计算方式" in _norm_header_cell(c)
        or "具体算法" in _norm_header_cell(c)
        or _looks_like_formula_usage_header(_norm_header_cell(c))
        or (
            "算法" in _norm_header_cell(c) and not _looks_like_formula_usage_header(_norm_header_cell(c))
        )
        for c in header_row
    )

    item_ok = any(
        "项目" in _norm_header_cell(c)
        or "物料名称" in _norm_header_cell(c)
        or "材料名称" in _norm_header_cell(c)
        or (_norm_header_cell(c) == "名称")
        or ("品名" in _norm_header_cell(c))
        for c in header_row
    ) or ("项目" in joined)

    return bool(qty_ok and calc_ok and item_ok)


def find_quotation_detail_header_row(rows: list[list[str]]) -> int | None:
    """定位「报价明细」表头：兼容图二样式（计算方式 + 单位用量具体算法）与经典五列模板。"""
    for idx, row in enumerate(rows[:160]):
        if row_looks_like_quotation_detail_header(row):
            return idx
    return None


def _merge_detail_calc_cells(formula_text: str, brief_text: str) -> str:
    f = formula_text.strip()
    b = brief_text.strip()
    if not f:
        out = b
    elif not b:
        out = f
    elif b in f or f in b:
        out = f if len(f) >= len(b) else b
    else:
        # 长段通常为「具体算法」算式句，更符合图二，置前便于阅读。
        if len(f) >= len(b):
            out = f"{f}；{b}"
        else:
            out = f"{b}；{f}"
    return out[:_CALC_NOTE_MAX_CHARS]


def _build_detail_column_map(header_row: list[str]) -> dict[str, Any]:
    """识别列：拆分 calc_formula（具体算法）与 calc_brief（计算方式短句）；用量列排除算法列."""
    mapping: dict[str, Any] = {}

    formulas: list[tuple[int, str]] = []
    briefs: list[tuple[int, str]] = []
    amt_candidates: list[tuple[int, str]] = []

    for idx, raw in enumerate(header_row):
        text = _norm_header_cell(raw)
        if not text:
            continue

        item_hit = False
        if ("项目" in text or "物料名称" in text or "材料名称" in text) and "说明" not in text:
            mapping.setdefault("item", idx)
            item_hit = True
        if not item_hit and text.strip() == "名称":
            mapping.setdefault("item", idx)

        if _looks_like_formula_usage_header(text) or "具体算法" in text or "具体算式" in text:
            formulas.append((idx, text))
            continue

        if "计算方式" in text:
            briefs.append((idx, text))
            continue
        if "算法" in text and not _looks_like_formula_usage_header(text):
            briefs.append((idx, text))
            continue

        _tn = text.replace("　", " ").replace("／", "/")
        if (
            ("金额" in text and ("个" in _tn.replace(" ", "") or "/" in _tn))
            or ("成本" in text and "单个" in text)
        ):
            amt_candidates.append((idx, text))
        elif "单价" in text or "物料单价" in text:
            mapping.setdefault("price", idx)

    best_qty_sc = -1
    best_qty_i = -1
    for idx, raw in enumerate(header_row):
        text = _norm_header_cell(raw)
        sc = _score_qty_column_header(text)
        if sc > best_qty_sc:
            best_qty_sc, best_qty_i = sc, idx
    if best_qty_sc >= 40:
        mapping["qty"] = best_qty_i

    if amt_candidates:
        mapping["amt"] = amt_candidates[0][0]
    elif "amt" not in mapping:
        # 回退：「金额」「小计」类
        for idx, raw in enumerate(header_row):
            text = _norm_header_cell(raw)
            norm_slash = text.replace("／", "/")
            if "金额" in text and "总价" not in text and "/" not in norm_slash.replace(" ", ""):
                mapping.setdefault("amt", idx)
                break

    if formulas:
        mapping["calc_formula"] = formulas[0][0]
    fi = mapping.get("calc_formula")
    for bi, _txt in briefs:
        if fi is None or bi != fi:
            mapping["calc_brief"] = bi
            break

    # 仅有「计算方式」列、无公式列时兜底
    if "calc_formula" not in mapping and "calc_brief" not in mapping and briefs:
        mapping["calc_brief"] = briefs[0][0]

    return mapping


def _cell(row: list[str], column_map: dict[str, Any], key: str) -> str:
    idx = column_map.get(key)
    if idx is None:
        return ""
    return row_get(row, int(idx)).strip()


def parse_quotation_detail_rows(
    rows: list[list[str]],
    *,
    header_index: int,
) -> list[QuotationDetailRow]:
    header = rows[header_index]
    cmap = _build_detail_column_map(header)
    if cmap.get("item") is None or cmap.get("qty") is None:
        return []

    out: list[QuotationDetailRow] = []
    for row in rows[header_index + 1 :]:
        name = _cell(row, cmap, "item")
        usage = _cell(row, cmap, "qty").strip()
        price = (_cell(row, cmap, "price") or "").strip()
        amt = (_cell(row, cmap, "amt") or "").strip()

        fb = ""
        cf = ""
        if "calc_formula" in cmap:
            cf = _cell(row, cmap, "calc_formula").strip()
        if "calc_brief" in cmap:
            fb = _cell(row, cmap, "calc_brief").strip()
        calc = _merge_detail_calc_cells(cf, fb)

        if not name or _SKIP_NAME_RX.search(name):
            continue
        if is_non_material_label_name(name):
            continue
        if not usage and not price and not amt:
            continue

        if not usage:
            continue

        out.append(
            QuotationDetailRow(
                name=name,
                calc_method=calc,
                quoted_usage=usage,
                unit_price=price or "-",
                amount_unit=amt,
            )
        )
    return out


def quotation_detail_rows_to_material_dicts(
    detail_rows: list[QuotationDetailRow],
    *,
    sheet_slug: str,
) -> list[dict[str, Any]]:
    """转成 demand_parser.Material 可消费的 dict（由调用处构 Material）。"""
    blobs: list[dict[str, Any]] = []
    for r in detail_rows:
        role = _infer_role(r.name)
        blobs.append(
            {
                "role": role,
                "name": r.name.strip(),
                "spec": "-",
                "note": "",
                "inline_price": r.unit_price if r.unit_price != "-" else "",
                "source": f"bom_detail:{sheet_slug}",
                "quoted_usage": r.quoted_usage.strip(),
                "calc_method": r.calc_method.strip(),
                "sheet_amount_unit": r.amount_unit.strip(),
            }
        )
    return blobs


def _infer_role(item_name: str) -> str:
    n = item_name.strip()
    if any(k in n for k in ("面料", "外料", "里布", "里料", "DCF", "DCH", "X-PAC", "XPAC")):
        return "外料"
    if any(k in n for k in ("拉链", "拉头")):
        return "拉链"
    if any(k in n for k in ("扣", "多耐福", "WooJin")):
        return "扣具"
    if any(k in n for k in ("绳", "织带")):
        return "织带"
    if any(k in n for k in ("胶", "糊")):
        return "辅料"
    if any(k in n for k in ("标", "唛", "LOGO")):
        return "辅料"
    if "包装" in n:
        return "包装"
    return "辅料"
