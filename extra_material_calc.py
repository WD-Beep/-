"""额外材料替换试算：在保留主报价会话的前提下替换单行物料并重算。"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

from core.smart_lookup import enqueue_knowledge_learn_after_rule_miss
from kimi_client import autofill_items_with_kimi
from price_kb import KBHit

_DIGIT = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_price_number(text: object) -> float:
    """从单价字符串中提取主数字（与 server.parse_unit_price_numeric 行为接近）。"""
    s = str(text or "").strip().lower()
    if not s:
        return 0.0
    m = _DIGIT.search(s.replace(",", ""))
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except ValueError:
        return 0.0


def _parse_amount_float(row: dict[str, Any]) -> float:
    try:
        return float(row.get("amount") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def extract_substitution_query(user_text: str) -> str:
    """用户想换成的材料/叫法（用于知识库检索）。"""
    t = (user_text or "").strip()
    t = re.sub(r"(的话|是多少|多少钱|什么价|呢|啊|吗|嘛)\s*$", "", t)
    for pat in (
        r"(?:用|换成|改用|替换为|改为|换)\s*([^，。！？!?；;\n]{2,36})",
        r"(?:如果|要是|假设)(?:改|换|用)\s*([^，。！？!?；;\n]{2,36})",
    ):
        m = re.search(pat, t)
        if m:
            q = m.group(1).strip()
            return re.sub(r"(价格|单价|多少|钱).*$", "", q).strip()[:40]
    if "尼龙" in t:
        return "尼龙"
    if re.search(r"x-?pac", t, re.I):
        return "X-PAC"
    return t[:24] if t else "材料"


def find_target_row_index(items: list[dict[str, Any]], user_text: str) -> int | None:
    """规则 + 关键词：匹配要替换的 BOM 行。"""
    if not items:
        return None
    names = [str(it.get("name") or "") for it in items]

    def first_match(pred: Callable[[str], bool]) -> int | None:
        for i, n in enumerate(names):
            if pred(n):
                return i
        return None

    ut = user_text
    if "拉链" in ut or "拉头" in ut or "拉链头" in ut:
        idx = first_match(lambda n: "拉链" in n or "拉头" in n)
        if idx is not None:
            return idx
    if "织带" in ut:
        idx = first_match(lambda n: "织带" in n)
        if idx is not None:
            return idx
    if "扣" in ut and ("扣具" in ut or "插扣" in ut or "日字" in ut):
        idx = first_match(lambda n: "扣" in n)
        if idx is not None:
            return idx
    if any(k in ut for k in ("里布", "里料", "内里")):
        idx = first_match(lambda n: "里" in n and "拉链" not in n)
        if idx is not None:
            return idx
    if any(
        k in ut
        for k in ("面料", "布料", "尼龙", "牛津", "帆布", "格子", "xpac", "X-PAC", "主料")
    ):
        idx = first_match(
            lambda n: bool(
                re.search(r"面料|布料|尼龙|牛津|帆布|格|xpac|胶布|pc", n, re.I)
                and "拉链" not in n
                and "织带" not in n
            )
        )
        if idx is not None:
            return idx

    # 用原文 token 与名称做简单交集
    stop = set("的了是在和与或如果要不吗呢啊几多少价钱单价用换成改用替换")
    utoks = set(re.findall(r"[\u4e00-\u9fff]{2,4}|[A-Za-z]{2,}", ut))
    utoks = {x for x in utoks if x not in stop and len(x) >= 2}
    best_i: int | None = None
    best_s = 0
    for i, n in enumerate(names):
        score = sum(1 for tok in utoks if tok and tok in n)
        if score > best_s:
            best_s = score
            best_i = i
    if best_i is not None and best_s >= 1:
        return best_i
    return 0 if items else None


def _format_kb_substitution_miss_message(query: str, entries: list[Any]) -> str:
    parts: list[str] = []
    for ent in entries[:6]:
        name = str(getattr(ent, "raw_name", "") or "").strip()
        price = str(getattr(ent, "raw_price", "") or "").strip()
        if name:
            parts.append(f"{name}（{price}）" if price else name)
    q = (query or "").strip() or "该材料"
    head = f"未能找到「{q}」的匹配项"
    if not parts:
        return (
            f"{head}，知识库中也无相近条目。"
            "请改用更具体的材料编号/名称，或上传表格以便精确报价。"
        )
    return (
        f"{head}，知识库中相关物料可参考："
        f"{ '、'.join(parts)}。"
        "请确认具体型号，或上传表格精确报价。"
    )


def apply_material_substitution(
    base_items: list[dict[str, Any]],
    user_text: str,
    *,
    kb,
    llm_status_holder: dict[str, Any],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """
    返回 (新 items 列表, 元信息)。失败时 items 为 None，meta 含 error。
    """
    meta: dict[str, Any] = {}
    items = copy.deepcopy(base_items)
    idx = find_target_row_index(items, user_text)
    if idx is None or idx >= len(items):
        return None, {"error": "未找到可对调的物料行。"}

    row = items[idx]
    old_name = str(row.get("name") or "").strip()
    old_spec = str(row.get("spec") or "-").strip()
    old_up = str(row.get("unit_price") or "-").strip()
    old_amt = _parse_amount_float(row)
    old_price_num = _parse_price_number(old_up)

    query = extract_substitution_query(user_text)
    meta["target_index"] = idx
    meta["old_material_label"] = old_name or "-"
    meta["old_unit_price"] = old_up
    meta["query_phrase"] = query

    new_up = ""
    new_name = old_name
    kb_hit = False
    hit: KBHit | None = None

    if kb is not None:
        hit = kb.lookup(f"{query} {old_name}".strip(), old_spec)
        if hit is not None:
            kb_hit = True
            ent = hit.entry
            new_up = ent.raw_price
            new_name = ent.raw_name
            meta["new_material_label"] = new_name
            meta["kb_score"] = round(hit.score, 2)
            meta["kb_auto_learned"] = bool(getattr(ent, "auto_learned", False))
        else:
            enqueue_knowledge_learn_after_rule_miss(
                f"{query} {old_name}".strip(),
                old_spec,
            )

    if not new_up:
        sugg: list[Any] = []
        if kb is not None:
            sugg = kb.suggest_entries_for_query(query, limit=6)
        if sugg:
            return None, {
                "error": _format_kb_substitution_miss_message(query, sugg),
                "substitution_kb_miss": True,
                "target_index": idx,
            }
        # 无相近库内条目时才走 Kimi 单行补价，避免与「仅换料」期望冲突
        trial_row = copy.deepcopy(row)
        trial_row["name"] = f"{old_name}（客户替料：{query}）" if old_name else str(query)
        single = [trial_row]
        merged, st = autofill_items_with_kimi(single, user_prompt=user_text)
        if isinstance(st, dict):
            llm_status_holder.clear()
            llm_status_holder.update(st)
        if merged and isinstance(merged[0], dict):
            new_up = str(merged[0].get("unit_price") or "").strip() or "面议"
            if str(merged[0].get("name") or "").strip():
                new_name = str(merged[0].get("name")).strip()
        else:
            new_up = "面议（待补价）"
        meta["new_material_label"] = new_name
        meta["ai_price"] = True
    else:
        meta["ai_price"] = False

    new_price_num = _parse_price_number(new_up)
    row["name"] = new_name
    row["unit_price"] = new_up
    row["unit_price_ai"] = not kb_hit
    row["kb_hit"] = kb_hit
    if kb_hit and meta.get("kb_score") is not None:
        row["kb_score"] = meta["kb_score"]
    if kb_hit:
        row["kb_auto_learned"] = bool(meta.get("kb_auto_learned"))

    if old_price_num > 0 and new_price_num > 0 and old_amt > 0:
        row["amount"] = round(old_amt * (new_price_num / old_price_num), 2)
        row["amount_ai"] = True
    elif isinstance(row.get("amount"), (int, float)):
        row["amount_ai"] = bool(row.get("amount_ai"))

    return items, meta
