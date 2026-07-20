from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.tenant import TenantContext
from app.models.collection_task import CollectionTask
from app.models.message_template import MessageTemplate
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.schemas.outreach_campaign import (
    OutreachCampaignCreateRequest,
    OutreachCampaignPreviewRequest,
    OutreachCampaignQueueRequest,
)
from app.services.email import resolve_influencer_email
from app.services.outreach_campaign_service import (
    OutreachCampaignService,
    _is_high_value_product_influencer,
)
from app.services.outreach_recipient import outreach_recipient_skip_reason
from app.services.product_influencer_service import ProductInfluencerService
from app.services.task_influencer import TaskInfluencerService

logger = logging.getLogger(__name__)


def _template_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _template_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        parsed = default
    return min(max(parsed, minimum), maximum)


def _template_text(templates: dict, key: str) -> str:
    return str(templates.get(key) or "").strip()


def build_task_auto_outreach_template_content(templates: dict) -> str:
    parts = [
        f"Email subject template: {_template_text(templates, 'subject_template')}",
        f"Email body template: {_template_text(templates, 'body_template')}",
        f"Product name: {_template_text(templates, 'product_name')}",
        f"Product selling points: {_template_text(templates, 'selling_points')}",
        f"Collaboration offer: {_template_text(templates, 'collaboration_offer')}",
        f"Notes: {_template_text(templates, 'note')}",
        "Rules: Write a personalized English email for each creator. Do not copy the template verbatim. First introduce our brand, then tailor the message to the creator profile, invite them to create a video and post it on Amazon or social media, include the product link if available, and mention an optional Amazon affiliate commission of 10%-30% when appropriate.",
    ]
    return "\n".join(part for part in parts if part.split(":", 1)[-1].strip())


