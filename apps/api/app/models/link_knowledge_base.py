# 文件说明：后端数据库模型，定义业务数据表结构；当前文件：link knowledge base
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LinkKnowledgeBase(Base):
    __tablename__ = "link_knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    fetch_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parse_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_knowledge: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    manual_selling_points: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class LinkKnowledgeChunk(Base):
    __tablename__ = "link_knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link_knowledge_base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("link_knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_type: Mapped[str] = mapped_column(String(64), nullable=False, default="raw_text")
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LinkScriptJob(Base):
    __tablename__ = "link_script_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    link_knowledge_base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("link_knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    message_template_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("message_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="en")
    tone: Mapped[str] = mapped_column(String(50), nullable=False, default="friendly")
    collaboration_type: Mapped[str] = mapped_column(String(50), nullable=False, default="gifted_collab")
    script_types: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extra_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class LinkScriptResult(Base):
    __tablename__ = "link_script_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("link_script_jobs.id", ondelete="CASCADE"), index=True)
    link_knowledge_base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("link_knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    influencer_id: Mapped[int] = mapped_column(Integer, ForeignKey("product_influencers.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profile_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    influencer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    influencer_handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    edited_content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    used_content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
