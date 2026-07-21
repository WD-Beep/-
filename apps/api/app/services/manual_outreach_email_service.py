# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：manual outreach email service
"""Manual custom-address outreach email sending."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory
from app.deps.tenant import TenantContext, require_write_product_id
from app.models.enums import EmailLogStatus
from app.models.manual_outreach_email import ManualOutreachEmail
from app.schemas.manual_outreach_email import (
    ManualOutreachEmailItemRead,
    ManualOutreachEmailRequest,
    ManualOutreachEmailResponse,
)
from app.services.email import EmailNotConfiguredError, EmailService, format_smtp_send_error
from app.services.email_reply_utils import build_outbound_message_id
from app.services.outreach_send_queue_service import _resolve_sender_email

logger = logging.getLogger(__name__)

MAX_MANUAL_RECIPIENTS = 10


@dataclass
class ManualDueQueueProcessResult:
    processed: int = 0
    sent: int = 0
    failed: int = 0
    locked: int = 0


def _normalize_recipient(value: object) -> str:
    return str(value).strip().lower()


class ManualOutreachEmailService:
    @staticmethod
    def _validate_payload(payload: ManualOutreachEmailRequest) -> list[str]:
        recipients = []
        seen = set()
        for recipient in payload.recipients:
            normalized = _normalize_recipient(recipient)
            if normalized and normalized not in seen:
                recipients.append(normalized)
                seen.add(normalized)
        if len(recipients) > MAX_MANUAL_RECIPIENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"自定义测试发送一次最多支持 {MAX_MANUAL_RECIPIENTS} 个收件邮箱",
            )
        if payload.send_mode == "scheduled" and not payload.scheduled_at:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="定时发送需要选择发送时间")
        return recipients

    @staticmethod
    async def submit(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        payload: ManualOutreachEmailRequest,
    ) -> ManualOutreachEmailResponse:
        product_id = require_write_product_id(ctx)
        recipients = ManualOutreachEmailService._validate_payload(payload)
        if payload.send_mode == "scheduled":
            return await ManualOutreachEmailService.schedule(
                db,
                product_id=product_id,
                user_id=ctx.user_id,
                recipients=recipients,
                subject=payload.subject,
                body=payload.body,
                scheduled_at=payload.scheduled_at,
            )
        return await ManualOutreachEmailService.send_now(
            db,
            product_id=product_id,
            user_id=ctx.user_id,
            recipients=recipients,
            subject=payload.subject,
            body=payload.body,
        )

    @staticmethod
    async def schedule(
        db: AsyncSession,
        *,
        product_id: int,
        user_id: int | None,
        recipients: list[str],
        subject: str,
        body: str,
        scheduled_at: datetime | None,
    ) -> ManualOutreachEmailResponse:
        items: list[ManualOutreachEmail] = []
        for recipient in recipients:
            row = ManualOutreachEmail(
                product_id=product_id,
                user_id=user_id,
                recipient=recipient,
                sender_email=_resolve_sender_email(),
                subject=subject.strip(),
                body=body.strip(),
                status="scheduled",
                scheduled_at=scheduled_at,
            )
            db.add(row)
            items.append(row)
        await db.commit()
        for item in items:
            await db.refresh(item)
        return ManualOutreachEmailResponse(
            status="scheduled",
            total=len(items),
            scheduled_count=len(items),
            message=f"已设置 {len(items)} 封自定义测试邮件定时发送",
            items=[ManualOutreachEmailItemRead.model_validate(item) for item in items],
        )

    @staticmethod
    async def send_now(
        db: AsyncSession,
        *,
        product_id: int,
        user_id: int | None,
        recipients: list[str],
        subject: str,
        body: str,
    ) -> ManualOutreachEmailResponse:
        try:
            EmailService.ensure_smtp_configured()
        except EmailNotConfiguredError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc

        sent = failed = 0
        items: list[ManualOutreachEmailItemRead] = []
        for recipient in recipients:
            row = ManualOutreachEmail(
                product_id=product_id,
                user_id=user_id,
                recipient=recipient,
                sender_email=_resolve_sender_email(),
                subject=subject.strip(),
                body=body.strip(),
                status="sending",
                scheduled_at=datetime.now(UTC),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            outcome = await ManualOutreachEmailService._send_row(db, row)
            if outcome == "sent":
                sent += 1
            else:
                failed += 1
            await db.refresh(row)
            items.append(ManualOutreachEmailItemRead.model_validate(row))

        return ManualOutreachEmailResponse(
            status="sent" if failed == 0 else "failed",
            total=len(recipients),
            sent_count=sent,
            failed_count=failed,
            message=f"自定义测试邮件已处理：成功 {sent} 封，失败 {failed} 封",
            items=items,
        )

    @staticmethod
    async def _send_row(db: AsyncSession, row: ManualOutreachEmail) -> str:
        message_id = build_outbound_message_id(product_id=row.product_id)
        message = MIMEMultipart()
        message["From"] = settings.smtp_from
        message["To"] = row.recipient
        message["Subject"] = row.subject
        message["Message-ID"] = message_id
        message.attach(MIMEText(row.body, "plain", "utf-8"))

        log_kwargs = {
            "task_id": None,
            "recipients": [row.recipient],
            "subject": row.subject,
            "body": row.body,
            "product_id": row.product_id,
            "user_id": row.user_id,
            "product_influencer_id": None,
            "sender_email": row.sender_email or _resolve_sender_email(),
            "influencer_username": None,
            "generated_by_ai": False,
            "ai_provider": None,
            "ai_reason": "manual_custom_outreach_test",
            "matched_knowledge": None,
            "message_id": message_id,
        }

        try:
            await EmailService._send_message(message, [row.recipient])
            log = await EmailService.create_outreach_email_log(db, status=EmailLogStatus.SENT, **log_kwargs)
            row.status = "sent"
            row.sent_at = datetime.now(UTC)
            row.error_message = None
            row.email_log_id = log.id
            await db.commit()
            return "sent"
        except Exception as exc:
            err = format_smtp_send_error(exc)
            logger.warning("Manual outreach send failed for %s: %s", row.recipient, err)
            log = await EmailService.create_outreach_email_log(
                db,
                status=EmailLogStatus.FAILED,
                error_message=err,
                **log_kwargs,
            )
            row.status = "failed"
            row.error_message = err
            row.email_log_id = log.id
            await db.commit()
            return "failed"


async def _lock_manual_item(db: AsyncSession, *, item_id: int) -> bool:
    result = await db.execute(
        update(ManualOutreachEmail)
        .where(ManualOutreachEmail.id == item_id, ManualOutreachEmail.status == "scheduled")
        .values(status="sending")
    )
    await db.commit()
    return int(result.rowcount or 0) == 1


async def process_due_manual_outreach_emails(limit: int = 20) -> ManualDueQueueProcessResult:
    result = ManualDueQueueProcessResult()
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        rows = await db.execute(
            select(ManualOutreachEmail.id)
            .where(
                ManualOutreachEmail.status == "scheduled",
                ManualOutreachEmail.scheduled_at <= now,
            )
            .order_by(ManualOutreachEmail.scheduled_at.asc(), ManualOutreachEmail.id.asc())
            .limit(max(1, int(limit)))
        )
        item_ids = [row[0] for row in rows.all()]
        if not item_ids:
            return result
        try:
            EmailService.ensure_smtp_configured()
        except EmailNotConfiguredError:
            return result

        for item_id in item_ids:
            if not await _lock_manual_item(db, item_id=item_id):
                continue
            result.locked += 1
            row = await db.get(ManualOutreachEmail, item_id)
            if not row:
                continue
            outcome = await ManualOutreachEmailService._send_row(db, row)
            result.processed += 1
            if outcome == "sent":
                result.sent += 1
            else:
                result.failed += 1
    return result
