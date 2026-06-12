from __future__ import annotations

import asyncio

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.services.platform_providers.tiktok_api_direct import TikTokApiDirectProvider


async def main() -> None:
    async with async_session_factory() as db:
        task = await db.get(CollectionTask, 87)
        assert task
        print("keywords", task.keywords[:5])
        result = await TikTokApiDirectProvider.discover(task)
        print("discovered", result.discovered_count)
        print("deduped", result.deduped_count)
        print("items", len(result.items or []))
        print("errors", result.errors)
        print("fatal", result.fatal)


if __name__ == "__main__":
    asyncio.run(main())
