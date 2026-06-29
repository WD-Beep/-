"""041: outreach send queue scheduler fields"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "041_outreach_send_queue_scheduler"
down_revision: Union[str, None] = "040_link_knowledge_bases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outreach_send_queue", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outreach_send_queue", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "outreach_send_queue",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outreach_send_queue",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "outreach_send_queue",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("outreach_send_queue", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.add_column("outreach_send_queue", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outreach_send_queue", sa.Column("smtp_account_id", sa.Integer(), nullable=True))

    op.create_index("ix_outreach_send_queue_failed_at", "outreach_send_queue", ["failed_at"])
    op.create_index("ix_outreach_send_queue_next_retry_at", "outreach_send_queue", ["next_retry_at"])
    op.create_index("ix_outreach_send_queue_priority", "outreach_send_queue", ["priority"])
    op.create_index("ix_outreach_send_queue_dedupe_key", "outreach_send_queue", ["dedupe_key"])
    op.create_index("ix_outreach_send_queue_locked_at", "outreach_send_queue", ["locked_at"])
    op.create_index("ix_outreach_send_queue_smtp_account_id", "outreach_send_queue", ["smtp_account_id"])
    op.create_index(
        "ix_outreach_send_queue_status_scheduled_at",
        "outreach_send_queue",
        ["status", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outreach_send_queue_status_scheduled_at", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_smtp_account_id", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_locked_at", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_dedupe_key", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_priority", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_next_retry_at", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_failed_at", table_name="outreach_send_queue")

    op.drop_column("outreach_send_queue", "smtp_account_id")
    op.drop_column("outreach_send_queue", "locked_at")
    op.drop_column("outreach_send_queue", "dedupe_key")
    op.drop_column("outreach_send_queue", "priority")
    op.drop_column("outreach_send_queue", "max_retries")
    op.drop_column("outreach_send_queue", "retry_count")
    op.drop_column("outreach_send_queue", "next_retry_at")
    op.drop_column("outreach_send_queue", "failed_at")
