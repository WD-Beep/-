# 文件说明：后端内部脚本入口，用于初始化、验收或数据处理；当前文件：setup db
import asyncio

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/postgres")
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'influencer_intel'")
    if not exists:
        await conn.execute("CREATE DATABASE influencer_intel")
        print("Created database influencer_intel")
    else:
        print("Database already exists")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
