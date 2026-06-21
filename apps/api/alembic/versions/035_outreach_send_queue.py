"""035: outreach send queue for scheduled/manual batch send"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "035_outreach_send_queue"
down_revision: Union[str, None] = "034_email_log_ai_outreach"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outreach_send_queue",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "product_influencer_id",
            sa.Integer(),
            sa.ForeignKey("product_influencers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("sender_email", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generated_by_ai", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("matched_knowledge", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("email_log_id", sa.Integer(), sa.ForeignKey("email_logs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_outreach_send_queue_product_id", "outreach_send_queue", ["product_id"])
    op.create_index("ix_outreach_send_queue_user_id", "outreach_send_queue", ["user_id"])
    op.create_index("ix_outreach_send_queue_product_influencer_id", "outreach_send_queue", ["product_influencer_id"])
    op.create_index("ix_outreach_send_queue_status", "outreach_send_queue", ["status"])
    op.create_index("ix_outreach_send_queue_scheduled_at", "outreach_send_queue", ["scheduled_at"])


def downgrade() -> None:
    op.drop_index("ix_outreach_send_queue_scheduled_at", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_status", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_product_influencer_id", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_user_id", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_product_id", table_name="outreach_send_queue")
    op.drop_table("outreach_send_queue")
