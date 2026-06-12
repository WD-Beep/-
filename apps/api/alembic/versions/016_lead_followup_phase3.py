"""016: 线索跟进字段与跟进记录表"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_lead_followup_phase3"
down_revision: Union[str, None] = "015_candidate_pool_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "influencers",
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("invalid_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("blacklist_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_influencers_next_follow_up_at", "influencers", ["next_follow_up_at"])
    op.create_index("ix_influencers_follow_status", "influencers", ["follow_status"])

    op.create_table(
        "influencer_followups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("influencer_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("old_status", sa.String(length=50), nullable=True),
        sa.Column("new_status", sa.String(length=50), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("operator_name", sa.String(length=100), nullable=True),
        sa.Column("contact_channel", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["influencer_id"],
            ["influencers.id"],
            name="fk_influencer_followups_influencer_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_influencer_followups_influencer_id",
        "influencer_followups",
        ["influencer_id"],
    )
    op.create_index(
        "ix_influencer_followups_created_at",
        "influencer_followups",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_influencer_followups_created_at", table_name="influencer_followups")
    op.drop_index("ix_influencer_followups_influencer_id", table_name="influencer_followups")
    op.drop_table("influencer_followups")
    op.drop_index("ix_influencers_follow_status", table_name="influencers")
    op.drop_index("ix_influencers_next_follow_up_at", table_name="influencers")
    op.drop_column("influencers", "blacklist_reason")
    op.drop_column("influencers", "invalid_reason")
    op.drop_column("influencers", "last_reply_at")
    op.drop_column("influencers", "last_contacted_at")
    op.drop_column("influencers", "next_follow_up_at")
