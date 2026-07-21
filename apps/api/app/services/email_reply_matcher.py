# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：email reply matcher
"""Match inbound replies to outbound outreach records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_campaign_recipient import OutreachCampaignRecipient
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
    match_confidence: str = "medium"
    candidates: list[dict] = field(default_factory=list)


GENERIC_LOCAL_PARTS = {
    "support",
    "contact",
    "hello",
    "info",
    "service",
    "noreply",
    "no-reply",
}


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


def _is_generic_address(email: str | None) -> bool:
    normalized = normalize_email_address(email)
    if not normalized or "@" not in normalized:
        return False
    local = normalized.split("@", 1)[0]
    return local in GENERIC_LOCAL_PARTS


def _merge_reply_match_meta(raw_headers: dict | None, meta: dict) -> dict:
    headers = dict(raw_headers or {})
    headers["reply_match"] = meta
    return headers


def reply_match_meta(result: ReplyMatchResult | None, *, status: str = "matched") -> dict:
    if not result:
        return {"status": "unmatched"}
    return {
        "status": status,
        "confidence": result.match_confidence,
        "reason": result.match_method,
        "product_influencer_id": result.product_influencer_id,
        "campaign_id": result.campaign_id,
        "email_log_id": result.email_log_id,
        "candidates": result.candidates,
    }


def with_reply_match_meta(raw_headers: dict | None, meta: dict) -> dict:
    return _merge_reply_match_meta(raw_headers, meta)


def _candidate_email(global_row: GlobalInfluencerProfile) -> str | None:
    for value in (
        global_row.final_email,
        global_row.business_email,
        global_row.public_email,
        global_row.email,
    ):
        normalized = normalize_email_address(value)
        if normalized:
            return normalized
    return None


def _candidate_payload(
    product_row: ProductInfluencer,
    global_row: GlobalInfluencerProfile,
    *,
    reason: str,
    matched_text: str | None = None,
    campaign_id: int | None = None,
) -> dict:
    return {
        "product_influencer_id": product_row.id,
        "display_name": global_row.display_name,
        "username": global_row.username,
        "email": _candidate_email(global_row),
        "campaign_id": campaign_id,
        "reason": reason,
        "matched_text": matched_text,
    }


def _extract_name_tokens(*values: str | None) -> list[str]:
    text = "\n".join(value for value in values if value)
    if not text:
        return []
    candidates: list[str] = []
    patterns = (
        r"(?:--|\u2014|-)\s*([A-Z][A-Za-z][A-Za-z ._-]{1,40})",
        r"(?:Best|Regards|Thanks|Cheers|Sincerely|Best wishes),?\s*\n\s*([A-Z][A-Za-z][A-Za-z ._-]{1,40})",
    )
    for pattern in patterns:
        for match in re.findall(pattern, text):
            cleaned = " ".join(match.replace("_", " ").split()).strip(" .,-")
            if 2 <= len(cleaned) <= 40:
                candidates.append(cleaned)
    return list(dict.fromkeys(candidates))[:5]


class EmailReplyMatcher:
    @staticmethod
    async def match(
        db: AsyncSession,
        *,
        from_address: str,
        to_address: str,
        subject: str,
        snippet: str | None = None,
        body: str | None = None,
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
                matched = await EmailReplyMatcher._match_by_sender_only(
                    db,
                    sender=sender,
                    subject=subject,
                    product_id_hint=product_id_hint,
                )
                if matched:
                    return matched
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
                product_id_hint=product_id_hint,
            )
            if matched:
                return matched

        matched = await EmailReplyMatcher._match_by_sender_only(
            db,
            sender=sender,
            subject=subject,
            product_id_hint=product_id_hint,
        )
        if matched:
            return matched

        matched = await EmailReplyMatcher._match_by_campaign_recipient(
            db,
            sender=sender,
            subject=subject,
            product_id_hint=product_id_hint,
        )
        if matched:
            return matched

        return await EmailReplyMatcher._match_by_unique_name_candidate(
            db,
            from_address=sender,
            subject=subject,
            snippet=snippet,
            body=body,
            product_id_hint=product_id_hint,
        )

    @staticmethod
    async def _match_by_message_ids(
        db: AsyncSession,
        *,
        thread_ids: list[str],
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
            if not log.product_influencer_id:
                continue
            product_row = await db.get(ProductInfluencer, log.product_influencer_id)
            if not product_row:
                continue
            campaign_id = await EmailReplyMatcher._resolve_campaign_id(db, email_log_id=log.id)
            return ReplyMatchResult(
                product_id=log.product_id or product_row.product_id,
                product_influencer_id=product_row.id,
                email_log_id=log.id,
                campaign_id=campaign_id,
                match_method="message_header",
                match_confidence="high",
            )
        return None

    @staticmethod
    async def _match_by_sender_only(
        db: AsyncSession,
        *,
        sender: str,
        subject: str | None = None,
        product_id_hint: int | None,
    ) -> ReplyMatchResult | None:
        rows = await EmailReplyMatcher._find_product_influencer_rows_by_email(
            db,
            email=sender,
            product_id_hint=product_id_hint,
        )
        if not rows:
            return None
        if len(rows) > 1:
            return await EmailReplyMatcher._match_ambiguous_sender_by_sent_subject(
                db,
                rows=rows,
                subject=subject,
            )
        product_row, _global_row = rows[0]

        log_query = (
            select(EmailLog)
            .where(
                EmailLog.product_influencer_id == product_row.id,
                EmailLog.status == EmailLogStatus.SENT.value,
                EmailLog.product_id == product_row.product_id,
            )
            .order_by(EmailLog.sent_at.desc())
            .limit(20)
        )
        logs = (await db.scalars(log_query)).all()
        normalized_subject = normalize_subject(subject)
        log = None
        if normalized_subject:
            for row in logs:
                if normalize_subject(row.subject) == normalized_subject:
                    log = row
                    break
        if log is None and not normalized_subject:
            log = logs[0] if logs else None
        campaign_id = await EmailReplyMatcher._resolve_campaign_id(db, email_log_id=log.id if log else None)
        return ReplyMatchResult(
            product_id=product_row.product_id,
            product_influencer_id=product_row.id,
            email_log_id=log.id if log else None,
            campaign_id=campaign_id,
            match_method="from_email",
            match_confidence="high" if log else "medium",
        )

    @staticmethod
    async def _match_ambiguous_sender_by_sent_subject(
        db: AsyncSession,
        *,
        rows: list[tuple[ProductInfluencer, GlobalInfluencerProfile]],
        subject: str | None,
    ) -> ReplyMatchResult | None:
        normalized_subject = normalize_subject(subject)
        if not normalized_subject:
            return None

        product_rows = {product_row.id: product_row for product_row, _global_row in rows}
        log_query = (
            select(EmailLog)
            .where(
                EmailLog.product_influencer_id.in_(list(product_rows.keys())),
                EmailLog.status == EmailLogStatus.SENT.value,
            )
            .order_by(EmailLog.sent_at.desc().nullslast(), EmailLog.id.desc())
            .limit(50)
        )
        logs = [
            log
            for log in (await db.scalars(log_query)).all()
            if normalize_subject(log.subject) == normalized_subject
        ]
        matched_ids = {log.product_influencer_id for log in logs if log.product_influencer_id}
        if len(matched_ids) != 1:
            return None

        log = logs[0]
        product_row = product_rows.get(log.product_influencer_id)
        if not product_row or log.product_id != product_row.product_id:
            return None
        campaign_id = await EmailReplyMatcher._resolve_campaign_id(db, email_log_id=log.id)
        return ReplyMatchResult(
            product_id=product_row.product_id,
            product_influencer_id=product_row.id,
            email_log_id=log.id,
            campaign_id=campaign_id,
            match_method="from_email_sent_subject",
            match_confidence="high",
        )

    @staticmethod
    async def _match_by_campaign_recipient(
        db: AsyncSession,
        *,
        sender: str,
        subject: str,
        product_id_hint: int | None,
    ) -> ReplyMatchResult | None:
        if _is_generic_address(sender):
            return None
        sender_norm = normalize_email_address(sender)
        if not sender_norm:
            return None

        queue_query = (
            select(OutreachSendQueueItem)
            .where(
                func.lower(OutreachSendQueueItem.recipient) == sender_norm,
                OutreachSendQueueItem.status == "sent",
            )
            .order_by(OutreachSendQueueItem.sent_at.desc())
            .limit(10)
        )
        if product_id_hint is not None:
            queue_query = queue_query.where(OutreachSendQueueItem.product_id == product_id_hint)
        queue_rows = (await db.scalars(queue_query)).all()

        normalized_subject = normalize_subject(subject)
        if normalized_subject:
            queue_rows = [
                row for row in queue_rows if normalize_subject(row.subject) == normalized_subject
            ] or queue_rows

        unique_ids = {row.product_influencer_id for row in queue_rows}
        if len(unique_ids) == 1:
            row = queue_rows[0]
            product_row = await db.get(ProductInfluencer, row.product_influencer_id)
            if not product_row or product_row.product_id != row.product_id:
                return None
            return ReplyMatchResult(
                product_id=row.product_id,
                product_influencer_id=row.product_influencer_id,
                email_log_id=row.email_log_id,
                campaign_id=row.campaign_id,
                match_method="campaign_recipient",
                match_confidence="medium",
            )

        recipient_query = (
            select(OutreachCampaignRecipient)
            .where(func.lower(OutreachCampaignRecipient.recipient) == sender_norm)
            .order_by(OutreachCampaignRecipient.updated_at.desc())
            .limit(10)
        )
        recipient_rows = (await db.scalars(recipient_query)).all()
        if product_id_hint is not None:
            scoped_rows = []
            for row in recipient_rows:
                product_row = await db.get(ProductInfluencer, row.product_influencer_id)
                if product_row and product_row.product_id == product_id_hint:
                    scoped_rows.append(row)
            recipient_rows = scoped_rows
        unique_ids = {row.product_influencer_id for row in recipient_rows}
        if len(unique_ids) != 1:
            return None
        row = recipient_rows[0]
        product_row = await db.get(ProductInfluencer, row.product_influencer_id)
        if not product_row:
            return None
        if product_id_hint is not None and product_row.product_id != product_id_hint:
            return None
        queue_row = None
        if row.queue_item_id:
            queue_row = await db.get(OutreachSendQueueItem, row.queue_item_id)
            if queue_row and queue_row.product_id != product_row.product_id:
                queue_row = None
        email_log_id = queue_row.email_log_id if queue_row else None
        campaign_id = queue_row.campaign_id if queue_row and queue_row.campaign_id else row.campaign_id
        return ReplyMatchResult(
            product_id=queue_row.product_id if queue_row else product_row.product_id,
            product_influencer_id=queue_row.product_influencer_id if queue_row else product_row.id,
            email_log_id=email_log_id,
            campaign_id=campaign_id,
            match_method="campaign_recipient",
            match_confidence="medium",
        )

    @staticmethod
    async def _resolve_candidate_campaign_id(
        db: AsyncSession,
        *,
        product_influencer_id: int,
        product_id: int,
        subject: str | None,
    ) -> int | None:
        normalized_subject = normalize_subject(subject)
        queue_query = (
            select(OutreachSendQueueItem)
            .where(
                OutreachSendQueueItem.product_id == product_id,
                OutreachSendQueueItem.product_influencer_id == product_influencer_id,
                OutreachSendQueueItem.campaign_id.is_not(None),
            )
            .order_by(OutreachSendQueueItem.sent_at.desc().nullslast(), OutreachSendQueueItem.updated_at.desc())
            .limit(10)
        )
        queue_rows = (await db.scalars(queue_query)).all()
        if normalized_subject:
            for row in queue_rows:
                if normalize_subject(row.subject) == normalized_subject:
                    return row.campaign_id
        if queue_rows:
            return queue_rows[0].campaign_id

        recipient_query = (
            select(OutreachCampaignRecipient)
            .where(OutreachCampaignRecipient.product_influencer_id == product_influencer_id)
            .order_by(OutreachCampaignRecipient.updated_at.desc())
            .limit(1)
        )
        row = await db.scalar(recipient_query)
        return row.campaign_id if row else None

    @staticmethod
    async def find_low_confidence_candidates(
        db: AsyncSession,
        *,
        from_address: str,
        subject: str | None,
        snippet: str | None,
        body: str | None,
        product_id_hint: int | None,
    ) -> list[dict]:
        tokens = _extract_name_tokens(subject, snippet, body)
        if not tokens:
            return []
        lowered = [token.lower() for token in tokens]
        name_filters = []
        for token in lowered:
            name_filters.append(func.lower(GlobalInfluencerProfile.display_name) == token)
            name_filters.append(func.lower(GlobalInfluencerProfile.display_name).like(f"{token} %"))
            name_filters.append(func.lower(GlobalInfluencerProfile.username) == token.replace(" ", ""))
            name_filters.append(func.lower(GlobalInfluencerProfile.normalized_username) == token.replace(" ", ""))

        query = (
            select(ProductInfluencer, GlobalInfluencerProfile)
            .join(
                GlobalInfluencerProfile,
                ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id,
            )
            .where(or_(*name_filters))
            .order_by(ProductInfluencer.updated_at.desc())
            .limit(10)
        )
        if product_id_hint is not None:
            query = query.where(ProductInfluencer.product_id == product_id_hint)

        rows = (await db.execute(query)).all()
        candidates: list[dict] = []
        seen: set[int] = set()
        for product_row, global_row in rows:
            if product_row.id in seen:
                continue
            seen.add(product_row.id)
            matched_text = next(
                (
                    token
                    for token in tokens
                    if token.lower() in {
                        (global_row.display_name or "").lower(),
                        (global_row.username or "").lower(),
                        (global_row.normalized_username or "").lower(),
                    }
                    or (global_row.display_name or "").lower().startswith(f"{token.lower()} ")
                ),
                None,
            )
            campaign_id = await EmailReplyMatcher._resolve_candidate_campaign_id(
                db,
                product_influencer_id=product_row.id,
                product_id=product_row.product_id,
                subject=subject,
            )
            candidates.append(
                _candidate_payload(
                    product_row,
                    global_row,
                    reason="name_fallback",
                    matched_text=matched_text,
                    campaign_id=campaign_id,
                )
            )
        if _is_generic_address(from_address):
            for candidate in candidates:
                candidate["generic_sender"] = True
        return candidates

    @staticmethod
    async def _match_by_unique_name_candidate(
        db: AsyncSession,
        *,
        from_address: str,
        subject: str | None,
        snippet: str | None,
        body: str | None,
        product_id_hint: int | None,
    ) -> ReplyMatchResult | None:
        if _is_generic_address(from_address):
            return None
        candidates = await EmailReplyMatcher.find_low_confidence_candidates(
            db,
            from_address=from_address,
            subject=subject,
            snippet=snippet,
            body=body,
            product_id_hint=product_id_hint,
        )
        if len(candidates) != 1:
            return None

        candidate = candidates[0]
        product_influencer_id = candidate.get("product_influencer_id")
        if not isinstance(product_influencer_id, int):
            return None
        product_row = await db.get(ProductInfluencer, product_influencer_id)
        if not product_row:
            return None
        if product_id_hint is not None and product_row.product_id != product_id_hint:
            return None

        campaign_id = candidate.get("campaign_id")
        return ReplyMatchResult(
            product_id=product_row.product_id,
            product_influencer_id=product_row.id,
            email_log_id=None,
            campaign_id=campaign_id if isinstance(campaign_id, int) else None,
            match_method="name_fallback_auto",
            match_confidence="medium",
            candidates=candidates,
        )

    @staticmethod
    async def candidate_meta(
        db: AsyncSession,
        *,
        from_address: str,
        subject: str | None,
        snippet: str | None,
        body: str | None,
        product_id_hint: int | None,
    ) -> dict:
        candidates = await EmailReplyMatcher.find_low_confidence_candidates(
            db,
            from_address=from_address,
            subject=subject,
            snippet=snippet,
            body=body,
            product_id_hint=product_id_hint,
        )
        if not candidates:
            return {"status": "unmatched", "confidence": None, "reason": None, "candidates": []}
        return {
            "status": "candidate",
            "confidence": "low",
            "reason": "name_fallback",
            "candidates": candidates,
        }

    @staticmethod
    async def _find_product_influencer_by_email(
        db: AsyncSession,
        *,
        email: str,
        product_id_hint: int | None,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile] | None:
        rows = await EmailReplyMatcher._find_product_influencer_rows_by_email(
            db,
            email=email,
            product_id_hint=product_id_hint,
        )
        if len(rows) != 1:
            return None
        return rows[0][0], rows[0][1]

    @staticmethod
    async def _find_product_influencer_rows_by_email(
        db: AsyncSession,
        *,
        email: str,
        product_id_hint: int | None,
    ) -> list[tuple[ProductInfluencer, GlobalInfluencerProfile]]:
        normalized = normalize_email_address(email)
        if not normalized:
            return []

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
        return [(product_row, global_row) for product_row, global_row in rows]

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
