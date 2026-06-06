"""基于上一次的报价 payload 合并用户追问（改数量阶梯、改整单件数等）。"""
from __future__ import annotations

import copy
import re
from typing import Any

_DIM = re.compile(r"(多高|多长|多宽|多大|多厚|底面积|尺寸|规格|体积|容量|升|寸)", re.I)

# ---------- 调节主报价 vs 额外数量试算 ----------
_ADJUST_QTY = re.compile(
    r"(?:用量|数量|件数|档位|阶梯|起订)\s*改|"
    r"(?:改成|改为|变更为|换为|调到|调至)\s*\d|"
    r"^\s*改\s*\d|"
    r"(?:^|[，,。！!\s])改\s*\d{1,7}\s*(?:件)?$",
    re.I,
)


def is_adjust_quantity_intent(user_text: str) -> bool:
    """用户明确要求把主报价改成某数量/阶梯（覆盖会话主报价）。"""
    t = (user_text or "").strip()
    if not t:
        return False
    return bool(_ADJUST_QTY.search(t))


def is_extra_quantity_calc_intent(user_text: str) -> bool:
    """额外试算：同物料下试另一个件数，不覆盖原主报价。"""
    if is_adjust_quantity_intent(user_text):
        return False
    t = (user_text or "").strip()
    if not t:
        return False
    if re.search(r"(?:如果|要是|假设)(?:做|订)?\s*\d{1,7}\s*件", t):
        return True
    if re.search(
        r"\d+\s*件\s*(?:多少钱|多少|啥价|如何|咋样|怎么样|多少啊|是多少)",
        t,
    ):
        return True
    if re.search(r"\d+\s*件\s*呢", t):
        return True
    if re.match(r"^\s*(?:那|那如果)?\s*\d{1,7}\s*件\s*呢\s*$", t):
        return True
    if re.search(r"\d+\s*件\s*是多少", t):
        return True
    if re.search(r"(?:再算|帮我算|试算|算算|额外试|加试)\s*\d", t):
        return True
    if re.search(
        r"\d{1,7}\s*件\s*(?:\?|？|吗|嘛|么|呐|吧|呀|啊)\s*$",
        t,
    ):
        return True
    return False


def parse_extra_calc_quantity(user_text: str) -> int | None:
    """从试算类话术中提取单一试算件数（与调节类话术互斥）。"""
    if is_adjust_quantity_intent(user_text):
        return None
    t = (user_text or "").strip()
    if not t:
        return None
    m0 = re.search(r"(\d{1,7})\s*件", t)
    if m0:
        n = int(m0.group(1))
        return n if n > 0 else None
    m1 = re.search(r"(?:如果|要是|假设)(?:做|订)?\s*(\d{1,7})\s*件?", t)
    if m1:
        n = int(m1.group(1))
        return n if n > 0 else None
    m2 = re.search(r"(?:再算|帮我算|试算|算算|额外试|加试)\s*(\d{1,7})\s*件?", t)
    if m2:
        n = int(m2.group(1))
        return n if n > 0 else None
    m3 = re.search(r"(?:再算|帮我算|试算|算算)\s*(\d{1,7})(?!\d)", t)
    if m3:
        n = int(m3.group(1))
        return n if n > 0 else None
    return None


def _parse_int_list_from_text(text: str) -> list[int] | None:
    """识别「300,500,1000」「300和500」「只算 500 件」等；数量不固定死档位。"""
    t = (text or "").strip()
    if not t:
        return None

    m_change = re.search(r"改\s*(\d{1,7})(?:\s*件)?", t)
    if m_change:
        n = int(m_change.group(1))
        return [n, n, n]

    # 三档：逗号/顿号分隔
    m = re.search(
        r"(\d{1,7})\s*[,，、/]\s*(\d{1,7})\s*[,，、/]\s*(\d{1,7})",
        t,
    )
    if m:
        return [int(m.group(1)), int(m.group(2)), int(m.group(3))]

    # 双档：300 和 500、算 300 与 400
    m_pair = re.search(
        r"(?:算|要|就|加|各|或|再看|顺便)?\s*(\d{1,7})\s*(?:和|与|跟|到|至|～|~|、|，|,)\s*(\d{1,7})"
        r"(?:\s*件)?",
        t,
    )
    if m_pair:
        a, b = int(m_pair.group(1)), int(m_pair.group(2))
        if 0 < a < 10**7 and 0 < b < 10**7:
            return sorted({a, b})

    nums = re.findall(r"(?<![0-9])(\d{1,7})(?![0-9])", t)
    if not nums:
        return None
    ints = [int(x) for x in nums]
    if not ints:
        return None

    m_single_tier = re.search(
        r"(?:只算|就算|改成|改为|只要|单档|一档|就要|单算|另算|加算|顺算|额外)"
        r".*?(\d{1,7})\s*件",
        t,
    )
    if m_single_tier:
        n = int(m_single_tier.group(1))
        return [n]

    if re.search(
        r"(?:用量|数量|件数|起订)?\s*改\s*(\d{1,7})",
        t,
    ):
        n = int(re.search(r"(?:用量|数量|件数|起订)?\s*改\s*(\d{1,7})", t).group(1))
        return [n, n, n]

    if len(ints) == 1 and ("件" in t or "量" in t or "档" in t):
        return [ints[0]]
    # 「都算算」「三档都要」且列出了多个数
    if len(ints) >= 2 and re.search(r"(?:各档|两三档|几档|档.*都要|分别)", t):
        return sorted(set(ints))

    if len(ints) == 1 and re.search(
        r"(?:多少钱|什么价|啥价|单价|价格|成本|报价|合|卖|核算|算算|报个)",
        t,
    ):
        return [ints[0]]

    return None


def merge_follow_up_text(user_text: str, base_payload: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base_payload)
    if not isinstance(out, dict):
        out = {}
    qty_list = _parse_int_list_from_text(user_text)
    if qty_list:
        out["quantities"] = qty_list
    # 毛利率：包含「毛利率」「毛利」百分比
    mg = re.search(
        r"(?:毛利率|毛利|利润率)\s*[:：]?\s*(\d{1,2})\s*%",
        user_text or "",
    )
    if mg:
        out["gross_margin_rate"] = float(mg.group(1)) / 100.0
    return out


def is_dimension_follow_up_only(user_text: str) -> bool:
    """仅问规格/尺寸、不含改件数等数字意图时，走明细说明而非重算。"""
    if _parse_int_list_from_text(user_text or ""):
        return False
    if re.search(r"改\s*\d", user_text or ""):
        return False
    return bool(_DIM.search(user_text or ""))


def build_dimension_hint_from_result(last_result: dict[str, Any]) -> str:
    """用上一单的 detail_rows 回答「多高/多长」等（基于明细行，不调用 LLM）。"""
    rows = last_result.get("detail_rows") if isinstance(last_result, dict) else None
    if not isinstance(rows, list) or not rows:
        return "当前会话里没有可引用的明细行；请先完成一次有效报价。"
    lines = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip() or "-"
        spec = str(row.get("spec", "")).strip() or "-"
        usage = str(row.get("usage", "")).strip() or "-"
        lines.append(f"· {name}：规格 {spec}；用量 {usage}")
    head = "根据**当前这张报价单**自动解析出的物料与用量（尺寸类多在「规格/用量」栏，单为近似展示）：\n"
    return head + "\n".join(lines)
