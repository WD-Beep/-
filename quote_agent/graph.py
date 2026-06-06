"""LangGraph wiring for the conversational quote agent."""
from __future__ import annotations

import copy
from typing import Any

from quote_agent.nodes import (
    build_response,
    decide_commit_mode,
    execute_quote_tools,
    load_session_context,
    plan_actions,
    understand_user_request,
    update_session,
    validate_context,
)
from quote_agent.state import (
    AgentMemoryPut,
    ApplyOutputGate,
    FinalizePersistence,
    QuoteAgentDeps,
    QuoteAgentState,
    SessionGetCurrentQuoteId,
    ResolveSeriesUid,
    SessionGetPayload,
    SessionGetResult,
    SessionSetCurrent,
    SyncAgentContext,
)
from session_quote_context import GLOBAL_SESSION_STORE


def build_quote_agent_graph(deps: QuoteAgentDeps):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise ImportError("请先安装 LangGraph：pip install langgraph langchain-core") from exc

    def _load(s: QuoteAgentState) -> dict[str, Any]:
        return load_session_context(s, deps)

    def _execute(s: QuoteAgentState) -> dict[str, Any]:
        return execute_quote_tools(s, deps)

    def _update(s: QuoteAgentState) -> dict[str, Any]:
        return update_session(s, deps)

    g = StateGraph(QuoteAgentState)
    g.add_node("load_session_context", _load)
    g.add_node("understand_user_request", understand_user_request)
    g.add_node("validate_context", validate_context)
    g.add_node("plan_actions", plan_actions)
    g.add_node("execute_quote_tools", _execute)
    g.add_node("decide_commit_mode", decide_commit_mode)
    g.add_node("update_session", _update)
    g.add_node("build_response", build_response)
    g.add_edge(START, "load_session_context")
    g.add_edge("load_session_context", "understand_user_request")
    g.add_edge("understand_user_request", "validate_context")
    g.add_edge("validate_context", "plan_actions")
    g.add_edge("plan_actions", "execute_quote_tools")
    g.add_edge("execute_quote_tools", "decide_commit_mode")
    g.add_edge("decide_commit_mode", "update_session")
    g.add_edge("update_session", "build_response")
    g.add_edge("build_response", END)
    return g.compile()


def invoke_quote_agent(
    *,
    sid: str,
    user_message: str,
    session_context: dict[str, Any],
    llm_status: dict[str, Any],
    memory: dict[str, Any],
    get_current_quote_id: SessionGetCurrentQuoteId = GLOBAL_SESSION_STORE.get_current_quote_id,
    get_payload_for_quote: SessionGetPayload = GLOBAL_SESSION_STORE.get_payload_for_quote,
    get_last_quote_result: SessionGetResult = GLOBAL_SESSION_STORE.get_last_quote_result,
    set_current_quote: SessionSetCurrent = GLOBAL_SESSION_STORE.set_current_quote,
    finalize_quote_persistence: FinalizePersistence | None = None,
    resolve_quote_series_uid: ResolveSeriesUid | None = None,
    apply_output_gate: ApplyOutputGate | None = None,
    sync_agent_context: SyncAgentContext | None = None,
    agent_memory_put: AgentMemoryPut | None = None,
) -> dict[str, Any]:
    """Run one quote follow-up turn and return an API-compatible response."""
    deps: QuoteAgentDeps = {
        "get_current_quote_id": get_current_quote_id,
        "get_payload_for_quote": get_payload_for_quote,
        "get_last_quote_result": get_last_quote_result,
        "set_current_quote": set_current_quote,
        "finalize_quote_persistence": finalize_quote_persistence,
        "resolve_quote_series_uid": resolve_quote_series_uid,
        "apply_output_gate": apply_output_gate,
        "sync_agent_context": sync_agent_context,
        "agent_memory_put": agent_memory_put,
    }
    initial: QuoteAgentState = {
        "sid": sid,
        "user_message": user_message,
        "session_context": copy.deepcopy(session_context or {}),
        "llm_status": copy.deepcopy(llm_status or {}),
        "memory": copy.deepcopy(memory or {}),
        "tool_notes": [],
        "actions": [],
    }
    out = build_quote_agent_graph(deps).invoke(initial)
    response = out.get("response")
    if isinstance(response, dict):
        return response
    return {
        "quote_ready": False,
        "assistant_message": "本轮报价工作流没有生成结果，请补充需求或重新上传报价表。",
        "intent": "AGENT_MESSAGE",
        "llm_status": llm_status,
    }


# Compatibility name used by the first LangGraph follow-up integration.
invoke_quote_followup_graph = invoke_quote_agent
