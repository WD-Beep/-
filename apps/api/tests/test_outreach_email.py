"""单个红人 AI 定制邮件试发测试。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.schemas.outreach_email import SingleOutreachEmailSendRequest
from app.services.ai.openai_client import OPENAI_NOT_CONFIGURED_MSG
from app.services.email import resolve_influencer_email
from app.services.influencer_projection import merged_influencer_for_ai
from app.services.single_outreach_email_service import SingleOutreachEmailService
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _create_influencer(
    db,
    *,
    suffix: str,
    email: str | None,
    follow_status: str = "new",
) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    uname = f"trial_outreach_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=uname,
        profile_url=f"https://instagram.com/{uname}",
        platform_unique_id=f"ig_trial_{suffix}",
        followers_count=35000,
        engagement_rate=3.1,
        bio="travel and lifestyle",
        final_email=email,
        business_email=None,
        public_email=None,
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
    record.follow_status = follow_status
    db.add(record)
    await db.flush()
    return record


def test_resolve_influencer_email_priority():
    from app.models.influencer import Influencer

    row = Influencer(
        final_email="final@example.com",
        business_email="biz@example.com",
        public_email="pub@example.com",
        email="legacy@example.com",
    )
    assert resolve_influencer_email(row) == "final@example.com"

    row2 = Influencer(
        final_email=None,
        business_email="biz@example.com",
        public_email="pub@example.com",
        email="legacy@example.com",
    )
    assert resolve_influencer_email(row2) == "biz@example.com"


def test_preview_rejects_missing_email():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            record = await _create_influencer(db, suffix=suffix, email=None)
            await db.commit()
            try:
                with pytest.raises(Exception) as exc:
                    await SingleOutreachEmailService.preview(
                        db,
                        product_id=1,
                        influencer_id=record.id,
                    )
                assert "邮箱" in str(exc.value.detail)
            finally:
                await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id == record.id))
                await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
                gp = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
                if gp:
                    await db.execute(
                        delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == gp.id)
                    )
                await db.commit()

    asyncio.run(_run())


def test_preview_rejects_blacklisted():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"blocked_{suffix}@example.com",
                follow_status="blacklisted",
            )
            await db.commit()
            try:
                with pytest.raises(Exception) as exc:
                    await SingleOutreachEmailService.preview(
                        db,
                        product_id=1,
                        influencer_id=record.id,
                    )
                assert "黑名单" in str(exc.value.detail)
            finally:
                await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
                gp = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
                if gp:
                    await db.execute(
                        delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == gp.id)
                    )
                await db.commit()

    asyncio.run(_run())


def test_preview_returns_subject_body_when_openai_configured():
    async def _run() -> None:
        suffix = _suffix()
        email = f"preview_{suffix}@example.com"
        async with async_session_factory() as db:
            record = await _create_influencer(db, suffix=suffix, email=email)
            global_row = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            await db.commit()

            ai_payload = {
                "subject": f"Collab with {global_row.username}",
                "body": "Hi there,\n\nWe would love to explore a collaboration.\n\nBest",
                "reason": "Travel niche fit",
                "matched_knowledge": [
                    {"document": "brand.pdf", "section": "1", "summary": "Nordic home brand"}
                ],
                "recommended_script_title": "First outreach",
            }

            with patch(
                "app.services.speech_recommendation_service.settings"
            ) as mock_settings:
                mock_settings.is_openai_configured = True
                mock_settings.smtp_from = "sender@example.com"
                mock_settings.smtp_user = "sender@example.com"
                with patch(
                    "app.services.speech_recommendation_service.chat_completion_json",
                    new_callable=AsyncMock,
                    return_value=ai_payload,
                ):
                    preview = await SingleOutreachEmailService.preview(
                        db,
                        product_id=1,
                        influencer_id=record.id,
                    )

            assert preview.subject.startswith("Collab")
            assert "collaboration" in preview.body.lower()
            assert preview.recipient == email
            assert len(preview.matched_knowledge) == 1

            await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id == record.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(
                delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_row.id)
            )
            await db.commit()

    asyncio.run(_run())


def test_preview_fails_when_openai_not_configured():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            record = await _create_influencer(
                db, suffix=suffix, email=f"noai_{suffix}@example.com"
            )
            await db.commit()
            try:
                with patch(
                    "app.services.single_outreach_email_service.settings"
                ) as mock_settings:
                    mock_settings.is_openai_configured = False
                    with pytest.raises(Exception) as exc:
                        await SingleOutreachEmailService.preview(
                            db,
                            product_id=1,
                            influencer_id=record.id,
                        )
                    assert OPENAI_NOT_CONFIGURED_MSG in str(exc.value.detail)
            finally:
                await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
                gp = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
                if gp:
                    await db.execute(
                        delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == gp.id)
                    )
                await db.commit()

    asyncio.run(_run())


def test_send_success_writes_sent_log_and_does_not_mark_blacklisted():
    async def _run() -> None:
        suffix = _suffix()
        email = f"sendok_{suffix}@example.com"
        async with async_session_factory() as db:
            record = await _create_influencer(db, suffix=suffix, email=email, follow_status="new")
            await db.commit()

            with patch(
                "app.services.single_outreach_email_service.EmailService.ensure_smtp_configured"
            ):
                with patch(
                    "app.services.single_outreach_email_service.EmailService._send_message",
                    new_callable=AsyncMock,
                ):
                    result = await SingleOutreachEmailService.send(
                        db,
                        product_id=1,
                        user_id=1,
                        influencer_id=record.id,
                        payload=SingleOutreachEmailSendRequest(
                            subject="Test subject",
                            body="Test body for outreach",
                        ),
                    )

            assert result.success is True
            assert result.email_log is not None
            assert result.email_log.status == EmailLogStatus.SENT.value
            assert result.email_log.product_influencer_id == record.id
            assert result.email_log.body == "Test body for outreach"

            await db.refresh(record)
            assert record.follow_status == "contacted"

            logs = (
                await db.execute(
                    select(EmailLog).where(EmailLog.product_influencer_id == record.id)
                )
            ).scalars().all()
            assert len(logs) == 1
            assert logs[0].status == EmailLogStatus.SENT.value

            await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id == record.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            gp = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            if gp:
                await db.execute(
                    delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == gp.id)
                )
            await db.commit()

    asyncio.run(_run())


def test_send_failure_writes_failed_log_without_marking_contacted():
    async def _run() -> None:
        suffix = _suffix()
        email = f"sendfail_{suffix}@example.com"
        async with async_session_factory() as db:
            record = await _create_influencer(db, suffix=suffix, email=email, follow_status="new")
            await db.commit()
            original_status = record.follow_status

            with patch(
                "app.services.single_outreach_email_service.EmailService.ensure_smtp_configured"
            ):
                with patch(
                    "app.services.single_outreach_email_service.EmailService._send_message",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("SMTP auth failed"),
                ):
                    result = await SingleOutreachEmailService.send(
                        db,
                        product_id=1,
                        user_id=1,
                        influencer_id=record.id,
                        payload=SingleOutreachEmailSendRequest(
                            subject="Fail subject",
                            body="Fail body",
                        ),
                    )

            assert result.success is False
            assert result.email_log is not None
            assert result.email_log.status == EmailLogStatus.FAILED.value
            assert result.email_log.error_message

            await db.refresh(record)
            assert record.follow_status == original_status

            await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id == record.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            gp = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            if gp:
                await db.execute(
                    delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == gp.id)
                )
            await db.commit()

    asyncio.run(_run())


def test_send_invalid_status_blocked():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"invalid_{suffix}@example.com",
                follow_status="invalid",
            )
            await db.commit()
            try:
                with pytest.raises(Exception) as exc:
                    await SingleOutreachEmailService.send(
                        db,
                        product_id=1,
                        user_id=1,
                        influencer_id=record.id,
                        payload=SingleOutreachEmailSendRequest(
                            subject="S",
                            body="B",
                        ),
                    )
                assert "无效" in str(exc.value.detail)
            finally:
                await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
                gp = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
                if gp:
                    await db.execute(
                        delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == gp.id)
                    )
                await db.commit()

    asyncio.run(_run())


def test_send_uses_profile_email_not_client_payload():
    async def _run() -> None:
        suffix = _suffix()
        profile_email = f"profile_{suffix}@example.com"
        async with async_session_factory() as db:
            record = await _create_influencer(
                db, suffix=suffix, email=profile_email, follow_status="new"
            )
            await db.commit()

            captured: list[list[str]] = []

            async def _capture_send(message, recipients):
                captured.append(recipients)

            with patch(
                "app.services.single_outreach_email_service.EmailService.ensure_smtp_configured"
            ):
                with patch(
                    "app.services.single_outreach_email_service.EmailService._send_message",
                    new_callable=AsyncMock,
                    side_effect=_capture_send,
                ):
                    result = await SingleOutreachEmailService.send(
                        db,
                        product_id=1,
                        user_id=1,
                        influencer_id=record.id,
                        payload=SingleOutreachEmailSendRequest(
                            subject="Locked recipient",
                            body="Only profile email should receive this",
                        ),
                    )

            assert result.success is True
            assert captured == [[profile_email]]
            assert result.email_log is not None
            assert result.email_log.recipients == [profile_email]

            await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id == record.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            gp = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            if gp:
                await db.execute(
                    delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == gp.id)
                )
            await db.commit()

    asyncio.run(_run())
