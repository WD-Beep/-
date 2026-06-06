"""LangGraph 节点：意图路由、视觉（占位可接 Kimi）、参数更新、核算桥接、回复生成。

原则：
- **算术只做在 calculator_node**（调用现有 quote_engine）。
- 未配置 Kimi/LangChain 时，意图路由与参数抽取可用启发式兜底，便于离线跑通图。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from quotation_agent.calculator_bridge import run_calculate_quote
from quotation_agent.moonshot_client import (
    chat_completions,
    chat_completions_multimodal_user,
    default_text_model,
    default_vision_model,
    moonshot_api_key,
    moonshot_base_url,
)
from quotation_agent.state import IntentLiteral, QuotationState

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: str = "0") -> bool:
    raw = os.environ.get(name, default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def intent_router_node(state: QuotationState) -> dict[str, Any]:
    """意图路由：对比图 / 单图 / 解释口径 / 改参数 / 闲聊。"""
    msg = (state.get("user_message") or "").strip()
    images = list(state.get("current_images") or [])

    intent: IntentLiteral | str = "chitchat"

    compare_kw = ("差距", "对比", "区别", "为什么", "为啥", "何以", "不一样", "差那么多", "两张")
    param_kw = ("换", "改成", "改为", "面料", "数量", "件", "个", "码", "尼龙", "涤纶", "里布")
    quote_kw = ("报价", "核算", "重算", "再算")
    explain_kw = (
        "怎么算",
        "如何算",
        "咋算",
        "不一致",
        "不一样",
        "差在哪",
        "口径",
        "对吗",
        "靠谱吗",
        "跟你算",
        "跟我算",
        "跟你算的",
        "跟我算的",
        "合理性",
        "毛利",
        "加工费",
        "含税",
        "exw",
        "摊销",
        "模具",
    )

    calc = state.get("calculation_result")
    params = state.get("parameters") or {}
    has_quote_anchor = bool(params.get("items")) or calc is not None

    if len(images) >= 2 and any(k in msg for k in compare_kw):
        intent = "vision_compare"
    elif len(images) >= 1:
        intent = "vision_single"
    elif (
        any(k in msg for k in explain_kw)
        or ("为什么" in msg and len(images) == 0)
        or ("为何" in msg and len(images) == 0)
    ) and has_quote_anchor:
        intent = "quote_explain"
    elif any(k in msg for k in param_kw) or (any(k in msg for k in quote_kw) and state.get("parameters")):
        intent = "parameter_change"
    else:
        intent = "chitchat"

    # 可选：接入 LangChain 分类器（未安装则跳过）
    llm_intent = _classify_intent_llm(msg, len(images))
    if llm_intent:
        intent = llm_intent  # type: ignore[assignment]

    return {"last_intent": intent}


def _classify_intent_llm(message: str, n_images: int) -> str | None:
    """若配置了 LangChain + OpenAI 兼容底座，可做意图细分；否则返回 None。"""
    if not _env_flag("QUOTATION_AGENT_USE_LLM_ROUTER"):
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
    base_url = (
        os.environ.get("MOONSHOT_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or moonshot_base_url()
    )
    if not api_key:
        return None

    model = os.environ.get("QUOTATION_AGENT_ROUTER_MODEL") or default_text_model()
    kwargs: dict[str, Any] = {"model": model, "api_key": api_key, "temperature": 0}
    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")

    llm = ChatOpenAI(**kwargs)
    sys = SystemMessage(
        content=(
            "你是意图分类器。仅输出 JSON：{\"intent\":\"vision_compare\"|\"vision_single\""
            "|\"parameter_change\"|\"quote_explain\"|\"chitchat\"}。\n"
            f"当前用户附图数量：{n_images}。\n"
            "规则：两张及以上图且问差异/为何→vision_compare；"
            "有图→vision_single；"
            "问怎么算/毛利口径/为何与手动不一致且会话内已有报价结果→quote_explain；"
            "提到换料改数量→parameter_change；否则 chitchat。"
        )
    )
    try:
        resp = llm.invoke([sys, HumanMessage(content=message)])
        raw = getattr(resp, "content", "") or ""
        data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        return str(data.get("intent") or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("intent llm fallback: %s", exc)
        return None


def route_after_intent(state: QuotationState) -> str:
    """条件边：映射 intent → 下一节点名。"""
    intent = state.get("last_intent") or "chitchat"
    if intent in ("vision_compare", "vision_single"):
        return "vision_analysis"
    if intent == "parameter_change":
        return "parameter_update"
    if intent == "quote_explain":
        return "explain_quote"
    return "generate_response"


def route_after_vision(state: QuotationState) -> str:
    """视觉节点结束后：若已写入可核算的 BOM（items），强制再走 Calculator。"""
    params = state.get("parameters") or {}
    items = params.get("items")
    if isinstance(items, list) and len(items) > 0:
        return "calculator"
    return "generate_response"


def _compact_quote_snapshot_for_prompt(calc: dict[str, Any] | None, *, max_chars: int = 16000) -> str:
    if not isinstance(calc, dict):
        return "{}"
    raw = json.dumps(calc, ensure_ascii=False, default=str)
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + "\n…(truncated)"


def _parameters_digest(parameters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        return {}
    items = parameters.get("items")
    names: list[str] = []
    if isinstance(items, list):
        for row in items[:16]:
            if isinstance(row, dict):
                names.append(str(row.get("name") or "").strip()[:48])
    return {
        "product_name": parameters.get("product_name"),
        "quantities": parameters.get("quantities"),
        "quantity": parameters.get("quantity"),
        "material": parameters.get("material"),
        "material_fabric": parameters.get("material_fabric"),
        "processing_fee": parameters.get("processing_fee"),
        "system_overhead": parameters.get("system_overhead"),
        "mold_fee": parameters.get("mold_fee"),
        "gross_margin_rate": parameters.get("gross_margin_rate"),
        "bom_row_names_preview": names,
        "bom_rows": len(items) if isinstance(items, list) else 0,
    }


def _fallback_quote_explain_body(state: QuotationState, err_note: str) -> str:
    calc = state.get("calculation_result") if isinstance(state.get("calculation_result"), dict) else {}
    try:
        from quote_explain import build_local_quote_explanation_text

        return build_local_quote_explanation_text(
            calc,
            user_question=str(state.get("user_message") or ""),
            advisory_error=err_note,
        )
    except Exception:  # noqa: BLE001
        lines = ["当前未调用到大模型或调用失败；以下为基于系统核算结果的极简摘要。"]
        if err_note:
            lines.append(f"调用备注：{err_note}")
        if calc.get("error"):
            lines.append(f"核算未完成：{calc.get('error')}")
            return "\n".join(lines)
        mt = calc.get("material_total_text") or calc.get("material_total")
        tiers = calc.get("tiers") if isinstance(calc.get("tiers"), list) else []
        lines.append(f"物料合计（系统）：{mt or '-'}")
        if tiers and isinstance(tiers[0], dict):
            t0 = tiers[0]
            lines.append(
                "首档示例：数量 "
                f"{t0.get('quantity') or '-'}；成本/件 {t0.get('cost_before_margin_text') or t0.get('cost_before_margin') or '-'}；"
                f"EXW {t0.get('exw_price_text') or '-'}"
            )
        return "\n".join(lines)


def explain_quote_node(state: QuotationState) -> dict[str, Any]:
    """基于 Python 核算快照，用 Kimi 白话解释「怎么算的 / 为啥和您不一致」。"""
    msg = (state.get("user_message") or "").strip()
    calc_json = _compact_quote_snapshot_for_prompt(state.get("calculation_result"))
    digest = _parameters_digest(dict(state.get("parameters") or {}))
    inner = json.dumps({"用户问题": msg, "核算引擎JSON": calc_json, "参数摘要": digest}, ensure_ascii=False)

    sys_prompt = (
        "你是箱包 OEM 报价顾问。你将收到「核算引擎」输出的 JSON（数字以它为准）和用户的质疑/追问。"
        "要求：\n"
        "1）只用 JSON 中出现的数字与字段解释，不要编造新的物料行、单价或小计。\n"
        "2）用分段大白话：先总后分；典型顺序为 物料合计 → 加工费/杂费/模具摊销 → 单件系统成本 → 含税参考（若快照有）→ 毛利/EXW（若快照有 tiers 与说明）。\n"
        "3）若用户觉得「和你们算的不一样」，点出 2～3 个最常见的口径陷阱（含税、毛利是除法而不是乘成本 30%、模具按量摊销导致各档单价不同等）但不武断否定用户。\n"
        "4）若 JSON 缺少关键字段，直接说缺什么，让用户补图或补充手算假设。"
        "禁止输出 Markdown 巨表；少量行内数字即可。"
    )

    text: str
    err_note = ""
    if moonshot_api_key():
        try:
            text = chat_completions(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": inner},
                ],
                model=os.environ.get("QUOTATION_AGENT_EXPLAIN_MODEL") or default_text_model(),
                temperature=0.35,
                max_tokens=4096,
            ).strip()
        except Exception as exc:  # noqa: BLE001
            err_note = str(exc)
            text = _fallback_quote_explain_body(state, err_note)
    else:
        text = _fallback_quote_explain_body(state, "未配置 MOONSHOT_API_KEY")

    return {"quote_explanation_text": text}


def vision_analysis_node(state: QuotationState) -> dict[str, Any]:
    """视觉分析：Kimi 多模态抽取 / 对比；结构化进 ``extracted_data``，白话进 ``reply_plain``。"""
    msg = (state.get("user_message") or "").strip()
    images_b64 = list(state.get("current_images") or [])
    intent = state.get("last_intent") or ""

    reply_plain, extracted_delta, bom_patch = _vision_with_kimi_optional(
        images_b64, msg, compare_mode=intent == "vision_compare"
    )
    merged_patch = dict(state.get("vision_extracted_patch") or {})
    merged_patch.update(bom_patch)

    merged_extracted = dict(state.get("extracted_data") or {})
    merged_extracted.update(extracted_delta)

    updates: dict[str, Any] = {
        "vision_analysis_text": reply_plain,
        "vision_extracted_patch": merged_patch,
        "extracted_data": merged_extracted,
    }
    params = dict(state.get("parameters") or {})
    bp = bom_patch
    if isinstance(bp.get("items"), list) and bp["items"]:
        params["items"] = bp["items"]
    if bp.get("quantities"):
        params["quantities"] = bp["quantities"]
    if bp.get("product_name"):
        params["product_name"] = bp["product_name"]
    if params != state.get("parameters"):
        updates["parameters"] = params
    return updates


def _vision_with_kimi_optional(
    images_b64: list[str],
    user_text: str,
    *,
    compare_mode: bool,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """调用 Moonshot 视觉接口；返回 (白话正文, extracted_data 增量, BOM 合并补丁)。"""
    if not images_b64:
        return ("本轮未附带图片。", {}, {})

    mime_default = os.environ.get("QUOTATION_AGENT_VISION_MIME", "image/jpeg")
    pairs: list[tuple[str, str]] = [(mime_default, b.strip()) for b in images_b64 if b.strip()]

    schema_hint = (
        '你必须只输出 **一段合法 JSON 对象**（不要 Markdown、不要代码围栏）。顶层字段固定为：\n'
        '{"reply_plain":"给用户的大白话说明，分段叙述；禁止用大表格刷屏；优先解释差异逻辑与可疑口径",'
        '"extracted_data":{\n'
        '  "quotes":[{"label":"图A|图B|截图1","material_total":"","processing_fee":"","overhead":"","mold_share":"","tax_hint":"","margin_hint":"","exw_or_unit_price":"","quantity_tier":""}],\n'
        '  "key_differences":[{"aspect":"","figure_a":"","figure_b":"","impact_note":""}],\n'
        '  "red_flags":[{"issue":"","severity":"","detail":""}]\n'
        "},\n"
        '"items":[{"name":"","spec":"","usage":"","unit_price":"","amount":0}],\n'
        '"quantities":[500,1000,1500],\n'
        '"product_name":""}\n'
        "其中 items/quantities/product_name 仅在确有把握时填写；对比模式下 extracted_data.quotes 至少两行。"
    )

    task = (
        "你是箱包 OEM 报价审计助手。用户上传了报价截图或物料截图。\n"
        + (
            "**对比两张（或以上）图**：抓住主料费、辅料、加工费、杂费/管理费、模具摊销、含税口径、毛利（倒扣）与 EXW 的差异；"
            "说明「差额主要来自哪里」（例如模具摊销随数量下降、毛利公式用成本÷(1-毛利率) 等），但不要编造图上没有的数值。\n"
            if compare_mode
            else "**单图**：抽取可见 BOM / 报价字段；看不清的数字写「未能识别」，勿臆测。\n"
        )
        + schema_hint
        + "\n用户问题："
        + user_text
    )

    if not moonshot_api_key():
        return (
            "[占位] 未配置 MOONSHOT_API_KEY：无法调用 Kimi 视觉。"
            "已接收 {} 张图。".format(len(pairs)),
            {},
            {},
        )

    try:
        raw_text = chat_completions_multimodal_user(
            text=task,
            images_b64=pairs[:6],
            model=os.environ.get("QUOTATION_AGENT_VISION_MODEL") or default_vision_model(),
            temperature=0.35,
            max_tokens=8192,
            timeout_sec=180,
        )
        obj = _extract_json_object(raw_text)
        reply_plain = str(obj.get("reply_plain") or "").strip()
        if not reply_plain:
            reply_plain = raw_text.strip() or "（模型未给出可读正文）"

        extracted_delta: dict[str, Any] = {}
        if isinstance(obj.get("extracted_data"), dict):
            extracted_delta = dict(obj["extracted_data"])

        bom_patch: dict[str, Any] = {}
        if isinstance(obj.get("items"), list):
            bom_patch["items"] = obj["items"]
        if obj.get("quantities"):
            bom_patch["quantities"] = obj["quantities"]
        if obj.get("product_name"):
            bom_patch["product_name"] = obj["product_name"]

        return reply_plain, extracted_delta, bom_patch
    except Exception as exc:  # noqa: BLE001
        logger.warning("vision request failed: %s", exc)
        return (f"[视觉调用失败] {exc!s}", {}, {})


def _extract_json_object(text: str) -> dict[str, Any]:
    """从模型回复中抠 JSON object（容忍 ```json 围栏）。"""
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("\n", 1)
        if len(parts) == 2:
            rest = parts[1]
            if "```" in rest:
                t = rest.rsplit("```", 1)[0].strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        obj = json.loads(t[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def parameter_update_node(state: QuotationState) -> dict[str, Any]:
    """从用户话语抽取结构化补丁，合并进 parameters（保留未提及字段）。"""
    msg = (state.get("user_message") or "").strip()
    params = dict(state.get("parameters") or {})

    note_parts: list[str] = []

    # --- 启发式：数量 ---
    for pat in (r"(\d+)\s*件", r"(\d+)\s*个", r"数量\D*(\d+)", r"改成\D*(\d+)", r"改为\D*(\d+)"):
        m = re.search(pat, msg)
        if m:
            q = int(m.group(1))
            params["quantity"] = q
            params["quantities"] = [q]
            note_parts.append(f"quantity→{q}")
            break

    # --- 启发式：面料关键词写入自定义槽位（可按业务映射到 BOM）---
    fabric_map = (
        ("尼龙", "尼龙面料"),
        ("涤纶", "涤纶面料"),
        ("牛津", "牛津布"),
        ("帆布", "帆布"),
        ("rpet", "RPET"),
        ("RPET", "RPET"),
    )
    lower = msg.lower()
    for kw, label in fabric_map:
        matched = kw in msg
        if not matched and kw.isascii():
            matched = kw.lower() in lower
        if matched:
            params["material_fabric"] = label
            params["material"] = label
            note_parts.append(f"material→{label}")
            break

    # --- 可选：LangChain 抽取 JSON delta ---
    delta = _extract_parameters_llm(msg)
    if delta:
        for k, v in delta.items():
            if v is not None:
                params[k] = v
        note_parts.append("llm_patch")

    if params.get("material") and not params.get("material_fabric"):
        params["material_fabric"] = str(params["material"])
    elif params.get("material_fabric") and not params.get("material"):
        params["material"] = str(params["material_fabric"])

    return {
        "parameters": params,
        "parameter_delta_note": "；".join(note_parts) if note_parts else "（规则未命中显性字段）",
    }


def _extract_parameters_llm(message: str) -> dict[str, Any]:
    if not _env_flag("QUOTATION_AGENT_USE_LLM_EXTRACTOR"):
        return {}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError:
        return {}

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        return {}

    base_url = (
        os.environ.get("MOONSHOT_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or moonshot_base_url()
    )
    model = os.environ.get("QUOTATION_AGENT_EXTRACT_MODEL") or default_text_model()
    kwargs: dict[str, Any] = {"model": model, "api_key": api_key, "temperature": 0}
    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")

    llm = ChatOpenAI(**kwargs)
    sys = SystemMessage(
        content=(
            "从用户话中提取报价参数增量，仅输出 JSON 对象，键仅限："
            "quantity(int), quantities(list[int]), product_name(str), "
            "material(str), material_fabric(str), lining(str), size(str), "
            "items(list of BOM rows with name/spec/usage/unit_price/amount). "
            "未提及的键不要输出。"
        )
    )
    try:
        resp = llm.invoke([sys, HumanMessage(content=message)])
        raw = getattr(resp, "content", "") or ""
        data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("parameter llm skipped: %s", exc)
        return {}


def calculator_node(state: QuotationState) -> dict[str, Any]:
    """纯 Python：组装 payload → calculate_quote。"""
    params = dict(state.get("parameters") or {})
    result = run_calculate_quote(params)
    return {"calculation_result": result, "ran_calculator_this_turn": True}


def generate_response_node(state: QuotationState) -> dict[str, Any]:
    """根据 vision / 核算结果生成用户可读回复，并写入 chat_history。"""
    intent = state.get("last_intent") or ""
    hist = list(state.get("chat_history") or [])

    if intent in ("vision_compare", "vision_single"):
        body = (state.get("vision_analysis_text") or "").strip() or "（视觉节点无输出）"
        reply = body
        if state.get("parameter_delta_note"):
            reply += f"\n\n【参数合并备注】{state['parameter_delta_note']}"
        if state.get("ran_calculator_this_turn"):
            calc = state.get("calculation_result") or {}
            err = calc.get("error") if isinstance(calc, dict) else None
            if err:
                reply += f"\n\n【按提取 BOM 尝试核算】未完成：{err}"
            else:
                mt = calc.get("material_total_text") if isinstance(calc, dict) else None
                exw = None
                tiers = calc.get("tiers") if isinstance(calc, dict) else None
                if isinstance(tiers, list) and tiers:
                    exw = tiers[0].get("exw_price_text")
                reply += (
                    f"\n\n【按提取 BOM 自动核算】\n"
                    f"- 物料合计：{mt or '—'}\n"
                    f"- 一档 EXW：{exw or '—'}"
                )
    elif intent == "parameter_change":
        calc = state.get("calculation_result") or {}
        err = calc.get("error") if isinstance(calc, dict) else None
        if err:
            reply = f"已尝试按新参数核算，但未完成：{err}"
        else:
            mt = calc.get("material_total_text") if isinstance(calc, dict) else None
            exw = None
            tiers = calc.get("tiers") if isinstance(calc, dict) else None
            if isinstance(tiers, list) and tiers:
                exw = tiers[0].get("exw_price_text")
            reply = (
                f"已根据最新参数完成核算。\n"
                f"- 物料合计：{mt or '—'}\n"
                f"- 一档 EXW：{exw or '—'}\n"
                f"- 本轮提取：{state.get('parameter_delta_note') or '—'}"
            )
    elif intent == "quote_explain":
        reply = (state.get("quote_explanation_text") or "").strip() or _fallback_quote_explain_body(
            state, ""
        )
    else:
        reply = (
            "我可以帮您：上传两张报价图做差异说明，或在已有 BOM 前提下说「换成尼龙、数量改 500」等。"
            "如需正式工作台报价，请继续使用现有上传表格流程。"
        )

    hist.append({"role": "assistant", "content": reply})
    return {"assistant_reply": reply, "final_reply": reply, "chat_history": hist}
