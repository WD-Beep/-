"""采集完成后自动外联：收件人校验与 skip 行为。"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.collectors.base import CollectedInfluencer
from app.core.config import Settings
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.schemas.outreach_email import OutreachEmailGenerationResult
from app.services.email import EmailService
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services.influencer_projection import merged_influencer_for_ai


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _sender_settings(sender: str) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_user=sender,
        smtp_password="secret",
        smtp_from=sender,
    )


async def _create_influencer(db, *, suffix: str, email: str) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    uname = f"sync_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=uname,
        profile_url=f"https://instagram.com/{uname}",
        platform_unique_id=f"ig_sync_{suffix}",
        followers_count=12000,
        engagement_rate=2.0,
        bio="travel",
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
    db.add(record)
    await db.flush()
    return record


def _mock_generation() -> OutreachEmailGenerationResult:
    return OutreachEmailGenerationResult(
        subject="Hello",
        body="Body text",
        recommended_script_title="Script",
        reason="test generation",
        matched_knowledge=[],
    )


async def _sync_for_record(
    db,
    record: ProductInfluencer,
    *,
    provider: str = "smtp",
    dry_run: bool = False,
    mock_settings: Settings | None = None,
):
    product_row = await db.get(ProductInfluencer, record.id)
    assert product_row is not None
    global_row = await db.get(GlobalInfluencerProfile, product_row.global_influencer_id)
    assert global_row is not None

    async def _get_influencers(_db, _task):
        return [merged_influencer_for_ai(product_row, global_row)]

    task = CollectionTask(
        id=9001,
        product_id=1,
        user_id=1,
        name="sync test",
        platform="instagram",
        outreach_provider=provider,
        outreach_dry_run=dry_run,
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.services.email.TaskInfluencerService.get_influencers_for_task",
                side_effect=_get_influencers,
            )
        )
        stack.enter_context(
            patch(
                "app.services.speech_recommendation_service.SpeechRecommendationService.generate_outreach_email",
                new=AsyncMock(return_value=_mock_generation()),
            )
        )
        send_mock = stack.enter_context(
            patch(
                "app.services.email.EmailService._send_message",
                new=AsyncMock(),
            )
        )
        mark_mock = stack.enter_context(
            patch(
                "app.services.email.InfluencerLeadService.mark_product_email_sent",
                new=AsyncMock(),
            )
        )
        mailchimp_mock = stack.enter_context(
            patch(
                "app.services.email.EmailService.sync_contact_to_mailchimp",
                new=AsyncMock(return_value="synced"),
            )
        )
        if mock_settings is not None:
            stack.enter_context(
                patch("app.services.outreach_recipient.settings", mock_settings)
            )

        result = await EmailService.sync_outreach_contacts_after_collection(db, task)

    return {
        "result": result,
        "send_mock": send_mock,
        "mark_mock": mark_mock,
        "mailchimp_mock": mailchimp_mock,
    }


@pytest.mark.asyncio
async def test_sync_outreach_smtp_skips_sender_email():
    suffix = _suffix()
    sender = "sender@company.com"
    async with async_session_factory() as db:
        record = await _create_influencer(db, suffix=suffix, email=sender)
        await db.commit()

        ctx = await _sync_for_record(
            db,
            record,
            provider="smtp",
            dry_run=False,
            mock_settings=_sender_settings(sender),
        )

        assert ctx["result"]["skipped"] == 1
        assert ctx["result"]["sent"] == 0
        assert ctx["result"]["queued"] == 0
        ctx["send_mock"].assert_not_called()
        ctx["mark_mock"].assert_not_called()

        log_count = await db.scalar(
            select(func.count())
            .select_from(EmailLog)
            .where(
                EmailLog.product_influencer_id == record.id,
                EmailLog.status == EmailLogStatus.SENT.value,
            )
        )
        assert log_count == 0


@pytest.mark.asyncio
async def test_sync_outreach_dry_run_skips_sender_email_without_log():
    suffix = _suffix()
    sender = "sender@company.com"
    async with async_session_factory() as db:
        record = await _create_influencer(db, suffix=suffix, email=sender)
        await db.commit()

        ctx = await _sync_for_record(
            db,
            record,
            provider="smtp",
            dry_run=True,
            mock_settings=_sender_settings(sender),
        )

        assert ctx["result"]["skipped"] == 1
        assert ctx["result"]["queued"] == 0

        log_count = await db.scalar(
            select(func.count()).select_from(EmailLog).where(
                EmailLog.product_influencer_id == record.id
            )
        )
        assert log_count == 0
        ctx["mark_mock"].assert_not_called()


@pytest.mark.asyncio
async def test_sync_outreach_mailchimp_skips_sender_email():
    suffix = _suffix()
    sender = "sender@company.com"
    async with async_session_factory() as db:
        record = await _create_influencer(db, suffix=suffix, email=sender)
        await db.commit()

        ctx = await _sync_for_record(
            db,
            record,
            provider="mailchimp",
            dry_run=False,
            mock_settings=_sender_settings(sender),
        )

        assert ctx["result"]["skipped"] == 1
        assert ctx["result"]["sent"] == 0
        ctx["mailchimp_mock"].assert_not_called()
        ctx["mark_mock"].assert_not_called()

        log_count = await db.scalar(
            select(func.count())
            .select_from(EmailLog)
            .where(
                EmailLog.product_influencer_id == record.id,
                EmailLog.status == EmailLogStatus.SENT.value,
            )
        )
        assert log_count == 0
