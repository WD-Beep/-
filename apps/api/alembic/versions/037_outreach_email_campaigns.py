"""037: outreach email campaigns + campaign recipients"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "037_outreach_email_campaigns"
down_revision: Union[str, None] = "036_outreach_queue_allow_resend"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outreach_email_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("knowledge_base_id", sa.Integer(), sa.ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_template_id", sa.Integer(), sa.ForeignKey("message_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("send_window_start", sa.String(length=8), nullable=True),
        sa.Column("send_window_end", sa.String(length=8), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("skip_sent", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("skip_replied", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("skip_blacklisted", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("skip_invalid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allow_resend", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_outreach_email_campaigns_product_id", "outreach_email_campaigns", ["product_id"])
    op.create_index("ix_outreach_email_campaigns_status", "outreach_email_campaigns", ["status"])

    op.create_table(
        "outreach_campaign_recipients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("outreach_email_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_influencer_id",
            sa.Integer(),
            sa.ForeignKey("product_influencers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("template_title", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("matched_knowledge", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("can_queue", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("previewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queue_item_id", sa.Integer(), sa.ForeignKey("outreach_send_queue.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_outreach_campaign_recipients_campaign_id", "outreach_campaign_recipients", ["campaign_id"])
    op.create_unique_constraint(
        "uq_outreach_campaign_recipients_campaign_pi",
        "outreach_campaign_recipients",
        ["campaign_id", "product_influencer_id"],
    )

    op.add_column(
        "outreach_send_queue",
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("outreach_email_campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_outreach_send_queue_campaign_id", "outreach_send_queue", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_outreach_send_queue_campaign_id", table_name="outreach_send_queue")
    op.drop_column("outreach_send_queue", "campaign_id")
    op.drop_table("outreach_campaign_recipients")
    op.drop_index("ix_outreach_email_campaigns_status", table_name="outreach_email_campaigns")
    op.drop_index("ix_outreach_email_campaigns_product_id", table_name="outreach_email_campaigns")
    op.drop_table("outreach_email_campaigns")
