"""Request-time route selection for /api/quote.

This module decides which workflow should receive the request before the
expensive quote pipeline starts. It only routes; quote math stays in
quote_engine unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from intent_router import looks_like_material_substitution
from message_intent import should_explain_quote_without_requote
from prompt_intent import user_prompt_has_quote_intent
from qa_rag import is_qa_price_lookup


ROUTE_QUOTE = "quote"
ROUTE_QUOTE_PATCH = "quote_patch"
ROUTE_EXPLAIN = "explain"
ROUTE_COMPARE_EXPLAIN = "compare_explain"
ROUTE_QA = "qa"
ROUTE_CLARIFY = "clarify"
ROUTE_CAPABILITY_HELP = "capability_help"
ROUTE_ADMIN_ACTION = "admin_action"

INTENT_GENERATE_QUOTE = "generate_quote"
INTENT_EXPLAIN_PRICE = "explain_price"
INTENT_COMPARE_QUOTE = "compare_quote"
INTENT_CONSULT_MATERIAL = "consult_material"
INTENT_NEGOTIATE_PRICE = "negotiate_price"
INTENT_MODIFY_PARAMS = "modify_params"
INTENT_FALLBACK_GENERAL = "fallback_general"

ROUTE_INTENTS = frozenset(
    {
        ROUTE_QUOTE,
        ROUTE_QUOTE_PATCH,
        ROUTE_EXPLAIN,
        ROUTE_COMPARE_EXPLAIN,
        ROUTE_QA,
        ROUTE_CLARIFY,
        ROUTE_CAPABILITY_HELP,
        ROUTE_ADMIN_ACTION,
    }
)
BUSINESS_INTENTS = frozenset(
    {
        INTENT_GENERATE_QUOTE,
        INTENT_EXPLAIN_PRICE,
        INTENT_COMPARE_QUOTE,
        INTENT_CONSULT_MATERIAL,
        INTENT_NEGOTIATE_PRICE,
        INTENT_MODIFY_PARAMS,
        INTENT_FALLBACK_GENERAL,
    }
)

DIRECT_CONFIDENCE = 0.75
CLARIFY_MIN_CONFIDENCE = 0.45

_BACKPACK_CONSULT_RE = re.compile(
    r"(背包|旅行包|登山包|双肩包|软包|包袋|定制|户外|出差|通勤|旅行|收纳|结构|版型|肩带|背负|"
    r"面料|里料|辅料|拉链|扣具|织带|防水|耐磨|轻量|减重|降本|替代|优化|建议|怎么做|怎么选|"
    r"适合|优缺点|区别|工艺|做法|材料)",
    re.I,
)

_QUOTE_EXPLAIN_TRIGGER_RE = re.compile(
    r"(你怎么算的|怎么算的|为什么这个价|为何这个价|为什么这么高|为何这么贵|报价.*高|太贵了?|"
    r"贵在哪|成本怎么来的|成本从哪来|和业务员差在哪|"
    r"跟业务员不一样|跟销售不一样|价格怎么来的|怎么得出这个价|计算过程|明细|拆解|构成|"
    r"怎么跟客户|客户问.*贵|怎么解释)",
    re.I,
)
_BUSINESS_ASSISTANT_RE = re.compile(
    r"(能不能发|发给客户|对外发|有什么风险|风险点|字段.*意思|是什么意思|什么意思|"
    r"能不能做|是否可行|配置.*能不能|替代方案|有没有替代|换便宜|便宜一点|"
    r"工艺.*影响|材料.*影响|这张表|报价表)",
    re.I,
)

_PROFESSIONAL_QA_TRIGGER_RE = re.compile(
    r"(面料怎么选|面料选择|工艺怎么做|工艺做法|背包结构|耐磨性|防水性|降本方案|替代材料|"
    r"肩带设计|拉链选择|扣具选型|材料推荐|面料对比|工艺风险|适用场景|成本取舍|"
    r"尼龙.*牛津|涤纶.*帆布|420D|1680D|Cordura|XPAC|DCF)",
    re.I,
)

_EXPLICIT_QUOTE_REQUEST_RE = re.compile(
    r"(报价|算多少钱|多少钱|多少件|帮我报|核算|询价|出个价|给个价|生成报价)",
    re.I,
)
_NEGOTIATE_RE = re.compile(
    r"(便宜|降价|压价|降本|降成本|省钱|预算不够|太贵|贵了|能不能低|能不能便宜|"
    r"替代方案|替换方案|降档|低配|国产替代|换便宜|成本优化)",
    re.I,
)


def is_quote_explain_trigger(text: str, has_active_quote: bool) -> bool:
    """判断是否为报价解释链路触发（必须有 active quote）"""
    if not has_active_quote:
        return False
    if not text or not text.strip():
        return False
    s = text.strip()
    if _QUOTE_EXPLAIN_TRIGGER_RE.search(s):
        return True
    if should_explain_quote_without_requote(s):
        return True
    if _EXPLAIN_RE.search(s) and not _PROFESSIONAL_QA_TRIGGER_RE.search(s):
        return True
    return False


def looks_like_business_assistant(text: str, *, has_active_quote: bool = False) -> bool:
    """业务助手类问题：答疑/解释/替料咨询，不要求上传 BOM。"""
    s = str(text or "").strip()
    if not s:
        return False
    if _EXPLICIT_QUOTE_REQUEST_RE.search(s) and not has_active_quote:
        if not (
            _QUOTE_EXPLAIN_TRIGGER_RE.search(s)
            or _has_explain_signal(s)
            or _BUSINESS_ASSISTANT_RE.search(s)
        ):
            return False
    if _QUOTE_EXPLAIN_TRIGGER_RE.search(s):
        return True
    if is_quote_explain_trigger(s, has_active_quote):
        return True
    if _has_negotiate_signal(s) or _looks_like_qa(s):
        return True
    if has_active_quote and (
        _has_explain_signal(s)
        or looks_like_material_substitution(s)
        or _has_patch_signal(s)
    ):
        return True
    if _BUSINESS_ASSISTANT_RE.search(s):
        return True
    if _BACKPACK_CONSULT_RE.search(s) and not _EXPLICIT_QUOTE_REQUEST_RE.search(s):
        return True
    return False


def is_professional_qa_trigger(text: str, has_active_quote: bool) -> bool:
    """判断是否为专业答疑链路触发（无报价上下文或明确问材料/工艺）"""
    if not text or not text.strip():
        return False
    s = text.strip()
    if _EXPLICIT_QUOTE_REQUEST_RE.search(s):
        return False
    if _PROFESSIONAL_QA_TRIGGER_RE.search(s):
        if not has_active_quote:
            return True
        if not _QUOTE_EXPLAIN_TRIGGER_RE.search(s):
            return True
    if _BACKPACK_CONSULT_RE.search(s) and not has_active_quote:
        if not _EXPLICIT_QUOTE_REQUEST_RE.search(s):
            return True
    return False


@dataclass(frozen=True)
class RequestRoute:
    route_intent: str
    route_confidence: float
    route_reason: str
    dialog_intent: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "route_intent": self.route_intent,
            "route_confidence": round(float(self.route_confidence), 4),
            "route_reason": self.route_reason,
            "dialog_intent": self.dialog_intent or _dialog_intent_for_route(self.route_intent, self.route_reason),
        }


_PRICE_PATCH_RE = re.compile(
    r"(箱子|纸箱|外箱|包装|单价|加工费|管理费|杂费|模具|开模|毛利|利润|数量|用量|改成|改为|换成|调到|按)"
    r".{0,24}?\d+(?:\.\d+)?",
    re.I,
)
_QTY_RE = re.compile(r"\d{1,7}\s*(?:件|pcs|PCS|个|只|套)")
_EXPLAIN_RE = re.compile(
    r"(为什么|为啥|为何|怎么来的|怎么算|怎么算的|差距|差异|哪里低|哪里高|比业务员|业务员算|你算|原因|依据|口径)",
    re.I,
)
_COMPARE_RE = re.compile(
    "("
    "\u4e0d\u4e00\u6837|\u4e0d\u540c|\u5dee\u5f02|\u5dee\u8ddd|\u5dee\u5728\u54ea|\u5dee\u591a\u5c11|"
    "\u5bf9\u6bd4|\u6bd4\u8f83|\u5bf9\u8d26|\u6838\u5bf9|"
    "\u4e1a\u52a1\u5458|\u522b\u4eba|\u5bf9\u65b9|\u540c\u884c|\u5916\u90e8\u62a5\u4ef7|"
    "\u56fe\u4e00|\u56fe\u4e8c|\u56fe\u4e09|\u7b2c\u4e00\u4e2a|\u7b2c\u4e8c\u4e2a|\u7b2c\u4e09\u4e2a"
    ")",
    re.I,
)
_COMPARE_AMOUNT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:\u5143|\u5757|rmb|RMB)?"
    r".{0,24}?"
    r"(?:\u4f60\u7b97|\u7cfb\u7edf\u7b97|\u4e1a\u52a1\u5458|\u522b\u4eba|\u5bf9\u65b9|\u540c\u884c|\u62a5)",
    re.I,
)
_CAPABILITY_RE = re.compile(
    "("
    "\u4f60\u80fd\u505a\u4ec0\u4e48|\u4f60\u4f1a\u4ec0\u4e48|\u6709\u54ea\u4e9b\u529f\u80fd|"
    "\u54ea\u4e9b\u529f\u80fd|\u529f\u80fd\u4ecb\u7ecd|\u80fd\u5e72\u561b|\u80fd\u5e72\u4ec0\u4e48|"
    "\u600e\u4e48\u7528|\u5982\u4f55\u4f7f\u7528|\u4f7f\u7528\u5e2e\u52a9|\u5e2e\u52a9\u6587\u6863"
    ")",
    re.I,
)
_ADMIN_RE = re.compile(
    r"(后台|价格库|知识库|待补充|待补价|补价|更新价格|修改价格|导入|管理后台|部署|同步)",
    re.I,
)
_QA_RE = re.compile(
    r"(是什么|什么材料|什么面料|有什么好处|用途|工艺|做法|区别|防水|耐磨|材质|材料介绍|解释一下|怎么用|如何操作)",
    re.I,
)
_UNCLEAR_PRICE_RE = re.compile(r"^(这个|这款|这张|这个表|它|这个包)?\s*(多少钱|什么价|成本多少|报价|算一下)\s*[?？。!！]*$")


def route_quote_request(
    payload: dict[str, Any] | None,
    *,
    has_upload: bool,
    has_active_quote: bool,
) -> RequestRoute:
    text = _request_text(payload)
    has_text = bool(text)

    if _ADMIN_RE.search(text):
        return _direct_or_clarify(ROUTE_ADMIN_ACTION, 0.82, "admin_or_kb_operation")

    if _has_capability_signal(text):
        return _direct_or_clarify(ROUTE_CAPABILITY_HELP, 0.86, "capability_help_signal")

    # 新增：两条链路互斥机制（优先级最高）
    # 规则1：用户明确要求报价 → 强制走报价流程
    if _EXPLICIT_QUOTE_REQUEST_RE.search(text):
        pass  # 继续走原有报价逻辑

    if has_active_quote and _has_compare_signal(text):
        return _direct_or_clarify(ROUTE_COMPARE_EXPLAIN, 0.9, "active_quote_with_compare_signal")

    if _has_negotiate_signal(text):
        if has_active_quote:
            return _direct_or_clarify(ROUTE_QA, 0.84, "active_quote_with_negotiate_signal")
        return _direct_or_clarify(ROUTE_QA, 0.8, "negotiate_consult_without_active_quote")

    # 规则2：有 active quote + 问"怎么算/为什么这个价" → 走报价解释
    if is_quote_explain_trigger(text, has_active_quote):
        return _direct_or_clarify(ROUTE_EXPLAIN, 0.9, "quote_explain_trigger_with_active_quote")

    # 规则3：无报价上下文 + 问材料/工艺/结构建议 → 走专业答疑
    if is_professional_qa_trigger(text, has_active_quote):
        return _direct_or_clarify(ROUTE_QA, 0.88, "professional_qa_trigger_no_quote_context")

    # Upload should not force auto-quote. Text intent always wins.
    if has_upload:
        if _has_compare_signal(text):
            if has_active_quote:
                return _direct_or_clarify(ROUTE_COMPARE_EXPLAIN, 0.9, "upload_with_compare_signal")
            return RequestRoute(ROUTE_CLARIFY, 0.76, "upload_compare_needs_target")
        if _has_explain_signal(text):
            if has_active_quote:
                return _direct_or_clarify(ROUTE_EXPLAIN, 0.88, "upload_with_explain_signal")
            return RequestRoute(ROUTE_CLARIFY, 0.74, "upload_explain_needs_compare_target")
        if _looks_like_qa(text):
            return _direct_or_clarify(ROUTE_QA, 0.82, "upload_with_qa_signal")
        if _has_negotiate_signal(text):
            return _direct_or_clarify(ROUTE_QA, 0.8, "upload_with_negotiate_signal")
        if _has_patch_signal(text):
            if has_active_quote:
                return _direct_or_clarify(ROUTE_QUOTE_PATCH, 0.88, "upload_with_patch_signal")
            return RequestRoute(ROUTE_CLARIFY, 0.72, "upload_patch_needs_active_quote")
        if not text or user_prompt_has_quote_intent(text):
            return RequestRoute(ROUTE_QUOTE, 0.92, "upload_with_quote_intent")
        return RequestRoute(ROUTE_CLARIFY, 0.7, "upload_non_quote_text_requires_intent")

    if _has_patch_signal(text) and _is_vague_patch_without_target(text):
        return RequestRoute(ROUTE_CLARIFY, 0.88, "patch_missing_target")

    if has_active_quote and _has_patch_signal(text):
        if _is_vague_patch_without_target(text):
            return RequestRoute(ROUTE_CLARIFY, 0.88, "patch_missing_target")
        return _direct_or_clarify(ROUTE_QUOTE_PATCH, 0.9, "active_quote_with_patch_signal")

    if has_active_quote and _has_compare_signal(text):
        return _direct_or_clarify(ROUTE_COMPARE_EXPLAIN, 0.9, "active_quote_with_compare_signal")

    if not has_active_quote and _has_compare_signal(text):
        return RequestRoute(ROUTE_CLARIFY, 0.72, "compare_needs_active_quote_or_targets")

    if has_active_quote and _has_explain_signal(text):
        return _direct_or_clarify(ROUTE_EXPLAIN, 0.88, "active_quote_with_explain_signal")

    if not has_active_quote and _has_explain_signal(text):
        if looks_like_business_assistant(text, has_active_quote=False):
            return _direct_or_clarify(ROUTE_QA, 0.78, "explain_consult_without_active_quote")
        return RequestRoute(ROUTE_CLARIFY, 0.7, "explain_needs_active_quote")

    if _looks_like_qa(text):
        return _direct_or_clarify(ROUTE_QA, 0.82, "qa_signal")

    if _has_negotiate_signal(text):
        return _direct_or_clarify(ROUTE_QA, 0.78, "negotiate_signal")

    if has_active_quote and has_text:
        if _QTY_RE.search(text) or looks_like_material_substitution(text):
            return _direct_or_clarify(ROUTE_QUOTE_PATCH, 0.82, "active_quote_follow_up")

    if _UNCLEAR_PRICE_RE.match(text):
        return RequestRoute(ROUTE_CLARIFY, 0.68, "unclear_quote_request_without_context")

    if user_prompt_has_quote_intent(text):
        if looks_like_business_assistant(text, has_active_quote=has_active_quote):
            if has_active_quote and is_quote_explain_trigger(text, has_active_quote):
                return _direct_or_clarify(ROUTE_EXPLAIN, 0.86, "business_explain_over_quote_phrase")
            return _direct_or_clarify(ROUTE_QA, 0.8, "business_over_quote_intent_phrase")
        return _direct_or_clarify(ROUTE_QUOTE, 0.76, "quote_intent_text")

    if not has_text and not has_active_quote:
        return RequestRoute(ROUTE_CLARIFY, 0.4, "empty_request_without_context")

    if has_active_quote and has_text:
        if looks_like_business_assistant(text, has_active_quote=True):
            if is_quote_explain_trigger(text, has_active_quote):
                return _direct_or_clarify(ROUTE_EXPLAIN, 0.88, "active_quote_business_explain")
            if looks_like_material_substitution(text) or _has_negotiate_signal(text):
                return _direct_or_clarify(ROUTE_QUOTE_PATCH, 0.84, "active_quote_material_consult")
            return _direct_or_clarify(ROUTE_QA, 0.82, "active_quote_business_qa")

    if has_text and looks_like_business_assistant(text, has_active_quote=has_active_quote):
        return _direct_or_clarify(ROUTE_QA, 0.8, "business_assistant_without_force_quote")

    return RequestRoute(ROUTE_CLARIFY, 0.42, "low_confidence_no_context")


def _direct_or_clarify(intent: str, confidence: float, reason: str) -> RequestRoute:
    if confidence >= DIRECT_CONFIDENCE:
        return RequestRoute(intent, confidence, reason)
    if confidence >= CLARIFY_MIN_CONFIDENCE:
        return RequestRoute(ROUTE_CLARIFY, confidence, f"needs_clarification:{reason}")
    return RequestRoute(ROUTE_CLARIFY, confidence, f"low_confidence:{reason}")


def _request_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(
        payload.get("message_text")
        or payload.get("user_prompt")
        or payload.get("prompt")
        or ""
    ).strip()


def _has_patch_signal(text: str) -> bool:
    if not text:
        return False
    return bool(_PRICE_PATCH_RE.search(text) or _QTY_RE.search(text) or looks_like_material_substitution(text))


def _has_explain_signal(text: str) -> bool:
    if not text:
        return False
    return bool(_EXPLAIN_RE.search(text) or should_explain_quote_without_requote(text))


def _has_compare_signal(text: str) -> bool:
    if not text:
        return False
    if not (_COMPARE_RE.search(text) or _COMPARE_AMOUNT_RE.search(text)):
        return False
    has_relation = bool(
        re.search(
            "("
            "\u4e1a\u52a1\u5458|\u522b\u4eba|\u5bf9\u65b9|\u540c\u884c|\u56fe\u4e00|\u56fe\u4e8c|\u56fe\u4e09|"
            "\u4f60\u7b97|\u7cfb\u7edf\u7b97|\u7cfb\u7edf\u62a5|\u5916\u90e8\u62a5\u4ef7"
            ")",
            text,
            re.I,
        )
    )
    has_difference = bool(
        re.search(
            "("
            "\u4e0d\u4e00\u6837|\u4e0d\u540c|\u5dee|\u5bf9\u6bd4|\u6bd4\u8f83|\u5bf9\u8d26|\u6838\u5bf9|"
            "\u4e3a\u4ec0\u4e48|\u4e3a\u5565"
            ")",
            text,
            re.I,
        )
    )
    has_amount = bool(re.search(r"\d+(?:\.\d+)?", text))
    return (has_relation and has_difference) or (has_relation and has_amount)


def _has_capability_signal(text: str) -> bool:
    if not text:
        return False
    return bool(_CAPABILITY_RE.search(text))


def _has_negotiate_signal(text: str) -> bool:
    if not text:
        return False
    return bool(_NEGOTIATE_RE.search(text))


def _dialog_intent_for_route(route_intent: str, reason: str = "") -> str:
    r = str(reason or "")
    if "negotiate" in r:
        return INTENT_NEGOTIATE_PRICE
    if route_intent == ROUTE_QUOTE:
        return INTENT_GENERATE_QUOTE
    if route_intent == ROUTE_QUOTE_PATCH:
        return INTENT_MODIFY_PARAMS
    if route_intent == ROUTE_EXPLAIN:
        return INTENT_EXPLAIN_PRICE
    if route_intent == ROUTE_COMPARE_EXPLAIN:
        return INTENT_COMPARE_QUOTE
    if route_intent == ROUTE_QA:
        return INTENT_CONSULT_MATERIAL
    return INTENT_FALLBACK_GENERAL


def _is_vague_patch_without_target(text: str) -> bool:
    from clarify_once import is_vague_patch_without_target

    return is_vague_patch_without_target(text)


def _looks_like_qa(text: str) -> bool:
    if not text:
        return False
    if is_qa_price_lookup(text):
        return True
    if _QA_RE.search(text):
        return True
    if _BACKPACK_CONSULT_RE.search(text):
        return True
    return bool(re.search(r"[A-Za-z0-9#]{2,}.*(材料|面料|布|拉链|织带|扣具)", text))
