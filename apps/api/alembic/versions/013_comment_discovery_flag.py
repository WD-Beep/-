"""013: 评论区发现开关（默认开启）"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_comment_discovery_flag"
down_revision: Union[str, None] = "012_comment_discovery_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column("comment_discovery_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("collection_tasks", "comment_discovery_enabled")
