"""Inbound email reply ingestion tests (mock webhook/IMAP payloads)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.collectors.base import CollectedInfluencer
from app.core.config import Settings
from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.enums import EmailLogStatus, LeadStatus
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product
from app.schemas.email_reply import InboundEmailPayload
from app.services.email import EmailService
from app.services.email_reply_service import EmailReplyService
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
    email: str,
    product_id: int = 1,
    follow_status: str = "contacted",
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
    uname = f"reply_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=uname,
        profile_url=f"https://instagram.com/{uname}",
        platform_unique_id=f"ig_reply_{suffix}",
        followers_count=18000,
        engagement_rate=2.8,
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
    record.follow_status = follow_status
    db.add(record)
    await db.flush()
    return record


@pytest.mark.asyncio
async def test_webhook_ingest_matches_by_message_id_and_marks_replied():
    suffix = _suffix()
    sender = "amazon03@ptraveldesign.com"
    influencer_email = f"inf_{suffix}@example.com"
    message_id = f"<outreach-1-{suffix}@example.com>"

    async with async_session_factory() as db:
        record = await _create_influencer(db, suffix=suffix, email=influencer_email)
        log = await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[influencer_email],
            subject="Collaboration invite",
            body="Hello there",
            status=EmailLogStatus.SENT,
            product_id=1,
            user_id=1,
            product_influencer_id=record.id,
            sender_email=sender,
            influencer_username=f"reply_{suffix}",
            message_id=message_id,
        )
        await db.commit()

        payload = InboundEmailPayload(
            message_id=f"<reply-{suffix}@example.com>",
            in_reply_to=message_id,
            from_address=influencer_email,
            to_address=sender,
            subject="Re: Collaboration invite",
            body="Thanks for reaching out!",
            received_at=datetime.now(UTC),
            product_id=1,
        )
        result = await EmailReplyService.ingest(db, payload, source="webhook")

        assert result.status == "ingested"
        assert result.product_influencer_id == record.id
        assert result.email_log_id == log.id
        assert result.match_method == "message_id"
        assert result.follow_status == LeadStatus.REPLIED.value

        row = await db.get(ProductInfluencer, record.id)
        assert row is not None
        assert row.follow_status == LeadStatus.REPLIED.value
        assert row.last_reply_at is not None


@pytest.mark.asyncio
async def test_webhook_ingest_detects_interest_keywords():
    suffix = _suffix()
    sender = "amazon03@ptraveldesign.com"
    influencer_email = f"interest_{suffix}@example.com"

    async with async_session_factory() as db:
        record = await _create_influencer(db, suffix=suffix, email=influencer_email)
        await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[influencer_email],
            subject="Partnership",
            body="Would you like to collaborate?",
            status=EmailLogStatus.SENT,
            product_id=1,
            user_id=1,
            product_influencer_id=record.id,
            sender_email=sender,
            message_id=f"<outreach-interest-{suffix}@example.com>",
        )
        await db.commit()

        payload = InboundEmailPayload(
            message_id=f"<reply-interest-{suffix}@example.com>",
            from_address=influencer_email,
            to_address=sender,
            subject="Re: Partnership",
            body="I'm interested in a collaboration. Please send your rate card.",
            received_at=datetime.now(UTC),
            product_id=1,
        )
        result = await EmailReplyService.ingest(db, payload, source="webhook")
        assert result.status == "ingested"
        assert result.follow_status == LeadStatus.INTERESTED.value


@pytest.mark.asyncio
async def test_webhook_does_not_change_blacklisted_status():
    suffix = _suffix()
    sender = "amazon03@ptraveldesign.com"
    influencer_email = f"black_{suffix}@example.com"

    async with async_session_factory() as db:
        record = await _create_influencer(
            db,
            suffix=suffix,
            email=influencer_email,
            follow_status=LeadStatus.BLACKLISTED.value,
        )
        await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[influencer_email],
            subject="Hello",
            body="Body",
            status=EmailLogStatus.SENT,
            product_id=1,
            user_id=1,
            product_influencer_id=record.id,
            sender_email=sender,
        )
        await db.commit()

        payload = InboundEmailPayload(
            message_id=f"<reply-black-{suffix}@example.com>",
            from_address=influencer_email,
            to_address=sender,
            subject="Re: Hello",
            body="Reply text",
            received_at=datetime.now(UTC),
            product_id=1,
        )
        result = await EmailReplyService.ingest(db, payload, source="webhook")
        assert result.status == "ingested"

        row = await db.get(ProductInfluencer, record.id)
        assert row is not None
        assert row.follow_status == LeadStatus.BLACKLISTED.value


@pytest.mark.asyncio
async def test_webhook_skips_cross_product_ambiguous_sender():
    suffix = _suffix()
    shared_email = f"shared_{suffix}@example.com"
    sender = "amazon03@ptraveldesign.com"

    async with async_session_factory() as db:
        record1 = await _create_influencer(db, suffix=f"a_{suffix}", email=shared_email, product_id=1)
        record2 = await _create_influencer(db, suffix=f"b_{suffix}", email=shared_email, product_id=2)
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

        payload = InboundEmailPayload(
            message_id=f"<reply-shared-{suffix}@example.com>",
            from_address=shared_email,
            to_address=sender,
            subject="Re: Product 1 outreach",
            body="Reply",
            received_at=datetime.now(UTC),
        )
        ambiguous = await EmailReplyService.ingest(db, payload, source="webhook")
        assert ambiguous.status == "ingested"
        assert ambiguous.match_method == "unmatched"

        payload.product_id = 1
        scoped = await EmailReplyService.ingest(
            db,
            InboundEmailPayload(
                message_id=f"<reply-shared-scoped-{suffix}@example.com>",
                from_address=shared_email,
                to_address=sender,
                subject="Re: Product 1 outreach",
                body="Reply",
                received_at=datetime.now(UTC),
                product_id=1,
            ),
            source="webhook",
        )
        assert scoped.status == "ingested"
        assert scoped.product_id == 1
        assert scoped.product_influencer_id == record1.id


@pytest.mark.asyncio
async def test_poll_imap_uses_mock_messages():
    suffix = _suffix()
    sender = "amazon03@ptraveldesign.com"
    influencer_email = f"imap_{suffix}@example.com"
    message_id = f"<outreach-imap-{suffix}@example.com>"

    async with async_session_factory() as db:
        record = await _create_influencer(db, suffix=suffix, email=influencer_email)
        await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[influencer_email],
            subject="IMAP thread",
            body="Hello",
            status=EmailLogStatus.SENT,
            product_id=1,
            user_id=1,
            product_influencer_id=record.id,
            sender_email=sender,
            message_id=message_id,
        )
        await db.commit()

        mock_messages = [
            InboundEmailPayload(
                message_id=f"<imap-reply-{suffix}@example.com>",
                in_reply_to=message_id,
                from_address=influencer_email,
                to_address=sender,
                subject="Re: IMAP thread",
                body="Got it",
                received_at=datetime.now(UTC),
                product_id=1,
            )
        ]

        with patch(
            "app.services.email_reply_service.fetch_unread_imap_messages",
            return_value=mock_messages,
        ):
            batch = await EmailReplyService.poll_imap(db, mark_seen=False)

        assert batch.processed == 1
        assert batch.ingested == 1
        reply = await db.scalar(
            select(EmailReply).where(EmailReply.product_influencer_id == record.id)
        )
        assert reply is not None
        assert reply.source == "imap"


@pytest.mark.asyncio
async def test_unmatched_reply_is_saved_for_manual_review():
    suffix = _suffix()

    async with async_session_factory() as db:
        payload = InboundEmailPayload(
            message_id=f"<unmatched-{suffix}@example.com>",
            from_address=f"unknown_{suffix}@example.com",
            to_address="amazon03@ptraveldesign.com",
            subject="Re: Partnership",
            body="Who is this for?",
            received_at=datetime.now(UTC),
            product_id=1,
        )
        result = await EmailReplyService.ingest(db, payload, source="imap")

        assert result.status == "ingested"
        assert result.match_method == "unmatched"
        assert result.product_influencer_id is None
        assert result.message == "已接收回复，但还没有匹配到红人，请在未匹配回复中手动关联"

        reply = await db.scalar(
            select(EmailReply).where(EmailReply.message_id == f"<unmatched-{suffix}@example.com>")
        )
        assert reply is not None
        assert reply.product_id == 1
        assert reply.processing_status == "unprocessed"
        assert reply.intent_status == "unmatched"


@pytest.mark.asyncio
async def test_unmatched_automated_mail_is_skipped():
    suffix = _suffix()

    async with async_session_factory() as db:
        result = await EmailReplyService.ingest(
            db,
            InboundEmailPayload(
                message_id=f"<steam-promo-{suffix}@example.com>",
                from_address="noreply@steampowered.com",
                to_address="amazon03@ptraveldesign.com",
                subject="Steam sale notification",
                body="Wishlist item sale alert",
                received_at=datetime.now(UTC),
                product_id=1,
            ),
            source="imap",
        )

        assert result.status == "skipped"
        assert result.reply_id is None

        row = await db.scalar(
            select(EmailReply).where(EmailReply.message_id == f"<steam-promo-{suffix}@example.com>")
        )
        assert row is None


@pytest.mark.asyncio
async def test_reply_work_count_only_counts_matched_influencer_replies_for_badge():
    suffix = _suffix()
    sender = "amazon03@ptraveldesign.com"
    influencer_email = f"badge_{suffix}@example.com"
    product_id = 7000 + int(suffix[:4], 16)

    async with async_session_factory() as db:
        record = await _create_influencer(
            db,
            suffix=suffix,
            email=influencer_email,
            product_id=product_id,
        )
        await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[influencer_email],
            subject="Badge collaboration",
            body="Hello",
            status=EmailLogStatus.SENT,
            product_id=product_id,
            user_id=1,
            product_influencer_id=record.id,
            sender_email=sender,
        )
        await db.commit()

        matched = await EmailReplyService.ingest(
            db,
            InboundEmailPayload(
                message_id=f"<badge-matched-{suffix}@example.com>",
                from_address=influencer_email,
                to_address=sender,
                subject="Re: Badge collaboration",
                body="Interested",
                received_at=datetime.now(UTC),
                product_id=product_id,
            ),
            source="imap",
        )
        unmatched = await EmailReplyService.ingest(
            db,
            InboundEmailPayload(
                message_id=f"<badge-unmatched-{suffix}@example.com>",
                from_address=f"unknown_badge_{suffix}@example.com",
                to_address=sender,
                subject="Random message",
                body="Manual review only",
                received_at=datetime.now(UTC),
                product_id=product_id,
            ),
            source="imap",
        )

        assert matched.status == "ingested"
        assert unmatched.status == "ingested"

        unprocessed_count, unmatched_count = await EmailReplyService.count_reply_work(
            db,
            product_id=product_id,
        )

        assert unprocessed_count == 1
        assert unmatched_count == 1


@pytest.mark.asyncio
async def test_reply_status_filter_and_manual_link_marks_influencer_replied():
    suffix = _suffix()
    influencer_email = f"manual_{suffix}@example.com"

    async with async_session_factory() as db:
        record = await _create_influencer(db, suffix=suffix, email=influencer_email)
        result = await EmailReplyService.ingest(
            db,
            InboundEmailPayload(
                message_id=f"<manual-link-{suffix}@example.com>",
                from_address=f"unknown_manual_{suffix}@example.com",
                to_address="amazon03@ptraveldesign.com",
                subject="Re: Manual match",
                body="Please send more details.",
                received_at=datetime.now(UTC),
                product_id=1,
            ),
            source="imap",
        )
        assert result.reply_id is not None

        linked = await EmailReplyService.update_reply(
            db,
            product_id=1,
            reply_id=result.reply_id,
            product_influencer_id=record.id,
            intent_status="follow_up",
            processing_status="unprocessed",
        )

        assert linked.product_influencer_id == record.id
        assert linked.intent_status == "follow_up"
        row = await db.get(ProductInfluencer, record.id)
        assert row is not None
        assert row.follow_status == LeadStatus.REPLIED.value

        items, total = await EmailReplyService.list_replies(
            db,
            product_id=1,
            intent_status="follow_up",
            page=1,
            page_size=20,
        )
        assert total >= 1
        assert any(item.id == result.reply_id for item in items)


@pytest.mark.asyncio
async def test_delete_replies_removes_only_current_product_rows():
    suffix = _suffix()

    async with async_session_factory() as db:
        keep_other_product = await EmailReplyService.ingest(
            db,
            InboundEmailPayload(
                message_id=f"<delete-other-product-{suffix}@example.com>",
                from_address=f"delete_other_{suffix}@example.com",
                to_address="amazon03@ptraveldesign.com",
                subject="Other product",
                body="Keep this reply",
                received_at=datetime.now(UTC),
                product_id=2,
            ),
            source="imap",
        )
        delete_one = await EmailReplyService.ingest(
            db,
            InboundEmailPayload(
                message_id=f"<delete-one-{suffix}@example.com>",
                from_address=f"delete_one_{suffix}@example.com",
                to_address="amazon03@ptraveldesign.com",
                subject="Delete one",
                body="Remove this reply",
                received_at=datetime.now(UTC),
                product_id=1,
            ),
            source="imap",
        )
        delete_two = await EmailReplyService.ingest(
            db,
            InboundEmailPayload(
                message_id=f"<delete-two-{suffix}@example.com>",
                from_address=f"delete_two_{suffix}@example.com",
                to_address="amazon03@ptraveldesign.com",
                subject="Delete two",
                body="Remove this reply too",
                received_at=datetime.now(UTC),
                product_id=1,
            ),
            source="imap",
        )

        assert delete_one.reply_id is not None
        assert delete_two.reply_id is not None
        assert keep_other_product.reply_id is not None

        result = await EmailReplyService.delete_replies(
            db,
            product_id=1,
            reply_ids=[delete_one.reply_id, delete_two.reply_id, keep_other_product.reply_id],
        )

        assert result.deleted_count == 2
        assert await db.get(EmailReply, delete_one.reply_id) is None
        assert await db.get(EmailReply, delete_two.reply_id) is None
        assert await db.get(EmailReply, keep_other_product.reply_id) is not None


@pytest.mark.asyncio
async def test_webhook_route_requires_secret():
    from app.api.routes.email_inbound import ingest_inbound_webhook
    from app.schemas.email_reply import InboundEmailWebhookRequest

    mock_settings = Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        email_inbound_webhook_secret="test-secret",
    )
    with patch("app.api.routes.email_inbound.settings", mock_settings):
        with pytest.raises(HTTPException) as exc:
            await ingest_inbound_webhook(
                InboundEmailWebhookRequest(from_address="a@b.com", to_address="c@d.com"),
                db=None,  # type: ignore[arg-type]
                x_webhook_secret="wrong",
            )
        assert exc.value.status_code == 401
