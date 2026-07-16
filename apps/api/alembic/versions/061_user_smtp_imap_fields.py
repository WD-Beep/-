from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "061_user_smtp_imap_fields"
down_revision: Union[str, None] = "060_user_smtp_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_smtp_accounts", sa.Column("imap_host", sa.String(length=255), nullable=True))
    op.add_column("user_smtp_accounts", sa.Column("imap_port", sa.Integer(), nullable=True))
    op.add_column("user_smtp_accounts", sa.Column("imap_user", sa.String(length=320), nullable=True))
    op.add_column("user_smtp_accounts", sa.Column("imap_password", sa.Text(), nullable=True))
    op.add_column(
        "user_smtp_accounts",
        sa.Column("imap_use_ssl", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("user_smtp_accounts", "imap_use_ssl")
    op.drop_column("user_smtp_accounts", "imap_password")
    op.drop_column("user_smtp_accounts", "imap_user")
    op.drop_column("user_smtp_accounts", "imap_port")
    op.drop_column("user_smtp_accounts", "imap_host")
