from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel


class MessageTemplateGenerationRules(BaseModel):
    tone: str | None = Field(default=None, max_length=50)
    language: str | None = Field(default=None, max_length=16)
    min_length: int | None = Field(default=None, ge=20, le=2000)
    max_length: int | None = Field(default=None, ge=20, le=4000)
    subject_format: str | None = Field(default=None, max_length=500)
    body_structure: str | None = Field(default=None, max_length=2000)
    required_content: list[str] = Field(default_factory=list, max_length=20)
    forbidden_content: list[str] = Field(default_factory=list, max_length=20)
    cta: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_length_range(self) -> "MessageTemplateGenerationRules":
        if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
            raise ValueError("最短长度不能大于最长长度")
        return self


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
    generation_rules: dict
    is_default: bool
    source_filename: str | None
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
    note: str | None = Field(default=None, max_length=500)
    generation_rules: MessageTemplateGenerationRules = Field(default_factory=MessageTemplateGenerationRules)
    is_default: bool = False
    source_filename: str | None = Field(default=None, max_length=255)


class MessageTemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    scenario: str | None = Field(default=None, min_length=1, max_length=64)
    platform: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default=None, max_length=16)
    tags: list[str] | None = None
    content: str | None = Field(default=None, min_length=1)
    note: str | None = Field(default=None, max_length=500)
    generation_rules: MessageTemplateGenerationRules | None = None
    is_default: bool | None = None
    source_filename: str | None = Field(default=None, max_length=255)


class MessageTemplateUploadRead(BaseModel):
    filename: str
    content: str


class MessageTemplateFilter(BaseModel):
    product_id: int
    search: str | None = None
    scenario: str | None = None
    platform: str | None = None
    language: str | None = None
    tag: str | None = None
