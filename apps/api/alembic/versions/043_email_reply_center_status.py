"""043: email reply center workflow fields"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "043_email_reply_center_status"
down_revision: Union[str, None] = "042_follow_up_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_replies",
        sa.Column(
            "processing_status",
            sa.String(length=32),
            nullable=False,
            server_default="unprocessed",
        ),
    )
    op.add_column(
        "email_replies",
        sa.Column(
            "intent_status",
            sa.String(length=32),
            nullable=False,
            server_default="unprocessed",
        ),
    )
    op.add_column("email_replies", sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("email_replies", sa.Column("manual_note", sa.Text(), nullable=True))
    op.create_index("ix_email_replies_processing_status", "email_replies", ["processing_status"], unique=False)
    op.create_index("ix_email_replies_intent_status", "email_replies", ["intent_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_email_replies_intent_status", table_name="email_replies")
    op.drop_index("ix_email_replies_processing_status", table_name="email_replies")
    op.drop_column("email_replies", "manual_note")
    op.drop_column("email_replies", "handled_at")
    op.drop_column("email_replies", "intent_status")
    op.drop_column("email_replies", "processing_status")
