"""IMAP 轮询 scheduler 与 product scope 测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.collectors.base import CollectedInfluencer
from app.core.config import Settings
from app.db.session import async_session_factory
from app.deps.tenant import TenantContext
from app.models.email_reply import EmailReply
from app.models.enums import EmailLogStatus
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product
from app.schemas.email_reply import InboundEmailPayload
from app.services.email import EmailService
from app.services.email_reply_service import EmailReplyService
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.scheduler.manager import IMAP_POLL_JOB_ID, SchedulerManager


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _imap_settings(*, poll_enabled: bool) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        imap_host="imap.example.com",
        imap_port=993,
        imap_user="inbox@example.com",
        imap_password="test-secret",
        imap_poll_enabled=poll_enabled,
        imap_poll_interval_minutes=5,
    )


@pytest.fixture
def isolated_scheduler_manager():
    manager = SchedulerManager()
    SchedulerManager._instance = manager
    yield manager
    manager.shutdown()
    SchedulerManager._instance = None


def test_scheduler_registers_imap_poll_job_when_enabled(isolated_scheduler_manager):
    manager = isolated_scheduler_manager
    with patch("app.scheduler.manager.settings", _imap_settings(poll_enabled=True)):
        manager.start()
        job = manager.scheduler.get_job(IMAP_POLL_JOB_ID)
        assert job is not None
        assert job.id == IMAP_POLL_JOB_ID


def test_scheduler_does_not_register_imap_poll_job_when_disabled(isolated_scheduler_manager):
    manager = isolated_scheduler_manager
    with patch("app.scheduler.manager.settings", _imap_settings(poll_enabled=False)):
        manager.start()
        assert manager.scheduler.get_job(IMAP_POLL_JOB_ID) is None


def test_scheduler_removes_imap_poll_job_when_disabled_after_enabled(isolated_scheduler_manager):
    manager = isolated_scheduler_manager
    with patch("app.scheduler.manager.settings", _imap_settings(poll_enabled=True)):
        manager.start()
        assert manager.scheduler.get_job(IMAP_POLL_JOB_ID) is not None

    with patch("app.scheduler.manager.settings", _imap_settings(poll_enabled=False)):
        manager._sync_imap_poll_job()
        assert manager.scheduler.get_job(IMAP_POLL_JOB_ID) is None


async def _create_influencer(
    db,
    *,
    suffix: str,
    email: str,
    product_id: int,
) -> ProductInfluencer:
    if product_id != 1 and not await db.get(Product, product_id):
        db.add(
            Product(
                id=product_id,
                workspace_id=1,
                name=f"Test Product {product_id}",
                slug=f"test-product-{product_id}",
                is_default=False,
            )
        )
        await db.flush()
    run_at = datetime.now(UTC)
    uname = f"scope_{suffix}_{product_id}"
    item = CollectedInfluencer(
        platform="instagram",
        username=uname,
        profile_url=f"https://instagram.com/{uname}",
        platform_unique_id=f"ig_scope_{suffix}_{product_id}",
        followers_count=12000,
        engagement_rate=2.0,
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
    db.add(record)
    await db.flush()
    return record


@pytest.mark.asyncio
async def test_poll_imap_product_scope_does_not_ingest_other_product():
    suffix = _suffix()
    shared_email = f"shared_scope_{suffix}@example.com"
    sender = "amazon03@ptraveldesign.com"

    async with async_session_factory() as db:
        record1 = await _create_influencer(
            db, suffix=suffix, email=shared_email, product_id=1
        )
        record2 = await _create_influencer(
            db, suffix=suffix, email=shared_email, product_id=2
        )
        await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[shared_email],
            subject="Product 1 outreach",
            body="Hi",
            status=EmailLogStatus.SENT,
            product_id=1,
            user_id=1,
            product_influencer_id=record1.id,
            sender_email=sender,
        )
        await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[shared_email],
            subject="Product 2 outreach",
            body="Hi",
            status=EmailLogStatus.SENT,
            product_id=2,
            user_id=1,
            product_influencer_id=record2.id,
            sender_email=sender,
        )
        await db.commit()

        mock_messages = [
            InboundEmailPayload(
                message_id=f"<scope-reply-{suffix}@example.com>",
                from_address=shared_email,
                to_address=sender,
                subject="Re: Product 2 outreach",
                body="Reply for product 2 only",
                received_at=datetime.now(UTC),
            )
        ]

        with patch(
            "app.services.email_reply_service.fetch_unread_imap_messages",
            return_value=mock_messages,
        ):
            batch = await EmailReplyService.poll_imap(
                db,
                mark_seen=False,
                product_id_hint=1,
            )

        assert batch.processed == 1
        assert batch.ingested == 1
        assert batch.skipped == 0

        reply_p1 = await db.scalar(
            select(EmailReply).where(EmailReply.product_id == 1)
        )
        reply_p2 = await db.scalar(
            select(EmailReply).where(EmailReply.product_id == 2)
        )
        assert reply_p1 is not None
        assert reply_p2 is None


@pytest.mark.asyncio
async def test_poll_imap_route_passes_product_scope():
    suffix = _suffix()
    sender = "amazon03@ptraveldesign.com"
    influencer_email = f"route_{suffix}@example.com"

    async with async_session_factory() as db:
        record = await _create_influencer(
            db, suffix=suffix, email=influencer_email, product_id=1
        )
        await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[influencer_email],
            subject="Route scope thread",
            body="Hello",
            status=EmailLogStatus.SENT,
            product_id=1,
            user_id=1,
            product_influencer_id=record.id,
            sender_email=sender,
        )
        await db.commit()

        from app.api.routes.email_inbound import poll_imap_inbox

        mock_messages = [
            InboundEmailPayload(
                message_id=f"<route-reply-{suffix}@example.com>",
                from_address=influencer_email,
                to_address=sender,
                subject="Re: Route scope thread",
                body="Scoped reply",
                received_at=datetime.now(UTC),
            )
        ]
        ctx = TenantContext(user_id=1, workspace_id=1, product_id=1, is_admin=True)

        with patch(
            "app.services.email_reply_service.fetch_unread_imap_messages",
            return_value=mock_messages,
        ):
            result = await poll_imap_inbox(db=db, ctx=ctx, mark_seen=False)

        assert result.ingested == 1
        reply = await db.scalar(
            select(EmailReply).where(EmailReply.product_influencer_id == record.id)
        )
        assert reply is not None
        assert reply.product_id == 1


@pytest.mark.asyncio
async def test_run_imap_reply_poll_uses_service_without_product_hint():
    from app.schemas.email_reply import EmailReplyIngestBatchResponse
    from app.scheduler.manager import run_imap_reply_poll

    batch = EmailReplyIngestBatchResponse(processed=0, ingested=0, skipped=0, failed=0, results=[])

    with patch(
        "app.services.email_reply_service.EmailReplyService.poll_imap",
        new=AsyncMock(return_value=batch),
    ) as poll_mock:
        with patch(
            "app.scheduler.manager.settings",
            _imap_settings(poll_enabled=True),
        ):
            await run_imap_reply_poll()

    poll_mock.assert_awaited_once()
    assert poll_mock.await_args.kwargs.get("product_id_hint") is None
    assert poll_mock.await_args.kwargs.get("mark_seen") is True
