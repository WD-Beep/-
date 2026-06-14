"""报价 + 答疑双模式：统一响应信封与轻量意图路由（quote / qa / hybrid / clarify）。"""
from __future__ import annotations

import time
from typing import Any, Mapping

# 对外统一 intent（与历史 JSON 中的 quote 引擎 flow 分离，见 flow_intent）
DUAL_INTENT_QUOTE = "quote"
DUAL_INTENT_QA = "qa"
DUAL_INTENT_HYBRID = "hybrid"
DUAL_INTENT_CLARIFY = "clarify"

DUAL_INTENTS = frozenset({DUAL_INTENT_QUOTE, DUAL_INTENT_QA, DUAL_INTENT_HYBRID, DUAL_INTENT_CLARIFY})


def _boolish(v: object) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return s in {"1", "true", "yes", "on", "y"}


def infer_dual_route(resp: Mapping[str, Any], *, http_status: int) -> tuple[str, float, str]:
    """返回 (intent, confidence 0..1, route_target)。"""
    if not isinstance(resp, Mapping):
        return DUAL_INTENT_CLARIFY, 0.4, "empty"

    if http_status >= 500:
        return DUAL_INTENT_CLARIFY, 0.5, "server_error"
    if http_status >= 400:
        er = str(resp.get("error") or resp.get("error_code") or "").strip().lower()
        if er == "invalid_material_pricing":
            return DUAL_INTENT_CLARIFY, 0.82, "invalid_material_pricing"
        if er in {"invalid_attachments", "sheet_parse_failed"}:
            return DUAL_INTENT_CLARIFY, 0.8, er
        return DUAL_INTENT_CLARIFY, 0.75, "http_client_error"

    reply_type = str(resp.get("reply_type") or "").strip().lower()
    if reply_type == "structure_confirmation":
        return DUAL_INTENT_CLARIFY, 0.85, "structure_confirmation_gate"

    quote_ready = _boolish(resp.get("quote_ready"))
    legacy_int = str(resp.get("intent") or "").strip()

    md = resp.get("metadata") if isinstance(resp.get("metadata"), dict) else {}
    extra_calc = md.get("is_extra_calc") is True
    extra_mat = md.get("is_extra_material_calc") is True

    if quote_ready and (
        legacy_int in {"agent_trial", "extra_material_calc", "extra_quantity_calc"}
        or extra_calc
        or extra_mat
    ):
        return DUAL_INTENT_HYBRID, 0.88, "follow_up_trial"

    if quote_ready and legacy_int in {"promote_to_primary", "promote_material_to_primary"}:
        return DUAL_INTENT_QUOTE, 0.95, legacy_int

    if quote_ready:
        return DUAL_INTENT_QUOTE, 0.9, "calculate_quote"

    if reply_type == "process_card":
        return DUAL_INTENT_QA, 0.83, "process_card"

    if legacy_int == "COMPARE":
        return DUAL_INTENT_QA, 0.84, "session_compare"
    if legacy_int in {"CHAT", "QA", "ADMIN_ACTION"}:
        return DUAL_INTENT_QA, 0.9, "session_chat"
    if legacy_int == "CLARIFY":
        return DUAL_INTENT_CLARIFY, 0.82, "request_clarify"
    if legacy_int in {"FOLLOW_UP", "AGENT_UNAVAILABLE"}:
        return DUAL_INTENT_QA, 0.8, legacy_int.lower()

    am = str(resp.get("assistant_message") or "").strip()
    low = legacy_int.lower()
    if legacy_int == "new_quote_text" or low == "new_quote_text":
        return DUAL_INTENT_CLARIFY, 0.78, "new_quote_text_unsatisfied"

    return DUAL_INTENT_CLARIFY, 0.72, "default_deferred"


def _compose_answer(resp: Mapping[str, Any]) -> str:
    for key in ("assistant_message", "message", "final_reply"):
        v = resp.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def apply_dual_mode_envelope(resp: dict[str, Any], *, trace: Mapping[str, Any], http_status: int) -> None:
    """原地补充统一信封字段并打日志。"""
    if not isinstance(resp, dict):
        return

    t0 = trace.get("t0")
    if isinstance(t0, (int, float)):
        latency_ms = round(max(0.0, (time.perf_counter() - float(t0))) * 1000, 2)
    else:
        latency_ms = 0.0

    dual_intent, confidence, route_target = infer_dual_route(resp, http_status=http_status)
    legacy_flow = resp.pop("intent", None)

    reply_type = str(resp.get("reply_type") or "").strip().lower()
    if reply_type == "structure_confirmation":
        preserved = str(legacy_flow or "STRUCTURE_CONFIRMATION_REQUIRED").strip()
        resp["intent"] = preserved or "STRUCTURE_CONFIRMATION_REQUIRED"
        resp["dual_intent"] = dual_intent
    else:
        if legacy_flow is not None and legacy_flow != "":
            lf = legacy_flow if isinstance(legacy_flow, str) else str(legacy_flow)
            if lf not in DUAL_INTENTS:
                resp["flow_intent"] = lf
        resp["intent"] = dual_intent
    resp["confidence"] = round(float(confidence), 4)
    resp["route_target"] = route_target
    resp["latency_ms"] = latency_ms

    resp.setdefault("answer", _compose_answer(resp))
    resp.setdefault("actions", resp.get("actions") if isinstance(resp.get("actions"), list) else [])
    qp = resp.get("quote_patch")
    resp.setdefault("quote_patch", qp if isinstance(qp, dict) else {})

    if "quote_ready" not in resp:
        resp["quote_ready"] = False

    rid = str(resp.get("request_id") or "").strip()
    print(
        f"[quote-dual] intent={dual_intent} confidence={confidence:.3f} route_target={route_target} "
        f"latency_ms={latency_ms} request_id={rid or '-'}"
    )
