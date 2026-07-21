from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.deps.tenant import TenantContext
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionTaskStatus
from app.models.message_template import MessageTemplate
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.schemas.outreach_email import OutreachEmailGenerationResult
from app.services.collection_auto_outreach import CollectionAutoOutreachService
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _mock_generation(subject: str = "Personalized subject", body: str = "Personalized body"):
    return OutreachEmailGenerationResult(
        subject=subject,
        body=body,
        recommended_script_title="Task auto outreach",
        reason="generated from task template",
        matched_knowledge=[],
    )


async def _create_task_with_inserted_candidate(
    db,
    *,
    candidate_count: int = 1,
    task_country: str | None = None,
    task_category: str | None = None,
    influencer_country: str | None = None,
    influencer_category: str | None = None,
):
    suffix = _suffix()
    run_at = datetime.now(UTC)
    task = CollectionTask(
        product_id=1,
        user_id=1,
        workspace_id=1,
        name=f"auto outreach {_suffix()}",
        collection_mode="discovery",
        platform="instagram",
        platforms=["instagram"],
        keywords=["home decor"],
        country=task_country,
        category=task_category,
        status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
        outreach_enabled=True,
        outreach_dry_run=False,
        outreach_templates={
            "subject_template": "Collaboration with {绾汉鍚嶇О}",
            "body_template": "Introduce our brand and invite this creator.",
            "product_name": "Travel Home Lamp",
            "selling_points": "Portable, warm light, Amazon-ready",
            "collaboration_offer": "Create a video and join our Amazon affiliate plan.",
            "daily_limit": "25",
            "hourly_limit": "5",
            "send_interval_minutes": "8",
            "allow_resend": "false",
        },
        run_checkpoint={},
    )
    db.add(task)
    await db.flush()

    for index in range(candidate_count):
        item = CollectedInfluencer(
            platform="instagram",
            username=f"creator_{suffix}_{index}",
            profile_url=f"https://instagram.com/creator_{suffix}_{index}",
            platform_unique_id=f"ig_creator_{suffix}_{index}",
            followers_count=28000 + index,
            engagement_rate=4.2,
            country=influencer_country,
            category=influencer_category,
            bio="home decor creator",
            final_email=f"creator_{suffix}_{index}@gmail.com",
        )
        global_profile = create_global_profile_from_collected(item, run_at=run_at)
        db.add(global_profile)
        await db.flush()
        product_row = create_product_influencer_from_collected(
            product_id=1,
            global_profile=global_profile,
            data=item,
            task=None,
            run_at=run_at,
        )
        db.add(product_row)
        await db.flush()
        db.add(
            CollectionTaskCandidate(
                task_id=task.id,
                product_id=1,
                user_id=1,
                global_influencer_id=global_profile.id,
                product_influencer_id=product_row.id,
                username=global_profile.username or "",
                profile_url=global_profile.profile_url or "",
                platform=global_profile.platform or "instagram",
                followers_count=global_profile.followers_count,
                engagement_rate=global_profile.engagement_rate,
                is_high_value=True,
                has_email=True,
                status=CandidateStatus.INSERTED.value,
                run_at=run_at,
            )
        )
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_collection_auto_outreach_creates_campaign_generates_and_sends_due_email_once():
    async with async_session_factory() as db:
        task = await _create_task_with_inserted_candidate(db)
        ctx = TenantContext(user_id=task.user_id, product_id=task.product_id, workspace_id=1, is_admin=False)

        sent_messages: list[tuple[str, list[str]]] = []

        async def _capture_send(message, recipients, smtp_account=None):
            sent_messages.append((message["Subject"], list(recipients)))

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation()),
        ) as generate, patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(side_effect=_capture_send),
        ):
            result = await CollectionAutoOutreachService.create_campaign_and_queue(
                db,
                task,
                ctx=ctx,
            )

        assert result["created"] is True
        assert result["queued"] == 1
        assert result["processed"] == 1
        assert result["sent"] == 1
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert generate.await_count == 1
        assert len(sent_messages) == 1
        assert task.run_checkpoint["auto_outreach_campaign_id"] == result["campaign_id"]
        assert task.run_checkpoint["auto_outreach_status"] == "sent"
        assert task.run_checkpoint["auto_outreach_sent"] == 1

        campaign = await db.scalar(
            select(OutreachEmailCampaign).where(OutreachEmailCampaign.id == result["campaign_id"])
        )
        assert campaign is not None
        assert campaign.daily_limit == 25
        assert campaign.allow_resend is False
        assert campaign.status == "running"
        assert campaign.message_template_id is not None
        template = await db.get(MessageTemplate, campaign.message_template_id)
        assert template is not None
        assert template.generation_rules["required_content"] == []

        queue_rows = (
            await db.scalars(
                select(OutreachSendQueueItem).where(OutreachSendQueueItem.campaign_id == campaign.id)
            )
        ).all()
        assert len(queue_rows) == 1
        assert queue_rows[0].subject == "Personalized subject"
        assert queue_rows[0].body == "Personalized body"
        assert queue_rows[0].status == "sent"

        second = await CollectionAutoOutreachService.create_campaign_and_queue(db, task, ctx=ctx)
        assert second["created"] is False
        assert second["campaign_id"] == result["campaign_id"]
        assert second["sent"] == 1


