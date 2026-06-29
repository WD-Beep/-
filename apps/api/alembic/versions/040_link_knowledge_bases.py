"""040: link knowledge bases and script generation results"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "040_link_knowledge_bases"
down_revision: Union[str, None] = "039_email_replies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "link_knowledge_bases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("fetch_status", sa.String(length=32), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("clean_text", sa.Text(), nullable=True),
        sa.Column("extracted_knowledge", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_link_knowledge_bases_workspace_id", "link_knowledge_bases", ["workspace_id"])
    op.create_index("ix_link_knowledge_bases_product_id", "link_knowledge_bases", ["product_id"])
    op.create_index("ix_link_knowledge_bases_domain", "link_knowledge_bases", ["domain"])
    op.create_index("ix_link_knowledge_bases_status", "link_knowledge_bases", ["status"])
    op.create_index("ix_link_knowledge_bases_updated_at", "link_knowledge_bases", ["updated_at"])

    op.create_table(
        "link_knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("link_knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_type", sa.String(length=64), nullable=False, server_default="raw_text"),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["link_knowledge_base_id"], ["link_knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_link_knowledge_chunks_link_knowledge_base_id", "link_knowledge_chunks", ["link_knowledge_base_id"])
    op.create_index("ix_link_knowledge_chunks_workspace_id", "link_knowledge_chunks", ["workspace_id"])

    op.create_table(
        "link_script_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("link_knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("language", sa.String(length=20), nullable=False, server_default="en"),
        sa.Column("tone", sa.String(length=50), nullable=False, server_default="friendly"),
        sa.Column("collaboration_type", sa.String(length=50), nullable=False, server_default="gifted_collab"),
        sa.Column("script_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ai_model", sa.String(length=100), nullable=True),
        sa.Column("extra_instruction", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["link_knowledge_base_id"], ["link_knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_link_script_jobs_workspace_id", "link_script_jobs", ["workspace_id"])
    op.create_index("ix_link_script_jobs_link_knowledge_base_id", "link_script_jobs", ["link_knowledge_base_id"])
    op.create_index("ix_link_script_jobs_status", "link_script_jobs", ["status"])

    op.create_table(
        "link_script_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("link_knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("influencer_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=True),
        sa.Column("profile_url", sa.String(length=1024), nullable=True),
        sa.Column("influencer_name", sa.String(length=255), nullable=True),
        sa.Column("influencer_handle", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generated_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("edited_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("used_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["influencer_id"], ["product_influencers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["link_script_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["link_knowledge_base_id"], ["link_knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_link_script_results_workspace_id", "link_script_results", ["workspace_id"])
    op.create_index("ix_link_script_results_job_id", "link_script_results", ["job_id"])
    op.create_index("ix_link_script_results_link_knowledge_base_id", "link_script_results", ["link_knowledge_base_id"])
    op.create_index("ix_link_script_results_influencer_id", "link_script_results", ["influencer_id"])
    op.create_index("ix_link_script_results_status", "link_script_results", ["status"])


def downgrade() -> None:
    op.drop_index("ix_link_script_results_status", table_name="link_script_results")
    op.drop_index("ix_link_script_results_influencer_id", table_name="link_script_results")
    op.drop_index("ix_link_script_results_link_knowledge_base_id", table_name="link_script_results")
    op.drop_index("ix_link_script_results_job_id", table_name="link_script_results")
    op.drop_index("ix_link_script_results_workspace_id", table_name="link_script_results")
    op.drop_table("link_script_results")

    op.drop_index("ix_link_script_jobs_status", table_name="link_script_jobs")
    op.drop_index("ix_link_script_jobs_link_knowledge_base_id", table_name="link_script_jobs")
    op.drop_index("ix_link_script_jobs_workspace_id", table_name="link_script_jobs")
    op.drop_table("link_script_jobs")

    op.drop_index("ix_link_knowledge_chunks_workspace_id", table_name="link_knowledge_chunks")
    op.drop_index("ix_link_knowledge_chunks_link_knowledge_base_id", table_name="link_knowledge_chunks")
    op.drop_table("link_knowledge_chunks")

    op.drop_index("ix_link_knowledge_bases_updated_at", table_name="link_knowledge_bases")
    op.drop_index("ix_link_knowledge_bases_status", table_name="link_knowledge_bases")
    op.drop_index("ix_link_knowledge_bases_domain", table_name="link_knowledge_bases")
    op.drop_index("ix_link_knowledge_bases_product_id", table_name="link_knowledge_bases")
    op.drop_index("ix_link_knowledge_bases_workspace_id", table_name="link_knowledge_bases")
    op.drop_table("link_knowledge_bases")
