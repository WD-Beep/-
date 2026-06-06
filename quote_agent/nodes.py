"""LangGraph node functions for the quote agent."""
from __future__ import annotations

import copy
import uuid
from typing import Any

from quote_agent import parser
from quote_agent import tools
from quote_agent.state import QuoteAgentDeps, QuoteAgentState


def load_session_context(state: QuoteAgentState, deps: QuoteAgentDeps) -> dict[str, Any]:
    """Read current quote id, previous payload/result and display file name."""
    sc = state.get("session_context") if isinstance(state.get("session_context"), dict) else {}
    sid = str(state.get("sid") or "")
    qid = ""
    for key in ("currentQuoteId", "activeQuoteId", "quote_id", "quoteId"):
        qid = str(sc.get(key) or "").strip()
        if qid:
            break
    if not qid:
        getter = deps.get("get_current_quote_id")
        if getter is not None:
            qid = str(getter(sid) or "").strip()
    file_name = str(sc.get("fileName") or "").strip()
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    valid = False
    active_quote = sc.get("active_quote") if isinstance(sc.get("active_quote"), dict) else {}
    if active_quote:
        payload = active_quote.get("payload_snapshot") if isinstance(active_quote.get("payload_snapshot"), dict) else None
        result = active_quote.get("last_quote_result") if isinstance(active_quote.get("last_quote_result"), dict) else None
        if not qid:
            qid = str(active_quote.get("quote_id") or "").strip()
    if qid:
        payload = payload or deps["get_payload_for_quote"](sid, qid)
        result = result or deps["get_last_quote_result"](sid, qid)
        valid = isinstance(payload, dict) and isinstance(result, dict) and bool(payload.get("items"))
    return {
        "quote_id": qid,
        "file_name": file_name,
        "base_payload": copy.deepcopy(payload or {}),
        "base_quote_result": copy.deepcopy(result or {}),
        "working_payload": copy.deepcopy(payload or {}),
        "has_valid_context": valid,
    }


def understand_user_request(state: QuoteAgentState) -> dict[str, Any]:
    """Parse a turn into a composite structured request."""
    msg = str(state.get("user_message") or "").strip()
    mem = state.get("memory") if isinstance(state.get("memory"), dict) else {}
    parsed, planner_status = parser.understand_message(
        msg,
        has_pending_trial=bool(mem.get("pending_trial_payload")),
    )
    llm_status = dict(state.get("llm_status") or {})
    llm_status["agent_understand"] = planner_status
    return {"understood": parsed, "llm_status": llm_status}


def validate_context(state: QuoteAgentState) -> dict[str, Any]:
    """Return a natural prompt when a quote-dependent request has no context."""
    understood = state.get("understood") if isinstance(state.get("understood"), dict) else {}
    needs_context = bool(
        understood.get("wants_process")
        or understood.get("wants_explanation")
        or understood.get("material_change")
        or understood.get("wants_alternatives")
        or understood.get("quantity") is not None
        or understood.get("gross_margin_rate") is not None
        or bool(understood.get("price_patch"))
        or understood.get("commit_requested")
        or understood.get("wants_explain_only")
    )
    if needs_context and not state.get("has_valid_context"):
        return {
            "context_error": (
                "我还没有可引用的上一单报价，不能直接换料、改数量或解释计算过程。"
                "请先上传 BOM/表格完成一次报价，或直接描述产品、材料和数量让我生成新报价。"
            )
        }
    return {"context_error": ""}


def plan_actions(state: QuoteAgentState) -> dict[str, Any]:
    """Decide local tool sequence; process cards and trial recalcs can coexist."""
    if state.get("context_error"):
        return {"actions": ["clarify"]}
    u = state.get("understood") if isinstance(state.get("understood"), dict) else {}
    actions: list[str] = []
    if u.get("wants_explain_only") or (
        u.get("wants_explanation")
        and not u.get("material_change")
        and not u.get("price_patch")
        and u.get("quantity") is None
        and u.get("gross_margin_rate") is None
    ):
        actions.append("explain_quote")
    elif u.get("wants_process"):
        actions.append("build_process")
    elif u.get("wants_explanation"):
        actions.append("explain_quote")
    if u.get("material_change"):
        actions.append("substitute_material")
    if u.get("price_patch"):
        actions.append("patch_unit_price")
    if u.get("quantity") is not None or u.get("gross_margin_rate") is not None:
        actions.append("patch_params")
    if u.get("wants_alternatives"):
        actions.append("alternatives")
    if u.get("commit_pending_trial"):
        actions.append("commit_pending_trial")
    elif any(a in actions for a in ("substitute_material", "patch_unit_price", "patch_params")):
        actions.append("calculate")
    return {"actions": actions}


