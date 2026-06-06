"""用户消息 intent：NEW_QUOTE / FOLLOW_UP / COMPARE / CHAT（扩展自 prompt_intent）。"""
from __future__ import annotations

import re

from intent_router import looks_like_material_substitution, is_new_quote_text_priority
from prompt_intent import _GREETING_OR_CHAT_ONLY, user_prompt_has_quote_intent

# 注意：不要加入单独字符「件」——容易把「帮我报价 500 件」误判为追问。
_FOLLOW_UP_KEYWORDS = (
    "改",
    "换",
    "变成",
    "如果",
    "假设",
    "用量",
    "数量",
    "多高",
    "多长",
    "多大",
    "多宽",
    "底面积",
    "尺寸",
    "规格",
    "计算过程",
    "过程拆解",
    "怎么算",
    "咋算",
    "如何算",
    "成本构成",
    "公式",
    "毛利",
    "毛利率",
    "利润率",
    "明细",
    "再算一遍",
    "重新算",
    "换个材料",
    "这款",
    "此包",
    "这包",
    "这个包",
    "本单",
)

_FOLLOW_UP_START = re.compile(r"^(这个|该款|此包|这包|本单|这张|这单)", re.I)
# 仅含询价用语、常与「上一条报价」连用（需与 has_session 配合；见 classify_intent 顺序）
_FOLLOW_UP_PRICE_PHRASE = re.compile(
    r"(多少钱|什么价|啥价|啥价钱|单价|报个价|怎么卖|咋算|怎么算|合\s*多\s*少)",
    re.I,
)
# 质疑系统与手算/他厂不一致、要求说明口径（非「300 件多少钱」类试算）
_QUOTE_DISPUTE_OR_LOGIC = re.compile(
    r"(为什么|为何|为啥|怎么会).{0,40}(不一样|不同|不一致|对不上|有差|差异|误差|相差|偏高|偏低|贵了|便宜了|差错|算错|大)",
    re.I,
)
_DIMENSION_QUERY = re.compile(
    r"(多高|多长|多宽|多大|多厚|底面积|尺寸|规格|体积|容量|升|寸)",
    re.I,
)
_COMPARE_PATTERNS = re.compile(
    r"(对比|比较|差别|区别|哪个更|哪档|和上次|跟上一次|历史)",
    re.I,
)

# 明显的新询价（优先于弱追问信号；勿加单独「价格」，以免与追问句冲突）
_FRESH_QUOTE_REQUEST = re.compile(
    r"(报价|询价|多少钱|成本多少|预算|给我报|帮我报|重新上传|新需求|帮我做报价|核算)" r"|(?:报|出)\s*个\s*价",
    re.I,
)


def looks_like_quote_explain_follow_up(user_text: str) -> bool:
    """质疑或要求说明「为什么跟你算的不一样」等（已带会话报价时使用）。"""
    s = (user_text or "").strip()
    if not s:
        return False
    if _QUOTE_DISPUTE_OR_LOGIC.search(s):
        return True
    if re.search(
        r"(跟你|跟我|和你们|跟您|和系统)(算|报|做|给).{0,20}(不一样|不同|不一致|对不上)",
        s,
    ):
        return True
    if re.search(r"(解释|说明).{0,10}(报价|核算|价格|这个数字|这笔)", s):
        return True
    if re.search(r"(差在哪|哪里不一样|哪儿不一样|口径|依据是什么|凭什么这么算)", s):
        return True
    if re.search(r"(误差|差异|相差).{0,20}(大|多|明显|原因|为啥|为什么|为何)", s):
        return True
    return False


