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
