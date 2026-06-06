"""需求表 BOM 行预处理：避免「网布+EVA+底 X-PAC」复合行与单独 X-PAC 等行重复计整码。"""
from __future__ import annotations

import re
from typing import Any


def _norm(s: str) -> str:
    t = (s or "").strip().lower()
    t = re.sub(r"\s+", "", t)
    return t


def _is_composite_material_name(name: str) -> bool:
    """Composite sandwich / multi-ply description (一格多料)."""
    n = (name or "").strip()
    if len(n) < 8:
        return False
    if "+" in n or "＋" in n:
        return True
    nl = n.lower()
    if any(k in n for k in ("三明治", "复合料", "贴合", "双层面料")) and len(n) >= 10:
        return True
    if ("网布" in n or "eva" in nl) and ("x-pac" in nl or "xpac" in nl):
        return True
    if "整块" in n and ("eva" in nl or "网" in n) and ("x-pac" in nl or "xpac" in nl):
        return True
    return False


def _mentions_xpac(text: str) -> bool:
    t = _norm(text)
    return bool(re.search(r"x[\s-]*pac|vx\s*\d+|vx21", t))


def _mentions_dch_or_dcf(text: str) -> bool:
    t = _norm(text)
    return "dch" in t or "dcf" in t or "3.2oz" in t or "1.43oz" in t


def _composite_texts_cover_xpac(composite_names: list[str]) -> bool:
    for c in composite_names:
        cl = c.lower()
        if "x-pac" in cl or "xpac" in cl or "vx" in cl:
            return True
    return False


_WIDTH_DIM_TOKEN = re.compile(
    r"(幅宽|门幅|宽幅)\s*[：:]?\s*(\d+)\s*(?:CM|厘米|毫米|MM|英寸|inch|m)?",
    re.I,
)


def _row_amount_value(row: dict[str, Any]) -> float:
    raw = row.get("amount")
    if raw is None or raw == "":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _width_dimension_bucket_key(name: str) -> str:
    nm = str(name or "").strip()
    m = _WIDTH_DIM_TOKEN.search(nm)
    if not m:
        return ""
    return f"w:{int(m.group(2))}"


