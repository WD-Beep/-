"""只读：邮件日志与已发送红人统计。"""
import asyncio

from sqlalchemy import func, select, text

from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.services.email_sent_status import SUCCESS_EMAIL_STATUSES


async def main() -> None:
    async with async_session_factory() as db:
        cols = await db.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name='email_logs' ORDER BY ordinal_position
                """
            )
        )
        print("email_logs columns:", [r[0] for r in cols.all()])

        versions = await db.execute(text("SELECT version_num FROM alembic_version"))
        print("alembic_version:", [r[0] for r in versions.all()])

        total_sent = await db.scalar(
            select(func.count())
            .select_from(EmailLog)
            .where(EmailLog.status.in_(tuple(SUCCESS_EMAIL_STATUSES)))
        )
        print("total success email_logs:", total_sent)

        linked_sent = await db.scalar(
            select(func.count())
            .select_from(EmailLog)
            .where(
                EmailLog.status.in_(tuple(SUCCESS_EMAIL_STATUSES)),
                EmailLog.product_influencer_id.isnot(None),
            )
        )
        print("success logs with product_influencer_id:", linked_sent)

        distinct_influencers = await db.scalar(
            select(func.count(func.distinct(EmailLog.product_influencer_id)))
            .select_from(EmailLog)
            .where(
                EmailLog.status.in_(tuple(SUCCESS_EMAIL_STATUSES)),
                EmailLog.product_influencer_id.isnot(None),
            )
        )
        print("distinct influencers with success logs:", distinct_influencers)

        from app.schemas.influencer import InfluencerFilter
        from app.services.product_influencer_service import ProductInfluencerService

        product_id = 1
        sent_filter_total = await db.scalar(
            select(func.count()).select_from(
                ProductInfluencerService._apply_filters(
                    ProductInfluencerService._base_join(product_id),
                    InfluencerFilter(email_status="sent"),
                    product_id=product_id,
                ).subquery()
            )
        )
        print("influencers email_status=sent count:", sent_filter_total)

        all_total = await db.scalar(
            select(func.count()).select_from(
                ProductInfluencerService._base_join(product_id).subquery()
            )
        )
        print("influencers total:", all_total)

        smtp = await db.execute(
            text(
                """
                SELECT sender_email, COUNT(*) FROM email_logs
                WHERE status = :sent
                GROUP BY sender_email
                """
            ),
            {"sent": EmailLogStatus.SENT.value},
        )
        print("sent by sender_email:", list(smtp.all()))


asyncio.run(main())
