"""012: 评论区发现来源字段"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_comment_discovery_source"
down_revision: Union[str, None] = "011_expand_collection_task_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("influencers", sa.Column("source_discovery_type", sa.String(length=32), nullable=True))
    op.add_column("influencers", sa.Column("source_post_url", sa.String(length=512), nullable=True))
    op.add_column("influencers", sa.Column("source_comment_url", sa.String(length=512), nullable=True))
    op.add_column("influencers", sa.Column("source_comment_text", sa.Text(), nullable=True))

    op.add_column(
        "collection_task_candidates",
        sa.Column("source_comment_url", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "collection_task_candidates",
        sa.Column("source_comment_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "collection_task_candidates",
        sa.Column("source_discovery_type", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    for table, cols in (
        (
            "collection_task_candidates",
            ("source_discovery_type", "source_comment_text", "source_comment_url"),
        ),
        (
            "influencers",
            ("source_comment_text", "source_comment_url", "source_post_url", "source_discovery_type"),
        ),
    ):
        for col in cols:
            op.drop_column(table, col)
