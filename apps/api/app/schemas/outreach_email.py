from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.email_log import EmailLogRead
from app.schemas.knowledge import MatchedKnowledgeItem


class OutreachEmailGenerationResult(BaseModel):
    subject: str
    body: str
    recommended_script_id: str | None = None
    recommended_script_title: str = ""
    reason: str = ""
    matched_knowledge: list[MatchedKnowledgeItem] = Field(default_factory=list)
    tone: str = "professional"
    risk_notes: list[str] = Field(default_factory=list)
    provider: str = "heuristic"
    configured: bool = False
    error_message: str | None = None


class OutreachBatchPreviewRequest(BaseModel):
    influencer_ids: list[int] = Field(min_length=1, max_length=100)
    user_intent: str = "首次合作邀约"
    selected_script_ids: list[int] | None = None
    language: str | None = None
    tone: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class OutreachPreviewItem(BaseModel):
    influencer_id: int
    username: str
    display_name: str | None = None
    recipient: str | None = None
    subject: str = ""
    body: str = ""
    reason: str = ""
    matched_knowledge: list[MatchedKnowledgeItem] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    tone: str = "professional"
    can_send: bool = False
    generated_by_ai: bool = False
    provider: str = "heuristic"
    error_message: str | None = None


class OutreachBatchPreviewSummary(BaseModel):
    total: int
    generated: int
    missing_email: int
    failed: int


class OutreachBatchPreviewResponse(BaseModel):
    items: list[OutreachPreviewItem]
    summary: OutreachBatchPreviewSummary


class OutreachBatchSendRequest(BaseModel):
    influencer_ids: list[int] = Field(min_length=1, max_length=100)
    user_intent: str = "首次合作邀约"
    selected_script_ids: list[int] | None = None
    language: str | None = None
    tone: str | None = None
    dry_run: bool = True
    require_preview: bool = False


class OutreachSendItemResult(BaseModel):
    influencer_id: int
    username: str
    recipient: str | None = None
    subject: str = ""
    body: str = ""
    status: str
    email_log_id: int | None = None
    error_message: str | None = None
    generated_by_ai: bool = False


class OutreachBatchSendSummary(BaseModel):
    total: int
    generated: int
    sent: int
    pending: int
    failed: int
    skipped_missing_email: int


class OutreachBatchSendResponse(BaseModel):
    items: list[OutreachSendItemResult]
    summary: OutreachBatchSendSummary
    dry_run: bool


class SingleOutreachEmailPreviewResponse(BaseModel):
    subject: str
    body: str
    recipient: str
    sender_email: str
    sender_display: str = ""
    template_title: str = ""
    reason: str = ""
    matched_knowledge: list[MatchedKnowledgeItem] = Field(default_factory=list)


class SingleOutreachEmailSendRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)


class SingleOutreachEmailSendResponse(BaseModel):
    success: bool
    message: str
    email_log: EmailLogRead | None = None


class OutreachSendQueueEnqueueRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    matched_knowledge: list[MatchedKnowledgeItem] | None = None
    ai_reason: str | None = None
    template_title: str | None = None
    scheduled_at: datetime | None = None
    allow_resend: bool = False


class OutreachScheduleConfig(BaseModel):
    start_at: datetime
    timezone: str = "Asia/Singapore"
    send_window_start: str = "09:00"
    send_window_end: str = "18:00"
    interval_minutes: int = Field(default=5, ge=1, le=1440)
    daily_limit: int = Field(default=100, ge=1, le=10000)
    hourly_limit: int = Field(default=20, ge=1, le=10000)
    weekdays_only: bool = True


class OutreachScheduleItem(BaseModel):
    product_influencer_id: int
    recipient: str = Field(min_length=1, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    matched_knowledge: list[MatchedKnowledgeItem] | None = None
    ai_reason: str | None = None
    allow_resend: bool = False
    priority: int = 0
    dedupe_key: str | None = Field(default=None, max_length=255)
    max_retries: int = Field(default=3, ge=0, le=20)


class OutreachScheduleRequest(BaseModel):
    campaign_id: int | None = None
    items: list[OutreachScheduleItem] = Field(min_length=1, max_length=500)
    schedule_config: OutreachScheduleConfig


class OutreachScheduleResponse(BaseModel):
    created_count: int
    skipped_count: int
    first_scheduled_at: datetime | None = None
    last_scheduled_at: datetime | None = None


class OutreachQueueBulkActionRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class OutreachQueueRescheduleRequest(BaseModel):
    scheduled_at: datetime


class OutreachSendQueueRead(BaseModel):
    id: int
    product_id: int
    user_id: int | None
    product_influencer_id: int
    recipient: str
    sender_email: str | None
    subject: str
    body: str
    status: str
    scheduled_at: datetime | None
    sent_at: datetime | None
    failed_at: datetime | None = None
    next_retry_at: datetime | None = None
    retry_count: int = 0
    max_retries: int = 3
    priority: int = 0
    error_message: str | None
    dedupe_key: str | None = None
    locked_at: datetime | None = None
    generated_by_ai: bool
    matched_knowledge: list[MatchedKnowledgeItem] | None = None
    ai_reason: str | None = None
    allow_resend: bool = False
    campaign_id: int | None = None
    email_log_id: int | None = None
    smtp_account_id: int | None = None
    queue_type: str = "first_touch"
    follow_up_step: int | None = None
    parent_queue_id: int | None = None
    outreach_record_id: int | None = None
    should_skip_if_replied: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OutreachSendQueueProcessResponse(BaseModel):
    processed: int
    sent: int
    failed: int
    skipped: int
    daily_limit: int
    sent_today: int
    message: str


class OutreachSendQueueClearFailedResponse(BaseModel):
    deleted_count: int
    message: str
