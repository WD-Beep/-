# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：email sent status
"""红人邮件发送状态：仅基于成功 email_logs（product 隔离 + product_influencer 关联）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer

SUCCESS_EMAIL_STATUSES = frozenset(
    {
        EmailLogStatus.SENT.value,
        "success",
        "delivered",
    }
)


@dataclass(frozen=True)
class EmailSentInfo:
    email_sent: bool
    last_email_sent_at: datetime | None
    last_email_subject: str | None


def successful_email_sent_exists(
    product_id: int,
    *,
    PI=ProductInfluencer,
    GP=GlobalInfluencerProfile,  # noqa: ARG001 — kept for call-site compatibility
):
    """Correlated EXISTS：当前产品下该红人存在带 product_influencer_id 的成功邮件日志。"""
    return exists(
        select(1).where(
            EmailLog.product_id == product_id,
            EmailLog.product_influencer_id == PI.id,
            EmailLog.status.in_(tuple(SUCCESS_EMAIL_STATUSES)),
        )
    )


async def load_email_sent_map(
    db: AsyncSession,
    *,
    product_id: int,
    product_influencer_ids: list[int],
) -> dict[int, EmailSentInfo]:
    if not product_influencer_ids:
        return {}

    details: dict[int, EmailSentInfo] = {
        pi_id: EmailSentInfo(
            email_sent=False,
            last_email_sent_at=None,
            last_email_subject=None,
        )
        for pi_id in product_influencer_ids
    }

    log_rows = (
        await db.execute(
            select(
                EmailLog.product_influencer_id,
                EmailLog.sent_at,
                EmailLog.subject,
            )
            .where(
                EmailLog.product_id == product_id,
                EmailLog.product_influencer_id.in_(product_influencer_ids),
                EmailLog.status.in_(tuple(SUCCESS_EMAIL_STATUSES)),
            )
            .order_by(EmailLog.sent_at.desc().nullslast(), EmailLog.id.desc())
        )
    ).all()
    for pi_id, sent_at, subject in log_rows:
        if pi_id is None or details[pi_id].email_sent:
            continue
        details[pi_id] = EmailSentInfo(
            email_sent=True,
            last_email_sent_at=sent_at,
            last_email_subject=subject,
        )

    return details


async def product_influencer_has_successful_email_sent(
    db: AsyncSession,
    *,
    product_id: int,
    product_influencer_id: int,
) -> bool:
    """当前产品下该 product_influencer 是否已有成功 email_logs。"""
    found = await db.scalar(
        select(EmailLog.id)
        .where(
            EmailLog.product_id == product_id,
            EmailLog.product_influencer_id == product_influencer_id,
            EmailLog.status.in_(tuple(SUCCESS_EMAIL_STATUSES)),
        )
        .limit(1)
    )
    return found is not None
