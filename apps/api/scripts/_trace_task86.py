# 文件说明：后端维护脚本，用于检查、迁移、验证或批处理任务；当前文件：trace task86
from __future__ import annotations

import asyncio
import traceback

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.services.collection_runner import CollectionRunnerService


async def main() -> None:
    async with async_session_factory() as db:
        task = await db.get(CollectionTask, 86)
        assert task
        print("run task", task.id, task.status, task.last_error)
        try:
            await CollectionRunnerService.run_task(db, task, allow_running=True)
        except Exception as exc:
            print("ERROR:", exc)
            traceback.print_exc()
        await db.refresh(task)
        print("done", task.status, task.inserted_count, task.last_error)


if __name__ == "__main__":
    asyncio.run(main())
