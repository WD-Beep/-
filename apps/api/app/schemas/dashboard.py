# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：dashboard
from datetime import datetime

from pydantic import BaseModel

from app.schemas.collection_task import CollectionTaskRead


class PlatformCount(BaseModel):
    platform: str
    count: int


class DashboardSummary(BaseModel):
    total_influencers: int
    total_tasks: int
    active_tasks: int
    completed_tasks: int
    failed_tasks: int
    total_email_logs: int
    sent_emails: int
    failed_emails: int
    instagram_influencers: int = 0
    email_coverage_rate: float = 0.0
    contactable_count: int = 0
    high_match_count: int = 0
    average_score: float | None = None
    average_product_fit: float | None = None
    average_roi_forecast: float | None = None
    platforms: list[PlatformCount]
    recent_tasks: list[CollectionTaskRead]


class MonthlyReportMetricCard(BaseModel):
    label: str
    value: str
    helper: str
    href: str
    tone: str = "neutral"


class MonthlyReportFunnelStep(BaseModel):
    label: str
    value: int
    href: str


class MonthlyReportSkipReason(BaseModel):
    label: str
    value: int
    helper: str
    href: str
    tone: str = "neutral"


class MonthlyReportTodo(BaseModel):
    title: str
    description: str
    href: str
    action_label: str
    tone: str = "neutral"


class MonthlyReportCardSection(BaseModel):
    title: str
    cards: list[MonthlyReportMetricCard]


class MonthlyReportFunnelSection(BaseModel):
    title: str
    funnel: list[MonthlyReportFunnelStep]


class MonthlyReportSkipReasonSection(BaseModel):
    title: str
    items: list[MonthlyReportSkipReason]


class DashboardMonthlyReport(BaseModel):
    month: str
    updated_at: datetime
    review_notice: str
    overview: MonthlyReportCardSection
    outreach_recap: MonthlyReportFunnelSection
    draft_quality: MonthlyReportCardSection
    queue_performance: MonthlyReportCardSection
    skip_reasons: MonthlyReportSkipReasonSection
    reply_progress: MonthlyReportCardSection
    todos: list[MonthlyReportTodo]