def execute_quote_tools(state: QuoteAgentState, deps: QuoteAgentDeps) -> dict[str, Any]:
    """Call local tools only. LLMs are never used to produce final quote truth."""
    actions = list(state.get("actions") or [])
    if "clarify" in actions:
        return {"assistant_message": str(state.get("context_error") or "")}

    payload = copy.deepcopy(state.get("working_payload") or {})
    out: dict[str, Any] = {"working_payload": payload}
    notes = list(state.get("tool_notes") or [])
    u = state.get("understood") if isinstance(state.get("understood"), dict) else {}
    user_message = str(state.get("user_message") or "")

    if "build_process" in actions:
        out["process_payload"] = tools.build_process_payload(state.get("base_quote_result") or {})
    if "explain_quote" in actions:
        out["explain_response"] = tools.build_explain_response(
            state.get("base_quote_result") or {},
            user_message,
            llm_status=state.get("llm_status") if isinstance(state.get("llm_status"), dict) else {},
        )

    if "local_explain" in actions:
        out["explanation_text"] = tools.build_local_explanation(
            state.get("base_quote_result") or {},
            user_message,
        )

    if "commit_pending_trial" in actions:
        pending = (state.get("memory") or {}).get("pending_trial_payload")
        if isinstance(pending, dict) and pending.get("items"):
            payload = copy.deepcopy(pending)
            out["working_payload"] = payload
        else:
            out["assistant_message"] = "当前没有可确认的试算方案，请先试算一次。"
            return out

    if "substitute_material" in actions:
        substituted, meta, holder = tools.apply_substitution_to_payload(payload, user_message)
        out["material_meta"] = dict(meta or {})
        if holder:
            notes.append("材料补价调用了模型/兜底补全。")
        if substituted is None:
            out["assistant_message"] = str((meta or {}).get("error") or "无法完成材料替换。")
            return out
        payload = substituted
        notes.append(
            f"已替换物料：{meta.get('old_material_label') or '-'} -> "
            f"{meta.get('new_material_label') or meta.get('query_phrase') or '-'}"
        )
        out["working_payload"] = payload

    if "patch_unit_price" in actions:
        patched, meta = tools.apply_price_patch_to_payload(
            payload,
            u.get("price_patch"),
            state.get("base_quote_result") or {},
        )
        out["price_patch_meta"] = dict(meta or {})
        if patched is None:
            out["assistant_message"] = str((meta or {}).get("error") or "无法完成单价改动。")
            return out
        payload = patched
        notes.append(
            f"已试算单价改动：{meta.get('target_label') or '-'} "
            f"{meta.get('old_unit_price') or '-'} -> {meta.get('new_unit_price') or '-'}"
        )
        out["working_payload"] = payload

    if "patch_params" in actions:
        before = copy.deepcopy(payload)
        payload = tools.patch_payload_params(payload, user_message, u)
        param_meta = tools.build_param_patch_meta(before, payload, u)
        if param_meta:
            out["param_patch_meta"] = param_meta
            notes.append(
                f"已试算参数改动：{param_meta.get('target_label') or '-'} "
                f"{param_meta.get('old_value') or '-'} -> {param_meta.get('new_value') or '-'}"
            )
        out["working_payload"] = payload

    if "alternatives" in actions:
        out["alternatives_text"] = tools.suggest_alternatives(
            str(u.get("material_query") or ""),
            payload,
            user_message,
        )

    if "calculate" in actions or "commit_pending_trial" in actions:
        if not tools.has_effective_material_pricing(payload.get("items")):
            out["assistant_message"] = "本轮需要重算，但没有有效物料金额，请先补全物料价格。"
            return out
        out["quote_result"] = tools.calculate_local_quote(
            payload,
            apply_output_gate=deps.get("apply_output_gate"),
        )
    out["tool_notes"] = notes
    return out


def decide_commit_mode(state: QuoteAgentState) -> dict[str, Any]:
    """Trial never overwrites; commit updates the main quote context."""
    u = state.get("understood") if isinstance(state.get("understood"), dict) else {}
    if u.get("commit_requested"):
        return {"commit_mode": "commit"}
    # 局部试算默认 trial；写入价格库需用户明确说「保存到价格库」（由上层 price_admin 处理）
    if state.get("quote_result"):
        return {"commit_mode": "trial"}
    return {"commit_mode": "none"}


