"""受控并发工具测试。"""

import anyio

from app.services.concurrency import map_bounded


def test_map_bounded_continues_after_single_failure():
    async def _worker(value: int) -> int:
        if value == 2:
            raise ValueError("boom")
        return value * 10

    async def _run():
        return await map_bounded([1, 2, 3], _worker, concurrency=2)

    results = anyio.run(_run)
    assert results[0] == 10
    assert isinstance(results[1], ValueError)
    assert results[2] == 30
