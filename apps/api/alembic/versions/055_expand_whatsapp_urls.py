"""Expand WhatsApp fields to preserve full contact URLs."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "055_expand_whatsapp_urls"
down_revision: Union[str, None] = "054_collection_task_runtime_limit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "global_influencer_profiles",
        "whatsapp",
        existing_type=sa.String(length=50),
        type_=sa.String(length=1024),
        existing_nullable=True,
    )
    op.alter_column(
        "influencers",
        "whatsapp",
        existing_type=sa.String(length=50),
        type_=sa.String(length=1024),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "influencers",
        "whatsapp",
        existing_type=sa.String(length=1024),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "global_influencer_profiles",
        "whatsapp",
        existing_type=sa.String(length=1024),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