def should_explain_quote_without_requote(user_text: str) -> bool:
    """本会话已有有效报价：仅口述解释/口径说明，不重跑 calculate_quote。"""
    s = (user_text or "").strip()
    if not s:
        return False
    if looks_like_material_substitution(s):
        return False
    # 「500 件多少钱」等仍走试算/重算链路
    if re.search(r"\d+\s*件", s) and re.search(r"(多少钱|啥价|什么价|单价|报个价|合\s*多\s*少)", s):
        return False
    if re.search(r"(怎么算|如何算|咋算|怎样算)", s):
        return True
    if looks_like_quote_explain_follow_up(s):
        return True
    if re.search(
        r"(计算过程|过程拆解|拆分|成本构成|公式是怎样的|逐行|明细怎么来)",
        s,
        re.I,
    ):
        return True
    if re.search(r"(业务员|业务算|销售算).{0,30}(\d+(?:\.\d+)?)", s):
        return True
    if re.search(r"(加工费|包装|面料|物料).{0,8}(怎么来的|从哪来|哪来的)", s):
        return True
    if re.search(r"(哪个|哪项).{0,12}(材料|物料).{0,8}(差距|差|大|贵)", s):
        return True
    return False


def looks_like_follow_up(user_text: str) -> bool:
    s = (user_text or "").strip()
    if not s:
        return False
    if looks_like_quote_explain_follow_up(s):
        return True
    if _FOLLOW_UP_START.search(s):
        return True
    for kw in _FOLLOW_UP_KEYWORDS:
        if kw in s:
            return True
    if re.search(r"\d+\s*件", s):
        return True
    if looks_like_material_substitution(s):
        return True
    if _FOLLOW_UP_PRICE_PHRASE.search(s):
        return True
    if _DIMENSION_QUERY.search(s):
        return True
    return False


def looks_like_compare(user_text: str) -> bool:
    return bool(_COMPARE_PATTERNS.search(user_text or ""))


def looks_like_chat_only(user_text: str) -> bool:
    s = (user_text or "").strip()
    if not s:
        return True
    if _GREETING_OR_CHAT_ONLY.match(s):
        return True
    if len(s) <= 6 and s in {"在吗", "在", "hi", "ok", "OK"}:
        return True
    return False


def classify_intent(
    user_text: str,
    *,
    has_new_upload: bool,
    has_session_quote: bool,
) -> str:
    """返回 NEW_QUOTE | FOLLOW_UP | COMPARE | CHAT。"""
    if has_new_upload:
        return "NEW_QUOTE"
    if looks_like_compare(user_text):
        return "COMPARE"
    if looks_like_chat_only(user_text) and not user_prompt_has_quote_intent(user_text):
        return "CHAT"
    # 有具体尺寸的新产品文字描述：优先于「会话内追问」，避免误判为换料试算
    if is_new_quote_text_priority(user_text):
        return "NEW_QUOTE"
    # 已有报价会话时：先认追问（含「300 件多少钱」），避免「多少钱」命中新询价规则
    if has_session_quote and looks_like_follow_up(user_text):
        return "FOLLOW_UP"
    # 全新询价优先，避免「报价 500 件」因含「件」被判为追问
    if _FRESH_QUOTE_REQUEST.search(user_text or ""):
        return "NEW_QUOTE"
    if looks_like_follow_up(user_text):
        return "FOLLOW_UP"
    if user_prompt_has_quote_intent(user_text):
        return "NEW_QUOTE"
    return "CHAT"


FOLLOW_UP_NO_SESSION_HINT = (
    "当前没有进行中的报价会话，无法替您换料试算。\n"
    "您可以：1）上传 BOM；2）或直接描述需求，例如「28L 尼龙双肩包 500 件多少钱」。\n"
    "若刚刷新过页面，请重新上传表格或完成一次报价后再追问。"
)

COMPARE_STUB_REPLY = (
    "「与历史报价对比」正在接入：当前可先分别查看两次报价卡，或在问题里 @ 历史文件名后用「计算过程拆解」核对。"
)

CHAT_STUB_REPLY = "您好，我是报价助手。上传 BOM 或描述产品与数量后即可生成明细与三档报价；对上一条报价有疑问可直接说「用量改 500」等追问。"
