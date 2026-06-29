"""默认话术种子、保存为话术、发送队列测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.deps.tenant import TenantContext
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.message_template import MessageTemplate
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.schemas.email_log import SaveEmailLogAsTemplateRequest
from app.schemas.outreach_email import OutreachSendQueueEnqueueRequest
from app.services.default_message_templates import (
    SYSTEM_DEFAULT_TEMPLATE_SPECS,
    ensure_default_templates_for_product,
    format_template_source_title,
)
from app.services.email_log import EmailLogService
from app.services.email_sent_status import product_influencer_has_successful_email_sent
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services.outreach_send_queue_service import OutreachSendQueueService


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _create_influencer(db, *, suffix: str, email: str) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    uname = f"queue_test_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=uname,
        profile_url=f"https://instagram.com/{uname}",
        platform_unique_id=f"ig_q_{suffix}",
        followers_count=12000,
        engagement_rate=2.5,
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


@pytest.mark.asyncio
async def test_ensure_default_templates_seeds_product_scoped():
    async with async_session_factory() as db:
        await db.execute(delete(MessageTemplate).where(MessageTemplate.product_id == 1))
        await db.commit()
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        created = await ensure_default_templates_for_product(db, ctx=ctx, product_id=1)
        assert created == len(SYSTEM_DEFAULT_TEMPLATE_SPECS)
        rows = (
            await db.scalars(select(MessageTemplate).where(MessageTemplate.product_id == 1))
        ).all()
        assert len(rows) == len(SYSTEM_DEFAULT_TEMPLATE_SPECS)
        assert all("system_default" in (row.tags or []) for row in rows)
        again = await ensure_default_templates_for_product(db, ctx=ctx, product_id=1)
        assert again == 0


def test_format_template_source_title():
    assert format_template_source_title("First Outreach", from_system_default=True).startswith("系统默认话术")
    assert format_template_source_title("My Script", from_system_default=False) == "My Script"


@pytest.mark.asyncio
async def test_save_email_log_as_template_duplicate_detection():
    suffix = _suffix()
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=f"dup_{suffix}@example.com")
        log = EmailLog(
            product_id=1,
            user_id=1,
            product_influencer_id=influencer.id,
            recipients=[f"dup_{suffix}@example.com"],
            subject="Dup Subject",
            body="Dup body content",
            status=EmailLogStatus.SENT.value,
            generated_by_ai=True,
            sent_at=datetime.now(UTC),
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        payload = SaveEmailLogAsTemplateRequest(title="Dup Subject", content="Dup body content")
        first = await EmailLogService.save_as_message_template(db, log=log, ctx=ctx, payload=payload)
        assert first.created is True

        second = await EmailLogService.save_as_message_template(db, log=log, ctx=ctx, payload=payload)
        assert second.created is False
        assert second.duplicate is True

        copy_payload = SaveEmailLogAsTemplateRequest(
            title="Dup Subject",
            content="Dup body content",
            save_as_copy=True,
        )
        third = await EmailLogService.save_as_message_template(db, log=log, ctx=ctx, payload=copy_payload)
        assert third.created is True
        assert third.template is not None
        assert "副本" in third.template.title


@pytest.mark.asyncio
async def test_enqueue_and_duplicate_blocked():
    suffix = _suffix()
    email = f"queue_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        row = await OutreachSendQueueService.enqueue(
            db,
            ctx=ctx,
            influencer_id=influencer.id,
            payload=OutreachSendQueueEnqueueRequest(subject="Hello", body="Body text"),
        )
        assert row.status == "queued"
        assert row.recipient == email

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await OutreachSendQueueService.enqueue(
                db,
                ctx=ctx,
                influencer_id=influencer.id,
                payload=OutreachSendQueueEnqueueRequest(subject="Dup", body="Another"),
            )
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_clear_failed_queue_deletes_only_failed_items():
    suffix = _suffix()
    async with async_session_factory() as db:
        await db.execute(
            delete(OutreachSendQueueItem).where(
                OutreachSendQueueItem.product_id == 1,
                OutreachSendQueueItem.status == "failed",
                OutreachSendQueueItem.recipient.like("failed_%@example.com"),
            )
        )
        await db.commit()

        failed_influencer = await _create_influencer(
            db, suffix=f"failed_{suffix}", email=f"failed_{suffix}@example.com"
        )
        queued_influencer = await _create_influencer(
            db, suffix=f"queued_{suffix}", email=f"queued_{suffix}@example.com"
        )
        sent_influencer = await _create_influencer(
            db, suffix=f"sentq_{suffix}", email=f"sentq_{suffix}@example.com"
        )
        failed = OutreachSendQueueItem(
            product_id=1,
            user_id=1,
            product_influencer_id=failed_influencer.id,
            recipient=f"failed_{suffix}@example.com",
            subject="Failed",
            body="Failed body",
            status="failed",
            error_message="SMTP auth failed",
        )
        queued = OutreachSendQueueItem(
            product_id=1,
            user_id=1,
            product_influencer_id=queued_influencer.id,
            recipient=f"queued_{suffix}@example.com",
            subject="Queued",
            body="Queued body",
            status="queued",
        )
        sent = OutreachSendQueueItem(
            product_id=1,
            user_id=1,
            product_influencer_id=sent_influencer.id,
            recipient=f"sentq_{suffix}@example.com",
            subject="Sent",
            body="Sent body",
            status="sent",
            sent_at=datetime.now(UTC),
        )
        db.add_all([failed, queued, sent])
        await db.commit()

        deleted_count = await OutreachSendQueueService.clear_failed(db, product_id=1)

        assert deleted_count == 1
        remaining = (
            await db.scalars(
                select(OutreachSendQueueItem).where(
                    OutreachSendQueueItem.id.in_([failed.id, queued.id, sent.id])
                )
            )
        ).all()
        assert {item.status for item in remaining} == {"queued", "sent"}

        await db.execute(
            delete(OutreachSendQueueItem).where(
                OutreachSendQueueItem.id.in_([queued.id, sent.id])
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_enqueue_fresh_product_influencer_no_attribute_error():
    """DB 查出的 ProductInfluencer 无 email_sent 字段，入队不得 AttributeError。"""
    suffix = _suffix()
    email = f"fresh_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        await db.commit()
        await db.refresh(influencer)
        assert not hasattr(influencer, "email_sent") or getattr(influencer, "email_sent", None) is None

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        row = await OutreachSendQueueService.enqueue(
            db,
            ctx=ctx,
            influencer_id=influencer.id,
            payload=OutreachSendQueueEnqueueRequest(subject="Fresh", body="Fresh body"),
        )
        assert row.status == "queued"
        await db.execute(
            delete(OutreachSendQueueItem).where(OutreachSendQueueItem.id == row.id)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_enqueue_rejects_when_success_email_log_exists_without_allow_resend():
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
                subject="Prior sent",
                body="Prior body",
                status=EmailLogStatus.SENT.value,
                generated_by_ai=True,
                sent_at=datetime.now(UTC),
            )
        )
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await OutreachSendQueueService.enqueue(
                db,
                ctx=ctx,
                influencer_id=influencer.id,
                payload=OutreachSendQueueEnqueueRequest(
                    subject="Retry",
                    body="Retry body",
                    allow_resend=False,
                ),
            )
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_enqueue_allows_resend_when_flag_set():
    suffix = _suffix()
    email = f"resend_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        db.add(
            EmailLog(
                product_id=1,
                user_id=1,
                product_influencer_id=influencer.id,
                recipients=[email],
                subject="Prior sent",
                body="Prior body",
                status=EmailLogStatus.SENT.value,
                sent_at=datetime.now(UTC),
            )
        )
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        row = await OutreachSendQueueService.enqueue(
            db,
            ctx=ctx,
            influencer_id=influencer.id,
            payload=OutreachSendQueueEnqueueRequest(
                subject="Retry",
                body="Retry body",
                allow_resend=True,
            ),
        )
        assert row.allow_resend is True


@pytest.mark.asyncio
async def test_process_today_skips_when_email_sent_after_enqueue():
    suffix = _suffix()
    email = f"skip_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        queued = await OutreachSendQueueService.enqueue(
            db,
            ctx=ctx,
            influencer_id=influencer.id,
            payload=OutreachSendQueueEnqueueRequest(subject="Skip me", body="Skip body"),
        )
        db.add(
            EmailLog(
                product_id=1,
                user_id=1,
                product_influencer_id=influencer.id,
                recipients=[email],
                subject="Sent elsewhere",
                body="Sent elsewhere body",
                status=EmailLogStatus.SENT.value,
                sent_at=datetime.now(UTC),
            )
        )
        await db.commit()

        item = await db.scalar(
            select(OutreachSendQueueItem).where(OutreachSendQueueItem.id == queued.id)
        )
        assert item is not None

        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ) as send_mock:
            outcome = await OutreachSendQueueService._process_one(db, row=item, user_id=1)
            send_mock.assert_not_called()

        assert outcome == "skipped"
        await db.refresh(item)
        assert item.status == "skipped"
        assert "成功发信" in (item.error_message or "")


@pytest.mark.asyncio
async def test_process_today_failed_writes_email_log():
    suffix = _suffix()
    email = f"fail_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        queued = await OutreachSendQueueService.enqueue(
            db,
            ctx=ctx,
            influencer_id=influencer.id,
            payload=OutreachSendQueueEnqueueRequest(
                subject="Queue fail",
                body="Queue body",
                ai_reason="test reason",
                matched_knowledge=[],
            ),
        )
        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(side_effect=RuntimeError("smtp down")),
        ):
            item = await db.scalar(
                select(OutreachSendQueueItem).where(OutreachSendQueueItem.id == queued.id)
            )
            assert item is not None
            await OutreachSendQueueService._process_one(db, row=item, user_id=1)

        refreshed = await db.scalar(
            select(OutreachSendQueueItem).where(OutreachSendQueueItem.id == queued.id)
        )
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.email_log_id is not None

        log = await db.scalar(select(EmailLog).where(EmailLog.id == refreshed.email_log_id))
        assert log is not None
        assert log.status == EmailLogStatus.FAILED.value
        assert log.error_message
        assert log.product_influencer_id == influencer.id

        still_sent = await product_influencer_has_successful_email_sent(
            db, product_id=1, product_influencer_id=influencer.id
        )
        assert still_sent is False


@pytest.mark.asyncio
async def test_process_today_success_writes_email_log_with_ai_context():
    suffix = _suffix()
    email = f"ok_{suffix}@example.com"
    matched = [{"document": "Brand Guide", "section": "Intro", "summary": "fit check"}]
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        queued = await OutreachSendQueueService.enqueue(
            db,
            ctx=ctx,
            influencer_id=influencer.id,
            payload=OutreachSendQueueEnqueueRequest(
                subject="Queue ok",
                body="Queue ok body",
                ai_reason="strong fit",
                matched_knowledge=[],
            ),
        )
        item = await db.scalar(
            select(OutreachSendQueueItem).where(OutreachSendQueueItem.id == queued.id)
        )
        assert item is not None
        item.matched_knowledge = matched
        item.ai_reason = "strong fit"
        await db.commit()

        with patch(
            "app.services.outreach_send_queue_service.EmailService._send_message",
            new=AsyncMock(),
        ):
            await OutreachSendQueueService._process_one(db, row=item, user_id=1)

        refreshed = await db.scalar(
            select(OutreachSendQueueItem).where(OutreachSendQueueItem.id == queued.id)
        )
        assert refreshed is not None
        assert refreshed.status == "sent"
        log = await db.scalar(select(EmailLog).where(EmailLog.id == refreshed.email_log_id))
        assert log is not None
        assert log.status == EmailLogStatus.SENT.value
        assert log.ai_reason == "strong fit"
        assert log.matched_knowledge == matched
        assert log.sender_email


@pytest.mark.asyncio
async def test_blacklisted_influencer_cannot_enqueue():
    suffix = _suffix()
    email = f"blk_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        influencer.follow_status = "blacklisted"
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await OutreachSendQueueService.enqueue(
                db,
                ctx=ctx,
                influencer_id=influencer.id,
                payload=OutreachSendQueueEnqueueRequest(subject="No", body="No"),
            )
        assert exc.value.status_code == 400
        assert "黑名单" in exc.value.detail


@pytest.mark.asyncio
async def test_invalid_influencer_cannot_enqueue():
    suffix = _suffix()
    email = f"inv_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        influencer.follow_status = "invalid"
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await OutreachSendQueueService.enqueue(
                db,
                ctx=ctx,
                influencer_id=influencer.id,
                payload=OutreachSendQueueEnqueueRequest(subject="No", body="No"),
            )
        assert exc.value.status_code == 400
        assert "无效" in exc.value.detail


@pytest.mark.asyncio
async def test_replied_influencer_cannot_enqueue():
    suffix = _suffix()
    email = f"rep_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        influencer.follow_status = "replied"
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await OutreachSendQueueService.enqueue(
                db,
                ctx=ctx,
                influencer_id=influencer.id,
                payload=OutreachSendQueueEnqueueRequest(subject="No", body="No"),
            )
        assert exc.value.status_code == 400
        assert "已回复" in exc.value.detail


@pytest.mark.asyncio
async def test_enqueue_rejects_sender_address_as_recipient():
    suffix = _suffix()
    async with async_session_factory() as db:
        from unittest.mock import patch

        from app.core.config import Settings

        sender = "sender@company.com"
        influencer = await _create_influencer(db, suffix=suffix, email=sender)
        await db.commit()

        mock_settings = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user=sender,
            smtp_password="secret",
            smtp_from=sender,
        )
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        from fastapi import HTTPException

        with patch("app.services.outreach_recipient.settings", mock_settings):
            with pytest.raises(HTTPException) as exc:
                await OutreachSendQueueService.enqueue(
                    db,
                    ctx=ctx,
                    influencer_id=influencer.id,
                    payload=OutreachSendQueueEnqueueRequest(subject="No", body="No"),
                )
        assert exc.value.status_code == 400
        assert "发件邮箱相同" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_process_one_skips_sender_address_recipient():
    suffix = _suffix()
    sender = "sender@company.com"
    email = f"queue_{suffix}@example.com"
    async with async_session_factory() as db:
        from unittest.mock import patch

        from app.core.config import Settings

        influencer = await _create_influencer(db, suffix=suffix, email=email)
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        queued = await OutreachSendQueueService.enqueue(
            db,
            ctx=ctx,
            influencer_id=influencer.id,
            payload=OutreachSendQueueEnqueueRequest(subject="Hi", body="Body"),
        )
        product_row = await db.get(ProductInfluencer, influencer.id)
        assert product_row is not None
        global_row = await db.scalar(
            select(GlobalInfluencerProfile).where(
                GlobalInfluencerProfile.id == product_row.global_influencer_id
            )
        )
        assert global_row is not None
        global_row.final_email = sender
        await db.commit()

        item = await db.scalar(
            select(OutreachSendQueueItem).where(OutreachSendQueueItem.id == queued.id)
        )
        assert item is not None
        mock_settings = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user=sender,
            smtp_password="secret",
            smtp_from=sender,
        )
        with patch("app.services.outreach_recipient.settings", mock_settings):
            with patch(
                "app.services.outreach_send_queue_service.EmailService._send_message",
                new=AsyncMock(),
            ) as send_mock:
                outcome = await OutreachSendQueueService._process_one(
                    db, row=item, user_id=1
                )
                send_mock.assert_not_called()
        assert outcome == "skipped"
        await db.refresh(item)
        assert "发件邮箱相同" in (item.error_message or "")
    suffix = _suffix()
    email = f"rep_resend_{suffix}@example.com"
    async with async_session_factory() as db:
        influencer = await _create_influencer(db, suffix=suffix, email=email)
        influencer.follow_status = "interested"
        db.add(
            EmailLog(
                product_id=1,
                user_id=1,
                product_influencer_id=influencer.id,
                recipients=[email],
                subject="Prior sent",
                body="Prior body",
                status=EmailLogStatus.SENT.value,
                sent_at=datetime.now(UTC),
            )
        )
        await db.commit()

        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await OutreachSendQueueService.enqueue(
                db,
                ctx=ctx,
                influencer_id=influencer.id,
                payload=OutreachSendQueueEnqueueRequest(
                    subject="Retry",
                    body="Retry body",
                    allow_resend=True,
                ),
            )
        assert exc.value.status_code == 400
        assert "已回复" in exc.value.detail
