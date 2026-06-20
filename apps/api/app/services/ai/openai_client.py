"""统一 OpenAI 客户端封装，所有 AI 请求必须走后端。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, AuthenticationError, NotFoundError

from app.core.config import settings

logger = logging.getLogger(__name__)

OPENAI_NOT_CONFIGURED_MSG = (
    "未配置 OPENAI_API_KEY。请在环境变量中设置 OPENAI_API_KEY 与 OPENAI_MODEL 后重启 API 服务。"
)


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI 返回的 JSON 不是对象")
    return parsed


def _build_client() -> AsyncOpenAI:
    if not settings.is_openai_configured:
        raise ValueError(OPENAI_NOT_CONFIGURED_MSG)
    return AsyncOpenAI(
        api_key=settings.openai_api_key.strip(),
        base_url=settings.openai_api_base.rstrip("/"),
    )


def _format_openai_error(exc: Exception) -> str:
    if isinstance(exc, NotFoundError):
        model = settings.openai_model.strip() or "(empty)"
        return (
            f"OpenAI 模型不可用：{model}。"
            f"请检查 OPENAI_MODEL 环境变量是否与当前 API 账户支持的模型一致。"
        )
    if isinstance(exc, AuthenticationError):
        return "OpenAI API Key 无效或已过期，请检查 OPENAI_API_KEY。"
    if isinstance(exc, APIStatusError):
        body = ""
        try:
            body = exc.response.text[:300]
        except Exception:
            body = str(exc)
        return f"OpenAI API 错误 HTTP {exc.status_code}: {body or exc.message}"
    if isinstance(exc, APIConnectionError):
        return f"无法连接 OpenAI API（{settings.openai_api_base}），请检查网络与 OPENAI_API_BASE。"
    return str(exc).strip() or exc.__class__.__name__


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

    client = _build_client()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        message = _format_openai_error(exc)
        logger.warning("OpenAI chat completion failed (model=%s): %s", model, message)
        raise RuntimeError(message) from exc

    choice = response.choices[0] if response.choices else None
    content = (choice.message.content if choice and choice.message else "") or ""
    if not content.strip():
        raise ValueError("OpenAI 返回空内容")
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

    client = _build_client()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        message = _format_openai_error(exc)
        logger.warning("OpenAI chat completion failed (model=%s): %s", model, message)
        raise RuntimeError(message) from exc

    choice = response.choices[0] if response.choices else None
    content = (choice.message.content if choice and choice.message else "") or ""
    if not content.strip():
        raise ValueError("OpenAI 返回空内容")
    return content.strip()
