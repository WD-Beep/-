from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class MessageTemplateRead(ORMModel):
    id: int
    user_id: int
    workspace_id: int
    product_id: int
    title: str
    scenario: str
    platform: str | None
    language: str | None
    tags: list[str]
    content: str
    note: str | None
    usage_count: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_system_default: bool = False


class MessageTemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    scenario: str = Field(min_length=1, max_length=64)
    platform: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default=None, max_length=16)
    tags: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1)
    note: str | None = None


class MessageTemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    scenario: str | None = Field(default=None, min_length=1, max_length=64)
    platform: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default=None, max_length=16)
    tags: list[str] | None = None
    content: str | None = Field(default=None, min_length=1)
    note: str | None = None


class MessageTemplateFilter(BaseModel):
    product_id: int
    search: str | None = None
    scenario: str | None = None
    platform: str | None = None
    language: str | None = None
    tag: str | None = None
