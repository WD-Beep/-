from pydantic import BaseModel, Field

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
