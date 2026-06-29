from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.schemas.common import ORMModel


DEFAULT_SCRIPT_TYPES = [
    "email_subjects",
    "email_first_touch",
    "instagram_dm",
    "follow_up_1",
    "follow_up_2",
]


class LinkKnowledgeBaseCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    url: HttpUrl
    product_id: int | None = None
    tags: list[str] | None = None
    parse_immediately: bool = True


class LinkKnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    extracted_knowledge: dict[str, Any] | None = None
    tags: list[str] | None = None
    is_active: bool | None = None


class LinkKnowledgeChunkRead(ORMModel):
    id: int
    link_knowledge_base_id: int
    workspace_id: int
    chunk_index: int
    chunk_type: str
    title: str | None
    content: str
    metadata: dict[str, Any] | None = Field(default=None, alias="chunk_metadata")
    created_at: datetime
    updated_at: datetime


class LinkKnowledgeBaseRead(ORMModel):
    id: int
    workspace_id: int
    user_id: int | None
    product_id: int | None
    name: str
    url: str
    domain: str | None
    source_type: str
    status: str
    fetch_status: str | None
    parse_status: str | None
    summary: str | None
    extracted_knowledge: dict[str, Any] | None
    tags: list[str] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_fetched_at: datetime | None
    error_message: str | None
    chunks: list[LinkKnowledgeChunkRead] = Field(default_factory=list)


class LinkScriptGenerateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    influencer_ids: list[int] = Field(min_length=1)
    language: str = "en"
    tone: str = "friendly"
    collaboration_type: str = "gifted_collab"
    script_types: list[str] = Field(default_factory=lambda: list(DEFAULT_SCRIPT_TYPES))
    extra_instruction: str | None = None


class LinkScriptJobRead(ORMModel):
    id: int
    workspace_id: int
    link_knowledge_base_id: int
    product_id: int | None
    name: str
    status: str
    total_count: int
    success_count: int
    failed_count: int
    language: str
    tone: str
    collaboration_type: str
    script_types: list[str] | None
    ai_model: str | None
    extra_instruction: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    error_message: str | None


class LinkScriptResultRead(ORMModel):
    id: int
    workspace_id: int
    job_id: int
    link_knowledge_base_id: int
    influencer_id: int
    platform: str | None
    profile_url: str | None
    influencer_name: str | None
    influencer_handle: str | None
    status: str
    input_snapshot: dict[str, Any] | None
    generated_content: dict[str, Any] | None
    edited_content: dict[str, Any] | None
    used_content: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    error_message: str | None


class LinkScriptResultUpdate(BaseModel):
    edited_content: dict[str, Any] | None = None
    used_content: dict[str, Any] | None = None


class LinkScriptRegenerateRequest(BaseModel):
    tone: str | None = None
    language: str | None = None
    collaboration_type: str | None = None
    extra_instruction: str | None = None
