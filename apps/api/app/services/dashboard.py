from sqlalchemy import func, or_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CollectionTaskStatus, EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.schemas.dashboard import DashboardSummary, PlatformCount
from app.services.collection_task import CollectionTaskService
from app.services.email_log import EmailLogService
from app.services.tenant_scope import ALL_PRODUCTS_ID, scoped_product_id


class DashboardService:
    @staticmethod
    def _empty_summary() -> DashboardSummary:
        return DashboardSummary(
            total_influencers=0,
            total_tasks=0,
            active_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
            total_email_logs=0,
            sent_emails=0,
            failed_emails=0,
            instagram_influencers=0,
            email_coverage_rate=0.0,
            contactable_count=0,
            high_match_count=0,
            average_score=None,
            average_product_fit=None,
            average_roi_forecast=None,
            platforms=[],
            recent_tasks=[],
        )

    @staticmethod
    def _inserted_scope(product_id: int, *, PI=ProductInfluencer):
        if product_id == ALL_PRODUCTS_ID:
            return PI.is_inserted.is_(True)
        return (PI.product_id == product_id) & PI.is_inserted.is_(True)

    @staticmethod
    def _product_join(product_id: int):
        return (
            select(ProductInfluencer, GlobalInfluencerProfile)
            .join(GlobalInfluencerProfile, ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id)
            .where(DashboardService._inserted_scope(product_id))
        )

    @staticmethod
    async def get_summary(db: AsyncSession, *, product_id: int) -> DashboardSummary:
        try:
            PI, GP = ProductInfluencer, GlobalInfluencerProfile
            scope = DashboardService._inserted_scope(product_id, PI=PI)
            scoped_tasks = scoped_product_id(product_id)
            base = DashboardService._product_join(product_id).subquery()
            total_influencers = await db.scalar(select(func.count()).select_from(base)) or 0

            instagram_influencers = await db.scalar(
                select(func.count())
                .select_from(PI)
                .join(GP, PI.global_influencer_id == GP.id)
                .where(scope, GP.platform == "instagram")
            ) or 0

            email_count = await db.scalar(
                select(func.count())
                .select_from(PI)
                .join(GP, PI.global_influencer_id == GP.id)
                .where(
                    scope,
                    or_(
                        GP.final_email.isnot(None),
                        GP.email.isnot(None),
                        GP.public_email.isnot(None),
                        GP.business_email.isnot(None),
                    ),
                )
            ) or 0

            contactable_count = await db.scalar(
                select(func.count())
                .select_from(PI)
                .join(GP, PI.global_influencer_id == GP.id)
                .where(
                    scope,
                    or_(
                        GP.final_email.isnot(None),
                        GP.email.isnot(None),
                        GP.public_email.isnot(None),
                        GP.business_email.isnot(None),
                        GP.whatsapp.isnot(None),
                        GP.telegram.isnot(None),
                        GP.contact_page.isnot(None),
                        GP.linktree_url.isnot(None),
                    ),
                )
            ) or 0

            high_match_count = await db.scalar(
                select(func.count())
                .select_from(PI)
                .where(scope, PI.score >= 75, PI.product_fit >= 70)
            ) or 0

            average_score = await db.scalar(select(func.avg(PI.score)).where(scope))
            average_product_fit = await db.scalar(select(func.avg(PI.product_fit)).where(scope))
            average_roi_forecast = await db.scalar(select(func.avg(PI.roi_forecast)).where(scope))

            platform_rows = await db.execute(
                select(GP.platform, func.count())
                .select_from(PI)
                .join(GP, PI.global_influencer_id == GP.id)
                .where(scope)
                .group_by(GP.platform)
                .order_by(func.count().desc())
            )
            platforms = [PlatformCount(platform=row[0], count=row[1]) for row in platform_rows.all()]

            total_tasks = await CollectionTaskService.count_all(db, product_id=scoped_tasks)
            active_tasks = await CollectionTaskService.count_by_status(
                db, CollectionTaskStatus.RUNNING, product_id=scoped_tasks
            )
            active_tasks += await CollectionTaskService.count_by_status(
                db, CollectionTaskStatus.PENDING, product_id=scoped_tasks
            )
            completed_tasks = await CollectionTaskService.count_by_statuses(
                db,
                [
                    CollectionTaskStatus.COMPLETED,
                    CollectionTaskStatus.COMPLETED_WITH_RESULTS,
                    CollectionTaskStatus.COMPLETED_NO_RESULTS,
                    CollectionTaskStatus.PARTIAL_FAILED,
                ],
                product_id=scoped_tasks,
            )
            failed_tasks = await CollectionTaskService.count_by_status(
                db, CollectionTaskStatus.FAILED, product_id=scoped_tasks
            )

            total_email_logs = await EmailLogService.count_all(db, product_id=scoped_tasks)
            sent_emails = await EmailLogService.count_by_status(
                db, EmailLogStatus.SENT, product_id=scoped_tasks
            )
            failed_emails = await EmailLogService.count_by_status(
                db, EmailLogStatus.FAILED, product_id=scoped_tasks
            )

            recent_tasks = await CollectionTaskService.get_recent_tasks(db, limit=5, product_id=scoped_tasks)
        except ProgrammingError as exc:
            await db.rollback()
            err = str(exc).lower()
            if "does not exist" in err or "undefinedcolumn" in err or "不存在" in str(exc):
                return DashboardService._empty_summary()
            raise

        return DashboardSummary(
            total_influencers=total_influencers,
            total_tasks=total_tasks,
            active_tasks=active_tasks,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            total_email_logs=total_email_logs,
            sent_emails=sent_emails,
            failed_emails=failed_emails,
            instagram_influencers=instagram_influencers,
            email_coverage_rate=round((email_count / total_influencers) * 100, 1) if total_influencers else 0.0,
            contactable_count=contactable_count,
            high_match_count=high_match_count,
            average_score=round(float(average_score), 1) if average_score is not None else None,
            average_product_fit=round(float(average_product_fit), 1) if average_product_fit is not None else None,
            average_roi_forecast=round(float(average_roi_forecast), 1) if average_roi_forecast is not None else None,
            platforms=platforms,
            recent_tasks=recent_tasks,
        )
