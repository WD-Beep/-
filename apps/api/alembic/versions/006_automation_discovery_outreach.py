"""Add discovery filtering and outreach settings."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_auto_discovery_outreach"
down_revision: Union[str, None] = "005_link_import_batches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collection_tasks", sa.Column("discovery_limit", sa.Integer(), nullable=True))
    op.add_column("collection_tasks", sa.Column("min_engagement_rate", sa.Float(), nullable=True))
    op.add_column(
        "collection_tasks",
        sa.Column("outreach_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("outreach_provider", sa.String(length=50), nullable=False, server_default="smtp"),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("outreach_dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("outreach_templates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("collection_tasks", "outreach_templates")
    op.drop_column("collection_tasks", "outreach_dry_run")
    op.drop_column("collection_tasks", "outreach_provider")
    op.drop_column("collection_tasks", "outreach_enabled")
    op.drop_column("collection_tasks", "min_engagement_rate")
    op.drop_column("collection_tasks", "discovery_limit")
