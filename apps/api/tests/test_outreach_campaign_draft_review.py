"""Draft review workflow tests for outreach campaigns."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.deps.tenant import TenantContext
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_campaign_recipient import OutreachCampaignRecipient
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.schemas.outreach_campaign import (
    OutreachCampaignBulkApproveRequest,
    OutreachCampaignCreateRequest,
    OutreachCampaignDraftUpdateRequest,
    OutreachCampaignQueueRequest,
)
from app.schemas.outreach_email import OutreachEmailGenerationResult
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services.outreach_campaign_service import OutreachCampaignService


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _mock_generation(subject: str = "Hello", body: str = "Body text") -> OutreachEmailGenerationResult:
    return OutreachEmailGenerationResult(
        subject=subject,
        body=body,
        recommended_script_title="AI draft",
        reason="fit reason",
        matched_knowledge=[],
    )


async def _create_influencer(
    db,
    *,
    suffix: str,
    email: str | None,
    score: float | None = None,
    product_fit: float | None = None,
    final_priority: str | None = None,
) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    item = CollectedInfluencer(
        platform="instagram",
        username=f"draft_{suffix}",
        profile_url=f"https://instagram.com/draft_{suffix}",
        platform_unique_id=f"ig_draft_{suffix}",
        followers_count=15000,
        engagement_rate=2.5,
        bio="creator open for collab",
        final_email=email,
    )
    global_profile = create_global_profile_from_collected(item, run_at=run_at)
    db.add(global_profile)
    await db.flush()
    record = create_product_influencer_from_collected(
        product_id=1,
        global_profile=global_profile,
        data=item,
        task=None,
        run_at=run_at,
    )
    record.score = score
    record.product_fit = product_fit
    record.final_priority = final_priority
    db.add(record)
    await db.flush()
    return record


async def _create_campaign(db, *, ctx: TenantContext, influencer_ids: list[int]):
    created = await OutreachCampaignService.create_campaign(
        db,
        ctx=ctx,
        payload=OutreachCampaignCreateRequest(
            name=f"Draft review {_suffix()}",
            influencer_ids=influencer_ids,
            send_window_start="00:00",
            send_window_end="23:59",
        ),
    )
    return created


@pytest.mark.asyncio
async def test_preview_saves_reviewable_draft_status_and_high_value_guard():
    suffix = _suffix()
    async with async_session_factory() as db:
        high = await _create_influencer(
            db,
            suffix=f"high_{suffix}",
            email=f"high_{suffix}@example.com",
            score=80,
        )
        normal = await _create_influencer(
            db,
            suffix=f"normal_{suffix}",
            email=f"normal_{suffix}@example.com",
            score=10,
        )
        missing = await _create_influencer(db, suffix=f"missing_{suffix}", email=None)
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[high.id, normal.id, missing.id])

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation()),
        ):
            preview = await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )

        by_id = {item.influencer_id: item for item in preview.items}
        assert by_id[high.id].draft_status == "pending_review"
        assert by_id[high.id].is_high_value is True
        assert by_id[high.id].approval_block_reason == "high_value_requires_open"
        assert by_id[normal.id].draft_status == "pending_review"
        assert by_id[normal.id].is_high_value is False
        assert by_id[missing.id].draft_status == "skipped"
        assert by_id[missing.id].skip_reason

        rec = await db.scalar(
            select(OutreachCampaignRecipient).where(
                OutreachCampaignRecipient.campaign_id == campaign.id,
                OutreachCampaignRecipient.product_influencer_id == high.id,
            )
        )
        assert rec is not None
        assert rec.draft_status == "pending_review"
        assert rec.is_high_value is True
        assert rec.opened_at is None


@pytest.mark.asyncio
async def test_high_value_must_be_opened_before_approval_but_normal_can_bulk_approve():
    suffix = _suffix()
    async with async_session_factory() as db:
        high = await _create_influencer(
            db,
            suffix=f"guard_{suffix}",
            email=f"guard_{suffix}@example.com",
            final_priority="P1",
        )
        normal = await _create_influencer(
            db,
            suffix=f"bulk_{suffix}",
            email=f"bulk_{suffix}@example.com",
            score=10,
        )
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[high.id, normal.id])

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation()),
        ):
            await OutreachCampaignService.preview_campaign(db, product_id=1, campaign_id=campaign.id)

        bulk = await OutreachCampaignService.bulk_approve_campaign_drafts(
            db,
            product_id=1,
            campaign_id=campaign.id,
            payload=OutreachCampaignBulkApproveRequest(confirm=True),
        )
        assert bulk.approved == 1
        assert bulk.skipped == 1

        high_rec = await OutreachCampaignService.approve_campaign_draft(
            db,
            product_id=1,
            campaign_id=campaign.id,
            influencer_id=high.id,
        )
        assert high_rec.draft_status == "pending_review"
        assert high_rec.approval_block_reason == "high_value_requires_open"

        opened = await OutreachCampaignService.open_campaign_draft(
            db,
            product_id=1,
            campaign_id=campaign.id,
            influencer_id=high.id,
        )
        assert opened.opened_at is not None

        approved = await OutreachCampaignService.approve_campaign_draft(
            db,
            product_id=1,
            campaign_id=campaign.id,
            influencer_id=high.id,
        )
        assert approved.draft_status == "approved"
        assert approved.approval_block_reason is None


@pytest.mark.asyncio
async def test_edit_skip_regenerate_and_queue_only_approved_drafts():
    suffix = _suffix()
    async with async_session_factory() as db:
        a = await _create_influencer(db, suffix=f"a_{suffix}", email=f"a_{suffix}@example.com", score=10)
        b = await _create_influencer(db, suffix=f"b_{suffix}", email=f"b_{suffix}@example.com", score=10)
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[a.id, b.id])

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation()),
        ):
            await OutreachCampaignService.preview_campaign(db, product_id=1, campaign_id=campaign.id)

        edited = await OutreachCampaignService.update_campaign_draft(
            db,
            product_id=1,
            campaign_id=campaign.id,
            influencer_id=a.id,
            payload=OutreachCampaignDraftUpdateRequest(subject="Edited subject", body="Edited body"),
        )
        assert edited.draft_status == "modified"
        assert edited.subject == "Edited subject"
        assert edited.body == "Edited body"

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation(subject="Regenerated", body="Fresh body")),
        ):
            regenerated = await OutreachCampaignService.regenerate_campaign_draft(
                db,
                product_id=1,
                campaign_id=campaign.id,
                influencer_id=a.id,
            )
        assert regenerated.draft_status == "modified"
        assert regenerated.subject == "Regenerated"

        skipped = await OutreachCampaignService.skip_campaign_draft(
            db,
            product_id=1,
            campaign_id=campaign.id,
            influencer_id=b.id,
        )
        assert skipped.draft_status == "skipped"

        await OutreachCampaignService.approve_campaign_draft(
            db,
            product_id=1,
            campaign_id=campaign.id,
            influencer_id=a.id,
        )
        result = await OutreachCampaignService.queue_campaign(
            db,
            ctx=ctx,
            campaign_id=campaign.id,
            payload=OutreachCampaignQueueRequest(confirm=True),
        )
        assert result.queued == 1
        assert result.skipped == 1

        queue_row = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id,
                OutreachSendQueueItem.product_influencer_id == a.id,
            )
        )
        assert queue_row is not None
        assert queue_row.subject == "Regenerated"

        rows = (
            await db.scalars(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).all()
        statuses = {row.product_influencer_id: row.draft_status for row in rows}
        assert statuses[a.id] == "queued"
        assert statuses[b.id] == "skipped"
