from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
    total_pages: int | None = None

    @model_validator(mode="after")
    def fill_total_pages(self) -> "PaginatedResponse[T]":
        if self.total_pages is None:
            self.total_pages = self.pages
        return self


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: datetime
