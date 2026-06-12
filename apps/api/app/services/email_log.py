import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.schemas.common import PaginatedResponse
from app.schemas.email_log import EmailLogFilter, EmailLogRead


class EmailLogService:
    @staticmethod
    def _apply_filters(query, filters: EmailLogFilter):
        if filters.product_id is not None:
            query = query.where(EmailLog.product_id == filters.product_id)
        if filters.task_id is not None:
            query = query.where(EmailLog.task_id == filters.task_id)
        if filters.status:
            query = query.where(EmailLog.status == filters.status.value)
        return query

    @staticmethod
    async def list_logs(
        db: AsyncSession,
        filters: EmailLogFilter,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[EmailLogRead]:
        base_query = select(EmailLog)
        base_query = EmailLogService._apply_filters(base_query, filters)

        total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
        total = total or 0

        query = (
            base_query.order_by(EmailLog.sent_at.desc().nullslast(), EmailLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(query)
        items = [EmailLogRead.model_validate(row) for row in result.scalars().all()]

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def count_all(db: AsyncSession, *, product_id: int | None = None) -> int:
        query = select(func.count()).select_from(EmailLog)
        if product_id is not None:
            query = query.where(EmailLog.product_id == product_id)
        count = await db.scalar(query)
        return count or 0

    @staticmethod
    async def count_by_status(
        db: AsyncSession,
        status: EmailLogStatus,
        *,
        product_id: int | None = None,
    ) -> int:
        query = select(func.count()).select_from(EmailLog).where(EmailLog.status == status.value)
        if product_id is not None:
            query = query.where(EmailLog.product_id == product_id)
        count = await db.scalar(query)
        return count or 0