class CollectionAutoOutreachService:
    @staticmethod
    async def _ensure_message_template(
        db: AsyncSession,
        *,
        task: CollectionTask,
        templates: dict,
    ) -> MessageTemplate:
        checkpoint = dict(task.run_checkpoint or {})
        template_id = checkpoint.get("auto_outreach_message_template_id")
        if template_id:
            existing = await db.scalar(
                select(MessageTemplate).where(
                    MessageTemplate.id == int(template_id),
                    MessageTemplate.product_id == task.product_id,
                )
            )
            if existing:
                return existing

        now = datetime.now(UTC)
        row = MessageTemplate(
            user_id=task.user_id or 1,
            workspace_id=task.workspace_id or 1,
            product_id=task.product_id,
            title=f"采集任务自动发信 #{task.id}",
            scenario="collection_auto_outreach",
            platform=(task.platform or None),
            language="en",
            tags=["collection_auto_outreach"],
            content=build_task_auto_outreach_template_content(templates),
            note=_template_text(templates, "note") or None,
            generation_rules={
                "tone": "business",
                "language": "English",
                "subject_format": _template_text(templates, "subject_template"),
                "body_structure": _template_text(templates, "body_template"),
                "required_content": [
                    "brand introduction",
                    "creator-specific personalization",
                    "video creation request",
                    "Amazon or social media posting",
                    "product selling points",
                    "10%-30% Amazon affiliate commission option",
                ],
                "cta": _template_text(templates, "collaboration_offer"),
            },
            is_default=False,
            usage_count=0,
            last_used_at=now,
        )
        db.add(row)
        await db.flush()
        checkpoint["auto_outreach_message_template_id"] = row.id
        task.run_checkpoint = checkpoint
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def _eligible_influencer_ids(
        db: AsyncSession,
        *,
        task: CollectionTask,
        templates: dict,
    ) -> list[int]:
        influencers = await TaskInfluencerService.get_influencers_for_task(db, task)
        ids: list[int] = []
        seen: set[int] = set()
        require_high_value = _template_bool(templates.get("require_high_value"), default=False)
        for influencer in influencers:
            if not influencer.id or influencer.id in seen:
                continue
            recipient = resolve_influencer_email(influencer)
            if outreach_recipient_skip_reason(recipient):
                continue
            pair = await ProductInfluencerService.get_product_influencer(
                db,
                product_id=task.product_id,
                record_id=influencer.id,
            )
            if not pair:
                continue
            product_row, global_row = pair
            if require_high_value and not _is_high_value_product_influencer(
                product_row=product_row,
                global_row=global_row,
            ):
                continue
            seen.add(influencer.id)
            ids.append(influencer.id)
        return ids

    @staticmethod
    async def create_campaign_and_queue(
        db: AsyncSession,
        task: CollectionTask,
        *,
        ctx: TenantContext,
    ) -> dict[str, int | bool | str | None]:
        checkpoint = dict(task.run_checkpoint or {})
        existing_campaign_id = checkpoint.get("auto_outreach_campaign_id")
        if existing_campaign_id:
            return {
                "created": False,
                "campaign_id": int(existing_campaign_id),
                "queued": int(checkpoint.get("auto_outreach_queued") or 0),
                "skipped": int(checkpoint.get("auto_outreach_skipped") or 0),
                "status": str(checkpoint.get("auto_outreach_status") or "already_created"),
            }

        if not task.outreach_enabled or not task.product_id:
            return {"created": False, "campaign_id": None, "queued": 0, "skipped": 0, "status": "disabled"}
        if not task.user_id or not task.workspace_id:
            checkpoint["auto_outreach_status"] = "missing_task_context"
            checkpoint["auto_outreach_queued"] = 0
            checkpoint["auto_outreach_skipped"] = 0
            task.run_checkpoint = checkpoint
            await db.commit()
            return {
                "created": False,
                "campaign_id": None,
                "queued": 0,
                "skipped": 0,
                "status": "missing_task_context",
            }

        templates = dict(task.outreach_templates or {})
        influencer_ids = await CollectionAutoOutreachService._eligible_influencer_ids(
            db,
            task=task,
            templates=templates,
        )
        if not influencer_ids:
            checkpoint["auto_outreach_status"] = "no_eligible_recipients"
            checkpoint["auto_outreach_queued"] = 0
            checkpoint["auto_outreach_skipped"] = 0
            task.run_checkpoint = checkpoint
            await db.commit()
            return {
                "created": False,
                "campaign_id": None,
                "queued": 0,
                "skipped": 0,
                "status": "no_eligible_recipients",
            }

        message_template = await CollectionAutoOutreachService._ensure_message_template(
            db,
            task=task,
            templates=templates,
        )
        daily_limit = _template_int(templates.get("daily_limit"), default=50, minimum=1, maximum=1000)
        allow_resend = _template_bool(templates.get("allow_resend"), default=False)
        campaign_read = await OutreachCampaignService.create_campaign(
            db,
            ctx=ctx,
            payload=OutreachCampaignCreateRequest(
                name=f"采集任务 #{task.id} 自动AI发信",
                influencer_ids=influencer_ids,
                message_template_id=message_template.id,
                daily_limit=daily_limit,
                send_window_start="00:00",
                send_window_end="23:59",
                timezone="Asia/Shanghai",
                skip_sent=not allow_resend,
                skip_replied=True,
                skip_blacklisted=True,
                skip_invalid=True,
                allow_resend=allow_resend,
                auto_send_enabled=False,
            ),
        )
        preview = await OutreachCampaignService.preview_campaign(
            db,
            product_id=task.product_id,
            campaign_id=campaign_read.id,
            payload=OutreachCampaignPreviewRequest(content_source="ai"),
        )
        queue_result = await OutreachCampaignService.queue_campaign(
            db,
            ctx=ctx,
            campaign_id=campaign_read.id,
            payload=OutreachCampaignQueueRequest(confirm=True),
        )
        hourly_limit = _template_int(templates.get("hourly_limit"), default=10, minimum=1, maximum=1000)
        send_interval_minutes = _template_int(
            templates.get("send_interval_minutes"),
            default=6,
            minimum=1,
            maximum=1440,
        )
        await CollectionAutoOutreachService._spread_queue_schedule(
            db,
            campaign_id=campaign_read.id,
            hourly_limit=hourly_limit,
            send_interval_minutes=send_interval_minutes,
        )
        await db.refresh(task)
        checkpoint = dict(task.run_checkpoint or {})
        checkpoint["auto_outreach_campaign_id"] = campaign_read.id
        checkpoint["auto_outreach_message_template_id"] = message_template.id
        checkpoint["auto_outreach_status"] = "queued" if queue_result.queued else "no_queueable_recipients"
        checkpoint["auto_outreach_queued"] = queue_result.queued
        checkpoint["auto_outreach_skipped"] = queue_result.skipped + preview.skip_count
        checkpoint["auto_outreach_created_at"] = datetime.now(UTC).isoformat()
        task.run_checkpoint = checkpoint
        await db.commit()
        return {
            "created": True,
            "campaign_id": campaign_read.id,
            "queued": queue_result.queued,
            "skipped": queue_result.skipped + preview.skip_count,
            "status": checkpoint["auto_outreach_status"],
        }

    @staticmethod
    async def _spread_queue_schedule(
        db: AsyncSession,
        *,
        campaign_id: int,
        hourly_limit: int,
        send_interval_minutes: int,
    ) -> None:
        rows = (
            await db.scalars(
                select(OutreachSendQueueItem)
                .where(
                    OutreachSendQueueItem.campaign_id == campaign_id,
                    OutreachSendQueueItem.status.in_(("queued", "scheduled")),
                )
                .order_by(OutreachSendQueueItem.id.asc())
            )
        ).all()
        if not rows:
            return

        base = datetime.now(UTC)
        for index, row in enumerate(rows):
            hour_block = index // hourly_limit
            index_in_hour = index % hourly_limit
            minutes_offset = (hour_block * 60) + (index_in_hour * send_interval_minutes)
            row.scheduled_at = base + timedelta(minutes=minutes_offset)
            row.status = "scheduled"
        await db.flush()
