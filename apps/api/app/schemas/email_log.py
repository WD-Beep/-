from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import EmailLogStatus
from app.schemas.common import ORMModel
from app.schemas.knowledge import MatchedKnowledgeItem
from app.schemas.message_template import MessageTemplateRead


class EmailLogRead(ORMModel):
    id: int
    task_id: int | None
    product_influencer_id: int | None = None
    sender_email: str | None = None
    influencer_username: str | None = None
    recipients: list[EmailStr]
    subject: str
    body: str | None = None
    status: EmailLogStatus
    attachment_path: str | None
    error_message: str | None
    generated_by_ai: bool = False
    ai_provider: str | None = None
    ai_reason: str | None = None
    matched_knowledge: list[MatchedKnowledgeItem] | None = None
    risk_notes: list[str] | None = None
    sent_at: datetime | None


class EmailLogFilter(BaseModel):
    product_id: int | None = None
    task_id: int | None = None
    status: EmailLogStatus | None = None


class SaveEmailLogAsTemplateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    scenario: str = Field(default="first_contact", max_length=64)
    platform: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default="en", max_length=16)
    tags: list[str] = Field(default_factory=lambda: ["ai_outreach", "saved_from_email"])
    content: str | None = None
    note: str | None = None
    save_as_copy: bool = False


class SaveEmailLogAsTemplateResponse(BaseModel):
    created: bool
    duplicate: bool = False
    message: str
    template: MessageTemplateRead | None = None
