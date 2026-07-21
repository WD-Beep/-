# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：concurrency
"""受控并发工具。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def map_bounded(
    items: Iterable[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    concurrency: int,
) -> list[R | BaseException]:
    """对 items 受控并发执行 worker；单项异常作为结果返回，不中断其他任务。"""
    batch = list(items)
    if not batch:
        return []

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run(item: T) -> R:
        async with sem:
            return await worker(item)

    return list(await asyncio.gather(*(_run(item) for item in batch), return_exceptions=True))


async def map_bounded_incremental(
    items: Iterable[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    concurrency: int,
    on_complete: Callable[[T, R | BaseException], Awaitable[None]] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[R | BaseException]:
    """受控并发执行 worker，每项完成后可选回调；should_stop 为真时不再启动新任务。"""
    batch = list(items)
    if not batch:
        return []

    sem = asyncio.Semaphore(max(1, concurrency))
    outcomes: list[R | BaseException | None] = [None] * len(batch)
    stop_event = asyncio.Event()

    async def _run(index: int, item: T) -> None:
        if should_stop and should_stop():
            stop_event.set()
            return
        if stop_event.is_set():
            return
        async with sem:
            if should_stop and should_stop():
                stop_event.set()
                return
            if stop_event.is_set():
                return
            try:
                result = await worker(item)
                outcomes[index] = result
                if on_complete is not None:
                    await on_complete(item, result)
            except BaseException as exc:
                outcomes[index] = exc
                if on_complete is not None:
                    await on_complete(item, exc)

    await asyncio.gather(*(_run(index, item) for index, item in enumerate(batch)))
    return [outcome for outcome in outcomes if outcome is not None]
