# 文件说明：后端维护脚本，用于检查、迁移、验证或批处理任务；当前文件：repro list set
"""Reproduce list & set error from failed collection task."""
from __future__ import annotations

import asyncio
import traceback

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.services.collection_runner import CollectionRunnerService


async def main() -> int:
    async with async_session_factory() as db:
        result = await db.execute(
            select(CollectionTask).where(CollectionTask.status == "failed").order_by(CollectionTask.id.desc()).limit(1)
        )
        task = result.scalar_one_or_none()
        if not task:
            print("no failed task found")
            return 1
        print(f"task_id={task.id} name={task.name!r} last_error={task.last_error!r}")
        try:
            await CollectionRunnerService.run_task(db, task, allow_running=True)
        except Exception as exc:
            print(f"reproduced: {exc}")
            traceback.print_exc()
            return 0
        print("run completed without error")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
