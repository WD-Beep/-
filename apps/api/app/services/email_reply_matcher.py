"""Match inbound replies to outbound outreach records."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.services.email_reply_utils import (
    extract_email_address,
    normalize_message_id,
    normalize_subject,
)
from app.services.outreach_recipient import is_sender_address, normalize_email_address


@dataclass
class ReplyMatchResult:
    product_id: int
    product_influencer_id: int | None
    email_log_id: int | None
    campaign_id: int | None
    match_method: str


def _inbound_addresses() -> set[str]:
    addresses: set[str] = set()
    for candidate in (
        settings.inbound_email_address,
        settings.imap_user,
        settings.smtp_from,
        settings.smtp_user,
    ):
        normalized = normalize_email_address(candidate)
        if normalized:
            addresses.add(normalized)
    return addresses


class EmailReplyMatcher:
    @staticmethod
    async def match(
        db: AsyncSession,
        *,
        from_address: str,
        to_address: str,
        subject: str,
        in_reply_to: str | None,
        references: list[str],
        product_id_hint: int | None = None,
    ) -> ReplyMatchResult | None:
        sender = extract_email_address(from_address)
        recipient = extract_email_address(to_address)
        if not sender or is_sender_address(sender):
            return None

        inbound_to = _inbound_addresses()
        if product_id_hint is None and inbound_to and recipient and recipient not in inbound_to:
            # Allow missing/unknown to-address when thread headers exist.
            if not in_reply_to and not references:
                return None

        thread_ids = [
            item
            for item in (
                normalize_message_id(in_reply_to),
                *[normalize_message_id(ref) for ref in references],
            )
            if item
        ]

        if thread_ids:
            matched = await EmailReplyMatcher._match_by_message_ids(
                db,
                thread_ids=thread_ids,
                sender=sender,
                product_id_hint=product_id_hint,
            )
            if matched:
                return matched

        matched = await EmailReplyMatcher._match_by_sender_and_subject(
            db,
            sender=sender,
            subject=subject,
            product_id_hint=product_id_hint,
        )
        if matched:
            return matched

        return await EmailReplyMatcher._match_by_sender_only(
            db,
            sender=sender,
            product_id_hint=product_id_hint,
        )

    @staticmethod
    async def _match_by_message_ids(
        db: AsyncSession,
        *,
        thread_ids: list[str],
        sender: str,
        product_id_hint: int | None,
    ) -> ReplyMatchResult | None:
        normalized_ids = [item.lower() for item in thread_ids if item]
        if not normalized_ids:
            return None

        query = (
            select(EmailLog)
            .where(
                func.lower(EmailLog.message_id).in_(normalized_ids),
                EmailLog.status == EmailLogStatus.SENT.value,
            )
            .order_by(EmailLog.sent_at.desc())
            .limit(5)
        )
        if product_id_hint is not None:
            query = query.where(EmailLog.product_id == product_id_hint)

        logs = (await db.scalars(query)).all()
        for log in logs:
            pair = await EmailReplyMatcher._validate_sender_for_log(db, log=log, sender=sender)
            if not pair:
                continue
            product_row, _global_row = pair
            campaign_id = await EmailReplyMatcher._resolve_campaign_id(db, email_log_id=log.id)
            return ReplyMatchResult(
                product_id=log.product_id or product_row.product_id,
                product_influencer_id=product_row.id,
                email_log_id=log.id,
                campaign_id=campaign_id,
                match_method="message_id",
            )
        return None

    @staticmethod
    async def _match_by_sender_and_subject(
        db: AsyncSession,
        *,
        sender: str,
        subject: str,
        product_id_hint: int | None,
    ) -> ReplyMatchResult | None:
        normalized_subject = normalize_subject(subject)
        if not normalized_subject:
            return None

        pair = await EmailReplyMatcher._find_product_influencer_by_email(
            db,
            email=sender,
            product_id_hint=product_id_hint,
        )
        if not pair:
            return None
        product_row, _global_row = pair

        query = (
            select(EmailLog)
            .where(
                EmailLog.product_influencer_id == product_row.id,
                EmailLog.status == EmailLogStatus.SENT.value,
            )
            .order_by(EmailLog.sent_at.desc())
            .limit(20)
        )
        if product_id_hint is not None:
            query = query.where(EmailLog.product_id == product_id_hint)
        else:
            query = query.where(EmailLog.product_id == product_row.product_id)

        logs = (await db.scalars(query)).all()
        for log in logs:
            if normalize_subject(log.subject) == normalized_subject:
                campaign_id = await EmailReplyMatcher._resolve_campaign_id(db, email_log_id=log.id)
                return ReplyMatchResult(
                    product_id=log.product_id or product_row.product_id,
                    product_influencer_id=product_row.id,
                    email_log_id=log.id,
                    campaign_id=campaign_id,
                    match_method="subject_thread",
                )
        return None

    @staticmethod
    async def _match_by_sender_only(
        db: AsyncSession,
        *,
        sender: str,
        product_id_hint: int | None,
    ) -> ReplyMatchResult | None:
        pair = await EmailReplyMatcher._find_product_influencer_by_email(
            db,
            email=sender,
            product_id_hint=product_id_hint,
        )
        if not pair:
            return None
        product_row, _global_row = pair

        log_query = (
            select(EmailLog)
            .where(
                EmailLog.product_influencer_id == product_row.id,
                EmailLog.status == EmailLogStatus.SENT.value,
                EmailLog.product_id == product_row.product_id,
            )
            .order_by(EmailLog.sent_at.desc())
            .limit(1)
        )
        log = await db.scalar(log_query)
        campaign_id = await EmailReplyMatcher._resolve_campaign_id(db, email_log_id=log.id if log else None)
        return ReplyMatchResult(
            product_id=product_row.product_id,
            product_influencer_id=product_row.id,
            email_log_id=log.id if log else None,
            campaign_id=campaign_id,
            match_method="sender_email",
        )

    @staticmethod
    async def _find_product_influencer_by_email(
        db: AsyncSession,
        *,
        email: str,
        product_id_hint: int | None,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile] | None:
        normalized = normalize_email_address(email)
        if not normalized:
            return None

        email_match = or_(
            func.lower(GlobalInfluencerProfile.final_email) == normalized,
            func.lower(GlobalInfluencerProfile.business_email) == normalized,
            func.lower(GlobalInfluencerProfile.public_email) == normalized,
            func.lower(GlobalInfluencerProfile.email) == normalized,
        )
        query = (
            select(ProductInfluencer, GlobalInfluencerProfile)
            .join(
                GlobalInfluencerProfile,
                ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id,
            )
            .where(email_match)
            .order_by(ProductInfluencer.updated_at.desc())
        )
        if product_id_hint is not None:
            query = query.where(ProductInfluencer.product_id == product_id_hint)

        rows = (await db.execute(query)).all()
        if not rows:
            return None
        if product_id_hint is None and len(rows) > 1:
            product_ids = {row[0].product_id for row in rows}
            if len(product_ids) > 1:
                return None
        return rows[0][0], rows[0][1]

    @staticmethod
    async def _validate_sender_for_log(
        db: AsyncSession,
        *,
        log: EmailLog,
        sender: str,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile] | None:
        if not log.product_influencer_id:
            return None
        product_row = await db.get(ProductInfluencer, log.product_influencer_id)
        if not product_row:
            return None
        global_row = await db.get(GlobalInfluencerProfile, product_row.global_influencer_id)
        if not global_row:
            return None

        sender_norm = normalize_email_address(sender)
        known = {
            normalize_email_address(value)
            for value in (
                global_row.final_email,
                global_row.business_email,
                global_row.public_email,
                global_row.email,
            )
        }
        known.discard(None)
        if sender_norm not in known:
            return None
        return product_row, global_row

    @staticmethod
    async def _resolve_campaign_id(db: AsyncSession, *, email_log_id: int | None) -> int | None:
        if not email_log_id:
            return None
        return await db.scalar(
            select(OutreachSendQueueItem.campaign_id)
            .where(OutreachSendQueueItem.email_log_id == email_log_id)
            .order_by(OutreachSendQueueItem.sent_at.desc())
            .limit(1)
        )
