# 文件说明：后端维护脚本，用于检查、迁移、验证或批处理任务；当前文件：fix sequences
"""修复迁移后手动插入 id=1 导致的序列不同步。"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.session import async_session_factory


async def main() -> None:
    async with async_session_factory() as db:
        for table in ("users", "workspaces", "products", "global_influencer_profiles", "product_influencers"):
            await db.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
                )
            )
        await db.commit()
    print("sequences fixed")


if __name__ == "__main__":
    asyncio.run(main())
