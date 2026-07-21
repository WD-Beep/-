# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：dashboard
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CollectionTaskStatus, EmailLogStatus
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_campaign_recipient import OutreachCampaignRecipient
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.schemas.dashboard import (
    DashboardMonthlyReport,
    DashboardSummary,
    MonthlyReportCardSection,
    MonthlyReportFunnelSection,
    MonthlyReportFunnelStep,
    MonthlyReportMetricCard,
    MonthlyReportSkipReason,
    MonthlyReportSkipReasonSection,
    MonthlyReportTodo,
    PlatformCount,
)
from app.services.collection_task import CollectionTaskService
from app.services.email_log import EmailLogService
from app.services.tenant_scope import ALL_PRODUCTS_ID, scoped_product_id


class DashboardService:
    REVIEW_NOTICE = "月报是复盘视角，只展示结果和待办入口；发送仍然必须在草稿审核页完成。"

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
    def _month_window(month: str) -> tuple[datetime, datetime]:
        try:
            year, month_number = (int(part) for part in month.split("-", 1))
            start = datetime(year, month_number, 1, tzinfo=UTC)
        except (TypeError, ValueError):
            now = datetime.now(UTC)
            start = datetime(now.year, now.month, 1, tzinfo=UTC)
        if start.month == 12:
            end = datetime(start.year + 1, 1, 1, tzinfo=UTC)
        else:
            end = datetime(start.year, start.month + 1, 1, tzinfo=UTC)
        return start, end

    @staticmethod
    def _product_filter(model, product_id: int | None):
        if product_id is None or product_id == ALL_PRODUCTS_ID:
            return True
        return model.product_id == product_id

    @staticmethod
    def _in_month(column, start: datetime, end: datetime):
        return column >= start, column < end

    @staticmethod
    async def _count(db: AsyncSession, model, *filters) -> int:
        return await db.scalar(select(func.count()).select_from(model).where(*filters)) or 0

    @staticmethod
    def _format_int(value: int) -> str:
        return f"{value:,}"

    @staticmethod
    def _format_percent(numerator: int, denominator: int) -> str:
        return f"{round((numerator / denominator) * 100, 1)}%" if denominator else "0%"

    @staticmethod
    def _format_roi(value) -> str:
        return f"{round(float(value), 1)}x" if value is not None else "0x"

    @staticmethod
    def _skip_reason_bucket(reason: str | None) -> str:
        text = (reason or "").lower()
        if "缺邮箱" in text or "missing" in text or "no email" in text:
            return "缺邮箱"
        if "无效" in text or "invalid" in text:
            return "无效邮箱"
        if "黑名单" in text or "blacklist" in text:
            return "黑名单"
        if "已发送" in text or "sent" in text:
            return "已发送"
        if "已回复" in text or "replied" in text or "interested" in text:
            return "已回复"
        if "高价值" in text or "high_value" in text:
            return "高价值未确认"
        if "未批准" in text or "not approved" in text or "草稿" in text:
            return "草稿未批准"
        return "草稿未批准"

    @staticmethod
    async def get_monthly_report(db: AsyncSession, *, product_id: int, month: str) -> DashboardMonthlyReport:
        start, end = DashboardService._month_window(month)
        month_key = start.strftime("%Y-%m")
        PI, GP = ProductInfluencer, GlobalInfluencerProfile
        pi_scope = DashboardService._inserted_scope(product_id, PI=PI)
        product_scope = scoped_product_id(product_id)

        total_influencers = await db.scalar(
            select(func.count())
            .select_from(PI)
            .join(GP, PI.global_influencer_id == GP.id)
            .where(pi_scope)
        ) or 0
        instagram_count = await db.scalar(
            select(func.count())
            .select_from(PI)
            .join(GP, PI.global_influencer_id == GP.id)
            .where(pi_scope, GP.platform == "instagram")
        ) or 0
        email_count = await db.scalar(
            select(func.count())
            .select_from(PI)
            .join(GP, PI.global_influencer_id == GP.id)
            .where(
                pi_scope,
                or_(
                    GP.final_email.isnot(None),
                    GP.email.isnot(None),
                    GP.public_email.isnot(None),
                    GP.business_email.isnot(None),
                ),
            )
        ) or 0
        high_match_count = await db.scalar(
            select(func.count()).select_from(PI).where(pi_scope, PI.score >= 75, PI.product_fit >= 70)
        ) or 0
        roi_avg = await db.scalar(select(func.avg(PI.roi_forecast)).where(pi_scope))
        task_count = await DashboardService._count(
            db,
            CollectionTask,
            DashboardService._product_filter(CollectionTask, product_scope),
            *DashboardService._in_month(CollectionTask.created_at, start, end),
        )
        email_log_count = await DashboardService._count(
            db,
            EmailLog,
            DashboardService._product_filter(EmailLog, product_scope),
            *DashboardService._in_month(EmailLog.sent_at, start, end),
        )

        campaign_ids_rows = await db.execute(
            select(OutreachEmailCampaign.id).where(
                DashboardService._product_filter(OutreachEmailCampaign, product_id),
                *DashboardService._in_month(OutreachEmailCampaign.previewed_at, start, end),
            )
        )
        campaign_ids = [row[0] for row in campaign_ids_rows.all()]
        recipient_scope = [OutreachCampaignRecipient.campaign_id.in_(campaign_ids)] if campaign_ids else [False]

        generated = await DashboardService._count(db, OutreachCampaignRecipient, *recipient_scope)
        reviewed = await DashboardService._count(
            db,
            OutreachCampaignRecipient,
            *recipient_scope,
            or_(
                OutreachCampaignRecipient.opened_at.isnot(None),
                OutreachCampaignRecipient.approved_at.isnot(None),
                OutreachCampaignRecipient.skipped_at.isnot(None),
                OutreachCampaignRecipient.draft_status.in_(["modified", "approved", "skipped", "queued"]),
            ),
        )
        approved = await DashboardService._count(
            db,
            OutreachCampaignRecipient,
            *recipient_scope,
            or_(
                OutreachCampaignRecipient.approved_at.isnot(None),
                OutreachCampaignRecipient.draft_status.in_(["approved", "queued"]),
            ),
        )
        queued = await DashboardService._count(
            db,
            OutreachSendQueueItem,
            DashboardService._product_filter(OutreachSendQueueItem, product_id),
            *DashboardService._in_month(OutreachSendQueueItem.created_at, start, end),
        )
        sent = await DashboardService._count(
            db,
            OutreachSendQueueItem,
            DashboardService._product_filter(OutreachSendQueueItem, product_id),
            OutreachSendQueueItem.status == "sent",
            *DashboardService._in_month(OutreachSendQueueItem.sent_at, start, end),
        )
        failed = await DashboardService._count(
            db,
            OutreachSendQueueItem,
            DashboardService._product_filter(OutreachSendQueueItem, product_id),
            OutreachSendQueueItem.status == "failed",
            *DashboardService._in_month(OutreachSendQueueItem.failed_at, start, end),
        )
        replied = await DashboardService._count(
            db,
            EmailReply,
            DashboardService._product_filter(EmailReply, product_id),
            *DashboardService._in_month(EmailReply.received_at, start, end),
        )
        interested = await DashboardService._count(
            db,
            EmailReply,
            DashboardService._product_filter(EmailReply, product_id),
            EmailReply.intent_status == "interested",
            *DashboardService._in_month(EmailReply.received_at, start, end),
        )

        pending_review = await DashboardService._count(
            db,
            OutreachCampaignRecipient,
            *recipient_scope,
            OutreachCampaignRecipient.draft_status == "pending_review",
        )
        modified = await DashboardService._count(
            db,
            OutreachCampaignRecipient,
            *recipient_scope,
            OutreachCampaignRecipient.draft_status == "modified",
        )
        high_value_pending = await DashboardService._count(
            db,
            OutreachCampaignRecipient,
            *recipient_scope,
            OutreachCampaignRecipient.is_high_value.is_(True),
            OutreachCampaignRecipient.draft_status == "pending_review",
        )
        skipped = await DashboardService._count(
            db,
            OutreachCampaignRecipient,
            *recipient_scope,
            OutreachCampaignRecipient.draft_status == "skipped",
        )
        high_value_total = await DashboardService._count(
            db,
            OutreachCampaignRecipient,
            *recipient_scope,
            OutreachCampaignRecipient.is_high_value.is_(True),
        )
        high_value_confirmed = await DashboardService._count(
            db,
            OutreachCampaignRecipient,
            *recipient_scope,
            OutreachCampaignRecipient.is_high_value.is_(True),
            OutreachCampaignRecipient.approved_at.isnot(None),
        )

        skip_rows = await db.execute(
            select(OutreachCampaignRecipient.skip_reason, func.count())
            .where(*recipient_scope, OutreachCampaignRecipient.skip_reason.isnot(None))
            .group_by(OutreachCampaignRecipient.skip_reason)
        )
        skip_counts = {
            "缺邮箱": 0,
            "无效邮箱": 0,
            "黑名单": 0,
            "已发送": 0,
            "已回复": 0,
            "高价值未确认": high_value_pending,
            "草稿未批准": pending_review,
        }
        for reason, count in skip_rows.all():
            bucket = DashboardService._skip_reason_bucket(reason)
            skip_counts[bucket] = skip_counts.get(bucket, 0) + int(count)

        today = datetime.now(UTC)
        today_sent = await DashboardService._count(
            db,
            OutreachSendQueueItem,
            DashboardService._product_filter(OutreachSendQueueItem, product_id),
            OutreachSendQueueItem.status == "sent",
            OutreachSendQueueItem.sent_at >= datetime(today.year, today.month, today.day, tzinfo=UTC),
        )
        quota_remaining = max(0, 200 - today_sent)

        overview = MonthlyReportCardSection(
            title="运营总览",
            cards=[
                MonthlyReportMetricCard(label="Instagram 达人数", value=DashboardService._format_int(instagram_count), helper=f"总库 {DashboardService._format_int(total_influencers)} 人", href="/influencers?platform=instagram", tone="primary"),
                MonthlyReportMetricCard(label="邮箱覆盖率", value=DashboardService._format_percent(email_count, total_influencers), helper=f"有邮箱 {DashboardService._format_int(email_count)} 人", href="/influencers?has_email=true", tone="success"),
                MonthlyReportMetricCard(label="高匹配达人", value=DashboardService._format_int(high_match_count), helper="评分 >=75 且匹配度 >=70", href="/influencers?high_value=true", tone="warning"),
                MonthlyReportMetricCard(label="ROI 预估均值", value=DashboardService._format_roi(roi_avg), helper="基于当前产品达人", href="/influencers?sort=roi", tone="primary"),
                MonthlyReportMetricCard(label="采集任务数", value=DashboardService._format_int(task_count), helper=f"{month_key} 新建任务", href="/collection-tasks", tone="neutral"),
                MonthlyReportMetricCard(label="邮件记录数", value=DashboardService._format_int(email_log_count), helper=f"本月回复 {DashboardService._format_int(replied)} 封", href="/outreach-records", tone="primary"),
            ],
        )
        return DashboardMonthlyReport(
            month=month_key,
            updated_at=datetime.now(UTC),
            review_notice=DashboardService.REVIEW_NOTICE,
            overview=overview,
            outreach_recap=MonthlyReportFunnelSection(
                title="外联运营复盘",
                funnel=[
                    MonthlyReportFunnelStep(label="AI 生成草稿", value=generated, href="/outreach-campaigns"),
                    MonthlyReportFunnelStep(label="已审核", value=reviewed, href="/outreach-campaigns"),
                    MonthlyReportFunnelStep(label="已批准", value=approved, href="/outreach-campaigns"),
                    MonthlyReportFunnelStep(label="已入队", value=queued, href="/outreach-send-queue?status=queued"),
                    MonthlyReportFunnelStep(label="已发送", value=sent, href="/outreach-records?view=sent"),
                    MonthlyReportFunnelStep(label="已回复", value=replied, href="/email-replies"),
                    MonthlyReportFunnelStep(label="有合作意向", value=interested, href="/email-replies?intent_status=interested"),
                ],
            ),
            draft_quality=MonthlyReportCardSection(
                title="草稿审核质量",
                cards=[
                    MonthlyReportMetricCard(label="待审核草稿", value=str(pending_review), helper="进入草稿审核页处理", href="/outreach-campaigns", tone="warning"),
                    MonthlyReportMetricCard(label="已修改草稿", value=str(modified), helper="人工优化过的草稿", href="/outreach-campaigns", tone="primary"),
                    MonthlyReportMetricCard(label="高价值待确认", value=str(high_value_pending), helper="需要打开确认，避免误发", href="/outreach-campaigns", tone="warning"),
                    MonthlyReportMetricCard(label="已跳过草稿", value=str(skipped), helper="查看跳过原因", href="/outreach-campaigns", tone="neutral"),
                    MonthlyReportMetricCard(label="草稿批准率", value=DashboardService._format_percent(approved, generated), helper="已批准 / AI 草稿", href="/outreach-campaigns", tone="success"),
                    MonthlyReportMetricCard(label="高价值确认率", value=DashboardService._format_percent(high_value_confirmed, high_value_total), helper="高价值已确认 / 高价值草稿", href="/outreach-campaigns", tone="warning"),
                ],
            ),
            queue_performance=MonthlyReportCardSection(
                title="发送队列表现",
                cards=[
                    MonthlyReportMetricCard(label="本月入队", value=str(queued), helper="本月进入发送队列", href="/outreach-send-queue?status=queued", tone="primary"),
                    MonthlyReportMetricCard(label="本月发送", value=str(sent), helper=f"失败 {failed} 封", href="/outreach-records?view=sent", tone="primary"),
                    MonthlyReportMetricCard(label="发送成功率", value=DashboardService._format_percent(sent, sent + failed), helper="发送成功 / 已处理队列", href="/outreach-records?view=sent", tone="success"),
                    MonthlyReportMetricCard(label="发送失败数", value=str(failed), helper="需要处理", href="/outreach-send-queue?status=failed", tone="danger"),
                    MonthlyReportMetricCard(label="今日剩余额度", value=str(quota_remaining), helper="默认按每日 200 封估算", href="/outreach-send-queue", tone="neutral"),
                    MonthlyReportMetricCard(label="平均发送间隔", value="按队列节流", helper="由发送队列规则控制", href="/outreach-send-queue", tone="neutral"),
                ],
            ),
            skip_reasons=MonthlyReportSkipReasonSection(
                title="跳过原因分析",
                items=[
                    MonthlyReportSkipReason(label="缺邮箱", value=skip_counts["缺邮箱"], helper="补充联系方式", href="/influencers?missing_contact=true", tone="primary"),
                    MonthlyReportSkipReason(label="无效邮箱", value=skip_counts["无效邮箱"], helper="修正或移除", href="/influencers", tone="danger"),
                    MonthlyReportSkipReason(label="黑名单", value=skip_counts["黑名单"], helper="不可发送", href="/influencers", tone="danger"),
                    MonthlyReportSkipReason(label="已发送", value=skip_counts["已发送"], helper="避免重复", href="/outreach-records?view=sent", tone="neutral"),
                    MonthlyReportSkipReason(label="已回复", value=skip_counts["已回复"], helper="转跟进", href="/email-replies", tone="success"),
                    MonthlyReportSkipReason(label="高价值未确认", value=skip_counts["高价值未确认"], helper="先打开草稿确认", href="/outreach-campaigns", tone="warning"),
                    MonthlyReportSkipReason(label="草稿未批准", value=skip_counts["草稿未批准"], helper="审核后才能入队", href="/outreach-campaigns", tone="primary"),
                ],
            ),
            reply_progress=MonthlyReportCardSection(
                title="回复与合作进展",
                cards=[
                    MonthlyReportMetricCard(label="已回复", value=str(replied), helper="本月新增", href="/email-replies", tone="success"),
                    MonthlyReportMetricCard(label="感兴趣", value=str(interested), helper="优先跟进", href="/email-replies?intent_status=interested", tone="success"),
                    MonthlyReportMetricCard(label="待报价", value="0", helper="可在回复中心标记", href="/email-replies", tone="primary"),
                    MonthlyReportMetricCard(label="待寄样", value="0", helper="可在回复中心标记", href="/email-replies", tone="primary"),
                    MonthlyReportMetricCard(label="UGC 合作", value="0", helper="合作类型待补充", href="/email-replies", tone="neutral"),
                    MonthlyReportMetricCard(label="付费合作", value="0", helper="合作类型待补充", href="/email-replies", tone="warning"),
                    MonthlyReportMetricCard(label="联盟佣金合作", value="0", helper="合作类型待补充", href="/email-replies", tone="primary"),
                ],
            ),
            todos=[
                MonthlyReportTodo(title=f"{high_value_pending} 个高价值草稿未确认", description="打开草稿详情逐条确认，批准后才能入队。", href="/outreach-campaigns", action_label="去确认", tone="warning"),
                MonthlyReportTodo(title=f"{failed} 封发送失败需要处理", description="查看失败原因，修正邮箱或重新入队。", href="/outreach-send-queue?status=failed", action_label="处理失败", tone="danger"),
                MonthlyReportTodo(title=f"{replied} 位已回复红人待跟进", description="按意向状态分派后续动作。", href="/email-replies", action_label="跟进回复", tone="success"),
                MonthlyReportTodo(title=f"{skip_counts['缺邮箱']} 位缺邮箱红人需要补充联系方式", description="补齐联系方式后再参与外联。", href="/influencers?missing_contact=true", action_label="补联系方式", tone="primary"),
            ],
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
