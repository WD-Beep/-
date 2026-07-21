# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：http retry
"""HTTP 请求统一超时与有限重试。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def should_retry(status_code: int | None, exc: Exception | None) -> bool:
    if exc is not None:
        return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError))
    return status_code in RETRYABLE_STATUS


async def execute_with_retry(
    request_factory: Callable[[], Awaitable[httpx.Response]],
    *,
    max_retries: int | None = None,
    backoff_seconds: float | None = None,
    label: str = "HTTP",
) -> httpx.Response:
    retries = settings.api_direct_max_retries if max_retries is None else max_retries
    backoff = (
        settings.api_direct_retry_backoff_seconds
        if backoff_seconds is None
        else backoff_seconds
    )
    last_exc: Exception | None = None
    last_response: httpx.Response | None = None

    for attempt in range(max(0, retries) + 1):
        try:
            response = await request_factory()
            last_response = response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < retries and should_retry(None, exc):
                wait = max(0.5, backoff) * (2**attempt)
                logger.warning("%s 网络错误，%ss 后重试 (%d/%d): %s", label, wait, attempt + 1, retries, exc)
                await asyncio.sleep(wait)
                continue
            raise

        if response.status_code in RETRYABLE_STATUS and attempt < retries:
            wait = max(0.5, backoff) * (2**attempt)
            logger.warning(
                "%s HTTP %s，%ss 后重试 (%d/%d)",
                label,
                response.status_code,
                wait,
                attempt + 1,
                retries,
            )
            await asyncio.sleep(wait)
            continue
        return response

    if last_exc is not None:
        raise last_exc
    assert last_response is not None
    return last_response
