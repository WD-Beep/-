"""017: 联系方式深挖字段"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_contact_discovery_phase4"
down_revision: Union[str, None] = "016_lead_followup_phase3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "influencers",
        sa.Column("contact_discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("contact_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("contact_fetch_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("contact_fetch_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("contact_credibility_level", sa.String(length=20), nullable=True),
    )
    op.create_index("ix_influencers_contact_fetch_status", "influencers", ["contact_fetch_status"])


def downgrade() -> None:
    op.drop_index("ix_influencers_contact_fetch_status", table_name="influencers")
    op.drop_column("influencers", "contact_credibility_level")
    op.drop_column("influencers", "contact_fetch_error")
    op.drop_column("influencers", "contact_fetch_status")
    op.drop_column("influencers", "contact_sources")
    op.drop_column("influencers", "contact_discovered_at")
