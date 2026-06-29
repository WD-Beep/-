"""039: inbound email replies + outbound message_id on email_logs"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "039_email_replies"
down_revision: Union[str, None] = "038_campaign_auto_send_and_filters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_logs",
        sa.Column("message_id", sa.String(length=512), nullable=True),
    )
    op.create_index("ix_email_logs_message_id", "email_logs", ["message_id"], unique=False)

    op.create_table(
        "email_replies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("email_log_id", sa.Integer(), nullable=True),
        sa.Column("product_influencer_id", sa.Integer(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("message_id", sa.String(length=512), nullable=True),
        sa.Column("in_reply_to", sa.String(length=512), nullable=True),
        sa.Column("match_method", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="webhook"),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("to_address", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("snippet", sa.String(length=500), nullable=True),
        sa.Column("raw_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["outreach_email_campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["email_log_id"], ["email_logs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_influencer_id"], ["product_influencers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_replies_product_id", "email_replies", ["product_id"], unique=False)
    op.create_index(
        "ix_email_replies_product_influencer_id",
        "email_replies",
        ["product_influencer_id"],
        unique=False,
    )
    op.create_index("ix_email_replies_campaign_id", "email_replies", ["campaign_id"], unique=False)
    op.create_index("ix_email_replies_email_log_id", "email_replies", ["email_log_id"], unique=False)
    op.create_index("ix_email_replies_received_at", "email_replies", ["received_at"], unique=False)
    op.create_index(
        "uq_email_replies_message_id",
        "email_replies",
        ["message_id"],
        unique=True,
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_email_replies_message_id", table_name="email_replies")
    op.drop_index("ix_email_replies_received_at", table_name="email_replies")
    op.drop_index("ix_email_replies_email_log_id", table_name="email_replies")
    op.drop_index("ix_email_replies_campaign_id", table_name="email_replies")
    op.drop_index("ix_email_replies_product_influencer_id", table_name="email_replies")
    op.drop_index("ix_email_replies_product_id", table_name="email_replies")
    op.drop_table("email_replies")
    op.drop_index("ix_email_logs_message_id", table_name="email_logs")
    op.drop_column("email_logs", "message_id")
