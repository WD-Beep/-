# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：outreach send scheduler
"""Scheduled outreach send queue processing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.schemas.common import PaginatedResponse
from app.schemas.outreach_email import (
    OutreachQueueRescheduleRequest,
    OutreachScheduleConfig,
    OutreachScheduleRequest,
    OutreachScheduleResponse,
    OutreachSendQueueRead,
)
from app.services.outreach_send_queue_service import _resolve_sender_email, OutreachSendQueueService

SCHEDULED_STATUSES = ("queued", "scheduled")
PAUSABLE_STATUSES = ("queued", "scheduled")
CANCELLABLE_STATUSES = ("queued", "scheduled", "paused", "failed")
SEND_NOW_STATUSES = ("queued", "scheduled", "paused", "failed")


@dataclass
class DueQueueProcessResult:
    processed: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    locked: int = 0


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_window(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def _next_valid_window_start(candidate: datetime, config: OutreachScheduleConfig, tz: ZoneInfo) -> datetime:
    window_start = _parse_window(config.send_window_start)
    window_end = _parse_window(config.send_window_end)
    current = candidate.astimezone(tz)

    while True:
        if config.weekdays_only and current.weekday() >= 5:
            next_day = current.date() + timedelta(days=1)
            current = datetime.combine(next_day, window_start, tzinfo=tz)
            continue

        start = datetime.combine(current.date(), window_start, tzinfo=tz)
        end = datetime.combine(current.date(), window_end, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)

        if current < start:
            return start
        if current >= end:
            next_day = current.date() + timedelta(days=1)
            current = datetime.combine(next_day, window_start, tzinfo=tz)
            continue
        return current


def calculate_scheduled_times(count: int, config: OutreachScheduleConfig) -> list[datetime]:
    if count <= 0:
        return []

    tz = ZoneInfo(config.timezone)
    interval = timedelta(minutes=max(1, int(config.interval_minutes)))
    window_end_value = _parse_window(config.send_window_end)
    window_start_value = _parse_window(config.send_window_start)
    daily_counts: dict[str, int] = {}
    hourly_counts: dict[str, int] = {}
    times: list[datetime] = []
    candidate = _ensure_aware_utc(config.start_at).astimezone(tz)

    while len(times) < count:
        candidate = _next_valid_window_start(candidate, config, tz)
        window_end = datetime.combine(candidate.date(), window_end_value, tzinfo=tz)
        window_start = datetime.combine(candidate.date(), _parse_window(config.send_window_start), tzinfo=tz)
        if window_end <= window_start:
            window_end += timedelta(days=1)
        if candidate >= window_end:
            candidate = datetime.combine(candidate.date() + timedelta(days=1), window_start.time(), tzinfo=tz)
            continue

        day_key = candidate.date().isoformat()
        hour_key = candidate.strftime("%Y-%m-%dT%H")
        if daily_counts.get(day_key, 0) >= config.daily_limit:
            candidate = datetime.combine(candidate.date() + timedelta(days=1), window_start.time(), tzinfo=tz)
            continue
        if hourly_counts.get(hour_key, 0) >= config.hourly_limit:
            candidate = candidate.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            continue

        times.append(candidate.astimezone(UTC))
        daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
        hourly_counts[hour_key] = hourly_counts.get(hour_key, 0) + 1
        next_candidate = candidate + interval
        if next_candidate >= window_end:
            next_candidate = datetime.combine(candidate.date() + timedelta(days=1), window_start_value, tzinfo=tz)
        candidate = next_candidate

    return times


async def schedule_outreach_emails(
    db: AsyncSession,
    *,
    product_id: int,
    user_id: int,
    payload: OutreachScheduleRequest,
) -> OutreachScheduleResponse:
    scheduled_times = calculate_scheduled_times(len(payload.items), payload.schedule_config)
    created = 0
    skipped = 0
    created_times: list[datetime] = []

    for item, scheduled_at in zip(payload.items, scheduled_times, strict=True):
        if item.dedupe_key:
            existing = await db.scalar(
                select(OutreachSendQueueItem.id).where(
                    OutreachSendQueueItem.product_id == product_id,
                    OutreachSendQueueItem.dedupe_key == item.dedupe_key,
                    OutreachSendQueueItem.status.in_(("queued", "scheduled", "sending", "sent")),
                )
            )
            if existing:
                skipped += 1
                continue

        influencer = await db.scalar(
            select(ProductInfluencer).where(
                ProductInfluencer.id == item.product_influencer_id,
                ProductInfluencer.product_id == product_id,
            )
        )
        if not influencer:
            skipped += 1
            continue

        matched = [entry.model_dump() for entry in item.matched_knowledge] if item.matched_knowledge else None
        row = OutreachSendQueueItem(
            product_id=product_id,
            user_id=user_id,
            product_influencer_id=item.product_influencer_id,
            recipient=item.recipient.strip(),
            sender_email=_resolve_sender_email(),
            subject=item.subject.strip(),
            body=item.body.strip(),
            status="scheduled",
            scheduled_at=scheduled_at,
            matched_knowledge=matched,
            ai_reason=(item.ai_reason or "").strip() or None,
            allow_resend=item.allow_resend,
            campaign_id=payload.campaign_id,
            priority=item.priority,
            dedupe_key=(item.dedupe_key or "").strip() or None,
            max_retries=item.max_retries,
        )
        db.add(row)
        created += 1
        created_times.append(scheduled_at)

    await db.commit()
    return OutreachScheduleResponse(
        created_count=created,
        skipped_count=skipped,
        first_scheduled_at=min(created_times) if created_times else None,
        last_scheduled_at=max(created_times) if created_times else None,
    )


async def _lock_item(db: AsyncSession, *, item_id: int, statuses: tuple[str, ...]) -> bool:
    now = datetime.now(UTC)
    result = await db.execute(
        update(OutreachSendQueueItem)
        .where(
            OutreachSendQueueItem.id == item_id,
            OutreachSendQueueItem.status.in_(statuses),
        )
        .values(status="sending", locked_at=now)
    )
    await db.commit()
    return int(result.rowcount or 0) == 1


async def handle_send_success(db: AsyncSession, row: OutreachSendQueueItem) -> None:
    row.status = "sent"
    row.sent_at = row.sent_at or datetime.now(UTC)
    row.failed_at = None
    row.next_retry_at = None
    row.locked_at = None
    row.error_message = None
    await db.commit()


async def handle_send_failure(
    db: AsyncSession,
    row: OutreachSendQueueItem,
    *,
    error_message: str | None = None,
) -> None:
    now = datetime.now(UTC)
    max_retries = int(row.max_retries or 0)
    retry_count = int(row.retry_count or 0)
    message = error_message or row.error_message or "Send failed"
    if retry_count < max_retries:
        next_retry_count = retry_count + 1
        retry_at = now + timedelta(minutes=min(60, 5 * (2 ** (next_retry_count - 1))))
        row.status = "scheduled"
        row.retry_count = next_retry_count
        row.next_retry_at = retry_at
        row.scheduled_at = retry_at
        row.failed_at = None
    else:
        row.status = "failed"
        row.failed_at = now
        row.next_retry_at = None
    row.locked_at = None
    row.error_message = message
    await db.commit()


async def _send_locked_row(db: AsyncSession, row: OutreachSendQueueItem, *, user_id: int | None) -> str:
    campaign = await db.get(OutreachEmailCampaign, row.campaign_id) if row.campaign_id else None
    outcome = await OutreachSendQueueService._process_one(db, row=row, user_id=user_id, campaign=campaign)
    await db.refresh(row)
    if outcome == "sent":
        await handle_send_success(db, row)
    elif outcome == "failed":
        await handle_send_failure(db, row)
    else:
        row.locked_at = None
        await db.commit()
    return outcome


async def process_due_email_queue(limit: int = 20) -> DueQueueProcessResult:
    result = DueQueueProcessResult()
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        rows = await db.execute(
            select(OutreachSendQueueItem.id)
            .where(
                OutreachSendQueueItem.status == "scheduled",
                OutreachSendQueueItem.scheduled_at <= now,
                or_(
                    OutreachSendQueueItem.next_retry_at.is_(None),
                    OutreachSendQueueItem.next_retry_at <= now,
                ),
            )
            .order_by(OutreachSendQueueItem.priority.desc(), OutreachSendQueueItem.scheduled_at.asc())
            .limit(max(1, int(limit)))
        )
        item_ids = [row[0] for row in rows.all()]

        for item_id in item_ids:
            locked = await _lock_item(db, item_id=item_id, statuses=("scheduled",))
            if not locked:
                continue
            result.locked += 1
            row = await db.get(OutreachSendQueueItem, item_id)
            if not row:
                continue
            outcome = await _send_locked_row(db, row, user_id=row.user_id)
            result.processed += 1
            if outcome == "sent":
                result.sent += 1
            elif outcome == "failed":
                result.failed += 1
            else:
                result.skipped += 1

    return result


async def send_queue_item(queue_item_id: int, *, product_id: int | None = None, user_id: int | None = None) -> OutreachSendQueueRead:
    async with async_session_factory() as db:
        row = await db.get(OutreachSendQueueItem, queue_item_id)
        if not row or (product_id is not None and row.product_id != product_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue item not found")
        if row.status == "sent":
            return OutreachSendQueueRead.model_validate(row)
        if row.status == "cancelled":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled queue item cannot be sent")
        locked = await _lock_item(db, item_id=queue_item_id, statuses=SEND_NOW_STATUSES)
        if not locked:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue item is already being processed")
        row = await db.get(OutreachSendQueueItem, queue_item_id)
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue item not found")
        row.scheduled_at = datetime.now(UTC)
        await db.commit()
        await _send_locked_row(db, row, user_id=user_id or row.user_id)
        await db.refresh(row)
        return OutreachSendQueueRead.model_validate(row)


async def _bulk_update_status(
    db: AsyncSession,
    *,
    product_id: int,
    ids: list[int],
    from_statuses: tuple[str, ...],
    to_status: str,
) -> int:
    values = {"status": to_status}
    if to_status == "scheduled":
        values["locked_at"] = None
    if to_status == "cancelled":
        values["locked_at"] = None
    result = await db.execute(
        update(OutreachSendQueueItem)
        .where(
            OutreachSendQueueItem.product_id == product_id,
            OutreachSendQueueItem.id.in_(ids),
            OutreachSendQueueItem.status.in_(from_statuses),
        )
        .values(**values)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def pause_queue_items(db: AsyncSession, *, product_id: int, ids: list[int]) -> int:
    return await _bulk_update_status(
        db,
        product_id=product_id,
        ids=ids,
        from_statuses=PAUSABLE_STATUSES,
        to_status="paused",
    )


async def resume_queue_items(db: AsyncSession, *, product_id: int, ids: list[int]) -> int:
    return await _bulk_update_status(
        db,
        product_id=product_id,
        ids=ids,
        from_statuses=("paused",),
        to_status="scheduled",
    )


async def cancel_queue_items(db: AsyncSession, *, product_id: int, ids: list[int]) -> int:
    return await _bulk_update_status(
        db,
        product_id=product_id,
        ids=ids,
        from_statuses=CANCELLABLE_STATUSES,
        to_status="cancelled",
    )


async def get_queue_item(db: AsyncSession, *, product_id: int, item_id: int) -> OutreachSendQueueRead:
    row = await db.scalar(
        select(OutreachSendQueueItem).where(
            OutreachSendQueueItem.product_id == product_id,
            OutreachSendQueueItem.id == item_id,
        )
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue item not found")
    return OutreachSendQueueRead.model_validate(row)


async def reschedule_queue_item(
    db: AsyncSession,
    *,
    product_id: int,
    item_id: int,
    payload: OutreachQueueRescheduleRequest,
) -> OutreachSendQueueRead:
    row = await db.scalar(
        select(OutreachSendQueueItem).where(
            OutreachSendQueueItem.product_id == product_id,
            OutreachSendQueueItem.id == item_id,
        )
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue item not found")
    if row.status in ("sent", "cancelled", "sending"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Queue item cannot be rescheduled")
    row.status = "scheduled"
    row.scheduled_at = _ensure_aware_utc(payload.scheduled_at)
    row.next_retry_at = None
    row.locked_at = None
    row.error_message = None
    await db.commit()
    await db.refresh(row)
    return OutreachSendQueueRead.model_validate(row)


async def list_scheduled_queue(
    db: AsyncSession,
    *,
    product_id: int,
    campaign_id: int | None,
    status_filter: str | None,
    recipient_email: str | None,
    scheduled_from: datetime | None,
    scheduled_to: datetime | None,
    page: int,
    page_size: int,
) -> PaginatedResponse[OutreachSendQueueRead]:
    query = select(OutreachSendQueueItem).where(OutreachSendQueueItem.product_id == product_id)
    if campaign_id is not None:
        query = query.where(OutreachSendQueueItem.campaign_id == campaign_id)
    if status_filter:
        query = query.where(OutreachSendQueueItem.status == status_filter)
    if recipient_email:
        query = query.where(OutreachSendQueueItem.recipient.ilike(f"%{recipient_email.strip()}%"))
    if scheduled_from:
        query = query.where(OutreachSendQueueItem.scheduled_at >= _ensure_aware_utc(scheduled_from))
    if scheduled_to:
        query = query.where(OutreachSendQueueItem.scheduled_at <= _ensure_aware_utc(scheduled_to))

    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.execute(
        query.order_by(
            OutreachSendQueueItem.scheduled_at.desc().nullslast(),
            OutreachSendQueueItem.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PaginatedResponse(
        items=[OutreachSendQueueRead.model_validate(row) for row in rows.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )
