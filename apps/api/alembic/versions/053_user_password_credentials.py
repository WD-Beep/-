"""Add password credentials for managed accounts."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "053_user_password_credentials"
down_revision: Union[str, None] = "052_collection_task_batch_rounds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
