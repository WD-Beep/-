"""Structured 'calculation breakdown' payloads for advisory / process_card UI."""
from __future__ import annotations

import json
import re
from typing import Any


_DIM_USAGE_RE = re.compile(r"^\d+(?:\.\d+)?\s*[*xX×]\s*\d+(?:\.\d+)?\s*(CM|MM|M|米|码|码²|M²|㎡)?", re.I)


def _truthy_ai(row: dict[str, Any], key: str) -> bool:
    v = row.get(key)
    if v is True:
        return True
    if isinstance(v, (int, float)) and v != 0:
        return True
    s = str(v or "").strip().lower()
    return s in {"1", "true", "yes", "y"}


def _display_spec(spec: str) -> str:
    s = str(spec or "").strip()
    if not s or s in {"-", "规格-", "—"}:
        return "-"
    return s


def _human_source_line(row: dict[str, Any]) -> str:
    """给业务员看的来源说明，不用「模型补全」等技术词。"""
    if row.get("kb_hit"):
        return "来源：系统价（标价库已匹配）"
    src = str(row.get("source") or "").strip().lower()
    any_ai = (
        _truthy_ai(row, "spec_ai")
        or _truthy_ai(row, "usage_ai")
        or _truthy_ai(row, "unit_price_ai")
        or _truthy_ai(row, "amount_ai")
    )
    if src in {"ai", "model"} or any_ai:
        return (
            "来源：AI 参考价（标价库里没有这条或匹配不上，系统按常见行情帮您估了一个数，"
            "下单前建议再核对或问采购）"
        )
    return "来源：按表格/结构说明填写（未使用标价库单价）"


def _try_parse_unit_price_number(unit_price: str) -> float | None:
    t = str(unit_price or "").strip()
    if not t or t == "-":
        return None
    m = re.search(r"(?:¥|￥)?\s*(\d+(?:\.\d+)?)\s*元", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(?:¥|￥)\s*(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1))
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(?:元|$)", t)
    if m:
        return float(m.group(1))
    return None


def _fmt_compact_num(n: float) -> str:
    if n != n:  # NaN
        return "?"
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    s = f"{n:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _source_table_cell(row: dict[str, Any]) -> tuple[str, str]:
    """表格「来源」列短标签与 title 完整说明。"""
    title = _human_source_line(row)
    if row.get("kb_hit"):
        return ("🟢 系统价", title)
    src = str(row.get("source") or "").strip().lower()
    any_ai = (
        _truthy_ai(row, "spec_ai")
        or _truthy_ai(row, "usage_ai")
        or _truthy_ai(row, "unit_price_ai")
        or _truthy_ai(row, "amount_ai")
    )
    if src in {"ai", "model"} or any_ai:
        return ("🟡 AI参考", title)
    return ("⚪ 表填价", title)


def _material_remark_row(
    *,
    amt: float | None,
    pn: float | None,
    un: float | None,
    unit_raw: str,
    usage_raw: str,
    diff: float | None,
) -> str | None:
    """需跨列表格脚注时返回文案，否则 None。"""
    if amt is None:
        return "❌ 本行未能得到有效小计金额，请检查表格中单列是否填全。"
    if pn is None or un is None:
        u = unit_raw if unit_raw and unit_raw != "-" else "(单价原文)"
        g = usage_raw if usage_raw and usage_raw != "-" else "(用量原文)"
        return (
            f"⚠️ 本行未能自动还原计算式，原始数据：单价 {u} × 用量 {g} = {amt:.2f} 元，建议人工核对"
        )
    if diff is not None and diff > 0.05:
        return (
            f"⚠️ 按解析后的单价×用量（{_fmt_compact_num(pn)} × {_fmt_compact_num(un)}）"
            f"与系统给出的小计相差约 {diff:.2f} 元；报价以本行小计为准，常见原因为套装价、含税或表内直写小计。"
        )
    return None


def _verify_state_code(
    amt: float | None,
    pn: float | None,
    un: float | None,
    diff: float | None,
) -> str:
    if amt is None:
        return "error"
    if pn is not None and un is not None and diff is not None:
        return "ok" if diff <= 0.05 else "warn"
    return "warn"


def _try_parse_usage_quantity(usage: str) -> float | None:
    t = str(usage or "").strip()
    if not t or t == "-":
        return None
    if _DIM_USAGE_RE.match(t.strip()):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if not m:
        return None
    return float(m.group(1))


def _human_calc_and_verify(
    row: dict[str, Any],
    unit_raw: str,
    usage_raw: str,
    pn: float | None,
    un: float | None,
) -> tuple[str, str]:
    """返回 (计算行文案, 验算提示行)."""
    try:
        amt = float(row.get("amount"))
    except (TypeError, ValueError):
        return ("计算：本行小计未能算出一个数字，请检查表格。", "⚠️ 请核对单价与用量是否填全。")

    unit_show = str(unit_raw or "").strip() or "-"
    usage_show = str(usage_raw or "").strip() or "-"

    if pn is not None and un is not None:
        calc_txt = f"计算：{unit_show} × {usage_show} = {amt:.2f} 元"
        diff = round(abs(pn * un - amt), 2)
        if diff <= 0.05:
            verify = "✅ 验算无误（单价×用量与上面小计一致）"
        else:
            verify = (
                "⚠️ 提示：把单价和用量单独相乘，和本行小计略有出入。"
                "常见原因是套装价、含税、或表里直接写了小计；报价以本行小计为准。"
            )
        return (calc_txt, verify)

    calc_txt = f"计算：本行小计 {amt:.2f} 元（未能自动还原成「一个单价 × 一段用量」，请对照下面三行原文）"
    verify = "ℹ️ 建议人工用单价、用量手算核对一遍。"
    return (calc_txt, verify)