def update_session(state: QuoteAgentState, deps: QuoteAgentDeps) -> dict[str, Any]:
    """Only commit updates the current main quote. Trial stores pending memory."""
    quote = state.get("quote_result")
    mode = str(state.get("commit_mode") or "none")
    sid = str(state.get("sid") or "")
    mem = copy.deepcopy(state.get("memory") or {})
    working = copy.deepcopy(state.get("working_payload") or {})

    if isinstance(quote, dict) and quote:
        quote["quote_ready"] = True
        quote["quote_id"] = str(uuid.uuid4())
        quote["intent"] = "agent_commit" if mode == "commit" else "agent_trial"
        quote["llm_status"] = tools.status_with_plan(state)
        if isinstance(state.get("process_payload"), dict):
            quote["agent_process"] = {
                "title": "计算过程拆解",
                "file_hint": str(state.get("file_name") or ""),
                "process": state["process_payload"],
            }
        quote["metadata"] = tools.quote_metadata(state, quote)
        quote_patch = tools.build_quote_patch(state, quote)
        if quote_patch:
            quote["quote_patch"] = quote_patch
            quote["assistant_message"] = tools.build_patch_message(quote_patch)
        if mode == "trial" and (quote.get("metadata") or {}).get("is_extra_material_calc"):
            quote["trial_items_snapshot"] = copy.deepcopy(working.get("items") or [])
            quote["reply_type"] = "material_substitution"

    if isinstance(quote, dict) and quote and mode == "commit":
        snap = copy.deepcopy(working)
        snap.pop("uploaded_sheet", None)
        resolve_series = deps.get("resolve_quote_series_uid")
        series_uid = resolve_series(sid, working, quote) if resolve_series else str(quote.get("quote_id") or "")
        finalize = deps.get("finalize_quote_persistence")
        if finalize is not None:
            finalize(
                quote_series_uid=series_uid,
                quote_result=quote,
                uploaded_sheet=working.get("uploaded_sheet") if isinstance(working.get("uploaded_sheet"), dict) else None,
                sheet_original_display_name=str(state.get("file_name") or ""),
            )
        deps["set_current_quote"](
            sid,
            str(quote.get("quote_id") or ""),
            str(state.get("file_name") or ""),
            snap,
            quote,
            quote_series_uid=series_uid,
        )
        mem.pop("pending_trial_payload", None)
        mem.pop("pending_trial_result", None)
        _put_memory(deps, sid, mem)
        _sync_context(deps, sid, snap, quote, str(state.get("user_message") or ""))
    elif isinstance(quote, dict) and quote:
        snap = copy.deepcopy(working)
        snap.pop("uploaded_sheet", None)
        mem["pending_trial_payload"] = snap
        mem["pending_trial_result"] = copy.deepcopy(quote)
        _put_memory(deps, sid, mem)
        _sync_context(deps, sid, state.get("base_payload") or {}, quote, str(state.get("user_message") or ""))
    return {"quote_result": quote, "memory": mem}


def build_response(state: QuoteAgentState) -> dict[str, Any]:
    """Build frontend-compatible quote cards, process cards or friendly prompts."""
    explain_resp = state.get("explain_response")
    if isinstance(explain_resp, dict) and explain_resp.get("assistant_message"):
        return {"response": explain_resp}

    quote = state.get("quote_result")
    if isinstance(quote, dict) and quote:
        return {"response": quote}
    process = state.get("process_payload")
    if isinstance(process, dict) and process:
        return {
            "response": {
                "quote_ready": False,
                "reply_type": "process_card",
                "title": "计算过程拆解",
                "file_hint": str(state.get("file_name") or ""),
                "process": process,
                "intent": "QUOTE_PROCESS",
                "llm_status": tools.status_with_plan(state),
            }
        }
    msg = str(
        state.get("assistant_message")
        or state.get("alternatives_text")
        or state.get("explanation_text")
        or state.get("context_error")
        or "我还需要更具体的操作，例如「500件试算」或「改成500件以这个为准」。"
    )
    from clarify_once import ClarifySpec, build_clarify_response, clarify_from_agent_error

    clarified = clarify_from_agent_error(msg)
    if clarified is not None:
        clarified["llm_status"] = tools.status_with_plan(state)
        return {"response": clarified}
    if state.get("context_error"):
        return {
            "response": build_clarify_response(
                ClarifySpec(
                    "active_quote_missing",
                    msg,
                    ("active_quote", "upload_or_bom"),
                )
            )
        }
    actions = list(state.get("actions") or [])
    intent = "QUOTE_EXPLAIN" if ("explain_quote" in actions or "local_explain" in actions) else "AGENT_MESSAGE"
    return {
        "response": {
            "quote_ready": False,
            "reply_type": "clarify_question",
            "assistant_message": msg,
            "intent": intent,
            "missing_fields": ["patch_target"],
            "llm_status": tools.status_with_plan(state),
        }
    }


def _put_memory(deps: QuoteAgentDeps, sid: str, memory: dict[str, Any]) -> None:
    fn = deps.get("agent_memory_put")
    if fn is not None:
        fn(sid, memory)


def _sync_context(
    deps: QuoteAgentDeps,
    sid: str,
    payload: dict[str, Any],
    quote: dict[str, Any],
    user_message: str,
) -> None:
    fn = deps.get("sync_agent_context")
    if fn is not None:
        fn(
            sid=sid,
            payload_snapshot=payload,
            quote_result=quote,
            user_message=user_message,
            local_intent=str(quote.get("intent") or "agent_workflow"),
        )
