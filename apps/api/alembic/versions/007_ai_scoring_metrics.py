"""Add AI scoring metrics to influencers."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_ai_scoring_metrics"
down_revision: Union[str, None] = "006_auto_discovery_outreach"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("influencers", sa.Column("travel_fit_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("purchasing_power_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("sales_potential_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("audience_match_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("roi_forecast", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("influencers", "roi_forecast")
    op.drop_column("influencers", "audience_match_score")
    op.drop_column("influencers", "sales_potential_score")
    op.drop_column("influencers", "purchasing_power_score")
    op.drop_column("influencers", "travel_fit_score")
