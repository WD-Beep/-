"""LangGraph 全局状态（TypedDict）。

说明：
- LangGraph 默认「同名字段后者覆盖」；列表类字段由各节点返回完整替换列表即可。
- `parameters` 与现有 ``calculator_bridge.build_quote_payload`` 对齐（items / quantities / product_name 等）。
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


IntentLiteral = Literal[
    "vision_compare",
    "vision_single",
    "parameter_change",
    "quote_explain",
    "chitchat",
]


class QuotationState(TypedDict, total=False):
    """报价智能体一轮或多轮会话状态。"""

    # --- 本轮输入 ---
    user_message: str
    """当前用户自然语言输入。"""
    current_images: list[str]
    """当前轮次传入的图片 base64（不含 data: 前缀）；视觉节点可自行配对 mime。"""

    # --- 会话上下文 ---
    chat_history: list[dict[str, Any]]
    """消息列表，元素形如 {\"role\": \"user\"|\"assistant\", \"content\": str}。"""
    parameters: dict[str, Any]
    """生效中的报价参数（会与 calculator_bridge / calculate_quote payload 对齐）。"""
    extracted_data: dict[str, Any]
    """Kimi 从图片解析出的结构化价差 / BOM 摘要等（可与 vision 解析合并）。"""
    calculation_result: dict[str, Any] | None
    """最近一次 ``calculate_quote`` 完整结果；失败时可为带 error 键的字典。"""

    # --- 路由与中间产物 ---
    last_intent: IntentLiteral | str
    """意图路由结果（条件边分支依据）。"""
    vision_analysis_text: str
    """视觉模型输出的对比说明 / BOM 摘录（给用户看的中间摘要）。"""
    vision_extracted_patch: dict[str, Any]
    """视觉节点解析出的可合并字段（如 items 片段），由上游决定是否写入 parameters。"""
    parameter_delta_note: str
    """参数节点对本轮提取结果的简述。"""
    assistant_reply: str
    """最终回复正文（写入 chat_history 前置于该字段）。"""
    final_reply: str
    """与 ``assistant_reply`` 对齐：对外单一出口，便于接入方只读 ``final_reply``。"""
    quote_explanation_text: str
    """仅 ``quote_explain`` 分支：大模型生成的白话拆解（再由 reply 节点写入会话）。"""
    ran_calculator_this_turn: bool
    """本轮是否在图中执行过 calculator_node（用于区分视觉分支后的新核算与历史缓存结果）。"""
    last_local_quote_intent: str
    """正式 /api/quote 链路同步过来的最近一次业务 intent。"""


def empty_quotation_state() -> QuotationState:
    """空状态工厂，便于外部接入。"""
    return {
        "chat_history": [],
        "current_images": [],
        "parameters": {},
        "extracted_data": {},
        "calculation_result": None,
        "user_message": "",
        "assistant_reply": "",
        "final_reply": "",
        "quote_explanation_text": "",
        "vision_analysis_text": "",
        "vision_extracted_patch": {},
        "parameter_delta_note": "",
        "ran_calculator_this_turn": False,
        "last_local_quote_intent": "",
    }
