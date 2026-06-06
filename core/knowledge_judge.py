"""语义 miss 后对「是否写入标价表」做 LLM 裁决（不参与 calculate_quote）。"""

from __future__ import annotations

import json
from typing import Any

from kimi_client import (
    _call_kimi_with_fallback,
    _maybe_thinking_field,
    _parse_response_content,
    get_kimi_config,
)


_DEFAULT_IGNORE: dict[str, Any] = {
    "action": "ignore",
    "confidence": 0.0,
    "material": {"name": "", "spec": "", "price": ""},
}


def judge_write_decision(
    query: str,
    spec: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """输入用户查询与 embedding Top-K；输出 action / confidence / material。"""
    config = get_kimi_config()
    if not config.api_key:
        return dict(_DEFAULT_IGNORE)

    trimmed_q = str(query or "").strip()[:500]
    trimmed_s = str(spec or "").strip()[:400]
    if not trimmed_q and not candidates:
        return dict(_DEFAULT_IGNORE)

    cand_json = candidates[:10]
    system = (
        "你是标价知识库策展人。给定用户物料描述 query 以及语义相似的现有标价行（仅供参考），"
        "判断是否应该**新增一行**到公司内部「材料询价」标价表中。\n\n"
        "规则：\n"
        "1) 若能从候选中明确认定与用户描述为**同一种可标价物料**，且可参考某候选单价给出稳妥的人民币单价文案，则 action=write_to_kb。\n"
        "2) 若信息不足、名称含糊、与候选差异大或无法给出合理单价，则 action=ignore。\n"
        "3) write_to_kb 时 material.name / material.spec 要与用户查询中的关键词**明显重叠**，便于后续规则检索命中；"
        "material.price 为原始单价字符串（需带单位或格式，与现有表风格一致，如 7元/码、1.2元/PCS）。\n"
        "4) confidence 为你对「应写入且单价合理」的把握，0~1；仅 JSON，无 Markdown。\n"
    )
    user_obj = {
        "query": trimmed_q,
        "spec": trimmed_s,
        "candidates": cand_json,
    }
    user_text = (
        "Input:\n"
        f"{json.dumps(user_obj, ensure_ascii=False)}\n\n"
        "Output JSON keys: action (string: write_to_kb | ignore), "
        "confidence (number 0~1), material (object: name, spec, price — strings). "
        "ignore 时 material 三字段可用空字符串。"
    )
    status: dict[str, Any] = {
        "provider": "knowledge_judge",
        "model": config.model,
        "base_url": config.base_url,
        "api_key_source": config.api_key_source,
        "enabled": True,
        "used": False,
        "error": "",
    }
    req_body: dict[str, Any] = {
        "model": config.model,
        "temperature": max(0.0, min(2.0, float(config.temperature))),
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 512,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    }
    req_body.update(_maybe_thinking_field(config.base_url))

    raw, st = _call_kimi_with_fallback(req_body, config, status)
    if raw is None:
        print(f"[knowledge-judge] LLM failed: {st.get('error')}", flush=True)
        return dict(_DEFAULT_IGNORE)

    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        parsed = _parse_response_content(str(content))
    except Exception as exc:  # noqa: BLE001
        print(f"[knowledge-judge] parse_error: {exc}", flush=True)
        return dict(_DEFAULT_IGNORE)

    return _normalize_decision(parsed)


def _normalize_decision(raw: dict[str, Any]) -> dict[str, Any]:
    act = str(raw.get("action") or "ignore").strip().lower().replace("-", "_")
    if act in {"write_to_kb", "writetokb", "write"}:
        act_norm = "write_to_kb"
    else:
        act_norm = "ignore"

    try:
        conf = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    mat_raw = raw.get("material") if isinstance(raw.get("material"), dict) else {}
    mat = {
        "name": str(mat_raw.get("name", "")).strip()[:512],
        "spec": str(mat_raw.get("spec", "")).strip()[:512],
        "price": str(mat_raw.get("price", "") or mat_raw.get("unit_price", "")).strip()[:128],
    }

    return {"action": act_norm, "confidence": conf, "material": mat}