def material_process_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "-").strip() or "-"
        spec_disp = _display_spec(str(row.get("spec") or ""))
        usage_raw = str(row.get("usage") or "").strip() or "-"
        if usage_raw == "-":
            usage_disp = "-"
        else:
            usage_disp = usage_raw
        unit_raw = str(row.get("unit_price") or "").strip() or "-"

        pn = _try_parse_unit_price_number(unit_raw)
        un = _try_parse_usage_quantity(usage_raw)

        calc_txt, verify_txt = _human_calc_and_verify(row, unit_raw, usage_raw, pn, un)

        try:
            amt = float(row.get("amount"))
        except (TypeError, ValueError):
            amt = None

        diff: float | None = None
        if amt is not None and pn is not None and un is not None:
            diff = round(abs(pn * un - amt), 2)

        src_short, src_title = _source_table_cell(row)
        formula_short = (
            f"{_fmt_compact_num(pn)} × {_fmt_compact_num(un)}"
            if pn is not None and un is not None
            else "—"
        )
        subtotal_disp = f"{amt:.2f}元" if amt is not None else "—"
        verify_state = _verify_state_code(amt, pn, un, diff)
        remark = _material_remark_row(
            amt=amt,
            pn=pn,
            un=un,
            unit_raw=unit_raw,
            usage_raw=usage_raw,
            diff=diff,
        )

        material_table = {
            "source_display": src_short,
            "source_title": src_title,
            "spec": spec_disp,
            "usage": usage_disp,
            "unit_price": unit_raw if unit_raw != "-" else "—",
            "formula_short": formula_short,
            "subtotal": subtotal_disp,
            "verify_state": verify_state,
            "remark": remark,
        }

        detail_lines = (
            f"规格：{spec_disp}\n"
            f"用量：{usage_disp}\n"
            f"单价：{unit_raw if unit_raw != '-' else '-'}"
        )

        formula_parts: list[dict[str, str]] = [
            {"kind": "source", "text": _human_source_line(row)},
            {"kind": "detail", "text": detail_lines},
            {"kind": "calc", "text": calc_txt},
            {"kind": "verify", "text": verify_txt},
        ]

        formula = "\n".join(p["text"] for p in formula_parts)

        out.append(
            {
                "name": name,
                "formula": formula,
                "formula_parts": formula_parts,
                "source": "",
                "material_table": material_table,
            }
        )
    return out


