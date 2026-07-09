"""Apify REST API client."""

from __future__ import annotations

import logging
import time
from typing import Any

import anyio
import httpx

from app.core.config import settings
from app.services.http_retry import execute_with_retry

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
APIFY_NETWORK_UNREACHABLE_REASON = "network_unreachable"


class ApifyError(Exception):
    pass


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


def format_apify_timeout_error(
    *,
    timeout: float,
    exc: Exception | None = None,
    remote_stop_attempted: bool = False,
    remote_stop_failed: bool = False,
    run_id_available: bool = True,
) -> str:
    detail = str(exc).strip() if exc is not None else ""
    suffix = f": {detail}" if detail else ""
    message = f"Apify 请求超时（{timeout}s）{suffix}"
    if remote_stop_attempted:
        message = f"{message}，已尝试停止远端运行"
        if remote_stop_failed:
            message = f"{message}，但停止请求未确认成功"
    elif not run_id_available:
        message = f"{message}，未获取到远端 runId，无法自动停止"
    return message


def _response_data(response: Any) -> Any:
    data = response.json()
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def _is_run_finished(status: str | None) -> bool:
    return (status or "").upper() in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


async def _abort_actor_run(client: httpx.AsyncClient, run_id: str, token: str) -> bool:
    try:
        response = await client.post(f"{APIFY_BASE}/actor-runs/{run_id}/abort", params={"token": token})
        if response.status_code in (200, 201):
            logger.info("Apify actor run %s abort requested", run_id)
            return True
        logger.warning("Apify actor run %s abort failed: %s %s", run_id, response.status_code, response.text[:300])
    except Exception as exc:
        logger.warning("Apify actor run %s abort request failed: %s", run_id, exc)
    return False


async def run_actor_sync(
    actor_id: str,
    run_input: dict,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    memory_mbytes: int | None = None,
) -> list[dict]:
    """Run an Actor and return dataset items, aborting the remote run on local timeout."""
    if not settings.is_apify_configured:
        raise ApifyError("未配置 APIFY_TOKEN")

    timeout = timeout or settings.apify_timeout_seconds
    actor_slug = actor_id.replace("/", "~")
    start_url = f"{APIFY_BASE}/acts/{actor_slug}/runs"
    params: dict[str, str | int] = {"token": settings.apify_token}
    if memory_mbytes and memory_mbytes > 0:
        params["memory"] = memory_mbytes

    started = time.perf_counter()
    deadline = started + float(timeout)
    run_id: str | None = None
    dataset_id: str | None = None

    try:
        async with httpx.AsyncClient(timeout=max(1, min(float(timeout), 30.0))) as client:
            start_response = await execute_with_retry(
                lambda: client.post(start_url, params=params, json=run_input),
                label=f"Apify {actor_id}",
                max_retries=max_retries,
            )
            elapsed = time.perf_counter() - started
            if start_response.status_code in (400, 401, 403):
                detail = start_response.text[:500]
                logger.error("Apify actor %s rejected: %s %s (%.2fs)", actor_id, start_response.status_code, detail, elapsed)
                raise ApifyError(f"Apify 采集失败 ({start_response.status_code}): {detail}")
            if start_response.status_code not in (200, 201):
                detail = start_response.text[:500]
                logger.error("Apify actor %s failed to start: %s %s (%.2fs)", actor_id, start_response.status_code, detail, elapsed)
                raise ApifyError(f"Apify 采集失败 ({start_response.status_code}): {detail}")

            run_data = _response_data(start_response)
            if not isinstance(run_data, dict):
                raise ApifyError("Apify 返回格式异常，期望 run data")
            run_id = str(run_data.get("id") or "").strip() or None
            dataset_id = str(run_data.get("defaultDatasetId") or "").strip() or None
            if not run_id:
                raise ApifyError("Apify 返回格式异常，缺少 runId")

            status = str(run_data.get("status") or "").upper()
            while not _is_run_finished(status):
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise httpx.TimeoutException(f"local timeout after {timeout}s")
                await anyio.sleep(min(1.0, max(0.05, remaining)))
                run_response = await client.get(f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": settings.apify_token})
                if run_response.status_code not in (200, 201):
                    detail = run_response.text[:500]
                    logger.error("Apify actor %s poll failed: %s %s", actor_id, run_response.status_code, detail)
                    raise ApifyError(f"Apify 采集失败 ({run_response.status_code}): {detail}")
                run_data = _response_data(run_response)
                if not isinstance(run_data, dict):
                    raise ApifyError("Apify 返回格式异常，期望 run data")
                status = str(run_data.get("status") or "").upper()
                dataset_id = str(run_data.get("defaultDatasetId") or dataset_id or "").strip() or None

            if status != "SUCCEEDED":
                raise ApifyError(f"Apify 采集失败，run status={status}")
            if not dataset_id:
                raise ApifyError("Apify 返回格式异常，缺少 datasetId")

            items_response = await execute_with_retry(
                lambda: client.get(
                    f"{APIFY_BASE}/datasets/{dataset_id}/items",
                    params={"token": settings.apify_token, "clean": "true"},
                ),
                label=f"Apify dataset {dataset_id}",
                max_retries=max_retries,
            )
            if items_response.status_code not in (200, 201):
                detail = items_response.text[:500]
                logger.error("Apify actor %s dataset fetch failed: %s %s", actor_id, items_response.status_code, detail)
                raise ApifyError(f"Apify 采集失败 ({items_response.status_code}): {detail}")
            data = items_response.json()
    except httpx.TimeoutException as exc:
        elapsed = time.perf_counter() - started
        remote_stop_attempted = False
        remote_stop_failed = False
        logger.warning("Apify actor %s timed out after %.2fs run_id=%s", actor_id, elapsed, run_id)
        if run_id is not None:
            async with httpx.AsyncClient(timeout=10) as abort_client:
                remote_stop_attempted = True
                remote_stop_failed = not await _abort_actor_run(abort_client, run_id, settings.apify_token)
        raise ApifyError(
            format_apify_timeout_error(
                timeout=timeout,
                exc=exc,
                remote_stop_attempted=remote_stop_attempted,
                remote_stop_failed=remote_stop_failed,
                run_id_available=True,
            )
        ) from exc
    except httpx.NetworkError as exc:
        elapsed = time.perf_counter() - started
        detail = str(exc).strip() or type(exc).__name__
        logger.warning("Apify actor %s network error after %.2fs: %s", actor_id, elapsed, detail)
        if is_apify_network_unreachable(exc):
            raise ApifyError(f"Apify 网络不可达: {detail}") from exc
        raise ApifyError(f"Apify 网络错误: {detail}") from exc

    elapsed = time.perf_counter() - started
    if not isinstance(data, list):
        raise ApifyError("Apify 返回格式异常，期望 list")

    logger.info(
        "Apify actor %s finished in %.2fs items=%d input_keys=%s",
        actor_id,
        elapsed,
        len(data),
        sorted(run_input.keys()),
    )
    return [item for item in data if isinstance(item, dict)]
