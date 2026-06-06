"""State and dependency types for the conversational quote agent."""
from __future__ import annotations

from typing import Any, Callable, TypedDict


class QuoteAgentState(TypedDict, total=False):
    sid: str
    user_message: str
    session_context: dict[str, Any]
    llm_status: dict[str, Any]
    memory: dict[str, Any]

    quote_id: str
    file_name: str
    base_payload: dict[str, Any]
    base_quote_result: dict[str, Any]
    has_valid_context: bool

    understood: dict[str, Any]
    context_error: str
    actions: list[str]
    working_payload: dict[str, Any]

    process_payload: dict[str, Any]
    explain_response: dict[str, Any]
    explanation_text: str
    alternatives_text: str
    assistant_message: str
    quote_result: dict[str, Any]
    material_meta: dict[str, Any]
    price_patch_meta: dict[str, Any]
    param_patch_meta: dict[str, Any]
    tool_notes: list[str]
    commit_mode: str
    response: dict[str, Any]


SessionGetPayload = Callable[[str, str], dict[str, Any] | None]
SessionGetResult = Callable[[str, str], dict[str, Any] | None]
SessionGetCurrentQuoteId = Callable[[str], str]
SessionSetCurrent = Callable[..., None]
FinalizePersistence = Callable[..., None]
ResolveSeriesUid = Callable[[str | None, dict | None, dict], str]
ApplyOutputGate = Callable[[dict, dict], None]
SyncAgentContext = Callable[..., None]
AgentMemoryPut = Callable[[str, dict], None]

QuoteAgentDeps = dict[str, Any]
