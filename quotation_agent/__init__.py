"""箱包报价 LangGraph 智能体（脚手架）。

与现有 ``quote_engine`` 通过 ``calculator_bridge`` 衔接；可选 HTTP：
``POST /api/agent-turn``（见 ``server.py``），不改变原有 ``/api/quote`` 流程。

依赖（可选）：``pip install langgraph langchain-core``；
意图/抽取增强：``pip install langchain-openai``。"""
from __future__ import annotations

from quotation_agent.graph import build_quotation_graph, invoke_turn
from quotation_agent.state import QuotationState, empty_quotation_state

__all__ = [
    "QuotationState",
    "build_quotation_graph",
    "empty_quotation_state",
    "invoke_turn",
]
