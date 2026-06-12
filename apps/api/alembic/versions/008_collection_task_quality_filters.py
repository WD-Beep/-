"""Add follower and keyword quality filters to collection tasks."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008_collection_quality_filters"
down_revision: Union[str, None] = "007_ai_scoring_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collection_tasks", sa.Column("min_followers_count", sa.Integer(), nullable=True))
    op.add_column("collection_tasks", sa.Column("max_followers_count", sa.Integer(), nullable=True))
    op.add_column(
        "collection_tasks",
        sa.Column(
            "filter_include_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "collection_tasks",
        sa.Column(
            "filter_exclude_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("collection_tasks", "filter_exclude_keywords")
    op.drop_column("collection_tasks", "filter_include_keywords")
    op.drop_column("collection_tasks", "max_followers_count")
    op.drop_column("collection_tasks", "min_followers_count")
