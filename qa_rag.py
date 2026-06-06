"""轻量 RAG 答疑：价格库 / 历史报价 / 本地文档检索，不进入 calculate_quote。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib import error

SourceType = Literal["price_kb", "quote_history", "docs", "llm", "fallback"]

ROOT = Path(__file__).resolve().parent
README_PATH = ROOT / "README.md"

_PRICE_LOOKUP_RE = re.compile(
    r"(多少钱|什么价|啥价|多少价|单价多少|价格多少|怎么卖)",
    re.I,
)
_ADMIN_HOWTO_RE = re.compile(
    r"(价格库|知识库|后台).{0,12}(怎么|如何|怎样|更新|修改|导入|操作|改|维护|管理)"
    r"|(怎么|如何).{0,12}(价格库|知识库|后台)"
    r"|后台.{0,8}(怎么用|如何使用|操作步骤)",
    re.I,
)
_MISSING_PRICE_RE = re.compile(
    r"(没有价格|没价格|暂无价格|价格库暂无|待补充|待补价|补价|找不到价|缺价)",
    re.I,
)
_PROCESS_MATERIAL_RE = re.compile(
    r"(是什么|什么材料|什么面料|工艺|做法|区别|用途|防水|耐磨|材质介绍|优缺点)",
    re.I,
)
_BACKPACK_CONSULT_RE = re.compile(
    r"(背包|旅行包|登山包|双肩包|腰包|工具包|收纳包|软包|包袋|定制|户外|出差|通勤|旅行|收纳|结构|版型|"
    r"肩带|背负|腰封|背垫|侧袋|顶包|翻盖|补强|包边|压胶|"
    r"面料|里料|辅料|拉链|扣具|织带|EVA|网布|防水|耐磨|轻量|减重|降本|替代|优化|建议|怎么做|怎么选|"
    r"适合|优缺点|区别|工艺|做法|材料|客户|报价贵|太贵|解释|话术|说服|异议|"
    r"打样|量产|MOQ|起订|交期|包装|运输|测试|驳回|审批|毛利|漏项|BOM|"
    r"缺价|补价|价格库)",
    re.I,
)

OEM_QA_SYSTEM_PROMPT_ACTIVE = (
    "你是“定制软包 OEM 报价业务顾问”，服务于自动报价系统的业务答疑支路。"
    "你熟悉旅行背包、登山包、腰包、工具包、户外软包、收纳包等产品的 OEM 定制流程，"
    "懂面料辅料、结构工艺、BOM 成本、打样量产、客户沟通、降本替代和报价风险。\n\n"
    "你的角色是帮助业务员理解和解释当前报价，不是重新报价。"
    "你只能基于系统提供的当前报价上下文和本地知识回答，包括：结构清单、成本明细、价格库命中、"
    "AI/市场估算项、风险提示、审批或待确认信息、报价汇总。上下文没有的数据，不要猜。\n\n"
    "只读边界：\n"
    "1. 不修改报价、不改价格库、不自动审批、不生成新的正式报价总价。\n"
    "2. 不编造单价、金额、供应商价格或交期；涉及价格只能引用上下文已有数据。\n"
    "3. AI估算、市场估算、缺价格、结构漏项、单位异常、风险项，都必须提示需要人工复核。\n"
    "4. 不暴露系统内部术语，不提 LLM、API、payload、quote_engine、Kimi、Claude、pricing_gate 等。\n"
    "5. 如果用户的问题其实需要重新计算，只说明“需要重新生成/重新计算后才能确认”，不要自己算正式结果。\n\n"
    "回答范围：\n"
    "- 报价解释：为什么贵/便宜、哪些成本拉高、哪些项目需复核。\n"
    "- 材料咨询：面料、里料、织带、拉链、扣具、EVA、网布、包边、包装等选型建议。\n"
    "- 结构工艺：肩带、腰封、背垫、侧袋、顶包、翻盖、补强、车缝、包边、压胶等影响成本和量产风险的点。\n"
    "- 降本替代：在不明显牺牲功能的前提下给替代方向，但不直接承诺降价数值。\n"
    "- 客户沟通：帮业务员把报价、涨价、缺价、风险、驳回原因转成客户能听懂的话术。\n"
    "- 操作建议：价格库缺价、AI估算、审批驳回、结构漏项时，告诉业务员下一步该补什么信息。\n\n"
    "回答风格：\n"
    "1. 先给结论，再给 2-4 条原因或建议。\n"
    "2. 像客服聊天，短、清楚、能直接拿去和客户/主管沟通。\n"
    "3. 不要长篇手册，不要堆概念。\n"
    "4. 用户没问规格表时，不输出规格表。\n"
    "5. 用户没明确查价时，不输出单价或成本参考。\n"
    "6. 信息不足时，先说当前能判断什么，再列出最多 3 个需要补充的关键参数。\n"
    "7. 如果当前报价有风险，语气要稳：说明“建议先复核”，不要吓人，也不要替系统背书说一定正确。\n"
    "8. 引用当前报价时，优先使用 quote_context 中的结构清单、成本行、AI估算行、价格库命中、风险项和汇总信息。"
)

OEM_QA_SYSTEM_PROMPT_GENERAL = (
    "你是“定制软包 OEM 报价业务顾问”，服务于自动报价系统的业务答疑支路。"
    "你熟悉旅行背包、登山包、腰包、工具包、户外软包、收纳包等 OEM 定制，"
    "懂面料辅料、结构工艺、BOM 成本、打样量产、客户沟通、降本替代、包装运输、MOQ/交期、测试要求和报价风险。\n\n"
    "当前没有绑定具体报价单。你可以回答材料、工艺、结构、客户沟通、降本思路、打样量产风险、"
    "价格库操作、缺价处理、审批驳回理解等通用业务问题，但不能假装知道这单的单价、总价或订单细节。\n\n"
    "只读边界：\n"
    "1. 这是答疑，不是正式报价；不要生成总价，不要要求用户上传表格，不要改写报价结果。\n"
    "2. 涉及价格时，只能引用上下文给出的价格库或历史报价；没有可靠数据必须明确说不能编价。\n"
    "3. AI估算、市场估算、缺价格、结构漏项、单位异常、风险项，都要提醒需人工复核。\n"
    "4. 不暴露系统内部术语，不提 LLM、API、payload、quote_engine、Kimi、Claude、pricing_gate 等。\n"
    "5. 遇到需要重新核算的问题，说明需重新生成报价后再确认，不要自己算正式结果。\n\n"
    "回答风格：\n"
    "1. 先给结论，再给 2-4 条原因或建议；像懂工厂、懂业务、懂成本的客服顾问。\n"
    "2. 默认 3-5 句话或 3-5 条短列表，不要长篇手册，不要堆概念。\n"
    "3. 用户没问规格表时，不输出规格表；用户没明确查价时，不输出单价或成本参考。\n"
    "4. 信息不足时，先说能判断的原则，再列出最多 3 个需要补充的关键参数。\n"
    "5. 材料和工艺建议要说明适用场景、优点、风险或取舍。"
)
_QUOTE_STRONG_RE = re.compile(
    r"(\d{1,7}\s*件|上传|BOM|表格|询价|帮我报|正式报价|生成报价)",
    re.I,
)
_ACTIVE_QUOTE_QA_RE = re.compile(
    r"(这单|当前报价|本单|这份报价|成本明细|结构清单|结构件|结构漏|漏项|"
    r"AI估算|市场估算|人工确认|人工复核|待复核|风险项|价格库命中|知识库命中|"
    r"为什么.*(?:高|低|贵|便宜|空|缺)|偏高|偏低|"
    r"客户.*(?:贵|解释|话术|异议)|这单.*(?:贵|解释)|觉得.*(?:贵|高)|"
    r"哪些.*(?:AI|估算|待核|待确认|风险|结构|人工复核|复核)|"
    r"(哪些|哪几|什么地方|哪些地方).*(?:人工复核|待复核|待确认|风险)|"
    r"下一步.*(?:补|填|确认)|单价.*(?:空|缺|没有|为何|为什么)|"
    r"驳回|审批.*(?:理解|原因|备注))",
    re.I,
)


_VAGUE_PRICE_SUBJECT_RE = re.compile(
    r"^(这个|这款|那张|此|它|本|该)\s*$",
    re.I,
)


def _qa_audit(
    route: str,
    *,
    provider: str = "",
    model: str = "",
    used: bool = False,
    error: str = "",
    fallback_reason: str = "",
) -> dict[str, Any]:
    allowed = {"price_kb", "docs", "llm", "fallback"}
    resolved = route if route in allowed else "fallback"
    return {
        "route": resolved,
        "provider": str(provider or ""),
        "model": str(model or ""),
        "used": bool(used),
        "error": str(error or ""),
        "fallback_reason": str(fallback_reason or ""),
    }


def _audit_route_for_source(source_type: str) -> str:
    if source_type == "price_kb":
        return "price_kb"
    if source_type in {"docs", "quote_history"}:
        return "docs"
    if source_type == "llm":
        return "llm"
    return "fallback"


def is_qa_price_lookup(text: str) -> bool:
    """材料单价查询（走 QA，不走正式报价）。"""
    s = str(text or "").strip()
    if not s or not _PRICE_LOOKUP_RE.search(s):
        return False
    if _QUOTE_STRONG_RE.search(s):
        return False
    if _ADMIN_HOWTO_RE.search(s) or _MISSING_PRICE_RE.search(s):
        return False
    material = _extract_material_query(s)
    if not material or _VAGUE_PRICE_SUBJECT_RE.match(material):
        return False
    return bool(re.search(r"[A-Za-z0-9#\-]{2,}|[\u4e00-\u9fff]{2,}", material))


def answer_qa(user_text: str, *, sid: str | None = None) -> dict[str, Any]:
    """
    答疑主入口。返回 API 兼容 dict（含 assistant_message、source_type、qa_sources）。
    sid 存在时尝试读取当前会话 active quote，供只读业务顾问引用。
    """
    text = str(user_text or "").strip()
    if not text:
        return _wrap("请具体说明想了解的材料、工艺或后台操作。", "fallback", [])

    quote_context = load_readonly_quote_context(sid)

    if _ADMIN_HOWTO_RE.search(text):
        return _answer_admin_howto(text)
    if _MISSING_PRICE_RE.search(text):
        return _answer_missing_price_flow(text)
    if is_qa_price_lookup(text):
        return _answer_price_lookup(text)

    if quote_context and _looks_like_active_quote_question(text):
        local = _answer_active_quote_local(text, quote_context)
        if local is not None:
            local["qa_quote_context"] = {"quote_id": quote_context.get("quote_id"), "used": True}
            return local
        seed = _answer_from_docs(text)
        llm_body = _answer_with_backpack_consultant(
            text,
            local_context=seed,
            quote_context=quote_context,
        )
        if llm_body is not None:
            llm_body["qa_quote_context"] = {"quote_id": quote_context.get("quote_id"), "used": True}
            return llm_body
        fallback = _answer_active_quote_local(text, quote_context) or _answer_fallback(text)
        fallback["qa_quote_context"] = {"quote_id": quote_context.get("quote_id"), "used": bool(quote_context)}
        return fallback

    if _looks_like_backpack_consulting_question(text):
        seed = _answer_from_docs(text)
        llm_body = _answer_with_backpack_consultant(
            text,
            local_context=seed,
            quote_context=quote_context,
        )
        if llm_body is not None:
            if quote_context:
                llm_body["qa_quote_context"] = {"quote_id": quote_context.get("quote_id"), "used": True}
            return llm_body
        return _answer_fallback(text)
    if _looks_like_material_name_only(text):
        return _answer_price_lookup(text)
    if _PROCESS_MATERIAL_RE.search(text):
        body = _answer_from_docs(text)
        if body.get("source_type") != "fallback":
            return body
        llm_body = _answer_with_backpack_consultant(
            text,
            local_context=body,
            quote_context=quote_context,
        )
        if llm_body is not None:
            if quote_context:
                llm_body["qa_quote_context"] = {"quote_id": quote_context.get("quote_id"), "used": True}
            return llm_body
    body = _answer_from_docs(text)
    if body.get("source_type") != "fallback":
        return body
    # 工艺/规则类：文档 + 价格库弱匹配
    kb_body = _answer_price_lookup(text, allow_weak=True)
    if kb_body.get("source_type") == "price_kb":
        return kb_body
    fallback = _answer_fallback(text)
    if _looks_like_backpack_consulting_question(text):
        llm_body = _answer_with_backpack_consultant(
            text,
            local_context=fallback,
            quote_context=quote_context,
        )
        if llm_body is not None:
            if quote_context:
                llm_body["qa_quote_context"] = {"quote_id": quote_context.get("quote_id"), "used": True}
            return llm_body
    return fallback


def _looks_like_active_quote_question(text: str) -> bool:
    s = str(text or "").strip()
    if not s or _QUOTE_STRONG_RE.search(s):
        return False
    if _ADMIN_HOWTO_RE.search(s) or _MISSING_PRICE_RE.search(s):
        return False
    if is_qa_price_lookup(s):
        return False
    return bool(_ACTIVE_QUOTE_QA_RE.search(s))


def _truthy_flag(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)) and value != 0:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _row_has_any_ai_flag(row: dict[str, Any]) -> bool:
    return any(_truthy_flag(row.get(k)) for k in ("spec_ai", "usage_ai", "unit_price_ai", "amount_ai"))


def _serialize_cost_row(row: dict[str, Any]) -> dict[str, Any]:
    ai_keys = ("spec_ai", "usage_ai", "unit_price_ai", "amount_ai")
    ai_flags = [k for k in ai_keys if _truthy_flag(row.get(k))]
    serialized: dict[str, Any] = {
        "name": str(row.get("name") or "").strip(),
        "spec": str(row.get("spec") or "-").strip() or "-",
        "usage": str(row.get("usage") or "-").strip() or "-",
        "unit_price": str(row.get("unit_price") or "-").strip() or "-",
        "amount": row.get("amount"),
        "amount_text": str(row.get("amount_text") or "").strip(),
        "source": str(row.get("source") or "").strip().lower(),
        "kb_hit": bool(row.get("kb_hit")),
        "kb_matched_name": str(row.get("kb_matched_name") or "").strip(),
        "kb_matched_spec": str(row.get("kb_matched_spec") or "").strip(),
        "ai_flags": ai_flags,
        "recognition_status": str(row.get("recognition_status") or "").strip(),
        "recognition_reason": str(row.get("recognition_reason") or "").strip(),
        "calc_note": str(row.get("calc_note") or row.get("calc_method") or "").strip()[:160],
        "needs_manual_confirm": bool(row.get("needs_human_confirm") or row.get("needs_manual_confirm")),
    }
    for k in ai_keys:
        serialized[k] = _truthy_flag(row.get(k))
    return serialized


def _summarize_structure_checklist(
    checklist: dict[str, Any] | None,
    cost_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(checklist, dict):
        return {"is_bag_product": False, "items": [], "extraction_leaks": [], "items_without_cost": []}
    items = checklist.get("items") if isinstance(checklist.get("items"), list) else []
    leaks = checklist.get("extraction_leaks") if isinstance(checklist.get("extraction_leaks"), list) else []
    slim_items: list[dict[str, Any]] = []
    without_cost: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        cost_ids = item.get("cost_item_ids") if isinstance(item.get("cost_item_ids"), list) else []
        slim_items.append(
            {
                "name": name,
                "category": str(item.get("category_label") or item.get("category") or "").strip(),
                "estimate_status": str(item.get("estimate_status") or "").strip(),
                "risk_level": str(item.get("risk_level") or "").strip(),
                "missing_fields": list(item.get("missing_fields") or [])[:6],
                "cost_item_count": len(cost_ids),
                "user_status": str(item.get("user_status") or "").strip(),
            }
        )
        if bool(item.get("affects_cost")) and not cost_ids and str(item.get("user_status") or "") != "ignored":
            without_cost.append(name)
    return {
        "is_bag_product": bool(checklist.get("is_bag_product")),
        "extraction_complete": bool(checklist.get("extraction_complete")),
        "items": slim_items[:40],
        "extraction_leaks": [
            str(x.get("keyword") or x.get("reason") or "").strip()
            for x in leaks[:12]
            if isinstance(x, dict)
        ],
        "items_without_cost": without_cost[:24],
        "cost_row_count": len(cost_rows),
    }


def _slim_pricing_gate(gate: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(gate, dict):
        return {}
    return {
        "requires_manual_confirm": bool(gate.get("requires_manual_confirm")),
        "confirmed": bool(gate.get("confirmed")),
        "high_risk_codes": list(gate.get("high_risk_codes") or [])[:16],
        "medium_risk_codes": list(gate.get("medium_risk_codes") or [])[:16],
        "ai_confidence": gate.get("ai_confidence"),
        "risk_summary": str(gate.get("risk_summary") or gate.get("summary") or "").strip()[:400],
    }


def _slim_price_kb_sync(sync: object) -> dict[str, Any]:
    if not isinstance(sync, dict):
        return {}
    items = sync.get("items") if isinstance(sync.get("items"), list) else []
    pending_raw = sync.get("pending")
    if isinstance(pending_raw, int):
        pending_count = pending_raw
    elif isinstance(pending_raw, list):
        pending_count = len(pending_raw)
    else:
        pending_count = 0
    slim_items: list[dict[str, str]] = []
    for x in items[:16]:
        if not isinstance(x, dict):
            continue
        slim_items.append(
            {
                "name": str(x.get("name") or x.get("raw_name") or "").strip(),
                "spec": str(x.get("spec") or x.get("raw_spec") or "").strip(),
                "price": str(x.get("price") or x.get("unit_price") or x.get("raw_price") or "").strip(),
                "status": str(x.get("status") or "").strip(),
                "marker": str(x.get("marker") or "").strip(),
            }
        )
    out: dict[str, Any] = {
        "created": int(sync.get("created") or 0),
        "pending": pending_count,
        "conflicts": int(sync.get("conflicts") or 0),
        "skipped": int(sync.get("skipped") or 0),
        "dropped": int(sync.get("dropped") or 0),
        "items_count": len(items),
        "items_sample": slim_items,
    }
    matched_legacy = sync.get("matched") if isinstance(sync.get("matched"), list) else []
    if matched_legacy:
        out["legacy_matched_count"] = len(matched_legacy)
        out["legacy_matched_sample"] = [
            {
                "name": str(x.get("name") or x.get("raw_name") or "").strip(),
                "unit_price": str(x.get("unit_price") or x.get("raw_price") or "").strip(),
            }
            for x in matched_legacy[:12]
            if isinstance(x, dict)
        ]
    return out


def _merge_risk_flags(result: dict[str, Any], gate: dict[str, Any] | None) -> list[str]:
    flags: list[str] = []
    raw = result.get("risk_flags")
    if isinstance(raw, list):
        flags.extend(str(x).strip() for x in raw if str(x).strip())
    if isinstance(gate, dict):
        for code in gate.get("high_risk_codes") or []:
            c = str(code).strip()
            if c:
                flags.append(c)
        for code in gate.get("medium_risk_codes") or []:
            c = str(code).strip()
            if c:
                flags.append(c)
    return sorted(set(flags))[:32]


def _summarize_matched_kb(cost_rows: list[dict[str, Any]]) -> dict[str, Any]:
    matched = [r for r in cost_rows if r.get("kb_hit")]
    return {
        "count": len(matched),
        "rows": [
            {
                "name": r.get("name"),
                "spec": r.get("spec"),
                "unit_price": r.get("unit_price"),
                "kb_matched_name": r.get("kb_matched_name") or r.get("name"),
                "kb_matched_spec": r.get("kb_matched_spec") or r.get("spec"),
            }
            for r in matched[:24]
        ],
    }


def _summarize_quote_tiers(result: dict[str, Any]) -> dict[str, Any]:
    tiers = result.get("tiers") if isinstance(result.get("tiers"), list) else []
    first: dict[str, Any] = {}
    if tiers and isinstance(tiers[0], dict):
        t0 = tiers[0]
        first = {
            "quantity_text": str(t0.get("quantity_text") or "").strip(),
            "cost_before_margin_text": str(t0.get("cost_before_margin_text") or "").strip(),
            "margin_rate_text": str(t0.get("margin_rate_text") or "").strip(),
            "exw_price_text": str(t0.get("exw_price_text") or "").strip(),
            "fob_price_text": str(t0.get("fob_price_text") or "").strip(),
        }
    return {
        "material_total_text": str(result.get("material_total_text") or "").strip(),
        "system_cost_text": str(result.get("system_cost_text") or "").strip(),
        "consultant_summary": str(result.get("consultant_summary") or "").strip()[:400],
        "first_tier": first,
        "tier_count": len(tiers),
    }


def _derive_next_step_hints(
    *,
    quote_context: dict[str, Any],
) -> list[str]:
    hints: list[str] = []
    sc = quote_context.get("structure_checklist") if isinstance(quote_context.get("structure_checklist"), dict) else {}
    for name in sc.get("items_without_cost") or []:
        if name:
            hints.append(f"结构件「{name}」尚无对应成本行，需补用量/单价或确认忽略。")
    for leak in sc.get("extraction_leaks") or []:
        if leak:
            hints.append(f"结构提取可能漏项：{leak}")
    gate = quote_context.get("pricing_gate") if isinstance(quote_context.get("pricing_gate"), dict) else {}
    for code in gate.get("high_risk_codes") or []:
        hints.append(f"高风险项待人工确认：{code}")
    ai_rows = quote_context.get("ai_estimated_rows") if isinstance(quote_context.get("ai_estimated_rows"), list) else []
    if ai_rows:
        hints.append(f"有 {len(ai_rows)} 行含 AI/市场估算（规格/用量/单价/金额），建议逐行复核后再对外报价。")
    notice = str(quote_context.get("data_notice") or "").strip()
    if notice:
        hints.append(notice[:180])
    return hints[:12]


def build_readonly_quote_context(
    quote_id: str,
    payload: dict[str, Any],
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    """将会话中的 payload / quote_result 整理为 LLM 只读业务上下文。"""
    payload = payload if isinstance(payload, dict) else {}
    result = result if isinstance(result, dict) else {}

    checklist = result.get("structure_checklist")
    if not isinstance(checklist, dict):
        checklist = payload.get("structure_checklist") if isinstance(payload.get("structure_checklist"), dict) else None

    detail_rows = result.get("detail_rows")
    if not isinstance(detail_rows, list):
        detail_rows = payload.get("items") if isinstance(payload.get("items"), list) else []

    cost_rows = [_serialize_cost_row(r) for r in detail_rows if isinstance(r, dict)]
    ai_estimated_rows = [r for r in cost_rows if _row_has_any_ai_flag(r)]
    kb_matched_rows = [r for r in cost_rows if r.get("kb_hit")]
    matched_kb = _summarize_matched_kb(cost_rows)
    pricing_gate = _slim_pricing_gate(
        result.get("pricing_gate") if isinstance(result.get("pricing_gate"), dict) else None
    )
    risk_flags = _merge_risk_flags(result, pricing_gate)

    ctx: dict[str, Any] = {
        "has_active_quote": True,
        "quote_id": str(quote_id or "").strip(),
        "product_name": str(result.get("product_name") or payload.get("product_name") or "").strip(),
        "file_name": str(payload.get("file_name") or result.get("file_name") or "").strip(),
        "structure_checklist": _summarize_structure_checklist(checklist, cost_rows),
        "cost_rows": cost_rows[:48],
        "detail_rows": cost_rows[:48],
        "cost_row_count": len(cost_rows),
        "ai_estimated_rows": ai_estimated_rows[:24],
        "kb_matched_rows": kb_matched_rows[:24],
        "matched_kb": matched_kb,
        "pricing_gate": pricing_gate,
        "risk_flags": risk_flags,
        "data_notice": str(result.get("data_notice") or "").strip(),
        "price_kb_sync": _slim_price_kb_sync(result.get("price_kb_sync")),
        "quote_summary": _summarize_quote_tiers(result),
    }
    ctx["next_step_hints"] = _derive_next_step_hints(quote_context=ctx)
    return ctx


def load_readonly_quote_context(
    sid: str | None,
    session_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not str(sid or "").strip():
        return None
    try:
        from local_quote_patch import resolve_active_quote

        qid, payload, result = resolve_active_quote(str(sid).strip(), session_context)
    except Exception:
        return None
    if not isinstance(payload, dict) or not payload.get("items"):
        return None
    return build_readonly_quote_context(str(qid or "").strip(), payload, result)


def get_oem_qa_system_prompt(*, has_active_quote: bool) -> str:
    return OEM_QA_SYSTEM_PROMPT_ACTIVE if has_active_quote else OEM_QA_SYSTEM_PROMPT_GENERAL


def _summarize_active_quote_review_points(quote_context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    ai_rows = quote_context.get("ai_estimated_rows") if isinstance(quote_context.get("ai_estimated_rows"), list) else []
    if ai_rows:
        names = "、".join(str(r.get("name") or "-") for r in ai_rows[:6])
        lines.append(f"AI/市场估算 {len(ai_rows)} 行需复核：{names}")
    sc = quote_context.get("structure_checklist") if isinstance(quote_context.get("structure_checklist"), dict) else {}
    missing = sc.get("items_without_cost") or []
    if missing:
        lines.append("尚无成本行的结构件：" + "、".join(str(x) for x in missing[:6]))
    leaks = sc.get("extraction_leaks") or []
    if leaks:
        lines.append("结构提取可能漏项：" + "、".join(str(x) for x in leaks[:4]))
    rows = quote_context.get("cost_rows") if isinstance(quote_context.get("cost_rows"), list) else []
    missing_price = [
        str(r.get("name") or "-")
        for r in rows
        if str(r.get("unit_price") or "").strip() in {"", "-", "—"}
    ]
    if missing_price:
        lines.append("单价缺失：" + "、".join(missing_price[:6]))
    risk_flags = quote_context.get("risk_flags") if isinstance(quote_context.get("risk_flags"), list) else []
    if risk_flags:
        lines.append("风险提示：" + "、".join(str(x) for x in risk_flags[:6]))
    notice = str(quote_context.get("data_notice") or "").strip()
    if notice:
        lines.append(notice[:120])
    return lines


def _answer_active_quote_local(text: str, quote_context: dict[str, Any]) -> dict[str, Any] | None:
    """无 LLM 时基于 active quote 上下文的结构化本地答复。"""
    s = str(text or "").strip()
    qid = str(quote_context.get("quote_id") or "").strip()
    sources = [{"type": "active_quote", "quote_id": qid}] if qid else []

    if re.search(r"(哪些|哪几|什么地方|哪里).*(人工复核|待复核|待确认|风险)|人工复核.*(哪些|哪里|什么)", s, re.I):
        points = _summarize_active_quote_review_points(quote_context)
        if not points:
            return _wrap("当前报价未见明显待复核项；如仍有疑虑，请指出具体物料或结构件。", "fallback", sources)
        lines = [f"当前报价（{quote_context.get('product_name') or '未命名'}）建议先人工复核："]
        lines.extend(f"- {p}" for p in points[:10])
        return _wrap("\n".join(lines), "fallback", sources)

    if re.search(r"(贵|太贵|怎么解释|怎么说|话术|客户.*解释)", s, re.I):
        summary = quote_context.get("quote_summary") if isinstance(quote_context.get("quote_summary"), dict) else {}
        ai_n = len(quote_context.get("ai_estimated_rows") or [])
        kb_n = len(quote_context.get("kb_matched_rows") or [])
        lines = [
            f"跟客户可以先讲结论：这单（{quote_context.get('product_name') or '未命名'}）价格主要由材料、结构和工艺要求决定，建议先确认待复核项后再对外承诺。",
            f"物料合计 {summary.get('material_total_text') or '-'}；系统成本 {summary.get('system_cost_text') or '-'}。",
        ]
        tier = summary.get("first_tier") if isinstance(summary.get("first_tier"), dict) else {}
        if tier.get("exw_price_text"):
            lines.append(
                f"首档 {tier.get('quantity_text') or ''} EXW {tier.get('exw_price_text') or '-'}（毛利率 {tier.get('margin_rate_text') or '-'}）。"
            )
        if ai_n:
            lines.append(f"有 {ai_n} 行 AI/市场估算，需说明“参考价、待复核”，不要当最终定价。")
        if kb_n:
            lines.append(f"有 {kb_n} 行已匹配价格库，可作为已核对成本向客户说明。")
        review = _summarize_active_quote_review_points(quote_context)
        if review:
            lines.append("建议先核对：" + review[0])
        return _wrap("\n".join(lines), "fallback", sources)

    if re.search(r"(哪些|哪几|列出).*(AI|估算|市场估算)", s, re.I):
        rows = quote_context.get("ai_estimated_rows") if isinstance(quote_context.get("ai_estimated_rows"), list) else []
        if not rows:
            return _wrap("当前报价里没有标记为 AI/市场估算的成本行。", "fallback", sources)
        lines = ["当前报价中含 AI/市场估算（需人工复核）的成本行："]
        for row in rows[:16]:
            flags = "、".join(row.get("ai_flags") or []) or "AI估算"
            lines.append(
                f"- {row.get('name')}：单价 {row.get('unit_price')}，小计 {row.get('amount_text') or row.get('amount')}（{flags}）"
            )
        return _wrap("\n".join(lines), "fallback", sources)

    if re.search(r"(结构漏|漏项|没有成本|缺成本|结构件)", s, re.I):
        sc = quote_context.get("structure_checklist") if isinstance(quote_context.get("structure_checklist"), dict) else {}
        leaks = sc.get("extraction_leaks") or []
        missing = sc.get("items_without_cost") or []
        lines = [f"当前报价（{quote_context.get('product_name') or '未命名'}）结构核对："]
        if leaks:
            lines.append("结构提取漏项：" + "、".join(str(x) for x in leaks[:8]))
        if missing:
            lines.append("尚无成本行的结构件：" + "、".join(str(x) for x in missing[:8]))
        if not leaks and not missing:
            lines.append("结构清单项均已关联成本行，未见明显结构漏项。")
        gate = quote_context.get("pricing_gate") if isinstance(quote_context.get("pricing_gate"), dict) else {}
        high = gate.get("high_risk_codes") or []
        if high:
            lines.append("相关风险提示：" + "、".join(str(x) for x in high[:6]))
        return _wrap("\n".join(lines), "fallback", sources)

    if re.search(r"(价格库|知识库).*(命中|匹配)|哪些.*(系统价|标价库)", s, re.I):
        rows = quote_context.get("kb_matched_rows") if isinstance(quote_context.get("kb_matched_rows"), list) else []
        if not rows:
            return _wrap("当前报价中没有价格库命中的成本行。", "fallback", sources)
        lines = ["当前报价中价格库命中的成本行："]
        for row in rows[:16]:
            matched = row.get("kb_matched_name") or row.get("name")
            lines.append(f"- {row.get('name')}：{row.get('unit_price')}（匹配 {matched}）")
        return _wrap("\n".join(lines), "fallback", sources)

    if re.search(r"(单价|价格).*(空|缺|没有|为何|为什么)|需人工|待确认", s, re.I):
        rows = quote_context.get("cost_rows") if isinstance(quote_context.get("cost_rows"), list) else []
        bad = [
            r for r in rows
            if str(r.get("unit_price") or "").strip() in {"", "-", "—"}
            or _row_has_any_ai_flag(r)
            or r.get("needs_manual_confirm")
        ]
        if not bad:
            hints = quote_context.get("next_step_hints") or []
            if hints:
                return _wrap("\n".join(hints[:6]), "fallback", sources)
            return _wrap("当前成本行单价均已填写；如仍有疑虑，请指出具体物料名。", "fallback", sources)
        lines = ["以下成本行单价为空、为 AI 估算或需人工确认："]
        for row in bad[:12]:
            reason = row.get("recognition_reason") or row.get("calc_note") or "需人工复核"
            lines.append(f"- {row.get('name')}：单价 {row.get('unit_price')}（{reason}）")
        return _wrap("\n".join(lines), "fallback", sources)

    if re.search(r"(偏高|偏低|为什么.*(?:贵|便宜|高|低))", s, re.I):
        summary = quote_context.get("quote_summary") if isinstance(quote_context.get("quote_summary"), dict) else {}
        ai_n = len(quote_context.get("ai_estimated_rows") or [])
        kb_n = len(quote_context.get("kb_matched_rows") or [])
        lines = [
            f"产品：{quote_context.get('product_name') or '-'}",
            f"物料合计：{summary.get('material_total_text') or '-'}；系统成本：{summary.get('system_cost_text') or '-'}",
        ]
        tier = summary.get("first_tier") if isinstance(summary.get("first_tier"), dict) else {}
        if tier.get("exw_price_text"):
            lines.append(
                f"首档 {tier.get('quantity_text') or ''}：成本 {tier.get('cost_before_margin_text') or '-'}，"
                f"毛利率 {tier.get('margin_rate_text') or '-'}，EXW {tier.get('exw_price_text') or '-'}"
            )
        lines.append(f"价格库命中 {kb_n} 行，AI/市场估算 {ai_n} 行。")
        hints = quote_context.get("next_step_hints") or []
        if hints:
            lines.append("建议优先核对：" + hints[0])
        return _wrap("\n".join(lines), "fallback", sources)

    return None


def _looks_like_material_name_only(text: str) -> bool:
    s = str(text or "").strip()
    if len(s) < 2 or len(s) > 40:
        return False
    if _QUOTE_STRONG_RE.search(s) or _PRICE_LOOKUP_RE.search(s):
        return False
    return bool(re.match(r"^[A-Za-z0-9#\-/.\u4e00-\u9fff]{2,40}$", s))


def _looks_like_backpack_consulting_question(text: str) -> bool:
    s = str(text or "").strip()
    if not s or _QUOTE_STRONG_RE.search(s):
        return False
    if _ADMIN_HOWTO_RE.search(s) or _MISSING_PRICE_RE.search(s):
        return False
    if is_qa_price_lookup(s):
        return False
    return bool(_BACKPACK_CONSULT_RE.search(s))


def _answer_with_backpack_consultant(
    text: str,
    *,
    local_context: dict[str, Any] | None = None,
    quote_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """LLM-backed professional QA branch for custom travel-backpack consulting."""
    if os.environ.get("QUOTE_QA_LLM_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return None
    try:
        from kimi_client import (
            _http_error_body,
            _maybe_thinking_field,
            _send_chat_request_moonshot_with_400_relax,
            billing_reminder_from_http,
            build_endpoint_candidates,
            get_kimi_config,
            get_kimi_status,
        )
    except Exception:
        return None

    config = get_kimi_config()
    status = dict(get_kimi_status())
    status.update({"agent": "backpack_qa_consultant", "used": False, "error": ""})
    if not config.api_key:
        return None

    context = local_context if isinstance(local_context, dict) else {}
    local_answer = str(context.get("assistant_message") or context.get("answer") or "").strip()
    sources = context.get("qa_sources") if isinstance(context.get("qa_sources"), list) else []
    source_type = str(context.get("source_type") or "fallback")
    active_quote = quote_context if isinstance(quote_context, dict) and quote_context.get("has_active_quote") else None
    if active_quote:
        status["agent"] = "quote_business_advisor"

    if active_quote:
        system_prompt = OEM_QA_SYSTEM_PROMPT_ACTIVE
    else:
        system_prompt = OEM_QA_SYSTEM_PROMPT_GENERAL

    user_payload: dict[str, Any] = {
        "source_type": source_type,
        "local_answer": local_answer,
        "sources": sources[:5],
    }
    if active_quote:
        user_payload["quote_context"] = active_quote

    req_body: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
        "max_completion_tokens": 1200,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": (
                    "用户问题：\n"
                    f"{text.strip()}\n\n"
                    "本地系统可用事实上下文（只能作为事实依据，不能扩写价格）：\n"
                    f"{json.dumps(user_payload, ensure_ascii=False, default=str)}"
                ),
            },
        ],
    }
    req_body.update(_maybe_thinking_field(config.base_url))

    http_failures: list[tuple[int, str]] = []
    for endpoint in build_endpoint_candidates(config.base_url, api_key_source=config.api_key_source):
        try:
            raw = _send_chat_request_moonshot_with_400_relax(
                endpoint=endpoint,
                api_key=config.api_key,
                body=req_body,
                timeout_s=config.timeout_s,
                disable_proxy=False,
            )
        except error.HTTPError as exc:
            body = _http_error_body(exc)
            http_failures.append((exc.code, endpoint))
            billing = billing_reminder_from_http(exc.code, body)
            if billing:
                status["error"] = f"http_{exc.code}"
                status["billing_reminder"] = billing
                return None
            if exc.code in {400, 401, 403, 404}:
                continue
            status["error"] = f"http_{exc.code}"
            return None
        except Exception:
            try:
                raw = _send_chat_request_moonshot_with_400_relax(
                    endpoint=endpoint,
                    api_key=config.api_key,
                    body=req_body,
                    timeout_s=config.timeout_s,
                    disable_proxy=True,
                )
            except Exception:
                continue

        try:
            payload = json.loads(raw)
            content = _normalize_consultant_answer(
                str(payload["choices"][0]["message"]["content"] or "").strip(),
                text,
            )
        except Exception:
            status["error"] = "parse_error"
            return None
        if not content:
            status["error"] = "empty_reply"
            return None
        status["used"] = True
        status["base_url"] = endpoint.removesuffix("/chat/completions")
        resp = _wrap(
            content,
            "llm",
            [
                {
                    "type": "llm_consultant",
                    "provider": status.get("provider"),
                    "model": status.get("model"),
                    "local_source_type": source_type,
                    "quote_advisor": bool(active_quote),
                    "quote_id": str(active_quote.get("quote_id") or "") if active_quote else "",
                },
                *sources[:5],
            ],
            qa_audit=_qa_audit(
                "llm",
                provider=str(status.get("provider") or ""),
                model=str(status.get("model") or ""),
                used=True,
            ),
        )
        resp["llm_status"] = status
        return resp

    if http_failures:
        code, _endpoint = http_failures[-1]
        status["error"] = f"http_{code}"
    else:
        status["error"] = "network_error"
    return _wrap(
        _natural_consultant_fallback(text),
        "fallback",
        sources[:5],
        qa_audit=_qa_audit(
            "fallback",
            provider=str(status.get("provider") or ""),
            model=str(status.get("model") or ""),
            used=False,
            error=str(status.get("error") or ""),
            fallback_reason="llm_failed",
        ),
    )


def _extract_material_query(text: str) -> str:
    s = str(text or "").strip()
    s = re.sub(
        r"(多少钱|什么价|啥价|多少价|单价多少|价格多少|怎么卖|是多少|价格|单价)",
        "",
        s,
        flags=re.I,
    )
    s = re.sub(r"[?？!！。，,\s]+", " ", s).strip()
    return s[:48]


def _answer_price_lookup(text: str, *, allow_weak: bool = False) -> dict[str, Any]:
    query = _extract_material_query(text) or text.strip()
    sources: list[dict[str, Any]] = []

    try:
        from price_kb import get_price_kb

        kb = get_price_kb()
        hit = kb.lookup(query)
        if hit and hit.entry:
            ent = hit.entry
            spec = str(ent.raw_spec or "").strip() or "-"
            msg = (
                f"「{ent.raw_name}」（规格 {spec}）在价格库中的参考单价为 **{ent.raw_price}**"
                f"（匹配度 {hit.score:.0%}）。"
                f"\n\n此为标价库参考价，正式报价仍以当次 BOM/用量核算为准。"
            )
            sources.append(
                {
                    "type": "price_kb",
                    "name": ent.raw_name,
                    "spec": spec,
                    "price": ent.raw_price,
                    "score": round(hit.score, 3),
                }
            )
            return _wrap(msg, "price_kb", sources)

        suggestions = kb.suggest_entries_for_query(query, limit=3)
        if suggestions and allow_weak:
            lines = [f"价格库没有完全匹配「{query}」，相近条目："]
            for ent in suggestions:
                lines.append(f"- {ent.raw_name}（{ent.raw_spec or '-'}）：{ent.raw_price}")
            sources.append({"type": "price_kb", "mode": "suggest", "query": query})
            return _wrap("\n".join(lines), "price_kb", sources)
    except Exception as exc:  # noqa: BLE001
        sources.append({"type": "price_kb", "error": str(exc)})

    hist = _search_quote_history(query, limit=4)
    if hist:
        lines = [f"价格库暂无「{query}」的确定单价，但在历史报价中找到相近用料："]
        for row in hist:
            lines.append(
                f"- {row.get('product_name') or '历史单'} / {row.get('name')}："
                f"单价 {row.get('unit_price') or '-'}，小计 {row.get('amount_text') or row.get('amount')}"
                f"（{row.get('saved_at') or ''}）"
            )
        lines.append("\n如需纳入正式价格库，请在后台补价或导入 price_kb.xlsx。")
        sources.extend({"type": "quote_history", **row} for row in hist)
        return _wrap("\n".join(lines), "quote_history", sources)

    msg = (
        f"价格库暂无「{query}」的单价记录，需要后台补价后才能作为系统参考价。"
        f"\n\n操作：登录管理后台 → 价格库 → 搜索材料名 → 填写单价并保存；"
        f"暂时没有单价可先标记为「待补充」，不会用猜价参与正式报价。"
    )
    return _wrap(msg, "fallback", sources)


def _answer_admin_howto(text: str) -> dict[str, Any]:
    _ = text
    port = "8776"
    msg = (
        "**价格库 / 后台操作步骤**（来源：项目使用说明）\n\n"
        f"1. 启动服务：`python server.py`，前台工作台默认 `http://127.0.0.1:{port}/`。\n"
        "2. 管理后台：使用独立后台端口登录（终端启动日志会打印 `[报价归档后台·独立端口]` 地址），"
        "使用管理员账号进入。\n"
        "3. **更新单价**：后台 → 价格库 → 按材料名称或规格搜索 → 修改「单价」列 → 保存。"
        "保存后内存价格库会刷新，后续报价匹配到该行才会带出价格。\n"
        "4. **批量导入**：可将 Excel 维护为 `data/price_kb.xlsx`（列：材料名称 / 规格大小 / 单价），"
        "或在后台使用导入功能（若有）。\n"
        "5. **待补充**：没有可靠单价的材料应标为待补充，系统不会瞎编价格参与正式核算。\n\n"
        "若只是查某个材料参考价，可直接问「600D塔丝隆多少钱」；若要正式出报价，请上传 BOM 或说明数量与尺寸。"
    )
    return _wrap(
        msg,
        "docs",
        [{"type": "docs", "path": str(README_PATH), "topic": "admin_price_kb"}],
    )


def _answer_missing_price_flow(text: str) -> dict[str, Any]:
    _ = text
    msg = (
        "**材料没有价格时的处理流程**\n\n"
        "1. 报价时若价格库未命中，该行会标记为 AI 参考价或待确认，并在数据提示里说明。\n"
        "2. 不应手工假设单价参与正式报价；请在后台 **价格库** 补录材料名称、规格与单价。\n"
        "3. 暂时没有单价可保存为 **待补充 / 待补价**，该状态不会当作可靠系统价。\n"
        "4. 补价后新报价会自动匹配；历史单如需对齐可重新试算或改价。\n"
        "5. 生产环境建议「先审后写」：自动回流候选默认进待审核队列，不直接污染 price_kb.xlsx。\n\n"
        "需要改价时：后台 → 价格库 → 搜索材料 → 填单价 → 保存。"
    )
    return _wrap(
        msg,
        "docs",
        [{"type": "docs", "topic": "missing_price_workflow"}],
    )


def _answer_from_docs(text: str) -> dict[str, Any]:
    chunks = _load_doc_chunks()
    if not chunks:
        return _wrap("", "fallback", [])
    q_tokens = _tokenize(text)
    if not q_tokens:
        return _wrap("", "fallback", [])
    scored: list[tuple[float, dict[str, str]]] = []
    for ch in chunks:
        score = _overlap_score(q_tokens, _tokenize(ch.get("title", "") + " " + ch.get("body", "")))
        if score > 0:
            scored.append((score, ch))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < 1.0:
        return _wrap("", "fallback", [])
    best = scored[0][1]
    excerpt = best.get("body", "").strip()
    if len(excerpt) > 420:
        excerpt = excerpt[:420].rstrip() + "…"
    msg = f"根据项目说明（{best.get('title', '文档')}）：\n\n{excerpt}"
    return _wrap(
        msg,
        "docs",
        [{"type": "docs", "path": best.get("path", ""), "title": best.get("title", "")}],
    )


def _answer_fallback(text: str) -> dict[str, Any]:
    s = str(text or "").strip()
    if _looks_like_backpack_consulting_question(s):
        msg = _natural_consultant_fallback(s)
    elif _PROCESS_MATERIAL_RE.search(s):
        msg = (
            "这类材料/工艺问题可以先按“用途、强度、防水/耐磨要求、量产风险”四个点判断。"
            "如果只是做日常包，优先选成熟、稳定、好采购的常规方案；如果是户外或高端款，再考虑更高等级材料和特殊工艺。"
            "没有明确订单参数时，我不直接编单价或规格表；你补充使用场景、数量和目标价位后，我可以再给更贴近项目的建议。"
        )
    else:
        msg = (
            "我可以在不重新报价的前提下，帮你查 **价格库单价**、**历史报价用料** 或 **后台/价格库操作说明**。"
            "例如：「600D塔丝隆多少钱」「价格库怎么更新」「这个材料没有价格怎么办」。"
            "若要正式核算一整单，请说明产品、数量、尺寸并上传 BOM。"
        )
    return _wrap(_filter_internal_jargon(msg), "fallback", [])


def _natural_consultant_fallback(question: str) -> str:
    """Natural business-facing fallback when the consultant model is unavailable."""
    q = str(question or "").strip().lower()
    if re.search(r"(贵|太贵|客户|解释|怎么说|话术|说服)", q):
        return (
            "可以先跟客户讲结论：这版价格主要贵在材料、做工和品控要求，不是单纯加利润。\n"
            "1. 先把高成本点说清楚，比如主面料、拉链、肩带受力位、加固工艺。\n"
            "2. 再给选择题：保品质用当前方案，想降预算就从里料、辅料等级或非受力结构优化。\n"
            "3. 不建议直接砍关键受力件，否则后期返修和客诉风险会更高。"
        )
    if re.search(r"(耐磨|耐用|耐刮|磨损|面料.*选|怎么选.*面料)", q):
        return (
            "如果目标是更耐磨，优先看外层主面料和包底加固。\n"
            "1. 日常旅行包可选 600D/900D 牛津布，稳定、好采购、成本也容易控。\n"
            "2. 户外或高频使用场景，建议提高到高强尼龙、1680D 或类似 Cordura 档位。\n"
            "3. 包底、转角、肩带连接位比整包盲目升级更关键，可以局部加厚或加补强片。"
        )
    if re.search(r"(防水|防泼水|雨|淋水)", q):
        return (
            "防水要先区分“防泼水”和“长时间防雨”。\n"
            "1. 普通旅行包通常做表面防泼水 + 背面涂层就够用。\n"
            "2. 如果客户要求雨中使用，要同步看拉链、缝线和包口结构，不是只换面料。\n"
            "3. 真正高防水会增加成本和工艺风险，建议先确认使用场景。"
        )
    if re.search(r"(降本|便宜|省钱|替代|优化|成本)", q):
        return (
            "降本可以做，但建议先保住客户最容易感知和最容易出问题的部位。\n"
            "1. 可优先看里料、辅料品牌档位、非受力装饰件和包装方式。\n"
            "2. 主拉链、肩带根部、包底和提手连接位不建议硬降。\n"
            "3. 如果给我目标价位和订单数量，我可以帮你把可降项和风险项分开说。"
        )
    return (
        "可以先按使用场景来判断，不急着定材料。\n"
        "1. 日常通勤看稳定、轻便和好采购；旅行/户外要更关注耐磨、承重和防泼水。\n"
        "2. 主面料、包底、肩带连接位是优先级最高的地方，装饰件和里料更适合做成本优化。\n"
        "3. 你补充用途、容量、目标价位和数量后，我可以继续给更贴近这单的建议。"
    )


def _normalize_consultant_answer(content: str, question: str) -> str:
    """Keep AI QA flexible, but make the final wording look like a chat reply."""
    text = _filter_internal_jargon(str(content or "").strip())
    if not text:
        return ""
    asks_price = bool(_PRICE_LOOKUP_RE.search(question or ""))
    cleaned: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            if cleaned and cleaned[-1]:
                cleaned.append("")
            continue
        if re.fullmatch(r"[-*_]{3,}", line):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = line.replace("**", "").replace("__", "")
        if line.startswith("💡") or line.startswith("提示：") or line.startswith("提示:"):
            continue
        if not asks_price and re.search(r"(单价|价格|成本参考|￥|¥|\bRMB\b)", line, re.I):
            continue
        cleaned.append(line)

    compact: list[str] = []
    blank = False
    for line in cleaned:
        if not line:
            blank = True
            continue
        if blank and compact:
            compact.append("")
        compact.append(line)
        blank = False

    nonblank_count = 0
    limited: list[str] = []
    for line in compact:
        if line:
            nonblank_count += 1
        if nonblank_count > 6:
            break
        limited.append(line)
    result = "\n".join(limited).strip()
    if len(result) > 520:
        result = result[:520].rstrip()
        cut = max(result.rfind("。"), result.rfind("；"), result.rfind("\n"))
        if cut >= 180:
            result = result[: cut + 1]
        else:
            result += "..."
    return result


def _generate_dynamic_backpack_answer(question: str) -> str:
    """根据问题内容动态生成专业的背包/OEM软包咨询回答"""
    q = question.lower()

    material_keywords = {
        "尼龙": ["尼龙布", "尼龙面料", "nylon", "锦纶"],
        "牛津": ["牛津布", "oxford", "600d", "420d", "1680d"],
        "涤纶": ["涤纶", "聚酯纤维", "polyester"],
        "帆布": ["帆布", "canvas"],
        "cordura": ["cordura", "考杜拉"],
        "xpac": ["xpac", "x-pac", "DCF"],
    }

    topic_keywords = {
        "耐磨": ["耐磨", "耐磨损", "耐用", "寿命", "耐刮"],
        "防水": ["防水", "防泼水", "防雨", "waterproof", "水 resistance"],
        "降本": ["降本", "降低成本", "省钱", "便宜", "性价比", "替代"],
        "结构": ["结构", "版型", "设计", "背负", "肩带"],
        "拉链": ["拉链", "zipper", "拉锁"],
        "扣具": ["扣具", "插扣", "卡扣", "buckle", "织带"],
        "面料选择": ["面料怎么选", "面料选择", "什么面料好", "推荐面料"],
        "材料对比": ["区别", "对比", "差异", "哪个好", "比较"],
    }

    detected_materials = []
    for material, aliases in material_keywords.items():
        if any(alias in q for alias in aliases):
            detected_materials.append(material)

    detected_topics = []
    for topic, keywords_list in topic_keywords.items():
        if any(kw in q for kw in keywords_list):
            detected_topics.append(topic)

    focus = detected_topics[:3] or detected_materials[:3]
    if focus:
        lead = "定制旅行背包项目里，这个问题我会先看：" + "、".join(focus) + "。"
    else:
        lead = "定制旅行背包项目里，这个问题我会先按使用场景和量产可行性来判断。"
    return (
        f"{lead}\n"
        "一般先讲功能差异，再看用在包上的位置，最后看工艺风险和成本取舍。"
        "日常款优先稳定好采购，户外/高端款再提高材料或工艺等级。\n"
        "如果你给到产品用途、目标客群和大概价位，我可以按这个项目继续细化。"
    )


def _get_material_comparison(materials: list[str]) -> str:
    """材料对比分析"""
    comp_data = {
        "尼龙": {"耐磨性": "★★★★☆", "防水性": "★★★☆☆", "重量": "轻", "价格": "中等", "典型应用": "户外背包、登山包"},
        "牛津": {"耐磨性": "★★★☆☆", "防水性": "★★★☆☆", "重量": "中等", "价格": "经济", "典型应用": "通勤包、学生书包"},
        "涤纶": {"耐磨性": "★★★☆☆", "防水性": "★★★☆☆", "重量": "轻", "价格": "经济", "典型应用": "轻便背包、折叠包"},
        "帆布": {"耐磨性": "★★☆☆☆", "防水性": "★★☆☆☆", "重量": "重", "价格": "中等", "典型应用": "时尚休闲包、购物袋"},
        "cordura": {"耐磨性": "★★★★★", "防水性": "★★★★☆", "重量": "中等", "价格": "较高", "典型应用": "高端战术包、专业户外"},
        "xpac": {"耐磨性": "★★★★☆", "防水性": "★★★★★", "重量": "轻", "价格": "高", "典型应用": "超轻徒步、骑行背包"},
    }

    lines = [f"## { ' vs '.join(materials[:2]) } 材料对比分析\n"]
    lines.append("| 特性 | " + " | ".join(materials[:2]) + " |")
    lines.append("|------|" + "|".join(["------"] * len(materials[:2])) + "|")

    properties = ["耐磨性", "防水性", "重量", "价格", "典型应用"]
    for prop in properties:
        values = []
        for m in materials[:2]:
            val = comp_data.get(m, {}).get(prop, "-")
            values.append(val)
        lines.append(f"| {prop} | {' | '.join(values)} |")

    lines.append("\n**选型建议**：")
    if "尼龙" in materials and "牛津" in materials:
        lines.append("- 偏重**耐用与轻量化** → 选尼龙（420D/600D适合日常，1680D适合高强度使用）")
        lines.append("- 偏重**性价比与易打理** → 选牛津布（600D/900D是主流选择）")
    elif "cordura" in materials:
        lines.append("- 预算充足且追求**极致耐磨** → Cordura 是首选（但成本高 30-50%）")

    return "\n".join(lines)


def _get_material_selection_guide(materials: list[str], topics: list[str]) -> str:
    """面料选择指南"""
    guide = ["## 定制旅行背包面料选择建议\n"]

    if "尼龙" in materials or not materials:
        guide.extend([
            "**尼龙系列**（主流选择）：",
            "- **420D 尼龙**：轻量通勤、日常短途旅行，性价比最优",
            "- **600D 尼龙**：均衡型选择，适合中长途旅行、轻度户外",
            "- **1680D / CORDURA®**：高强度使用、专业户外、频繁摩擦场景",
        ])

    if "牛津" in materials or not materials:
        guide.extend([
            "\n**牛津布系列**（经济型选择）：",
            "- **600D 牛津**：学生书包、促销礼品包、预算敏感项目",
            "- **900D-1200D 牛津**：需要一定强度的经济型背包",
        ])

    guide.extend([
        "\n**选择决策树**：",
        "1. 使用频率：偶尔用（<每月1次）→ 420D牛津 | 经常用（每周+）→ 600D尼龙",
        "2. 负重需求：< 8kg → 标准厚度 | 8-15kg → 加厚款 | >15kg → 专业级面料",
        "3. 预算范围：< ¥80/个 → 牛津布 | ¥80-150 → 600D尼龙 | > ¥150 → Cordura/XPAC",
        "4. 交付周期：急单（<7天）→ 库存现货面料 | 正常（15-30天）→ 可定制",
    ])

    return "\n".join(guide)


def _get_durability_advice(materials: list[str]) -> str:
    """耐磨性建议"""
    advice = [
        "## 耐磨性提升方案\n",
        "**主料选择优先级**：",
        "1. **Cordura® / Dyneema® 复合面料**（顶级，成本高 40-100%）",
        "2. **1680D 双股尼龙**（高强度，性价比适中）",
        "3. **600D 涤纶/尼龙 + PU 涂层**（标准配置，满足大多数场景）",
        "",
        "**工艺增强措施**：",
        "- 底部/边角部位采用**双层加厚**或**补强片**",
        "- 高磨损区（肩带根部、拉链头）增加**车缝加固**",
        "- 考虑**热压贴合**代替传统车缝减少磨损点",
        "",
        "**OEM量产注意事项**：",
        "- 要求供应商提供**马丁代尔耐磨测试报告**（≥ 50000次为优）",
        "- 大货生产前做**破坏性测试**（模拟实际使用场景）",
        "- 批次间色差控制在 ΔE < 1.5 以保证外观一致性",
    ]
    return "\n".join(advice)


def _get_waterproof_advice(materials: list[str]) -> str:
    """防水性能建议"""
    advice = [
        "## 防水性能实现方案\n",
        "**防水等级定义**：",
        "- **防泼水 (DWR)**：表面荷叶效应，小雨/短时淋湿不渗透（日常够用）",
        "- **防水涂层 (PU/PVC)**：中雨级别，接缝处仍可能渗水",
        "- **复合防水膜 (TPU/ePTFE)**：大雨级别，需配合热压密封接缝",
        "- **全密封防水**：潜水级，成本极高且影响透气性",
        "",
        "**定制背包常用方案**：",
        "1. **经济型**：600D牛津 + PU涂银（防泼水，成本最低）",
        "2. **标准型**：尼龙 + DWR处理 + 反面TPU覆膜（性价比最优）",
        "3. **专业型**：XPAC 复合面料（自带防水层，超轻且耐用）",
        "",
        "**工艺风险提醒**：",
        "- PU涂层随时间老化脱落（通常 6-12个月开始衰减）",
        "- 热压接缝增加工序成本（约 +¥2-5/件）",
        "- 全防水设计牺牲透气性，长期存放可能有异味",
    ]
    return "\n".join(advice)


def _get_cost_reduction_tips() -> str:
    """降本建议"""
    tips = [
        "## OEM软包降本策略（不影响核心质量）\n",
        "**安全降本区域**（按影响从小到大排序）：",
        "1. **包装材料**：改用简化包装（节省 ¥0.5-2/个）",
        "2. **里料/内衬**：从210T改为190T或取消部分隔层（节省 ¥1-3/个）",
        "3. **辅件品牌**：拉链/扣具选用国产替代进口（YKK→SBS，节省 ¥2-8/个）",
        "4. **织带宽度**：在不影响强度前提下减小 25%-30%（节省约 ¥0.5-1/个）",
        "",
        "**谨慎调整区域**（需评估风险）：",
        "- ⚠️ 主料克重降低（可能影响整体强度和手感）",
        "- ⚠️ 减少车缝密度（可能造成开线风险）",
        "- ⚠️ 取消底部加厚（高频磨损部位不宜省）",
        "",
        "**不建议降本项**（影响核心功能）：",
        "- ❌ 主拉链品质（故障率最高的部件之一）",
        "- ❌ 肩带连接处强度（安全隐患）",
        "- ❌ 关键受力点缝线（整包结构基础）",
        "",
        "**降本幅度参考**（基于 28L 标准双肩包）：",
        "- 轻度优化：↓ 5-8%（基本无感知）",
        "- 中度优化：↓ 10-15%（需平衡取舍）",
        "- 深度优化：↓ 20%+（明显影响品质，慎用）",
    ]
    return "\n".join(tips)


def _get_structure_advice() -> str:
    """结构设计建议"""
    advice = [
        "## 旅行背包结构设计要点\n",
        "**背负系统**：",
        "- **日系/短途（<20L）**：简单双肩带 + 泡沫背垫即可",
        "- **欧系/中长途（20-35L）**：需透气背板（PE/EVA）+ 胸扣 + 腰带分担",
        "- **专业户外（>35L）**：铝合金/碳纤维支架 + 可调节背负系统",
        "",
        "**容量规划原则**：",
        "- 主仓：总容量的 60-70%（放置大件物品）",
        "- 前袋/侧袋：15-20%（常用小物快速取放）",
        "- 电脑仓/分隔层：10-15%（保护贵重电子设备）",
        "",
        "**常见结构问题及解决方案**：",
        "- 问题：装满后重心后仰 → 解决：增加胸部束紧带 + 紧贴背部设计",
        "- 问题：取物不便 → 解决：U型主开口 + 多仓位分类",
        "- 问题：肩带滑落 → 解决：S型剪裁 + 胸扣位置可调",
    ]
    return "\n".join(advice)


def _get_zipper_guide() -> str:
    """拉链选择指南"""
    guide = [
        "## 拉链选型与应用场景\n",
        "**品牌档次**（由低到高）：",
        "1. **国产通用**（SBS/三力/YCC）：经济型，适合内部隔层、非关键部位",
        "2. **YKF/KEE**：中端，适合前袋、侧袋等次要开口",
        "3. **YKK**（日本）：主流选择，质量稳定，适合主仓开口",
        "4. **RIR/YKK Excella**：高端，防水/顺滑要求高的专业包",
        "",
        "**齿型选择**：",
        "- **3# / 5# 树脂拉链**：前袋、附件袋（成本低，强度一般）",
        "- **5# / 8# 金属拉链**：主仓开口（强度高，外观质感好）",
        "- **5# / 8# 防水拉链**（TPU覆膜）：户外/旅行包主仓（防水必备）",
        "- **10# 工业拉链**：超大开口或特殊用途",
        "",
        "**OEM采购注意**：",
        "- 要求提供**SGS检测报告**（重金属、色牢度合规）",
        "- 抽检**拉头往返测试**（≥ 1000次顺畅为合格）",
        "- 批次间颜色一致性（ΔE < 1.0，避免视觉瑕疵）",
        "",
        "**成本参考**（以5#为例）：",
        "- 国产：¥0.8-1.5/条",
        "- YKK：¥2.5-4/条",
        "- YKK防水：¥4-7/条",
    ]
    return "\n".join(guide)


def _get_hardware_guide() -> str:
    """扣具/五金选择指南"""
    guide = [
        "## 扣具与五金配件选型\n",
        "**插扣/卡扣**：",
        "- **材质选择**：POM（耐用）> PP（经济）> ABS（脆，避免用于受力点）",
        "- **品牌**：ITW NEXUS / Duraflex（高端）> 国产知名（中端）> 杂牌（慎用）",
        "- **强度要求**：主肩带连接扣 ≥ 80kg 承重， accessory 扣 ≥ 30kg",
        "",
        "**织带/肩带**：",
        "- **宽度规范**：",
            "  - 装饰/挂带：15-20mm",
            "  - 提手/副带：25-38mm",
            "  - 主肩带：38-50mm（成人背包标准）",
        "- **材质**：聚丙烯(PP) < 聚酯(PET) < 尼龙（强度排序）",
        "- **密度**：普通 300-400D / 加密 600-1000D / 重型 1200D+",
        "",
        "**其他五金**：",
        "- **D环/钩扣**：不锈钢 > 合金 > 铁（防锈能力排序）",
        "- **气眼/鸡眼**：铜质 > 不锈钢 > 合金（耐用性排序）",
        "",
        "**成本控制建议**：",
        "- 受力点（肩带根、主扣）用品牌件，装饰件可用国产替代",
        "- 统一采购同品牌系列，便于售后维修和备件管理",
        "- 要求样品确认后再大货，避免批次色差或尺寸偏差",
    ]
    return "\n".join(guide)


def _get_general_backpack_guide() -> str:
    """通用背包咨询引导"""
    return (
        "作为定制旅行背包/OEM软包顾问，我可以从以下角度为您提供建议：\n\n"
        "**🎯 我能帮您解答的问题类型**：\n\n"
        "1. **材料选择**：\n"
        "   - 「尼龙和牛津布有什么区别？」\n"
        "   - 「28L旅行背包用什么面料合适？」\n"
        "   - 「Cordura 和普通尼龙差多少？」\n\n"
        "2. **工艺与性能**：\n"
        "   - 「怎么做更耐磨？」\n"
        "   - 「防水要做到什么程度？」\n"
        "   - 「肩带应该多宽？」\n\n"
        "3. **结构与设计**：\n"
        "   - 「背负系统怎么设计？」\n"
        "   - 「容量怎么分配合理？」\n\n"
        "4. **成本优化**：\n"
        "   - 「想降本但不影响质量」\n"
        "   - 「用什么替代材料可以省钱？」\n\n"
        "5. **供应链与量产**：\n"
        "   - 「MOQ 一般多少？」\n"
        "   - 「交期大概要多久？」\n\n"
        "---\n"
        "**💡 请直接描述您的具体需求**，例如：\n"
        "- 「我要做一批 28L 户外旅行包，预算 120 元以内，主要走山路，面料怎么选？」\n"
        "- 「600D牛津布和 420D尼龙做通勤包，哪个更划算？」\n"
        "- \"想给现有款式降本 10%，哪些地方可以优化？\"\n\n"
        "我会根据您的具体场景给出针对性建议。"
    )


def _filter_internal_jargon(text: str) -> str:
    """过滤所有内部系统术语和技术细节"""
    text = str(text or "").strip()
    if not text:
        return text

    replacements = {
        "KIMI_API_KEY": "",
        "MOONSHOT_API_KEY": "",
        "API key": "",
        "API Key": "",
        "API_KEY": "",
        "API 接口": "",
        "LLM": "",
        "模型调用": "系统分析",
        "该条 QA 支线": "答疑模块",
        "专业背包顾问模型": "专业顾问",
        "price_kb": "标价库",
        "price_kb_sync": "标价库匹配记录",
        "quote_engine": "报价引擎",
        "pricing_gate": "风控提示",
        "Claude": "OpenAI",
        "ClaudeCode": "OpenAI",
        "Anthropic": "OpenAI",
        "Kimi": "",
        "payload": "数据",
        "calculate_quote": "核算流程",
        "endpoint": "接口地址",
        "billing_reminder": "",
        "http_402": "",
        "http_429": "",
        "insufficient quota": "",
        "balance": "",
        "recharge": "",
        "quota": "额度",
        "Moonshot/Kimi": "AI服务",
        "OpenAPI": "",
        "thinking field": "",
        "temperature": "",
        "max_completion_tokens": "",
        "base_url": "",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"配置\s*[\w_]*API[_\w]*\s*KEY[^。]*?。?", "", text)
    text = re.sub(r"该条\s*\w+\s*支线[^。]*?。?", "", text)
    text = re.sub(r"(HTTP|http)\s*\d{3}[^。]*?。?", "", text)
    text = re.sub(r"余额|配额|计费|充值|套餐|费用不足[^。]*?。?", "", text)
    text = re.sub(r"\s*到\s*(?:控制台|平台)[^。]*?。?", "", text)
    text = re.sub(r"请核对[^。]*?(?:账户|API Key|余额|套餐)[^。]*?。?", "", text)

    while "  " in text:
        text = text.replace("  ", " ")
    text = text.strip()

    return text


def _search_quote_history(keyword: str, *, limit: int = 5) -> list[dict[str, Any]]:
    q = str(keyword or "").strip()
    if not q or len(q) < 2:
        return []
    try:
        from quote_storage.backend import configured_quote_db_backend

        if configured_quote_db_backend() == "postgres":
            return _search_quote_history_postgres(q, limit=limit)
        from quote_upload_storage import search_quote_items_by_keyword

        return search_quote_items_by_keyword(q, limit=limit)
    except Exception:
        return []


def _search_quote_history_postgres(keyword: str, *, limit: int = 5) -> list[dict[str, Any]]:
    try:
        from quote_storage import postgres_impl

        return postgres_impl.search_quote_items_by_keyword(keyword, limit=limit)
    except Exception:
        return []


def _load_doc_chunks() -> list[dict[str, str]]:
    paths = [README_PATH]
    chunks: list[dict[str, str]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        title = ""
        body_lines: list[str] = []
        for line in raw.splitlines():
            if line.startswith("## "):
                if body_lines:
                    chunks.append(
                        {
                            "path": str(path),
                            "title": title or path.name,
                            "body": "\n".join(body_lines).strip(),
                        }
                    )
                    body_lines = []
                title = line[3:].strip()
            else:
                body_lines.append(line)
        if body_lines:
            chunks.append(
                {
                    "path": str(path),
                    "title": title or path.name,
                    "body": "\n".join(body_lines).strip(),
                }
            )
    return [c for c in chunks if c.get("body")]


def _tokenize(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z0-9#\-]{2,}|[\u4e00-\u9fff]{2,}", str(text or ""))
    }


def _overlap_score(q: set[str], doc: set[str]) -> float:
    if not q or not doc:
        return 0.0
    return float(len(q & doc))


def _wrap(
    message: str,
    source_type: SourceType,
    sources: list[dict[str, Any]],
    *,
    qa_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit = qa_audit if isinstance(qa_audit, dict) else _qa_audit(_audit_route_for_source(source_type))
    return {
        "quote_ready": False,
        "intent": "QA",
        "reply_type": "business_qa",
        "assistant_message": str(message or "").strip(),
        "source_type": source_type,
        "qa_sources": sources,
        "qa_audit": audit,
        "answer": str(message or "").strip(),
    }
