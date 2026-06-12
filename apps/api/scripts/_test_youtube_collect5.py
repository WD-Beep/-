"""YouTube 类目采集测试：目标 5 条合格入库。"""
from __future__ import annotations

import asyncio
import traceback

from app.db.session import async_session_factory
from app.models.enums import CollectionMode
from app.schemas.collection_task import CollectionTaskCreate
from app.services.collection_runner import CollectionRunnerService
from app.services.collection_task import CollectionTaskService


async def main() -> int:
    payload = CollectionTaskCreate(
        name="Agent YouTube 5条入库测试",
        collection_mode=CollectionMode.CATEGORY_DISCOVERY,
        platform="youtube",
        keywords=[
            "AmazonFinds",
            "amazon finds creator",
            "amazon home finds",
            "amazon must haves",
        ],
        country="US",
        category="AmazonFinds",
        discovery_limit=5,
        min_engagement_rate=0.5,
        min_followers_count=3000,
        filter_include_keywords=[
            "amazon",
            "finds",
            "must haves",
            "must-haves",
            "storefront",
            "home",
            "deals",
            "recommendations",
            "affiliate",
            "creator",
            "influencer",
            "haul",
            "review",
            "ltk",
            "link in bio",
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
        print(f"created task_id={task.id} name={task.name!r}")
        try:
            await CollectionRunnerService.run_task(db, task, allow_running=True)
        except Exception as exc:
            print(f"run error: {exc}")
            traceback.print_exc()
            return 1

        await db.refresh(task)
        print("--- result ---")
        print(f"status={task.status}")
        print(f"inserted={task.inserted_count} target={task.discovery_limit}")
        print(
            f"pipeline: discovered={task.discovered_count} deduped={task.deduped_count} "
            f"homepage={task.profile_fetched_count} filtered={task.filtered_out_count}"
        )
        print(f"summary={task.status_summary!r}")
        if task.last_error:
            print(f"last_error={task.last_error!r}")
        if task.error_message:
            print(f"error_message={task.error_message!r}")
        ok = (task.inserted_count or 0) >= (task.discovery_limit or 5)
        print(f"PASS={ok}")
        return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
