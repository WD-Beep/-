"""020: collection_tasks 结构化进度与 checkpoint。"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "020_collection_task_run_progress"
down_revision: Union[str, None] = "019_collection_task_platforms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("total_estimate", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("current_stage", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "collection_tasks",
        sa.Column(
            "run_checkpoint",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    for col in (
        "run_checkpoint",
        "last_error",
        "current_stage",
        "total_estimate",
        "skipped_count",
        "failed_count",
        "success_count",
        "processed_count",
    ):
        op.drop_column("collection_tasks", col)
