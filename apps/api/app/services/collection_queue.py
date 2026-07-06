from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionTaskStatus
from app.services.collection_task import CollectionTaskService
from app.services.task_run_progress import STAGE_DISCOVERY, reset_run_progress

logger = logging.getLogger(__name__)
_queue_decision_lock = asyncio.Lock()

QUEUE_REASON_GLOBAL_FULL = "global_concurrency_full"
QUEUE_REASON_USER_RUNNING = "user_already_running"

QUEUE_REASON_MESSAGES = {
    QUEUE_REASON_GLOBAL_FULL: "全局并发已满",
    QUEUE_REASON_USER_RUNNING: "当前业务员已有任务运行中",
}

def _queue_message(reasons: list[str]) -> str:
    labels = [QUEUE_REASON_MESSAGES.get(reason, reason) for reason in reasons]
    detail = "；".join(labels) if labels else "等待空位"
    return f"任务已排队，等待空位（{detail}）"


def _start_message(task: CollectionTask, *, resume: bool = False) -> str:
    if resume:
        return "检测到上次运行中断，将从 checkpoint 继续采集（跳过已完成项）"
    platforms = [str(p).lower() for p in (getattr(task, "platforms", None) or []) if p]
    if not platforms and getattr(task, "platform", None):
        platforms = [str(task.platform).lower()]
    platform_names = ", ".join(dict.fromkeys(platforms)) or "配置的平台"
    return f"采集任务已开始，正在从 {platform_names} 发现候选作者并补采主页"


