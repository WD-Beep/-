"""Apify REST API 客户端。"""



from __future__ import annotations



import logging

import time



import httpx



from app.core.config import settings

from app.services.http_retry import execute_with_retry



logger = logging.getLogger(__name__)



APIFY_BASE = "https://api.apify.com/v2"





class ApifyError(Exception):

    pass


APIFY_NETWORK_UNREACHABLE_REASON = "network_unreachable"


def is_apify_network_unreachable(exc: Exception) -> bool:
    """Return True when this machine cannot open a connection to Apify."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        detail = f"{type(current).__name__}: {current}".lower()
        if "all connection attempts failed" in detail:
            return True
        if "api.apify.com" in detail and any(
            marker in detail
            for marker in (
                "connection refused",
                "connection timed out",
                "network is unreachable",
                "connecterror",
                "networkerror",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def format_apify_timeout_error(*, timeout: float, exc: Exception | None = None) -> str:
    detail = str(exc).strip() if exc is not None else ""
    suffix = f": {detail}" if detail else ""
    return f"Apify 请求超时（>{timeout}s）{suffix}"





async def run_actor_sync(

    actor_id: str,

    run_input: dict,

    *,

    timeout: float | None = None,

    max_retries: int | None = None,

    memory_mbytes: int | None = None,

) -> list[dict]:

    """同步运行 Actor 并返回 dataset items。"""

    if not settings.is_apify_configured:

        raise ApifyError("未配置 APIFY_TOKEN")



    timeout = timeout or settings.apify_timeout_seconds

    actor_slug = actor_id.replace("/", "~")

    url = f"{APIFY_BASE}/acts/{actor_slug}/run-sync-get-dataset-items"

    params: dict[str, str | int] = {"token": settings.apify_token}
    if memory_mbytes and memory_mbytes > 0:
        params["memory"] = memory_mbytes

    started = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await execute_with_retry(
                lambda: client.post(url, params=params, json=run_input),
                label=f"Apify {actor_id}",
                max_retries=max_retries,
            )
    except httpx.TimeoutException as exc:
        elapsed = time.perf_counter() - started
        logger.warning("Apify actor %s timed out after %.2fs", actor_id, elapsed)
        raise ApifyError(format_apify_timeout_error(timeout=timeout, exc=exc)) from exc
    except httpx.NetworkError as exc:
        elapsed = time.perf_counter() - started
        detail = str(exc).strip() or type(exc).__name__
        logger.warning("Apify actor %s network error after %.2fs: %s", actor_id, elapsed, detail)
        if is_apify_network_unreachable(exc):
            raise ApifyError(f"Apify 网络不可达: {detail}") from exc
        raise ApifyError(f"Apify 网络错误: {detail}") from exc

    elapsed = time.perf_counter() - started

    if response.status_code in (400, 401, 403):

        detail = response.text[:500]

        logger.error("Apify actor %s rejected: %s %s (%.2fs)", actor_id, response.status_code, detail, elapsed)

        raise ApifyError(f"Apify 采集失败 ({response.status_code}): {detail}")



    if response.status_code not in (200, 201):

        detail = response.text[:500]

        logger.error("Apify actor %s failed: %s %s (%.2fs)", actor_id, response.status_code, detail, elapsed)

        raise ApifyError(f"Apify 采集失败 ({response.status_code}): {detail}")



    data = response.json()

    if not isinstance(data, list):

        raise ApifyError("Apify 返回格式异常，期望 list")



    logger.info(

        "Apify actor %s finished in %.2fs items=%d input_keys=%s",

        actor_id,

        elapsed,

        len(data),

        sorted(run_input.keys()),

    )

    return data

