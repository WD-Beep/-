"""批量 AI 个性化外联邮件：预览与发送。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.schemas.knowledge import MatchedKnowledgeItem
from app.schemas.outreach_email import (
    OutreachBatchPreviewRequest,
    OutreachBatchPreviewResponse,
    OutreachBatchPreviewSummary,
    OutreachBatchSendRequest,
    OutreachBatchSendResponse,
    OutreachBatchSendSummary,
    OutreachEmailGenerationResult,
    OutreachPreviewItem,
    OutreachSendItemResult,
)
from app.services.email import (
    EmailNotConfiguredError,
    EmailService,
    format_smtp_send_error,
    resolve_influencer_email,
)
from app.services.influencer_lead import InfluencerLeadService
from app.services.influencer_projection import merged_influencer_for_ai
from app.services.outreach_recipient import outreach_recipient_skip_reason
from app.services.product_influencer_service import ProductInfluencerService
from app.services.speech_recommendation_service import SpeechRecommendationService

logger = logging.getLogger(__name__)


def _matched_to_json(items: list[MatchedKnowledgeItem]) -> list[dict]:
    return [item.model_dump(mode="json") for item in items]


class OutreachEmailService:
    @staticmethod
    async def _load_pair(
        db: AsyncSession,
        *,
        product_id: int,
        influencer_id: int,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile] | None:
        pair = await ProductInfluencerService.get_product_influencer(
            db,
            product_id=product_id,
            record_id=influencer_id,
        )
        return pair

    @staticmethod
    async def _generate_for_pair(
        db: AsyncSession,
        *,
        product_id: int,
        product_row: ProductInfluencer,
        global_row: GlobalInfluencerProfile,
        user_intent: str,
        selected_script_ids: list[int] | None,
        language: str | None,
        tone: str | None,
    ) -> OutreachEmailGenerationResult:
        return await SpeechRecommendationService.generate_outreach_email(
            db,
            product_id=product_id,
            global_row=global_row,
            product_row=product_row,
            user_intent=user_intent,
            selected_script_ids=selected_script_ids,
            language=language,
            tone=tone,
        )

    @staticmethod
    async def preview_batch(
        db: AsyncSession,
        *,
        product_id: int,
        payload: OutreachBatchPreviewRequest,
    ) -> OutreachBatchPreviewResponse:
        ids = payload.influencer_ids[: payload.limit]
        items: list[OutreachPreviewItem] = []
        generated = 0
        missing_email = 0
        failed = 0

        for influencer_id in ids:
            pair = await OutreachEmailService._load_pair(
                db, product_id=product_id, influencer_id=influencer_id
            )
            if not pair:
                failed += 1
                items.append(
                    OutreachPreviewItem(
                        influencer_id=influencer_id,
                        username=str(influencer_id),
                        can_send=False,
                        error_message="红人不存在或不属于当前产品",
                    )
                )
                continue

            product_row, global_row = pair
            merged = merged_influencer_for_ai(product_row, global_row)
            recipient = resolve_influencer_email(merged)
            recipient_issue = outreach_recipient_skip_reason(recipient)
            if recipient_issue:
                missing_email += 1
                items.append(
                    OutreachPreviewItem(
                        influencer_id=influencer_id,
                        username=global_row.username or "",
                        display_name=global_row.display_name,
                        recipient=recipient,
                        can_send=False,
                        error_message=recipient_issue,
                    )
                )
                continue

            try:
                generation = await OutreachEmailService._generate_for_pair(
                    db,
                    product_id=product_id,
                    product_row=product_row,
                    global_row=global_row,
                    user_intent=payload.user_intent,
                    selected_script_ids=payload.selected_script_ids,
                    language=payload.language,
                    tone=payload.tone,
                )
                generated += 1
                items.append(
                    OutreachPreviewItem(
                        influencer_id=influencer_id,
                        username=global_row.username or "",
                        display_name=global_row.display_name,
                        recipient=recipient,
                        subject=generation.subject,
                        body=generation.body,
                        reason=generation.reason,
                        matched_knowledge=generation.matched_knowledge,
                        risk_notes=generation.risk_notes,
                        tone=generation.tone,
                        can_send=True,
                        generated_by_ai=generation.configured and generation.provider == "openai",
                        provider=generation.provider,
                        error_message=generation.error_message,
                    )
                )
            except Exception as exc:
                failed += 1
                logger.exception("Preview generation failed for influencer %s", influencer_id)
                items.append(
                    OutreachPreviewItem(
                        influencer_id=influencer_id,
                        username=global_row.username or "",
                        display_name=global_row.display_name,
                        recipient=recipient,
                        can_send=False,
                        error_message=str(exc)[:2000],
                    )
                )

        return OutreachBatchPreviewResponse(
            items=items,
            summary=OutreachBatchPreviewSummary(
                total=len(ids),
                generated=generated,
                missing_email=missing_email,
                failed=failed,
            ),
        )

    @staticmethod
    async def _write_log(
        db: AsyncSession,
        *,
        product_id: int,
        user_id: int | None,
        product_row: ProductInfluencer,
        global_row: GlobalInfluencerProfile,
        recipient: str,
        generation: OutreachEmailGenerationResult,
        status: EmailLogStatus,
        error_message: str | None = None,
        task_id: int | None = None,
    ):
        return await EmailService.create_outreach_email_log(
            db,
            task_id=task_id,
            recipients=[recipient],
            subject=generation.subject,
            body=generation.body,
            status=status,
            error_message=error_message,
            product_id=product_id,
            user_id=user_id,
            product_influencer_id=product_row.id,
            influencer_username=global_row.username,
            generated_by_ai=generation.configured and generation.provider == "openai",
            ai_provider=generation.provider,
            ai_reason=generation.reason,
            matched_knowledge=_matched_to_json(generation.matched_knowledge),
            risk_notes=generation.risk_notes,
        )

    @staticmethod
    async def send_batch(
        db: AsyncSession,
        *,
        product_id: int,
        user_id: int | None,
        payload: OutreachBatchSendRequest,
    ) -> OutreachBatchSendResponse:
        ids = payload.influencer_ids
        results: list[OutreachSendItemResult] = []
        sent = pending = failed = skipped = generated = 0

        if not payload.dry_run:
            try:
                EmailService.ensure_smtp_configured()
            except EmailNotConfiguredError:
                return OutreachBatchSendResponse(
                    items=[
                        OutreachSendItemResult(
                            influencer_id=iid,
                            username="",
                            status=EmailLogStatus.FAILED.value,
                            error_message=SMTP_NOT_CONFIGURED_MSG,
                        )
                        for iid in ids
                    ],
                    summary=OutreachBatchSendSummary(
                        total=len(ids),
                        generated=0,
                        sent=0,
                        pending=0,
                        failed=len(ids),
                        skipped_missing_email=0,
                    ),
                    dry_run=False,
                )

        for influencer_id in ids:
            pair = await OutreachEmailService._load_pair(
                db, product_id=product_id, influencer_id=influencer_id
            )
            if not pair:
                failed += 1
                results.append(
                    OutreachSendItemResult(
                        influencer_id=influencer_id,
                        username=str(influencer_id),
                        status=EmailLogStatus.FAILED.value,
                        error_message="红人不存在或不属于当前产品",
                    )
                )
                continue

            product_row, global_row = pair
            merged = merged_influencer_for_ai(product_row, global_row)
            recipient = resolve_influencer_email(merged)
            username = global_row.username or ""

            recipient_issue = outreach_recipient_skip_reason(recipient)
            if recipient_issue:
                skipped += 1
                results.append(
                    OutreachSendItemResult(
                        influencer_id=influencer_id,
                        username=username,
                        recipient=recipient,
                        status="skipped",
                        error_message=recipient_issue,
                    )
                )
                continue

            try:
                generation = await OutreachEmailService._generate_for_pair(
                    db,
                    product_id=product_id,
                    product_row=product_row,
                    global_row=global_row,
                    user_intent=payload.user_intent,
                    selected_script_ids=payload.selected_script_ids,
                    language=payload.language,
                    tone=payload.tone,
                )
                generated += 1

                if payload.dry_run:
                    log = await OutreachEmailService._write_log(
                        db,
                        product_id=product_id,
                        user_id=user_id,
                        product_row=product_row,
                        global_row=global_row,
                        recipient=recipient,
                        generation=generation,
                        status=EmailLogStatus.PENDING,
                        error_message="dry-run：已生成个性化话术，未 SMTP 发送",
                    )
                    pending += 1
                    results.append(
                        OutreachSendItemResult(
                            influencer_id=influencer_id,
                            username=username,
                            recipient=recipient,
                            subject=generation.subject,
                            body=generation.body,
                            status=EmailLogStatus.PENDING.value,
                            email_log_id=log.id,
                            generated_by_ai=generation.configured and generation.provider == "openai",
                        )
                    )
                    continue

                message = MIMEMultipart()
                message["From"] = settings.smtp_from
                message["To"] = recipient
                message["Subject"] = generation.subject
                message.attach(MIMEText(generation.body, "plain", "utf-8"))

                try:
                    await EmailService._send_message(message, [recipient])
                    log = await OutreachEmailService._write_log(
                        db,
                        product_id=product_id,
                        user_id=user_id,
                        product_row=product_row,
                        global_row=global_row,
                        recipient=recipient,
                        generation=generation,
                        status=EmailLogStatus.SENT,
                    )
                    await InfluencerLeadService.mark_product_email_sent(
                        db,
                        product_row,
                        subject=generation.subject,
                        operator_name="ai_outreach_batch",
                    )
                    sent += 1
                    results.append(
                        OutreachSendItemResult(
                            influencer_id=influencer_id,
                            username=username,
                            recipient=recipient,
                            subject=generation.subject,
                            body=generation.body,
                            status=EmailLogStatus.SENT.value,
                            email_log_id=log.id,
                            generated_by_ai=True,
                        )
                    )
                except Exception as exc:
                    err = format_smtp_send_error(exc)
                    log = await OutreachEmailService._write_log(
                        db,
                        product_id=product_id,
                        user_id=user_id,
                        product_row=product_row,
                        global_row=global_row,
                        recipient=recipient,
                        generation=generation,
                        status=EmailLogStatus.FAILED,
                        error_message=err,
                    )
                    failed += 1
                    results.append(
                        OutreachSendItemResult(
                            influencer_id=influencer_id,
                            username=username,
                            recipient=recipient,
                            subject=generation.subject,
                            body=generation.body,
                            status=EmailLogStatus.FAILED.value,
                            email_log_id=log.id,
                            error_message=err,
                            generated_by_ai=generation.configured and generation.provider == "openai",
                        )
                    )
            except Exception as exc:
                failed += 1
                logger.exception("Batch send failed for influencer %s", influencer_id)
                results.append(
                    OutreachSendItemResult(
                        influencer_id=influencer_id,
                        username=username,
                        recipient=recipient,
                        status=EmailLogStatus.FAILED.value,
                        error_message=str(exc)[:2000],
                    )
                )

        return OutreachBatchSendResponse(
            items=results,
            summary=OutreachBatchSendSummary(
                total=len(ids),
                generated=generated,
                sent=sent,
                pending=pending,
                failed=failed,
                skipped_missing_email=skipped,
            ),
            dry_run=payload.dry_run,
        )
