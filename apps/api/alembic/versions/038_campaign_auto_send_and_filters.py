"""038: outreach campaign auto send + filter snapshot"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "038_campaign_auto_send_and_filters"
down_revision: Union[str, None] = "037_outreach_email_campaigns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outreach_email_campaigns",
        sa.Column("auto_send_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "outreach_email_campaigns",
        sa.Column("auto_send_time", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "outreach_email_campaigns",
        sa.Column(
            "auto_send_timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Shanghai",
        ),
    )
    op.add_column(
        "outreach_email_campaigns",
        sa.Column("last_auto_processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outreach_email_campaigns",
        sa.Column("next_auto_process_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outreach_email_campaigns",
        sa.Column("influencer_filters_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_email_campaigns", "influencer_filters_snapshot")
    op.drop_column("outreach_email_campaigns", "next_auto_process_at")
    op.drop_column("outreach_email_campaigns", "last_auto_processed_at")
    op.drop_column("outreach_email_campaigns", "auto_send_timezone")
    op.drop_column("outreach_email_campaigns", "auto_send_time")
    op.drop_column("outreach_email_campaigns", "auto_send_enabled")