def merge_duplicate_width_label_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并「幅宽145CM」「宽幅145cm」等数值相同的门幅描述重复行。"""
    if not items or len(items) < 2:
        return items
    buckets: dict[str, list[int]] = {}
    for idx, row in enumerate(items):
        if not isinstance(row, dict):
            continue
        bk = _width_dimension_bucket_key(str(row.get("name") or ""))
        if not bk:
            continue
        buckets.setdefault(bk, []).append(idx)
    skip_idx: set[int] = set()
    replace_idx: dict[int, dict[str, Any]] = {}
    for _bk, ixlist in buckets.items():
        if len(ixlist) < 2:
            continue
        lead_idx = max(ixlist, key=lambda i: len(str(items[i].get("name") or "")))
        total_amt = round(sum(_row_amount_value(items[i]) for i in ixlist), 2)
        keeper = dict(items[lead_idx])
        merged_names = sorted(
            {str(items[i].get("name") or "").strip() for i in ixlist if str(items[i].get("name") or "").strip()}
        )
        if len(merged_names) > 1:
            keeper["name"] = merged_names[0]
            note = "; ".join(merged_names)
            prev = str(keeper.get("spec") or "").strip()
            tail = f"合并门幅同源:{note}"
            keeper["spec"] = f"{prev}；{tail}" if prev and prev != "-" else tail
        keeper["amount"] = total_amt
        keeper["amount_text"] = f"{total_amt:.2f}元"
        replace_idx[lead_idx] = keeper
        for i in ixlist:
            if i != lead_idx:
                skip_idx.add(i)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(items):
        if i in skip_idx:
            continue
        out.append(replace_idx.get(i, row))
    return out if out else items

def collapse_fabric_reverse_use_shadow_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉「同款面料仅为反用说明」的假 BOM 行——避免与主料行双倍计价。

    典型：主料格已有 3.2oz DCH，结构说明里「××部位 DCH 面料反用（450元/码）」；
    Agent 再加一行并按 450×1 码计价 → 应与主料合并为规格备注，不参与二次计费。
    """
    if len(items) < 2:
        return items

    def is_shadow(nm: str) -> bool:
        n = str(nm or "").strip()
        if len(n) < 10:
            return False
        if "反用" in n:
            return True
        if re.search(r"反面\s*做面|翻面|面料\s*反", n):
            return True
        if "悬用" in n and ("面料" in n or _mentions_dch_or_dcf(n)):
            return True
        return False

    normals: list[dict[str, Any]] = []
    shadows: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if is_shadow(name):
            shadows.append(dict(raw))
        else:
            normals.append(dict(raw))

    out: list[dict[str, Any]] = list(normals)
    if not shadows:
        return out if out else items

    def find_anchor(nm: str) -> int | None:
        idx: int | None = None
        if _mentions_dch_or_dcf(nm):
            idx = next(
                (
                    i
                    for i, peer in enumerate(out)
                    if _mentions_dch_or_dcf(str(peer.get("name") or ""))
                    and len(str(peer.get("name") or "")) <= 42
                    and not is_shadow(str(peer.get("name") or ""))
                ),
                None,
            )
        if idx is None and _mentions_xpac(nm):
            idx = next(
                (
                    i
                    for i, peer in enumerate(out)
                    if _mentions_xpac(str(peer.get("name") or ""))
                    and len(str(peer.get("name") or "")) <= 52
                    and not is_shadow(str(peer.get("name") or ""))
                ),
                None,
            )
        return idx

    for shadow in shadows:
        name = str(shadow.get("name") or "").strip()
        anchor_idx = find_anchor(name)
        if anchor_idx is None:
            out.append(dict(shadow))
            continue
        keeper = dict(out[anchor_idx])
        prev_spec = str(keeper.get("spec") or "").strip()
        suffix = name if len(name) <= 140 else name[:137] + "…"
        tag = f"并入工艺备注（非独立用料）：{suffix}"
        keeper["spec"] = f"{prev_spec}；{tag}" if prev_spec and prev_spec != "-" else tag
        out[anchor_idx] = keeper
    return out if out else items


