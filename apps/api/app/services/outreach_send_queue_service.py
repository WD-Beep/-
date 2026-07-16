"""邮件发送队列：保守版定时/手动批量发送。"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, time, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG
from app.deps.tenant import TenantContext, require_write_product_id
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_campaign_recipient import OutreachCampaignRecipient
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.schemas.common import PaginatedResponse
from app.schemas.outreach_campaign import OutreachCampaignProcessResponse
from app.schemas.outreach_email import (
    OutreachSendQueueEnqueueRequest,
    OutreachSendQueueProcessResponse,
    OutreachSendQueueRead,
)
from app.services.email import (
    EmailNotConfiguredError,
    EmailService,
    format_smtp_send_error,
    resolve_influencer_email,
)
from app.services.follow_up_scheduler import mark_follow_up_queue_skipped, should_skip_follow_up_queue
from app.services.email_sent_status import product_influencer_has_successful_email_sent
from app.services.email_reply_utils import build_outbound_message_id
from app.services.influencer_lead import InfluencerLeadService
from app.services.influencer_projection import merged_influencer_for_ai
from app.services.outreach_recipient import (
    is_sender_address,
    outreach_recipient_skip_reason,
    validate_real_outreach_recipient,
)
from app.services.product_influencer_service import ProductInfluencerService
from app.services.single_outreach_email_service import BLOCKED_FOLLOW_STATUSES
from app.services.smtp_account import resolve_smtp_account

logger = logging.getLogger(__name__)

ACTIVE_QUEUE_STATUSES = frozenset({"queued", "scheduled", "sending"})
REPLIED_SKIP_STATUSES = frozenset({"replied", "interested", "quoted", "cooperating", "cooperated"})


def _resolve_sender_email() -> str | None:
    return (settings.smtp_from or settings.smtp_user or "").strip() or None


class OutreachSendQueueService:
    @staticmethod
    def _today_bounds() -> tuple[datetime, datetime]:
        tz = ZoneInfo("Asia/Shanghai")
        now_local = datetime.now(tz)
        start = datetime.combine(now_local.date(), time.min, tzinfo=tz)
        end = start + timedelta(days=1)
        return start.astimezone(UTC), end.astimezone(UTC)

    @staticmethod
    async def _count_sent_today(db: AsyncSession, *, product_id: int) -> int:
        start, end = OutreachSendQueueService._today_bounds()
        count = await db.scalar(
            select(func.count())
            .select_from(OutreachSendQueueItem)
            .where(
                OutreachSendQueueItem.product_id == product_id,
                OutreachSendQueueItem.status == "sent",
                OutreachSendQueueItem.sent_at >= start,
                OutreachSendQueueItem.sent_at < end,
            )
        )
        return int(count or 0)

    @staticmethod
    async def _load_pair(
        db: AsyncSession,
        *,
        product_id: int,
        influencer_id: int,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile]:
        pair = await ProductInfluencerService.get_product_influencer(
            db,
            product_id=product_id,
            record_id=influencer_id,
        )
        if not pair:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="红人不存在或不属于当前产品",
            )
        return pair

    @staticmethod
    async def _validate_enqueueable(
        db: AsyncSession,
        product_row: ProductInfluencer,
        global_row: GlobalInfluencerProfile,
        *,
        product_id: int,
        recipient: str,
        allow_resend: bool,
    ) -> None:
        follow = (product_row.follow_status or "").lower()
        if follow in BLOCKED_FOLLOW_STATUSES:
            label = "黑名单" if follow == "blacklisted" else "无效"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"红人状态为{label}，无法加入发送队列",
            )
        if follow in REPLIED_SKIP_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="红人已回复/跟进中，无法加入发送队列",
            )
        if not recipient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少邮箱，无法加入发送队列",
            )
        merged = merged_influencer_for_ai(product_row, global_row)
        resolved = resolve_influencer_email(merged)
        if resolved != recipient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="收件人邮箱与红人档案不一致，请重新预览后再加入队列",
            )
        validate_real_outreach_recipient(recipient)
        if not allow_resend and await product_influencer_has_successful_email_sent(
            db,
            product_id=product_id,
            product_influencer_id=product_row.id,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该红人已有成功发信记录。如需再次发送，请勾选允许二次发送",
            )

    @staticmethod
    async def enqueue(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        influencer_id: int,
        payload: OutreachSendQueueEnqueueRequest,
    ) -> OutreachSendQueueRead:
        product_id = require_write_product_id(ctx)
        product_row, global_row = await OutreachSendQueueService._load_pair(
            db, product_id=product_id, influencer_id=influencer_id
        )
        merged = merged_influencer_for_ai(product_row, global_row)
        recipient = resolve_influencer_email(merged) or ""
        await OutreachSendQueueService._validate_enqueueable(
            db,
            product_row,
            global_row,
            product_id=product_id,
            recipient=recipient,
            allow_resend=payload.allow_resend,
        )

        subject = payload.subject.strip()
        body = payload.body.strip()
        if not subject or not body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮件标题和正文不能为空",
            )

        existing = await db.scalar(
            select(OutreachSendQueueItem.id).where(
                OutreachSendQueueItem.product_id == product_id,
                OutreachSendQueueItem.product_influencer_id == product_row.id,
                OutreachSendQueueItem.status.in_(tuple(ACTIVE_QUEUE_STATUSES)),
            )
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该红人已在发送队列中，请勿重复加入",
            )

        scheduled_at = payload.scheduled_at or datetime.now(UTC)
        matched = [item.model_dump() for item in payload.matched_knowledge] if payload.matched_knowledge else None

        row = OutreachSendQueueItem(
            product_id=product_id,
            user_id=ctx.user_id,
            product_influencer_id=product_row.id,
            recipient=recipient,
            sender_email=_resolve_sender_email(),
            subject=subject,
            body=body,
            status="queued",
            scheduled_at=scheduled_at,
            generated_by_ai=True,
            matched_knowledge=matched,
            ai_reason=(payload.ai_reason or "").strip() or None,
            allow_resend=payload.allow_resend,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return OutreachSendQueueRead.model_validate(row)

    @staticmethod
    async def list_queue(
        db: AsyncSession,
        *,
        product_id: int,
        status: str | None = None,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[OutreachSendQueueRead]:
        query = select(OutreachSendQueueItem).where(OutreachSendQueueItem.product_id == product_id)
        if status:
            query = query.where(OutreachSendQueueItem.status == status)
        total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
        result = await db.execute(
            query.order_by(OutreachSendQueueItem.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [OutreachSendQueueRead.model_validate(row) for row in result.scalars().all()]
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def cancel(db: AsyncSession, *, product_id: int, item_id: int) -> OutreachSendQueueRead:
        row = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.id == item_id,
                OutreachSendQueueItem.product_id == product_id,
            )
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="队列项不存在")
        if row.status not in ACTIVE_QUEUE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="仅 queued/scheduled 状态可取消",
            )
        row.status = "cancelled"
        await db.commit()
        await db.refresh(row)
        return OutreachSendQueueRead.model_validate(row)

    @staticmethod
    async def clear_failed(db: AsyncSession, *, product_id: int) -> int:
        failed_ids = [
            row[0]
            for row in (
                await db.execute(
                    select(OutreachSendQueueItem.id).where(
                        OutreachSendQueueItem.product_id == product_id,
                        OutreachSendQueueItem.status == "failed",
                    )
                )
            ).all()
        ]
        if not failed_ids:
            return 0

        await db.execute(
            update(OutreachCampaignRecipient)
            .where(OutreachCampaignRecipient.queue_item_id.in_(failed_ids))
            .values(queue_item_id=None)
        )
        result = await db.execute(
            delete(OutreachSendQueueItem).where(
                OutreachSendQueueItem.product_id == product_id,
                OutreachSendQueueItem.status == "failed",
            )
        )
        await db.commit()
        return int(result.rowcount or 0)

    @staticmethod
    async def _count_sent_today_for_campaign(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
    ) -> int:
        start, end = OutreachSendQueueService._today_bounds()
        count = await db.scalar(
            select(func.count())
            .select_from(OutreachSendQueueItem)
            .where(
                OutreachSendQueueItem.product_id == product_id,
                OutreachSendQueueItem.campaign_id == campaign_id,
                OutreachSendQueueItem.status == "sent",
                OutreachSendQueueItem.sent_at >= start,
                OutreachSendQueueItem.sent_at < end,
            )
        )
        return int(count or 0)

    @staticmethod
    async def process_campaign_queue(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        campaign: OutreachEmailCampaign,
    ) -> OutreachCampaignProcessResponse:
        from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG
        from app.services.email import EmailNotConfiguredError

        product_id = campaign.product_id
        limit = max(1, int(campaign.daily_limit))
        sent_today = await OutreachSendQueueService._count_sent_today_for_campaign(
            db, product_id=product_id, campaign_id=campaign.id
        )
        remaining = max(0, limit - sent_today)
        if remaining <= 0:
            return OutreachCampaignProcessResponse(
                processed=0,
                sent=0,
                failed=0,
                skipped=0,
                daily_limit=limit,
                sent_today=sent_today,
                message=f"今日已达活动发送上限（{limit} 封/天）",
            )

        try:
            EmailService.ensure_smtp_configured()
        except EmailNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=exc.message or SMTP_NOT_CONFIGURED_MSG,
            ) from exc

        now = datetime.now(UTC)
        result = await db.execute(
            select(OutreachSendQueueItem)
            .where(
                OutreachSendQueueItem.product_id == product_id,
                OutreachSendQueueItem.campaign_id == campaign.id,
                OutreachSendQueueItem.status.in_(("queued", "scheduled")),
                or_(
                    OutreachSendQueueItem.scheduled_at.is_(None),
                    OutreachSendQueueItem.scheduled_at <= now,
                ),
            )
            .order_by(OutreachSendQueueItem.id.asc())
            .limit(remaining)
        )
        rows = list(result.scalars().all())

        sent = failed = skipped = 0
        for row in rows:
            outcome = await OutreachSendQueueService._process_one(
                db, row=row, user_id=ctx.user_id, campaign=campaign
            )
            if outcome == "sent":
                sent += 1
                campaign.sent_count = int(campaign.sent_count or 0) + 1
            elif outcome == "failed":
                failed += 1
                campaign.failed_count = int(campaign.failed_count or 0) + 1
            else:
                skipped += 1
                campaign.skipped_count = int(campaign.skipped_count or 0) + 1

        if sent + failed + skipped > 0 and campaign.status == "running":
            pending = await db.scalar(
                select(func.count())
                .select_from(OutreachSendQueueItem)
                .where(
                    OutreachSendQueueItem.campaign_id == campaign.id,
                    OutreachSendQueueItem.status.in_(("queued", "scheduled")),
                )
            )
            if not pending:
                campaign.status = "completed"

        return OutreachCampaignProcessResponse(
            processed=len(rows),
            sent=sent,
            failed=failed,
            skipped=skipped,
            daily_limit=limit,
            sent_today=sent_today + sent,
            message=f"活动已处理 {len(rows)} 条，成功 {sent}，失败 {failed}，跳过 {skipped}",
        )

    @staticmethod
    async def process_today(
        db: AsyncSession,
        *,
        ctx: TenantContext,
    ) -> OutreachSendQueueProcessResponse:
        product_id = require_write_product_id(ctx)
        limit = max(1, int(settings.outreach_daily_send_limit))
        sent_today = await OutreachSendQueueService._count_sent_today(db, product_id=product_id)
        remaining = max(0, limit - sent_today)
        if remaining <= 0:
            return OutreachSendQueueProcessResponse(
                processed=0,
                sent=0,
                failed=0,
                skipped=0,
                daily_limit=limit,
                sent_today=sent_today,
                message=f"今日已达发送上限（{limit} 封/天）",
            )

        try:
            EmailService.ensure_smtp_configured()
        except EmailNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=exc.message or SMTP_NOT_CONFIGURED_MSG,
            ) from exc

        now = datetime.now(UTC)
        start, end = OutreachSendQueueService._today_bounds()
        result = await db.execute(
            select(OutreachSendQueueItem)
            .where(
                OutreachSendQueueItem.product_id == product_id,
                OutreachSendQueueItem.status.in_(("queued", "scheduled")),
                or_(
                    OutreachSendQueueItem.scheduled_at.is_(None),
                    OutreachSendQueueItem.scheduled_at <= now,
                ),
                or_(
                    OutreachSendQueueItem.scheduled_at.is_(None),
                    and_(
                        OutreachSendQueueItem.scheduled_at >= start,
                        OutreachSendQueueItem.scheduled_at < end,
                    ),
                ),
            )
            .order_by(OutreachSendQueueItem.scheduled_at.asc().nullsfirst(), OutreachSendQueueItem.id.asc())
            .limit(remaining)
        )
        rows = list(result.scalars().all())

        sent = failed = skipped = 0
        for row in rows:
            outcome = await OutreachSendQueueService._process_one(db, row=row, user_id=ctx.user_id)
            if outcome == "sent":
                sent += 1
            elif outcome == "failed":
                failed += 1
            else:
                skipped += 1

        return OutreachSendQueueProcessResponse(
            processed=len(rows),
            sent=sent,
            failed=failed,
            skipped=skipped,
            daily_limit=limit,
            sent_today=sent_today + sent,
            message=f"已处理 {len(rows)} 条队列，成功 {sent}，失败 {failed}，跳过 {skipped}",
        )

    @staticmethod
    async def _process_one(
        db: AsyncSession,
        *,
        row: OutreachSendQueueItem,
        user_id: int | None,
        campaign: OutreachEmailCampaign | None = None,
    ) -> str:
        row.status = "sending"
        await db.commit()

        if await should_skip_follow_up_queue(db, row):
            await mark_follow_up_queue_skipped(db, row)
            return "skipped"

        product_row = await db.scalar(
            select(ProductInfluencer).where(
                ProductInfluencer.id == row.product_influencer_id,
                ProductInfluencer.product_id == row.product_id,
            )
        )
        if not product_row:
            row.status = "skipped"
            row.error_message = "红人已不属于当前产品"
            await db.commit()
            return "skipped"

        global_row = await db.scalar(
            select(GlobalInfluencerProfile).where(
                GlobalInfluencerProfile.id == product_row.global_influencer_id
            )
        )
        if not global_row:
            row.status = "skipped"
            row.error_message = "红人档案缺失"
            await db.commit()
            return "skipped"

        merged = merged_influencer_for_ai(product_row, global_row)
        recipient = resolve_influencer_email(merged)
        follow = (product_row.follow_status or "").lower()
        if follow in BLOCKED_FOLLOW_STATUSES:
            row.status = "skipped"
            row.error_message = f"红人状态为 {follow}，已跳过"
            await db.commit()
            return "skipped"

        if campaign is None and row.campaign_id:
            campaign = await db.get(OutreachEmailCampaign, row.campaign_id)

        skip_replied = campaign.skip_replied if campaign else True
        if skip_replied and follow in REPLIED_SKIP_STATUSES:
            row.status = "skipped"
            row.error_message = "红人已回复/跟进中，已跳过"
            await db.commit()
            return "skipped"

        sender_skip = outreach_recipient_skip_reason(recipient)
        if sender_skip or not recipient or recipient != row.recipient:
            row.status = "skipped"
            if sender_skip:
                row.error_message = sender_skip
            elif not recipient:
                row.error_message = "收件人邮箱已变更或缺失，已跳过"
            elif is_sender_address(recipient):
                row.error_message = "收件人与发件邮箱相同，疑似配置或红人邮箱错误，已跳过"
            else:
                row.error_message = "收件人邮箱已变更或缺失，已跳过"
            await db.commit()
            return "skipped"

        if not row.allow_resend and await product_influencer_has_successful_email_sent(
            db,
            product_id=row.product_id,
            product_influencer_id=product_row.id,
        ):
            row.status = "skipped"
            row.error_message = "该红人已有成功发信记录，已跳过重复发送"
            await db.commit()
            return "skipped"

        sender_account = await resolve_smtp_account(db, user_id=row.user_id or user_id)
        sender_email = sender_account.smtp_from or _resolve_sender_email()
        row.sender_email = sender_email
        row.smtp_account_id = sender_account.account_id
        message_id = build_outbound_message_id(product_id=row.product_id)
        message = MIMEMultipart()
        message["From"] = sender_email or settings.smtp_from
        message["To"] = recipient
        message["Subject"] = row.subject
        message["Message-ID"] = message_id
        message.attach(MIMEText(row.body, "plain", "utf-8"))

        log_kwargs = {
            "task_id": None,
            "recipients": [recipient],
            "subject": row.subject,
            "body": row.body,
            "product_id": row.product_id,
            "user_id": user_id,
            "product_influencer_id": product_row.id,
            "sender_user_id": sender_account.sender_user_id,
            "smtp_account_id": sender_account.account_id,
            "sender_source": sender_account.source,
            "follow_up_index": row.follow_up_step,
            "sender_email": sender_email,
            "influencer_username": global_row.username,
            "generated_by_ai": row.generated_by_ai,
            "ai_provider": "openai" if row.generated_by_ai else None,
            "ai_reason": row.ai_reason,
            "matched_knowledge": row.matched_knowledge,
            "message_id": message_id,
        }

        try:
            await EmailService._send_message(message, [recipient], smtp_account=sender_account)
            log = await EmailService.create_outreach_email_log(
                db,
                status=EmailLogStatus.SENT,
                **log_kwargs,
            )
            await InfluencerLeadService.mark_product_email_sent(
                db,
                product_row,
                subject=row.subject,
                operator_name="outreach_send_queue",
            )
            row.status = "sent"
            row.sent_at = datetime.now(UTC)
            row.email_log_id = log.id
            row.error_message = None
            await db.commit()
            return "sent"
        except Exception as exc:
            err = format_smtp_send_error(exc)
            logger.warning("Queue send failed for item %s: %s", row.id, err)
            log = await EmailService.create_outreach_email_log(
                db,
                status=EmailLogStatus.FAILED,
                error_message=err,
                **log_kwargs,
            )
            row.status = "failed"
            row.error_message = err
            row.email_log_id = log.id
            await db.commit()
            return "failed"
