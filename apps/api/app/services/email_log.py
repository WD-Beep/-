import math

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.tenant import TenantContext
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.message_template import MessageTemplate
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.schemas.common import PaginatedResponse
from app.schemas.email_log import (
    EmailLogFilter,
    EmailLogRead,
    SaveEmailLogAsTemplateRequest,
    SaveEmailLogAsTemplateResponse,
)
from app.schemas.message_template import MessageTemplateCreate
from app.services.message_template import MessageTemplateService
from app.services.test_data_visibility import business_email_log_filter


class EmailLogService:
    @staticmethod
    def _business_base_query():
        return select(EmailLog).where(business_email_log_filter())

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
        base_query = EmailLogService._business_base_query()
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
        query = select(func.count()).select_from(EmailLog).where(business_email_log_filter())
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
        query = (
            select(func.count())
            .select_from(EmailLog)
            .where(EmailLog.status == status.value)
            .where(business_email_log_filter())
        )
        if product_id is not None:
            query = query.where(EmailLog.product_id == product_id)
        count = await db.scalar(query)
        return count or 0

    @staticmethod
    async def get_log(
        db: AsyncSession,
        *,
        log_id: int,
        product_id: int,
    ) -> EmailLog | None:
        return await db.scalar(
            select(EmailLog).where(EmailLog.id == log_id, EmailLog.product_id == product_id)
        )

    @staticmethod
    async def bulk_delete_logs(
        db: AsyncSession,
        *,
        log_ids: list[int],
        product_id: int,
    ) -> tuple[list[int], list[int]]:
        unique_ids = list(dict.fromkeys(log_ids))
        rows = (
            await db.scalars(
                select(EmailLog.id).where(
                    EmailLog.product_id == product_id,
                    EmailLog.id.in_(unique_ids),
                )
            )
        ).all()
        deleted_ids = list(rows)
        missing_ids = [log_id for log_id in unique_ids if log_id not in set(deleted_ids)]
        if not deleted_ids:
            return [], missing_ids

        await db.execute(
            update(OutreachSendQueueItem)
            .where(
                OutreachSendQueueItem.product_id == product_id,
                OutreachSendQueueItem.email_log_id.in_(deleted_ids),
            )
            .values(email_log_id=None)
        )
        rows_to_delete = (
            await db.scalars(
                select(EmailLog).where(
                    EmailLog.product_id == product_id,
                    EmailLog.id.in_(deleted_ids),
                )
            )
        ).all()
        for row in rows_to_delete:
            await db.delete(row)
        await db.commit()
        return deleted_ids, missing_ids

    @staticmethod
    async def bulk_delete_logs_by_status(
        db: AsyncSession,
        *,
        status: EmailLogStatus,
        product_id: int,
    ) -> list[int]:
        rows = (
            await db.scalars(
                select(EmailLog.id).where(
                    EmailLog.product_id == product_id,
                    EmailLog.status == status.value,
                    business_email_log_filter(),
                )
            )
        ).all()
        deleted_ids = list(rows)
        if not deleted_ids:
            return []
        deleted_ids, _ = await EmailLogService.bulk_delete_logs(
            db,
            log_ids=deleted_ids,
            product_id=product_id,
        )
        return deleted_ids

    @staticmethod
    async def save_as_message_template(
        db: AsyncSession,
        *,
        log: EmailLog,
        ctx: TenantContext,
        payload: SaveEmailLogAsTemplateRequest,
    ) -> SaveEmailLogAsTemplateResponse:
        product_id = ctx.product_id
        if not log.generated_by_ai:
            return SaveEmailLogAsTemplateResponse(
                created=False,
                message="仅支持将 AI 生成的邮件保存为话术",
                template=None,
            )
        if log.status != EmailLogStatus.SENT.value:
            return SaveEmailLogAsTemplateResponse(
                created=False,
                message="仅支持保存已成功发送的 AI 邮件",
                template=None,
            )
        body = (payload.content or log.body or "").strip()
        if not body:
            return SaveEmailLogAsTemplateResponse(
                created=False,
                message="邮件正文为空，无法保存",
                template=None,
            )
        title = (payload.title or log.subject or "Saved outreach email").strip()
        if not title:
            title = "Saved outreach email"

        duplicate = await db.scalar(
            select(MessageTemplate.id).where(
                MessageTemplate.product_id == product_id,
                MessageTemplate.title == title,
                MessageTemplate.content == body,
            )
        )
        if duplicate and not payload.save_as_copy:
            return SaveEmailLogAsTemplateResponse(
                created=False,
                duplicate=True,
                message="当前产品下已存在相同标题和正文的话术，可确认另存为副本",
                template=None,
            )
        if duplicate and payload.save_as_copy:
            title = f"{title}（副本）"[:255]

        platform = (payload.platform or "").strip() or None
        if not platform and log.product_influencer_id:
            product_row = await db.scalar(
                select(ProductInfluencer).where(
                    ProductInfluencer.id == log.product_influencer_id,
                    ProductInfluencer.product_id == product_id,
                )
            )
            if product_row:
                global_row = await db.scalar(
                    select(GlobalInfluencerProfile).where(
                        GlobalInfluencerProfile.id == product_row.global_influencer_id
                    )
                )
                if global_row and global_row.platform:
                    platform = global_row.platform

        row = await MessageTemplateService.create_template(
            db,
            MessageTemplateCreate(
                title=title,
                scenario=(payload.scenario or "first_contact").strip(),
                platform=platform,
                language=(payload.language or "en").strip() or "en",
                tags=payload.tags or ["ai_outreach", "saved_from_email"],
                content=body,
                note=(payload.note or f"Saved from email log #{log.id}").strip() or None,
            ),
            ctx=ctx,
        )
        return SaveEmailLogAsTemplateResponse(
            created=True,
            message="已保存为话术模板",
            template=MessageTemplateService._to_read(row),
        )
