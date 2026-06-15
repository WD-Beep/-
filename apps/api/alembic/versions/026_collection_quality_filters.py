"""026: 采集任务高价值筛选与候选池质量字段"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026_collection_quality_filters"
down_revision: Union[str, None] = "025_message_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column("require_email", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("require_contact", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("strict_quality_filter", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("insert_qualified_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("export_qualified_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.add_column("collection_task_candidates", sa.Column("is_high_value", sa.Boolean(), nullable=True))
    op.add_column("collection_task_candidates", sa.Column("has_email", sa.Boolean(), nullable=True))
    op.add_column("collection_task_candidates", sa.Column("has_contact", sa.Boolean(), nullable=True))
    op.add_column(
        "collection_task_candidates",
        sa.Column("contact_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "collection_task_candidates",
        sa.Column("insert_blocked_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("collection_task_candidates", "insert_blocked_reason")
    op.drop_column("collection_task_candidates", "contact_status")
    op.drop_column("collection_task_candidates", "has_contact")
    op.drop_column("collection_task_candidates", "has_email")
    op.drop_column("collection_task_candidates", "is_high_value")
    op.drop_column("collection_tasks", "export_qualified_only")
    op.drop_column("collection_tasks", "insert_qualified_only")
    op.drop_column("collection_tasks", "strict_quality_filter")
    op.drop_column("collection_tasks", "require_contact")
    op.drop_column("collection_tasks", "require_email")
