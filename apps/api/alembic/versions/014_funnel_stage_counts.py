"""014: 漏斗阶段计数持久化（hashtag/post/comment_author）"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_funnel_stage_counts"
down_revision: Union[str, None] = "013_comment_discovery_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column("hashtag_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("post_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("comment_author_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("collection_tasks", "comment_author_count")
    op.drop_column("collection_tasks", "post_count")
    op.drop_column("collection_tasks", "hashtag_count")
