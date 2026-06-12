"""创建并运行 YouTube 5 条入库测试（与 task 75 同配置）。"""
from __future__ import annotations

import asyncio

from app.db.session import async_session_factory
from app.models.enums import CollectionMode
from app.schemas.collection_task import CollectionTaskCreate
from app.services.collection_runner import CollectionRunnerService
from app.services.collection_task import CollectionTaskService


async def main() -> int:
    payload = CollectionTaskCreate(
        name="Agent YouTube 5条验证",
        collection_mode=CollectionMode.DISCOVERY,
        platform="youtube",
        keywords=["amazon finds creator", "amazon home finds", "AmazonFinds"],
        country="US",
        discovery_limit=5,
        min_engagement_rate=0.5,
        min_followers_count=3000,
        filter_include_keywords=[
            "amazon",
            "finds",
            "must haves",
            "storefront",
            "home",
            "deals",
            "affiliate",
            "creator",
            "influencer",
            "haul",
            "review",
        ],
        filter_exclude_keywords=[
            "wholesale",
            "official store",
            "our shop",
            "customer service",
            "fan page",
            "coupon only",
            "news account",
        ],
    )
    async with async_session_factory() as db:
        task = await CollectionTaskService.create_task(db, payload)
        print(f"created task_id={task.id}")
        await CollectionRunnerService.run_task(db, task, allow_running=True)
        await db.refresh(task)
        inserted = task.inserted_count or 0
        target = task.discovery_limit or 5
        print(
            f"status={task.status} inserted={inserted}/{target} "
            f"discovered={task.discovered_count} filtered={task.filtered_out_count}"
        )
        if task.last_error:
            print(f"last_error={task.last_error}")
        if task.status_summary:
            print(f"summary={task.status_summary}")
        return 0 if inserted >= target else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
