from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import EmailLogStatus
from app.schemas.common import ORMModel
from app.schemas.knowledge import MatchedKnowledgeItem


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
