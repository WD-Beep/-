"""022: YouTube platform_unique_id 历史数据补强回填（021 已执行环境）

- 通过同 username 且唯一 UC 的行，向 @handle 等 URL 形态传播 platform_unique_id
- 清理同一 (platform, platform_unique_id) 的重复行（保留最小 id，其余清空 UC 避免唯一索引冲突）
- @handle 无法单独推断 UC 的行保持 NULL，依赖应用层 identity key 去重，不会假装已闭环
"""

from typing import Sequence, Union

from alembic import op

revision: str = "022_youtube_platform_unique_id_backfill"
down_revision: Union[str, None] = "021_influencer_platform_unique_id"
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
    _backfill_youtube_platform_unique_id()


def downgrade() -> None:
    pass
