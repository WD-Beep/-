# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：manual outreach email
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


ManualOutreachSendMode = Literal["now", "scheduled"]


class ManualOutreachEmailRequest(BaseModel):
    recipients: list[EmailStr] = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    send_mode: ManualOutreachSendMode = "now"
    scheduled_at: datetime | None = None

    @field_validator("subject", "body")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("required")
        return stripped


class ManualOutreachEmailItemRead(BaseModel):
    id: int | None = None
    recipient: str
    status: str
    email_log_id: int | None = None
    error_message: str | None = None
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None

    model_config = {"from_attributes": True}


class ManualOutreachEmailResponse(BaseModel):
    status: str
    total: int
    sent_count: int = 0
    scheduled_count: int = 0
    failed_count: int = 0
    message: str
    items: list[ManualOutreachEmailItemRead]
