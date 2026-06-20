from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    uploaded_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    knowledge_base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
