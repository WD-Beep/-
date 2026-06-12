"""Add Instagram quality scoring and priority fields."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_instagram_quality_pipeline"
down_revision: Union[str, None] = "008_collection_quality_filters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("influencers", sa.Column("engagement_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("content_match_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("contactability_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("commercial_signal_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("activity_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("risk_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("final_priority", sa.String(length=10), nullable=True))
    op.add_column("influencers", sa.Column("ai_outreach_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("influencers", "ai_outreach_message")
    op.drop_column("influencers", "final_priority")
    op.drop_column("influencers", "risk_score")
    op.drop_column("influencers", "activity_score")
    op.drop_column("influencers", "commercial_signal_score")
    op.drop_column("influencers", "contactability_score")
    op.drop_column("influencers", "content_match_score")
    op.drop_column("influencers", "engagement_score")
