"""LangGraph StateGraph：意图路由 + 强制「改参数 → 参数更新 → 核算 → 回复」。"""
from __future__ import annotations

from typing import Any

from quotation_agent.nodes import (
    calculator_node,
    explain_quote_node,
    generate_response_node,
    intent_router_node,
    parameter_update_node,
    route_after_intent,
    route_after_vision,
    vision_analysis_node,
)
from quotation_agent.state import QuotationState


def build_quotation_graph():
    """编译并返回可 invoke 的 Graph。"""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as e:
        raise ImportError(
            "请先安装 LangGraph：pip install langgraph langchain-core"
        ) from e

    g = StateGraph(QuotationState)
    g.add_node("intent_router", intent_router_node)
    g.add_node("vision_analysis", vision_analysis_node)
    g.add_node("explain_quote", explain_quote_node)
    g.add_node("parameter_update", parameter_update_node)
    g.add_node("calculator", calculator_node)
    g.add_node("generate_response", generate_response_node)

    g.add_edge(START, "intent_router")
    g.add_conditional_edges(
        "intent_router",
        route_after_intent,
        {
            "vision_analysis": "vision_analysis",
            "parameter_update": "parameter_update",
            "explain_quote": "explain_quote",
            "generate_response": "generate_response",
        },
    )
    g.add_conditional_edges(
        "vision_analysis",
        route_after_vision,
        {
            "calculator": "calculator",
            "generate_response": "generate_response",
        },
    )
    # 硬性约束：改参数必须先更新参数再核算
    g.add_edge("parameter_update", "calculator")
    g.add_edge("calculator", "generate_response")
    g.add_edge("explain_quote", "generate_response")
    g.add_edge("generate_response", END)

    return g.compile()


def invoke_turn(
    state: QuotationState,
    *,
    user_message: str,
    images_base64: list[str] | None = None,
) -> QuotationState:
    """单轮增量：写入 user_message / current_images，跑一遍图，返回合并后状态。"""
    graph = build_quotation_graph()
    hist = list(state.get("chat_history") or [])
    hist.append({"role": "user", "content": user_message})

    patch: QuotationState = {
        **state,
        "user_message": user_message,
        "current_images": images_base64 or [],
        "chat_history": hist,
        "ran_calculator_this_turn": False,
        "quote_explanation_text": "",
    }
    out = graph.invoke(patch)
    return out  # type: ignore[return-value]
