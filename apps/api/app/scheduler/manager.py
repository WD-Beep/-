import logging
from dataclasses import dataclass, field

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionTaskStatus
from app.services.collection_runner import CollectionRunnerService
from app.services.collection_task import CollectionTaskService

logger = logging.getLogger(__name__)

JOB_ID_PREFIX = "collection_task_"


@dataclass
class SchedulerRefreshResult:
    registered: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def job_id_for_task(task_id: int) -> str:
    return f"{JOB_ID_PREFIX}{task_id}"


def parse_cron_expression(cron: str) -> CronTrigger:
    """Parse 5-field cron: minute hour day month day_of_week"""
    expression = cron.strip()
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError(
            f"Cron 表达式需为 5 段格式（分 时 日 月 周），当前为 {len(parts)} 段：{expression}"
        )
    return CronTrigger.from_crontab(expression, timezone="UTC")


async def run_scheduled_collection(task_id: int) -> None:
    """APScheduler 回调：执行定时采集。"""
    logger.info("Starting scheduled collection for task_id=%s", task_id)

    async with async_session_factory() as db:
        task = await db.get(CollectionTask, task_id)
        if not task:
            logger.warning("Scheduled task_id=%s not found", task_id)
            return
        if not task.schedule_enabled:
            logger.info("Task_id=%s schedule disabled, skip", task_id)
            return
        if task.status == CollectionTaskStatus.RUNNING.value:
            logger.warning("Task_id=%s already running, skip scheduled run", task_id)
            return

        blocking_task = await CollectionTaskService.get_blocking_running_task(db, exclude_id=task_id)
        if blocking_task is not None:
            logger.warning(
                "Scheduled task_id=%s skipped: task_id=%s (%s) is running",
                task_id,
                blocking_task.id,
                blocking_task.name,
            )
            return

        if CollectionRunnerService.has_active_collection_run():
            active_ids = CollectionRunnerService.get_active_collection_task_ids()
            if task_id not in active_ids:
                active_id = CollectionRunnerService.get_active_collection_task_id()
                logger.warning(
                    "Scheduled task_id=%s skipped: in-process collection at capacity (%s active, task_id=%s)",
                    task_id,
                    len(active_ids),
                    active_id,
                )
                return

        try:
            await CollectionRunnerService.run_task(db, task)
            logger.info("Scheduled collection completed for task_id=%s", task_id)
        except ValueError as exc:
            logger.warning("Scheduled collection skipped for task_id=%s: %s", task_id, exc)
        except Exception as exc:
            logger.exception("Scheduled collection failed for task_id=%s: %s", task_id, exc)

    await SchedulerManager.sync_next_run_at(task_id)


class SchedulerManager:
    _instance: "SchedulerManager | None" = None

    def __init__(self) -> None:
        self.scheduler: AsyncIOScheduler | None = None

    @classmethod
    def get(cls) -> "SchedulerManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        if self.scheduler and self.scheduler.running:
            return
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.scheduler.start()
        logger.info("APScheduler started")

    def shutdown(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("APScheduler shutdown")
        self.scheduler = None

    def _remove_collection_jobs(self) -> None:
        if not self.scheduler:
            return
        for job in self.scheduler.get_jobs():
            if job.id.startswith(JOB_ID_PREFIX):
                job.remove()

    @staticmethod
    async def _set_task_schedule_error(task_id: int, message: str) -> None:
        async with async_session_factory() as db:
            task = await db.get(CollectionTask, task_id)
            if task:
                task.error_message = message[:2000]
                await db.commit()

    @staticmethod
    async def sync_next_run_at(task_id: int) -> None:
        manager = SchedulerManager.get()
        if not manager.scheduler:
            return
        job = manager.scheduler.get_job(job_id_for_task(task_id))
        next_run = job.next_run_time if job else None

        async with async_session_factory() as db:
            task = await db.get(CollectionTask, task_id)
            if task:
                task.next_run_at = next_run
                await db.commit()

    async def _register_task(self, task: CollectionTask, result: SchedulerRefreshResult) -> None:
        if not self.scheduler:
            result.skipped += 1
            result.errors.append(f"Task {task.id}: scheduler not running")
            return

        if not task.schedule_cron or not task.schedule_cron.strip():
            msg = "已启用定时但未配置 schedule_cron"
            await self._set_task_schedule_error(task.id, msg)
            result.skipped += 1
            result.errors.append(f"Task {task.id} ({task.name}): {msg}")
            return

        try:
            trigger = parse_cron_expression(task.schedule_cron)
        except Exception as exc:
            msg = f"无效的 Cron 表达式「{task.schedule_cron}」: {exc}"
            await self._set_task_schedule_error(task.id, msg)
            result.skipped += 1
            result.errors.append(f"Task {task.id} ({task.name}): {msg}")
            logger.warning("Invalid cron for task %s: %s", task.id, exc)
            return

        try:
            self.scheduler.add_job(
                run_scheduled_collection,
                trigger=trigger,
                id=job_id_for_task(task.id),
                args=[task.id],
                replace_existing=True,
                misfire_grace_time=300,
            )
            result.registered += 1

            async with async_session_factory() as db:
                db_task = await db.get(CollectionTask, task.id)
                if db_task:
                    job = self.scheduler.get_job(job_id_for_task(task.id))
                    db_task.next_run_at = job.next_run_time if job else None
                    if db_task.error_message and any(
                        kw in db_task.error_message for kw in ("Cron", "cron", "定时", "schedule")
                    ):
                        db_task.error_message = None
                    await db.commit()

            logger.info(
                "Registered schedule for task_id=%s cron=%s next_run=%s",
                task.id,
                task.schedule_cron,
                self.scheduler.get_job(job_id_for_task(task.id)).next_run_time,
            )
        except Exception as exc:
            msg = f"注册定时任务失败: {exc}"
            await self._set_task_schedule_error(task.id, msg)
            result.skipped += 1
            result.errors.append(f"Task {task.id} ({task.name}): {msg}")
            logger.exception("Failed to register task %s", task.id)

    async def refresh(self) -> SchedulerRefreshResult:
        """重新加载所有 schedule_enabled=true 的采集任务。"""
        result = SchedulerRefreshResult()

        if not self.scheduler or not self.scheduler.running:
            self.start()

        self._remove_collection_jobs()

        async with async_session_factory() as db:
            rows = await db.execute(
                select(CollectionTask).where(CollectionTask.schedule_enabled.is_(True))
            )
            tasks = list(rows.scalars().all())

        for task in tasks:
            await self._register_task(task, result)

        logger.info(
            "Scheduler refreshed: registered=%s skipped=%s total_enabled=%s",
            result.registered,
            result.skipped,
            len(tasks),
        )
        return result


scheduler_manager = SchedulerManager.get()


async def refresh_scheduler() -> SchedulerRefreshResult:
    return await scheduler_manager.refresh()