def tier_process_notes(quote: dict[str, Any]) -> list[str]:
    tiers = quote.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        return []
    include_fob = bool(quote.get("include_fob", True))
    mf = quote.get("settings") or {}
    if not isinstance(mf, dict):
        mf = {}
    try:
        mold = float(mf.get("mold_fee") or 0)
    except (TypeError, ValueError):
        mold = 0.0
    try:
        proc = float(mf.get("processing_fee") or 0)
    except (TypeError, ValueError):
        proc = 0.0
    try:
        sysv = float(mf.get("system_overhead") or 0)
    except (TypeError, ValueError):
        sysv = 0.0
    try:
        fob_add = float(mf.get("fob_addition_per_piece") or 0)
    except (TypeError, ValueError):
        fob_add = 0.0
    gm_text = str(mf.get("gross_margin_rate_text") or "").strip()
    mt = quote.get("material_total_text") or ""
    try:
        mtn = float(quote.get("material_total") or 0)
    except (TypeError, ValueError):
        mtn = 0.0
    if not mt:
        mt = f"{mtn:.2f}元"

    mold_bits: list[str] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        try:
            q = int(tier.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        try:
            ms = float(tier.get("mold_share") or 0)
        except (TypeError, ValueError):
            ms = 0.0
        if q and mold > 0:
            mold_bits.append(f"订 {q} 件时约 {ms:.2f} 元/件（{mold:g} 元模具费 ÷ {q}）")

    mold_examples = "；".join(mold_bits[:3]) if mold_bits else "见上方「分档验算」表。"

    ex_line = ""
    t0 = tiers[0] if isinstance(tiers[0], dict) else {}
    try:
        cb0 = float(t0.get("cost_before_margin") or 0)
        mr0 = float(t0.get("margin_rate") or 0)
        exw0 = float(t0.get("exw_price") or 0)
        if mr0 > 0 and mr0 < 1 and cb0 > 0:
            ex_line = (
                f"举例（第一档）：成本 {cb0:.2f} 元/件，毛利约 {mr0*100:.0f}% → "
                f"EXW ≈ {cb0:.2f} ÷ (1−{mr0:.2f}) = {exw0:.2f} 元/件"
            )
    except (TypeError, ValueError):
        pass

    block_cost = "\n".join(
        [
            "💰 成本怎么来的（都是「一件货」上的钱）：",
            f"1）物料费：把上面每一行小计加起来，本单合计约 {mt}。",
            f"2）加工费：每件 {proc:g} 元（固定单价，和表格里加工费设置一致）。",
            f"3）开模费：模具一共 {mold:g} 元，按订货件数摊到每一件；{mold_examples}",
            f"4）系统杂费：每件 {sysv:g} 元（系统里预留的杂项成本占位，不是利润）。",
            f"5）成本价/件 ≈ 物料费 + 加工费 + 开模分摊 + 杂费（和报价卡里「成本/件」同一套算法）。",
        ]
    )

    if include_fob:
        block_quote = "\n".join(
            [
                "💰 出厂价（EXW）和 FOB 怎么来的：",
                "1）EXW：在「成本/件」上留出毛利率。可以粗想成：成本 ÷（1−毛利率）＝ 给客户的出厂价。"
                + (f" 当前各档毛利率摘要：{gm_text}。" if gm_text else ""),
                f"2）FOB：在 EXW 上再加 {fob_add:g} 元/件的运费/港杂等附加（和系统杂费不是一回事）。",
            ]
            + ([ex_line] if ex_line else [])
        )
    else:
        block_quote = "\n".join(
            [
                "💰 出厂价（EXW）怎么来的：",
                "需求表「价格类型」里没有写 FOB，本单只给出出厂价（EXW），不算港口装船价。",
                "EXW：在「成本/件」上留出毛利率，可以粗想成：成本 ÷（1−毛利率）＝ 给客户的出厂价。"
                + (f" 当前各档毛利率摘要：{gm_text}。" if gm_text else ""),
            ]
            + ([ex_line] if ex_line else [])
        )

    disclaimer = (
        "以上价格为系统根据表格与规则自动估算，实际下单以打样、核价为准；市场面料与配件价格会随季节波动。"
    )

    return [block_cost, block_quote, disclaimer]


def build_cost_overview(quote: dict[str, Any]) -> dict[str, Any]:
    """与报价接口返回同源：拆出「成本/件」由哪些项目组成，便于逐项对账。"""
    include_fob = bool(quote.get("include_fob", True))
    settings = quote.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    try:
        mt = float(quote.get("material_total") or 0)
    except (TypeError, ValueError):
        mt = 0.0
    mt_display = str(quote.get("material_total_text") or "").strip() or f"{mt:.2f}元"
    try:
        sysv = float(settings.get("system_overhead") or 0)
    except (TypeError, ValueError):
        sysv = 0.0
    try:
        proc = float(settings.get("processing_fee") or 0)
    except (TypeError, ValueError):
        proc = 0.0
    try:
        mold_total = float(settings.get("mold_fee") or 0)
    except (TypeError, ValueError):
        mold_total = 0.0
    try:
        fob_add = float(settings.get("fob_addition_per_piece") or 0)
    except (TypeError, ValueError):
        fob_add = 0.0
    gm_text = str(settings.get("gross_margin_rate_text") or "").strip()

    components: list[dict[str, Any]] = [
        {
            "key": "material_total",
            "label": "物料合计",
            "amount_display": mt_display,
            "per_piece": True,
            "hint": "下面每行物料的「小计」相加，应等于这个数。",
        },
        {
            "key": "system_overhead",
            "label": "系统杂费",
            "amount_display": f"{sysv:.2f}元/件",
            "per_piece": True,
            "hint": "单件上的杂项成本占位（管理、损耗等打包估算），不是面料钱。",
        },
        {
            "key": "processing_fee",
            "label": "加工费",
            "amount_display": f"{proc:.2f}元/件",
            "per_piece": True,
            "hint": "缝纫、整烫等加工；若需求表里写了加工费，一般会优先用表里的。",
        },
        {
            "key": "mold_fee",
            "label": "模具费（整单）",
            "amount_display": f"{mold_total:g}元",
            "per_piece": False,
            "hint": "整套模具的钱；摊到每件 = 总价 ÷ 订货件数，件数越高每件越少。",
        },
    ]

    per_tier: list[dict[str, Any]] = []
    tiers = quote.get("tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            try:
                q = int(tier.get("quantity") or 0)
            except (TypeError, ValueError):
                q = 0
            try:
                ms = float(tier.get("mold_share") or 0)
            except (TypeError, ValueError):
                ms = 0.0
            try:
                cbm = float(tier.get("cost_before_margin") or 0)
            except (TypeError, ValueError):
                cbm = 0.0
            try:
                exw = float(tier.get("exw_price") or 0)
            except (TypeError, ValueError):
                exw = 0.0
            try:
                fob = float(tier.get("fob_price") or 0)
            except (TypeError, ValueError):
                fob = 0.0
            try:
                margin = float(tier.get("margin_rate") or 0)
            except (TypeError, ValueError):
                margin = 0.0
            mold_formula = ""
            if mold_total and q:
                mold_formula = f"{mold_total:g} ÷ {q} ≈ {ms:g}"
            sum_formula = f"{mt:g} + {sysv:g} + {proc:g} + {ms:g} = {cbm:g}"
            row_obj: dict[str, Any] = {
                "quantity": q,
                "mold_share": round(ms, 2),
                "mold_share_text": tier.get("mold_share_text") or f"{ms:.2f}元",
                "cost_before_margin": round(cbm, 2),
                "cost_before_margin_text": tier.get("cost_before_margin_text") or f"{cbm:.2f}元",
                "exw_price": round(exw, 2),
                "exw_price_text": tier.get("exw_price_text") or f"{exw:.2f}元",
                "margin_rate_text": tier.get("margin_rate_text") or f"{margin * 100:.0f}%",
                "mold_formula": mold_formula,
                "sum_formula": sum_formula,
            }
            if include_fob:
                row_obj["fob_price"] = round(fob, 2)
                row_obj["fob_price_text"] = tier.get("fob_price_text") or f"{fob:.2f}元"
            else:
                row_obj["fob_price"] = None
                row_obj["fob_price_text"] = ""
            per_tier.append(row_obj)

    footnote_lines = [
        "成本价（毛利前）= 上表物料合计 + 杂费 + 加工费 + 开模分摊；这里还没算「要赚多少个点」。",
        f"出厂价 EXW：在成本上乘以毛利率系数；若各档毛利不同，以报价卡各档为准（摘要：{gm_text or '见表'}）。",
    ]
    if include_fob:
        footnote_lines.append(
            f"FOB：在 EXW 上再加 {fob_add:g} 元/件（港口、运费类附加），和「系统杂费」不是同一笔钱。"
        )
    else:
        footnote_lines.append(
            "本单需求表「价格类型」未注明 FOB，系统不计算、不展示 FOB；需要 FOB 时请在表中价格类型栏写上含 FOB 的说明。"
        )

    return {
        "components": components,
        "per_tier": per_tier,
        "footnote_lines": footnote_lines,
        "include_fob": include_fob,
    }


def tier_cost_stack_blocks(quote: dict[str, Any]) -> list[str]:
    """逐档多行文本块：成本加法 + EXW/FOB 公式，便于人工核对。"""
    include_fob = bool(quote.get("include_fob", True))
    tiers = quote.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        return []
    settings = quote.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    try:
        material_total = float(quote.get("material_total") or 0)
    except (TypeError, ValueError):
        material_total = 0.0
    mt_text = str(quote.get("material_total_text") or "").strip() or f"{material_total:.2f}元"
    try:
        sysv = float(settings.get("system_overhead") or 0)
    except (TypeError, ValueError):
        sysv = 0.0
    try:
        fob_add = float(settings.get("fob_addition_per_piece") or 0)
    except (TypeError, ValueError):
        fob_add = 0.0
    try:
        mold_total = float(settings.get("mold_fee") or 0)
    except (TypeError, ValueError):
        mold_total = 0.0

    blocks: list[str] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        try:
            q = int(tier.get("quantity") or 0)
        except (TypeError, ValueError):
            q = 0
        try:
            mold_share = float(tier.get("mold_share") or 0)
        except (TypeError, ValueError):
            mold_share = 0.0
        try:
            proc = float(tier.get("processing_fee") or 0)
        except (TypeError, ValueError):
            proc = 0.0
        try:
            cbm = float(tier.get("cost_before_margin") or 0)
        except (TypeError, ValueError):
            cbm = 0.0
        try:
            exw = float(tier.get("exw_price") or 0)
        except (TypeError, ValueError):
            exw = 0.0
        try:
            fob = float(tier.get("fob_price") or 0)
        except (TypeError, ValueError):
            fob = 0.0
        try:
            margin = float(tier.get("margin_rate") or 0)
        except (TypeError, ValueError):
            margin = 0.0
        qf = str(tier.get("quote_formula") or "").strip()

        lines = [
            f"▸ {q} 件订货",
            "",
            "【单件成本（还没算毛利）】",
            f"  物料合计 {material_total:g} + 杂费 {sysv:g} + 加工 {proc:g} + 开模分摊 {mold_share:g}",
            f"  = {cbm:g} 元/件",
            f"  （物料合计：{mt_text}）",
            "",
            "【出厂价 EXW】",
            "  在成本上留出毛利率，粗略就是：成本 ÷（1 − 毛利率）。",
            f"  本档：{cbm:g} ÷ (1 − {margin:g}) ≈ {exw:g} 元/件",
        ]
        if include_fob:
            lines.extend(
                [
                    "",
                    "【FOB】",
                    f"  EXW 再加 {fob_add:g} 元/件 ≈ {fob:g} 元/件",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "（本单未报 FOB：需求表「价格类型」未写 FOB，以下为出厂价 EXW 即可。）",
                ]
            )
        if mold_total and q:
            lines.insert(
                5,
                f"  （开模分摊怎么来的：模具共 {mold_total:g} 元 ÷ {q} 件）",
            )
        if qf:
            lines.append("")
            lines.append(f"（系统里存的公式快照：{qf}）")
        blocks.append("\n".join(lines))
    return blocks


def build_process_explainer_payload(quote: dict[str, Any]) -> dict[str, Any]:
    rows = quote.get("detail_rows")
    lines: list[dict[str, Any]] = []
    if isinstance(rows, list):
        lines = material_process_lines([r for r in rows if isinstance(r, dict)])
    overview = build_cost_overview(quote)
    return {
        "product_name": str(quote.get("product_name") or "").strip() or "(未命名产品)",
        "cost_overview": overview,
        "material_lines": lines,
        "tier_notes": tier_process_notes(quote),
        "tier_cost_lines": tier_cost_stack_blocks(quote),
        "raw_hint": quote.get("data_notice"),
        "footer_help": (
            "看不懂？可以在对话里直接问：例如「为什么这行面料这么贵？」"
            "「换成便宜一点的主料多少钱？」系统会按本单数据帮您改算。"
        ),
    }


def _first_tier(quote: dict[str, Any]) -> dict[str, Any]:
    tiers = quote.get("tiers")
    if isinstance(tiers, list) and tiers and isinstance(tiers[0], dict):
        return tiers[0]
    return {}


def _float_or(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_AMOUNT_IN_TEXT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)?")
_EXTERNAL_ROLE_RE = re.compile(
    r"(业务员|业务|销售|客户|手工|手算|表内|对方|他们|厂里)",
    re.I,
)
_SYSTEM_ROLE_RE = re.compile(r"(你|系统|这边|我们|自动|AI)", re.I)
_COMPONENT_EXPLAIN_RE = re.compile(
    r"(怎么来的|从哪来|哪来的|如何得出|依据|组成|占比|差距最大|差最多|最贵)",
    re.I,
)


def _role_for_amount_before(text: str, amount_start: int) -> str:
    """只看数字左侧短窗口，避免「业务员…你算」整段误判。"""
    window = text[max(0, amount_start - 18) : amount_start]
    ext_m = None
    for m in _EXTERNAL_ROLE_RE.finditer(window):
        ext_m = m
    sys_m = None
    for m in _SYSTEM_ROLE_RE.finditer(window):
        sys_m = m
    if ext_m and sys_m:
        return "external" if ext_m.start() >= sys_m.start() else "system"
    if ext_m:
        return "external"
    if sys_m:
        return "system"
    return "unknown"


def _parse_labeled_amounts(user_question: str) -> list[dict[str, Any]]:
    """从用户话术中提取带角色标签的金额，如「业务员算69.2」「你算59.77」。"""
    text = str(user_question or "")
    found: list[dict[str, Any]] = []
    for m in _AMOUNT_IN_TEXT_RE.finditer(text):
        try:
            value = float(m.group(1))
        except (TypeError, ValueError):
            continue
        if value <= 0 or value > 1_000_000:
            continue
        role = _role_for_amount_before(text, m.start())
        if role == "unknown":
            role = "external" if len(found) == 0 else "system"
        found.append(
            {
                "role": role,
                "amount": round(value, 4),
                "context": text[max(0, m.start() - 12) : m.end()].strip(),
            }
        )
    dedup: dict[str, dict[str, Any]] = {}
    for item in found:
        dedup[str(item.get("role"))] = item
    return list(dedup.values())


def _pick_system_price_field(user_question: str) -> str:
    q = str(user_question or "")
    if re.search(r"(成本|毛利前|未含税|出厂前)", q):
        return "cost_before_margin"
    if re.search(r"\bFOB\b|fob|离岸|含运", q, re.I):
        return "fob_price"
    return "exw_price"


def _system_reference_price(quote: dict[str, Any], *, field: str) -> tuple[float, str, dict[str, Any]]:
    tier = _first_tier(quote)
    labels = {
        "exw_price": "EXW出厂价",
        "fob_price": "FOB价",
        "cost_before_margin": "毛利前成本",
    }
    key = field if field in labels else "exw_price"
    val = _float_or(tier.get(key))
    text = str(tier.get(f"{key}_text") or tier.get("total_cost_text") or "").strip()
    q_text = tier.get("quantity_text") or (
        f"{tier.get('quantity')}件" if tier.get("quantity") is not None else "首档"
    )
    label = f"{labels.get(key, key)}（{q_text}）"
    return round(val, 4), text or f"{val:.2f}元", tier


def _row_is_system_estimate(row: dict[str, Any]) -> bool:
    if row.get("kb_hit"):
        return False
    src = str(row.get("source") or "").strip().lower()
    if src in {"ai", "model"}:
        return True
    return bool(
        _truthy_ai(row, "unit_price_ai")
        or _truthy_ai(row, "amount_ai")
        or _truthy_ai(row, "usage_ai")
        or _truthy_ai(row, "spec_ai")
    )


def _row_is_missing_or_pending(row: dict[str, Any]) -> bool:
    try:
        amt = float(row.get("amount"))
        if amt <= 0:
            return True
    except (TypeError, ValueError):
        return True
    unit = str(row.get("unit_price") or "").strip()
    if not unit or unit == "-":
        return True
    return False


def build_amount_breakdown(quote: dict[str, Any]) -> list[dict[str, Any]]:
    """单件金额拆解（物料/加工/杂费/开模/毛利前成本/EXW）。"""
    tier = _first_tier(quote)
    settings = quote.get("settings") if isinstance(quote.get("settings"), dict) else {}
    bridge = quote.get("cost_bridge") if isinstance(quote.get("cost_bridge"), dict) else {}
    material = _float_or(quote.get("material_total"))
    proc = _float_or(tier.get("processing_fee"), settings.get("processing_fee"))
    overhead = _float_or(bridge.get("system_overhead_per_pc"), settings.get("system_overhead"))
    mold = _float_or(tier.get("mold_share"))
    cost = _float_or(tier.get("cost_before_margin"))
    exw = _float_or(tier.get("exw_price"))
    margin = _float_or(tier.get("margin_rate"))
    rows = [
        {"key": "material_total", "label": "物料合计", "amount": round(material, 2), "unit": "元/件"},
        {"key": "processing_fee", "label": "加工费", "amount": round(proc, 2), "unit": "元/件"},
        {"key": "system_overhead", "label": "系统杂费", "amount": round(overhead, 2), "unit": "元/件"},
        {"key": "mold_share", "label": "开模分摊", "amount": round(mold, 2), "unit": "元/件"},
        {"key": "cost_before_margin", "label": "毛利前成本", "amount": round(cost, 2), "unit": "元/件"},
        {"key": "exw_price", "label": "EXW出厂价", "amount": round(exw, 2), "unit": "元/件"},
    ]
    if margin > 0:
        rows.append(
            {
                "key": "margin_rate",
                "label": "毛利率",
                "amount": round(margin * 100, 2),
                "unit": "%",
            }
        )
    if bool(quote.get("include_fob", True)):
        rows.append(
            {
                "key": "fob_price",
                "label": "FOB价",
                "amount": round(_float_or(tier.get("fob_price")), 2),
                "unit": "元/件",
            }
        )
    return rows


def rank_material_rows_by_amount(quote: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    detail_rows = quote.get("detail_rows")
    if not isinstance(detail_rows, list):
        return []
    ranked: list[dict[str, Any]] = []
    for row in detail_rows:
        if not isinstance(row, dict):
            continue
        amt = _float_or(row.get("amount"))
        ranked.append(
            {
                "name": str(row.get("name") or "-").strip(),
                "amount": round(amt, 2),
                "amount_text": str(row.get("amount_text") or f"{amt:.2f}元"),
                "unit_price": str(row.get("unit_price") or "-"),
                "usage": str(row.get("usage") or "-"),
                "is_estimate": _row_is_system_estimate(row),
                "is_pending": _row_is_missing_or_pending(row),
                "kb_hit": bool(row.get("kb_hit")),
            }
        )
    ranked.sort(key=lambda x: x["amount"], reverse=True)
    total = sum(r["amount"] for r in ranked) or 1.0
    for r in ranked:
        r["share_pct"] = round(r["amount"] / total * 100, 1)
    return ranked[:limit]


def rank_gap_source_hypotheses(
    quote: dict[str, Any],
    *,
    delta: float,
    compare_field: str = "exw_price",
) -> list[dict[str, Any]]:
    """按组件金额排序，提示哪些项最可能造成与外部报价的差额。"""
    tier = _first_tier(quote)
    settings = quote.get("settings") if isinstance(quote.get("settings"), dict) else {}
    bridge = quote.get("cost_bridge") if isinstance(quote.get("cost_bridge"), dict) else {}
    material = _float_or(quote.get("material_total"))
    proc = _float_or(tier.get("processing_fee"), settings.get("processing_fee"))
    overhead = _float_or(bridge.get("system_overhead_per_pc"), settings.get("system_overhead"))
    mold = _float_or(tier.get("mold_share"))
    cost = _float_or(tier.get("cost_before_margin"))
    exw = _float_or(tier.get("exw_price"))
    margin = _float_or(tier.get("margin_rate"))
    margin_effect = max(exw - cost, 0.0)

    candidates = [
        ("物料合计", material, "面料用量或单价口径不同"),
        ("加工费", proc, "加工单价或工序范围不同"),
        ("包装/辅料", _packaging_subtotal(quote), "包装计价方式或外箱单价不同"),
        ("系统杂费", overhead, "管理损耗/杂费打包比例不同"),
        ("开模分摊", mold, "模具总额或分摊件数不同"),
        ("毛利率折算", margin_effect, "毛利点数或倒推公式不同"),
    ]
    abs_delta = abs(delta) if delta else 0.0
    out: list[dict[str, Any]] = []
    for label, amount, hint in sorted(candidates, key=lambda x: x[1], reverse=True):
        if amount <= 0 and label != "毛利率折算":
            continue
        coverage = round(min(abs_delta, amount) / abs_delta * 100, 1) if abs_delta > 1e-6 else 0.0
        direction = "偏高" if delta > 0 else "偏低"
        out.append(
            {
                "source": label,
                "system_amount": round(amount, 2),
                "hint": f"若对方报价{direction}，可优先核对：{hint}",
                "coverage_pct": coverage,
            }
        )
    if compare_field == "exw_price" and margin > 0:
        # 粗算：毛利差 1% 对 EXW 的敏感度 ≈ cost/(1-m)^2 * 0.01
        sens = cost / max((1 - margin) ** 2, 1e-6) * 0.01
        if sens > 0.01:
            out.append(
                {
                    "source": "毛利率敏感",
                    "system_amount": round(sens, 2),
                    "hint": f"当前毛利约{margin*100:.0f}%；毛利每差 1 个点，EXW 约差 {sens:.2f} 元/件",
                    "coverage_pct": round(min(abs_delta, sens * 5) / abs_delta * 100, 1) if abs_delta else 0,
                }
            )
    return out


def _packaging_subtotal(quote: dict[str, Any]) -> float:
    detail_rows = quote.get("detail_rows")
    if not isinstance(detail_rows, list):
        return 0.0
    pack_re = re.compile(r"包装|纸箱|外箱|OPP|胶袋|封箱|箱子", re.I)
    total = 0.0
    for row in detail_rows:
        if not isinstance(row, dict):
            continue
        if not pack_re.search(str(row.get("name") or "")):
            continue
        total += _float_or(row.get("amount"))
    return round(total, 2)


def _collect_system_estimates(quote: dict[str, Any]) -> list[dict[str, Any]]:
    detail_rows = quote.get("detail_rows")
    if not isinstance(detail_rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in detail_rows:
        if not isinstance(row, dict):
            continue
        if _row_is_system_estimate(row):
            out.append(
                {
                    "name": str(row.get("name") or "-"),
                    "unit_price": str(row.get("unit_price") or "-"),
                    "amount": _float_or(row.get("amount")),
                    "note": _human_source_line(row),
                }
            )
    return out


def _collect_missing_or_pending(quote: dict[str, Any]) -> list[dict[str, Any]]:
    detail_rows = quote.get("detail_rows")
    if not isinstance(detail_rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in detail_rows:
        if not isinstance(row, dict):
            continue
        if _row_is_missing_or_pending(row):
            out.append(
                {
                    "name": str(row.get("name") or "-"),
                    "unit_price": str(row.get("unit_price") or "-"),
                    "usage": str(row.get("usage") or "-"),
                    "note": "缺少有效单价或小计，报价以兜底/人工补全为准",
                }
            )
    notice = str(quote.get("data_notice") or "").strip()
    if notice:
        out.append({"name": "(数据提示)", "unit_price": "-", "usage": "-", "note": notice[:200]})
    return out


def _build_external_comparison(
    quote: dict[str, Any],
    user_question: str,
) -> dict[str, Any] | None:
    labeled = _parse_labeled_amounts(user_question)
    if not labeled:
        return None
    field = _pick_system_price_field(user_question)
    system_amt, system_text, tier = _system_reference_price(quote, field=field)

    external_amt: float | None = None
    external_label = "对方/业务员"
    for item in labeled:
        if item.get("role") == "external":
            external_amt = _float_or(item.get("amount"))
            break
    if external_amt is None:
        for item in labeled:
            if item.get("role") != "system":
                external_amt = _float_or(item.get("amount"))
                break
    if external_amt is None and len(labeled) >= 2:
        amounts = [_float_or(x.get("amount")) for x in labeled]
        external_amt = max(amounts)
        system_amt = min(amounts)
    elif external_amt is None and len(labeled) == 1:
        external_amt = _float_or(labeled[0].get("amount"))
    if external_amt <= 0:
        return None

    # 若用户明确写出系统侧数字，优先采用话术中的系统价
    for item in labeled:
        if item.get("role") == "system" and _float_or(item.get("amount")) > 0:
            system_amt = round(_float_or(item.get("amount")), 4)
            break

    delta = round(external_amt - system_amt, 2)
    return {
        "external_label": external_label,
        "external_amount": external_amt,
        "external_amount_text": f"{external_amt:.2f}元/件",
        "system_amount": system_amt,
        "system_amount_text": system_text or f"{system_amt:.2f}元/件",
        "system_field": field,
        "delta": delta,
        "delta_text": f"{delta:+.2f}元/件",
        "tier_quantity": tier.get("quantity"),
        "possible_sources": rank_gap_source_hypotheses(quote, delta=delta, compare_field=field),
    }


def explain_quote_difference(
    quote: dict[str, Any],
    *,
    user_question: str = "",
    price_kb_sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    报价解释模式：只读上一单 quote_result，不重新 calculate_quote。
    返回结构化拆解 + 自然语言 assistant_message。
    """
    if not isinstance(quote, dict) or quote.get("error"):
        err = str(quote.get("error") or "当前没有可解释的报价结果。").strip()
        return {
            "explain_mode": True,
            "assistant_message": f"当前无法解释报价：{err}",
            "amount_breakdown": [],
            "gap_sources_ranked": [],
            "system_estimates": [],
            "missing_or_pending": [],
            "external_comparison": None,
        }

    uq = str(user_question or "").strip()
    tier = _first_tier(quote)
    breakdown = build_amount_breakdown(quote)
    materials_ranked = rank_material_rows_by_amount(quote)
    estimates = _collect_system_estimates(quote)
    pending = _collect_missing_or_pending(quote)
    external = _build_external_comparison(quote, uq)
    bridge = quote.get("cost_bridge") if isinstance(quote.get("cost_bridge"), dict) else {}
    settings = quote.get("settings") if isinstance(quote.get("settings"), dict) else {}

    gap_ranked = (
        list(external.get("possible_sources") or [])
        if isinstance(external, dict)
        else rank_gap_source_hypotheses(quote, delta=0.0)
    )

    lines: list[str] = []
    product = str(quote.get("product_name") or "").strip() or "当前报价单"
    lines.append(f"以下说明基于上一单「{product}」已有报价结果，未重新跑报价、未改价格库。")

    if external:
        lines.append(
            f"对比：{external.get('external_label', '对方')} {external['external_amount_text']}，"
            f"系统 {external['system_amount_text']}，差额 {external['delta_text']}。"
        )
        if external.get("delta", 0) > 0:
            lines.append("对方报价更高，常见原因是加工费、包装、面料用量/单价、模具分摊件数或毛利口径不同。")
        elif external.get("delta", 0) < 0:
            lines.append("系统报价更高，常见原因是系统按标价库/规则估高了某项，或对方未摊入模具/杂费。")
        for i, src in enumerate(gap_ranked[:4], start=1):
            lines.append(
                f"{i}. {src.get('source')}（系统约 {src.get('system_amount')} 元/件）：{src.get('hint')}"
            )
    else:
        field = _pick_system_price_field(uq)
        sys_amt, sys_text, _ = _system_reference_price(quote, field=field)
        lines.append(f"系统首档 {sys_text or f'{sys_amt:.2f}元/件'}（口径：{field}）。")

    if re.search(r"加工费", uq) and _COMPONENT_EXPLAIN_RE.search(uq):
        proc = _float_or(tier.get("processing_fee"), settings.get("processing_fee"))
        lines.append(
            f"加工费：每件 {proc:.2f} 元，来自需求表/报价设置（payload.processing_fee），"
            f"计入毛利前成本，不重复摊进物料行。"
        )

    if re.search(r"(哪个|哪项).*(材料|物料).*(差距|差|大|贵)", uq):
        if materials_ranked:
            top = materials_ranked[0]
            lines.append(
                f"物料行里金额最大的是「{top['name']}」约 {top['amount_text']}（占物料约 {top['share_pct']}%）。"
            )
            if len(materials_ranked) > 1:
                second = materials_ranked[1]
                lines.append(
                    f"其次「{second['name']}」约 {second['amount_text']}（{second['share_pct']}%）。"
                )
        else:
            lines.append("当前明细行里没有可排序的物料金额。")

    lines.append(
        "单件拆解：物料 "
        f"{_float_or(quote.get('material_total')):.2f} + 加工 {_float_or(tier.get('processing_fee')):.2f} + "
        f"杂费 {_float_or(bridge.get('system_overhead_per_pc'), settings.get('system_overhead')):.2f} + "
        f"开模 {_float_or(tier.get('mold_share')):.2f} = 成本 {_float_or(tier.get('cost_before_margin')):.2f} → "
        f"EXW {_float_or(tier.get('exw_price')):.2f}。"
    )

    if estimates:
        names = "、".join(e["name"] for e in estimates[:4])
        lines.append(f"系统估算项（非标价库命中）：{names}。")
    if pending:
        lines.append(f"待确认/缺失项 {len(pending)} 条，建议先补齐再与业务员口径对齐。")

    if isinstance(price_kb_sync, dict) and not price_kb_sync.get("error"):
        lines.append("标价库同步：本单报价时已尝试匹配 price_kb（详见 price_kb_sync）。")

    if re.search(r"为什么|为何|为啥", uq) and not external:
        m = _AMOUNT_IN_TEXT_RE.search(uq)
        if m:
            try:
                asked = float(m.group(1))
                field = _pick_system_price_field(uq)
                sys_amt, _, _ = _system_reference_price(quote, field=field)
                diff = round(asked - sys_amt, 2)
                lines.append(
                    f"您提到的 {asked:g} 元/件，与系统 {field} {sys_amt:.2f} 元/件相差 {diff:+.2f} 元/件。"
                )
            except (TypeError, ValueError):
                pass

    return {
        "explain_mode": True,
        "assistant_message": "\n".join(lines),
        "amount_breakdown": breakdown,
        "material_rows_ranked": materials_ranked,
        "gap_sources_ranked": gap_ranked,
        "system_estimates": estimates,
        "missing_or_pending": pending,
        "external_comparison": external,
        "cost_bridge": bridge,
        "settings_snapshot": {
            "processing_fee": settings.get("processing_fee"),
            "system_overhead": settings.get("system_overhead"),
            "mold_fee": settings.get("mold_fee"),
            "gross_margin_rate_text": settings.get("gross_margin_rate_text"),
        },
        "price_kb_sync": price_kb_sync if isinstance(price_kb_sync, dict) else None,
        "cost_overview": build_cost_overview(quote),
    }


def build_explain_response_payload(
    quote: dict[str, Any],
    *,
    user_question: str = "",
    price_kb_sync: dict[str, Any] | None = None,
    llm_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """API 兼容：解释模式响应信封。"""
    body = explain_quote_difference(
        quote,
        user_question=user_question,
        price_kb_sync=price_kb_sync,
    )
    sync = price_kb_sync
    if sync is None and isinstance(quote, dict):
        sync = quote.get("price_kb_sync") if isinstance(quote.get("price_kb_sync"), dict) else None
    status = dict(llm_status or {})
    status["agent"] = "quote_explain_local"
    status["explain_mode"] = True
    return {
        "quote_ready": False,
        "intent": "QUOTE_EXPLAIN",
        "reply_type": "quote_explain",
        "assistant_message": _polish_quote_explain_message(body.get("assistant_message") or ""),
        "quote_explanation": body,
        "llm_status": status,
    }


def build_local_quote_explanation_text(
    quote: dict[str, Any],
    *,
    user_question: str = "",
    advisory_error: str = "",
) -> str:
    """不用 LLM 的报价口径说明；数字只来自已有 ``calculate_quote`` 结果。"""
    body = explain_quote_difference(quote, user_question=user_question)
    text = _polish_quote_explain_message(body.get("assistant_message") or "")
    if advisory_error:
        return f"模型口述暂时不可用，我先按本地核算结果说明。\n{text}"
    if text:
        return text
    return "当前没有可解释的报价结果。"


def _polish_quote_explain_message(message: object) -> str:
    """Keep quote explanations business-facing and avoid internal routing jargon."""
    text = str(message or "").strip()
    if not text:
        return ""
    replacements = {
        "以下说明基于上一单": "本说明基于当前已保存报价",
        "未重新跑报价、未改价格库": "本次只解释计算来源，未重新核价，未写入价格库",
        "口径：": "价格字段：",
        "（口径：": "（价格字段：",
        "毛利口径": "毛利计算方式",
        "含税口径": "含税计算方式",
        "业务员口径对齐": "业务员核价方式对齐",
        "面料用量/单价口径不同": "面料用量或单价取值不同",
        "毛利点数或倒推公式不同": "毛利率或倒推公式不同",
        "系统首档": "当前首档报价",
        "常见原因是": "重点核对项为",
        "以下说明": "价格构成说明",
        "上一单": "当前报价单",
        "模型不可用": "当前无法提供详细说明",
        "API key": "",
        "API Key": "",
        "API_KEY": "",
        "price_kb_sync": "标价库匹配记录",
        "price_kb": "标价库",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"（?口径[：:]?[^）]*）?", "", text)
    text = re.sub(r"模型[^，。]*?不可用", "暂无详细数据", text)
    return text


def compact_quote_bridge(quote: dict[str, Any], *, file_hint: str) -> str:
    """Short JSON excerpt for advisory LLM context."""
    tiers = quote.get("tiers")
    tiers_brief = []
    if isinstance(tiers, list):
        for tier in tiers[:5]:
            if not isinstance(tier, dict):
                continue
            tiers_brief.append(
                {
                    "qty": tier.get("quantity_text"),
                    "cost_piece": tier.get("cost_before_margin_text"),
                    "margin": tier.get("margin_rate_text"),
                    "exw": tier.get("exw_price_text"),
                    "fob": tier.get("fob_price_text"),
                }
            )
    snippet = {
        "file_hint": file_hint or "",
        "product_name": quote.get("product_name"),
        "consultant_summary": quote.get("consultant_summary"),
        "material_total_text": quote.get("material_total_text"),
        "system_cost_text": quote.get("system_cost_text"),
        "data_notice": quote.get("data_notice"),
        "first_tiers": tiers_brief,
        "detail_sample": [],
    }
    rows = quote.get("detail_rows")
    if isinstance(rows, list):
        for row in rows[:16]:
            if not isinstance(row, dict):
                continue
            snippet["detail_sample"].append(
                {
                    "name": row.get("name"),
                    "spec": row.get("spec"),
                    "usage": row.get("usage"),
                    "unit_price": row.get("unit_price"),
                    "amount_text": row.get("amount_text"),
                    "source": row.get("source"),
                    "kb_hit": row.get("kb_hit"),
                }
            )
    return json.dumps(snippet, ensure_ascii=False)
