from pydantic import BaseModel, EmailStr, Field

from app.models.enums import EmailLogStatus
from app.schemas.email_log import EmailLogRead


class SmtpStatus(BaseModel):
    configured: bool
    host: str | None = None
    port: int | None = None
    user_address: str | None = None
    from_address: str | None = None
    from_user_mismatch: bool = False
    warning: str | None = None
    use_tls: bool = True
    message: str
    test_recipient: str | None = None
    test_schedule_enabled: bool = False
    test_interval_minutes: int | None = None


class MailchimpStatus(BaseModel):
    configured: bool
    server_prefix: str | None = None
    list_id: str | None = None
    message: str


class KlaviyoStatus(BaseModel):
    configured: bool
    list_id: str | None = None
    message: str


class EmailTestRequest(BaseModel):
    recipient: EmailStr = Field(
        description="测试收件人（必填）。仅用于验证 SMTP 配置，不是红人外联邮件。",
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
