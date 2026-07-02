"""Add viewed_at to email replies."""

from alembic import op
import sqlalchemy as sa


revision = "045_email_reply_viewed_at"
down_revision = "044_seed_sales_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_replies", sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_email_replies_viewed_at", "email_replies", ["viewed_at"])


def downgrade() -> None:
    op.drop_index("ix_email_replies_viewed_at", table_name="email_replies")
    op.drop_column("email_replies", "viewed_at")
