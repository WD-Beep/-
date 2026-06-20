from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class KnowledgeBaseRead(ORMModel):
    id: int
    workspace_id: int
    product_id: int
    name: str
    description: str | None
    document_count: int = 0
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class KnowledgeDocumentRead(ORMModel):
    id: int
    knowledge_base_id: int
    workspace_id: int
    product_id: int
    file_name: str
    file_type: str
    source_path: str | None
    uploaded_file_path: str | None
    status: str
    error_message: str | None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeChunkRead(ORMModel):
    id: int
    document_id: int
    knowledge_base_id: int
    product_id: int
    chunk_index: int
    title: str | None
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class KnowledgeDocumentImportRequest(BaseModel):
    file_path: str = Field(min_length=1, max_length=1024)
    knowledge_base_id: int | None = None


class KnowledgeImportPreset(BaseModel):
    id: str
    label: str
    file_path: str
    available: bool


class KnowledgeSearchResult(BaseModel):
    chunk_id: int
    document_id: int
    document_name: str
    title: str | None
    section: str | None
    content: str
    score: float
    metadata: dict = Field(default_factory=dict)


class MatchedKnowledgeItem(BaseModel):
    document: str
    section: str | None = None
    summary: str


class ScriptRecommendRequest(BaseModel):
    influencer_id: int
    user_intent: str = "首次联系"
    selected_script_ids: list[int] | None = None
    contact_status: str | None = None
    followup_status: str | None = None


class ScriptRecommendResponse(BaseModel):
    recommended_script_id: str | None
    recommended_script_title: str
    final_message: str
    reason: str
    matched_knowledge: list[MatchedKnowledgeItem]
    tone: str
    risk_notes: list[str]
    provider: str
    configured: bool
    error_message: str | None = None
