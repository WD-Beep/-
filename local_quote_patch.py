"""基于 active_quote 的局部试算：只改上一单 payload 中的目标字段，再走既有 calculate_quote。

不重新解析整张表，不修改 quote_engine 内正式公式。试算结果默认 trial，不写价格库。
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from quote_agent import parser, tools
from session_quote_context import GLOBAL_SESSION_STORE

SessionGetPayload = Callable[[str, str], dict[str, Any] | None]
SessionGetResult = Callable[[str, str], dict[str, Any] | None]
ApplyOutputGate = Callable[[dict[str, Any], dict[str, Any]], None] | None


def resolve_active_quote(
    sid: str,
    session_context: dict[str, Any] | None,
    *,
    get_current_quote_id: Callable[[str], str] = GLOBAL_SESSION_STORE.get_current_quote_id,
    get_payload_for_quote: SessionGetPayload = GLOBAL_SESSION_STORE.get_payload_for_quote,
    get_last_quote_result: SessionGetResult = GLOBAL_SESSION_STORE.get_last_quote_result,
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """从 session_context / GLOBAL_SESSION_STORE 读取 active_quote。"""
    sc = session_context if isinstance(session_context, dict) else {}
    qid = ""
    for key in ("currentQuoteId", "activeQuoteId", "quote_id", "quoteId"):
        qid = str(sc.get(key) or "").strip()
        if qid:
            break
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    active = sc.get("active_quote") if isinstance(sc.get("active_quote"), dict) else {}
    if active:
        payload = active.get("payload_snapshot") if isinstance(active.get("payload_snapshot"), dict) else None
        result = active.get("last_quote_result") if isinstance(active.get("last_quote_result"), dict) else None
        if not qid:
            qid = str(active.get("quote_id") or "").strip()
    if not qid:
        qid = str(get_current_quote_id(sid) or "").strip()
    if qid:
        payload = payload or get_payload_for_quote(sid, qid)
        result = result or get_last_quote_result(sid, qid)
    if not isinstance(payload, dict) or not payload.get("items"):
        return qid, None, None
    return qid, copy.deepcopy(payload), copy.deepcopy(result) if isinstance(result, dict) else None


def parse_local_patch(user_message: str) -> dict[str, Any]:
    """解析用户局部改动意图（包装/材料单价/数量/加工费/模具分摊）。"""
    understood, _planner = parser.understand_message(user_message, has_pending_trial=False)
    return understood


def apply_local_patch(
    base_payload: dict[str, Any],
    base_quote_result: dict[str, Any] | None,
    understood: dict[str, Any],
    user_message: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    """
    将 patch 应用到 payload 副本。
    返回 (patched_payload, patch_meta, error_message)。
    """
    payload = copy.deepcopy(base_payload)
    price_patch = understood.get("price_patch")
    if isinstance(price_patch, dict):
        patched, meta = tools.apply_price_patch_to_payload(
            payload,
            price_patch,
            base_quote_result,
        )
        if patched is None:
            return None, dict(meta or {}), str((meta or {}).get("error") or "无法完成单价改动。")
        return patched, dict(meta or {}), ""

    if understood.get("quantity") is not None or understood.get("gross_margin_rate") is not None:
        before = copy.deepcopy(payload)
        patched = tools.patch_payload_params(payload, user_message, understood)
        meta = tools.build_param_patch_meta(before, patched, understood)
        if not meta:
            return None, {}, "没有识别到要改的参数。"
        return patched, meta, ""

    return None, {}, "没有识别到可试算的局部改动，请说明要改包装、材料单价、数量或加工费。"


def run_local_quote_trial(
    *,
    sid: str,
    user_message: str,
    session_context: dict[str, Any] | None = None,
    apply_output_gate: ApplyOutputGate = None,
) -> dict[str, Any]:
    """
    基于 active_quote 做局部试算。
    成功时返回 quote_ready=True、quote_patch、assistant_message；失败时返回澄清文案。
    """
    qid, base_payload, base_result = resolve_active_quote(sid, session_context)
    if base_payload is None:
        return {
            "quote_ready": False,
            "assistant_message": (
                "我还没有可引用的上一单报价，不能直接做局部试算。"
                "请先上传 BOM/表格完成一次报价。"
            ),
            "intent": "AGENT_MESSAGE",
            "quote_patch": {},
        }

    understood = parse_local_patch(user_message)
    if understood.get("wants_explanation") and not (
        understood.get("price_patch")
        or understood.get("quantity") is not None
        or understood.get("material_change")
    ):
        return {
            "quote_ready": False,
            "assistant_message": tools.build_local_explanation(base_result or {}, user_message),
            "intent": "QUOTE_EXPLAIN",
            "quote_patch": {},
        }

    patched, patch_meta, err = apply_local_patch(
        base_payload,
        base_result,
        understood,
        user_message,
    )
    if patched is None:
        return {
            "quote_ready": False,
            "assistant_message": err or "无法完成局部试算。",
            "intent": "AGENT_MESSAGE",
            "quote_patch": {},
        }

    if not tools.has_effective_material_pricing(patched.get("items")):
        return {
            "quote_ready": False,
            "assistant_message": "本轮需要重算，但没有有效物料金额，请先补全物料价格。",
            "intent": "AGENT_MESSAGE",
            "quote_patch": {},
        }

    quote = tools.calculate_local_quote(patched, apply_output_gate=apply_output_gate)
    quote["quote_ready"] = True
    quote["intent"] = "agent_trial"
    quote["quote_id"] = qid or quote.get("quote_id")

    state: dict[str, Any] = {
        "base_quote_result": base_result or {},
        "base_payload": base_payload,
        "working_payload": patched,
        "actions": ["patch_unit_price" if understood.get("price_patch") else "patch_params"],
    }
    if understood.get("price_patch"):
        state["price_patch_meta"] = patch_meta
    else:
        state["param_patch_meta"] = patch_meta

    quote_patch = tools.build_quote_patch(state, quote)
    if quote_patch:
        quote["quote_patch"] = quote_patch
        quote["assistant_message"] = tools.build_patch_message(quote_patch)
    quote["metadata"] = {
        "mode": "trial",
        "is_extra_calc": True,
        "local_quote_patch": True,
        "patch_type": quote_patch.get("patch_type") if quote_patch else "",
    }
    return quote
