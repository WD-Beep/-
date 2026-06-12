import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionMode, CollectionTaskStatus
from app.schemas.collection_task import (
    CollectionTaskCreate,
    CollectionTaskFilter,
    CollectionTaskRead,
    CollectionTaskUpdate,
)
from app.schemas.common import PaginatedResponse


class CollectionTaskService:
    @staticmethod
    def _as_aware_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    async def get_blocking_running_task(
        db: AsyncSession,
        *,
        exclude_id: int | None = None,
    ) -> CollectionTask | None:
        """Return another task that is actively running (not stale), if any."""
        result = await db.execute(
            select(CollectionTask).where(CollectionTask.status == CollectionTaskStatus.RUNNING.value)
        )
        for task in result.scalars():
            if exclude_id is not None and task.id == exclude_id:
                continue
            if not CollectionTaskService.is_running_stale(task):
                return task
        return None

    @staticmethod
    def is_running_stale(
        task: CollectionTask,
        *,
        now: datetime | None = None,
    ) -> bool:
        if task.status != CollectionTaskStatus.RUNNING.value:
            return False
        reference = (
            CollectionTaskService._as_aware_utc(task.updated_at)
            or CollectionTaskService._as_aware_utc(task.created_at)
        )
        if reference is None:
            return False
        threshold_seconds = max(settings.collection_running_stale_seconds, 0)
        current = now.astimezone(UTC) if now and now.tzinfo else (now.replace(tzinfo=UTC) if now else datetime.now(UTC))
        return current - reference > timedelta(seconds=threshold_seconds)

    @staticmethod
    def task_read(task: CollectionTask) -> CollectionTaskRead:
        stale = CollectionTaskService.is_running_stale(task)
        return CollectionTaskRead.model_validate(task).model_copy(
            update={
                "stale": stale,
                "recoverable": stale,
                "stale_after_seconds": max(settings.collection_running_stale_seconds, 0),
            }
        )

    @staticmethod
    def _serialize_task_data(data: dict) -> dict:
        if "status" in data and data["status"] is not None:
            data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
        if "collection_mode" in data and data["collection_mode"] is not None:
            mode = data["collection_mode"]
            data["collection_mode"] = mode.value if hasattr(mode, "value") else mode
        if "email_recipients" in data and data["email_recipients"] is not None:
            data["email_recipients"] = [str(email) for email in data["email_recipients"]]
        return data

    @staticmethod
    def _validate_task_inputs(
        collection_mode: str,
        keywords: list[str],
        input_urls: list[str],
        email_enabled: bool,
        email_recipients: list,
        *,
        category: str | None = None,
    ) -> None:
        keywords = [k.strip() for k in keywords if k and str(k).strip()]
        input_urls = [u.strip() for u in input_urls if u and str(u).strip()]

        mode_value = (
            collection_mode.value
            if isinstance(collection_mode, CollectionMode)
            else collection_mode
        )

        if mode_value in (CollectionMode.KEYWORD.value, CollectionMode.DISCOVERY.value) and not keywords:
            raise ValueError("关键词采集模式至少需要一个关键词")
        if mode_value == CollectionMode.CATEGORY_DISCOVERY.value and not (category or "").strip():
            raise ValueError("类目采集模式必须填写类目")
        if mode_value in (CollectionMode.URLS.value, CollectionMode.CLUSTERING.value) and not input_urls:
            raise ValueError("链接采集模式至少需要一个主页链接")
        if mode_value == CollectionMode.MIXED.value and not keywords and not input_urls:
            raise ValueError("混合模式需要填写关键词或链接至少一项")
        if mode_value == CollectionMode.COMPETITOR_PRODUCT.value and not keywords and not input_urls:
            raise ValueError("竞品商品发现需填写 Amazon 链接、ASIN 或商品关键词")
        if email_enabled and not email_recipients:
            raise ValueError("启用邮件发送时请填写收件人邮箱")

    @staticmethod
    def _apply_filters(query, filters: CollectionTaskFilter):
        if filters.product_id:
            query = query.where(CollectionTask.product_id == filters.product_id)
        if filters.platform:
            query = query.where(CollectionTask.platform == filters.platform)
        if filters.status:
            query = query.where(CollectionTask.status == filters.status.value)
        if filters.search:
            term = f"%{filters.search}%"
            query = query.where(or_(CollectionTask.name.ilike(term), CollectionTask.category.ilike(term)))
        return query

    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        filters: CollectionTaskFilter,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[CollectionTaskRead]:
        base_query = select(CollectionTask)
        base_query = CollectionTaskService._apply_filters(base_query, filters)

        total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
        total = total or 0

        query = base_query.order_by(CollectionTask.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = [CollectionTaskService.task_read(row) for row in result.scalars().all()]

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def get_task(db: AsyncSession, task_id: int) -> CollectionTask | None:
        return await db.get(CollectionTask, task_id)

    @staticmethod
    async def create_task(
        db: AsyncSession,
        data: CollectionTaskCreate,
        *,
        user_id: int | None = None,
        workspace_id: int | None = None,
        product_id: int | None = None,
    ) -> CollectionTask:
        payload = CollectionTaskService._serialize_task_data(data.model_dump())
        if user_id is not None:
            payload["user_id"] = user_id
        if workspace_id is not None:
            payload["workspace_id"] = workspace_id
        if product_id is not None:
            payload["product_id"] = product_id
        task = CollectionTask(**payload)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def update_task(
        db: AsyncSession,
        task: CollectionTask,
        data: CollectionTaskUpdate,
    ) -> CollectionTask:
        update_data = CollectionTaskService._serialize_task_data(data.model_dump(exclude_unset=True))

        merged_mode = update_data.get("collection_mode", task.collection_mode)
        merged_keywords = update_data.get("keywords", task.keywords or [])
        merged_urls = update_data.get("input_urls", task.input_urls or [])
        merged_category = update_data.get("category", task.category)
        merged_email_enabled = update_data.get("email_enabled", task.email_enabled)
        merged_recipients = update_data.get("email_recipients", task.email_recipients or [])

        merged_mode_value = (
            merged_mode.value if isinstance(merged_mode, CollectionMode) else merged_mode
        )
        if any(
            key in update_data
            for key in (
                "collection_mode",
                "keywords",
                "input_urls",
                "category",
                "email_enabled",
                "email_recipients",
            )
        ):
            CollectionTaskService._validate_task_inputs(
                merged_mode,
                merged_keywords,
                merged_urls,
                merged_email_enabled,
                merged_recipients,
                category=merged_category,
            )

        if merged_mode_value == CollectionMode.COMPETITOR_PRODUCT.value:
            update_data["comment_discovery_enabled"] = False

        for field, value in update_data.items():
            setattr(task, field, value)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def delete_task(db: AsyncSession, task: CollectionTask) -> None:
        if task.status == CollectionTaskStatus.RUNNING.value:
            raise ValueError("任务正在运行中，无法删除")
        await db.delete(task)
        await db.commit()

    @staticmethod
    async def get_recent_tasks(
        db: AsyncSession,
        limit: int = 5,
        *,
        product_id: int | None = None,
    ) -> list[CollectionTaskRead]:
        query = select(CollectionTask).order_by(CollectionTask.updated_at.desc()).limit(limit)
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        result = await db.execute(query)
        return [CollectionTaskService.task_read(row) for row in result.scalars().all()]

    @staticmethod
    async def count_by_statuses(
        db: AsyncSession,
        statuses: list[CollectionTaskStatus],
        *,
        product_id: int | None = None,
    ) -> int:
        values = [status.value for status in statuses]
        query = select(func.count()).select_from(CollectionTask).where(CollectionTask.status.in_(values))
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        count = await db.scalar(query)
        return count or 0

    @staticmethod
    async def count_by_status(
        db: AsyncSession,
        status: CollectionTaskStatus,
        *,
        product_id: int | None = None,
    ) -> int:
        query = select(func.count()).select_from(CollectionTask).where(CollectionTask.status == status.value)
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        count = await db.scalar(query)
        return count or 0

    @staticmethod
    async def count_all(db: AsyncSession, *, product_id: int | None = None) -> int:
        query = select(func.count()).select_from(CollectionTask)
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        count = await db.scalar(query)
        return count or 0

    @staticmethod
    async def reconcile_stale_running_tasks(db: AsyncSession) -> int:
        """Mark long-idle running tasks as interrupted so the UI and mutex stay accurate."""
        result = await db.execute(
            select(CollectionTask).where(CollectionTask.status == CollectionTaskStatus.RUNNING.value)
        )
        reconciled = 0
        for task in result.scalars():
            if not CollectionTaskService.is_running_stale(task):
                continue
            task.status = CollectionTaskStatus.PARTIAL_FAILED.value
            task.current_stage = "failed"
            interrupted = "任务已超时中断（可能因服务重启），可重新运行继续采集"
            task.status_summary = interrupted
            if not task.error_message:
                task.error_message = interrupted
            reconciled += 1
        if reconciled:
            await db.commit()
        return reconciled
