"""Add a configurable collection task runtime limit."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "054_collection_task_runtime_limit"
down_revision: Union[str, None] = "053_user_password_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column("max_runtime_minutes", sa.Integer(), nullable=True, server_default="60"),
    )


def downgrade() -> None:
    op.drop_column("collection_tasks", "max_runtime_minutes")
