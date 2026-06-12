"""010: 采集漏斗统计 + 候选账号表"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_collection_funnel_candidates"
down_revision: Union[str, None] = "009_instagram_quality_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collection_tasks", sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("collection_tasks", sa.Column("deduped_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("collection_tasks", sa.Column("profile_fetched_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("collection_tasks", sa.Column("profile_failed_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("collection_tasks", sa.Column("filtered_out_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("collection_tasks", sa.Column("inserted_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("collection_tasks", sa.Column("status_summary", sa.Text(), nullable=True))

    op.create_table(
        "collection_task_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("profile_url", sa.String(length=512), nullable=False),
        sa.Column("source_hashtag", sa.String(length=255), nullable=True),
        sa.Column("source_post_url", sa.String(length=512), nullable=True),
        sa.Column("source_caption", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_profile"),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["collection_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collection_task_candidates_task_id", "collection_task_candidates", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_collection_task_candidates_task_id", table_name="collection_task_candidates")
    op.drop_table("collection_task_candidates")
    for col in (
        "status_summary",
        "inserted_count",
        "filtered_out_count",
        "profile_failed_count",
        "profile_fetched_count",
        "deduped_count",
        "discovered_count",
    ):
        op.drop_column("collection_tasks", col)