def dedupe_composite_overlapping_fabric_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    存在复合夹层行时，删除已被复合行语义覆盖的「短名单独面料行」，
    减少后续模型对每行都给 1 码造成的翻倍。

    典型：单独一行「X-PAC VX21」+ 一行「网布+EVA+底 x-pac」→ 删前者。
    「3.2oz DCH」若复合行不含 DCH，必须保留（常见前幅 DCH、后幅夹层）。
    """
    if not items or len(items) < 2:
        return items
    names = [str(it.get("name") or "").strip() for it in items]
    comp_idx = [i for i, n in enumerate(names) if _is_composite_material_name(n)]
    if not comp_idx:
        return items
    composites = [names[i] for i in comp_idx]

    out: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        n = names[i]
        if i in comp_idx:
            out.append(it)
            continue
        if len(n) > 55:
            out.append(it)
            continue

        # 单独短行的 X-PAC，复合层已描述底布/夹层 X-PAC → 去掉重复
        if (
            _mentions_xpac(n)
            and len(n) <= 40
            and _composite_texts_cover_xpac(composites)
        ):
            continue

        # 仅当复合行文字里也出现 DCH/DCF 时，才删短行的重复 DCH（避免误删前幅单独 DCH）
        if _mentions_dch_or_dcf(n) and len(n) <= 40:
            if any(_mentions_dch_or_dcf(c) for c in composites):
                continue

        out.append(it)

    return out if out else items


_STRUCTURE_MERGED_IN_PLACE_PATTERN = re.compile(r"已并入第\s*\d+\s*行")


def _fabric_dedupe_bucket(name: str) -> str:
    """同一桶内的行若为「简短 BOM + 结构说明长句」并存，只保留 BOM 行。"""
    raw = str(name or "").strip()
    if not raw:
        return ""
    nl = raw.lower()
    nu = _norm(raw)
    if _mentions_xpac(raw):
        return "fab:xpac_vx"
    if _mentions_dch_or_dcf(raw):
        return "fab:dyneema"
    if "ultra" in nu:
        return "fab:ultra"
    # 防水拉链族（避免「5#YKK防水拉链」与「采用防水拉链…」两条并存）
    if "拉链" in raw and ("防水" in raw or "ykk" in nl or re.search(r"\d\s*#", raw)):
        return "acc:zip_water"
    return ""


def _looks_like_structure_narrative_row_name(name: str) -> bool:
    """结构说明拆出来的长描述行（非简短主料/辅料标题）。"""
    n = str(name or "").strip()
    if len(n) < 14:
        return False
    prose = ("主体", "采用", "背板", "肩带", "进口", "面料", "包身")
    hits = sum(1 for m in prose if m in n)
    if hits >= 2:
        return True
    if len(n) >= 18 and hits >= 1:
        return True
    # 「采用……拉链」「主体……拉链」类
    if len(n) >= 12 and "拉链" in n and ("采用" in n or "主体" in n):
        return True
    return False


def drop_duplicate_structure_narrative_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉与 BOM 同行的「结构说明复述」物料行（同面料桶只保留简短计价行）。

    仅在「桶内已有非叙述型 keeper 且 keeper 已有小计」或「叙述行本身未计价」时删除叙述行，
    避免误删唯一有价数据。"""
    if not items or len(items) < 2:
        return items

    buckets: dict[str, list[int]] = {}
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        bk = _fabric_dedupe_bucket(str(raw.get("name") or ""))
        if bk:
            buckets.setdefault(bk, []).append(i)

    drop_ix: set[int] = set()
    for ixlist in buckets.values():
        if len(ixlist) < 2:
            continue
        keeper_candidates = [
            i
            for i in ixlist
            if not _looks_like_structure_narrative_row_name(str(items[i].get("name") or ""))
        ]
        if not keeper_candidates:
            continue
        keeper_idx = min(keeper_candidates)
        keeper_amt = _row_amount_value(items[keeper_idx])

        for i in ixlist:
            if i == keeper_idx:
                continue
            if not _looks_like_structure_narrative_row_name(str(items[i].get("name") or "")):
                continue
            nar_amt = _row_amount_value(items[i])
            if keeper_amt > 1e-6 or nar_amt <= 1e-6:
                drop_ix.add(i)

    out = [row for j, row in enumerate(items) if j not in drop_ix]
    return out if out else items


def drop_structure_duplicate_markup_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉「已并入第 N 行」类结构说明重复行——与同主料合并计价后不应再出现在明细表里。"""
    if not items:
        return items
    kept: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        blob = "\n".join(
            str(raw.get(k) or "")
            for k in ("calc_note", "calc_method", "spec", "note", "name")
        )
        if _STRUCTURE_MERGED_IN_PLACE_PATTERN.search(blob):
            continue
        kept.append(raw)
    return kept if kept else items


def _calc_blob_for_row(row: dict[str, Any]) -> str:
    return "\n".join(str(row.get(k) or "") for k in ("calc_note", "calc_method", "spec", "note", "name"))


def _should_hide_zero_merge_placeholder(row: dict[str, Any]) -> bool:
    """小计为 0 且文案写明「已合并到其它行 / 禁止双计」的占位行，不在明细里展示。"""
    if _row_amount_value(row) > 1e-6:
        return False
    blob = _calc_blob_for_row(row)
    if not blob.strip():
        return False
    if "已合并计入" in blob:
        return True
    if re.search(r"与首行.{0,80}重复", blob):
        return True
    if "禁止双计" in blob and ("重复" in blob or "合并" in blob):
        return True
    return False


def drop_zero_subtotal_merge_placeholder_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉「重复已合并」说明且小计为 0 的行（例如主面料 DCF 占位解释行）。"""
    if not items:
        return items
    kept: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if _should_hide_zero_merge_placeholder(raw):
            continue
        kept.append(raw)
    return kept if kept else items
