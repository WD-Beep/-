"""030: 采集任务软删除（归档）字段"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030_collection_task_archive"
down_revision: Union[str, None] = "029_product_influencer_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_collection_tasks_is_archived", "collection_tasks", ["is_archived"])


def downgrade() -> None:
    op.drop_index("ix_collection_tasks_is_archived", table_name="collection_tasks")
    op.drop_column("collection_tasks", "archived_at")
    op.drop_column("collection_tasks", "is_archived")
