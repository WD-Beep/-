"""011: 扩容 collection_tasks.status 以支持 completed_with_results 等状态值"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_expand_collection_task_status"
down_revision: Union[str, None] = "010_collection_funnel_candidates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic 默认 version_num 为 VARCHAR(32)，本 revision id 超过 32 需先扩容
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")

    op.alter_column(
        "collection_tasks",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "collection_tasks",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
