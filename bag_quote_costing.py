"""包类报价 skill 运行时：识别、复杂度、漏项保护、低估校验、LLM 规则注入。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bag_structure_list import build_bag_structure_checklist, structure_checklist_high_codes

SKILL_NAME = "bag-quote-costing"
SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "bag-quote-costing"

_BAG_TYPE_KEYWORDS = (
    "背包",
    "旅行包",
    "登山包",
    "腰包",
    "工具包",
    "手提包",
    "收纳包",
    "防水包",
    "斜挎包",
    "胸包",
    "驮包",
    "双肩包",
    "单肩包",
    "邮差包",
    "backpack",
    "daypack",
    "duffel",
    "messenger",
    "sling",
    "waist pack",
    "tool bag",
    "rucksack",
)

_COMPLEXITY_COMPLEX_HINTS = (
    "顶包",
    "翻盖",
    "腰封",
    "背负系统",
    "三明治",
    "三明治网布",
    "弹力绳",
    "调节织带",
    "多拉链",
    "补强",
    "胸扣",
    "背垫",
    "水袋仓",
    "电脑仓",
    "隔层",
    "压胶",
    "热压",
)
_COMPLEXITY_MEDIUM_HINTS = (
    "前袋",
    "侧袋",
    "肩带",
    "提手",
    "里布",
    "内袋",
    "织带",
    "插扣",
    "拉链袋",
    "水壶",
)

_LEAK_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("肩带", ("肩带", "背带", "背负带")),
    ("背垫", ("背垫", "背板", "海绵背")),
    ("腰封", ("腰封", "腰带")),
    ("顶包", ("顶包", "顶袋", "顶盖")),
    ("翻盖", ("翻盖", "盖片")),
    ("前袋", ("前袋", "前仓", "正面袋")),
    ("侧袋", ("侧袋", "侧仓", "侧兜")),
    ("水壶袋", ("水壶袋", "水袋仓", "水瓶袋")),
    ("网袋", ("网袋", "网兜", "网布袋")),
    ("三明治网布", ("三明治", "三明治网布")),
    ("弹力绳", ("弹力绳", "弹性绳", " shock cord")),
    ("织带", ("织带", "尼龙带", "包边带")),
    ("插扣", ("插扣", " buckle", "扣具")),
    ("胸扣", ("胸扣", " sternum")),
    ("D环", ("d环", "d扣", "拉环")),
    ("补强", ("补强", "补强片", "耐磨片")),
    ("拉链袋", ("拉链袋", "拉链仓")),
    ("包边", ("包边", "滚边")),
    ("调节扣", ("调节扣", "日字扣", "梯扣")),
)

_COST_MODULES: tuple[dict[str, Any], ...] = (
    {"id": "main_body", "label": "主包主体", "terms": ("前幅", "后幅", "侧片", "底片", "顶片", "主料", "面料", "外料", "底料")},
    {"id": "external", "label": "外部结构", "terms": ("前袋", "侧袋", "水壶", "顶包", "翻盖", "外袋")},
    {"id": "carry", "label": "背负结构", "terms": ("肩带", "背带", "背垫", "腰封", "胸扣", "背负")},
    {"id": "internal", "label": "内部结构", "terms": ("里布", "里料", "内袋", "隔层", "电脑仓")},
    {"id": "accessory", "label": "辅料配件", "terms": ("拉链", "拉头", "插扣", "调节扣", "d环", "绳扣", "织带", "包边", "弹力绳")},
    {"id": "functional", "label": "功能材料", "terms": ("网布", "三明治", "补强", "防水膜", "反光")},
    {"id": "process", "label": "工艺费用", "terms": ("加工", "车缝", "包边工", "压胶", "热压", "印刷", "工艺")},
    {"id": "loss", "label": "损耗费用", "terms": ("损耗", "裁剪损", "结构损")},
    {"id": "packaging", "label": "包装费用", "terms": ("包装", "纸箱", "opp", "吊牌", "说明卡")},
    {"id": "amortization", "label": "摊销费用", "terms": ("模具", "刀模", "开料模", "五金模", "塑胶模", "摊销")},
)

_MIN_ITEM_COUNT = {"simple": 8, "medium": 12, "complex": 18}
_MIN_MATERIAL_TOTAL = {"simple": 12.0, "medium": 28.0, "complex": 55.0}

_MAIN_FABRIC_HINTS = ("面料", "外料", "主料", "里布", "里料", "尼龙", "涤纶", "牛津", "帆布", "x-pac", "dcf")


@dataclass(frozen=True)
class BagQuoteContext:
    is_bag: bool
    bag_category: str = ""
    complexity: str = "medium"
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    skill_name: str = SKILL_NAME


def _norm(text: object) -> str:
    return str(text or "").strip().lower()


def _blob(*parts: object) -> str:
    return " ".join(str(p or "") for p in parts if str(p or "").strip())


def detect_bag_product(
    *,
    product_type: str = "",
    product_name: str = "",
    structure_text: str = "",
    user_prompt: str = "",
) -> BagQuoteContext:
    blob = _norm(_blob(product_type, product_name, structure_text, user_prompt))
    matched = [kw for kw in _BAG_TYPE_KEYWORDS if kw.lower() in blob]
    structure_bag = any(
        token in blob
        for token in (
            "肩带",
            "前袋",
            "侧袋",
            "顶包",
            "腰封",
            "背负",
            "里布",
            "拉链袋",
            "backpanel",
        )
    )
    is_bag = bool(matched) or structure_bag
    category = ""
    if matched:
        category = matched[0]
    elif structure_bag:
        category = "包类（结构识别）"
    complexity = classify_bag_complexity(structure_text or user_prompt, product_type=product_type)
    return BagQuoteContext(
        is_bag=is_bag,
        bag_category=category,
        complexity=complexity,
        matched_keywords=tuple(matched[:6]),
    )


def _hint_in_text(hint: str, blob: str) -> bool:
    token = hint.lower()
    if token not in blob:
        return False
    if f"无{hint}" in blob or f"不含{hint}" in blob or f"没有{hint}" in blob:
        return False
    return True


def classify_bag_complexity(structure_text: str = "", product_type: str = "") -> str:
    blob = _norm(_blob(structure_text, product_type))
    if not blob:
        return "medium"
    complex_hits = sum(1 for k in _COMPLEXITY_COMPLEX_HINTS if _hint_in_text(k, blob))
    medium_hits = sum(1 for k in _COMPLEXITY_MEDIUM_HINTS if _hint_in_text(k, blob))
    if complex_hits >= 2 or ("背负" in blob and "腰封" in blob):
        return "complex"
    if complex_hits >= 1 or medium_hits >= 2:
        return "medium"
    if medium_hits >= 1:
        return "medium"
    if any(k in blob for k in ("单仓", "简单", "基础款")):
        return "simple"
    return "simple" if len(blob) < 40 else "medium"


def _row_names_blob(rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parts.append(str(row.get("name") or ""))
        parts.append(str(row.get("role") or ""))
        parts.append(str(row.get("calc_note") or ""))
    return _norm(" ".join(parts))


def _row_matches_any(text: str, terms: tuple[str, ...]) -> bool:
    low = _norm(text)
    return any(t.lower() in low for t in terms)


def _modules_covered(rows: list[dict[str, Any]]) -> dict[str, bool]:
    names_blob = _row_names_blob(rows)
    out: dict[str, bool] = {}
    for mod in _COST_MODULES:
        out[mod["id"]] = _row_matches_any(names_blob, mod["terms"])
    return out


def check_leak_risks(structure_text: str, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    struct = str(structure_text or "")
    if not struct.strip():
        return []
    names_blob = _row_names_blob(rows)
    risks: list[dict[str, str]] = []
    for label, synonyms in _LEAK_KEYWORDS:
        if not any(_structure_mentions_keyword(struct, (s,)) for s in synonyms):
            continue
        if not any(s.lower() in names_blob for s in synonyms):
            risks.append(
                {
                    "keyword": label,
                    "reason": f"结构说明含「{label}」但明细未见对应成本项",
                    "severity": "high",
                }
            )
    return risks


def _structure_mentions_keyword(struct: str, synonyms: tuple[str, ...]) -> bool:
    for s in synonyms:
        if s not in struct:
            continue
        if f"无{s}" in struct or f"不含{s}" in struct or f"没有{s}" in struct:
            continue
        return True
    return False


def check_underestimation_risks(
    *,
    ctx: BagQuoteContext,
    rows: list[dict[str, Any]],
    structure_text: str = "",
    material_total: float | None = None,
) -> list[dict[str, str]]:
    if not ctx.is_bag:
        return []
    risks: list[dict[str, str]] = []
    count = len([r for r in rows if isinstance(r, dict) and str(r.get("name") or "").strip()])
    min_count = _MIN_ITEM_COUNT.get(ctx.complexity, 12)
    if count < min_count:
        risks.append(
            {
                "code": "bag_too_few_line_items",
                "reason": f"{ctx.complexity} 包类明细仅 {count} 行，低于合理下限 {min_count}",
                "severity": "high",
            }
        )

    covered = _modules_covered(rows)
    essential = ("main_body", "accessory", "process", "packaging")
    missing_mods = [m["label"] for m in _COST_MODULES if m["id"] in essential and not covered.get(m["id"])]
    if missing_mods:
        risks.append(
            {
                "code": "bag_missing_core_modules",
                "reason": f"缺少核心模块：{'、'.join(missing_mods)}",
                "severity": "high",
            }
        )

    if ctx.complexity == "complex" and covered.get("main_body") and not covered.get("carry"):
        risks.append(
            {
                "code": "bag_complex_missing_carry",
                "reason": "复杂包类未见背负/肩带相关成本项",
                "severity": "high",
            }
        )

    if material_total is not None:
        floor = _MIN_MATERIAL_TOTAL.get(ctx.complexity, 28.0)
        if material_total < floor:
            risks.append(
                {
                    "code": "bag_material_total_low",
                    "reason": f"物料合计 {material_total:.2f} 元低于 {ctx.complexity} 包类经验下限约 {floor:.0f} 元",
                    "severity": "high",
                }
            )

    main_rows = [
        r
        for r in rows
        if isinstance(r, dict) and any(h in _norm(r.get("name")) for h in _MAIN_FABRIC_HINTS)
    ]
    if main_rows and ctx.complexity in {"medium", "complex"}:
        tiny_main = 0
        for r in main_rows:
            usage = str(r.get("usage") or "")
            m = re.search(r"(\d+(?:\.\d+)?)", usage)
            if m and float(m.group(1)) < 0.15:
                tiny_main += 1
        if tiny_main >= max(1, len(main_rows) // 2):
            risks.append(
                {
                    "code": "bag_main_fabric_usage_small",
                    "reason": "主体面料用量相对袋型偏小，疑似仅用外包络粗算",
                    "severity": "medium",
                }
            )

    ai_rows = [
        r
        for r in rows
        if isinstance(r, dict)
        and (
            r.get("usage_ai")
            or r.get("unit_price_ai")
            or r.get("amount_ai")
            or r.get("ai_filled")
        )
    ]
    if len(ai_rows) >= max(3, count // 2):
        risks.append(
            {
                "code": "bag_heavy_ai_fill",
                "reason": f"明细中 {len(ai_rows)}/{count} 行含 AI 补全字段，需人工确认",
                "severity": "medium",
            }
        )

    leak = check_leak_risks(structure_text, rows)
    for item in leak:
        risks.append(
            {
                "code": "bag_structure_keyword_missing",
                "reason": item["reason"],
                "severity": item["severity"],
            }
        )
    return risks


def annotate_bag_cost_rows(
    rows: list[dict[str, Any]],
    *,
    structure_text: str = "",
) -> list[dict[str, Any]]:
    """为明细行补充包类 skill 要求的追溯字段。"""
    struct = str(structure_text or "")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        name = str(r.get("name") or "").strip()
        ai_est = bool(r.get("usage_ai") or r.get("unit_price_ai") or r.get("amount_ai") or r.get("ai_filled"))
        r["is_ai_estimate"] = ai_est
        r["needs_human_confirm"] = bool(ai_est or r.get("needs_human_confirm"))
        if not str(r.get("source_structure_desc") or "").strip() and struct and name:
            snippet = _find_structure_snippet(struct, name)
            if snippet:
                r["source_structure_desc"] = snippet
        if ai_est and not str(r.get("risk_note") or "").strip():
            r["risk_note"] = "AI 估算，建议人工复核用量/单价"
        out.append(r)
    return out


def _find_structure_snippet(structure_text: str, material_name: str) -> str:
    name = str(material_name or "").strip()
    if not name or len(name) < 2:
        return ""
    for line in re.split(r"[\n；;。]", structure_text):
        text = line.strip()
        if not text:
            continue
        if name[:2] in text or any(k in text for k in name.split() if len(k) >= 2):
            return text[:120]
    return ""


def load_skill_markdown() -> str:
    path = SKILL_ROOT / "SKILL.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_skill_reference(name: str) -> str:
    """读取 references/*.md，供 agent 或调试加载详细规则。"""
    safe = Path(name).name
    path = SKILL_ROOT / "references" / safe
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def resolve_bag_quote_skill(
    *,
    product_type: str = "",
    product_name: str = "",
    structure_text: str = "",
    user_prompt: str = "",
) -> dict[str, Any]:
    """报价 agent 入口：识别包类并返回 skill 元数据（未命中则 active=false）。"""
    ctx = detect_bag_product(
        product_type=product_type,
        product_name=product_name,
        structure_text=structure_text,
        user_prompt=user_prompt,
    )
    if not ctx.is_bag:
        return {"active": False, "skill": SKILL_NAME}
    return {
        "active": True,
        "skill": SKILL_NAME,
        "skill_path": str(SKILL_ROOT),
        "is_bag_product": True,
        "bag_category": ctx.bag_category,
        "complexity": ctx.complexity,
        "matched_keywords": list(ctx.matched_keywords),
        "references": {
            "component_model": "references/component-model.md",
            "estimation_rules": "references/estimation-rules.md",
            "risk_checks": "references/risk-checks.md",
        },
        "minimum_line_items": _MIN_ITEM_COUNT.get(ctx.complexity, 12),
    }


def build_llm_system_prompt_addon(ctx: BagQuoteContext, structure_text: str = "") -> str:
    if not ctx.is_bag:
        return ""
    min_lines = _MIN_ITEM_COUNT.get(ctx.complexity, 12)
    return (
        f"\n【项目 skill · {SKILL_NAME} · 包类报价严谨拆解与低估防护】\n"
        f"已识别：{ctx.bag_category or '包类'}；复杂度 **{ctx.complexity}**。"
        "须按 skill 流程执行：结构拆解 → 成本项生成 → 风险校验 → 输出明细。\n"
        "详细规则见 skills/bag-quote-costing/references/（component-model / estimation-rules / risk-checks）。\n"
        "禁止：L×W×H 外包络粗算全部主料、Excel/历史单硬编码、业务员表格反推、忽略主要部件。\n"
        f"本款至少 **{min_lines}** 条有效成本行；模块须覆盖：主体裁片、外结构、背负/提手（如有）、"
        "内部里布、辅料配件、功能材（如有）、工艺、损耗、包装、摊销（如有）。\n"
        "缺尺寸：usage_ai/unit_price_ai=true，calc_note 写清依据；每行尽量填 source_structure_desc。\n"
        "结构词（肩带/腰封/顶包/前袋/网布/织带/插扣等）须在 rows 有对应行；否定表述（无肩带）除外。\n"
        + (f"结构摘要：{structure_text[:800]}\n" if structure_text else "")
    )


def build_bag_quote_report(
    *,
    ctx: BagQuoteContext,
    rows: list[dict[str, Any]],
    structure_text: str = "",
    material_total: float | None = None,
) -> dict[str, Any]:
    modules = _modules_covered(rows)
    risks = check_underestimation_risks(
        ctx=ctx,
        rows=rows,
        structure_text=structure_text,
        material_total=material_total,
    )
    high = [r for r in risks if r.get("severity") == "high"]
    review_required = bool(high)
    return {
        "skill": SKILL_NAME,
        "is_bag_product": ctx.is_bag,
        "bag_category": ctx.bag_category,
        "complexity": ctx.complexity,
        "modules_covered": modules,
        "line_item_count": len([r for r in rows if isinstance(r, dict)]),
        "minimum_line_items": _MIN_ITEM_COUNT.get(ctx.complexity, 12),
        "leak_risks": check_leak_risks(structure_text, rows),
        "underestimation_risks": risks,
        "review_required": review_required,
        "review_label": "需人工复核" if review_required else "",
    }


def enrich_pricing_gate_for_bag_quote(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """包类低估/漏项 → 合并进 pricing_gate 高风险码。"""
    structure_text = str(
        payload.get("structure_text_snapshot")
        or payload.get("structure_text")
        or ""
    ).strip()
    product_type = str(payload.get("product_type") or "").strip()
    product_name = str(payload.get("product_name") or result.get("product_name") or "").strip()
    user_prompt = str(payload.get("user_prompt") or payload.get("prompt") or "").strip()

    ctx = detect_bag_product(
        product_type=product_type,
        product_name=product_name,
        structure_text=structure_text,
        user_prompt=user_prompt,
    )
    if not ctx.is_bag:
        return {"high_codes": [], "report": None}

    rows = result.get("detail_rows")
    if not isinstance(rows, list):
        rows = payload.get("items") if isinstance(payload.get("items"), list) else []

    try:
        material_total = float(result.get("material_total"))
    except (TypeError, ValueError):
        material_total = None

    report = build_bag_quote_report(
        ctx=ctx,
        rows=rows,
        structure_text=structure_text,
        material_total=material_total,
    )

    existing_checklist = payload.get("structure_checklist")
    existing_items = None
    patch_items = payload.get("structure_checklist_patches")
    if isinstance(patch_items, list) and patch_items:
        existing_items = patch_items
    elif isinstance(existing_checklist, dict):
        existing_items = existing_checklist.get("items")
    elif isinstance(payload.get("structure_items"), list):
        existing_items = payload.get("structure_items")

    structure_checklist = build_bag_structure_checklist(
        ctx=ctx,
        structure_text=structure_text,
        detail_rows=rows if isinstance(rows, list) else [],
        existing_items=existing_items if isinstance(existing_items, list) else None,
    )
    result["structure_checklist"] = structure_checklist
    result["structure_items"] = structure_checklist.get("items") or []

    result["bag_quote_costing"] = report
    result["bag_quote_skill"] = {
        "active": True,
        "skill": SKILL_NAME,
        "skill_path": str(SKILL_ROOT),
    }

    high_codes: list[str] = []
    for risk in report.get("underestimation_risks") or []:
        if risk.get("severity") == "high":
            code = str(risk.get("code") or "bag_quote_risk")
            high_codes.append(code)

    high_codes.extend(structure_checklist_high_codes(structure_checklist))
    from bag_quote_pipeline import pipeline_high_codes

    high_codes.extend(pipeline_high_codes(structure_text, structure_checklist))
    from material_inference import append_inferred_data_notice, inference_high_risk_codes

    items = payload.get("items") if isinstance(payload.get("items"), list) else rows
    inf_report = payload.get("material_inference_report")
    high_codes.extend(inference_high_risk_codes(inf_report if isinstance(inf_report, dict) else None, items))
    high_codes = sorted(set(high_codes))

    if inference_high_risk_codes(inf_report if isinstance(inf_report, dict) else None, items):
        result["data_notice"] = append_inferred_data_notice(str(result.get("data_notice") or ""), items)

    if report.get("review_required"):
        result["bag_quote_review_required"] = True
        gate = result.get("pricing_gate")
        if isinstance(gate, dict):
            gate["bag_quote_review_required"] = True
            gate["bag_quote_review_label"] = "需人工复核"
    return {"high_codes": high_codes, "report": report}