@pytest.mark.asyncio
async def test_collection_auto_outreach_spreads_queue_by_hourly_limit_and_interval():
    async with async_session_factory() as db:
        task = await _create_task_with_inserted_candidate(db, candidate_count=3)
        ctx = TenantContext(user_id=task.user_id, product_id=task.product_id, workspace_id=1, is_admin=False)

        sent_messages: list[str] = []

        async def _capture_send(message, recipients, smtp_account=None):
            sent_messages.extend(recipients)

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation()),
        ), patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(side_effect=_capture_send),
        ):
            result = await CollectionAutoOutreachService.create_campaign_and_queue(
                db,
                task,
                ctx=ctx,
            )

        queue_rows = (
            await db.scalars(
                select(OutreachSendQueueItem)
                .where(OutreachSendQueueItem.campaign_id == result["campaign_id"])
                .order_by(OutreachSendQueueItem.scheduled_at.asc(), OutreachSendQueueItem.id.asc())
            )
        ).all()

        assert len(queue_rows) == 3
        assert result["sent"] == 1
        assert len(sent_messages) == 1
        assert queue_rows[0].status == "sent"
        assert queue_rows[1].status == "scheduled"
        assert queue_rows[2].status == "scheduled"
        assert queue_rows[1].scheduled_at > queue_rows[0].scheduled_at
        assert queue_rows[2].scheduled_at > queue_rows[1].scheduled_at
        assert (queue_rows[1].scheduled_at - queue_rows[0].scheduled_at).total_seconds() >= 8 * 60


@pytest.mark.asyncio
async def test_collection_auto_outreach_uses_inserted_candidates_without_country_category_refilter():
    async with async_session_factory() as db:
        task = await _create_task_with_inserted_candidate(
            db,
            task_country="DE",
            task_category="Beauty & Personal Care›Tools & Accessories›Bags & Cases›Travel Cases",
            influencer_country="US",
            influencer_category="Tools & Accessories›Bags & Cases›Travel Cases",
        )
        ctx = TenantContext(user_id=task.user_id, product_id=task.product_id, workspace_id=1, is_admin=False)

        sent_messages: list[str] = []

        async def _capture_send(message, recipients, smtp_account=None):
            del message, smtp_account
            sent_messages.extend(recipients)

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation()),
        ), patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(side_effect=_capture_send),
        ):
            result = await CollectionAutoOutreachService.create_campaign_and_queue(
                db,
                task,
                ctx=ctx,
            )

        assert result["status"] == "sent"
        assert result["queued"] == 1
        assert result["sent"] == 1
        assert len(sent_messages) == 1


