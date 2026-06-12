"""024: link-import 租户字段 + 全局红人去重合并"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_tenant_link_import_global_dedup"
down_revision: Union[str, None] = "023_multi_tenant_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("link_import_batches", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("link_import_batches", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.add_column("link_import_batches", sa.Column("product_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_link_import_batches_user_id",
        "link_import_batches",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_link_import_batches_workspace_id",
        "link_import_batches",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_link_import_batches_product_id",
        "link_import_batches",
        "products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_link_import_batches_user_id", "link_import_batches", ["user_id"])
    op.create_index("ix_link_import_batches_workspace_id", "link_import_batches", ["workspace_id"])
    op.create_index("ix_link_import_batches_product_id", "link_import_batches", ["product_id"])

    op.execute(
        """
        UPDATE link_import_batches
        SET user_id = COALESCE(user_id, 1),
            workspace_id = COALESCE(workspace_id, 1),
            product_id = COALESCE(product_id, 1)
        """
    )

    op.execute(
        """
        WITH duplicate_groups AS (
            SELECT platform, platform_unique_id, MIN(id) AS canonical_id, ARRAY_AGG(id ORDER BY id) AS all_ids
            FROM global_influencer_profiles
            WHERE platform_unique_id IS NOT NULL
            GROUP BY platform, platform_unique_id
            HAVING COUNT(*) > 1
        ),
        duplicate_map AS (
            SELECT canonical_id, UNNEST(all_ids) AS duplicate_id
            FROM duplicate_groups
        ),
        remapped AS (
            SELECT duplicate_id, canonical_id
            FROM duplicate_map
            WHERE duplicate_id <> canonical_id
        )
        UPDATE product_influencers pi
        SET global_influencer_id = r.canonical_id
        FROM remapped r
        WHERE pi.global_influencer_id = r.duplicate_id
          AND NOT EXISTS (
              SELECT 1
              FROM product_influencers existing
              WHERE existing.product_id = pi.product_id
                AND existing.global_influencer_id = r.canonical_id
                AND existing.id <> pi.id
          )
        """
    )

    op.execute(
        """
        WITH duplicate_groups AS (
            SELECT platform, platform_unique_id, MIN(id) AS canonical_id, ARRAY_AGG(id ORDER BY id) AS all_ids
            FROM global_influencer_profiles
            WHERE platform_unique_id IS NOT NULL
            GROUP BY platform, platform_unique_id
            HAVING COUNT(*) > 1
        ),
        duplicate_map AS (
            SELECT canonical_id, UNNEST(all_ids) AS duplicate_id
            FROM duplicate_groups
        ),
        remapped AS (
            SELECT duplicate_id, canonical_id
            FROM duplicate_map
            WHERE duplicate_id <> canonical_id
        )
        UPDATE collection_task_candidates c
        SET global_influencer_id = r.canonical_id
        FROM remapped r
        WHERE c.global_influencer_id = r.duplicate_id
        """
    )

    op.execute(
        """
        WITH duplicate_groups AS (
            SELECT platform, platform_unique_id, MIN(id) AS canonical_id, ARRAY_AGG(id ORDER BY id) AS all_ids
            FROM global_influencer_profiles
            WHERE platform_unique_id IS NOT NULL
            GROUP BY platform, platform_unique_id
            HAVING COUNT(*) > 1
        ),
        duplicate_map AS (
            SELECT canonical_id, UNNEST(all_ids) AS duplicate_id
            FROM duplicate_groups
        ),
        remapped AS (
            SELECT duplicate_id, canonical_id
            FROM duplicate_map
            WHERE duplicate_id <> canonical_id
        )
        UPDATE collection_task_candidates c
        SET product_influencer_id = target_pi.id
        FROM remapped r
        JOIN product_influencers target_pi
          ON target_pi.global_influencer_id = r.canonical_id
         AND target_pi.product_id = c.product_id
        WHERE c.product_influencer_id IN (
            SELECT pi.id FROM product_influencers pi WHERE pi.global_influencer_id = r.duplicate_id
        )
        """
    )

    op.execute(
        """
        DELETE FROM global_influencer_profiles g
        USING (
            SELECT platform, platform_unique_id, MIN(id) AS canonical_id
            FROM global_influencer_profiles
            WHERE platform_unique_id IS NOT NULL
            GROUP BY platform, platform_unique_id
            HAVING COUNT(*) > 1
        ) d
        WHERE g.platform = d.platform
          AND g.platform_unique_id = d.platform_unique_id
          AND g.id <> d.canonical_id
          AND NOT EXISTS (
              SELECT 1 FROM product_influencers pi WHERE pi.global_influencer_id = g.id
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_link_import_batches_product_id", table_name="link_import_batches")
    op.drop_index("ix_link_import_batches_workspace_id", table_name="link_import_batches")
    op.drop_index("ix_link_import_batches_user_id", table_name="link_import_batches")
    op.drop_constraint("fk_link_import_batches_product_id", "link_import_batches", type_="foreignkey")
    op.drop_constraint("fk_link_import_batches_workspace_id", "link_import_batches", type_="foreignkey")
    op.drop_constraint("fk_link_import_batches_user_id", "link_import_batches", type_="foreignkey")
    op.drop_column("link_import_batches", "product_id")
    op.drop_column("link_import_batches", "workspace_id")
    op.drop_column("link_import_batches", "user_id")
