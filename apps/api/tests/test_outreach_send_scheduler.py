"""Scheduled outreach send queue tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_email_campaign import OutreachEmailCampaign
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
    uname = f"sched_queue_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=uname,
        profile_url=f"https://instagram.com/{uname}",
        platform_unique_id=f"ig_sched_{suffix}",
        followers_count=18000,
        engagement_rate=3.2,
        bio="lifestyle creator",
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


async def _create_campaign(db, suffix: str) -> OutreachEmailCampaign:
    row = OutreachEmailCampaign(
        product_id=1,
        user_id=1,
        name=f"scheduled campaign {suffix}",
        status="running",
        daily_limit=100,
    )
    db.add(row)
    await db.flush()
    return row


async def _cleanup(db, *, influencer_ids: list[int], global_ids: list[int], campaign_id: int | None = None) -> None:
    await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id.in_(influencer_ids)))
    await db.execute(delete(OutreachSendQueueItem).where(OutreachSendQueueItem.product_influencer_id.in_(influencer_ids)))
    if campaign_id:
        await db.execute(delete(OutreachEmailCampaign).where(OutreachEmailCampaign.id == campaign_id))
    await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id.in_(influencer_ids)))
    await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id.in_(global_ids)))
    await db.commit()


def test_calculate_scheduled_times_respects_interval_window_and_weekdays():
    from app.schemas.outreach_email import OutreachScheduleConfig
    from app.services.outreach_send_scheduler import calculate_scheduled_times

    times = calculate_scheduled_times(
        3,
        OutreachScheduleConfig(
            start_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            timezone="UTC",
            send_window_start="09:00",
            send_window_end="09:10",
            interval_minutes=5,
            daily_limit=10,
            hourly_limit=10,
            weekdays_only=True,
        ),
    )
    assert [item.isoformat() for item in times] == [
        "2026-06-01T09:00:00+00:00",
        "2026-06-01T09:05:00+00:00",
        "2026-06-02T09:00:00+00:00",
    ]

    weekend = calculate_scheduled_times(
        1,
        OutreachScheduleConfig(
            start_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
            timezone="UTC",
            send_window_start="09:00",
            send_window_end="18:00",
            weekdays_only=True,
        ),
    )
    assert weekend[0].date().isoformat() == "2026-06-08"


def test_schedule_endpoint_creates_scheduled_queue_items():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = _suffix()
        async with async_session_factory() as db:
            influencer = await _create_influencer(db, suffix=suffix, email=f"sched_{suffix}@example.com")
            campaign = await _create_campaign(db, suffix)
            await db.commit()
            influencer_id = influencer.id
            global_id = influencer.global_influencer_id
            campaign_id = campaign.id

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/outreach-send-queue/schedule",
                    headers={"X-User-Id": "1", "X-Product-Id": "1"},
                    json={
                        "campaign_id": campaign_id,
                        "items": [
                            {
                                "product_influencer_id": influencer_id,
                                "recipient": f"sched_{suffix}@example.com",
                                "subject": "Scheduled subject",
                                "body": "Scheduled body",
                            }
                        ],
                        "schedule_config": {
                            "start_at": "2026-06-01T09:00:00Z",
                            "timezone": "UTC",
                            "send_window_start": "09:00",
                            "send_window_end": "18:00",
                            "interval_minutes": 5,
                        },
                    },
                )
            assert response.status_code == 201, response.text
            data = response.json()
            assert data["created_count"] == 1
            assert data["skipped_count"] == 0

            async with async_session_factory() as db:
                row = await db.scalar(
                    select(OutreachSendQueueItem).where(
                        OutreachSendQueueItem.product_influencer_id == influencer_id
                    )
                )
                assert row is not None
                assert row.status == "scheduled"
                assert row.campaign_id == campaign_id
                assert row.scheduled_at is not None
        finally:
            async with async_session_factory() as db:
                await _cleanup(db, influencer_ids=[influencer_id], global_ids=[global_id], campaign_id=campaign_id)

    asyncio.run(_run())


def test_process_due_queue_sends_due_only_and_skips_paused_cancelled():
    async def _run() -> None:
        from app.services.outreach_send_scheduler import process_due_email_queue

        suffix = _suffix()
        now = datetime.now(UTC)
        async with async_session_factory() as db:
            due = await _create_influencer(db, suffix=f"{suffix}due", email=f"due_{suffix}@example.com")
            future = await _create_influencer(db, suffix=f"{suffix}future", email=f"future_{suffix}@example.com")
            paused = await _create_influencer(db, suffix=f"{suffix}paused", email=f"paused_{suffix}@example.com")
            cancelled = await _create_influencer(db, suffix=f"{suffix}cancel", email=f"cancel_{suffix}@example.com")
            rows = [
                OutreachSendQueueItem(product_id=1, user_id=1, product_influencer_id=due.id, recipient=f"due_{suffix}@example.com", subject="Due", body="Due", status="scheduled", scheduled_at=now - timedelta(minutes=1)),
                OutreachSendQueueItem(product_id=1, user_id=1, product_influencer_id=future.id, recipient=f"future_{suffix}@example.com", subject="Future", body="Future", status="scheduled", scheduled_at=now + timedelta(hours=1)),
                OutreachSendQueueItem(product_id=1, user_id=1, product_influencer_id=paused.id, recipient=f"paused_{suffix}@example.com", subject="Paused", body="Paused", status="paused", scheduled_at=now - timedelta(minutes=1)),
                OutreachSendQueueItem(product_id=1, user_id=1, product_influencer_id=cancelled.id, recipient=f"cancel_{suffix}@example.com", subject="Cancel", body="Cancel", status="cancelled", scheduled_at=now - timedelta(minutes=1)),
            ]
            db.add_all(rows)
            await db.commit()
            ids = [due.id, future.id, paused.id, cancelled.id]
            global_ids = [due.global_influencer_id, future.global_influencer_id, paused.global_influencer_id, cancelled.global_influencer_id]

        try:
            with patch(
                "app.services.outreach_send_scheduler.OutreachSendQueueService._process_one",
                new_callable=AsyncMock,
                return_value="sent",
            ) as mocked:
                result = await process_due_email_queue(limit=20)

            assert result.processed == 1
            assert result.sent == 1
            assert mocked.await_count == 1

            async with async_session_factory() as db:
                statuses = {
                    row.product_influencer_id: row.status
                    for row in (
                        await db.execute(
                            select(OutreachSendQueueItem).where(
                                OutreachSendQueueItem.product_influencer_id.in_(ids)
                            )
                        )
                    ).scalars().all()
                }
                assert statuses[due.id] == "sent"
                assert statuses[future.id] == "scheduled"
                assert statuses[paused.id] == "paused"
                assert statuses[cancelled.id] == "cancelled"
        finally:
            async with async_session_factory() as db:
                await _cleanup(db, influencer_ids=ids, global_ids=global_ids)

    asyncio.run(_run())


def test_process_due_queue_retries_then_marks_failed():
    async def _run() -> None:
        from app.services.outreach_send_scheduler import process_due_email_queue

        suffix = _suffix()
        now = datetime.now(UTC)
        async with async_session_factory() as db:
            retry = await _create_influencer(db, suffix=f"{suffix}retry", email=f"retry_{suffix}@example.com")
            final = await _create_influencer(db, suffix=f"{suffix}final", email=f"final_{suffix}@example.com")
            db.add_all(
                [
                    OutreachSendQueueItem(product_id=1, user_id=1, product_influencer_id=retry.id, recipient=f"retry_{suffix}@example.com", subject="Retry", body="Retry", status="scheduled", scheduled_at=now - timedelta(minutes=1), retry_count=0, max_retries=3),
                    OutreachSendQueueItem(product_id=1, user_id=1, product_influencer_id=final.id, recipient=f"final_{suffix}@example.com", subject="Final", body="Final", status="scheduled", scheduled_at=now - timedelta(minutes=1), retry_count=3, max_retries=3),
                ]
            )
            await db.commit()
            ids = [retry.id, final.id]
            global_ids = [retry.global_influencer_id, final.global_influencer_id]

        try:
            with patch(
                "app.services.outreach_send_scheduler.OutreachSendQueueService._process_one",
                new_callable=AsyncMock,
                return_value="failed",
            ):
                result = await process_due_email_queue(limit=20)

            assert result.failed == 2
            async with async_session_factory() as db:
                rows = {
                    row.product_influencer_id: row
                    for row in (
                        await db.execute(
                            select(OutreachSendQueueItem).where(
                                OutreachSendQueueItem.product_influencer_id.in_(ids)
                            )
                        )
                    ).scalars().all()
                }
                assert rows[retry.id].status == "scheduled"
                assert rows[retry.id].retry_count == 1
                assert rows[retry.id].next_retry_at is not None
                assert rows[final.id].status == "failed"
                assert rows[final.id].failed_at is not None
        finally:
            async with async_session_factory() as db:
                await _cleanup(db, influencer_ids=ids, global_ids=global_ids)

    asyncio.run(_run())


def test_send_now_locks_single_item_and_marks_sent():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = _suffix()
        async with async_session_factory() as db:
            influencer = await _create_influencer(db, suffix=suffix, email=f"now_{suffix}@example.com")
            row = OutreachSendQueueItem(
                product_id=1,
                user_id=1,
                product_influencer_id=influencer.id,
                recipient=f"now_{suffix}@example.com",
                subject="Now",
                body="Now",
                status="scheduled",
                scheduled_at=datetime.now(UTC) + timedelta(days=1),
            )
            db.add(row)
            await db.commit()
            item_id = row.id
            influencer_id = influencer.id
            global_id = influencer.global_influencer_id

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch(
                    "app.services.outreach_send_scheduler.OutreachSendQueueService._process_one",
                    new_callable=AsyncMock,
                    return_value="sent",
                ):
                    response = await client.post(
                        f"/api/outreach-send-queue/{item_id}/send-now",
                        headers={"X-User-Id": "1", "X-Product-Id": "1"},
                    )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "sent"
        finally:
            async with async_session_factory() as db:
                await _cleanup(db, influencer_ids=[influencer_id], global_ids=[global_id])

    asyncio.run(_run())
