from datetime import UTC, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import hashlib
import logging

import aiosmtplib
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import SMTP_AUTH_FAILED_MSG, SMTP_NOT_CONFIGURED_MSG
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.influencer import Influencer
from app.models.product_influencer import ProductInfluencer
from app.schemas.email import EmailSendResult, EmailTestResponse, MailchimpStatus, SmtpStatus
from app.schemas.email_log import EmailLogRead
from app.services.export import build_influencer_excel
from app.services.influencer_lead import InfluencerLeadService
from app.services.outreach_recipient import normalize_email_address, outreach_recipient_skip_reason
from app.services.task_influencer import TaskInfluencerService

logger = logging.getLogger(__name__)


class EmailNotConfiguredError(Exception):
    def __init__(self, message: str = SMTP_NOT_CONFIGURED_MSG) -> None:
        super().__init__(message)


def format_smtp_send_error(exc: Exception) -> str:
    message = str(exc)
    if "535" in message or "authentication failed" in message.lower():
        return SMTP_AUTH_FAILED_MSG
    return message[:2000]


class MailchimpNotConfiguredError(Exception):
    def __init__(self, message: str = "Mailchimp is not configured.") -> None:
        super().__init__(message)
        self.message = message


MAILCHIMP_SKIP_STATUSES = frozenset({"unsubscribed", "cleaned", "archived", "complained"})


def parse_recipients(raw: list | str | None) -> list[str]:
    """解析收件人，支持 JSON 数组或逗号分隔字符串。"""
    if not raw:
        return []

    if isinstance(raw, str):
        return [email.strip() for email in raw.split(",") if email.strip()]

    recipients: list[str] = []
    for item in raw:
        if isinstance(item, str):
            if "," in item:
                recipients.extend(parse_recipients(item))
            elif item.strip():
                recipients.append(item.strip())
    return recipients


def build_task_email_subject(task: CollectionTask) -> str:
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"海外红人采集结果 - {task.name} - {date_str}"


def build_task_email_body(total_count: int) -> str:
    return f"本次采集完成，共找到 {total_count} 个红人。附件为 Excel 数据表。"


def select_outreach_template(influencer: Influencer, templates: dict | None) -> tuple[str, str]:
    templates = templates or {}
    followers = influencer.followers_count or 0
    tier = "macro" if followers >= 100_000 else "mid" if followers >= 10_000 else "micro"
    subject = templates.get(f"{tier}_subject") or templates.get("subject") or "Collaboration opportunity"
    body = templates.get(f"{tier}_body") or templates.get("body") or (
        "Hi {name},\n\nWe like your content and would love to discuss a possible collaboration."
    )
    values = {
        "name": influencer.display_name or influencer.username,
        "username": influencer.username,
        "platform": influencer.platform,
        "followers": str(followers),
        "category": influencer.category or "",
    }
    for key, value in values.items():
        subject = subject.replace("{" + key + "}", value)
        body = body.replace("{" + key + "}", value)
    return subject, body


from app.services.outreach_recipient import normalize_email_address


def resolve_influencer_email(influencer: Influencer) -> str | None:
    """收件邮箱优先级：final_email > business_email > public_email > email。"""
    for field in ("final_email", "business_email", "public_email", "email"):
        value = getattr(influencer, field, None)
        if value and str(value).strip():
            return normalize_email_address(str(value))
    return None


def resolve_follower_tier(followers: int | None) -> str:
    count = followers or 0
    if count >= 100_000:
        return "macro"
    if count >= 10_000:
        return "mid"
    return "micro"


