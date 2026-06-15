"""无效果任务删除：任意候选状态均需归档。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.models.product_influencer_source import ProductInfluencerSource
from app.services.collection_task import CollectionTaskService


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


CANDIDATE_STATUSES = (
    CandidateStatus.PROFILE_FAILED,
    CandidateStatus.FILTERED_OUT,
    CandidateStatus.NOT_INSERTED,
    CandidateStatus.DUPLICATE,
    CandidateStatus.DISCOVERED,
)


@pytest.mark.parametrize("status", CANDIDATE_STATUSES)
@pytest.mark.anyio
async def test_dispose_archives_ineffective_task_with_any_candidate_status(status: CandidateStatus):
    post_url = "https://www.tiktok.com/@creator/video/1234567890"
    input_url = "https://vm.tiktok.com/abc123/"
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
                status=status.value,
                source_post_url=post_url,
                source_meta={"source_input_url": input_url, "input_url": input_url},
            )
        )
        await db.flush()

        action = await CollectionTaskService.dispose_task(db, task)
        await db.refresh(task)

        assert action == "archived"
        assert task.is_archived is True

        candidate_count = await db.scalar(
            select(func.count())
            .select_from(CollectionTaskCandidate)
            .where(CollectionTaskCandidate.task_id == task.id)
        )
        assert candidate_count == 1
        candidate = (
            await db.execute(
                select(CollectionTaskCandidate).where(CollectionTaskCandidate.task_id == task.id)
            )
        ).scalar_one()
        assert candidate.source_post_url == post_url
        assert candidate.source_meta["source_input_url"] == input_url

        assert await CollectionTaskService.get_task(db, task.id) is None
        assert await db.get(CollectionTask, task.id) is not None

        await db.rollback()


@pytest.mark.anyio
async def test_dispose_archives_task_with_product_influencer_source_only():
    import uuid

    from app.models.global_influencer_profile import GlobalInfluencerProfile
    from app.models.product_influencer import ProductInfluencer

    suffix = uuid.uuid4().hex[:8]
    async with async_session_factory() as db:
        task = _task()
        db.add(task)
        await db.flush()
        profile_url = f"https://www.tiktok.com/@creator_{suffix}"
        global_row = GlobalInfluencerProfile(
            platform="tiktok",
            username=f"creator_{suffix}",
            normalized_username=f"creator_{suffix}",
            profile_url=profile_url,
            normalized_profile_url=profile_url,
        )
        db.add(global_row)
        await db.flush()
        product_row = ProductInfluencer(
            product_id=1,
            global_influencer_id=global_row.id,
        )
        db.add(product_row)
        await db.flush()
        db.add(
            ProductInfluencerSource(
                product_influencer_id=product_row.id,
                task_id=task.id,
                source_post_url="https://www.tiktok.com/@creator/video/999",
                source_input_url="https://vm.tiktok.com/999",
                source_platform="tiktok",
                task_name=task.name,
                source_key="https://www.tiktok.com/@creator/video/999",
                collected_at=datetime.now(UTC),
            )
        )
        await db.flush()

        action = await CollectionTaskService.dispose_task(db, task)
        await db.refresh(task)
        assert action == "archived"

        source_count = await db.scalar(
            select(func.count())
            .select_from(ProductInfluencerSource)
            .where(ProductInfluencerSource.task_id == task.id)
        )
        assert source_count == 1
        await db.rollback()
