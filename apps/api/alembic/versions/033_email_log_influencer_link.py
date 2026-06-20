"""Add influencer linkage fields to email_logs."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "033_email_log_influencer_link"
down_revision: Union[str, None] = "032_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_logs",
        sa.Column("product_influencer_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "email_logs",
        sa.Column("sender_email", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "email_logs",
        sa.Column("influencer_username", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_email_logs_product_influencer_id",
        "email_logs",
        "product_influencers",
        ["product_influencer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_email_logs_product_influencer_id",
        "email_logs",
        ["product_influencer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_logs_product_influencer_id", table_name="email_logs")
    op.drop_constraint("fk_email_logs_product_influencer_id", "email_logs", type_="foreignkey")
    op.drop_column("email_logs", "influencer_username")
    op.drop_column("email_logs", "sender_email")
    op.drop_column("email_logs", "product_influencer_id")
