"""Add collection task batch round relationships."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "052_collection_task_batch_rounds"
down_revision: Union[str, None] = "051_sales_brand_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collection_tasks", sa.Column("parent_task_id", sa.Integer(), nullable=True))
    op.add_column("collection_tasks", sa.Column("batch_group_id", sa.String(length=64), nullable=True))
    op.add_column("collection_tasks", sa.Column("batch_round_index", sa.Integer(), nullable=True))
    op.add_column("collection_tasks", sa.Column("batch_round_count", sa.Integer(), nullable=True))
    op.create_index("ix_collection_tasks_parent_task_id", "collection_tasks", ["parent_task_id"])
    op.create_index("ix_collection_tasks_batch_group_id", "collection_tasks", ["batch_group_id"])
    op.create_foreign_key(
        "fk_collection_tasks_parent_task_id",
        "collection_tasks",
        "collection_tasks",
        ["parent_task_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_collection_tasks_parent_task_id", "collection_tasks", type_="foreignkey")
    op.drop_index("ix_collection_tasks_batch_group_id", table_name="collection_tasks")
    op.drop_index("ix_collection_tasks_parent_task_id", table_name="collection_tasks")
    op.drop_column("collection_tasks", "batch_round_count")
    op.drop_column("collection_tasks", "batch_round_index")
    op.drop_column("collection_tasks", "batch_group_id")
    op.drop_column("collection_tasks", "parent_task_id")
