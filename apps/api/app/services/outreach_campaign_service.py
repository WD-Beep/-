"""批量邮件活动：逐红人生成个性化草稿 -> 入队 -> 手动/定时按窗口/限额发送。"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.tenant import TenantContext, require_write_product_id
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.email_reply import EmailReply
from app.models.outreach_campaign_recipient import OutreachCampaignRecipient
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.schemas.knowledge import MatchedKnowledgeItem
from app.schemas.outreach_campaign import (
    AutoCampaignProcessLogItem,
    AutoCampaignProcessResult,
    OutreachCampaignCreateRequest,
    OutreachCampaignGenerateAndSendResponse,
    OutreachOneClickWorkbenchResponse,
    OutreachCampaignPreviewItem,
    OutreachCampaignPreviewRequest,
    OutreachCampaignPreviewResponse,
    OutreachCampaignProcessResponse,
    OutreachCampaignQueueRequest,
    OutreachCampaignQueueResponse,
    OutreachCampaignRead,
    OutreachCampaignRecipientListResponse,
    OutreachCampaignReplyBoardItem,
    OutreachCampaignReplyBoardResponse,
    OutreachWorkbenchResultItem,
    OutreachWorkbenchResultSection,
    OutreachWorkbenchStatusItem,
    OutreachCampaignUpdateRequest,
)
from app.core.config import settings
from app.services.email import resolve_influencer_email
from app.services.email_sent_status import product_influencer_has_successful_email_sent
from app.services.influencer_projection import merged_influencer_for_ai
from app.services.outreach_send_queue_service import OutreachSendQueueService, _resolve_sender_email
from app.services.outreach_recipient import outreach_recipient_skip_reason
from app.services.product_influencer_service import ProductInfluencerService
from app.services.speech_recommendation_service import SpeechRecommendationService

logger = logging.getLogger(__name__)


def _render_outreach_copy_template(
    text: str,
    *,
    product_row: ProductInfluencer,
    global_row: GlobalInfluencerProfile,
) -> str:
    values = {
        "name": global_row.display_name or global_row.username or "",
        "username": global_row.username or "",
        "platform": global_row.platform or "",
        "category": global_row.category or "",
        "niche": global_row.niche or "",
        "brand": "",
        "product": "",
        "price": "",
        "contact": resolve_influencer_email(merged_influencer_for_ai(product_row, global_row)) or "",
    }
    result = text
    for key, value in values.items():
        result = result.replace("{" + key + "}", str(value))
    return result

REPLIED_STATUSES = frozenset({"replied", "interested", "quoted", "cooperating", "cooperated"})
INTERESTED_REPLY_STATUSES = frozenset({"interested", "quoted", "cooperating", "cooperated"})
TERMINAL_CAMPAIGN_STATUSES = frozenset({"cancelled", "completed"})
AUTO_SEND_ACTIVE_STATUSES = frozenset({"running", "ready"})
MAX_CAMPAIGN_RECIPIENTS = 1000


def _coerce_knowledge_section(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_matched_knowledge(items: list | None) -> list[MatchedKnowledgeItem]:
    normalized: list[MatchedKnowledgeItem] = []
    for item in items or []:
        if isinstance(item, MatchedKnowledgeItem):
            normalized.append(
                MatchedKnowledgeItem(
                    document=item.document,
                    section=_coerce_knowledge_section(item.section),
                    summary=item.summary,
                )
            )
            continue
        if isinstance(item, dict):
            normalized.append(
                MatchedKnowledgeItem(
                    document=str(item.get("document", "")),
                    section=_coerce_knowledge_section(item.get("section")),
                    summary=str(item.get("summary", "")),
                )
            )
    return normalized


def _preview_failure_item(
    *,
    influencer_id: int,
    username: str,
    display_name: str | None = None,
    recipient: str | None = None,
    reason: str,
) -> OutreachCampaignPreviewItem:
    return OutreachCampaignPreviewItem(
        influencer_id=influencer_id,
        username=username,
        display_name=display_name,
        recipient=recipient,
        can_queue=False,
        skip_reason=reason,
    )


def _parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d{2}):(\d{2})", value.strip())
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"时间窗口格式无效：{value}，请使用 HH:MM",
        )
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"时间窗口无效：{value}")
    return time(hour=hour, minute=minute)


def is_in_send_window(
    *,
    tz_name: str,
    start: str | None,
    end: str | None,
    now: datetime | None = None,
) -> bool:
    start_t = _parse_hhmm(start)
    end_t = _parse_hhmm(end)
    if start_t is None or end_t is None:
        return True
    tz = ZoneInfo(tz_name or "Asia/Shanghai")
    local_now = (now or datetime.now(UTC)).astimezone(tz)
    current = local_now.time()
    if start_t <= end_t:
        return start_t <= current <= end_t
    return current >= start_t or current <= end_t


def compute_next_auto_process_at(
    *,
    auto_send_time: str,
    tz_name: str,
    from_dt: datetime | None = None,
) -> datetime:
    """Compute next daily auto-send slot in UTC."""
    tz = ZoneInfo(tz_name or "Asia/Shanghai")
    local_now = (from_dt or datetime.now(UTC)).astimezone(tz)
    send_t = _parse_hhmm(auto_send_time)
    assert send_t is not None
    candidate = datetime.combine(local_now.date(), send_t, tzinfo=tz)
    if local_now >= candidate:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def is_auto_send_due(
    *,
    auto_send_time: str,
    tz_name: str,
    last_auto_processed_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """True when local clock matches auto_send_time and not yet processed this slot."""
    tz = ZoneInfo(tz_name or "Asia/Shanghai")
    local_now = (now or datetime.now(UTC)).astimezone(tz)
    send_t = _parse_hhmm(auto_send_time)
    if send_t is None:
        return False
    if local_now.hour != send_t.hour or local_now.minute != send_t.minute:
        return False
    if last_auto_processed_at:
        last_local = last_auto_processed_at.astimezone(tz)
        if last_local.date() == local_now.date() and last_local.hour == send_t.hour:
            return False
    return True


class OutreachCampaignService:
    @staticmethod
    async def get_one_click_workbench(
        db: AsyncSession,
        *,
        product_id: int,
    ) -> OutreachOneClickWorkbenchResponse:
        latest = await OutreachCampaignService._latest_workbench_campaign(
            db, product_id=product_id
        )
        latest_read = (
            await OutreachCampaignService._campaign_read_with_stats(
                db, campaign=latest, product_id=product_id
            )
            if latest
            else None
        )
        results = (
            await OutreachCampaignService._latest_workbench_results(
                db, product_id=product_id, campaign=latest
            )
            if latest
            else OutreachWorkbenchResultSection()
        )
        replies = (
            await OutreachCampaignService.list_campaign_replies(
                db, product_id=product_id, campaign_id=latest.id
            )
            if latest
            else OutreachCampaignReplyBoardResponse(
                campaign_id=0,
                total=0,
                reply_count=0,
                interested_count=0,
                unreplied_count=0,
                latest_reply_at=None,
                items=[],
            )
        )
        return OutreachOneClickWorkbenchResponse(
            ai_generation=OutreachWorkbenchStatusItem(
                status="normal" if settings.is_openai_configured else "not_configured",
                message=(
                    f"{settings.active_ai_provider} 已配置，可生成个性化邮件"
                    if settings.is_openai_configured
                    else "未配置 GPT，无法生成个性化邮件"
                ),
            ),
            smtp=OutreachWorkbenchStatusItem(
                status="normal" if settings.is_smtp_configured and not settings.smtp_from_user_mismatch else "not_configured",
                message=settings.get_smtp_status()["message"],
            ),
            available_recipient_count=await OutreachCampaignService._count_available_recipients(
                db, product_id=product_id
            ),
            latest_campaign=latest_read,
            latest_results=results,
            reply_followup=replies,
        )

    @staticmethod
    async def _latest_workbench_campaign(
        db: AsyncSession,
        *,
        product_id: int,
    ) -> OutreachEmailCampaign | None:
        latest_with_queue = await db.scalar(
            select(OutreachEmailCampaign)
            .join(
                OutreachSendQueueItem,
                OutreachSendQueueItem.campaign_id == OutreachEmailCampaign.id,
            )
            .where(
                OutreachEmailCampaign.product_id == product_id,
                OutreachSendQueueItem.product_id == product_id,
            )
            .group_by(OutreachEmailCampaign.id)
            .order_by(func.max(OutreachSendQueueItem.updated_at).desc(), OutreachEmailCampaign.updated_at.desc())
            .limit(1)
        )
        if latest_with_queue:
            return latest_with_queue
        return await db.scalar(
            select(OutreachEmailCampaign)
            .where(OutreachEmailCampaign.product_id == product_id)
            .order_by(OutreachEmailCampaign.updated_at.desc())
            .limit(1)
        )

    @staticmethod
    async def _count_available_recipients(db: AsyncSession, *, product_id: int) -> int:
        rows = (
            await db.execute(
                select(ProductInfluencer, GlobalInfluencerProfile)
                .join(
                    GlobalInfluencerProfile,
                    GlobalInfluencerProfile.id == ProductInfluencer.global_influencer_id,
                )
                .where(ProductInfluencer.product_id == product_id)
                .limit(MAX_CAMPAIGN_RECIPIENTS)
            )
        ).all()
        count = 0
        for product_row, global_row in rows:
            if (product_row.follow_status or "").lower() in {
                "blacklisted",
                "invalid",
                *REPLIED_STATUSES,
            }:
                continue
            merged = merged_influencer_for_ai(product_row, global_row)
            recipient = resolve_influencer_email(merged)
            if outreach_recipient_skip_reason(recipient):
                continue
            if await product_influencer_has_successful_email_sent(
                db,
                product_id=product_id,
                product_influencer_id=product_row.id,
            ):
                continue
            count += 1
        return count

    @staticmethod
    async def _latest_workbench_results(
        db: AsyncSession,
        *,
        product_id: int,
        campaign: OutreachEmailCampaign,
    ) -> OutreachWorkbenchResultSection:
        recipients = (
            await db.scalars(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).all()
        queue_rows = (
            await db.scalars(
                select(OutreachSendQueueItem).where(
                    OutreachSendQueueItem.product_id == product_id,
                    OutreachSendQueueItem.campaign_id == campaign.id,
                )
            )
        ).all()
        queue_by_id = {row.id: row for row in queue_rows}
        queue_by_influencer = {row.product_influencer_id: row for row in queue_rows}

        items: list[OutreachWorkbenchResultItem] = []
        for rec in recipients:
            pair = await ProductInfluencerService.get_product_influencer(
                db, product_id=product_id, record_id=rec.product_influencer_id
            )
            if pair:
                _product_row, global_row = pair
                username = global_row.username or str(rec.product_influencer_id)
                display_name = global_row.display_name
            else:
                username = str(rec.product_influencer_id)
                display_name = None
            queue_row = (
                queue_by_id.get(rec.queue_item_id)
                if rec.queue_item_id
                else queue_by_influencer.get(rec.product_influencer_id)
            )
            if queue_row and queue_row.status == "sent":
                result_status = "sent"
            elif queue_row and queue_row.status == "failed":
                result_status = "failed"
            elif rec.skip_reason or (queue_row and queue_row.status == "skipped"):
                result_status = "skipped"
            else:
                result_status = "pending"
            items.append(
                OutreachWorkbenchResultItem(
                    influencer_id=rec.product_influencer_id,
                    username=username,
                    display_name=display_name,
                    recipient=rec.recipient or (queue_row.recipient if queue_row else None),
                    status=result_status,
                    subject=rec.subject or (queue_row.subject if queue_row else None),
                    body=rec.body or (queue_row.body if queue_row else None),
                    reason=rec.skip_reason or (queue_row.error_message if queue_row else None),
                    sent_at=queue_row.sent_at if queue_row else None,
                )
            )

        return OutreachWorkbenchResultSection(
            campaign_id=campaign.id,
            total=len(items),
            sent=sum(1 for item in items if item.status == "sent"),
            skipped=sum(1 for item in items if item.status == "skipped"),
            failed=sum(1 for item in items if item.status == "failed"),
            pending=sum(1 for item in items if item.status == "pending"),
            items=items,
        )

    @staticmethod
    async def _get_campaign(
        db: AsyncSession,
        *,
        campaign_id: int,
        product_id: int,
    ) -> OutreachEmailCampaign:
        row = await db.scalar(
            select(OutreachEmailCampaign).where(
                OutreachEmailCampaign.id == campaign_id,
                OutreachEmailCampaign.product_id == product_id,
            )
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邮件活动不存在")
        return row

    @staticmethod
    async def list_campaigns(
        db: AsyncSession,
        *,
        product_id: int,
    ) -> list[OutreachCampaignRead]:
        rows = (
            await db.scalars(
                select(OutreachEmailCampaign)
                .where(OutreachEmailCampaign.product_id == product_id)
                .order_by(OutreachEmailCampaign.updated_at.desc())
            )
        ).all()
        return [
            await OutreachCampaignService._campaign_read_with_stats(
                db, campaign=row, product_id=product_id
            )
            for row in rows
        ]

    @staticmethod
    async def _campaign_read_with_stats(
        db: AsyncSession,
        *,
        campaign: OutreachEmailCampaign,
        product_id: int,
    ) -> OutreachCampaignRead:
        recipients = (
            await db.scalars(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).all()
        queue_rows = (
            await db.scalars(
                select(OutreachSendQueueItem).where(
                    OutreachSendQueueItem.product_id == product_id,
                    OutreachSendQueueItem.campaign_id == campaign.id,
                )
            )
        ).all()
        replies = (
            await db.scalars(
                select(EmailReply).where(
                    EmailReply.product_id == product_id,
                    EmailReply.campaign_id == campaign.id,
                )
            )
        ).all()

        replied_ids = {
            row.product_influencer_id
            for row in replies
            if row.product_influencer_id is not None
        }
        latest_reply_at = max((row.received_at for row in replies), default=None)
        interested_count = 0
        for influencer_id in replied_ids:
            product_row = await db.get(ProductInfluencer, influencer_id)
            if product_row and product_row.product_id == product_id:
                if (product_row.follow_status or "").lower() in INTERESTED_REPLY_STATUSES:
                    interested_count += 1

        draft_count = sum(1 for row in recipients if (row.subject or "").strip() and (row.body or "").strip())
        can_queue_count = sum(1 for row in recipients if row.can_queue)
        queued_count = sum(1 for row in recipients if row.queue_item_id is not None)
        sent_count = sum(1 for row in queue_rows if row.status == "sent")
        failed_count = sum(1 for row in queue_rows if row.status == "failed")
        skipped_count = sum(1 for row in recipients if not row.can_queue)

        result = OutreachCampaignRead.model_validate(campaign)
        result.draft_count = draft_count
        result.can_queue_count = can_queue_count
        result.queued_count = queued_count
        result.sent_count = sent_count
        result.failed_count = failed_count
        result.skipped_count = skipped_count
        result.reply_count = len(replied_ids)
        result.interested_count = interested_count
        result.unreplied_count = max(can_queue_count - len(replied_ids), 0)
        result.latest_reply_at = latest_reply_at
        return result

    @staticmethod
    async def _resolve_influencer_ids(
        db: AsyncSession,
        *,
        product_id: int,
        payload: OutreachCampaignCreateRequest,
    ) -> tuple[list[int], dict | None]:
        if payload.select_all_by_filters:
            assert payload.influencer_filters is not None
            ids = await ProductInfluencerService.list_ids_by_filters(
                db,
                product_id=product_id,
                filters=payload.influencer_filters,
                limit=MAX_CAMPAIGN_RECIPIENTS,
            )
            if not ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="当前筛选条件下没有可加入活动的红人",
                )
            snapshot = payload.influencer_filters.model_dump(exclude_none=True)
            return ids, snapshot
        unique_ids = list(dict.fromkeys(payload.influencer_ids or []))
        if not unique_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请至少选择一位红人",
            )
        return unique_ids, None

    @staticmethod
    async def create_campaign(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        payload: OutreachCampaignCreateRequest,
    ) -> OutreachCampaignRead:
        product_id = require_write_product_id(ctx)
        _parse_hhmm(payload.send_window_start)
        _parse_hhmm(payload.send_window_end)
        if payload.auto_send_enabled:
            _parse_hhmm(payload.auto_send_time)

        unique_ids, filters_snapshot = await OutreachCampaignService._resolve_influencer_ids(
            db, product_id=product_id, payload=payload
        )
        valid_pairs: list[tuple[ProductInfluencer, GlobalInfluencerProfile]] = []
        for influencer_id in unique_ids:
            pair = await ProductInfluencerService.get_product_influencer(
                db, product_id=product_id, record_id=influencer_id
            )
            if not pair:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"红人 #{influencer_id} 不存在或不属于当前产品",
                )
            valid_pairs.append(pair)

        if payload.message_template_id:
            from app.models.message_template import MessageTemplate

            tpl = await db.scalar(
                select(MessageTemplate).where(
                    MessageTemplate.id == payload.message_template_id,
                    MessageTemplate.product_id == product_id,
                )
            )
            if not tpl:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="话术模板不存在")

        if payload.knowledge_base_id:
            from app.models.knowledge import KnowledgeBase

            kb = await db.scalar(
                select(KnowledgeBase).where(
                    KnowledgeBase.id == payload.knowledge_base_id,
                    KnowledgeBase.product_id == product_id,
                )
            )
            if not kb:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="知识库不存在")

        now = datetime.now(UTC)
        next_auto: datetime | None = None
        if payload.auto_send_enabled and payload.auto_send_time:
            next_auto = compute_next_auto_process_at(
                auto_send_time=payload.auto_send_time,
                tz_name=payload.auto_send_timezone or payload.timezone,
                from_dt=now,
            )

        campaign = OutreachEmailCampaign(
            product_id=product_id,
            user_id=ctx.user_id,
            name=payload.name.strip(),
            status="draft",
            knowledge_base_id=payload.knowledge_base_id,
            message_template_id=payload.message_template_id,
            daily_limit=payload.daily_limit,
            send_window_start=payload.send_window_start,
            send_window_end=payload.send_window_end,
            timezone=payload.timezone or "Asia/Shanghai",
            skip_sent=payload.skip_sent,
            skip_replied=payload.skip_replied,
            skip_blacklisted=payload.skip_blacklisted,
            skip_invalid=payload.skip_invalid,
            allow_resend=payload.allow_resend,
            auto_send_enabled=payload.auto_send_enabled,
            auto_send_time=payload.auto_send_time,
            auto_send_timezone=payload.auto_send_timezone or payload.timezone or "Asia/Shanghai",
            next_auto_process_at=next_auto,
            influencer_filters_snapshot=filters_snapshot,
            total_count=len(valid_pairs),
        )
        db.add(campaign)
        await db.flush()

        for product_row, _global_row in valid_pairs:
            db.add(
                OutreachCampaignRecipient(
                    campaign_id=campaign.id,
                    product_influencer_id=product_row.id,
                )
            )
        await db.commit()
        await db.refresh(campaign)
        return OutreachCampaignRead.model_validate(campaign)

    @staticmethod
    async def update_campaign(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
        payload: OutreachCampaignUpdateRequest,
    ) -> OutreachCampaignRead:
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        if campaign.status in TERMINAL_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="活动已结束，无法修改")

        data = payload.model_dump(exclude_unset=True)
        if "send_window_start" in data:
            _parse_hhmm(data["send_window_start"])
        if "send_window_end" in data:
            _parse_hhmm(data["send_window_end"])
        if data.get("auto_send_time"):
            _parse_hhmm(data["auto_send_time"])

        auto_enabled = data.get("auto_send_enabled", campaign.auto_send_enabled)
        auto_time = data.get("auto_send_time", campaign.auto_send_time)
        if auto_enabled and not auto_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="启用自动发送时必须设置 auto_send_time（HH:MM）",
            )

        for key, value in data.items():
            setattr(campaign, key, value)

        if auto_enabled and auto_time:
            tz = campaign.auto_send_timezone or campaign.timezone or "Asia/Shanghai"
            campaign.next_auto_process_at = compute_next_auto_process_at(
                auto_send_time=auto_time,
                tz_name=tz,
            )
        elif "auto_send_enabled" in data and not auto_enabled:
            campaign.next_auto_process_at = None

        await db.commit()
        await db.refresh(campaign)
        return OutreachCampaignRead.model_validate(campaign)

    @staticmethod
    async def _evaluate_skip(
        db: AsyncSession,
        *,
        campaign: OutreachEmailCampaign,
        product_row: ProductInfluencer,
        recipient: str | None,
    ) -> str | None:
        follow = (product_row.follow_status or "").lower()
        if campaign.skip_blacklisted and follow == "blacklisted":
            return "红人在黑名单中"
        if campaign.skip_invalid and follow == "invalid":
            return "红人状态为无效"
        recipient_reason = outreach_recipient_skip_reason(recipient)
        if recipient_reason:
            return recipient_reason
        if campaign.skip_replied and follow in REPLIED_STATUSES:
            return "红人已回复/跟进中，已跳过"
        if campaign.skip_sent and not campaign.allow_resend:
            if await product_influencer_has_successful_email_sent(
                db,
                product_id=campaign.product_id,
                product_influencer_id=product_row.id,
            ):
                return "已有成功发信记录"
        return None

    @staticmethod
    async def preview_campaign(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
        payload: OutreachCampaignPreviewRequest | None = None,
    ) -> OutreachCampaignPreviewResponse:
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        if campaign.status in TERMINAL_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="活动已结束，无法生成邮件")

        recipients = (
            await db.scalars(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).all()

        preview_request = payload or OutreachCampaignPreviewRequest()
        content_source = preview_request.content_source
        script_ids = [campaign.message_template_id] if campaign.message_template_id else None
        template_subject: str | None = None
        template_body: str | None = None
        template_title: str = ""
        if content_source == "template":
            if not campaign.message_template_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="请选择话术库模板",
                )
            from app.models.message_template import MessageTemplate

            template = await db.scalar(
                select(MessageTemplate).where(
                    MessageTemplate.id == campaign.message_template_id,
                    MessageTemplate.product_id == product_id,
                )
            )
            if not template:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="话术模板不存在")
            template_subject = template.title.strip()
            template_body = template.content.strip()
            template_title = template.title
        if content_source == "manual":
            if not (preview_request.subject or "").strip():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先填写邮件主题")
            if not (preview_request.body or "").strip():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先填写邮件正文")

        items: list[OutreachCampaignPreviewItem] = []
        can_queue_count = 0
        now = datetime.now(UTC)

        if not recipients:
            campaign.previewed_at = now
            campaign.status = "ready"
            await db.commit()
            return OutreachCampaignPreviewResponse(
                campaign_id=campaign.id,
                items=[],
                total=0,
                can_queue_count=0,
                skip_count=0,
            )

        for rec in recipients:
            try:
                pair = await ProductInfluencerService.get_product_influencer(
                    db, product_id=product_id, record_id=rec.product_influencer_id
                )
                if not pair:
                    item = _preview_failure_item(
                        influencer_id=rec.product_influencer_id,
                        username=str(rec.product_influencer_id),
                        reason="红人不存在或不属于当前产品",
                    )
                    items.append(item)
                    rec.can_queue = False
                    rec.skip_reason = item.skip_reason
                    rec.previewed_at = now
                    continue

                product_row, global_row = pair
                merged = merged_influencer_for_ai(product_row, global_row)
                recipient = resolve_influencer_email(merged)

                try:
                    skip_reason = await OutreachCampaignService._evaluate_skip(
                        db,
                        campaign=campaign,
                        product_row=product_row,
                        recipient=recipient,
                    )
                except Exception as exc:
                    logger.warning(
                        "Skip evaluation failed for influencer %s: %s",
                        product_row.id,
                        exc,
                    )
                    skip_reason = f"跳过规则检查失败：{str(exc)[:200]}"

                if skip_reason:
                    item = _preview_failure_item(
                        influencer_id=product_row.id,
                        username=global_row.username or "",
                        display_name=global_row.display_name,
                        recipient=recipient,
                        reason=skip_reason,
                    )
                    rec.recipient = recipient
                    rec.can_queue = False
                    rec.skip_reason = skip_reason
                    rec.previewed_at = now
                    items.append(item)
                    continue

                matched = []
                item_template_title = ""
                if content_source == "manual":
                    subject = _render_outreach_copy_template(
                        preview_request.subject or "",
                        product_row=product_row,
                        global_row=global_row,
                    ).strip()
                    body = _render_outreach_copy_template(
                        preview_request.body or "",
                        product_row=product_row,
                        global_row=global_row,
                    ).strip()
                    generation_reason = "使用自己填写的邮件内容"
                    item_template_title = "自己填写"
                elif content_source == "template":
                    subject = _render_outreach_copy_template(
                        template_subject or "",
                        product_row=product_row,
                        global_row=global_row,
                    ).strip()
                    body = _render_outreach_copy_template(
                        template_body or "",
                        product_row=product_row,
                        global_row=global_row,
                    ).strip()
                    generation_reason = "使用话术库模板并替换变量"
                    item_template_title = template_title
                else:
                    try:
                        generation = await SpeechRecommendationService.generate_outreach_email(
                            db,
                            product_id=product_id,
                            global_row=global_row,
                            product_row=product_row,
                            selected_script_ids=script_ids,
                            knowledge_base_id=campaign.knowledge_base_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Outreach email generation failed for influencer %s: %s",
                            product_row.id,
                            exc,
                        )
                        item = _preview_failure_item(
                            influencer_id=product_row.id,
                            username=global_row.username or "",
                            display_name=global_row.display_name,
                            recipient=recipient,
                            reason=f"生成失败：{str(exc)[:200]}",
                        )
                        rec.recipient = recipient
                        rec.can_queue = False
                        rec.skip_reason = item.skip_reason
                        rec.previewed_at = now
                        items.append(item)
                        continue

                    matched = _normalize_matched_knowledge(generation.matched_knowledge)
                    if not matched:
                        base_reason = generation.reason or ""
                        generation_reason = (
                            f"{base_reason}；未引用知识库，仅使用话术和红人资料".strip("；")
                            if base_reason
                            else "未引用知识库，仅使用话术和红人资料"
                        )
                    else:
                        generation_reason = generation.reason or ""
                    subject = (generation.subject or "").strip()
                    body = (generation.body or "").strip()
                    item_template_title = generation.recommended_script_title
                can_queue = bool(subject and body)
                item_skip_reason: str | None = None
                if not can_queue:
                    item_skip_reason = "邮件标题或正文为空，无法入队"
                elif content_source == "ai" and generation.error_message and generation.configured:
                    generation_reason = (
                        f"{generation_reason}；{generation.error_message}".strip("；")
                        if generation_reason
                        else generation.error_message
                    )
                    can_queue = False
                    item_skip_reason = f"AI 生成失败：{generation.error_message}"

                if content_source == "ai" and generation.error_message and generation.configured and subject and body:
                    can_queue = True
                    item_skip_reason = None

                item = OutreachCampaignPreviewItem(
                    influencer_id=product_row.id,
                    username=global_row.username or "",
                    display_name=global_row.display_name,
                    recipient=recipient,
                    subject=subject,
                    body=body,
                    reason=generation_reason,
                    matched_knowledge=matched,
                    template_title=item_template_title,
                    can_queue=can_queue,
                    skip_reason=item_skip_reason,
                )
                rec.recipient = recipient
                rec.subject = subject or None
                rec.body = body or None
                rec.template_title = item_template_title
                rec.reason = generation_reason
                rec.matched_knowledge = [m.model_dump() for m in matched]
                rec.can_queue = item.can_queue
                rec.skip_reason = item_skip_reason
                rec.previewed_at = now
                if item.can_queue:
                    can_queue_count += 1
                items.append(item)
            except Exception as exc:
                logger.exception(
                    "Unexpected preview failure for recipient %s: %s",
                    rec.product_influencer_id,
                    exc,
                )
                reason = f"预览失败：{str(exc)[:200]}"
                item = _preview_failure_item(
                    influencer_id=rec.product_influencer_id,
                    username=str(rec.product_influencer_id),
                    reason=reason,
                )
                rec.can_queue = False
                rec.skip_reason = reason
                rec.previewed_at = now
                items.append(item)

        campaign.previewed_at = now
        campaign.status = "ready"
        await db.commit()

        return OutreachCampaignPreviewResponse(
            campaign_id=campaign.id,
            items=items,
            total=len(items),
            can_queue_count=can_queue_count,
            skip_count=len(items) - can_queue_count,
        )

    @staticmethod
    async def list_campaign_recipients(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
    ) -> OutreachCampaignRecipientListResponse:
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        recipients = (
            await db.scalars(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).all()

        items: list[OutreachCampaignPreviewItem] = []
        for rec in recipients:
            pair = await ProductInfluencerService.get_product_influencer(
                db, product_id=product_id, record_id=rec.product_influencer_id
            )
            if pair:
                _, global_row = pair
                username = global_row.username or str(rec.product_influencer_id)
                display_name = global_row.display_name
            else:
                username = str(rec.product_influencer_id)
                display_name = None

            matched = _normalize_matched_knowledge(rec.matched_knowledge or [])
            items.append(
                OutreachCampaignPreviewItem(
                    influencer_id=rec.product_influencer_id,
                    username=username,
                    display_name=display_name,
                    recipient=rec.recipient,
                    subject=rec.subject or "",
                    body=rec.body or "",
                    reason=rec.reason or "",
                    matched_knowledge=matched,
                    template_title=rec.template_title or "",
                    can_queue=bool(rec.can_queue),
                    skip_reason=rec.skip_reason,
                )
            )

        can_queue_count = sum(1 for item in items if item.can_queue)
        return OutreachCampaignRecipientListResponse(
            campaign_id=campaign.id,
            items=items,
            total=len(items),
            can_queue_count=can_queue_count,
            skip_count=len(items) - can_queue_count,
        )

    @staticmethod
    async def list_campaign_replies(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
    ) -> OutreachCampaignReplyBoardResponse:
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        recipients = (
            await db.scalars(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).all()
        queue_rows = (
            await db.scalars(
                select(OutreachSendQueueItem).where(
                    OutreachSendQueueItem.product_id == product_id,
                    OutreachSendQueueItem.campaign_id == campaign.id,
                )
            )
        ).all()
        replies = (
            await db.scalars(
                select(EmailReply)
                .where(
                    EmailReply.product_id == product_id,
                    EmailReply.campaign_id == campaign.id,
                )
                .order_by(EmailReply.received_at.desc())
            )
        ).all()

        queue_by_influencer = {
            row.product_influencer_id: row
            for row in queue_rows
        }
        latest_reply_by_influencer: dict[int, EmailReply] = {}
        for reply in replies:
            if reply.product_influencer_id is None:
                continue
            latest_reply_by_influencer.setdefault(reply.product_influencer_id, reply)

        items: list[OutreachCampaignReplyBoardItem] = []
        for rec in recipients:
            pair = await ProductInfluencerService.get_product_influencer(
                db, product_id=product_id, record_id=rec.product_influencer_id
            )
            if pair:
                product_row, global_row = pair
                username = global_row.username or str(rec.product_influencer_id)
                display_name = global_row.display_name
                platform = global_row.platform
                follow_status = (product_row.follow_status or "").lower()
            else:
                username = str(rec.product_influencer_id)
                display_name = None
                platform = None
                follow_status = ""

            queue_row = queue_by_influencer.get(rec.product_influencer_id)
            reply = latest_reply_by_influencer.get(rec.product_influencer_id)
            if queue_row:
                send_status = queue_row.status
            elif rec.skip_reason:
                send_status = "skipped"
            else:
                send_status = "not_queued"

            if reply:
                reply_status = (
                    "interested"
                    if follow_status in INTERESTED_REPLY_STATUSES
                    else "replied"
                )
            elif rec.skip_reason:
                reply_status = "skipped"
            else:
                reply_status = "unreplied"

            items.append(
                OutreachCampaignReplyBoardItem(
                    influencer_id=rec.product_influencer_id,
                    username=username,
                    display_name=display_name,
                    platform=platform,
                    recipient=rec.recipient,
                    subject=rec.subject or (queue_row.subject if queue_row else None),
                    send_status=send_status,
                    reply_status=reply_status,
                    reply_time=reply.received_at if reply else None,
                    reply_snippet=reply.snippet if reply else None,
                    reply_body=reply.body if reply else None,
                    match_method=reply.match_method if reply else None,
                    skip_reason=rec.skip_reason,
                )
            )

        reply_count = sum(1 for item in items if item.reply_status in {"replied", "interested"})
        interested_count = sum(1 for item in items if item.reply_status == "interested")
        unreplied_count = sum(1 for item in items if item.reply_status == "unreplied")
        latest_reply_at = max(
            (item.reply_time for item in items if item.reply_time is not None),
            default=None,
        )
        return OutreachCampaignReplyBoardResponse(
            campaign_id=campaign.id,
            total=len(items),
            reply_count=reply_count,
            interested_count=interested_count,
            unreplied_count=unreplied_count,
            latest_reply_at=latest_reply_at,
            items=items,
        )

    @staticmethod
    async def queue_campaign(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        campaign_id: int,
        payload: OutreachCampaignQueueRequest,
    ) -> OutreachCampaignQueueResponse:
        if not payload.confirm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="加入队列前必须确认（confirm=true）",
            )

        product_id = require_write_product_id(ctx)
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        if not campaign.previewed_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请先生成个性化邮件草稿后再加入队列",
            )
        if campaign.status in TERMINAL_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="活动已结束")

        filter_ids = set(payload.influencer_ids or [])
        recipients = (
            await db.scalars(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).all()

        queued = skipped = 0
        now = datetime.now(UTC)

        for rec in recipients:
            if filter_ids and rec.product_influencer_id not in filter_ids:
                continue
            if rec.queue_item_id:
                skipped += 1
                continue
            subject = (rec.subject or "").strip()
            body = (rec.body or "").strip()
            if not rec.can_queue or not subject or not body or not rec.recipient:
                if rec.can_queue and rec.recipient and (not subject or not body):
                    rec.can_queue = False
                    rec.skip_reason = "邮件标题或正文为空，无法入队"
                skipped += 1
                continue

            pair = await ProductInfluencerService.get_product_influencer(
                db, product_id=product_id, record_id=rec.product_influencer_id
            )
            if not pair:
                skipped += 1
                continue
            product_row, global_row = pair
            merged = merged_influencer_for_ai(product_row, global_row)
            recipient = resolve_influencer_email(merged)
            skip_reason = await OutreachCampaignService._evaluate_skip(
                db, campaign=campaign, product_row=product_row, recipient=recipient
            )
            if skip_reason or recipient != rec.recipient:
                rec.can_queue = False
                rec.skip_reason = skip_reason or "邮箱已变更"
                skipped += 1
                continue

            existing = await db.scalar(
                select(OutreachSendQueueItem.id).where(
                    OutreachSendQueueItem.product_id == product_id,
                    OutreachSendQueueItem.product_influencer_id == product_row.id,
                    OutreachSendQueueItem.status.in_(("queued", "scheduled", "sending")),
                )
            )
            if existing:
                skipped += 1
                continue

            queue_row = OutreachSendQueueItem(
                product_id=product_id,
                user_id=ctx.user_id,
                product_influencer_id=product_row.id,
                campaign_id=campaign.id,
                recipient=recipient,
                sender_email=_resolve_sender_email(),
                subject=subject,
                body=body,
                status="queued",
                scheduled_at=now,
                generated_by_ai=True,
                matched_knowledge=rec.matched_knowledge,
                ai_reason=rec.reason,
                allow_resend=campaign.allow_resend,
            )
            db.add(queue_row)
            await db.flush()
            rec.queue_item_id = queue_row.id
            rec.queued_at = now
            queued += 1

        campaign.queued_count = int(
            await db.scalar(
                select(func.count())
                .select_from(OutreachCampaignRecipient)
                .where(
                    OutreachCampaignRecipient.campaign_id == campaign.id,
                    OutreachCampaignRecipient.queue_item_id.is_not(None),
                )
            )
            or 0
        )
        if queued > 0 and campaign.status in ("draft", "ready"):
            campaign.status = "running"
        await db.commit()

        return OutreachCampaignQueueResponse(
            queued=queued,
            skipped=skipped,
            message=f"已加入队列 {queued} 条，跳过 {skipped} 条",
        )

    @staticmethod
    async def process_campaign(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        campaign_id: int,
    ) -> OutreachCampaignProcessResponse:
        product_id = require_write_product_id(ctx)
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        if campaign.status == "cancelled":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="活动已取消")
        if campaign.status == "paused":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="活动已暂停，请先恢复")

        if not is_in_send_window(
            tz_name=campaign.timezone,
            start=campaign.send_window_start,
            end=campaign.send_window_end,
        ):
            window = f"{campaign.send_window_start or '00:00'}-{campaign.send_window_end or '23:59'}"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"当前不在发送时间窗口内（{window} {campaign.timezone}），请稍后再试",
            )

        result = await OutreachSendQueueService.process_campaign_queue(
            db,
            ctx=ctx,
            campaign=campaign,
        )
        campaign.last_processed_at = datetime.now(UTC)
        if campaign.status == "ready":
            campaign.status = "running"
        await db.commit()
        return result

    @staticmethod
    async def generate_and_send_campaign(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        campaign_id: int,
    ) -> OutreachCampaignGenerateAndSendResponse:
        product_id = require_write_product_id(ctx)
        preview = await OutreachCampaignService.preview_campaign(
            db,
            product_id=product_id,
            campaign_id=campaign_id,
        )
        queue_result = await OutreachCampaignService.queue_campaign(
            db,
            ctx=ctx,
            campaign_id=campaign_id,
            payload=OutreachCampaignQueueRequest(confirm=True),
        )
        process_result = await OutreachCampaignService.process_campaign(
            db,
            ctx=ctx,
            campaign_id=campaign_id,
        )
        total_skipped = preview.skip_count + process_result.skipped
        return OutreachCampaignGenerateAndSendResponse(
            campaign_id=campaign_id,
            preview=preview,
            queued=queue_result.queued,
            queue_skipped=queue_result.skipped,
            processed=process_result.processed,
            sent=process_result.sent,
            failed=process_result.failed,
            skipped=process_result.skipped,
            daily_limit=process_result.daily_limit,
            sent_today=process_result.sent_today,
            message=(
                "已一键生成并发送："
                f"生成 {preview.total} 人，"
                f"入队 {queue_result.queued} 封，"
                f"成功发送 {process_result.sent} 封，"
                f"失败 {process_result.failed} 封，"
                f"跳过 {total_skipped} 人"
            ),
        )

    @staticmethod
    async def pause_campaign(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
    ) -> OutreachCampaignRead:
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        if campaign.status in TERMINAL_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="活动已结束")
        campaign.status = "paused"
        await db.commit()
        await db.refresh(campaign)
        return OutreachCampaignRead.model_validate(campaign)

    @staticmethod
    async def resume_campaign(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
    ) -> OutreachCampaignRead:
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        if campaign.status != "paused":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅暂停状态可恢复")
        campaign.status = "running"
        await db.commit()
        await db.refresh(campaign)
        return OutreachCampaignRead.model_validate(campaign)

    @staticmethod
    async def cancel_campaign(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
    ) -> OutreachCampaignRead:
        campaign = await OutreachCampaignService._get_campaign(
            db, campaign_id=campaign_id, product_id=product_id
        )
        campaign.status = "cancelled"
        queue_rows = (
            await db.scalars(
                select(OutreachSendQueueItem).where(
                    OutreachSendQueueItem.campaign_id == campaign.id,
                    OutreachSendQueueItem.status.in_(("queued", "scheduled")),
                )
            )
        ).all()
        for row in queue_rows:
            row.status = "cancelled"
        await db.commit()
        await db.refresh(campaign)
        return OutreachCampaignRead.model_validate(campaign)

    @staticmethod
    async def process_due_auto_campaigns(
        db: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> AutoCampaignProcessResult:
        """Process campaigns whose daily auto-send slot is due. Safe for cron/scheduler."""
        from app.models.tenant import Product

        run_at = now or datetime.now(UTC)
        rows = (
            await db.scalars(
                select(OutreachEmailCampaign).where(
                    OutreachEmailCampaign.auto_send_enabled.is_(True),
                    OutreachEmailCampaign.auto_send_time.is_not(None),
                    OutreachEmailCampaign.status.in_(tuple(AUTO_SEND_ACTIVE_STATUSES)),
                )
            )
        ).all()

        items: list[AutoCampaignProcessLogItem] = []
        processed_count = 0

        for campaign in rows:
            tz = campaign.auto_send_timezone or campaign.timezone or "Asia/Shanghai"
            if not is_auto_send_due(
                auto_send_time=campaign.auto_send_time or "",
                tz_name=tz,
                last_auto_processed_at=campaign.last_auto_processed_at,
                now=run_at,
            ):
                continue

            if not is_in_send_window(
                tz_name=campaign.timezone,
                start=campaign.send_window_start,
                end=campaign.send_window_end,
                now=run_at,
            ):
                items.append(
                    AutoCampaignProcessLogItem(
                        campaign_id=campaign.id,
                        processed=0,
                        sent=0,
                        failed=0,
                        skipped=0,
                        error_message="当前不在发送时间窗口内",
                        run_at=run_at,
                    )
                )
                continue

            product = await db.get(Product, campaign.product_id)
            if not product:
                continue

            ctx = TenantContext(
                user_id=campaign.user_id,
                product_id=campaign.product_id,
                workspace_id=product.workspace_id,
                is_admin=True,
            )

            log_item = AutoCampaignProcessLogItem(
                campaign_id=campaign.id,
                processed=0,
                sent=0,
                failed=0,
                skipped=0,
                run_at=run_at,
            )
            try:
                result = await OutreachSendQueueService.process_campaign_queue(
                    db, ctx=ctx, campaign=campaign
                )
                campaign.last_processed_at = run_at
                campaign.last_auto_processed_at = run_at
                campaign.next_auto_process_at = compute_next_auto_process_at(
                    auto_send_time=campaign.auto_send_time or "10:00",
                    tz_name=tz,
                    from_dt=run_at,
                )
                if campaign.status == "ready":
                    campaign.status = "running"
                log_item.processed = result.processed
                log_item.sent = result.sent
                log_item.failed = result.failed
                log_item.skipped = result.skipped
                processed_count += 1
            except HTTPException as exc:
                log_item.error_message = str(exc.detail)
            except Exception as exc:
                log_item.error_message = str(exc)[:500]
            items.append(log_item)

        if items:
            await db.commit()

        return AutoCampaignProcessResult(
            checked=len(rows),
            processed=processed_count,
            items=items,
        )
