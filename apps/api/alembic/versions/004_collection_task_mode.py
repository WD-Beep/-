"""Add collection_mode, input_urls and contact stats to collection_tasks."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_collection_task_mode"
down_revision: Union[str, None] = "003_influencer_extended_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column("collection_mode", sa.String(length=20), nullable=False, server_default="keyword"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("input_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("email_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("missing_contact_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE collection_tasks SET input_urls = '[]'::jsonb WHERE input_urls IS NULL")


def downgrade() -> None:
    op.drop_column("collection_tasks", "missing_contact_count")
    op.drop_column("collection_tasks", "email_count")
    op.drop_column("collection_tasks", "input_urls")
    op.drop_column("collection_tasks", "collection_mode")
