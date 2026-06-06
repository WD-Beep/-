"""Compatibility wrapper for the quote-agent LangGraph workflow.

The implementation now lives in ``quote_agent`` so the workflow is split into
state, parser, tools, nodes and graph wiring. This module keeps older imports
working.
"""
from __future__ import annotations

from quote_agent.graph import build_quote_agent_graph, invoke_quote_agent, invoke_quote_followup_graph
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
from quote_agent.parser import _rule_understand
from quote_agent.state import QuoteAgentState as QuoteFollowupState

__all__ = [
    "QuoteFollowupState",
    "build_quote_agent_graph",
    "invoke_quote_agent",
    "invoke_quote_followup_graph",
    "load_session_context",
    "understand_user_request",
    "validate_context",
    "plan_actions",
    "execute_quote_tools",
    "decide_commit_mode",
    "update_session",
    "build_response",
    "_rule_understand",
]

