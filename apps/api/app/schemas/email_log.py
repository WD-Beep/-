from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import EmailLogStatus
from app.schemas.common import ORMModel


class EmailLogRead(ORMModel):
    id: int
    task_id: int | None
    recipients: list[EmailStr]
    subject: str
    status: EmailLogStatus
    attachment_path: str | None
    error_message: str | None
    sent_at: datetime | None


class EmailLogFilter(BaseModel):
    product_id: int | None = None
    task_id: int | None = None
    status: EmailLogStatus | None = None
