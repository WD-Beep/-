"""032: 品牌知识库 knowledge_bases / knowledge_documents / knowledge_chunks"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "032_knowledge_base"
down_revision: Union[str, None] = "031_candidate_source_input_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_bases" in inspector.get_table_names():
        return

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_bases_product_id", "knowledge_bases", ["product_id"])
    op.create_index("ix_knowledge_bases_workspace_id", "knowledge_bases", ["workspace_id"])
    op.create_index("ix_knowledge_bases_updated_at", "knowledge_bases", ["updated_at"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("uploaded_file_path", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_documents_knowledge_base_id", "knowledge_documents", ["knowledge_base_id"])
    op.create_index("ix_knowledge_documents_product_id", "knowledge_documents", ["product_id"])
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
    op.create_index("ix_knowledge_documents_file_type", "knowledge_documents", ["file_type"])
    op.create_index("ix_knowledge_documents_updated_at", "knowledge_documents", ["updated_at"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_knowledge_base_id", "knowledge_chunks", ["knowledge_base_id"])
    op.create_index("ix_knowledge_chunks_product_id", "knowledge_chunks", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_product_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_knowledge_base_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

    op.drop_index("ix_knowledge_documents_updated_at", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_file_type", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_status", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_product_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_knowledge_base_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")

    op.drop_index("ix_knowledge_bases_updated_at", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_workspace_id", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_product_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
