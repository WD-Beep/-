"""统一 OpenAI 客户端封装，所有 AI 请求必须走后端。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

def _ai_provider_label() -> str:
    return settings.ai_provider_display_name


OPENAI_NOT_CONFIGURED_MSG = (
    "未配置 AI API Key。请在环境变量中设置 OPENAI_API_KEY 与 OPENAI_MODEL "
    "（当前可对接 DeepSeek / OpenAI 兼容接口）后重启 API 服务。"
)


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"{_ai_provider_label()} 返回的 JSON 不是对象")
    return parsed


def _openai_base_url() -> str:
    if not settings.is_openai_configured:
        raise ValueError(OPENAI_NOT_CONFIGURED_MSG)
    return settings.openai_api_base.rstrip("/")


def _chat_temperature(model: str, requested: float) -> float:
    model_name = model.strip().lower()
    base_url = settings.openai_api_base.strip().lower()
    if model_name.startswith("kimi-k2.6") or "moonshot.cn" in base_url:
        return 1.0
    return requested


def _format_openai_error(exc: Exception, *, status_code: int | None = None, body: str = "") -> str:
    provider = _ai_provider_label()
    text = body or str(exc)
    if status_code == 404:
        model = settings.openai_model.strip() or "(empty)"
        return (
            f"{provider} 模型不可用：{model}。"
            f"请检查 OPENAI_MODEL 环境变量是否与当前 API 账户支持的模型一致。"
        )
    if status_code in {401, 403}:
        if "blocked" in text.lower():
            return f"{provider} API 错误 HTTP {status_code}: {text[:300]}"
        return f"{provider} API Key 无效或已过期，请检查 OPENAI_API_KEY。"
    if status_code is not None:
        return f"{provider} API 错误 HTTP {status_code}: {text[:300]}"
    if isinstance(exc, httpx.HTTPError):
        return (
            f"无法连接 {provider} API（{settings.openai_api_base}），"
            f"请检查网络与 OPENAI_API_BASE。"
        )
    return str(exc).strip() or exc.__class__.__name__


async def _post_chat_completion(payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_openai_base_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key.strip()}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(_format_openai_error(exc)) from exc

    if response.status_code >= 400:
        raise RuntimeError(
            _format_openai_error(
                RuntimeError(response.text),
                status_code=response.status_code,
                body=response.text,
            )
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"{_ai_provider_label()} 返回的响应不是 JSON 对象")
    return data


async def chat_completion_json(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """调用 Chat Completions 并解析为 JSON 对象。"""
    model = settings.openai_model.strip()
    if not model:
        raise ValueError("未配置 OPENAI_MODEL 环境变量")

    json_system_prompt = f"{system_prompt}\n\nReturn valid json only."
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": json_system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": _chat_temperature(model, temperature),
        "max_tokens": max_tokens,
    }
    try:
        response = await _post_chat_completion(payload)
    except Exception as exc:
        message = str(exc)
        if "response_format" not in message and "json_object" not in message and "text.format" not in message:
            logger.warning("AI chat completion failed (model=%s): %s", model, message)
            raise RuntimeError(message) from exc
        logger.warning(
            "AI json_object mode failed (model=%s), retrying plain JSON prompt: %s",
            model,
            message,
        )
        try:
            payload.pop("response_format", None)
            response = await _post_chat_completion(payload)
        except Exception as retry_exc:
            retry_message = str(retry_exc)
            logger.warning("AI chat completion failed (model=%s): %s", model, retry_message)
            raise RuntimeError(retry_message) from retry_exc

    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    content = (message.get("content") if isinstance(message, dict) else "") or ""
    if not content.strip():
        raise ValueError(f"{_ai_provider_label()} 返回空内容")
    return _parse_json_content(content)


async def chat_completion_text(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 4096,
) -> str:
    """调用 Chat Completions 并返回纯文本。"""
    model = settings.openai_model.strip()
    if not model:
        raise ValueError("未配置 OPENAI_MODEL 环境变量")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": _chat_temperature(model, temperature),
        "max_tokens": max_tokens,
    }
    try:
        response = await _post_chat_completion(payload)
    except Exception as exc:
        message = str(exc)
        logger.warning("AI chat completion failed (model=%s): %s", model, message)
        raise RuntimeError(message) from exc

    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    content = (message.get("content") if isinstance(message, dict) else "") or ""
    if not content.strip():
        raise ValueError(f"{_ai_provider_label()} 返回空内容")
    return content.strip()
