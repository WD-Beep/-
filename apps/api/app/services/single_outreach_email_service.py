"""单个红人 AI 定制邮件试发：预览与真实发送。"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.utils.email_display import format_email_display
from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.schemas.email_log import EmailLogRead
from app.schemas.outreach_email import (
    SingleOutreachEmailPreviewResponse,
    SingleOutreachEmailSendRequest,
    SingleOutreachEmailSendResponse,
)
from app.services.ai.openai_client import OPENAI_NOT_CONFIGURED_MSG
from app.services.contact_signals import build_contact_summary
from app.services.email import (
    EmailNotConfiguredError,
    EmailService,
    format_smtp_send_error,
    resolve_influencer_email,
)
from app.services.email_reply_utils import build_outbound_message_id
from app.services.influencer_lead import InfluencerLeadService
from app.services.influencer_projection import merged_influencer_for_ai
from app.services.outreach_recipient import validate_real_outreach_recipient
from app.services.product_influencer_service import ProductInfluencerService
from app.services.speech_recommendation_service import SpeechRecommendationService

logger = logging.getLogger(__name__)

BLOCKED_FOLLOW_STATUSES = frozenset({"blacklisted", "invalid"})


class SingleOutreachEmailService:
    @staticmethod
    async def _load_pair(
        db: AsyncSession,
        *,
        product_id: int,
        influencer_id: int,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile]:
        pair = await ProductInfluencerService.get_product_influencer(
            db,
            product_id=product_id,
            record_id=influencer_id,
        )
        if not pair:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="红人不存在或不属于当前产品",
            )
        return pair

    @staticmethod
    def _assert_sendable(
        product_row: ProductInfluencer,
        recipient: str | None,
    ) -> str:
        follow = (product_row.follow_status or "").lower()
        if follow in BLOCKED_FOLLOW_STATUSES:
            label = "黑名单" if follow == "blacklisted" else "无效"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"红人状态为{label}，无法发送邮件",
            )
        if not recipient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少邮箱，无法发送",
            )
        return validate_real_outreach_recipient(recipient)

    @staticmethod
    async def preview(
        db: AsyncSession,
        *,
        product_id: int,
        influencer_id: int,
    ) -> SingleOutreachEmailPreviewResponse:
        product_row, global_row = await SingleOutreachEmailService._load_pair(
            db, product_id=product_id, influencer_id=influencer_id
        )
        merged = merged_influencer_for_ai(product_row, global_row)
        recipient = resolve_influencer_email(merged)
        SingleOutreachEmailService._assert_sendable(product_row, recipient)

        if not settings.is_openai_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=OPENAI_NOT_CONFIGURED_MSG,
            )

        contact_summary = build_contact_summary(merged)
        try:
            generation = await SpeechRecommendationService.generate_single_trial_outreach_email(
                db,
                product_id=product_id,
                global_row=global_row,
                product_row=product_row,
                contact_summary=contact_summary,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            logger.exception("Single outreach preview failed for influencer %s", influencer_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc)[:500],
            ) from exc

        sender = settings.smtp_from or settings.smtp_user or ""
        return SingleOutreachEmailPreviewResponse(
            subject=generation.subject,
            body=generation.body,
            recipient=recipient or "",
            sender_email=sender,
            sender_display=format_email_display(sender, settings.smtp_from_name),
            template_title=generation.recommended_script_title,
            reason=generation.reason,
            matched_knowledge=generation.matched_knowledge,
        )

    @staticmethod
    async def send(
        db: AsyncSession,
        *,
        product_id: int,
        user_id: int | None,
        influencer_id: int,
        payload: SingleOutreachEmailSendRequest,
    ) -> SingleOutreachEmailSendResponse:
        product_row, global_row = await SingleOutreachEmailService._load_pair(
            db, product_id=product_id, influencer_id=influencer_id
        )
        merged = merged_influencer_for_ai(product_row, global_row)
        recipient = SingleOutreachEmailService._assert_sendable(
            product_row,
            resolve_influencer_email(merged),
        )

        subject = payload.subject.strip()
        body = payload.body.strip()
        if not subject or not body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮件标题和正文不能为空",
            )

        try:
            EmailService.ensure_smtp_configured()
        except EmailNotConfiguredError as exc:
            log = await EmailService.create_outreach_email_log(
                db,
                task_id=None,
                recipients=[recipient],
                subject=subject,
                body=body,
                status=EmailLogStatus.FAILED,
                error_message=exc.message,
                product_id=product_id,
                user_id=user_id,
                product_influencer_id=product_row.id,
                influencer_username=global_row.username,
                generated_by_ai=True,
                ai_provider="openai",
            )
            await db.commit()
            return SingleOutreachEmailSendResponse(
                success=False,
                message=exc.message,
                email_log=EmailLogRead.model_validate(log),
            )

        message_id = build_outbound_message_id(product_id=product_id)
        message = MIMEMultipart()
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message.attach(MIMEText(body, "plain", "utf-8"))

        try:
            await EmailService._send_message(message, [recipient])
            log = await EmailService.create_outreach_email_log(
                db,
                task_id=None,
                recipients=[recipient],
                subject=subject,
                body=body,
                status=EmailLogStatus.SENT,
                product_id=product_id,
                user_id=user_id,
                product_influencer_id=product_row.id,
                influencer_username=global_row.username,
                generated_by_ai=True,
                ai_provider="openai",
                message_id=message_id,
            )
            await InfluencerLeadService.mark_product_email_sent(
                db,
                product_row,
                subject=subject,
                operator_name="single_outreach_trial",
            )
            return SingleOutreachEmailSendResponse(
                success=True,
                message="邮件发送成功",
                email_log=EmailLogRead.model_validate(log),
            )
        except Exception as exc:
            err = format_smtp_send_error(exc)
            logger.warning("Single outreach send failed for %s: %s", influencer_id, err)
            log = await EmailService.create_outreach_email_log(
                db,
                task_id=None,
                recipients=[recipient],
                subject=subject,
                body=body,
                status=EmailLogStatus.FAILED,
                error_message=err,
                product_id=product_id,
                user_id=user_id,
                product_influencer_id=product_row.id,
                influencer_username=global_row.username,
                generated_by_ai=True,
                ai_provider="openai",
            )
            await db.commit()
            return SingleOutreachEmailSendResponse(
                success=False,
                message=f"邮件发送失败：{err}",
                email_log=EmailLogRead.model_validate(log),
            )
