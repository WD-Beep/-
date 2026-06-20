"""Add AI outreach fields to email_logs."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034_email_log_ai_outreach"
down_revision: Union[str, None] = "033_email_log_influencer_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("email_logs", sa.Column("body", sa.Text(), nullable=True))
    op.add_column(
        "email_logs",
        sa.Column("generated_by_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("email_logs", sa.Column("ai_provider", sa.String(length=50), nullable=True))
    op.add_column("email_logs", sa.Column("ai_reason", sa.Text(), nullable=True))
    op.add_column(
        "email_logs",
        sa.Column("matched_knowledge", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "email_logs",
        sa.Column("risk_notes", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_logs", "risk_notes")
    op.drop_column("email_logs", "matched_knowledge")
    op.drop_column("email_logs", "ai_reason")
    op.drop_column("email_logs", "ai_provider")
    op.drop_column("email_logs", "generated_by_ai")
    op.drop_column("email_logs", "body")
