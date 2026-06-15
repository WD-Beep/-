"""任务列表 has_retention_traces 应反映候选池与来源关系。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.schemas.collection_task import CollectionTaskFilter
from app.services.collection_task import CollectionTaskService


def _task(**kwargs) -> CollectionTask:
    defaults = {
        "name": f"retention-flag-{uuid.uuid4().hex[:8]}",
        "product_id": 1,
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


@pytest.mark.anyio
async def test_list_tasks_marks_retention_when_only_candidates_exist():
    async with async_session_factory() as db:
        task = _task()
        db.add(task)
        await db.flush()
        db.add(
            CollectionTaskCandidate(
                task_id=task.id,
                username="creator",
                profile_url="https://www.tiktok.com/@creator",
                platform="tiktok",
                status=CandidateStatus.DISCOVERED.value,
            )
        )
        await db.flush()

        result = await CollectionTaskService.list_tasks(
            db,
            CollectionTaskFilter(product_id=1, search=task.name),
            page=1,
            page_size=20,
        )
        matched = [row for row in result.items if row.id == task.id]
        assert len(matched) == 1
        assert matched[0].has_retention_traces is True
        assert matched[0].is_ineffective is True

        await db.rollback()


@pytest.mark.anyio
async def test_list_tasks_no_retention_for_clean_ineffective_task():
    async with async_session_factory() as db:
        task = _task()
        db.add(task)
        await db.flush()

        result = await CollectionTaskService.list_tasks(
            db,
            CollectionTaskFilter(product_id=1, search=task.name),
            page=1,
            page_size=20,
        )
        matched = [row for row in result.items if row.id == task.id]
        assert len(matched) == 1
        assert matched[0].has_retention_traces is False

        await db.rollback()
