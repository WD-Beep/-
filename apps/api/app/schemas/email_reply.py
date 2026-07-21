# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：email reply
"""Inbound email reply schemas."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel
from app.services.email_reply_utils import html_to_text, make_snippet


class InboundEmailPayload(BaseModel):
    """Normalized inbound message from IMAP or webhook."""

    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    from_address: str
    to_address: str
    subject: str = ""
    body: str = ""
    raw_headers: dict[str, str] | None = None
    received_at: datetime | None = None
    product_id: int | None = Field(
        default=None,
        description="Optional product scope hint; match still validates product isolation.",
    )


class InboundEmailWebhookRequest(BaseModel):
    message_id: str | None = None
    in_reply_to: str | None = None
    references: str | list[str] | None = None
    from_address: str | None = Field(default=None, alias="from")
    from_email: str | None = None
    to_address: str | list[str] | None = Field(default=None, alias="to")
    to_email: str | None = None
    subject: str = ""
    body: str | None = None
    text: str | None = None
    html: str | None = None
    headers: dict[str, str] | None = None
    received_at: datetime | None = None
    product_id: int | None = None

    model_config = {"populate_by_name": True}


class EmailReplyRead(ORMModel):
    id: int
    product_id: int
    email_log_id: int | None
    product_influencer_id: int | None
    campaign_id: int | None
    message_id: str | None
    in_reply_to: str | None
    match_method: str | None
    processing_status: str = "unprocessed"
    intent_status: str = "unprocessed"
    source: str
    from_address: str
    to_address: str
    subject: str
    body: str | None
    snippet: str | None
    raw_headers: dict | None = None
    received_at: datetime
    viewed_at: datetime | None = None
    handled_at: datetime | None = None
    manual_note: str | None = None

    @field_validator("body", mode="before")
    @classmethod
    def clean_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return html_to_text(value)

    @field_validator("snippet", mode="before")
    @classmethod
    def clean_snippet(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return make_snippet(value)


class EmailReplyUpdateRequest(BaseModel):
    product_influencer_id: int | None = None
    campaign_id: int | None = None
    intent_status: str | None = Field(
        default=None,
        pattern="^(unprocessed|interested|follow_up|not_interested|processed|unmatched)$",
    )
    processing_status: str | None = Field(default=None, pattern="^(unprocessed|processed)$")
    manual_note: str | None = Field(default=None, max_length=2000)
    mark_viewed: bool | None = None


class EmailReplySendResponseRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    subject: str | None = Field(default=None, max_length=500)
    use_ai_draft: bool = False
    mark_processed: bool = True


class EmailReplySendResponseResult(BaseModel):
    sent: bool
    message_id: str | None = None
    reply_id: int
    product_influencer_id: int | None = None
    campaign_id: int | None = None
    sent_at: datetime | None = None
    delivery_provider: str | None = None
    warning: str | None = None
    error: str | None = None


class EmailReplyBulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class EmailReplyBulkDeleteResponse(BaseModel):
    deleted_count: int
    deleted_ids: list[int]
    missing_ids: list[int]


class EmailReplyCountSummary(BaseModel):
    unprocessed_count: int
    unmatched_count: int
    unviewed_count: int = 0


class EmailReplyIngestResult(BaseModel):
    status: str
    reply_id: int | None = None
    product_id: int | None = None
    product_influencer_id: int | None = None
    email_log_id: int | None = None
    campaign_id: int | None = None
    match_method: str | None = None
    match_confidence: str | None = None
    follow_status: str | None = None
    message: str


class EmailReplyIngestBatchResponse(BaseModel):
    processed: int
    ingested: int
    skipped: int
    failed: int
    results: list[EmailReplyIngestResult]


class InboundEmailStatus(BaseModel):
    configured: bool
    imap_configured: bool
    webhook_configured: bool
    inbound_address: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_folder: str | None = None
    imap_poll_enabled: bool = False
    message: str


class EmailReplySummary(BaseModel):
    reply_count: int
    latest_reply_at: datetime | None = None
    latest_snippet: str | None = None
