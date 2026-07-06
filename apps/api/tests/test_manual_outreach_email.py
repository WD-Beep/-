"""Manual outreach test email tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.deps.tenant import TenantContext
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.manual_outreach_email import ManualOutreachEmail
from app.schemas.manual_outreach_email import ManualOutreachEmailRequest
from app.services.manual_outreach_email_service import ManualOutreachEmailService


def _ctx() -> TenantContext:
    return TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)


@pytest.mark.asyncio
async def test_manual_outreach_rejects_more_than_ten_recipients():
    async with async_session_factory() as db:
        payload = ManualOutreachEmailRequest(
            recipients=[f"creator{i}@example.com" for i in range(11)],
            subject="Test subject",
            body="Test body",
            send_mode="now",
        )

        with pytest.raises(HTTPException) as exc:
            await ManualOutreachEmailService.submit(db, ctx=_ctx(), payload=payload)

        assert exc.value.status_code == 400
        assert "10" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_manual_outreach_send_now_sends_and_writes_email_log():
    async with async_session_factory() as db:
        await db.execute(delete(EmailLog).where(EmailLog.subject == "Manual send now"))
        await db.commit()
        payload = ManualOutreachEmailRequest(
            recipients=["creator@example.com"],
            subject="Manual send now",
            body="Hello creator",
            send_mode="now",
        )

        with patch("app.services.manual_outreach_email_service.EmailService.ensure_smtp_configured"), patch(
            "app.services.manual_outreach_email_service.EmailService._send_message",
            new=AsyncMock(),
        ) as send_mock:
            result = await ManualOutreachEmailService.submit(db, ctx=_ctx(), payload=payload)

        assert result.status == "sent"
        assert result.sent_count == 1
        send_mock.assert_awaited_once()
        log = await db.scalar(select(EmailLog).where(EmailLog.subject == "Manual send now"))
        assert log is not None
        assert log.status == EmailLogStatus.SENT.value
        assert log.recipients == ["creator@example.com"]
        assert log.product_influencer_id is None
        assert log.generated_by_ai is False


@pytest.mark.asyncio
async def test_manual_outreach_schedule_creates_queue_without_sending():
    async with async_session_factory() as db:
        await db.execute(delete(ManualOutreachEmail).where(ManualOutreachEmail.subject == "Manual scheduled"))
        await db.commit()
        scheduled_at = datetime.now(UTC) + timedelta(hours=2)
        payload = ManualOutreachEmailRequest(
            recipients=["scheduled@example.com"],
            subject="Manual scheduled",
            body="Scheduled body",
            send_mode="scheduled",
            scheduled_at=scheduled_at,
        )

        with patch(
            "app.services.manual_outreach_email_service.EmailService._send_message",
            new=AsyncMock(),
        ) as send_mock:
            result = await ManualOutreachEmailService.submit(db, ctx=_ctx(), payload=payload)

        assert result.status == "scheduled"
        assert result.scheduled_count == 1
        send_mock.assert_not_called()
        queued = await db.scalar(select(ManualOutreachEmail).where(ManualOutreachEmail.subject == "Manual scheduled"))
        assert queued is not None
        assert queued.status == "scheduled"
        assert queued.recipient == "scheduled@example.com"
