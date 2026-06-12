"""015: 候选池第二阶段字段（来源、指标、入库关联、筛选计数）"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_candidate_pool_phase2"
down_revision: Union[str, None] = "014_funnel_stage_counts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_task_candidates",
        sa.Column("platform", sa.String(length=50), nullable=False, server_default="instagram"),
    )
    op.add_column(
        "collection_task_candidates",
        sa.Column("source_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "collection_task_candidates",
        sa.Column("source_keyword", sa.String(length=255), nullable=True),
    )
    op.add_column("collection_task_candidates", sa.Column("followers_count", sa.Integer(), nullable=True))
    op.add_column("collection_task_candidates", sa.Column("engagement_rate", sa.Float(), nullable=True))
    op.add_column(
        "collection_task_candidates",
        sa.Column("profile_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("collection_task_candidates", sa.Column("influencer_id", sa.Integer(), nullable=True))
    op.add_column(
        "collection_task_candidates",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_foreign_key(
        "fk_collection_task_candidates_influencer_id",
        "collection_task_candidates",
        "influencers",
        ["influencer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_collection_task_candidates_task_status",
        "collection_task_candidates",
        ["task_id", "status"],
    )
    op.create_index(
        "ix_collection_task_candidates_task_failure",
        "collection_task_candidates",
        ["task_id", "failure_reason"],
    )

    op.add_column(
        "collection_tasks",
        sa.Column("filtered_below_min_followers_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("filtered_excluded_keyword_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("collection_tasks", "filtered_excluded_keyword_count")
    op.drop_column("collection_tasks", "filtered_below_min_followers_count")
    op.drop_index("ix_collection_task_candidates_task_failure", table_name="collection_task_candidates")
    op.drop_index("ix_collection_task_candidates_task_status", table_name="collection_task_candidates")
    op.drop_constraint(
        "fk_collection_task_candidates_influencer_id",
        "collection_task_candidates",
        type_="foreignkey",
    )
    for col in (
        "updated_at",
        "influencer_id",
        "profile_fetched_at",
        "engagement_rate",
        "followers_count",
        "source_keyword",
        "source_type",
        "platform",
    ):
        op.drop_column("collection_task_candidates", col)
