from pydantic import BaseModel, EmailStr, Field

from app.models.enums import EmailLogStatus
from app.schemas.email_log import EmailLogRead


class SmtpStatus(BaseModel):
    configured: bool
    host: str | None = None
    port: int | None = None
    from_address: str | None = None
    use_tls: bool = True
    message: str


class MailchimpStatus(BaseModel):
    configured: bool
    server_prefix: str | None = None
    list_id: str | None = None
    message: str


class EmailTestRequest(BaseModel):
    recipient: EmailStr | None = Field(
        default=None,
        description="测试收件人，不传则使用 SMTP_FROM",
    )


class EmailTestResponse(BaseModel):
    success: bool
    message: str
    recipient: str | None = None


class EmailSendResult(BaseModel):
    success: bool
    message: str
    task_id: int
    total_count: int
    recipients: list[str]
    email_log: EmailLogRead | None = None
