# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：email reply service
"""Ingest and manage inbound influencer email replies."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product
from app.schemas.email_reply import (
    EmailReplyIngestBatchResponse,
    EmailReplyIngestResult,
    EmailReplyBulkDeleteResponse,
    EmailReplyRead,
    EmailReplySendResponseResult,
    EmailReplySummary,
    InboundEmailPayload,
    InboundEmailWebhookRequest,
)
from app.services.email import EmailService, format_smtp_send_error
from app.services.email_reply_matcher import EmailReplyMatcher, _is_generic_address, reply_match_meta, with_reply_match_meta
from app.services.email_reply_utils import (
    build_outbound_message_id,
    detect_cooperation_interest,
    extract_email_address,
    html_to_text,
    is_automated_sender,
    is_delivery_status_notification,
    is_outbound_copy,
    make_snippet,
    normalize_message_id,
    parse_references,
)
from app.services.follow_up_scheduler import mark_record_replied
from app.services.influencer_lead import InfluencerLeadService
from app.services.imap_reply_client import fetch_unread_imap_messages
from app.services.outreach_recipient import normalize_email_address
from app.services.smtp_account import resolve_imap_account, resolve_smtp_account

logger = logging.getLogger(__name__)


class EmailReplyService:
    @staticmethod
    def _response_subject(reply_subject: str | None, requested_subject: str | None) -> str:
        subject = (requested_subject or "").strip() or (reply_subject or "").strip() or "(no subject)"
        return subject if subject.lower().startswith("re:") else f"Re: {subject}"

    @staticmethod
    def _reply_response_meta(raw_headers: dict | None, meta: dict) -> dict:
        headers = dict(raw_headers or {})
        headers["reply_response"] = meta
        return headers

    @staticmethod
    def _thread_references(reply: EmailReply) -> list[str]:
        raw = reply.raw_headers or {}
        references = parse_references(raw.get("References") or raw.get("references"))
        for value in (reply.in_reply_to, reply.message_id):
            normalized = normalize_message_id(value)
            if normalized and normalized not in references:
                references.append(normalized)
        return references

    @staticmethod
    async def _reply_warning(
        db: AsyncSession,
        reply: EmailReply,
        recipient: str,
    ) -> str | None:
        if not reply.product_influencer_id:
            return "unmatched_reply_identity_warning"
        if _is_generic_address(recipient):
            return "generic_sender_warning"

        product_row = await db.get(ProductInfluencer, reply.product_influencer_id)
        if not product_row:
            return "unmatched_reply_identity_warning"
        global_row = await db.get(GlobalInfluencerProfile, product_row.global_influencer_id)
        if not global_row:
            return "unmatched_reply_identity_warning"

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
        if known and normalize_email_address(recipient) not in known:
            return "sender_email_mismatch_warning"
        return None

    @staticmethod
    async def send_response(
        db: AsyncSession,
        *,
        product_id: int,
        user_id: int | None,
        reply_id: int,
        body: str,
        subject: str | None = None,
        use_ai_draft: bool = False,
        mark_processed: bool = True,
    ) -> EmailReplySendResponseResult:
        reply = await db.get(EmailReply, reply_id)
        if not reply or reply.product_id != product_id:
            raise ValueError("reply_not_found")

        existing = await db.scalar(
            select(EmailLog)
            .where(
                EmailLog.reply_email_log_id == reply.id,
                EmailLog.status == EmailLogStatus.SENT.value,
            )
            .order_by(EmailLog.sent_at.desc().nullslast(), EmailLog.id.desc())
            .limit(1)
        )
        if existing:
            return EmailReplySendResponseResult(
                sent=True,
                message_id=existing.message_id,
                reply_id=reply.id,
                product_influencer_id=reply.product_influencer_id,
                campaign_id=reply.campaign_id,
                sent_at=existing.sent_at,
                delivery_provider="smtp",
                warning="duplicate_response_skipped",
            )

        recipient = extract_email_address(reply.from_address)
        if not recipient:
            raise ValueError("missing_reply_recipient")

        clean_body = (body or "").strip()
        if not clean_body:
            raise ValueError("empty_response_body")

        outbound_subject = EmailReplyService._response_subject(reply.subject, subject)
        message_id = build_outbound_message_id(product_id=product_id)
        warning = await EmailReplyService._reply_warning(db, reply, recipient)
        sender_account = await resolve_smtp_account(db, user_id=user_id)
        sender_email = sender_account.smtp_from or settings.smtp_from

        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = recipient
        message["Subject"] = outbound_subject
        message["Message-ID"] = message_id
        if reply.message_id:
            message["In-Reply-To"] = normalize_message_id(reply.message_id) or reply.message_id
        references = EmailReplyService._thread_references(reply)
        if references:
            message["References"] = " ".join(references)
        message.attach(MIMEText(clean_body, "plain", "utf-8"))

        sent_at = datetime.now(UTC)
        try:
            await EmailService._send_message(message, [recipient], smtp_account=sender_account)
        except Exception as exc:
            error = format_smtp_send_error(exc)
            await EmailService.create_outreach_email_log(
                db,
                task_id=None,
                recipients=[recipient],
                subject=outbound_subject,
                body=clean_body,
                status=EmailLogStatus.FAILED,
                error_message=error,
                product_id=product_id,
                user_id=user_id,
                product_influencer_id=reply.product_influencer_id,
                sender_user_id=sender_account.sender_user_id,
                smtp_account_id=sender_account.account_id,
                sender_source=sender_account.source,
                sender_email=sender_email or None,
                generated_by_ai=use_ai_draft,
                ai_provider="template" if use_ai_draft else None,
                message_id=message_id,
                reply_email_log_id=reply.id,
            )
            return EmailReplySendResponseResult(
                sent=False,
                message_id=message_id,
                reply_id=reply.id,
                product_influencer_id=reply.product_influencer_id,
                campaign_id=reply.campaign_id,
                delivery_provider="smtp",
                warning=warning,
                error=error,
            )

        log = await EmailService.create_outreach_email_log(
            db,
            task_id=None,
            recipients=[recipient],
            subject=outbound_subject,
            body=clean_body,
            status=EmailLogStatus.SENT,
            product_id=product_id,
            user_id=user_id,
            product_influencer_id=reply.product_influencer_id,
            sender_user_id=sender_account.sender_user_id,
            smtp_account_id=sender_account.account_id,
            sender_source=sender_account.source,
            sender_email=sender_email or None,
            generated_by_ai=use_ai_draft,
            ai_provider="template" if use_ai_draft else None,
            message_id=message_id,
            reply_email_log_id=reply.id,
        )
        sent_at = log.sent_at or sent_at

        if mark_processed:
            reply.processing_status = "processed"
            reply.handled_at = sent_at
        reply.raw_headers = EmailReplyService._reply_response_meta(
            reply.raw_headers,
            {
                "response_sent": True,
                "response_message_id": message_id,
                "response_sent_at": sent_at.isoformat(),
                "response_provider": "smtp",
                "response_email_log_id": log.id,
            },
        )

        if reply.product_influencer_id:
            product_row = await db.get(ProductInfluencer, reply.product_influencer_id)
            if product_row:
                await InfluencerLeadService.create_product_followup(
                    db,
                    product_row=product_row,
                    action_type="email_sent",
                    content=f"{outbound_subject}\n\n{clean_body}",
                    operator_name="email_reply_response",
                    contact_channel="email",
                )

        await db.commit()
        await db.refresh(reply)
        return EmailReplySendResponseResult(
            sent=True,
            message_id=message_id,
            reply_id=reply.id,
            product_influencer_id=reply.product_influencer_id,
            campaign_id=reply.campaign_id,
            sent_at=sent_at,
            delivery_provider="smtp",
            warning=warning,
        )

    @staticmethod
    async def _resolve_unmatched_product_id(
        db: AsyncSession,
        product_id_hint: int | None,
    ) -> int | None:
        if product_id_hint is not None:
            return await db.scalar(select(Product.id).where(Product.id == product_id_hint))

        default_id = await db.scalar(
            select(Product.id)
            .where(Product.is_archived.is_(False), Product.is_default.is_(True))
            .order_by(Product.id.asc())
            .limit(1)
        )
        if default_id:
            return default_id

        product_ids = list(
            (await db.scalars(select(Product.id).where(Product.is_archived.is_(False)))).all()
        )
        if len(product_ids) == 1:
            return product_ids[0]
        return None

    @staticmethod
    def webhook_to_payload(payload: InboundEmailWebhookRequest) -> InboundEmailPayload:
        from_address = extract_email_address(payload.from_address or payload.from_email)
        to_raw = payload.to_address or payload.to_email
        to_address = extract_email_address(to_raw if isinstance(to_raw, str) else None)
        if not to_address and isinstance(to_raw, list):
            to_address = extract_email_address(to_raw[0] if to_raw else None)
        body = payload.body or payload.text or html_to_text(payload.html) or ""
        return InboundEmailPayload(
            message_id=payload.message_id,
            in_reply_to=payload.in_reply_to,
            references=parse_references(payload.references),
            from_address=from_address or "",
            to_address=to_address or "",
            subject=payload.subject or "",
            body=body,
            raw_headers=payload.headers,
            received_at=payload.received_at,
            product_id=payload.product_id,
        )

    @staticmethod
    async def _save_unmatched_reply(
        db: AsyncSession,
        payload: InboundEmailPayload,
        *,
        source: str,
        from_address: str,
        to_address: str | None,
        normalized_message_id: str | None,
        match_meta: dict | None = None,
    ) -> EmailReplyIngestResult:
        product_id = await EmailReplyService._resolve_unmatched_product_id(db, payload.product_id)
        if product_id is None:
            return EmailReplyIngestResult(
                status="failed",
                message="已收到回复，但无法判断归属产品，请先选择产品后手动拉取收件箱",
            )

        reply = EmailReply(
            product_id=product_id,
            user_id=None,
            email_log_id=None,
            product_influencer_id=None,
            campaign_id=None,
            message_id=normalized_message_id,
            in_reply_to=normalize_message_id(payload.in_reply_to),
            match_method="unmatched",
            processing_status="unprocessed",
            intent_status="unmatched",
            source=source,
            from_address=from_address,
            to_address=to_address or "",
            subject=(payload.subject or "")[:500],
            body=html_to_text(payload.body),
            snippet=make_snippet(payload.body),
            raw_headers=with_reply_match_meta(
                payload.raw_headers,
                match_meta or {"status": "unmatched", "confidence": None, "reason": None, "candidates": []},
            ),
            received_at=payload.received_at or datetime.now(UTC),
        )
        db.add(reply)
        try:
            await db.commit()
            await db.refresh(reply)
        except IntegrityError:
            await db.rollback()
            return EmailReplyIngestResult(status="skipped", message="重复 Message-ID，已跳过")

        return EmailReplyIngestResult(
            status="ingested",
            reply_id=reply.id,
            product_id=reply.product_id,
            match_method=reply.match_method,
            match_confidence=(match_meta or {}).get("confidence"),
            message="已接收回复，但还没有匹配到红人，请在未匹配回复中手动关联",
        )

    @staticmethod
    async def ingest(
        db: AsyncSession,
        payload: InboundEmailPayload,
        *,
        source: str = "webhook",
    ) -> EmailReplyIngestResult:
        from_address = extract_email_address(payload.from_address)
        to_address = extract_email_address(payload.to_address)
        if not from_address:
            return EmailReplyIngestResult(status="skipped", message="缺少有效发件人地址")


        if is_delivery_status_notification(
            from_address=from_address,
            subject=payload.subject,
            body=payload.body,
        ):
            return EmailReplyIngestResult(status="skipped", message="退信/投递失败通知已跳过，不作为红人回复")

        outbound_addresses = {
            normalize_email_address(settings.smtp_from),
            normalize_email_address(settings.smtp_user),
            normalize_email_address(settings.inbound_email_address),
        }
        outbound_addresses.discard(None)
        if is_outbound_copy(from_address=from_address, configured_addresses=outbound_addresses):
            return EmailReplyIngestResult(status="skipped", message="自己发出的邮件副本已跳过，不作为红人回复")

        normalized_message_id = normalize_message_id(payload.message_id)
        if normalized_message_id:
            existing = await db.scalar(
                select(EmailReply.id).where(
                    func.lower(EmailReply.message_id) == normalized_message_id.lower()
                )
            )
            if existing:
                return EmailReplyIngestResult(
                    status="skipped",
                    reply_id=existing,
                    message="重复 Message-ID，已跳过",
                )

        clean_body = html_to_text(payload.body)
        match = await EmailReplyMatcher.match(
            db,
            from_address=from_address,
            to_address=to_address or "",
            subject=payload.subject,
            snippet=make_snippet(clean_body),
            body=clean_body,
            in_reply_to=payload.in_reply_to,
            references=payload.references,
            product_id_hint=payload.product_id,
        )
        if not match:
            if is_automated_sender(from_address):
                return EmailReplyIngestResult(
                    status="skipped",
                    message="系统通知或广告邮件未匹配到红人，已跳过",
                )
            resolved_product_id = await EmailReplyService._resolve_unmatched_product_id(db, payload.product_id)
            if resolved_product_id is None:
                return EmailReplyIngestResult(
                    status="failed",
                    message="已收到回复，但无法判断归属产品，请先选择产品后手动拉取收件箱",
                )
            snippet = make_snippet(clean_body)
            candidate_meta = await EmailReplyMatcher.candidate_meta(
                db,
                from_address=from_address,
                subject=payload.subject,
                snippet=snippet,
                body=clean_body,
                product_id_hint=resolved_product_id,
            )
            return await EmailReplyService._save_unmatched_reply(
                db,
                payload.model_copy(update={"product_id": resolved_product_id, "body": clean_body}),
                source=source,
                from_address=from_address,
                to_address=to_address,
                normalized_message_id=normalized_message_id,
                match_meta=candidate_meta,
            )

        product_row = None
        if match.product_influencer_id:
            product_row = await db.get(ProductInfluencer, match.product_influencer_id)
            if product_row and product_row.product_id != match.product_id:
                return EmailReplyIngestResult(
                    status="skipped",
                    message="匹配结果与当前产品不一致，已跳过",
                )

        received_at = payload.received_at or datetime.now(UTC)
        snippet = make_snippet(clean_body)
        interested = detect_cooperation_interest(subject=payload.subject, body=clean_body)
        reply = EmailReply(
            product_id=match.product_id,
            user_id=None,
            email_log_id=match.email_log_id,
            product_influencer_id=match.product_influencer_id,
            campaign_id=match.campaign_id,
            message_id=normalized_message_id,
            in_reply_to=normalize_message_id(payload.in_reply_to),
            match_method=match.match_method,
            processing_status="unprocessed",
            intent_status="interested" if interested else "unprocessed",
            source=source,
            from_address=from_address,
            to_address=to_address or "",
            subject=(payload.subject or "")[:500],
            body=clean_body,
            snippet=snippet,
            raw_headers=with_reply_match_meta(
                payload.raw_headers,
                {
                    **reply_match_meta(match),
                    "matched_at": datetime.now(UTC).isoformat(),
                },
            ),
            received_at=received_at,
        )
        db.add(reply)

        follow_status = None
        try:
            await db.flush()
            if match.email_log_id:
                await mark_record_replied(
                    db,
                    outreach_record_id=match.email_log_id,
                    product_id=match.product_id,
                    reply_id=reply.id,
                    replied_at=received_at,
                    reply_summary=snippet,
                )
            if product_row:
                updated = await InfluencerLeadService.mark_product_email_replied(
                    db,
                    product_row,
                    subject=payload.subject,
                    snippet=snippet,
                    interested=interested,
                    operator_name=source,
                )
                follow_status = updated.follow_status
            await db.commit()
            await db.refresh(reply)
        except IntegrityError:
            await db.rollback()
            return EmailReplyIngestResult(status="skipped", message="重复 Message-ID，已跳过")

        return EmailReplyIngestResult(
            status="ingested",
            reply_id=reply.id,
            product_id=reply.product_id,
            product_influencer_id=reply.product_influencer_id,
            email_log_id=reply.email_log_id,
            campaign_id=reply.campaign_id,
            match_method=reply.match_method,
            match_confidence=match.match_confidence,
            follow_status=follow_status,
            message="已接收并匹配红人回复",
        )

    @staticmethod
    async def rematch_unmatched_replies(
        db: AsyncSession,
        *,
        product_id: int | None = None,
        limit: int = 200,
    ) -> int:
        filters = [EmailReply.product_influencer_id.is_(None)]
        if product_id is not None:
            filters.append(EmailReply.product_id == product_id)

        replies = (
            await db.scalars(
                select(EmailReply)
                .where(*filters)
                .order_by(EmailReply.received_at.desc())
                .limit(limit)
            )
        ).all()

        updated = 0
        for reply in replies:
            references = parse_references((reply.raw_headers or {}).get("References"))
            if not reply.in_reply_to and not references:
                continue
            was_unmatched = reply.product_influencer_id is None
            match = await EmailReplyMatcher.match(
                db,
                from_address=reply.from_address,
                to_address=reply.to_address,
                subject=reply.subject,
                snippet=reply.snippet,
                body=reply.body,
                in_reply_to=reply.in_reply_to,
                references=references,
                product_id_hint=reply.product_id,
            )
            if match and match.product_influencer_id:
                reply.product_id = match.product_id
                reply.product_influencer_id = match.product_influencer_id
                reply.email_log_id = match.email_log_id
                reply.campaign_id = match.campaign_id
                reply.match_method = match.match_method
                reply.raw_headers = with_reply_match_meta(
                    reply.raw_headers,
                    {
                        **reply_match_meta(match),
                        "matched_at": datetime.now(UTC).isoformat(),
                        "rematched": True,
                    },
                )
                if was_unmatched:
                    updated += 1
                continue

            reply.raw_headers = with_reply_match_meta(
                reply.raw_headers,
                await EmailReplyMatcher.candidate_meta(
                    db,
                    from_address=reply.from_address,
                    subject=reply.subject,
                    snippet=reply.snippet,
                    body=reply.body,
                    product_id_hint=reply.product_id,
                ),
            )

        if replies:
            await db.commit()
        return updated

    @staticmethod
    async def rematch_reply(
        db: AsyncSession,
        *,
        product_id: int,
        reply_id: int,
    ) -> EmailReplyRead:
        reply = await db.get(EmailReply, reply_id)
        if not reply or reply.product_id != product_id:
            raise ValueError("reply_not_found")

        raw_headers = reply.raw_headers or {}
        references = parse_references(raw_headers.get("References") or raw_headers.get("references"))
        match = await EmailReplyMatcher.match(
            db,
            from_address=reply.from_address,
            to_address=reply.to_address,
            subject=reply.subject,
            snippet=reply.snippet,
            body=reply.body,
            in_reply_to=reply.in_reply_to,
            references=references,
            product_id_hint=reply.product_id,
        )
        if match and match.product_influencer_id:
            reply.product_id = match.product_id
            reply.product_influencer_id = match.product_influencer_id
            reply.email_log_id = match.email_log_id
            reply.campaign_id = match.campaign_id
            reply.match_method = match.match_method
            reply.intent_status = "unprocessed" if reply.intent_status == "unmatched" else reply.intent_status
            reply.raw_headers = with_reply_match_meta(
                reply.raw_headers,
                {
                    **reply_match_meta(match),
                    "matched_at": datetime.now(UTC).isoformat(),
                    "rematched": True,
                },
            )
            if match.email_log_id:
                await mark_record_replied(
                    db,
                    outreach_record_id=match.email_log_id,
                    product_id=match.product_id,
                    reply_id=reply.id,
                    replied_at=reply.received_at,
                    reply_summary=reply.snippet,
                )
        else:
            reply.raw_headers = with_reply_match_meta(
                reply.raw_headers,
                await EmailReplyMatcher.candidate_meta(
                    db,
                    from_address=reply.from_address,
                    subject=reply.subject,
                    snippet=reply.snippet,
                    body=reply.body,
                    product_id_hint=reply.product_id,
                ),
            )

        await db.commit()
        await db.refresh(reply)
        return EmailReplyRead.model_validate(reply)

    @staticmethod
    async def ingest_batch(
        db: AsyncSession,
        payloads: list[InboundEmailPayload],
        *,
        source: str,
    ) -> EmailReplyIngestBatchResponse:
        results: list[EmailReplyIngestResult] = []
        ingested = skipped = failed = 0
        for payload in payloads:
            try:
                result = await EmailReplyService.ingest(db, payload, source=source)
            except Exception as exc:
                logger.exception("Failed to ingest inbound reply")
                result = EmailReplyIngestResult(status="failed", message=str(exc)[:500])
            results.append(result)
            if result.status == "ingested":
                ingested += 1
            elif result.status == "failed":
                failed += 1
            else:
                skipped += 1
        return EmailReplyIngestBatchResponse(
            processed=len(payloads),
            ingested=ingested,
            skipped=skipped,
            failed=failed,
            results=results,
        )

    @staticmethod
    async def poll_imap(
        db: AsyncSession,
        *,
        mark_seen: bool = False,
        product_id_hint: int | None = None,
        user_id: int | None = None,
    ) -> EmailReplyIngestBatchResponse:
        imap_account = await resolve_imap_account(db, user_id=user_id)
        messages = await asyncio.to_thread(fetch_unread_imap_messages, mark_seen=mark_seen, account=imap_account)
        if product_id_hint is not None:
            messages = [message.model_copy(update={"product_id": product_id_hint}) for message in messages]
        return await EmailReplyService.ingest_batch(db, messages, source="imap")

    @staticmethod
    async def list_replies(
        db: AsyncSession,
        *,
        product_id: int | None,
        product_influencer_id: int | None = None,
        email_log_id: int | None = None,
        campaign_id: int | None = None,
        processing_status: str | None = None,
        intent_status: str | None = None,
        unmatched: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[EmailReplyRead], int]:
        filters = []
        if product_id is not None:
            filters.append(EmailReply.product_id == product_id)
        if product_influencer_id is not None:
            filters.append(EmailReply.product_influencer_id == product_influencer_id)
        if email_log_id is not None:
            filters.append(EmailReply.email_log_id == email_log_id)
        if campaign_id is not None:
            filters.append(EmailReply.campaign_id == campaign_id)
        if processing_status:
            filters.append(EmailReply.processing_status == processing_status)
        if intent_status:
            filters.append(EmailReply.intent_status == intent_status)
        if unmatched is True:
            filters.append(EmailReply.product_influencer_id.is_(None))
        elif unmatched is False:
            filters.append(EmailReply.product_influencer_id.is_not(None))

        total = int(await db.scalar(select(func.count()).select_from(EmailReply).where(*filters)) or 0)
        rows = (
            await db.scalars(
                select(EmailReply)
                .where(*filters)
                .order_by(EmailReply.received_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return [EmailReplyRead.model_validate(row) for row in rows], total

    @staticmethod
    async def count_reply_work(db: AsyncSession, *, product_id: int | None) -> tuple[int, int, int]:
        product_filters = [] if product_id is None else [EmailReply.product_id == product_id]
        unviewed_count = int(
            await db.scalar(
                select(func.count())
                .select_from(EmailReply)
                .where(
                    *product_filters,
                    EmailReply.viewed_at.is_(None),
                )
            )
            or 0
        )
        unprocessed_count = int(
            await db.scalar(
                select(func.count())
                .select_from(EmailReply)
                .where(
                    *product_filters,
                    EmailReply.processing_status == "unprocessed",
                    EmailReply.product_influencer_id.is_not(None),
                )
            )
            or 0
        )
        unmatched_count = int(
            await db.scalar(
                select(func.count())
                .select_from(EmailReply)
                .where(*product_filters, EmailReply.product_influencer_id.is_(None))
            )
            or 0
        )
        return unprocessed_count, unmatched_count, unviewed_count

    @staticmethod
    async def update_reply(
        db: AsyncSession,
        *,
        product_id: int,
        reply_id: int,
        product_influencer_id: int | None = None,
        campaign_id: int | None = None,
        intent_status: str | None = None,
        processing_status: str | None = None,
        manual_note: str | None = None,
        mark_viewed: bool | None = None,
    ) -> EmailReplyRead:
        reply = await db.get(EmailReply, reply_id)
        if not reply or reply.product_id != product_id:
            raise ValueError("没有找到这封回复")

        sync_lead_status = any(
            value is not None
            for value in (product_influencer_id, campaign_id, intent_status, processing_status)
        )
        product_row: ProductInfluencer | None = None
        if product_influencer_id is not None:
            product_row = await db.get(ProductInfluencer, product_influencer_id)
            if not product_row or product_row.product_id != product_id:
                raise ValueError("选择的红人不属于当前产品")
            reply.product_influencer_id = product_row.id
            if reply.match_method == "unmatched":
                reply.match_method = "manual"
            reply.raw_headers = with_reply_match_meta(
                reply.raw_headers,
                {
                    "status": "matched",
                    "confidence": "high",
                    "reason": "manual",
                    "product_influencer_id": product_row.id,
                    "campaign_id": campaign_id or reply.campaign_id,
                    "email_log_id": reply.email_log_id,
                    "candidates": [],
                    "matched_at": datetime.now(UTC).isoformat(),
                },
            )

        if campaign_id is not None:
            campaign = await db.get(OutreachEmailCampaign, campaign_id)
            if not campaign or campaign.product_id != product_id:
                raise ValueError("选择的外联活动不属于当前产品")
            reply.campaign_id = campaign.id

        if intent_status is not None:
            reply.intent_status = intent_status
        if processing_status is not None:
            reply.processing_status = processing_status
            reply.handled_at = datetime.now(UTC) if processing_status == "processed" else None
        if manual_note is not None:
            reply.manual_note = manual_note
        if mark_viewed is True and reply.viewed_at is None:
            reply.viewed_at = datetime.now(UTC)

        if sync_lead_status and product_row is None and reply.product_influencer_id is not None:
            product_row = await db.get(ProductInfluencer, reply.product_influencer_id)
        if sync_lead_status and product_row is not None:
            updated = await InfluencerLeadService.mark_product_email_replied(
                db,
                product_row,
                subject=reply.subject,
                snippet=reply.snippet,
                interested=reply.intent_status == "interested",
                operator_name="manual",
            )
            if reply.intent_status == "unmatched":
                reply.intent_status = "interested" if updated.follow_status == "interested" else "unprocessed"
            if reply.email_log_id:
                await mark_record_replied(
                    db,
                    outreach_record_id=reply.email_log_id,
                    product_id=product_id,
                    reply_id=reply.id,
                    replied_at=reply.received_at,
                    reply_summary=reply.snippet,
                )

        await db.commit()
        await db.refresh(reply)
        return EmailReplyRead.model_validate(reply)

    @staticmethod
    async def delete_replies(
        db: AsyncSession,
        *,
        product_id: int,
        reply_ids: list[int],
    ) -> EmailReplyBulkDeleteResponse:
        unique_ids = list(dict.fromkeys(reply_ids))
        rows = (
            await db.scalars(
                select(EmailReply.id).where(
                    EmailReply.product_id == product_id,
                    EmailReply.id.in_(unique_ids),
                )
            )
        ).all()
        deleted_ids = list(rows)
        missing_ids = [reply_id for reply_id in unique_ids if reply_id not in set(deleted_ids)]
        if deleted_ids:
            await db.execute(
                delete(EmailReply).where(
                    EmailReply.product_id == product_id,
                    EmailReply.id.in_(deleted_ids),
                )
            )
            await db.commit()
        return EmailReplyBulkDeleteResponse(
            deleted_count=len(deleted_ids),
            deleted_ids=deleted_ids,
            missing_ids=missing_ids,
        )

    @staticmethod
    async def reply_summary_for_influencer(
        db: AsyncSession,
        *,
        product_id: int,
        product_influencer_id: int,
    ) -> EmailReplySummary:
        latest = await db.scalar(
            select(EmailReply)
            .where(
                EmailReply.product_id == product_id,
                EmailReply.product_influencer_id == product_influencer_id,
            )
            .order_by(EmailReply.received_at.desc())
            .limit(1)
        )
        count = int(
            await db.scalar(
                select(func.count())
                .select_from(EmailReply)
                .where(
                    EmailReply.product_id == product_id,
                    EmailReply.product_influencer_id == product_influencer_id,
                )
            )
            or 0
        )
        return EmailReplySummary(
            reply_count=count,
            latest_reply_at=latest.received_at if latest else None,
            latest_snippet=latest.snippet if latest else None,
        )

    @staticmethod
    async def reply_summary_for_campaign(
        db: AsyncSession,
        *,
        product_id: int,
        campaign_id: int,
    ) -> EmailReplySummary:
        latest = await db.scalar(
            select(EmailReply)
            .where(EmailReply.product_id == product_id, EmailReply.campaign_id == campaign_id)
            .order_by(EmailReply.received_at.desc())
            .limit(1)
        )
        count = int(
            await db.scalar(
                select(func.count())
                .select_from(EmailReply)
                .where(EmailReply.product_id == product_id, EmailReply.campaign_id == campaign_id)
            )
            or 0
        )
        return EmailReplySummary(
            reply_count=count,
            latest_reply_at=latest.received_at if latest else None,
            latest_snippet=latest.snippet if latest else None,
        )
