"""021: influencers.platform_unique_id（YouTube 频道级唯一兜底）

回填策略：
1. 可从 profile_url 的 /channel/UC... 直接提取 platform_unique_id
2. 若同 username（忽略大小写）仅对应一个 UC，则向仍为 NULL 的行传播（含 @handle URL）
3. 同一 (platform, platform_unique_id) 保留最小 id，其余清空 UC，避免唯一索引创建失败
4. 纯 @handle /c/ /user/ 且无法与已知 UC 关联的行保持 NULL——不能安全映射，不假装已去重
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021_influencer_platform_unique_id"
down_revision: Union[str, None] = "020_collection_task_run_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_youtube_platform_unique_id() -> None:
    op.execute(
        """
        UPDATE influencers
        SET platform_unique_id = substring(profile_url from 'youtube\\.com/channel/(UC[^/]+)')
        WHERE platform = 'youtube'
          AND platform_unique_id IS NULL
          AND profile_url ~* 'youtube\\.com/channel/UC'
        """
    )
    op.execute(
        """
        UPDATE influencers AS target
        SET platform_unique_id = source.uc_id
        FROM (
            SELECT LOWER(username) AS username_key, MIN(platform_unique_id) AS uc_id
            FROM influencers
            WHERE platform = 'youtube'
              AND platform_unique_id IS NOT NULL
            GROUP BY LOWER(username)
            HAVING COUNT(DISTINCT platform_unique_id) = 1
        ) AS source
        WHERE target.platform = 'youtube'
          AND target.platform_unique_id IS NULL
          AND LOWER(target.username) = source.username_key
        """
    )
    op.execute(
        """
        UPDATE influencers
        SET platform_unique_id = NULL
        WHERE platform = 'youtube'
          AND platform_unique_id IS NOT NULL
          AND id NOT IN (
            SELECT MIN(id)
            FROM influencers
            WHERE platform = 'youtube'
              AND platform_unique_id IS NOT NULL
            GROUP BY platform, platform_unique_id
          )
        """
    )


def upgrade() -> None:
    op.add_column(
        "influencers",
        sa.Column("platform_unique_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_influencers_platform_unique_id",
        "influencers",
        ["platform_unique_id"],
        unique=False,
    )
    _backfill_youtube_platform_unique_id()
    op.create_index(
        "uq_influencers_platform_unique_id",
        "influencers",
        ["platform", "platform_unique_id"],
        unique=True,
        postgresql_where=sa.text("platform_unique_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_influencers_platform_unique_id", table_name="influencers")
    op.drop_index("ix_influencers_platform_unique_id", table_name="influencers")
    op.drop_column("influencers", "platform_unique_id")
