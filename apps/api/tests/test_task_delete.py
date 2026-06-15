"""采集任务删除/归档行为测试。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.services.collection_task import CollectionTaskService
from app.services.task_effectiveness import is_collection_task_ineffective
from app.services.task_retention import task_has_obvious_retention


def _task(**kwargs) -> CollectionTask:
    defaults = {
        "name": "test",
        "collection_mode": CollectionMode.LINK_IMPORT.value,
        "platform": "tiktok",
        "platforms": ["tiktok"],
        "keywords": [],
        "input_urls": ["https://www.tiktok.com/@u/video/1"],
        "status": CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
        "last_run_at": datetime.now(UTC),
        "inserted_count": 0,
        "result_count": 0,
        "discovered_count": 1,
        "profile_fetched_count": 0,
        "is_archived": False,
    }
    defaults.update(kwargs)
    return CollectionTask(**defaults)


def test_ineffective_without_inserts_has_no_obvious_retention():
    task = _task()
    assert is_collection_task_ineffective(task) is True
    assert task_has_obvious_retention(task) is False


def test_task_with_inserted_count_has_retention():
    task = _task(inserted_count=1, status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value)
    assert task_has_obvious_retention(task) is True
    assert is_collection_task_ineffective(task) is False


@pytest.mark.anyio
async def test_dispose_archives_task_with_retention_traces():
    async with async_session_factory() as db:
        task = _task()
        db.add(task)
        await db.flush()
        db.add(
            CollectionTaskCandidate(
                task_id=task.id,
                username="creator",
                profile_url="https://www.instagram.com/creator/",
                platform="instagram",
                status=CandidateStatus.INSERTED.value,
            )
        )
        await db.flush()
        action = await CollectionTaskService.dispose_task(db, task)
        await db.refresh(task)
        assert action == "archived"
        assert task.is_archived is True
        assert task.archived_at is not None
        await db.rollback()


@pytest.mark.anyio
async def test_dispose_physically_deletes_clean_ineffective_task():
    async with async_session_factory() as db:
        task = _task()
        db.add(task)
        await db.flush()
        task_id = task.id
        action = await CollectionTaskService.dispose_task(db, task)
        assert action == "deleted"
        assert await db.get(CollectionTask, task_id) is None
        await db.rollback()


@pytest.mark.anyio
async def test_dispose_skips_effective_task():
    async with async_session_factory() as db:
        task = _task(
            inserted_count=2,
            status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
        )
        db.add(task)
        await db.flush()
        db.add(
            CollectionTaskCandidate(
                task_id=task.id,
                product_id=1,
                username="creator",
                profile_url="https://www.instagram.com/creator/",
                platform="instagram",
                status=CandidateStatus.INSERTED.value,
                is_high_value=True,
                has_email=True,
            )
        )
        await db.flush()
        with pytest.raises(ValueError, match="只能删除无效果任务"):
            await CollectionTaskService.dispose_task(db, task)
        await db.rollback()


@pytest.mark.anyio
async def test_dispose_bulk_returns_deleted_archived_skipped():
    async with async_session_factory() as db:
        clean = _task(name="clean")
        retained = _task(name="retained")
        effective = _task(
            name="effective",
            inserted_count=1,
            status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
        )
        db.add_all([clean, retained, effective])
        await db.flush()
        db.add(
            CollectionTaskCandidate(
                task_id=retained.id,
                username="creator",
                profile_url="https://www.instagram.com/creator/",
                platform="instagram",
                status=CandidateStatus.INSERTED.value,
            )
        )
        db.add(
            CollectionTaskCandidate(
                task_id=effective.id,
                product_id=1,
                username="creator",
                profile_url="https://www.instagram.com/creator/",
                platform="instagram",
                status=CandidateStatus.INSERTED.value,
                is_high_value=True,
                has_email=True,
            )
        )
        await db.flush()
        result = await CollectionTaskService.dispose_tasks_bulk(
            db, [clean, retained, effective], require_ineffective=True
        )
        assert clean.id in result["deleted_ids"]
        assert retained.id in result["archived_ids"]
        assert effective.id in result["skipped_ids"]
        await db.rollback()
