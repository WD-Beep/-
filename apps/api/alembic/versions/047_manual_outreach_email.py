"""Add manual outreach email queue."""

from alembic import op
import sqlalchemy as sa


revision = "047_manual_outreach_email"
down_revision = "046_outreach_draft_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_outreach_emails",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("sender_email", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="scheduled", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("email_log_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["email_log_id"], ["email_logs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manual_outreach_emails_product_id", "manual_outreach_emails", ["product_id"])
    op.create_index("ix_manual_outreach_emails_user_id", "manual_outreach_emails", ["user_id"])
    op.create_index("ix_manual_outreach_emails_recipient", "manual_outreach_emails", ["recipient"])
    op.create_index("ix_manual_outreach_emails_status", "manual_outreach_emails", ["status"])
    op.create_index("ix_manual_outreach_emails_scheduled_at", "manual_outreach_emails", ["scheduled_at"])
    op.create_index("ix_manual_outreach_emails_sent_at", "manual_outreach_emails", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_manual_outreach_emails_sent_at", table_name="manual_outreach_emails")
    op.drop_index("ix_manual_outreach_emails_scheduled_at", table_name="manual_outreach_emails")
    op.drop_index("ix_manual_outreach_emails_status", table_name="manual_outreach_emails")
    op.drop_index("ix_manual_outreach_emails_recipient", table_name="manual_outreach_emails")
    op.drop_index("ix_manual_outreach_emails_user_id", table_name="manual_outreach_emails")
    op.drop_index("ix_manual_outreach_emails_product_id", table_name="manual_outreach_emails")
    op.drop_table("manual_outreach_emails")
