"""Follow-up scheduling and reply-stop tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _create_influencer(db, *, suffix: str, email: str) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    username = f"followup_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=username,
        profile_url=f"https://instagram.com/{username}",
        platform_unique_id=f"ig_followup_{suffix}",
        followers_count=12000,
        engagement_rate=2.4,
        bio="creator",
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


async def _create_email_log(
    db,
    *,
    influencer: ProductInfluencer,
    recipient: str,
    sent_at: datetime | None = None,
) -> EmailLog:
    row = EmailLog(
        product_id=1,
        user_id=1,
        product_influencer_id=influencer.id,
        sender_email="sender@example.com",
        influencer_username=f"@{influencer.id}",
        recipients=[recipient],
        subject="Initial outreach",
        body="Hello",
        status=EmailLogStatus.SENT.value,
        sent_at=sent_at or datetime.now(UTC) - timedelta(days=4),
        message_id=f"<followup-{_suffix()}@example.com>",
    )
    db.add(row)
    await db.flush()
    return row


async def _cleanup(db, *, influencer_ids: list[int], global_ids: list[int], log_ids: list[int]) -> None:
    await db.execute(delete(EmailReply).where(EmailReply.email_log_id.in_(log_ids)))
    await db.execute(delete(OutreachSendQueueItem).where(OutreachSendQueueItem.email_log_id.in_(log_ids)))
    await db.execute(delete(OutreachSendQueueItem).where(OutreachSendQueueItem.outreach_record_id.in_(log_ids)))
    await db.execute(delete(EmailLog).where(EmailLog.id.in_(log_ids)))
    await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id.in_(influencer_ids)))
    await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id.in_(global_ids)))
    await db.commit()


def test_schedule_follow_up_rejects_replied_record_and_allows_unreplied():
    async def _run() -> None:
        from app.services.follow_up_scheduler import schedule_follow_up_check

        suffix = _suffix()
        async with async_session_factory() as db:
            influencer = await _create_influencer(db, suffix=suffix, email=f"fu_{suffix}@example.com")
            replied = await _create_email_log(db, influencer=influencer, recipient=f"fu_{suffix}@example.com")
            unreplied = await _create_email_log(db, influencer=influencer, recipient=f"fu_{suffix}@example.com")
            replied.has_replied = True
            replied.stop_follow_up = True
            replied.stop_reason = "replied"
            await db.commit()
            ids = [influencer.id]
            global_ids = [influencer.global_influencer_id]
            log_ids = [replied.id, unreplied.id]

        try:
            async with async_session_factory() as db:
                try:
                    await schedule_follow_up_check(db, outreach_record_id=replied.id, product_id=1)
                    raise AssertionError("expected replied record to be rejected")
                except ValueError as exc:
                    assert "replied" in str(exc).lower()

                updated = await schedule_follow_up_check(
                    db,
                    outreach_record_id=unreplied.id,
                    product_id=1,
                    after_days=3,
                    max_followups=2,
                )
                assert updated.follow_up_status == "pending_check"
                assert updated.follow_up_count == 0
                assert updated.next_follow_up_at is not None
        finally:
            async with async_session_factory() as db:
                await _cleanup(db, influencer_ids=ids, global_ids=global_ids, log_ids=log_ids)

    asyncio.run(_run())


def test_process_due_follow_ups_creates_queue_and_stops_replied_records():
    async def _run() -> None:
        from app.services.follow_up_scheduler import process_due_follow_ups

        suffix = _suffix()
        due_time = datetime.now(UTC) - timedelta(minutes=5)
        async with async_session_factory() as db:
            influencer = await _create_influencer(db, suffix=suffix, email=f"due_{suffix}@example.com")
            due = await _create_email_log(db, influencer=influencer, recipient=f"due_{suffix}@example.com")
            replied = await _create_email_log(db, influencer=influencer, recipient=f"due_{suffix}@example.com")
            due.follow_up_status = "pending_check"
            due.next_follow_up_at = due_time
            due.follow_up_count = 0
            replied.follow_up_status = "pending_check"
            replied.next_follow_up_at = due_time
            replied.has_replied = True
            await db.commit()
            ids = [influencer.id]
            global_ids = [influencer.global_influencer_id]
            log_ids = [due.id, replied.id]

        try:
            result = await process_due_follow_ups(limit=10)
            assert result.created == 1
            assert result.stopped == 1

            async with async_session_factory() as db:
                queue = await db.scalar(
                    select(OutreachSendQueueItem).where(
                        OutreachSendQueueItem.outreach_record_id == due.id,
                        OutreachSendQueueItem.queue_type == "follow_up",
                    )
                )
                assert queue is not None
                assert queue.follow_up_step == 1
                assert queue.should_skip_if_replied is True
                stopped = await db.get(EmailLog, replied.id)
                assert stopped is not None
                assert stopped.follow_up_status == "stopped"
                assert stopped.stop_follow_up is True
                assert stopped.stop_reason == "replied"
        finally:
            async with async_session_factory() as db:
                await _cleanup(db, influencer_ids=ids, global_ids=global_ids, log_ids=log_ids)

    asyncio.run(_run())


def test_reply_ingest_marks_record_replied_and_cancels_follow_up_queue():
    async def _run() -> None:
        from app.schemas.email_reply import InboundEmailPayload
        from app.services.email_reply_service import EmailReplyService

        suffix = _suffix()
        async with async_session_factory() as db:
            influencer = await _create_influencer(db, suffix=suffix, email=f"reply_{suffix}@example.com")
            log = await _create_email_log(db, influencer=influencer, recipient=f"reply_{suffix}@example.com")
            queue = OutreachSendQueueItem(
                product_id=1,
                user_id=1,
                product_influencer_id=influencer.id,
                recipient=f"reply_{suffix}@example.com",
                subject="Re: Initial outreach",
                body="Follow-up",
                status="scheduled",
                scheduled_at=datetime.now(UTC) + timedelta(days=1),
                queue_type="follow_up",
                follow_up_step=1,
                outreach_record_id=log.id,
                should_skip_if_replied=True,
            )
            db.add(queue)
            await db.commit()
            ids = [influencer.id]
            global_ids = [influencer.global_influencer_id]
            log_ids = [log.id]

        try:
            async with async_session_factory() as db:
                result = await EmailReplyService.ingest(
                    db,
                    InboundEmailPayload(
                        message_id=f"<reply-{suffix}@example.com>",
                        in_reply_to=log.message_id,
                        references=[],
                        from_address=f"reply_{suffix}@example.com",
                        to_address="sender@example.com",
                        subject="Re: Initial outreach",
                        body="Thanks, interested.",
                        received_at=datetime.now(UTC),
                        product_id=1,
                    ),
                    source="imap",
                )
                assert result.status == "ingested"

            async with async_session_factory() as db:
                updated = await db.get(EmailLog, log.id)
                assert updated is not None
                assert updated.has_replied is True
                assert updated.follow_up_status == "stopped"
                assert updated.stop_follow_up is True
                assert updated.stop_reason == "replied"
                queue_row = await db.scalar(
                    select(OutreachSendQueueItem).where(
                        OutreachSendQueueItem.outreach_record_id == log.id,
                        OutreachSendQueueItem.queue_type == "follow_up",
                    )
                )
                assert queue_row is not None
                assert queue_row.status in {"cancelled", "skipped"}
        finally:
            async with async_session_factory() as db:
                await _cleanup(db, influencer_ids=ids, global_ids=global_ids, log_ids=log_ids)

    asyncio.run(_run())


def test_follow_up_queue_skips_if_record_replied_before_smtp():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            influencer = await _create_influencer(db, suffix=suffix, email=f"skip_{suffix}@example.com")
            log = await _create_email_log(db, influencer=influencer, recipient=f"skip_{suffix}@example.com")
            log.has_replied = True
            log.stop_follow_up = True
            row = OutreachSendQueueItem(
                product_id=1,
                user_id=1,
                product_influencer_id=influencer.id,
                recipient=f"skip_{suffix}@example.com",
                subject="Re: Initial outreach",
                body="Follow-up",
                status="scheduled",
                scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
                queue_type="follow_up",
                follow_up_step=1,
                outreach_record_id=log.id,
                should_skip_if_replied=True,
            )
            db.add(row)
            await db.commit()
            queue_id = row.id
            ids = [influencer.id]
            global_ids = [influencer.global_influencer_id]
            log_ids = [log.id]

        try:
            from app.services.outreach_send_scheduler import send_queue_item

            with patch("app.services.email.EmailService._send_message", new_callable=AsyncMock) as mocked_send:
                result = await send_queue_item(queue_id, product_id=1, user_id=1)
            assert result.status == "skipped"
            assert "replied" in (result.error_message or "").lower()
            mocked_send.assert_not_awaited()
        finally:
            async with async_session_factory() as db:
                await _cleanup(db, influencer_ids=ids, global_ids=global_ids, log_ids=log_ids)

    asyncio.run(_run())