class CollectionQueueService:
    @staticmethod
    def mark_task_queued(
        task: CollectionTask,
        reasons: list[str],
        *,
        resume: bool = False,
    ) -> None:
        checkpoint = dict(task.run_checkpoint or {})
        checkpoint["queue_reasons"] = reasons
        checkpoint["queue_reason_labels"] = [
            QUEUE_REASON_MESSAGES.get(reason, reason) for reason in reasons
        ]
        checkpoint["queued_at"] = datetime.now(UTC).isoformat()
        checkpoint["queued_resume"] = bool(resume)
        task.run_checkpoint = checkpoint
        task.status = CollectionTaskStatus.QUEUED.value
        task.current_stage = None
        task.status_summary = _queue_message(reasons)
        task.error_message = None
        task.last_error = None

    @staticmethod
    async def restore_task_to_queue(
        db: AsyncSession,
        task: CollectionTask,
        *,
        reasons: list[str] | None = None,
        resume: bool = False,
    ) -> None:
        from app.services.collection_runner import CollectionRunCapacityError, CollectionRunnerService

        await CollectionRunnerService._release_collection_run(task.id)
        CollectionQueueService.mark_task_queued(
            task,
            reasons or [QUEUE_REASON_GLOBAL_FULL],
            resume=resume,
        )
        await db.commit()
        await db.refresh(task)

    @staticmethod
    async def running_tasks(db: AsyncSession, *, exclude_id: int | None = None) -> list[CollectionTask]:
        from app.services.collection_runner import CollectionRunCapacityError, CollectionRunnerService

        await CollectionRunnerService.reconcile_in_process_runs(db)
        result = await db.execute(
            select(CollectionTask).where(CollectionTask.status == CollectionTaskStatus.RUNNING.value)
        )
        scalars = result.scalars()
        if inspect.isawaitable(scalars):
            scalars = await scalars
        tasks: list[CollectionTask] = []
        try:
            iterable = list(scalars)
        except TypeError:
            iterable = []
        for task in iterable:
            if exclude_id is not None and task.id == exclude_id:
                continue
            if not CollectionTaskService.is_running_stale(task):
                tasks.append(task)
        return tasks

    @staticmethod
    async def queue_reasons(db: AsyncSession, task: CollectionTask) -> list[str]:
        from app.services.collection_runner import CollectionRunnerService

        running = await CollectionQueueService.running_tasks(db, exclude_id=task.id)
        in_process = CollectionRunnerService.active_collection_run_count()
        active_count = max(len(running), in_process)
        capacity = max(1, settings.collection_max_running_tasks)
        reasons: list[str] = []
        if active_count >= capacity and not CollectionRunnerService.is_task_active_in_process(task.id):
            reasons.append(QUEUE_REASON_GLOBAL_FULL)
        if task.user_id is not None:
            for running_task in running:
                if running_task.user_id == task.user_id:
                    reasons.append(QUEUE_REASON_USER_RUNNING)
                    break
        return reasons

    @staticmethod
    async def queue_or_start(
        db: AsyncSession,
        task: CollectionTask,
        *,
        resume: bool = False,
    ) -> CollectionTaskStatus:
        from app.services.collection_runner import CollectionRunCapacityError, CollectionRunnerService

        async with _queue_decision_lock:
            reasons = await CollectionQueueService.queue_reasons(db, task)
            if reasons:
                CollectionQueueService.mark_task_queued(task, reasons, resume=resume)
                await db.commit()
                await db.refresh(task)
                return CollectionTaskStatus.QUEUED

            try:
                await CollectionRunnerService._claim_collection_run(task.id)
            except CollectionRunCapacityError:
                CollectionQueueService.mark_task_queued(
                    task,
                    [QUEUE_REASON_GLOBAL_FULL],
                    resume=resume,
                )
                await db.commit()
                await db.refresh(task)
                return CollectionTaskStatus.QUEUED

            try:
                CollectionQueueService.prepare_task_for_run(task, resume=resume)
                await db.commit()
                await db.refresh(task)
            except Exception:
                await CollectionRunnerService._release_collection_run(task.id)
                raise
            return CollectionTaskStatus.RUNNING

    @staticmethod
    def prepare_task_for_run(task: CollectionTask, *, resume: bool = False) -> None:
        checkpoint = dict(task.run_checkpoint or {})
        checkpoint.pop("queue_reasons", None)
        checkpoint.pop("queue_reason_labels", None)
        checkpoint.pop("queued_at", None)
        queued_resume = bool(checkpoint.pop("queued_resume", False))
        task.run_checkpoint = checkpoint
        task.status = CollectionTaskStatus.RUNNING.value
        task.error_message = None
        task.last_error = None
        effective_resume = resume or queued_resume
        if effective_resume:
            task.current_stage = task.current_stage or STAGE_DISCOVERY
        else:
            reset_run_progress(task)
        task.status_summary = _start_message(task, resume=effective_resume)

    @staticmethod
    async def _run_task_and_dispatch(task_id: int, *, resume: bool = False) -> None:
        from app.services.collection_runner import CollectionRunCapacityError, CollectionRunnerService

        async with async_session_factory() as db:
            task = await CollectionTaskService.get_task(db, task_id)
            if not task:
                return
            try:
                await CollectionRunnerService.run_task(db, task, allow_running=True, resume=resume)
            except CollectionRunCapacityError as exc:
                logger.warning("Queued collection task %s returned to queue: %s", task_id, exc)
                await CollectionQueueService.restore_task_to_queue(
                    db,
                    task,
                    reasons=[QUEUE_REASON_GLOBAL_FULL],
                    resume=resume,
                )
            except Exception as exc:
                logger.exception("Queued collection task %s failed: %s", task_id, exc)
            finally:
                await CollectionQueueService.dispatch_queued_tasks()

    @staticmethod
    async def start_background(task_id: int, *, resume: bool = False) -> None:
        asyncio.create_task(CollectionQueueService._run_task_and_dispatch(task_id, resume=resume))

    @staticmethod
    async def dispatch_queued_tasks(
        *,
        db: AsyncSession | None = None,
        starter: Callable[..., Awaitable[None]] | None = None,
    ) -> int:
        owns_session = db is None
        if db is None:
            session_cm = async_session_factory()
            db = await session_cm.__aenter__()
        else:
            session_cm = None
        started = 0
        start = starter or CollectionQueueService.start_background
        try:
            async with _queue_decision_lock:
                while True:
                    result = await db.execute(
                        select(CollectionTask)
                        .where(CollectionTask.status == CollectionTaskStatus.QUEUED.value)
                        .order_by(CollectionTask.updated_at.asc(), CollectionTask.id.asc())
                    )
                    scalars = result.scalars()
                    if inspect.isawaitable(scalars):
                        scalars = await scalars
                    try:
                        queued_tasks = list(scalars)
                    except TypeError:
                        queued_tasks = []
                    if not queued_tasks:
                        break

                    made_progress = False
                    for task in queued_tasks:
                        reasons = await CollectionQueueService.queue_reasons(db, task)
                        if reasons:
                            checkpoint = dict(task.run_checkpoint or {})
                            if checkpoint.get("queue_reasons") != reasons:
                                CollectionQueueService.mark_task_queued(
                                    task,
                                    reasons,
                                    resume=bool(checkpoint.get("queued_resume")),
                                )
                                await db.commit()
                            continue

                        resume = bool((task.run_checkpoint or {}).get("queued_resume"))
                        from app.services.collection_runner import CollectionRunCapacityError, CollectionRunnerService

                        try:
                            await CollectionRunnerService._claim_collection_run(task.id)
                        except CollectionRunCapacityError:
                            CollectionQueueService.mark_task_queued(
                                task,
                                [QUEUE_REASON_GLOBAL_FULL],
                                resume=resume,
                            )
                            await db.commit()
                            continue

                        try:
                            CollectionQueueService.prepare_task_for_run(task, resume=resume)
                            await db.commit()
                            await db.refresh(task)
                            await start(task.id, resume=resume)  # type: ignore[arg-type]
                        except Exception:
                            await CollectionRunnerService._release_collection_run(task.id)
                            CollectionQueueService.mark_task_queued(
                                task,
                                [QUEUE_REASON_GLOBAL_FULL],
                                resume=resume,
                            )
                            await db.commit()
                            logger.exception("Failed to start queued collection task %s", task.id)
                            continue
                        started += 1
                        made_progress = True
                        break

                    if not made_progress:
                        break
        finally:
            if owns_session and session_cm is not None:
                await session_cm.__aexit__(None, None, None)
        return started
