from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class UserSmtpAccountRead(ORMModel):
    id: int
    user_id: int
    provider: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_from: str
    smtp_from_name: str | None = None
    use_tls: bool
    imap_host: str | None = None
    imap_port: int | None = None
    imap_user: str | None = None
    imap_use_ssl: bool = True
    enabled: bool
    verified_at: datetime | None = None
    last_tested_at: datetime | None = None
    last_error: str | None = None
    has_password: bool = True
    has_imap_password: bool = False


class UserSmtpAccountUpsertRequest(BaseModel):
    provider: str | None = Field(default="gmail", max_length=32)
    smtp_user: EmailStr
    smtp_password: str | None = Field(default=None, min_length=8, max_length=256)
    imap_password: str | None = Field(default=None, min_length=8, max_length=256)
    imap_same_as_smtp: bool = True
    smtp_from_name: str | None = Field(default=None, max_length=255)
    enabled: bool = True


class UserSmtpAccountStatus(BaseModel):
    configured: bool
    source: str
    sender_email: str | None = None
    account: UserSmtpAccountRead | None = None
