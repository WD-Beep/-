"""判断纯文字输入是否具备可执行报价的最小信息，过滤寒暄与空内容。"""
from __future__ import annotations

import re

# 业务/产品相关弱信号：命中则倾向认为用户在询价
_INTENT_KEYWORDS = (
    "报价",
    "价格",
    "单价",
    "成本",
    "询盘",
    "预算",
    "多少钱",
    "多少",
    "数量",
    "起订量",
    "打样",
    "样品",
    "纸箱",
    "拉链",
    "尼龙",
    "牛津",
    "涤纶",
    "帆布",
    "里布",
    "底料",
    "开模",
    "fob",
    "exw",
    "定制",
    "面料",
    "材质",
    "规格",
    "尺寸",
    "厘米",
    "毫米",
    "采购",
    "订单",
    "工厂",
    "货期",
    "起订",
    "背包",
    "旅行包",
    "公文包",
    "化妆包",
    "旅行",
    "双肩",
    "手提",
    "腰包",
    "箱包",
    "码",
    "码²",
    "升",
    "物料",
    "物料表",
    "bom",
    "明细表",
    "订货",
    "索样",
    "大货",
)

# 整段仅为寒暄/致谢等短句时不报价
_GREETING_OR_CHAT_ONLY = re.compile(
    r"^[\s　！!？?。.,，、…~～]*("
    r"你好|您好|您好呀|你好呀|哈喽|嗨|Hi|Hello|在吗|在么|有人吗|"
    r"早上好|中午好|下午好|晚上好|早安|午安|晚安|"
    r"谢谢|多谢|感谢|谢啦|辛苦了|劳驾|"
    r"好的|好哒|好滴|嗯|嗯嗯|OK|ok|行|可以|没问题|"
    r"知道了|明白|了解|收到|好的好的|"
    r"再见|拜拜|回见|Bye"
    r")([\s　！!？?。.,，、…~～]*(你好|您好|谢谢|好的|拜拜|再见))*[\s　！!？?。.,，、…~～]*$",
    re.IGNORECASE,
)


def user_prompt_has_quote_intent(text: str) -> bool:
    """无表格、无结构化需求模板时：文字是否足以触发正式报价（非空寒暄）。"""
    s = (text or "").strip()
    if not s:
        return False
    if re.search(r"\d", s):
        return True
    low = s.lower()
    for kw in _INTENT_KEYWORDS:
        if kw.isascii():
            if kw in low:
                return True
        else:
            if kw in s:
                return True
    if len(s) >= 18:
        return True
    if _GREETING_OR_CHAT_ONLY.match(s):
        return False
    # 较短且无数字与关键词，视为信息不足
    if len(s) < 12:
        return False
    return True


DEFERRED_QUOTE_HINT = (
    "您好，请先说明需要报价的产品类型、数量或主要材质等信息；"
    "也可以上传物料/BOM 表格，我会在识别后生成明细与三档价格。"
)

# 无上传表且无解析出的物料行时：禁止用内置示例 BOM 冒充真实报价（见服务端门禁）
QUOTE_NEEDS_UPLOAD_OR_ITEMS_HINT = (
    "当前没有进行中的报价，您可以：1）上传 BOM / 物料表；2）或直接描述需求，例如「28L 尼龙双肩包 500 件多少钱」。"
    "（若曾刷新页面，请先重新上传表格或完成一次报价后再追问。）"
)
