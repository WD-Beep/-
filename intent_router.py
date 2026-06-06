"""会话内追问意图补强：材料替换试算等（与 extra_quantity_calc 同级语义）。"""
from __future__ import annotations

import re

# 明确产品外形尺寸（含数值），命中则优先走「全新文字询价」而非会话内换料试算
_DIM_EXPLICIT = re.compile(
    r"(?:"
    r"(?:长|宽|高|厚|深|直径|口径|边长|底|底部|周长)[^\d\n]{0,10}?\d+(?:\.\d+)?\s*(?:厘米|公分|cm|毫米|mm|m|米)?"
    r"|"
    r"\d+(?:\.\d+)?\s*(?:厘米|公分|cm|毫米|mm)\s*(?:×|[xX\*])\s*\d+(?:\.\d+)?"
    r"|"
    r"\d+(?:\.\d+)?\s*(?:×|[xX\*])\s*\d+(?:\.\d+)?(?:\s*(?:×|[xX\*])\s*\d+(?:\.\d+)?)?"
    r")",
    re.I,
)
# 询价/算价意图（与尺寸组合时视为新产品描述）
_NEW_QUOTE_ACTION = re.compile(
    r"(算|核算|报价|多少钱|成本|单价|什么价|啥价|估价|估价单|给\s*个\s*价)",
    re.I,
)

# 触发「换材料 / 试材料」类追问，避免被误判为新询价（如句末「多少」）
_SWAP_VERB = re.compile(
    r"(用|换|改|改用|换成|替换|改为|升级成|降级成|改下|换下)",
    re.I,
)
_MATERIAL_HINT = re.compile(
    r"(面料|布料|里布|里料|主料|辅料|拉链|拉头|拉片|织带|扣具|尼龙|牛津|"
    r"涤纶|帆布|格子|xpac|x-?pac|防水布|胶布|革|胶料|绳子|绳带|插扣|魔术贴|"
    r"鸡眼|气眼|d环|日字扣|背带)",
    re.I,
)
_TAIL_MATERIAL_ACTION = re.compile(
    r"(?:拉链|拉头|织带|面料|里料|里布|扣具|尼龙).{0,8}(?:换|改|用|成)",
    re.I,
)


def has_explicit_product_dimensions(user_text: str) -> bool:
    """是否包含可推算产品的具体尺寸数值（与「多高」类模糊问法区分）。"""
    return bool(_DIM_EXPLICIT.search(user_text or ""))


def is_new_quote_text_priority(user_text: str) -> bool:
    """尺寸 + 材料/面料信息 + 算价意图 → 全新文字报价（高于会话追问）。"""
    s = (user_text or "").strip()
    if not s:
        return False
    if not has_explicit_product_dimensions(s):
        return False
    if not (_MATERIAL_HINT.search(s) or re.search(r"尼龙|牛津|帆布|皮革|布料|面料|dcf|xpac", s, re.I)):
        return False
    if not _NEW_QUOTE_ACTION.search(s):
        return False
    return True


def looks_like_material_substitution(user_text: str) -> bool:
    """是否像「基于当前单换某类材料」而非全新询价。"""
    s = (user_text or "").strip()
    if not s:
        return False
    if _TAIL_MATERIAL_ACTION.search(s):
        return True
    if _SWAP_VERB.search(s) and _MATERIAL_HINT.search(s):
        return True
    if re.search(r"(如果|要是|假设)(?:改|换|用)", s):
        return True
    return bool(re.search(r"(?:换个|换一种|换种)(?:材料|料|面料)", s))


def is_extra_material_calc_intent(user_text: str) -> bool:
    """材料替换额外试算（不覆盖主报价）。"""
    from follow_up_merge import is_adjust_quantity_intent

    if is_adjust_quantity_intent(user_text):
        return False
    if has_explicit_product_dimensions(user_text):
        return False
    if is_new_quote_text_priority(user_text):
        return False
    return looks_like_material_substitution(user_text)
