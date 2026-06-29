from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.influencer import InfluencerFilter
from app.schemas.knowledge import MatchedKnowledgeItem


class OutreachCampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    influencer_ids: list[int] | None = Field(default=None, max_length=1000)
    influencer_filters: InfluencerFilter | None = None
    select_all_by_filters: bool = False
    knowledge_base_id: int | None = None
    message_template_id: int | None = None
    daily_limit: int = Field(default=50, ge=1, le=1000)
    send_window_start: str | None = None
    send_window_end: str | None = None
    timezone: str = "Asia/Shanghai"
    skip_sent: bool = True
    skip_replied: bool = True
    skip_blacklisted: bool = True
    skip_invalid: bool = True
    allow_resend: bool = False
    auto_send_enabled: bool = False
    auto_send_time: str | None = None
    auto_send_timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def validate_selection(self) -> "OutreachCampaignCreateRequest":
        if self.select_all_by_filters:
            if self.influencer_filters is None:
                raise ValueError("select_all_by_filters 需要提供 influencer_filters")
            if self.influencer_ids:
                raise ValueError("筛选全选模式下请勿同时提交 influencer_ids")
        elif not self.influencer_ids:
            raise ValueError("请提供 influencer_ids 或 select_all_by_filters")
        if self.auto_send_enabled and not self.auto_send_time:
            raise ValueError("启用自动发送时必须设置 auto_send_time")
        return self


class OutreachCampaignUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    daily_limit: int | None = Field(default=None, ge=1, le=1000)
    send_window_start: str | None = None
    send_window_end: str | None = None
    skip_sent: bool | None = None
    skip_replied: bool | None = None
    skip_blacklisted: bool | None = None
    skip_invalid: bool | None = None
    allow_resend: bool | None = None
    auto_send_enabled: bool | None = None
    auto_send_time: str | None = None
    auto_send_timezone: str | None = None


class OutreachCampaignRead(BaseModel):
    id: int
    product_id: int
    user_id: int
    name: str
    status: str
    knowledge_base_id: int | None
    message_template_id: int | None
    daily_limit: int
    send_window_start: str | None
    send_window_end: str | None
    timezone: str
    skip_sent: bool
    skip_replied: bool
    skip_blacklisted: bool
    skip_invalid: bool
    allow_resend: bool
    auto_send_enabled: bool
    auto_send_time: str | None
    auto_send_timezone: str
    total_count: int
    draft_count: int = 0
    can_queue_count: int = 0
    queued_count: int
    sent_count: int
    failed_count: int
    skipped_count: int
    reply_count: int = 0
    interested_count: int = 0
    unreplied_count: int = 0
    latest_reply_at: datetime | None = None
    previewed_at: datetime | None
    last_processed_at: datetime | None
    last_auto_processed_at: datetime | None
    next_auto_process_at: datetime | None
    influencer_filters_snapshot: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OutreachCampaignPreviewItem(BaseModel):
    influencer_id: int
    username: str
    display_name: str | None = None
    recipient: str | None = None
    subject: str = ""
    body: str = ""
    reason: str = ""
    matched_knowledge: list[MatchedKnowledgeItem] = Field(default_factory=list)
    template_title: str = ""
    can_queue: bool = False
    skip_reason: str | None = None


class OutreachCampaignPreviewResponse(BaseModel):
    campaign_id: int
    items: list[OutreachCampaignPreviewItem]
    total: int
    can_queue_count: int
    skip_count: int


class OutreachCampaignPreviewRequest(BaseModel):
    content_source: str = Field(default="ai", pattern="^(ai|manual|template)$")
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=20000)


class OutreachCampaignRecipientListResponse(BaseModel):
    campaign_id: int
    items: list[OutreachCampaignPreviewItem]
    total: int
    can_queue_count: int
    skip_count: int


class OutreachCampaignQueueRequest(BaseModel):
    confirm: bool = False
    influencer_ids: list[int] | None = None


class OutreachCampaignQueueResponse(BaseModel):
    queued: int
    skipped: int
    message: str


class OutreachCampaignProcessResponse(BaseModel):
    processed: int
    sent: int
    failed: int
    skipped: int
    daily_limit: int
    sent_today: int
    message: str


class OutreachCampaignGenerateAndSendResponse(BaseModel):
    campaign_id: int
    preview: OutreachCampaignPreviewResponse
    queued: int
    queue_skipped: int
    processed: int
    sent: int
    failed: int
    skipped: int
    daily_limit: int
    sent_today: int
    message: str


class OutreachCampaignReplyBoardItem(BaseModel):
    influencer_id: int
    username: str
    display_name: str | None = None
    platform: str | None = None
    recipient: str | None = None
    subject: str | None = None
    send_status: str
    reply_status: str
    reply_time: datetime | None = None
    reply_snippet: str | None = None
    reply_body: str | None = None
    match_method: str | None = None
    skip_reason: str | None = None


class OutreachCampaignReplyBoardResponse(BaseModel):
    campaign_id: int
    total: int
    reply_count: int
    interested_count: int
    unreplied_count: int
    latest_reply_at: datetime | None = None
    items: list[OutreachCampaignReplyBoardItem]


class OutreachWorkbenchStatusItem(BaseModel):
    status: str
    message: str


class OutreachWorkbenchResultItem(BaseModel):
    influencer_id: int
    username: str
    display_name: str | None = None
    recipient: str | None = None
    status: str
    subject: str | None = None
    body: str | None = None
    reason: str | None = None
    sent_at: datetime | None = None


class OutreachWorkbenchResultSection(BaseModel):
    campaign_id: int | None = None
    total: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    pending: int = 0
    items: list[OutreachWorkbenchResultItem] = Field(default_factory=list)


class OutreachOneClickWorkbenchResponse(BaseModel):
    ai_generation: OutreachWorkbenchStatusItem
    smtp: OutreachWorkbenchStatusItem
    available_recipient_count: int
    latest_campaign: OutreachCampaignRead | None = None
    latest_results: OutreachWorkbenchResultSection
    reply_followup: OutreachCampaignReplyBoardResponse


class AutoCampaignProcessLogItem(BaseModel):
    campaign_id: int
    processed: int
    sent: int
    failed: int
    skipped: int
    error_message: str | None = None
    run_at: datetime


class AutoCampaignProcessResult(BaseModel):
    checked: int
    processed: int
    items: list[AutoCampaignProcessLogItem]
