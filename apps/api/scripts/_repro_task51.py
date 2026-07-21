# 文件说明：后端维护脚本，用于检查、迁移、验证或批处理任务；当前文件：repro task51
"""Resume task 51 to reproduce persist-phase error."""
from __future__ import annotations

import asyncio
import traceback

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.services.collection_runner import CollectionRunnerService


async def main() -> int:
    async with async_session_factory() as db:
        task = await db.get(CollectionTask, 51)
        if not task:
            print("task 51 not found")
            return 1
        print(f"before: status={task.status} last_error={task.last_error!r}")
        try:
            await CollectionRunnerService.run_task(db, task, allow_running=True, resume=True)
        except Exception as exc:
            print(f"error: {exc}")
            traceback.print_exc()
            return 0
        await db.refresh(task)
        print(f"after: status={task.status} inserted={task.inserted_count} last_error={task.last_error!r}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
