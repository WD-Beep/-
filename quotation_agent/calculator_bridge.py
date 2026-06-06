"""核算桥接：只做「payload 组装 + 调用现有 quote_engine.calculate_quote」。

禁止在此处用大模型做算术；缺失必填字段时返回带 error 的字典。"""
from __future__ import annotations

from typing import Any


def build_quote_payload(parameters: dict[str, Any]) -> dict[str, Any]:
    """把高层 parameters 映射为 calculate_quote 可接受的 payload。"""
    payload: dict[str, Any] = {}

    # 数量档
    if "quantities" in parameters and parameters["quantities"]:
        payload["quantities"] = parameters["quantities"]
    elif "quantity" in parameters and parameters["quantity"] is not None:
        try:
            q = int(parameters["quantity"])
            payload["quantities"] = [q]
        except (TypeError, ValueError):
            pass

    if "items" in parameters and isinstance(parameters["items"], list):
        payload["items"] = parameters["items"]

    if "product_name" in parameters:
        payload["product_name"] = str(parameters["product_name"] or "").strip()

    for k in (
        "include_fob",
        "gross_margin_rate",
        "mold_fee",
        "processing_fee",
        "system_overhead",
        "fob_addition",
        "usd_cny_rate",
        "management_loss_rate",
    ):
        if k in parameters and parameters[k] is not None:
            payload[k] = parameters[k]

    return payload


def run_calculate_quote(parameters: dict[str, Any]) -> dict[str, Any]:
    from quote_engine import calculate_quote

    payload = build_quote_payload(parameters)
    if not payload.get("items"):
        return {
            "error": "缺少明细 items，无法核算。请先上传表格、由视觉节点提取 BOM，或手动提供 items。",
            "payload_attempted": payload,
        }
    try:
        return calculate_quote(payload)
    except Exception as e:  # noqa: BLE001
        return {"error": f"calculate_quote 异常: {e!s}", "payload_attempted": payload}
