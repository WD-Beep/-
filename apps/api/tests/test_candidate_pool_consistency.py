"""候选池统计与列表一致性测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateStatus, CollectionMode
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services.task_candidate import TaskCandidateService


def test_ensure_candidates_backfills_inserted_rows_for_legacy_task():
    run_at = datetime.now(UTC)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = CollectionTask(
                name="legacy-missing-candidates",
                platform="instagram",
                platforms=["instagram"],
                collection_mode=CollectionMode.LINK_IMPORT.value,
                input_urls=["https://www.instagram.com/legacy_creator/"],
                keywords=[],
                product_id=1,
                user_id=1,
                workspace_id=1,
                inserted_count=1,
                result_count=1,
                last_run_at=run_at,
            )
            db.add(task)
            await db.flush()

            item = CollectedInfluencer(
                platform="instagram",
                username="legacy_creator",
                profile_url="https://www.instagram.com/legacy_creator/",
                followers_count=20_000,
                engagement_rate=2.0,
            )
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db.add(global_profile)
            await db.flush()
            product_record = create_product_influencer_from_collected(
                product_id=1,
                global_profile=global_profile,
                data=item,
                task=task,
                run_at=run_at,
            )
            db.add(product_record)
            await db.flush()

            before = await TaskCandidateService.count_by_status(
                db, task.id, status=CandidateStatus.INSERTED.value
            )
            assert before == 0

            created = await TaskCandidateService.ensure_candidates_for_task(db, task)
            assert created == 1

            page = await TaskCandidateService.list_for_task(
                db,
                task.id,
                page=1,
                page_size=20,
                status=CandidateStatus.INSERTED.value,
            )
            assert page.total == 1
            assert page.items[0].username == "legacy_creator"
            assert page.items[0].product_influencer_id == product_record.id

            export_rows = await TaskCandidateService.list_for_export(
                db,
                task.id,
                product_id=1,
                status=CandidateStatus.INSERTED.value,
            )
            assert len(export_rows) == 1

            await db.rollback()

    asyncio.run(_run())


def test_list_for_export_includes_legacy_null_product_id_rows():
    run_at = datetime.now(UTC)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = CollectionTask(
                name="legacy-null-product-id",
                platform="instagram",
                platforms=["instagram"],
                collection_mode=CollectionMode.LINK_IMPORT.value,
                input_urls=[],
                keywords=[],
                product_id=1,
                user_id=1,
                workspace_id=1,
            )
            db.add(task)
            await db.flush()

            await TaskCandidateService.bulk_insert(
                db,
                task.id,
                [
                    TaskCandidateService.row_from_inserted(
                        meta=None,
                        username="null_scope",
                        profile_url="https://www.instagram.com/null_scope/",
                        platform="instagram",
                        collection_mode=task.collection_mode,
                        product_influencer_id=None,
                        product_id=None,
                        followers_count=10_000,
                        engagement_rate=1.5,
                        profile_fetched_at=run_at,
                    )
                ],
                run_at=run_at,
            )
            await db.flush()

            rows = await TaskCandidateService.list_for_export(
                db,
                task.id,
                product_id=1,
                status=CandidateStatus.INSERTED.value,
            )
            assert len(rows) == 1
            assert rows[0][0].username == "null_scope"

            await db.rollback()

    asyncio.run(_run())


def test_sync_task_inserted_stats_aligns_with_candidate_pool():
    run_at = datetime.now(UTC)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = CollectionTask(
                name="sync-inserted-stats",
                platform="instagram",
                platforms=["instagram"],
                collection_mode=CollectionMode.LINK_IMPORT.value,
                input_urls=[],
                keywords=[],
                product_id=1,
                user_id=1,
                workspace_id=1,
                inserted_count=9,
                result_count=9,
            )
            db.add(task)
            await db.flush()

            await TaskCandidateService.bulk_insert(
                db,
                task.id,
                [
                    TaskCandidateService.row_from_inserted(
                        meta=None,
                        username="one",
                        profile_url="https://www.instagram.com/one/",
                        platform="instagram",
                        collection_mode=task.collection_mode,
                        product_influencer_id=1,
                        product_id=1,
                        followers_count=10_000,
                        engagement_rate=1.5,
                        profile_fetched_at=run_at,
                    )
                ],
                run_at=run_at,
                product_id=1,
                user_id=1,
            )
            await TaskCandidateService.sync_task_inserted_stats(db, task)
            assert task.inserted_count == 1
            assert task.result_count == 1

            await db.rollback()

    asyncio.run(_run())
