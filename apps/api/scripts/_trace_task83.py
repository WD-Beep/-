"""Trace task 83 failure."""
from __future__ import annotations

import asyncio
import traceback

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.services.collection_runner import CollectionRunnerService


async def main() -> int:
    async with async_session_factory() as db:
        task = await db.get(CollectionTask, 83)
        if not task:
            print("task 83 missing")
            return 1
        print(f"rerun task_id={task.id} status={task.status} err={task.last_error!r}")
        try:
            await CollectionRunnerService.run_task(db, task, allow_running=True)
        except Exception:
            traceback.print_exc()
            return 2
        await db.refresh(task)
        print(
            f"done status={task.status} inserted={task.inserted_count}/{task.discovery_limit} "
            f"filtered={task.filtered_out_count}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
