"""Monthly report dashboard aggregation tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.enums import CollectionTaskStatus, EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_campaign_recipient import OutreachCampaignRecipient
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product, User, Workspace, WorkspaceMember
from app.services.dashboard import DashboardService


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _create_product_influencer(
    db,
    *,
    suffix: str,
    email: str | None,
    score: float | None = 80,
    product_fit: float | None = 80,
    roi_forecast: float | None = 3.0,
    product_id: int = 1,
) -> ProductInfluencer:
    now = datetime(2026, 6, 8, tzinfo=UTC)
    profile = GlobalInfluencerProfile(
        platform="instagram",
        platform_unique_id=f"monthly_{suffix}",
        username=f"monthly_{suffix}",
        normalized_username=f"monthly_{suffix}",
        profile_url=f"https://instagram.com/monthly_{suffix}",
        normalized_profile_url=f"https://instagram.com/monthly_{suffix}",
        final_email=email,
        created_at=now,
        updated_at=now,
    )
    db.add(profile)
    await db.flush()
    product = ProductInfluencer(
        product_id=product_id,
        global_influencer_id=profile.id,
        score=score,
        product_fit=product_fit,
        roi_forecast=roi_forecast,
        is_inserted=True,
        created_at=now,
        updated_at=now,
    )
    db.add(product)
    await db.flush()
    return product


async def _create_product_scope(db, *, suffix: str) -> tuple[int, int, int]:
    user = User(username=f"monthly_user_{suffix}", display_name="Monthly User")
    workspace = Workspace(name=f"Monthly Workspace {suffix}", slug=f"monthly-workspace-{suffix}")
    db.add_all([user, workspace])
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    product = Product(
        workspace_id=workspace.id,
        name=f"Monthly Product {suffix}",
        slug=f"monthly-product-{suffix}",
        is_default=True,
    )
    db.add(product)
    await db.flush()
    return user.id, workspace.id, product.id


@pytest.mark.asyncio
async def test_monthly_report_uses_month_scoped_outreach_data():
    suffix = _suffix()
    june = datetime(2026, 6, 10, tzinfo=UTC)
    may = datetime(2026, 5, 20, tzinfo=UTC)
    async with async_session_factory() as db:
        user_id, workspace_id, product_id = await _create_product_scope(db, suffix=suffix)
        high = await _create_product_influencer(
            db,
            suffix=f"high_{suffix}",
            email=f"high_{suffix}@example.com",
            score=88,
            product_fit=82,
            roi_forecast=4.0,
            product_id=product_id,
        )
        normal = await _create_product_influencer(
            db,
            suffix=f"normal_{suffix}",
            email=f"normal_{suffix}@example.com",
            score=45,
            product_fit=50,
            roi_forecast=2.0,
            product_id=product_id,
        )
        missing = await _create_product_influencer(
            db,
            suffix=f"missing_{suffix}",
            email=None,
            score=78,
            product_fit=72,
            roi_forecast=3.0,
            product_id=product_id,
        )
        old = await _create_product_influencer(
            db,
            suffix=f"old_{suffix}",
            email=f"old_{suffix}@example.com",
            score=90,
            product_fit=90,
            roi_forecast=9.0,
            product_id=product_id,
        )
        campaign = OutreachEmailCampaign(
            product_id=product_id,
            user_id=user_id,
            name=f"June campaign {suffix}",
            status="active",
            total_count=3,
            previewed_at=june,
            created_at=june,
            updated_at=june,
        )
        old_campaign = OutreachEmailCampaign(
            product_id=product_id,
            user_id=user_id,
            name=f"May campaign {suffix}",
            status="active",
            total_count=1,
            previewed_at=may,
            created_at=may,
            updated_at=may,
        )
        db.add_all([campaign, old_campaign])
        await db.flush()
        db.add_all(
            [
                OutreachCampaignRecipient(
                    campaign_id=campaign.id,
                    product_influencer_id=high.id,
                    recipient=f"high_{suffix}@example.com",
                    subject="Hi",
                    body="Body",
                    draft_status="pending_review",
                    is_high_value=True,
                    approval_block_reason="high_value_requires_open",
                    previewed_at=june,
                    created_at=june,
                    updated_at=june,
                ),
                OutreachCampaignRecipient(
                    campaign_id=campaign.id,
                    product_influencer_id=normal.id,
                    recipient=f"normal_{suffix}@example.com",
                    subject="Hi",
                    body="Edited body",
                    draft_status="modified",
                    opened_at=june,
                    previewed_at=june,
                    created_at=june,
                    updated_at=june,
                ),
                OutreachCampaignRecipient(
                    campaign_id=campaign.id,
                    product_influencer_id=missing.id,
                    draft_status="skipped",
                    skip_reason="缺邮箱，无法发送",
                    skipped_at=june,
                    previewed_at=june,
                    created_at=june,
                    updated_at=june,
                ),
                OutreachCampaignRecipient(
                    campaign_id=old_campaign.id,
                    product_influencer_id=old.id,
                    recipient=f"old_{suffix}@example.com",
                    draft_status="approved",
                    approved_at=may,
                    previewed_at=may,
                    created_at=may,
                    updated_at=may,
                ),
            ]
        )
        db.add_all(
            [
                OutreachSendQueueItem(
                    product_id=product_id,
                    user_id=user_id,
                    product_influencer_id=normal.id,
                    recipient=f"normal_{suffix}@example.com",
                    subject="Hi",
                    body="Body",
                    status="sent",
                    campaign_id=campaign.id,
                    created_at=june,
                    scheduled_at=june,
                    sent_at=june,
                    updated_at=june,
                ),
                OutreachSendQueueItem(
                    product_id=product_id,
                    user_id=user_id,
                    product_influencer_id=missing.id,
                    recipient=f"missing_{suffix}@example.com",
                    subject="Hi",
                    body="Body",
                    status="failed",
                    campaign_id=campaign.id,
                    created_at=june,
                    scheduled_at=june,
                    failed_at=june,
                    updated_at=june,
                ),
            ]
        )
        db.add_all(
            [
                EmailLog(
                    product_id=product_id,
                    user_id=user_id,
                    product_influencer_id=normal.id,
                    sender_email="sender@example.com",
                    influencer_username=f"normal_{suffix}",
                    recipients=[f"normal_{suffix}@example.com"],
                    subject="Hi",
                    status=EmailLogStatus.SENT.value,
                    sent_at=june,
                    has_replied=True,
                    replied_at=june,
                ),
                EmailReply(
                    product_id=product_id,
                    user_id=user_id,
                    product_influencer_id=normal.id,
                    campaign_id=campaign.id,
                    intent_status="interested",
                    processing_status="unprocessed",
                    from_address=f"normal_{suffix}@example.com",
                    to_address="sender@example.com",
                    subject="Re: Hi",
                    body="Interested",
                    received_at=june,
                    created_at=june,
                ),
                CollectionTask(
                    product_id=product_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    name=f"June task {suffix}",
                    platform="instagram",
                    platforms=["instagram"],
                    keywords=["camera"],
                    status=CollectionTaskStatus.COMPLETED.value,
                    created_at=june,
                    updated_at=june,
                ),
            ]
        )
        await db.commit()

        report = await DashboardService.get_monthly_report(db, product_id=product_id, month="2026-06")

    assert report.month == "2026-06"
    assert report.overview.cards[0].label == "Instagram 达人数"
    assert report.overview.cards[0].value == "4"
    assert report.overview.cards[1].href == "/influencers?has_email=true"
    assert report.outreach_recap.funnel[0].label == "AI 生成草稿"
    assert report.outreach_recap.funnel[0].value == 3
    assert {step.label: step.value for step in report.outreach_recap.funnel}["已发送"] == 1
    assert {step.label: step.value for step in report.outreach_recap.funnel}["有合作意向"] == 1
    assert {card.label: card.value for card in report.draft_quality.cards}["高价值待确认"] == "1"
    assert {card.label: card.value for card in report.queue_performance.cards}["发送失败数"] == "1"
    missing_reason = next(item for item in report.skip_reasons.items if item.label == "缺邮箱")
    assert missing_reason.value == 1
    assert missing_reason.href == "/influencers?missing_contact=true"
    assert report.todos[0].title.startswith("1 个高价值草稿未确认")
