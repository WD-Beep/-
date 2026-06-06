"""意图路由单测用：模拟 /api/quote 业务层返回（信封应用前）。"""
from __future__ import annotations

import copy
import time
from typing import Any

# 用户话术（与 message_intent / 会话路由对齐，仅作文档与桥接断言）
USER_PROMPT_PURE_QUOTE = "商务出行袋 500件 请报价"
USER_PROMPT_WHY_EXPENSIVE = "为什么这么贵"
USER_PROMPT_PROCESSING_FEE_RECALC = "把加工费改成22再算"
USER_PROMPT_UNCLEAR = "嗯"

# 统一信封必备字段（apply_dual_mode_envelope 之后）
ENVELOPE_REQUIRED_KEYS = (
    "intent",
    "answer",
    "actions",
    "quote_patch",
    "quote_ready",
    "confidence",
    "route_target",
    "latency_ms",
)


def _trace() -> dict[str, float]:
    return {"t0": time.perf_counter()}


def raw_pure_quote_response() -> dict[str, Any]:
    """上传/结构化物料后 calculate_quote 成功的主报价卡。"""
    return {
        "quote_ready": True,
        "intent": "NEW_QUOTE",
        "quote_id": "fixture-quote-primary-001",
        "product_name": "商务出行袋",
        "assistant_message": "",
        "tiers": [
            {
                "quantity": 500,
                "processing_fee": 12.0,
                "cost_per_piece": 28.5,
                "exw_price": 32.0,
            }
        ],
        "items": [
            {
                "name": "600D塔丝隆格子布",
                "spec": "140*90CM",
                "usage": "0.63㎡",
                "unit_price": "14元/码²",
                "amount": 8.82,
            }
        ],
        "sheet_parse": {"file_name": "B260162--报价资料.xlsx", "item_count": 8},
    }


def raw_why_expensive_response() -> dict[str, Any]:
    """会话内「为什么这么贵」：无新报价卡，口语解释（legacy CHAT / FOLLOW_UP）。"""
    return {
        "quote_ready": False,
        "intent": "CHAT",
        "assistant_message": (
            "当前 EXW 偏高，主要来自主料用量与加工费档位；"
            "可先核对 BOM 用量是否与结构说明一致，或追问「成本构成拆解」查看分项。"
        ),
        "llm_status": {"enabled": True},
    }


def raw_why_expensive_follow_up_explain_response() -> dict[str, Any]:
    """Agent 本地解释分支（legacy QUOTE_EXPLAIN，应用信封后为 clarify）。"""
    return {
        "quote_ready": False,
        "intent": "QUOTE_EXPLAIN",
        "assistant_message": "从物料合计、加工费与毛利倒扣看，单价高于手算多为用量或加工费口径差异。",
    }


def raw_processing_fee_recalc_response() -> dict[str, Any]:
    """「加工费改成22再算」：追问试算，出卡但不覆盖主报价（agent_trial / extra_calc）。"""
    return {
        "quote_ready": True,
        "intent": "agent_trial",
        "assistant_message": "已按加工费 22 元/件重新试算，以下为试算结果（未覆盖主报价）。",
        "quote_id": "fixture-quote-trial-pf22",
        "metadata": {
            "is_extra_calc": True,
            "processing_fee_override": 22,
            "base_quote_id": "fixture-quote-primary-001",
            "calc_quantity": 500,
        },
        "tiers": [{"quantity": 500, "processing_fee": 22.0, "exw_price": 31.2}],
    }


def raw_unclear_response() -> dict[str, Any]:
    """信息不足 / 默认延后：无明确报价或答疑产物。"""
    return {
        "quote_ready": False,
        "assistant_message": "",
    }


def raw_structure_confirmation_response() -> dict[str, Any]:
    """表格已解析，待结构确认（clarify 闸门）。"""
    return {
        "quote_ready": False,
        "reply_type": "structure_confirmation",
        "title": "结构确认后再报价",
        "assistant_message": "已完成结构预核对，请先确认结构/用量/单价后再生成正式报价。",
        "item_count": 8,
    }
