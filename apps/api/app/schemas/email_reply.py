"""Inbound email reply schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


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
    received_at: datetime
    handled_at: datetime | None = None
    manual_note: str | None = None


class EmailReplyUpdateRequest(BaseModel):
    product_influencer_id: int | None = None
    campaign_id: int | None = None
    intent_status: str | None = Field(
        default=None,
        pattern="^(unprocessed|interested|follow_up|not_interested|processed|unmatched)$",
    )
    processing_status: str | None = Field(default=None, pattern="^(unprocessed|processed)$")
    manual_note: str | None = Field(default=None, max_length=2000)


class EmailReplyBulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class EmailReplyBulkDeleteResponse(BaseModel):
    deleted_count: int
    deleted_ids: list[int]
    missing_ids: list[int]


class EmailReplyCountSummary(BaseModel):
    unprocessed_count: int
    unmatched_count: int


class EmailReplyIngestResult(BaseModel):
    status: str
    reply_id: int | None = None
    product_id: int | None = None
    product_influencer_id: int | None = None
    email_log_id: int | None = None
    campaign_id: int | None = None
    match_method: str | None = None
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
