from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import LinkImportBatchStatus
from app.schemas.common import ORMModel, TimestampMixin


def _list_or_empty(value: Any) -> list:
    return value if isinstance(value, list) else []


class ValidUrlItem(BaseModel):
    url: str
    platform: str


class LinkImportBatchCreate(BaseModel):
    name: str = Field(..., max_length=255)
    raw_urls: str = Field(..., min_length=1)


class LinkImportBatchRead(ORMModel, TimestampMixin):
    id: int
    name: str
    raw_urls: str
    valid_urls: list[ValidUrlItem] = Field(default_factory=list)
    invalid_urls: list[str] = Field(default_factory=list)
    status: LinkImportBatchStatus
    total_count: int
    success_count: int
    failed_count: int
    new_count: int
    updated_count: int
    error_message: str | None = None
    completed_at: datetime | None = None

    @field_validator("valid_urls", mode="before")
    @classmethod
    def normalize_valid_urls(cls, value: Any) -> list:
        items = _list_or_empty(value)
        return items

    @field_validator("invalid_urls", mode="before")
    @classmethod
    def normalize_invalid_urls(cls, value: Any) -> list:
        return _list_or_empty(value)


class LinkImportRunResult(BaseModel):
    batch_id: int
    status: LinkImportBatchStatus
    total_count: int
    success_count: int
    failed_count: int
    new_count: int
    updated_count: int
    invalid_urls: list[str] = Field(default_factory=list)
