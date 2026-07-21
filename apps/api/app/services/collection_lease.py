# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：collection lease
from __future__ import annotations

import logging
import os
import socket
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionTaskStatus
from app.services.collection_task import CollectionTaskService

logger = logging.getLogger(__name__)


def make_worker_id(slot: int | None = None) -> str:
    host = socket.gethostname()
    pid = os.getpid()
    if slot is None:
        return f"{host}:{pid}"
    return f"{host}:{pid}:w{slot}"


def task_platform_list(task: CollectionTask) -> list[str]:
    platforms = [str(p).lower() for p in (getattr(task, "platforms", None) or []) if p]
    if not platforms and getattr(task, "platform", None):
        platform = str(task.platform).lower()
        if platform and platform != "multi":
            platforms = [platform]
    return list(dict.fromkeys(platforms))


class CollectionLeaseService:
    @staticmethod
    def global_capacity() -> int:
        return max(1, int(settings.collection_max_running_tasks))

    @staticmethod
    def user_capacity() -> int:
        return max(1, int(settings.collection_max_concurrency_per_user))

    @staticmethod
    def platform_capacity() -> int:
        return max(1, int(settings.collection_max_concurrency_per_platform))

    @staticmethod
    def worker_count() -> int:
        return max(0, int(settings.collection_worker_count))

    @staticmethod
    def heartbeat_interval_seconds() -> int:
        return max(5, int(settings.collection_heartbeat_interval_seconds))

    @staticmethod
    def stale_threshold_seconds() -> int:
        return max(30, int(settings.collection_running_stale_seconds))

    @staticmethod
    def is_lease_stale(task: CollectionTask, *, now: datetime | None = None) -> bool:
        if task.status != CollectionTaskStatus.RUNNING.value:
            return False
        current = now.astimezone(UTC) if now and now.tzinfo else (
            now.replace(tzinfo=UTC) if now else datetime.now(UTC)
        )
        reference = CollectionTaskService._as_aware_utc(getattr(task, "heartbeat_at", None))
        if reference is None:
            reference = (
                CollectionTaskService._as_aware_utc(task.updated_at)
                or CollectionTaskService._as_aware_utc(task.created_at)
            )
        if reference is None:
            return False
        return current - reference > timedelta(seconds=CollectionLeaseService.stale_threshold_seconds())

    @staticmethod
    async def list_active_running(
        db: AsyncSession,
        *,
        exclude_id: int | None = None,
    ) -> list[CollectionTask]:
        result = await db.execute(
            select(CollectionTask).where(CollectionTask.status == CollectionTaskStatus.RUNNING.value)
        )
        scalars = result.scalars()
        try:
            rows = list(scalars.all())  # type: ignore[attr-defined]
        except Exception:
            try:
                rows = list(scalars)
            except TypeError:
                rows = []
        active: list[CollectionTask] = []
        for task in rows:
            if exclude_id is not None and task.id == exclude_id:
                continue
            if CollectionTaskService._is_batch_parent(task):
                continue
            if CollectionLeaseService.is_lease_stale(task):
                continue
            active.append(task)
        return active

    @staticmethod
    def capacity_reasons(
        task: CollectionTask,
        running: list[CollectionTask],
    ) -> list[str]:
        from app.services.collection_queue import (
            QUEUE_REASON_GLOBAL_FULL,
            QUEUE_REASON_PLATFORM_FULL,
            QUEUE_REASON_USER_LIMIT,
        )

        reasons: list[str] = []
        if len(running) >= CollectionLeaseService.global_capacity():
            reasons.append(QUEUE_REASON_GLOBAL_FULL)

        if task.user_id is not None:
            user_running = sum(1 for item in running if item.user_id == task.user_id)
            if user_running >= CollectionLeaseService.user_capacity():
                reasons.append(QUEUE_REASON_USER_LIMIT)

        platform_cap = CollectionLeaseService.platform_capacity()
        for platform in task_platform_list(task):
            platform_running = sum(
                1 for item in running if platform in task_platform_list(item)
            )
            if platform_running >= platform_cap:
                reasons.append(QUEUE_REASON_PLATFORM_FULL)
                break
        return reasons

    @staticmethod
    def attach_lease(task: CollectionTask, worker_id: str) -> None:
        now = datetime.now(UTC)
        task.worker_id = worker_id
        task.heartbeat_at = now
        task.run_started_at = now

    @staticmethod
    def clear_lease(task: CollectionTask) -> None:
        task.worker_id = None
        task.heartbeat_at = None
        # keep run_started_at for audit until next claim overwrites

    @staticmethod
    async def touch_heartbeat(
        db: AsyncSession,
        task_id: int,
        worker_id: str,
    ) -> bool:
        now = datetime.now(UTC)
        result = await db.execute(
            update(CollectionTask)
            .where(
                CollectionTask.id == task_id,
                CollectionTask.status == CollectionTaskStatus.RUNNING.value,
                CollectionTask.worker_id == worker_id,
            )
            .values(heartbeat_at=now, updated_at=now)
        )
        await db.commit()
        return bool(result.rowcount)

    @staticmethod
    def _queued_sort_key(task: CollectionTask, running: list[CollectionTask]) -> tuple:
        user_running = 0
        if task.user_id is not None:
            user_running = sum(1 for item in running if item.user_id == task.user_id)
        checkpoint = task.run_checkpoint if isinstance(task.run_checkpoint, dict) else {}
        queued_at = str(checkpoint.get("queued_at") or "")
        updated = CollectionTaskService._as_aware_utc(task.updated_at) or datetime.min.replace(tzinfo=UTC)
        return (user_running, queued_at or updated.isoformat(), task.id)

    @staticmethod
    async def claim_next_queued_task(
        db: AsyncSession,
        worker_id: str,
    ) -> CollectionTask | None:
        """Atomically claim one runnable queued task using SKIP LOCKED."""
        try:
            result = await db.execute(
                select(CollectionTask)
                .where(CollectionTask.status == CollectionTaskStatus.QUEUED.value)
                .order_by(CollectionTask.updated_at.asc(), CollectionTask.id.asc())
                .limit(80)
                .with_for_update(skip_locked=True)
            )
            candidates = [
                task
                for task in result.scalars().all()
                if not CollectionTaskService._is_batch_parent(task)
            ]
            if not candidates:
                return None

            running = await CollectionLeaseService.list_active_running(db)
            candidates.sort(key=lambda task: CollectionLeaseService._queued_sort_key(task, running))

            from app.services.collection_queue import CollectionQueueService

            for task in candidates:
                reasons = CollectionLeaseService.capacity_reasons(task, running)
                if reasons:
                    checkpoint = dict(task.run_checkpoint or {})
                    if checkpoint.get("queue_reasons") != reasons:
                        CollectionQueueService.mark_task_queued(
                            task,
                            reasons,
                            resume=bool(checkpoint.get("queued_resume")),
                        )
                    continue

                resume = bool((task.run_checkpoint or {}).get("queued_resume"))
                CollectionQueueService.prepare_task_for_run(task, resume=resume)
                CollectionLeaseService.attach_lease(task, worker_id)
                await db.commit()
                await db.refresh(task)
                return task

            await db.commit()
            return None
        except Exception:
            try:
                await db.rollback()
            except Exception:
                logger.exception("Failed rolling back collection task claim transaction")
            raise

    @staticmethod
    def concurrency_snapshot(
        *,
        running: list[CollectionTask],
        queued_count: int,
        current_user_id: int | None = None,
    ) -> dict:
        user_running = 0
        if current_user_id is not None:
            user_running = sum(1 for item in running if item.user_id == current_user_id)
        return {
            "global_running": len(running),
            "global_capacity": CollectionLeaseService.global_capacity(),
            "user_running": user_running,
            "user_capacity": CollectionLeaseService.user_capacity(),
            "platform_capacity": CollectionLeaseService.platform_capacity(),
            "queued_count": queued_count,
            "worker_count": CollectionLeaseService.worker_count(),
        }
