"""Add extended influencer profile fields."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_influencer_extended_profile"
down_revision: Union[str, None] = "002_add_score_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("influencers", sa.Column("niche", sa.String(length=100), nullable=True))
    op.add_column("influencers", sa.Column("final_email", sa.String(length=255), nullable=True))
    op.add_column("influencers", sa.Column("public_email", sa.String(length=255), nullable=True))
    op.add_column("influencers", sa.Column("business_email", sa.String(length=255), nullable=True))
    op.add_column("influencers", sa.Column("email_source", sa.String(length=100), nullable=True))
    op.add_column("influencers", sa.Column("contact_credibility", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("contact_score", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("contact_page", sa.String(length=1024), nullable=True))
    op.add_column("influencers", sa.Column("linktree_url", sa.String(length=1024), nullable=True))
    op.add_column("influencers", sa.Column("whatsapp", sa.String(length=50), nullable=True))
    op.add_column("influencers", sa.Column("telegram", sa.String(length=100), nullable=True))
    op.add_column(
        "influencers",
        sa.Column("other_social_links", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("influencers", sa.Column("product_fit", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("data_completeness", sa.Float(), nullable=True))
    op.add_column("influencers", sa.Column("has_brand_collaboration", sa.Boolean(), nullable=True))
    op.add_column("influencers", sa.Column("estimated_collab_price", sa.String(length=100), nullable=True))
    op.add_column(
        "influencers",
        sa.Column("collaboration_formats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("content_topics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("influencers", sa.Column("audience_country", sa.String(length=100), nullable=True))
    op.add_column("influencers", sa.Column("audience_language", sa.String(length=50), nullable=True))
    op.add_column(
        "influencers",
        sa.Column("recent_post_titles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "influencers",
        sa.Column("recent_post_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("influencers", sa.Column("last_post_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("influencers", sa.Column("posting_frequency", sa.String(length=50), nullable=True))

    op.execute(
        """
        UPDATE influencers
        SET final_email = email
        WHERE final_email IS NULL AND email IS NOT NULL
        """
    )


def downgrade() -> None:
    columns = [
        "niche",
        "final_email",
        "public_email",
        "business_email",
        "email_source",
        "contact_credibility",
        "contact_score",
        "contact_page",
        "linktree_url",
        "whatsapp",
        "telegram",
        "other_social_links",
        "product_fit",
        "data_completeness",
        "has_brand_collaboration",
        "estimated_collab_price",
        "collaboration_formats",
        "content_topics",
        "audience_country",
        "audience_language",
        "recent_post_titles",
        "recent_post_urls",
        "last_post_at",
        "posting_frequency",
    ]
    for column in columns:
        op.drop_column("influencers", column)
