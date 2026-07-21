# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：collection queue
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionTaskStatus
from app.services.collection_lease import CollectionLeaseService, make_worker_id
from app.services.collection_task import CollectionTaskService
from app.services.task_run_progress import STAGE_DISCOVERY, reset_run_progress

logger = logging.getLogger(__name__)
_queue_decision_lock = asyncio.Lock()

QUEUE_REASON_GLOBAL_FULL = "global_concurrency_full"
QUEUE_REASON_USER_RUNNING = "user_already_running"  # legacy alias → user limit
QUEUE_REASON_USER_LIMIT = "user_concurrency_full"
QUEUE_REASON_PLATFORM_FULL = "platform_concurrency_full"
QUEUE_REASON_STALE_RECOVERY = "stale_recovered"

QUEUE_REASON_MESSAGES = {
    QUEUE_REASON_GLOBAL_FULL: "全局并发已满",
    QUEUE_REASON_USER_RUNNING: "当前业务员并发已满",
    QUEUE_REASON_USER_LIMIT: "当前业务员并发已满",
    QUEUE_REASON_PLATFORM_FULL: "平台并发已满",
    QUEUE_REASON_STALE_RECOVERY: "stale 回收后重新排队",
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


def _normalize_reasons(reasons: list[str]) -> list[str]:
    normalized: list[str] = []
    for reason in reasons:
        if reason == QUEUE_REASON_USER_RUNNING:
            reason = QUEUE_REASON_USER_LIMIT
        if reason not in normalized:
            normalized.append(reason)
    return normalized


class CollectionQueueService:
    @staticmethod
    def mark_task_queued(
        task: CollectionTask,
        reasons: list[str],
        *,
        resume: bool = False,
    ) -> None:
        reasons = _normalize_reasons(reasons)
        checkpoint = dict(task.run_checkpoint or {})
        checkpoint["queue_reasons"] = reasons
        checkpoint["queue_reason_labels"] = [
            QUEUE_REASON_MESSAGES.get(reason, reason) for reason in reasons
        ]
        checkpoint["queued_at"] = checkpoint.get("queued_at") or datetime.now(UTC).isoformat()
        checkpoint["queued_resume"] = bool(resume)
        if QUEUE_REASON_STALE_RECOVERY in reasons:
            checkpoint["stale_recovered"] = True
            checkpoint["stale_recovered_at"] = datetime.now(UTC).isoformat()
        task.run_checkpoint = checkpoint
        task.status = CollectionTaskStatus.QUEUED.value
        task.current_stage = None
        task.status_summary = _queue_message(reasons)
        task.error_message = None
        task.last_error = None
        CollectionLeaseService.clear_lease(task)

    @staticmethod
    async def restore_task_to_queue(
        db: AsyncSession,
        task: CollectionTask,
        *,
        reasons: list[str] | None = None,
        resume: bool = False,
    ) -> None:
        from app.services.collection_runner import CollectionRunnerService

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
        from app.services.collection_runner import CollectionRunnerService

        await CollectionRunnerService.reconcile_in_process_runs(db)
        return await CollectionLeaseService.list_active_running(db, exclude_id=exclude_id)

    @staticmethod
    async def queue_reasons(db: AsyncSession, task: CollectionTask) -> list[str]:
        from app.services.collection_runner import CollectionRunnerService

        running = await CollectionQueueService.running_tasks(db, exclude_id=task.id)
        task_active = CollectionRunnerService.is_task_active_in_process(task.id)
        if task_active:
            return []
        reasons = CollectionLeaseService.capacity_reasons(task, running)
        # Also respect in-process slots (same API worker) so local capacity is not exceeded
        # even when DB rows lag or are mocked in tests.
        if (
            CollectionRunnerService.has_active_collection_run()
            and not task_active
            and QUEUE_REASON_GLOBAL_FULL not in reasons
        ):
            reasons.insert(0, QUEUE_REASON_GLOBAL_FULL)
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
                CollectionLeaseService.attach_lease(task, make_worker_id())
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
        checkpoint.pop("paused", None)
        checkpoint.pop("paused_at", None)
        checkpoint.pop("pause_requested_at", None)
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

        worker_id = make_worker_id()
        async with async_session_factory() as db:
            task = await CollectionTaskService.get_task(db, task_id)
            if not task:
                return
            if (task.run_checkpoint or {}).get("stopped"):
                return
            if not getattr(task, "worker_id", None):
                CollectionLeaseService.attach_lease(task, worker_id)
                await db.commit()
            try:
                await CollectionRunnerService.run_task_with_timeout(
                    db, task, allow_running=True, resume=resume
                )
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
                try:
                    await db.refresh(task)
                    CollectionLeaseService.clear_lease(task)
                    await db.commit()
                except Exception:
                    logger.exception("Failed clearing lease after task %s", task_id)
                await CollectionQueueService.dispatch_queued_tasks()

    @staticmethod
    async def start_background(task_id: int, *, resume: bool = False) -> None:
        asyncio.create_task(CollectionQueueService._run_task_and_dispatch(task_id, resume=resume))

    @staticmethod
    async def queued_count(db: AsyncSession) -> int:
        result = await db.scalar(
            select(func.count())
            .select_from(CollectionTask)
            .where(CollectionTask.status == CollectionTaskStatus.QUEUED.value)
        )
        return int(result or 0)

    @staticmethod
    async def queue_position(db: AsyncSession, task: CollectionTask) -> int | None:
        if task.status != CollectionTaskStatus.QUEUED.value:
            return None
        result = await db.execute(
            select(CollectionTask.id)
            .where(CollectionTask.status == CollectionTaskStatus.QUEUED.value)
            .order_by(CollectionTask.updated_at.asc(), CollectionTask.id.asc())
        )
        ids = [row[0] for row in result.all()]
        try:
            return ids.index(task.id) + 1
        except ValueError:
            return None

    @staticmethod
    async def concurrency_overview(
        db: AsyncSession,
        *,
        current_user_id: int | None = None,
    ) -> dict:
        running = await CollectionQueueService.running_tasks(db)
        queued = await CollectionQueueService.queued_count(db)
        return CollectionLeaseService.concurrency_snapshot(
            running=running,
            queued_count=queued,
            current_user_id=current_user_id,
        )

    @staticmethod
    async def dispatch_queued_tasks(
        *,
        db: AsyncSession | None = None,
        starter: Callable[..., Awaitable[None]] | None = None,
    ) -> int:
        # When the embedded/standalone worker pool is active, workers claim via
        # SKIP LOCKED. Avoid a second starting path that could race.
        if CollectionLeaseService.worker_count() > 0 and starter is None:
            return 0

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

                    running = await CollectionQueueService.running_tasks(db)
                    queued_tasks.sort(
                        key=lambda task: CollectionLeaseService._queued_sort_key(task, running)
                    )

                    made_progress = False
                    for task in queued_tasks:
                        if CollectionTaskService._is_batch_parent(task):
                            continue
                        reasons = CollectionLeaseService.capacity_reasons(task, running)
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
                        from app.services.collection_runner import (
                            CollectionRunCapacityError,
                            CollectionRunnerService,
                        )

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
                            CollectionLeaseService.attach_lease(task, make_worker_id())
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
                        running.append(task)
                        break

                    if not made_progress:
                        break
        finally:
            if owns_session and session_cm is not None:
                await session_cm.__aexit__(None, None, None)
        return started
