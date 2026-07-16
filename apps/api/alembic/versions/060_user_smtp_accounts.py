from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "060_user_smtp_accounts"
down_revision: Union[str, None] = "059_collection_task_lease_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_smtp_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="gmail", nullable=False),
        sa.Column("smtp_host", sa.String(length=255), server_default="smtp.gmail.com", nullable=False),
        sa.Column("smtp_port", sa.Integer(), server_default="587", nullable=False),
        sa.Column("smtp_user", sa.String(length=320), nullable=False),
        sa.Column("smtp_password", sa.Text(), nullable=False),
        sa.Column("smtp_from", sa.String(length=320), nullable=False),
        sa.Column("smtp_from_name", sa.String(length=255), nullable=True),
        sa.Column("use_tls", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_smtp_account_user_id"),
    )
    op.create_index("ix_user_smtp_accounts_user_id", "user_smtp_accounts", ["user_id"], unique=False)
    op.create_index("ix_user_smtp_accounts_enabled", "user_smtp_accounts", ["enabled"], unique=False)
    op.add_column("email_logs", sa.Column("sender_user_id", sa.Integer(), nullable=True))
    op.add_column("email_logs", sa.Column("smtp_account_id", sa.Integer(), nullable=True))
    op.add_column("email_logs", sa.Column("sender_source", sa.String(length=32), nullable=True))
    op.add_column("email_logs", sa.Column("follow_up_index", sa.Integer(), nullable=True))
    op.create_index("ix_email_logs_sender_user_id", "email_logs", ["sender_user_id"], unique=False)
    op.create_index("ix_email_logs_smtp_account_id", "email_logs", ["smtp_account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_email_logs_smtp_account_id", table_name="email_logs")
    op.drop_index("ix_email_logs_sender_user_id", table_name="email_logs")
    op.drop_column("email_logs", "follow_up_index")
    op.drop_column("email_logs", "sender_source")
    op.drop_column("email_logs", "smtp_account_id")
    op.drop_column("email_logs", "sender_user_id")
    op.drop_index("ix_user_smtp_accounts_enabled", table_name="user_smtp_accounts")
    op.drop_index("ix_user_smtp_accounts_user_id", table_name="user_smtp_accounts")
    op.drop_table("user_smtp_accounts")