def _mailchimp_subscriber_hash(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()


class EmailService:
    @staticmethod
    async def _mark_task_outreach_email_sent(
        db: AsyncSession,
        task: CollectionTask,
        influencer: Influencer,
        *,
        subject: str | None,
    ) -> None:
        product_row = await db.get(ProductInfluencer, influencer.id)
        if not product_row or product_row.product_id != task.product_id:
            return
        await InfluencerLeadService.mark_product_email_sent(
            db,
            product_row,
            subject=subject,
            operator_name="outreach",
        )

    @staticmethod
    def get_smtp_status() -> SmtpStatus:
        return SmtpStatus(**settings.get_smtp_status())

    @staticmethod
    def get_mailchimp_status() -> MailchimpStatus:
        return MailchimpStatus(**settings.get_mailchimp_status())

    @staticmethod
    def ensure_mailchimp_configured() -> None:
        if not settings.is_mailchimp_configured:
            raise MailchimpNotConfiguredError()

    @staticmethod
    def _mailchimp_auth() -> tuple[str, str]:
        return ("influencer-intel", settings.mailchimp_api_key.strip())

    @staticmethod
    async def _mailchimp_get_member(email: str) -> dict | None:
        base_url = settings.mailchimp_api_base_url
        list_id = settings.mailchimp_list_id.strip()
        if not base_url or not list_id:
            return None

        subscriber_hash = _mailchimp_subscriber_hash(email)
        url = f"{base_url}/lists/{list_id}/members/{subscriber_hash}"
        async with httpx.AsyncClient(timeout=settings.mailchimp_timeout_seconds) as client:
            response = await client.get(url, auth=EmailService._mailchimp_auth())
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    @staticmethod
    async def sync_contact_to_mailchimp(
        influencer: Influencer,
        task: CollectionTask,
        *,
        dry_run: bool = False,
    ) -> str:
        """
        Sync one influencer email to Mailchimp audience.

        New contacts use status_if_new=pending (double opt-in).
        Existing subscribed/pending members are updated; opted-out members are skipped.
        """
        recipient = resolve_influencer_email(influencer)
        if not recipient:
            return "skipped"

        subject, body = select_outreach_template(influencer, task.outreach_templates)
        tier = resolve_follower_tier(influencer.followers_count)

        if dry_run:
            return "queued"

        EmailService.ensure_mailchimp_configured()
        base_url = settings.mailchimp_api_base_url
        list_id = settings.mailchimp_list_id.strip()
        if not base_url or not list_id:
            raise MailchimpNotConfiguredError()

        existing = await EmailService._mailchimp_get_member(recipient)
        if existing and existing.get("status") in MAILCHIMP_SKIP_STATUSES:
            return "skipped"

        subscriber_hash = _mailchimp_subscriber_hash(recipient)
        url = f"{base_url}/lists/{list_id}/members/{subscriber_hash}"
        payload = {
            "email_address": recipient.strip().lower(),
            "status_if_new": settings.mailchimp_status_if_new.strip() or "pending",
            "merge_fields": {
                "FNAME": (influencer.display_name or influencer.username or "")[:255],
            },
            "tags": [
                f"tier:{tier}",
                f"platform:{influencer.platform}",
                f"task:{task.id}",
            ],
        }

        async with httpx.AsyncClient(timeout=settings.mailchimp_timeout_seconds) as client:
            response = await client.put(url, json=payload, auth=EmailService._mailchimp_auth())
            if response.status_code >= 400:
                detail = response.text[:500]
                raise RuntimeError(f"Mailchimp sync failed ({response.status_code}): {detail}")

        logger.info(
            "Mailchimp synced contact task=%s email=%s tier=%s subject=%s",
            task.id,
            recipient,
            tier,
            subject,
        )
        return "synced"

    @staticmethod
    def ensure_smtp_configured() -> None:
        if not settings.is_smtp_configured:
            raise EmailNotConfiguredError()

    @staticmethod
    async def _send_message(message: MIMEMultipart, recipients: list[str]) -> None:
        send_kwargs: dict = {
            "hostname": settings.smtp_host,
            "port": settings.smtp_port,
            "username": settings.smtp_user,
            "password": settings.smtp_password,
            "recipients": recipients,
        }

        if settings.smtp_port == 465:
            send_kwargs["use_tls"] = True
        elif settings.smtp_use_tls:
            send_kwargs["start_tls"] = True

        await aiosmtplib.send(message, **send_kwargs)

    @staticmethod
    async def _send_with_attachment(
        recipients: list[str],
        subject: str,
        body: str,
        attachment_bytes: bytes,
        attachment_filename: str,
    ) -> None:
        EmailService.ensure_smtp_configured()

        message = MIMEMultipart()
        message["From"] = settings.smtp_from
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain", "utf-8"))

        attachment = MIMEApplication(attachment_bytes, Name=attachment_filename)
        attachment.add_header("Content-Disposition", "attachment", filename=attachment_filename)
        message.attach(attachment)

        await EmailService._send_message(message, recipients)

    @staticmethod
    async def create_outreach_email_log(
        db: AsyncSession,
        *,
        task_id: int | None,
        recipients: list[str],
        subject: str,
        body: str | None,
        status: EmailLogStatus,
        attachment_path: str | None = None,
        error_message: str | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
        product_influencer_id: int | None = None,
        sender_email: str | None = None,
        influencer_username: str | None = None,
        generated_by_ai: bool = False,
        ai_provider: str | None = None,
        ai_reason: str | None = None,
        matched_knowledge: list | None = None,
        risk_notes: list | None = None,
        message_id: str | None = None,
        reply_email_log_id: int | None = None,
    ) -> EmailLog:
        log = EmailLog(
            task_id=task_id,
            product_id=product_id,
            user_id=user_id,
            product_influencer_id=product_influencer_id,
            sender_email=sender_email or settings.smtp_from or None,
            influencer_username=influencer_username,
            recipients=recipients,
            subject=subject,
            body=body,
            status=status.value,
            attachment_path=attachment_path,
            error_message=error_message,
            generated_by_ai=generated_by_ai,
            ai_provider=ai_provider,
            ai_reason=ai_reason,
            matched_knowledge=matched_knowledge,
            risk_notes=risk_notes,
            sent_at=datetime.now(UTC) if status == EmailLogStatus.SENT else None,
            message_id=message_id,
            reply_email_log_id=reply_email_log_id,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        return log

    @staticmethod
    async def _create_email_log(
        db: AsyncSession,
        *,
        task_id: int | None,
        recipients: list[str],
        subject: str,
        status: EmailLogStatus,
        attachment_path: str | None = None,
        error_message: str | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
        product_influencer_id: int | None = None,
        sender_email: str | None = None,
        influencer_username: str | None = None,
        body: str | None = None,
        generated_by_ai: bool = False,
        ai_provider: str | None = None,
        ai_reason: str | None = None,
        matched_knowledge: list | None = None,
        risk_notes: list | None = None,
        message_id: str | None = None,
        reply_email_log_id: int | None = None,
    ) -> EmailLog:
        return await EmailService.create_outreach_email_log(
            db,
            task_id=task_id,
            recipients=recipients,
            subject=subject,
            body=body,
            status=status,
            attachment_path=attachment_path,
            error_message=error_message,
            product_id=product_id,
            user_id=user_id,
            product_influencer_id=product_influencer_id,
            sender_email=sender_email,
            influencer_username=influencer_username,
            generated_by_ai=generated_by_ai,
            ai_provider=ai_provider,
            ai_reason=ai_reason,
            matched_knowledge=matched_knowledge,
            risk_notes=risk_notes,
            message_id=message_id,
            reply_email_log_id=reply_email_log_id,
        )

    @staticmethod
    async def send_test_email(recipient: str | None = None) -> EmailTestResponse:
        EmailService.ensure_smtp_configured()

        if not recipient or not str(recipient).strip():
            return EmailTestResponse(
                success=False,
                message="请填写测试收件人邮箱。SMTP 测试邮件仅用于验证配置，不会发送红人外联邮件。",
                recipient=None,
            )

        to_address = normalize_email_address(recipient)
        if not to_address:
            return EmailTestResponse(
                success=False,
                message="测试收件人邮箱无效，请重新填写。",
                recipient=None,
            )

        subject = f"Influencer Intel SMTP 测试 - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
        body = (
            "这是一封来自 Influencer Intel 的 SMTP 测试邮件。"
            "如果您收到此邮件，说明邮件服务配置正确。"
            "此邮件不是红人外联邮件。"
        )

        message = MIMEMultipart()
        message["From"] = settings.smtp_from
        message["To"] = to_address
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain", "utf-8"))

        try:
            await EmailService._send_message(message, [to_address])
        except Exception as exc:
            error_message = format_smtp_send_error(exc)
            if settings.smtp_from_user_mismatch:
                from app.core.config import SMTP_FROM_USER_MISMATCH_MSG

                error_message = f"{error_message} {SMTP_FROM_USER_MISMATCH_MSG}"
            return EmailTestResponse(
                success=False,
                message=f"测试邮件发送失败：{error_message}",
                recipient=to_address,
            )

        return EmailTestResponse(
            success=True,
            message=f"SMTP 测试邮件已发送至 {to_address}（仅用于验证 SMTP 配置，不是红人外联邮件）。",
            recipient=to_address,
        )

    @staticmethod
    async def send_task_email(
        db: AsyncSession,
        task: CollectionTask,
        total_count: int | None = None,
    ) -> EmailSendResult:
        recipients = parse_recipients(task.email_recipients)
        subject = build_task_email_subject(task)
        tenant = {"product_id": task.product_id, "user_id": task.user_id}

        if not settings.is_smtp_configured:
            log = await EmailService._create_email_log(
                db,
                task_id=task.id,
                recipients=recipients,
                subject=subject,
                status=EmailLogStatus.FAILED,
                error_message=SMTP_NOT_CONFIGURED_MSG,
                **tenant,
            )
            return EmailSendResult(
                success=False,
                message=SMTP_NOT_CONFIGURED_MSG,
                task_id=task.id,
                total_count=0,
                recipients=recipients,
                email_log=EmailLogRead.model_validate(log),
            )

        if not recipients:
            message = "任务未配置收件人，请在 email_recipients 中设置。"
            log = await EmailService._create_email_log(
                db,
                task_id=task.id,
                recipients=[],
                subject=subject,
                status=EmailLogStatus.FAILED,
                error_message=message,
                **tenant,
            )
            return EmailSendResult(
                success=False,
                message=message,
                task_id=task.id,
                total_count=0,
                recipients=[],
                email_log=EmailLogRead.model_validate(log),
            )

        influencers = await TaskInfluencerService.get_influencers_for_task(db, task)
        count = total_count if total_count is not None else len(influencers)
        body = build_task_email_body(count)

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
        attachment_filename = f"influencer_task_{task.id}_{timestamp}.xlsx"
        excel_bytes, _ = build_influencer_excel(influencers, filename=attachment_filename)

        try:
            await EmailService._send_with_attachment(
                recipients=recipients,
                subject=subject,
                body=body,
                attachment_bytes=excel_bytes,
                attachment_filename=attachment_filename,
            )
            log = await EmailService._create_email_log(
                db,
                task_id=task.id,
                recipients=recipients,
                subject=subject,
                status=EmailLogStatus.SENT,
                attachment_path=attachment_filename,
                **tenant,
            )
            return EmailSendResult(
                success=True,
                message="邮件发送成功。",
                task_id=task.id,
                total_count=count,
                recipients=recipients,
                email_log=EmailLogRead.model_validate(log),
            )
        except EmailNotConfiguredError as exc:
            log = await EmailService._create_email_log(
                db,
                task_id=task.id,
                recipients=recipients,
                subject=subject,
                status=EmailLogStatus.FAILED,
                error_message=exc.message,
                **tenant,
            )
            return EmailSendResult(
                success=False,
                message=exc.message,
                task_id=task.id,
                total_count=count,
                recipients=recipients,
                email_log=EmailLogRead.model_validate(log),
            )
        except Exception as exc:
            error_message = format_smtp_send_error(exc)
            log = await EmailService._create_email_log(
                db,
                task_id=task.id,
                recipients=recipients,
                subject=subject,
                status=EmailLogStatus.FAILED,
                attachment_path=attachment_filename,
                error_message=error_message,
                **tenant,
            )
            return EmailSendResult(
                success=False,
                message=f"邮件发送失败：{error_message}",
                task_id=task.id,
                total_count=count,
                recipients=recipients,
                email_log=EmailLogRead.model_validate(log),
            )

    @staticmethod
    async def send_task_email_after_collection(
        db: AsyncSession,
        task: CollectionTask,
        total_count: int,
    ) -> EmailSendResult | None:
        if not task.email_enabled:
            return None
        return await EmailService.send_task_email(db, task, total_count=total_count)

    @staticmethod
    async def sync_outreach_contacts_after_collection(
        db: AsyncSession,
        task: CollectionTask,
    ) -> dict[str, int]:
        influencers = await TaskInfluencerService.get_influencers_for_task(db, task)
        queued = 0
        sent = 0
        failed = 0
        skipped = 0

        provider = (task.outreach_provider or "smtp").strip().lower()
        dry_run = bool(task.outreach_dry_run)
        tenant = {"product_id": task.product_id, "user_id": task.user_id}

        for influencer in influencers:
            recipient = resolve_influencer_email(influencer)
            if outreach_recipient_skip_reason(recipient):
                skipped += 1
                continue
            recipient = normalize_email_address(recipient) or recipient

            from app.models.global_influencer_profile import GlobalInfluencerProfile
            from app.models.product_influencer import ProductInfluencer
            from app.services.speech_recommendation_service import SpeechRecommendationService

            product_row = await db.get(ProductInfluencer, influencer.id)
            if not product_row or product_row.product_id != task.product_id:
                skipped += 1
                continue
            global_row = await db.get(GlobalInfluencerProfile, product_row.global_influencer_id)
            if not global_row:
                skipped += 1
                continue

            generation = await SpeechRecommendationService.generate_outreach_email(
                db,
                product_id=task.product_id,
                global_row=global_row,
                product_row=product_row,
                user_intent="首次合作邀约",
            )
            subject = generation.subject
            body = generation.body
            ai_meta = {
                "body": body,
                "generated_by_ai": generation.configured and generation.provider == "openai",
                "ai_provider": generation.provider,
                "ai_reason": generation.reason,
                "matched_knowledge": [item.model_dump(mode="json") for item in generation.matched_knowledge],
                "risk_notes": generation.risk_notes,
            }

            if provider == "mailchimp":
                try:
                    result = await EmailService.sync_contact_to_mailchimp(
                        influencer,
                        task,
                        dry_run=dry_run,
                    )
                    if result == "skipped":
                        skipped += 1
                        continue
                    if result == "queued":
                        await EmailService._create_email_log(
                            db,
                            task_id=task.id,
                            recipients=[recipient],
                            subject=subject,
                            status=EmailLogStatus.PENDING,
                            error_message=f"Mailchimp dry-run queued (tier={resolve_follower_tier(influencer.followers_count)})",
                            product_influencer_id=influencer.id,
                            influencer_username=influencer.username,
                            **tenant,
                            **ai_meta,
                        )
                        queued += 1
                        continue

                    await EmailService._create_email_log(
                        db,
                        task_id=task.id,
                        recipients=[recipient],
                        subject=subject,
                        status=EmailLogStatus.SENT,
                        error_message="Mailchimp audience sync",
                        product_influencer_id=influencer.id,
                        influencer_username=influencer.username,
                        **tenant,
                        **ai_meta,
                    )
                    await EmailService._mark_task_outreach_email_sent(
                        db,
                        task,
                        influencer,
                        subject=subject,
                    )
                    sent += 1
                except Exception as exc:
                    await EmailService._create_email_log(
                        db,
                        task_id=task.id,
                        recipients=[recipient],
                        subject=subject,
                        status=EmailLogStatus.FAILED,
                        error_message=str(exc)[:2000],
                        product_influencer_id=influencer.id,
                        influencer_username=influencer.username,
                        **tenant,
                        **ai_meta,
                    )
                    failed += 1
                continue

            if dry_run or provider != "smtp":
                await EmailService._create_email_log(
                    db,
                    task_id=task.id,
                    recipients=[recipient],
                    subject=subject,
                    status=EmailLogStatus.PENDING,
                    error_message=f"Outreach queued via {provider}; dry_run={dry_run}",
                    product_influencer_id=influencer.id,
                    influencer_username=influencer.username,
                    **tenant,
                    **ai_meta,
                )
                queued += 1
                continue

            try:
                EmailService.ensure_smtp_configured()
                message = MIMEMultipart()
                message["From"] = settings.smtp_from
                message["To"] = recipient
                message["Subject"] = subject
                message.attach(MIMEText(body, "plain", "utf-8"))
                await EmailService._send_message(message, [recipient])
                await EmailService._create_email_log(
                    db,
                    task_id=task.id,
                    recipients=[recipient],
                    subject=subject,
                    status=EmailLogStatus.SENT,
                    product_influencer_id=influencer.id,
                    influencer_username=influencer.username,
                    **tenant,
                    **ai_meta,
                )
                await EmailService._mark_task_outreach_email_sent(
                    db,
                    task,
                    influencer,
                    subject=subject,
                )
                sent += 1
            except Exception as exc:
                await EmailService._create_email_log(
                    db,
                    task_id=task.id,
                    recipients=[recipient],
                    subject=subject,
                    status=EmailLogStatus.FAILED,
                    error_message=str(exc)[:2000],
                    product_influencer_id=influencer.id,
                    influencer_username=influencer.username,
                    **tenant,
                    **ai_meta,
                )
                failed += 1

        return {"queued": queued, "sent": sent, "failed": failed, "skipped": skipped}
