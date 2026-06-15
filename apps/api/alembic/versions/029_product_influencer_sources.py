"""029: 红人来源作品链接关联表"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029_product_influencer_sources"
down_revision: Union[str, None] = "028_product_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_influencer_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_influencer_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        sa.Column("source_post_url", sa.String(length=512), nullable=True),
        sa.Column("source_input_url", sa.String(length=512), nullable=True),
        sa.Column("source_platform", sa.String(length=50), nullable=True),
        sa.Column("task_name", sa.String(length=255), nullable=True),
        sa.Column("source_key", sa.String(length=512), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_influencer_id"], ["product_influencers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["collection_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_influencer_id", "source_key", name="uq_product_influencer_source_key"),
    )
    op.create_index(
        "ix_product_influencer_sources_product_influencer_id",
        "product_influencer_sources",
        ["product_influencer_id"],
    )
    op.create_index("ix_product_influencer_sources_task_id", "product_influencer_sources", ["task_id"])

    op.execute(
        """
        INSERT INTO product_influencer_sources (
            product_influencer_id,
            source_post_url,
            source_input_url,
            source_key,
            collected_at
        )
        SELECT
            pi.id,
            pi.source_post_url,
            pi.source_post_url,
            LOWER(RTRIM(pi.source_post_url, '/')),
            COALESCE(pi.last_collected_at, pi.first_inserted_at, pi.created_at, NOW())
        FROM product_influencers pi
        WHERE pi.source_post_url IS NOT NULL
          AND TRIM(pi.source_post_url) <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM product_influencer_sources pis
              WHERE pis.product_influencer_id = pi.id
                AND pis.source_key = LOWER(RTRIM(pi.source_post_url, '/'))
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_product_influencer_sources_task_id", table_name="product_influencer_sources")
    op.drop_index(
        "ix_product_influencer_sources_product_influencer_id",
        table_name="product_influencer_sources",
    )
    op.drop_table("product_influencer_sources")
