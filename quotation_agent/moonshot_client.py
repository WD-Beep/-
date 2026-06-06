"""Moonshot (Kimi) OpenAI 兼容 Chat Completions（urllib，无额外 SDK 强制依赖）。

默认：
- ``MOONSHOT_BASE_URL`` / ``OPENAI_BASE_URL`` 未设置时使用 ``https://api.moonshot.ai/v1``
- 文本 / 视觉默认模型 ``kimi-k2.6``（可通过环境变量覆盖）

详见：https://platform.moonshot.cn/docs （域名以官方文档为准）
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def moonshot_base_url() -> str:
    raw = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("KIMI_BASE_URL")
        or os.environ.get("MOONSHOT_BASE_URL")
        or os.environ.get("OPENCLAW_BASE_URL")
        or os.environ.get("DEEPSEEK_BASE_URL")
        or "https://api.moonshot.ai/v1"
    ).rstrip("/")
    return raw


def moonshot_api_key() -> str:
    return (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("KIMI_API_KEY")
        or os.environ.get("MOONSHOT_API_KEY")
        or os.environ.get("OPENCLAW_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or ""
    ).strip()


def default_text_model() -> str:
    return (
        os.environ.get("QUOTATION_AGENT_TEXT_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or os.environ.get("KIMI_MODEL")
        or os.environ.get("OPENCLAW_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or "gpt-5.3-codex"
    )


def default_vision_model() -> str:
    return os.environ.get("QUOTATION_AGENT_VISION_MODEL") or default_text_model()


def chat_completions(
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.6,
    max_tokens: int = 4096,
    timeout_sec: int = 180,
) -> str:
    """调用 ``/chat/completions``，返回 assistant 文本 content。"""
    api_key = moonshot_api_key()
    if not api_key:
        raise RuntimeError("未配置 MOONSHOT_API_KEY（或 OPENAI_API_KEY）")

    base = moonshot_base_url()
    use_model = model or default_text_model()

    body = json.dumps(
        {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        import urllib.request

        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw_json = json.loads(resp.read().decode("utf-8"))
        return str(raw_json["choices"][0]["message"]["content"] or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("moonshot chat_completions failed: %s", exc)
        raise


def chat_completions_multimodal_user(
    *,
    text: str,
    images_b64: list[tuple[str, str]],
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    timeout_sec: int = 180,
) -> str:
    """单条 user 消息：text + image_url(data:image/...;base64,...)。

    ``images_b64`` 元素为 ``(mime, base64_without_prefix)``。
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for mime, b64 in images_b64[:8]:
        b64 = (b64 or "").strip()
        if not b64:
            continue
        mime = (mime or "image/jpeg").strip()
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )

    messages = [{"role": "user", "content": content}]
    return chat_completions(
        messages=messages,
        model=model or default_vision_model(),
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_sec=timeout_sec,
    )
