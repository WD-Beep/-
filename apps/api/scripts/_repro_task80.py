# 文件说明：后端维护脚本，用于检查、迁移、验证或批处理任务；当前文件：repro task80
"""Re-run TikTok task 80 to reproduce DiscoveryProgressReporter platform error."""
from __future__ import annotations

import asyncio
import traceback

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.services.collection_runner import CollectionRunnerService


async def main() -> int:
    async with async_session_factory() as db:
        task = await db.get(CollectionTask, 80)
        if not task:
            print("task 80 not found")
            return 1
        print(f"before: status={task.status} error={task.error_message!r}")
        try:
            await CollectionRunnerService.run_task(db, task, allow_running=True)
        except Exception as exc:
            print(f"error: {exc}")
            traceback.print_exc()
            return 0
        await db.refresh(task)
        print(f"after: status={task.status} error={task.error_message!r}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
