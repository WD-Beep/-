"""Add outreach draft review fields."""

from alembic import op
import sqlalchemy as sa


revision = "046_outreach_draft_review"
down_revision = "045_email_reply_viewed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_campaign_recipients",
        sa.Column(
            "draft_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
    )
    op.add_column(
        "outreach_campaign_recipients",
        sa.Column("is_high_value", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "outreach_campaign_recipients",
        sa.Column("approval_block_reason", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "outreach_campaign_recipients",
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outreach_campaign_recipients",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outreach_campaign_recipients",
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outreach_campaign_recipients_draft_status",
        "outreach_campaign_recipients",
        ["draft_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_outreach_campaign_recipients_draft_status", table_name="outreach_campaign_recipients")
    op.drop_column("outreach_campaign_recipients", "skipped_at")
    op.drop_column("outreach_campaign_recipients", "approved_at")
    op.drop_column("outreach_campaign_recipients", "opened_at")
    op.drop_column("outreach_campaign_recipients", "approval_block_reason")
    op.drop_column("outreach_campaign_recipients", "is_high_value")
    op.drop_column("outreach_campaign_recipients", "draft_status")
