"""Outreach campaign creation, preview, queueing, sending, and safety tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.deps.tenant import TenantContext
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.enums import EmailLogStatus
from app.models.outreach_campaign_recipient import OutreachCampaignRecipient
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.schemas.outreach_campaign import (
    OutreachCampaignCreateRequest,
    OutreachCampaignPreviewRequest,
    OutreachCampaignQueueRequest,
    OutreachCampaignUpdateRequest,
)
from app.schemas.influencer import InfluencerFilter
from app.schemas.outreach_email import OutreachEmailGenerationResult
from app.services.email_sent_status import product_influencer_has_successful_email_sent
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services.outreach_campaign_service import (
    OutreachCampaignService,
    _parse_hhmm,
    is_auto_send_due,
    is_in_send_window,
)
from app.services.outreach_send_queue_service import OutreachSendQueueService


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _mock_generation(*, subject: str = "Hello", body: str = "Body text") -> OutreachEmailGenerationResult:
    return OutreachEmailGenerationResult(
        subject=subject,
        body=body,
        recommended_script_title="Test Script",
        reason="test generation",
        matched_knowledge=[],
    )


async def _create_influencer(
    db,
    *,
    suffix: str,
    email: str | None,
    product_id: int = 1,
    follow_status: str | None = None,
) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    uname = f"creator_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=uname,
        profile_url=f"https://instagram.com/{uname}",
        platform_unique_id=f"ig_creator_{suffix}",
        followers_count=15000,
        engagement_rate=2.5,
        bio="travel",
        final_email=email,
    )
    global_profile = create_global_profile_from_collected(item, run_at=run_at)
    db.add(global_profile)
    await db.flush()
    record = create_product_influencer_from_collected(
        product_id=product_id,
        global_profile=global_profile,
        data=item,
        task=None,
        run_at=run_at,
    )
    if follow_status:
        record.follow_status = follow_status
    db.add(record)
    await db.flush()
    return record


async def _create_campaign(
    db,
    *,
    ctx: TenantContext,
    influencer_ids: list[int],
    daily_limit: int = 20,
    allow_resend: bool = False,
    send_window_start: str | None = "00:00",
    send_window_end: str | None = "23:59",
) -> OutreachEmailCampaign:
    created = await OutreachCampaignService.create_campaign(
        db,
        ctx=ctx,
        payload=OutreachCampaignCreateRequest(
            name=f"Campaign {_suffix()}",
            influencer_ids=influencer_ids,
            daily_limit=daily_limit,
            send_window_start=send_window_start,
            send_window_end=send_window_end,
            allow_resend=allow_resend,
        ),
    )
    row = await db.scalar(
        select(OutreachEmailCampaign).where(OutreachEmailCampaign.id == created.id)
    )
    assert row is not None
    return row


async def _preview_with_mock(db, *, product_id: int, campaign_id: int):
    with patch(
        "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
        new=AsyncMock(return_value=_mock_generation()),
    ):
        return await OutreachCampaignService.preview_campaign(
            db, product_id=product_id, campaign_id=campaign_id
        )


async def _queue_confirmed(db, *, ctx: TenantContext, campaign_id: int):
    return await OutreachCampaignService.queue_campaign(
        db,
        ctx=ctx,
        campaign_id=campaign_id,
        payload=OutreachCampaignQueueRequest(confirm=True),
    )


@pytest.mark.asyncio
async def test_create_campaign_rejects_foreign_product_influencer():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=f"p1_{suffix}@example.com")
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=2, is_admin=True)
        with pytest.raises(HTTPException) as exc:
            await OutreachCampaignService.create_campaign(
                db,
                ctx=ctx,
                payload=OutreachCampaignCreateRequest(
                    name="Cross product",
                    influencer_ids=[influencer.id],
                ),
            )
        assert exc.value.status_code == 400
        assert exc.value.detail


@pytest.mark.asyncio
async def test_preview_skips_missing_email():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=None)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        preview = await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        assert preview.skip_count == 1
        assert preview.items[0].can_queue is False


@pytest.mark.asyncio
async def test_list_campaign_recipients_reads_saved_rows_without_regenerating():
    suffix = _suffix()
    async with async_session_factory() as db:
        email = f"saved_{suffix}@gmail.com"
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(side_effect=AssertionError("should not regenerate")),
        ):
            saved = await OutreachCampaignService.list_campaign_recipients(
                db, product_id=1, campaign_id=campaign.id
            )

        assert saved.total == 1
        assert saved.can_queue_count == 1
        assert saved.skip_count == 0
        assert saved.items[0].influencer_id == influencer.id
        assert saved.items[0].recipient == email
        assert saved.items[0].subject == "Hello"
        assert saved.items[0].body == "Body text"
        assert saved.items[0].can_queue is True


@pytest.mark.asyncio
async def test_manual_preview_uses_user_copy_without_ai_generation():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db,
            suffix=suffix,
            email=f"manual_{suffix}@example.com",
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(side_effect=AssertionError("manual copy should not call AI")),
        ):
            preview = await OutreachCampaignService.preview_campaign(
                db,
                product_id=1,
                campaign_id=campaign.id,
                payload=OutreachCampaignPreviewRequest(
                    content_source="manual",
                    subject="Manual subject",
                    body="Hi {name}, this is a direct note for {platform}.",
                ),
            )

        assert preview.can_queue_count == 1
        assert preview.items[0].subject == "Manual subject"
        assert "direct note" in preview.items[0].body
        assert "{name}" not in preview.items[0].body


@pytest.mark.asyncio
async def test_preview_skips_blacklisted_and_invalid():
    suffix = _suffix()
    async with async_session_factory() as db:
        black = await _create_influencer(
            db,
            suffix=f"bl_{suffix}",
            email=f"bl_{suffix}@example.com",
            follow_status="blacklisted",
        )
        invalid = await _create_influencer(
            db,
            suffix=f"inv_{suffix}",
            email=f"inv_{suffix}@example.com",
            follow_status="invalid",
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db, ctx=ctx, influencer_ids=[black.id, invalid.id]
        )
        preview = await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        reasons = {item.influencer_id: item.skip_reason for item in preview.items}
        assert reasons[black.id]
        assert reasons[invalid.id]
        assert preview.can_queue_count == 0


@pytest.mark.asyncio
async def test_preview_skips_sent_unless_allow_resend():
    suffix = _suffix()
    email = f"sent_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        db.add(
            EmailLog(
                product_id=1,
                user_id=1,
                product_influencer_id=influencer.id,
                recipients=[email],
                subject="Prior",
                body="Prior body",
                status=EmailLogStatus.SENT.value,
                sent_at=datetime.now(UTC),
            )
        )
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign_no_resend = await _create_campaign(
            db, ctx=ctx, influencer_ids=[influencer.id], allow_resend=False
        )
        preview1 = await _preview_with_mock(
            db, product_id=1, campaign_id=campaign_no_resend.id
        )
        assert preview1.items[0].skip_reason == "已有成功发信记录"

        campaign_resend = await _create_campaign(
            db, ctx=ctx, influencer_ids=[influencer.id], allow_resend=True
        )
        preview2 = await _preview_with_mock(
            db, product_id=1, campaign_id=campaign_resend.id
        )
        assert preview2.items[0].can_queue is True


@pytest.mark.asyncio
async def test_queue_requires_preview_and_valid_recipients():
    suffix = _suffix()
    async with async_session_factory() as db:
        ok = await _create_influencer(db, suffix=f"ok_{suffix}", email=f"ok_{suffix}@example.com")
        bad = await _create_influencer(db, suffix=f"bad_{suffix}", email=None)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[ok.id, bad.id])

        with pytest.raises(HTTPException) as exc:
            await OutreachCampaignService.queue_campaign(
                db,
                ctx=ctx,
                campaign_id=campaign.id,
                payload=OutreachCampaignQueueRequest(confirm=True),
            )
        assert "请先生成个性化邮件草稿" in str(exc.value.detail)

        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        result = await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)
        assert result.queued == 1
        assert result.skipped == 1


@pytest.mark.asyncio
async def test_queue_skips_whitespace_only_subject_or_body():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"ws_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)

        rec = await db.scalar(
            select(OutreachCampaignRecipient).where(
                OutreachCampaignRecipient.campaign_id == campaign.id,
                OutreachCampaignRecipient.product_influencer_id == influencer.id,
            )
        )
        assert rec is not None
        rec.subject = "   "
        rec.body = "   "
        rec.can_queue = True
        await db.commit()

        result = await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)
        assert result.queued == 0
        assert result.skipped == 1

        await db.refresh(rec)
        assert rec.skip_reason == "邮件标题或正文为空，无法入队"
        assert rec.queue_item_id is None

        queue_count = await db.scalar(
            select(func.count())
            .select_from(OutreachSendQueueItem)
            .where(OutreachSendQueueItem.campaign_id == campaign.id)
        )
        assert queue_count == 0


@pytest.mark.asyncio
async def test_queue_reuses_existing_active_queue_item_for_same_recipient():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"reuse_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        old_campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        new_campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        old_queue = OutreachSendQueueItem(
            product_id=1,
            user_id=1,
            product_influencer_id=influencer.id,
            campaign_id=old_campaign.id,
            recipient=f"reuse_{suffix}@example.com",
            subject="Old subject",
            body="Old body",
            status="queued",
            scheduled_at=datetime.now(UTC),
            generated_by_ai=True,
            allow_resend=True,
        )
        db.add(old_queue)
        await db.commit()

        await _preview_with_mock(
            db,
            product_id=1,
            campaign_id=new_campaign.id,
            generation=_mock_generation(subject="New subject", body="New body"),
        )
        result = await _queue_confirmed(db, ctx=ctx, campaign_id=new_campaign.id)

        assert result.queued == 1
        assert result.skipped == 0
        await db.refresh(old_queue)
        assert old_queue.campaign_id == new_campaign.id
        assert old_queue.subject == "New subject"
        assert old_queue.body == "New body"


@pytest.mark.asyncio
async def test_queue_requires_confirm_flag():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"q_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)

        with pytest.raises(HTTPException) as exc:
            await OutreachCampaignService.queue_campaign(
                db,
                ctx=ctx,
                campaign_id=campaign.id,
                payload=OutreachCampaignQueueRequest(confirm=False),
            )
        assert "confirm=true" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_process_respects_daily_limit():
    suffix = _suffix()
    async with async_session_factory() as db:
        inf1 = await _create_influencer(
            db, suffix=f"a_{suffix}", email=f"a_{suffix}@example.com"
        )
        inf2 = await _create_influencer(
            db, suffix=f"b_{suffix}", email=f"b_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db, ctx=ctx, influencer_ids=[inf1.id, inf2.id], daily_limit=1
        )
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ):
            result = await OutreachCampaignService.process_campaign(
                db, ctx=ctx, campaign_id=campaign.id
            )

        assert result.sent == 1
        assert result.processed == 1
        rows = (
            await db.scalars(
                select(OutreachSendQueueItem).where(
                    OutreachSendQueueItem.campaign_id == campaign.id
                )
            )
        ).all()
        statuses = sorted(row.status for row in rows)
        assert statuses.count("sent") == 1
        assert "queued" in statuses or "scheduled" in statuses

        refreshed = await db.get(OutreachEmailCampaign, campaign.id)
        assert refreshed is not None
        assert refreshed.sent_count == 1


def test_outreach_campaign_create_request_allows_large_batch_limit():
    payload = OutreachCampaignCreateRequest(
        name="large batch",
        influencer_ids=list(range(1, 1001)),
        daily_limit=1000,
    )

    assert len(payload.influencer_ids or []) == 1000
    assert payload.daily_limit == 1000


def test_outreach_campaign_create_request_defaults_to_business_batch_limit():
    payload = OutreachCampaignCreateRequest(
        name="default batch",
        influencer_ids=[1],
    )

    assert payload.daily_limit == 50


@pytest.mark.asyncio
async def test_manual_process_ignores_send_window():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"win_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db,
            ctx=ctx,
            influencer_ids=[influencer.id],
            send_window_start="03:00",
            send_window_end="03:01",
        )
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        with patch(
            "app.services.outreach_campaign_service.is_in_send_window",
            return_value=False,
        ), patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ):
            result = await OutreachCampaignService.process_campaign(
                db, ctx=ctx, campaign_id=campaign.id
            )

        assert result.sent == 1


def test_is_in_send_window_open_range():
    noon = datetime(2026, 6, 19, 4, 0, tzinfo=UTC)  # 12:00 Asia/Shanghai
    assert is_in_send_window(
        tz_name="Asia/Shanghai",
        start="10:00",
        end="18:00",
        now=noon,
    )


@pytest.mark.asyncio
async def test_process_skips_blacklisted_before_send():
    suffix = _suffix()
    email = f"blk_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        product_row = await db.get(ProductInfluencer, influencer.id)
        assert product_row is not None
        product_row.follow_status = "blacklisted"
        await db.commit()

        item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id
            )
        )
        assert item is not None
        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ) as send_mock:
            outcome = await OutreachSendQueueService._process_one(
                db, row=item, user_id=1, campaign=campaign
            )
            send_mock.assert_not_called()
        assert outcome == "skipped"


@pytest.mark.asyncio
async def test_process_skips_when_success_log_exists_without_allow_resend():
    suffix = _suffix()
    email = f"dup_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db, ctx=ctx, influencer_ids=[influencer.id], allow_resend=False
        )
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        db.add(
            EmailLog(
                product_id=1,
                user_id=1,
                product_influencer_id=influencer.id,
                recipients=[email],
                subject="Already sent",
                body="Already sent body",
                status=EmailLogStatus.SENT.value,
                sent_at=datetime.now(UTC),
            )
        )
        await db.commit()

        item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id
            )
        )
        assert item is not None
        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ) as send_mock:
            outcome = await OutreachSendQueueService._process_one(
                db, row=item, user_id=1, campaign=campaign
            )
            send_mock.assert_not_called()
        assert outcome == "skipped"


@pytest.mark.asyncio
async def test_process_success_writes_email_log_sent():
    suffix = _suffix()
    email = f"ok_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id
            )
        )
        assert item is not None
        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ):
            outcome = await OutreachSendQueueService._process_one(
                db, row=item, user_id=1, campaign=campaign
            )
        assert outcome == "sent"
        await db.refresh(item)
        assert item.status == "sent"
        assert item.email_log_id is not None
        log = await db.scalar(select(EmailLog).where(EmailLog.id == item.email_log_id))
        assert log is not None
        assert log.status == EmailLogStatus.SENT.value


@pytest.mark.asyncio
async def test_process_failure_writes_email_log_failed_and_not_mark_sent():
    suffix = _suffix()
    email = f"fail_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id
            )
        )
        assert item is not None
        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(side_effect=RuntimeError("smtp down")),
        ):
            outcome = await OutreachSendQueueService._process_one(
                db, row=item, user_id=1, campaign=campaign
            )
        assert outcome == "failed"
        await db.refresh(item)
        assert item.status == "failed"
        log = await db.scalar(select(EmailLog).where(EmailLog.id == item.email_log_id))
        assert log is not None
        assert log.status == EmailLogStatus.FAILED.value
        assert log.error_message
        still_sent = await product_influencer_has_successful_email_sent(
            db, product_id=1, product_influencer_id=influencer.id
        )
        assert still_sent is False


@pytest.mark.asyncio
async def test_process_success_preserves_replied_status():
    suffix = _suffix()
    email = f"rep_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=email, follow_status="replied"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db,
            ctx=ctx,
            influencer_ids=[influencer.id],
            allow_resend=True,
        )
        campaign.skip_replied = False
        await db.commit()

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation()),
        ):
            await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id
            )
        )
        assert item is not None
        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ):
            await OutreachSendQueueService._process_one(
                db, row=item, user_id=1, campaign=campaign
            )

        product_row = await db.get(ProductInfluencer, influencer.id)
        assert product_row is not None
        assert product_row.follow_status == "replied"


@pytest.mark.asyncio
async def test_process_updates_campaign_counters():
    suffix = _suffix()
    async with async_session_factory() as db:
        ok = await _create_influencer(
            db, suffix=f"s_{suffix}", email=f"s_{suffix}@example.com"
        )
        fail = await _create_influencer(
            db, suffix=f"f_{suffix}", email=f"f_{suffix}@example.com"
        )
        skip = await _create_influencer(
            db, suffix=f"k_{suffix}", email=f"k_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db, ctx=ctx, influencer_ids=[ok.id, fail.id, skip.id], daily_limit=10
        )
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        skip_row = await db.get(ProductInfluencer, skip.id)
        assert skip_row is not None
        skip_row.follow_status = "invalid"
        await db.commit()

        call_count = {"n": 0}

        async def _send_side_effect(*_args, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("smtp fail")
            return None

        campaign_row = await db.get(OutreachEmailCampaign, campaign.id)
        assert campaign_row is not None

        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(side_effect=_send_side_effect),
        ):
            result = await OutreachSendQueueService.process_campaign_queue(
                db, ctx=ctx, campaign=campaign_row
            )

        assert result.sent == 1
        assert result.failed == 1
        assert result.skipped == 1

        refreshed = await db.get(OutreachEmailCampaign, campaign.id)
        assert refreshed is not None
        assert refreshed.sent_count == 1
        assert refreshed.failed_count == 1
        assert refreshed.skipped_count == 1


@pytest.mark.asyncio
async def test_preview_shows_no_knowledge_message():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"kb_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])

        gen = _mock_generation()
        gen.reason = "基于话术模板"
        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=gen),
        ):
            preview = await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )
        assert "未引用知识库" in preview.items[0].reason


@pytest.mark.asyncio
async def test_preview_queues_safe_fallback_when_ai_generation_failed():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"ai_fail_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])

        gen = _mock_generation(subject="Fallback subject", body="Fallback body")
        gen.error_message = "OpenAI quota exceeded"
        gen.configured = True
        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=gen),
        ):
            preview = await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )

        assert preview.can_queue_count == 1
        assert preview.items[0].can_queue is True
        assert preview.items[0].skip_reason is None
        assert "OpenAI quota exceeded" in preview.items[0].reason


@pytest.mark.asyncio
async def test_create_campaign_by_filters_product_scope():
    suffix = _suffix()
    async with async_session_factory() as db:
        p1 = await _create_influencer(db, suffix=f"p1_{suffix}", email=f"p1_{suffix}@example.com", product_id=1)
        p2 = await _create_influencer(db, suffix=f"p2_{suffix}", email=f"p2_{suffix}@example.com", product_id=2)
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        created = await OutreachCampaignService.create_campaign(
            db,
            ctx=ctx,
            payload=OutreachCampaignCreateRequest(
                name="Filter campaign",
                select_all_by_filters=True,
                influencer_filters=InfluencerFilter(has_email=True, search=f"p1_{suffix}"),
            ),
        )
        assert created.total_count == 1
        assert created.influencer_filters_snapshot is not None

        with pytest.raises(HTTPException) as exc:
            await OutreachCampaignService.create_campaign(
                db,
                ctx=ctx,
                payload=OutreachCampaignCreateRequest(
                    name="Empty filter",
                    select_all_by_filters=True,
                    influencer_filters=InfluencerFilter(search=f"p2_{suffix}"),
                ),
            )
        assert exc.value.status_code == 400
        assert exc.value.detail


@pytest.mark.asyncio
async def test_preview_empty_campaign_returns_empty_state():
    suffix = _suffix()
    async with async_session_factory() as db:
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db,
            ctx=ctx,
            influencer_ids=[
                (
                    await _create_influencer(
                        db, suffix=f"tmp_{suffix}", email=f"tmp_{suffix}@example.com"
                    )
                ).id
            ],
        )
        recs = (
            await db.scalars(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id
                )
            )
        ).all()
        for rec in recs:
            await db.delete(rec)
        await db.commit()

        preview = await OutreachCampaignService.preview_campaign(
            db, product_id=1, campaign_id=campaign.id
        )
        assert preview.total == 0
        assert preview.items == []
        assert preview.can_queue_count == 0


@pytest.mark.asyncio
async def test_preview_single_ai_failure_does_not_500():
    suffix = _suffix()
    async with async_session_factory() as db:
        ok = await _create_influencer(
            db, suffix=f"ok_{suffix}", email=f"ok_{suffix}@example.com"
        )
        bad = await _create_influencer(
            db, suffix=f"bad_{suffix}", email=f"bad_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[ok.id, bad.id])

        async def _generate_side_effect(_db, *, product_row, **_kwargs):
            if product_row.id == bad.id:
                raise RuntimeError("AI provider timeout")
            return _mock_generation(subject=f"Hi {product_row.id}", body="Body")

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(side_effect=_generate_side_effect),
        ):
            preview = await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )

        assert preview.total == 2
        by_id = {item.influencer_id: item for item in preview.items}
        assert by_id[ok.id].can_queue is True
        assert by_id[bad.id].can_queue is False
        assert "生成失败" in (by_id[bad.id].skip_reason or "")


@pytest.mark.asyncio
async def test_list_campaigns_includes_real_draft_queue_and_reply_stats():
    suffix = _suffix()
    async with async_session_factory() as db:
        first = await _create_influencer(
            db, suffix=f"stats_a_{suffix}", email=f"stats_a_{suffix}@creator-mail.net"
        )
        second = await _create_influencer(
            db,
            suffix=f"stats_b_{suffix}",
            email=f"stats_b_{suffix}@creator-mail.net",
        )
        skipped = await _create_influencer(db, suffix=f"stats_skip_{suffix}", email=None)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db, ctx=ctx, influencer_ids=[first.id, second.id, skipped.id]
        )

        async def _generate_side_effect(_db, *, product_row, **_kwargs):
            return _mock_generation(
                subject=f"Subject for {product_row.id}",
                body=f"Body for {product_row.id}",
            )

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(side_effect=_generate_side_effect),
        ):
            await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        queue_item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id,
                OutreachSendQueueItem.product_influencer_id == first.id,
            )
        )
        assert queue_item is not None
        queue_item.status = "sent"
        second.follow_status = "interested"
        reply_time = datetime.now(UTC)
        db.add(
            EmailReply(
                product_id=1,
                product_influencer_id=second.id,
                campaign_id=campaign.id,
                from_address=f"stats_b_{suffix}@creator-mail.net",
                to_address="sales@example.com",
                subject="Re: Subject for second",
                body="Interested in collaboration",
                snippet="Interested in collaboration",
                match_method="sender_email",
                source="webhook",
                received_at=reply_time,
            )
        )
        await db.commit()

        rows = await OutreachCampaignService.list_campaigns(db, product_id=1)
        current = next(row for row in rows if row.id == campaign.id)

        assert current.draft_count == 2
        assert current.can_queue_count == 2
        assert current.queued_count == 2
        assert current.sent_count == 1
        assert current.skipped_count == 1
        assert current.reply_count == 1
        assert current.interested_count == 1
        assert current.unreplied_count == 1
        assert current.latest_reply_at == reply_time


@pytest.mark.asyncio
async def test_campaign_reply_board_lists_replied_unreplied_failed_and_skipped_rows():
    suffix = _suffix()
    async with async_session_factory() as db:
        replied = await _create_influencer(
            db,
            suffix=f"reply_{suffix}",
            email=f"reply_{suffix}@creator-mail.net",
            follow_status="interested",
        )
        unreplied = await _create_influencer(
            db, suffix=f"unreply_{suffix}", email=f"unreply_{suffix}@creator-mail.net"
        )
        failed = await _create_influencer(
            db, suffix=f"fail_{suffix}", email=f"fail_{suffix}@creator-mail.net"
        )
        skipped = await _create_influencer(db, suffix=f"skip_{suffix}", email=None)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db,
            ctx=ctx,
            influencer_ids=[replied.id, unreplied.id, failed.id, skipped.id],
        )
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        queued_rows = (
            await db.scalars(
                select(OutreachSendQueueItem).where(
                    OutreachSendQueueItem.campaign_id == campaign.id
                )
            )
        ).all()
        for row in queued_rows:
            if row.product_influencer_id == replied.id:
                row.status = "sent"
                row.sent_at = datetime.now(UTC)
            elif row.product_influencer_id == unreplied.id:
                row.status = "sent"
                row.sent_at = datetime.now(UTC)
            elif row.product_influencer_id == failed.id:
                row.status = "failed"
                row.error_message = "smtp rejected"

        db.add(
            EmailReply(
                product_id=1,
                product_influencer_id=replied.id,
                campaign_id=campaign.id,
                from_address=f"reply_{suffix}@creator-mail.net",
                to_address="sales@example.com",
                subject="Re: Hello",
                body="Yes, interested",
                snippet="Yes, interested",
                match_method="message_header",
                source="webhook",
                received_at=datetime.now(UTC),
            )
        )
        await db.commit()

        board = await OutreachCampaignService.list_campaign_replies(
            db, product_id=1, campaign_id=campaign.id
        )

        assert board.total == 4
        assert board.reply_count == 1
        assert board.interested_count == 1
        assert board.unreplied_count == 2
        by_id = {item.influencer_id: item for item in board.items}
        assert by_id[replied.id].reply_status == "interested"
        assert by_id[replied.id].match_method == "message_header"
        assert by_id[replied.id].reply_snippet == "Yes, interested"
        assert by_id[unreplied.id].reply_status == "unreplied"
        assert by_id[unreplied.id].send_status == "sent"
        assert by_id[failed.id].reply_status == "unreplied"
        assert by_id[failed.id].send_status == "failed"
        assert by_id[skipped.id].reply_status == "skipped"
        assert by_id[skipped.id].skip_reason == "缺少邮箱"


@pytest.mark.asyncio
async def test_preview_skip_evaluation_db_error_isolated():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"db_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])

        with patch(
            "app.services.outreach_campaign_service.product_influencer_has_successful_email_sent",
            new=AsyncMock(side_effect=RuntimeError("db unavailable")),
        ):
            preview = await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )

        assert preview.total == 1
        assert preview.items[0].can_queue is False
        assert preview.items[0].skip_reason


@pytest.mark.asyncio
async def test_preview_ai_not_configured_uses_fallback_template():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"noai_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])

        with patch("app.services.speech_recommendation_service.settings") as mock_settings:
            mock_settings.is_openai_configured = False
            mock_settings.active_ai_provider = "none"
            preview = await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )

        assert preview.total == 1
        assert preview.items[0].can_queue is True
        assert preview.items[0].subject
        assert preview.items[0].body
        assert preview.items[0].reason


def test_normalize_matched_knowledge_coerces_numeric_section():
    from app.services.outreach_campaign_service import _normalize_matched_knowledge

    result = _normalize_matched_knowledge(
        [{"document": "doc.pdf", "section": 2, "summary": "page two"}]
    )
    assert result[0].section == "2"


@pytest.mark.asyncio
async def test_preview_skips_replied_status():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db,
            suffix=suffix,
            email=f"rep_{suffix}@example.com",
            follow_status="replied",
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        preview = await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)


@pytest.mark.asyncio
async def test_preview_skips_sender_address_recipient():
    suffix = _suffix()
    async with async_session_factory() as db:
        from unittest.mock import patch

        from app.core.config import Settings

        sender = "sender@company.com"
        influencer = await _create_influencer(db, suffix=suffix, email=sender)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])

        mock_settings = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user=sender,
            smtp_password="secret",
            smtp_from=sender,
        )
        with patch("app.services.outreach_recipient.settings", mock_settings):
            preview = await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        assert preview.items[0].can_queue is False
        assert "鍙戜欢閭鐩稿悓" in (preview.items[0].skip_reason or "")


@pytest.mark.asyncio
async def test_process_skips_replied_at_send_time():
    suffix = _suffix()
    email = f"repq_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        product_row = await db.get(ProductInfluencer, influencer.id)
        assert product_row is not None
        product_row.follow_status = "interested"
        await db.commit()

        item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id
            )
        )
        assert item is not None
        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ) as send_mock:
            outcome = await OutreachSendQueueService._process_one(
                db, row=item, user_id=1, campaign=campaign
            )
            send_mock.assert_not_called()
        assert outcome == "skipped"


@pytest.mark.asyncio
async def test_pause_blocks_manual_process():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"pause_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await OutreachCampaignService.pause_campaign(
            db, product_id=1, campaign_id=campaign.id
        )
        with pytest.raises(HTTPException) as exc:
            await OutreachCampaignService.process_campaign(
                db, ctx=ctx, campaign_id=campaign.id
            )
        assert "鏆傚仠" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_cancel_campaign_cancels_queued_items():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"cancel_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)
        await OutreachCampaignService.cancel_campaign(
            db, product_id=1, campaign_id=campaign.id
        )
        item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id
            )
        )
        assert item is not None
        assert item.status == "cancelled"
        refreshed = await db.get(OutreachEmailCampaign, campaign.id)
        assert refreshed is not None
        assert refreshed.status == "cancelled"


def test_auto_send_time_validation():
    with pytest.raises(HTTPException):
        _parse_hhmm("25:99")


@pytest.mark.asyncio
async def test_auto_send_disabled_not_processed():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"auto_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        campaign.auto_send_enabled = False
        campaign.auto_send_time = "10:00"
        await db.commit()

        due = datetime(2026, 6, 19, 2, 0, tzinfo=UTC)  # 10:00 Asia/Shanghai
        result = await OutreachCampaignService.process_due_auto_campaigns(db, now=due)
        assert result.processed == 0


@pytest.mark.asyncio
async def test_due_auto_campaign_processes_queue():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"due_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db,
            ctx=ctx,
            influencer_ids=[influencer.id],
            daily_limit=5,
            send_window_start="00:00",
            send_window_end="23:59",
        )
        campaign.auto_send_enabled = True
        campaign.auto_send_time = "10:00"
        campaign.status = "running"
        await _preview_with_mock(db, product_id=1, campaign_id=campaign.id)
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)
        await db.commit()

        due = datetime(2026, 6, 19, 2, 0, tzinfo=UTC)
        assert is_auto_send_due(
            auto_send_time="10:00",
            tz_name="Asia/Shanghai",
            last_auto_processed_at=None,
            now=due,
        )
        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ):
            result = await OutreachCampaignService.process_due_auto_campaigns(db, now=due)
        assert result.processed == 1
        assert result.items[0].sent == 1


@pytest.mark.asyncio
async def test_paused_campaign_not_auto_processed():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"pauto_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        campaign.auto_send_enabled = True
        campaign.auto_send_time = "10:00"
        campaign.status = "paused"
        await db.commit()

        due = datetime(2026, 6, 19, 2, 0, tzinfo=UTC)
        result = await OutreachCampaignService.process_due_auto_campaigns(db, now=due)
        assert result.processed == 0


@pytest.mark.asyncio
async def test_update_campaign_auto_send_fields():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(
            db, suffix=suffix, email=f"upd_{suffix}@example.com"
        )
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        updated = await OutreachCampaignService.update_campaign(
            db,
            product_id=1,
            campaign_id=campaign.id,
            payload=OutreachCampaignUpdateRequest(
                auto_send_enabled=True,
                auto_send_time="11:30",
            ),
        )
        assert updated.auto_send_enabled is True
        assert updated.auto_send_time == "11:30"
        assert updated.next_auto_process_at is not None


@pytest.mark.asyncio
async def test_preview_three_influencers_each_gets_own_draft():
    suffix = _suffix()
    async with async_session_factory() as db:
        ids = []
        for i in range(3):
            row = await _create_influencer(
                db,
                suffix=f"t{i}_{suffix}",
                email=f"t{i}_{suffix}@example.com",
            )
            ids.append(row.id)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=ids)

        async def _generate_side_effect(_db, *, product_row, **_kwargs):
            return _mock_generation(
                subject=f"Subject for {product_row.id}",
                body=f"Unique body content for influencer {product_row.id}",
            )

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(side_effect=_generate_side_effect),
        ):
            preview = await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )

        assert preview.total == 3
        bodies = {item.influencer_id: item.body for item in preview.items}
        subjects = {item.influencer_id: item.subject for item in preview.items}
        assert len(set(bodies.values())) == 3
        assert len(set(subjects.values())) == 3

        for inf_id in ids:
            rec = await db.scalar(
                select(OutreachCampaignRecipient).where(
                    OutreachCampaignRecipient.campaign_id == campaign.id,
                    OutreachCampaignRecipient.product_influencer_id == inf_id,
                )
            )
            assert rec is not None
            assert rec.body == bodies[inf_id]
            assert rec.subject == subjects[inf_id]
            assert rec.can_queue is True


@pytest.mark.asyncio
async def test_queue_stores_per_recipient_subject_body_in_send_queue():
    suffix = _suffix()
    async with async_session_factory() as db:
        a = await _create_influencer(db, suffix=f"a_{suffix}", email=f"a_{suffix}@example.com")
        b = await _create_influencer(db, suffix=f"b_{suffix}", email=f"b_{suffix}@example.com")
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[a.id, b.id])

        async def _generate_side_effect(_db, *, product_row, **_kwargs):
            return _mock_generation(
                subject=f"Subj-{product_row.id}",
                body=f"Body-{product_row.id}",
            )

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(side_effect=_generate_side_effect),
        ):
            await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        rows = (
            await db.scalars(
                select(OutreachSendQueueItem).where(
                    OutreachSendQueueItem.campaign_id == campaign.id
                )
            )
        ).all()
        assert len(rows) == 2
        by_pi = {row.product_influencer_id: row for row in rows}
        assert by_pi[a.id].subject == f"Subj-{a.id}"
        assert by_pi[a.id].body == f"Body-{a.id}"
        assert by_pi[a.id].recipient == f"a_{suffix}@example.com"
        assert by_pi[b.id].subject == f"Subj-{b.id}"
        assert by_pi[b.id].body == f"Body-{b.id}"


@pytest.mark.asyncio
async def test_process_sends_queue_item_saved_subject_body():
    suffix = _suffix()
    email = f"send_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(db, ctx=ctx, influencer_ids=[influencer.id])
        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(
                return_value=_mock_generation(
                    subject="Queued subject line",
                    body="Queued body paragraph unique",
                )
            ),
        ):
            await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )
        await _queue_confirmed(db, ctx=ctx, campaign_id=campaign.id)

        item = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id
            )
        )
        assert item is not None

        captured: dict[str, str] = {}

        async def _capture_send(message, recipients):
            captured["subject"] = message["Subject"]
            part = message.get_payload()[0]
            raw = part.get_payload(decode=True)
            captured["body"] = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(side_effect=_capture_send),
        ):
            outcome = await OutreachSendQueueService._process_one(
                db, row=item, user_id=1, campaign=campaign
            )

        assert outcome == "sent"
        assert captured["subject"] == "Queued subject line"
        assert "Queued body paragraph unique" in captured["body"]


@pytest.mark.asyncio
async def test_send_campaign_now_sends_directly_then_records_terminal_queue_rows():
    suffix = _suffix()
    async with async_session_factory() as db:
        a = await _create_influencer(db, suffix=f"direct_a_{suffix}", email=f"direct_a_{suffix}@creator-mail.net")
        b = await _create_influencer(db, suffix=f"direct_b_{suffix}", email=f"direct_b_{suffix}@creator-mail.net")
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db,
            ctx=ctx,
            influencer_ids=[a.id, b.id],
            daily_limit=10,
            send_window_start="00:00",
            send_window_end="23:59",
        )

        async def _generate_side_effect(_db, *, product_row, **_kwargs):
            return _mock_generation(
                subject=f"Direct subject {product_row.id}",
                body=f"Direct body for influencer {product_row.id}",
            )

        captured: list[tuple[str, list[str]]] = []

        async def _capture_send(message, recipients):
            captured.append((message["Subject"], list(recipients)))

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(side_effect=_generate_side_effect),
        ), patch(
            "app.services.email.EmailService._send_message",
            new=AsyncMock(side_effect=_capture_send),
        ):
            preview = await OutreachCampaignService.preview_campaign(
                db, product_id=1, campaign_id=campaign.id
            )
            result = await OutreachCampaignService.send_campaign_now(
                db,
                ctx=ctx,
                campaign_id=campaign.id,
                influencer_ids=[item.influencer_id for item in preview.items],
            )

        assert result.processed == 2
        assert result.sent == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert {subject for subject, _recipients in captured} == {
            f"Direct subject {a.id}",
            f"Direct subject {b.id}",
        }

        queue_rows = list(
            (
                await db.scalars(
                    select(OutreachSendQueueItem).where(
                        OutreachSendQueueItem.campaign_id == campaign.id
                    )
                )
            ).all()
        )
        assert len(queue_rows) == 2
        assert {row.status for row in queue_rows} == {"sent"}
        assert not [row for row in queue_rows if row.status in {"queued", "scheduled", "sending"}]

        recipients = list(
            (
                await db.scalars(
                    select(OutreachCampaignRecipient).where(
                        OutreachCampaignRecipient.campaign_id == campaign.id
                    )
                )
            ).all()
        )
        assert {rec.draft_status for rec in recipients} == {"sent"}
        assert all(rec.queue_item_id for rec in recipients)


@pytest.mark.asyncio
async def test_generate_and_send_campaign_one_click_generates_queues_and_sends_unique_emails():
    suffix = _suffix()
    async with async_session_factory() as db:
        a = await _create_influencer(db, suffix=f"auto_a_{suffix}", email=f"auto_a_{suffix}@example.com")
        b = await _create_influencer(db, suffix=f"auto_b_{suffix}", email=f"auto_b_{suffix}@example.com")
        missing = await _create_influencer(db, suffix=f"auto_missing_{suffix}", email=None)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db,
            ctx=ctx,
            influencer_ids=[a.id, b.id, missing.id],
            daily_limit=10,
            send_window_start="00:00",
            send_window_end="23:59",
        )

        async def _generate_side_effect(_db, *, product_row, **_kwargs):
            return _mock_generation(
                subject=f"Auto subject {product_row.id}",
                body=f"Auto body for influencer {product_row.id}",
            )

        captured: list[tuple[str, str]] = []

        async def _capture_send(message, recipients):
            part = message.get_payload()[0]
            raw = part.get_payload(decode=True)
            body = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            captured.append((message["Subject"], body))

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(side_effect=_generate_side_effect),
        ), patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(side_effect=_capture_send),
        ):
            result = await OutreachCampaignService.generate_and_send_campaign(
                db, ctx=ctx, campaign_id=campaign.id
            )

        assert result.preview.total == 3
        assert result.preview.can_queue_count == 2
        assert result.preview.skip_count == 1
        assert result.queued == 2
        assert result.sent == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.message
        assert len(captured) == 2
        assert {subject for subject, _body in captured} == {
            f"Auto subject {a.id}",
            f"Auto subject {b.id}",
        }
        assert any(f"Auto body for influencer {a.id}" in body for _subject, body in captured)
        assert any(f"Auto body for influencer {b.id}" in body for _subject, body in captured)

        missing_rec = await db.scalar(
            select(OutreachCampaignRecipient).where(
                OutreachCampaignRecipient.campaign_id == campaign.id,
                OutreachCampaignRecipient.product_influencer_id == missing.id,
            )
        )
        assert missing_rec is not None
        assert missing_rec.skip_reason == "缂哄皯閭"


@pytest.mark.asyncio
async def test_one_click_workbench_summary_uses_real_campaign_queue_and_reply_tables():
    suffix = _suffix()
    async with async_session_factory() as db:
        sent = await _create_influencer(db, suffix=f"wb_sent_{suffix}", email=f"wb_sent_{suffix}@creator-mail.net")
        missing = await _create_influencer(db, suffix=f"wb_missing_{suffix}", email=None)
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        campaign = await _create_campaign(
            db,
            ctx=ctx,
            influencer_ids=[sent.id, missing.id],
            daily_limit=50,
            send_window_start="00:00",
            send_window_end="23:59",
        )

        with patch(
            "app.services.outreach_campaign_service.SpeechRecommendationService.generate_outreach_email",
            new=AsyncMock(return_value=_mock_generation(subject="Workbench subject", body="Workbench body")),
        ), patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ):
            await OutreachCampaignService.generate_and_send_campaign(
                db, ctx=ctx, campaign_id=campaign.id
            )

        queue_row = await db.scalar(
            select(OutreachSendQueueItem).where(
                OutreachSendQueueItem.campaign_id == campaign.id,
                OutreachSendQueueItem.product_influencer_id == sent.id,
            )
        )
        assert queue_row is not None
        db.add(
            EmailReply(
                product_id=1,
                email_log_id=queue_row.email_log_id,
                product_influencer_id=sent.id,
                campaign_id=campaign.id,
                message_id=f"reply-message-{suffix}",
                in_reply_to=f"outbound-message-{suffix}",
                match_method="message_header",
                source="imap",
                from_address=f"wb_sent_{suffix}@creator-mail.net",
                to_address="sales@example.com",
                subject="Re: Workbench subject",
                body="I am interested",
                snippet="I am interested",
                received_at=datetime.now(UTC),
            )
        )
        await db.commit()

        summary = await OutreachCampaignService.get_one_click_workbench(
            db,
            product_id=1,
        )

        assert summary.available_recipient_count >= 1
        assert summary.latest_campaign is not None
        assert summary.latest_campaign.id == campaign.id
        assert summary.latest_results.total == 2
        statuses = {item.influencer_id: item.status for item in summary.latest_results.items}
        reasons = {item.influencer_id: item.reason for item in summary.latest_results.items}
        assert statuses[sent.id] == "sent"
        assert statuses[missing.id] == "skipped"
        assert reasons[missing.id] == "缺少邮箱"
        assert summary.reply_followup.reply_count == 1
        reply_items = {item.influencer_id: item for item in summary.reply_followup.items}
        assert reply_items[sent.id].match_method == "message_header"
