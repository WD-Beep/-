"""Follow-up scheduling for outreach email logs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer

FOLLOW_UP_SKIP_MESSAGE = "Recipient already replied; follow-up skipped"


@dataclass
class FollowUpProcessResult:
    checked: int = 0
    created: int = 0
    stopped: int = 0
    skipped: int = 0


@dataclass
class BulkFollowUpResult:
    requested_count: int
    created_count: int
    skipped_count: int
    created_record_ids: list[int]
    queue_item_ids: list[int]
    skip_reasons: dict[int, str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resolve_sender_email() -> str | None:
    return (settings.smtp_from or settings.smtp_user or "").strip() or None


async def _load_outreach_record(db: AsyncSession, *, record_id: int, product_id: int | None = None) -> EmailLog:
    query = select(EmailLog).where(EmailLog.id == record_id)
    if product_id is not None:
        query = query.where(EmailLog.product_id == product_id)
    record = await db.scalar(query)
    if not record:
        raise ValueError("Outreach record not found")
    return record


def _reply_summary(text: str | None) -> str | None:
    if not text:
        return None
    compact = " ".join(text.split())
    return compact[:500] if compact else None


async def schedule_follow_up_check(
    db: AsyncSession,
    *,
    outreach_record_id: int,
    product_id: int | None = None,
    after_days: int = 3,
    step: int = 1,
    max_followups: int = 2,
) -> EmailLog:
    record = await _load_outreach_record(db, record_id=outreach_record_id, product_id=product_id)
    if record.has_replied:
        raise ValueError("Outreach record has already replied")
    if record.stop_follow_up:
        raise ValueError("Follow-up is stopped")
    if record.status != EmailLogStatus.SENT.value:
        raise ValueError("Only sent outreach records can schedule follow-up")

    base = record.sent_at or _utc_now()
    record.follow_up_status = "pending_check"
    record.next_follow_up_at = _ensure_aware_utc(base) + timedelta(days=max(0, int(after_days)))
    record.follow_up_count = max(0, int(record.follow_up_count or 0))
    record.max_followups = max(1, int(max_followups))
    record.stop_follow_up = False
    record.stop_reason = None
    await db.commit()
    await db.refresh(record)
    return record


def build_follow_up_email(record: EmailLog, step: int) -> tuple[str, str]:
    original_subject = record.subject or "Collaboration"
    subject = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"
    name = (record.influencer_username or "").lstrip("@") or "there"
    brand_or_product = "our brand"
    sender_name = (_resolve_sender_email() or "the team").split("@")[0]
    if step <= 1:
        body = (
            f"Hi {name},\n\n"
            "Just wanted to follow up on my previous note in case it got buried.\n\n"
            f"I thought there could be a good fit between your content and {brand_or_product}. "
            "If you're open to collaborations, I'd be happy to share more details.\n\n"
            f"Best,\n{sender_name}"
        )
    else:
        body = (
            f"Hi {name},\n\n"
            "Just checking in one last time. If this is not the right fit, no worries at all.\n\n"
            "Thanks for taking a look, and I hope we can connect another time.\n\n"
            f"Best,\n{sender_name}"
        )
    return subject, body


async def cancel_followups_for_replied_record(
    db: AsyncSession,
    *,
    outreach_record_id: int,
    status: str = "cancelled",
) -> int:
    result = await db.execute(
        update(OutreachSendQueueItem)
        .where(
            OutreachSendQueueItem.outreach_record_id == outreach_record_id,
            OutreachSendQueueItem.queue_type == "follow_up",
            OutreachSendQueueItem.status.in_(("scheduled", "paused", "failed")),
        )
        .values(status=status, error_message=FOLLOW_UP_SKIP_MESSAGE, locked_at=None)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def mark_record_replied(
    db: AsyncSession,
    *,
    outreach_record_id: int,
    product_id: int | None = None,
    reply_id: int | None = None,
    replied_at: datetime | None = None,
    reply_summary: str | None = None,
) -> EmailLog:
    record = await _load_outreach_record(db, record_id=outreach_record_id, product_id=product_id)
    record.has_replied = True
    record.replied_at = replied_at or _utc_now()
    record.reply_email_log_id = reply_id
    record.reply_summary = _reply_summary(reply_summary)
    record.follow_up_status = "stopped"
    record.stop_follow_up = True
    record.stop_reason = "replied"
    await db.commit()
    await cancel_followups_for_replied_record(db, outreach_record_id=record.id, status="cancelled")
    await db.refresh(record)
    return record


async def mark_record_unreplied(
    db: AsyncSession,
    *,
    outreach_record_id: int,
    product_id: int | None = None,
) -> EmailLog:
    record = await _load_outreach_record(db, record_id=outreach_record_id, product_id=product_id)
    record.has_replied = False
    record.replied_at = None
    record.reply_email_log_id = None
    record.reply_summary = None
    if record.follow_up_status == "stopped" and record.stop_reason == "replied":
        record.follow_up_status = "none"
    record.stop_follow_up = False
    record.stop_reason = None
    await db.commit()
    await db.refresh(record)
    return record


async def stop_follow_up(
    db: AsyncSession,
    *,
    outreach_record_id: int,
    product_id: int | None = None,
    reason: str = "manually_stopped",
) -> EmailLog:
    record = await _load_outreach_record(db, record_id=outreach_record_id, product_id=product_id)
    record.stop_follow_up = True
    record.follow_up_status = "stopped"
    record.stop_reason = reason
    await db.commit()
    await cancel_followups_for_replied_record(db, outreach_record_id=record.id, status="cancelled")
    await db.refresh(record)
    return record


async def _create_follow_up_queue(db: AsyncSession, record: EmailLog) -> bool:
    if not record.product_id or not record.product_influencer_id:
        record.follow_up_status = "failed"
        record.stop_reason = "invalid_email"
        return False
    product_row = await db.get(ProductInfluencer, record.product_influencer_id)
    if not product_row:
        record.follow_up_status = "failed"
        record.stop_reason = "invalid_email"
        return False
    global_row = await db.get(GlobalInfluencerProfile, product_row.global_influencer_id)
    recipient = (record.recipients or [None])[0]
    if not global_row or not recipient:
        record.follow_up_status = "failed"
        record.stop_reason = "invalid_email"
        return False

    step = int(record.follow_up_count or 0) + 1
    subject, body = build_follow_up_email(record, step)
    row = OutreachSendQueueItem(
        product_id=record.product_id,
        user_id=record.user_id or 1,
        product_influencer_id=record.product_influencer_id,
        recipient=recipient,
        sender_email=_resolve_sender_email(),
        subject=subject,
        body=body,
        status="scheduled",
        scheduled_at=_utc_now(),
        generated_by_ai=False,
        allow_resend=True,
        campaign_id=None,
        email_log_id=None,
        queue_type="follow_up",
        follow_up_step=step,
        outreach_record_id=record.id,
        should_skip_if_replied=True,
    )
    db.add(row)
    record.follow_up_count = step
    record.follow_up_status = "scheduled"
    record.last_outbound_at = _utc_now()
    if step >= int(record.max_followups or 2):
        record.next_follow_up_at = None
    else:
        record.next_follow_up_at = _utc_now() + timedelta(days=7)
        record.follow_up_status = "pending_check"
    return True


def _skip_reason_for_bulk_follow_up(record: EmailLog) -> str | None:
    if record.status != EmailLogStatus.SENT.value:
        return "not_sent"
    if record.has_replied:
        return "already_replied"
    if record.stop_follow_up:
        return "follow_up_stopped"
    if int(record.follow_up_count or 0) >= int(record.max_followups or 2):
        return "max_followups_reached"
    if not record.product_id or not record.product_influencer_id:
        return "missing_influencer"
    recipient = (record.recipients or [None])[0]
    if not recipient:
        return "missing_email"
    return None


async def _has_active_follow_up_queue(db: AsyncSession, record_id: int) -> bool:
    existing = await db.scalar(
        select(OutreachSendQueueItem.id)
        .where(
            OutreachSendQueueItem.outreach_record_id == record_id,
            OutreachSendQueueItem.queue_type == "follow_up",
            OutreachSendQueueItem.status.in_(("queued", "scheduled", "sending", "paused")),
        )
        .limit(1)
    )
    return existing is not None


async def bulk_create_second_follow_ups(
    db: AsyncSession,
    *,
    product_id: int,
    user_id: int | None,
    record_ids: list[int],
) -> BulkFollowUpResult:
    unique_ids = list(dict.fromkeys(int(record_id) for record_id in record_ids))
    if not unique_ids:
        return BulkFollowUpResult(
            requested_count=0,
            created_count=0,
            skipped_count=0,
            created_record_ids=[],
            queue_item_ids=[],
            skip_reasons={},
        )

    rows = (
        await db.scalars(
            select(EmailLog)
            .where(
                EmailLog.id.in_(unique_ids),
                EmailLog.product_id == product_id,
            )
            .order_by(EmailLog.id.asc())
        )
    ).all()
    records_by_id = {row.id: row for row in rows}

    created_record_ids: list[int] = []
    queue_item_ids: list[int] = []
    skip_reasons: dict[int, str] = {}
    now = _utc_now()

    for record_id in unique_ids:
        record = records_by_id.get(record_id)
        if not record:
            skip_reasons[record_id] = "not_found"
            continue

        reason = _skip_reason_for_bulk_follow_up(record)
        if reason:
            skip_reasons[record.id] = reason
            continue
        if await _has_active_follow_up_queue(db, record.id):
            skip_reasons[record.id] = "already_queued"
            continue

        step = max(2, int(record.follow_up_count or 0) + 1)
        subject, body = build_follow_up_email(record, step)
        queue = OutreachSendQueueItem(
            product_id=record.product_id,
            user_id=user_id or record.user_id,
            product_influencer_id=record.product_influencer_id,
            recipient=(record.recipients or [""])[0],
            sender_email=_resolve_sender_email(),
            subject=subject,
            body=body,
            status="scheduled",
            scheduled_at=now,
            generated_by_ai=False,
            allow_resend=True,
            queue_type="follow_up",
            follow_up_step=step,
            outreach_record_id=record.id,
            should_skip_if_replied=True,
        )
        db.add(queue)
        await db.flush()
        record.follow_up_count = max(1, int(record.follow_up_count or 0) + 1)
        record.follow_up_status = "scheduled"
        record.last_outbound_at = now
        record.next_follow_up_at = None
        created_record_ids.append(record.id)
        queue_item_ids.append(queue.id)

    await db.commit()
    return BulkFollowUpResult(
        requested_count=len(unique_ids),
        created_count=len(created_record_ids),
        skipped_count=len(skip_reasons),
        created_record_ids=created_record_ids,
        queue_item_ids=queue_item_ids,
        skip_reasons=skip_reasons,
    )


async def process_due_follow_ups(limit: int = 50) -> FollowUpProcessResult:
    result = FollowUpProcessResult()
    now = _utc_now()
    async with async_session_factory() as db:
        rows = (
            await db.scalars(
                select(EmailLog)
                .where(
                    EmailLog.follow_up_status == "pending_check",
                    EmailLog.next_follow_up_at <= now,
                    EmailLog.stop_follow_up.is_(False),
                    EmailLog.follow_up_count < EmailLog.max_followups,
                )
                .order_by(EmailLog.next_follow_up_at.asc())
                .limit(max(1, int(limit)))
            )
        ).all()

        for record in rows:
            result.checked += 1
            if record.has_replied:
                record.follow_up_status = "stopped"
                record.stop_follow_up = True
                record.stop_reason = "replied"
                result.stopped += 1
                continue
            created = await _create_follow_up_queue(db, record)
            if created:
                result.created += 1
            else:
                result.skipped += 1

        await db.commit()
    return result


async def should_skip_follow_up_queue(db: AsyncSession, row: OutreachSendQueueItem) -> bool:
    if row.queue_type != "follow_up" and not row.should_skip_if_replied:
        return False
    if not row.outreach_record_id:
        return False
    record = await db.get(EmailLog, row.outreach_record_id)
    return bool(record and (record.has_replied or record.stop_follow_up))


async def mark_follow_up_queue_skipped(db: AsyncSession, row: OutreachSendQueueItem) -> None:
    row.status = "skipped"
    row.error_message = FOLLOW_UP_SKIP_MESSAGE
    row.locked_at = None
    await db.commit()
