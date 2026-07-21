# 文件说明：后端后台任务执行器，负责异步采集和队列运行；当前文件：collection worker pool
"""In-process / standalone collection worker pool.

Workers atomically claim queued tasks from PostgreSQL (SKIP LOCKED),
run them, heartbeat while running, then release and pump the queue.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.core.config import settings
from app.db.session import async_session_factory
from app.services.collection_lease import CollectionLeaseService, make_worker_id
from app.services.collection_queue import CollectionQueueService
from app.services.collection_runner import CollectionRunCapacityError, CollectionRunnerService
from app.services.collection_task import CollectionTaskService

logger = logging.getLogger(__name__)

_pool_tasks: list[asyncio.Task] = []
_stop_event: asyncio.Event | None = None


def _stale_reconcile_interval_seconds() -> float:
    threshold = CollectionLeaseService.stale_threshold_seconds()
    return float(max(10, min(60, threshold // 2 or threshold)))


async def _reconcile_stale_before_claim(db) -> int:
    return await CollectionTaskService.reconcile_stale_running_tasks(db)


async def _heartbeat_loop(task_id: int, worker_id: str, stop: asyncio.Event) -> None:
    interval = CollectionLeaseService.heartbeat_interval_seconds()
    while not stop.is_set():
        try:
            async with async_session_factory() as db:
                ok = await CollectionLeaseService.touch_heartbeat(db, task_id, worker_id)
                if not ok:
                    logger.warning(
                        "Heartbeat failed for task %s worker %s (lease lost)",
                        task_id,
                        worker_id,
                    )
                    return
        except Exception:
            logger.exception("Heartbeat error for task %s", task_id)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


async def _run_claimed_task(task_id: int, worker_id: str, *, resume: bool) -> None:
    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat_loop(task_id, worker_id, stop))
    try:
        async with async_session_factory() as db:
            task = await CollectionTaskService.get_task(db, task_id)
            if not task:
                return
            if (task.run_checkpoint or {}).get("stopped"):
                return
            try:
                await CollectionRunnerService._claim_collection_run(task_id)
                await CollectionRunnerService.run_task_with_timeout(
                    db,
                    task,
                    allow_running=True,
                    resume=resume,
                )
            except CollectionRunCapacityError as exc:
                logger.warning("Worker %s could not keep capacity for %s: %s", worker_id, task_id, exc)
                await CollectionQueueService.restore_task_to_queue(
                    db,
                    task,
                    reasons=["global_concurrency_full"],
                    resume=resume,
                )
            except Exception:
                logger.exception("Worker %s failed running task %s", worker_id, task_id)
            finally:
                await CollectionRunnerService._release_collection_run(task_id)
                try:
                    await db.refresh(task)
                    CollectionLeaseService.clear_lease(task)
                    await db.commit()
                except Exception:
                    logger.exception("Failed clearing lease for task %s", task_id)
    finally:
        stop.set()
        heartbeat.cancel()
        try:
            await heartbeat
        except (asyncio.CancelledError, Exception):
            pass
        await CollectionQueueService.dispatch_queued_tasks()


async def _worker_loop(slot: int, stop_event: asyncio.Event) -> None:
    worker_id = make_worker_id(slot)
    poll = max(0.2, float(settings.collection_worker_poll_interval_seconds))
    stale_reconcile_interval = _stale_reconcile_interval_seconds()
    last_stale_reconcile = 0.0
    logger.info("Collection worker started: %s", worker_id)
    while not stop_event.is_set():
        claimed_id: int | None = None
        resume = False
        try:
            async with async_session_factory() as db:
                now = time.monotonic()
                if slot == 0 and now - last_stale_reconcile >= stale_reconcile_interval:
                    last_stale_reconcile = now
                    recovered = await _reconcile_stale_before_claim(db)
                    if recovered:
                        logger.warning("Collection worker recovered %s stale task(s) before claim", recovered)
                task = await CollectionLeaseService.claim_next_queued_task(db, worker_id)
                if task is not None:
                    claimed_id = task.id
                    resume = bool((task.run_checkpoint or {}).get("queued_resume"))
            if claimed_id is None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll)
                except asyncio.TimeoutError:
                    pass
                continue
            await _run_claimed_task(claimed_id, worker_id, resume=resume)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Collection worker %s loop error", worker_id)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll)
            except asyncio.TimeoutError:
                pass
    logger.info("Collection worker stopped: %s", worker_id)


def start_embedded_worker_pool() -> int:
    """Start asyncio worker slots inside the current event loop (API process)."""
    global _stop_event, _pool_tasks
    count = CollectionLeaseService.worker_count()
    if count <= 0:
        logger.info("COLLECTION_WORKER_COUNT=0; embedded collection workers disabled")
        return 0
    if _pool_tasks:
        logger.info("Collection worker pool already running (%s)", len(_pool_tasks))
        return len(_pool_tasks)
    _stop_event = asyncio.Event()
    _pool_tasks = [
        asyncio.create_task(_worker_loop(slot, _stop_event), name=f"collection-worker-{slot}")
        for slot in range(count)
    ]
    logger.info("Started embedded collection worker pool: %s workers", count)
    return count


async def stop_embedded_worker_pool() -> None:
    global _stop_event, _pool_tasks
    if not _pool_tasks:
        return
    if _stop_event is not None:
        _stop_event.set()
    for task in _pool_tasks:
        task.cancel()
    await asyncio.gather(*_pool_tasks, return_exceptions=True)
    _pool_tasks = []
    _stop_event = None
    logger.info("Embedded collection worker pool stopped")


async def run_standalone_worker_pool() -> None:
    """Entrypoint for `python -m app.workers.collection_worker`."""
    stop = asyncio.Event()
    count = max(1, CollectionLeaseService.worker_count() or 4)
    tasks = [
        asyncio.create_task(_worker_loop(slot, stop), name=f"collection-worker-{slot}")
        for slot in range(count)
    ]
    logger.info("Standalone collection worker pool running: %s workers", count)
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
