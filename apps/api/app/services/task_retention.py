"""采集任务删除/归档：保留红人库与来源追溯数据。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CollectionTaskStatus
from app.models.product_influencer_source import ProductInfluencerSource
from app.services.task_effectiveness import batch_task_has_valuable_insert, is_collection_task_ineffective

DisposalAction = Literal["deleted", "archived", "skipped"]


def task_has_obvious_retention(task: CollectionTask) -> bool:
    from app.services.task_effectiveness import inserted_count

    return inserted_count(task) > 0


async def task_has_retention_traces(db: AsyncSession, task_id: int, *, task: CollectionTask | None = None) -> bool:
    if task is not None and task_has_obvious_retention(task):
        return True

    candidate_count = await db.scalar(
        select(func.count())
        .select_from(CollectionTaskCandidate)
        .where(CollectionTaskCandidate.task_id == task_id)
    )
    if candidate_count and candidate_count > 0:
        return True

    source_count = await db.scalar(
        select(func.count())
        .select_from(ProductInfluencerSource)
        .where(ProductInfluencerSource.task_id == task_id)
    )
    return bool(source_count and source_count > 0)


async def batch_task_has_retention_traces(
    db: AsyncSession,
    task_ids: list[int],
    *,
    tasks: list[CollectionTask] | None = None,
) -> dict[int, bool]:
    """批量判断任务是否含需保留的追溯数据（统计、候选池、来源关系）。"""
    if not task_ids:
        return {}

    flags = {task_id: False for task_id in task_ids}
    if tasks:
        for task in tasks:
            if task_has_obvious_retention(task):
                flags[task.id] = True

    pending = [task_id for task_id in task_ids if not flags[task_id]]
    if not pending:
        return flags

    candidate_task_ids = (
        await db.execute(
            select(CollectionTaskCandidate.task_id)
            .where(CollectionTaskCandidate.task_id.in_(pending))
            .distinct()
        )
    ).scalars().all()
    for task_id in candidate_task_ids:
        flags[task_id] = True

    pending = [task_id for task_id in pending if not flags[task_id]]
    if not pending:
        return flags

    source_task_ids = (
        await db.execute(
            select(ProductInfluencerSource.task_id)
            .where(ProductInfluencerSource.task_id.in_(pending))
            .distinct()
        )
    ).scalars().all()
    for task_id in source_task_ids:
        flags[task_id] = True

    return flags


async def dispose_collection_task(
    db: AsyncSession,
    task: CollectionTask,
    *,
    require_ineffective: bool = True,
) -> tuple[DisposalAction, str | None]:
    """删除或归档单个任务。返回 (action, skip_reason)。"""
    if task.is_archived:
        return "skipped", "任务已归档"
    if task.status == CollectionTaskStatus.RUNNING.value:
        return "skipped", "任务正在运行中"
    if require_ineffective:
        valuable_flags = await batch_task_has_valuable_insert(db, [task.id])
        if not is_collection_task_ineffective(task, has_valuable_insert=valuable_flags.get(task.id)):
            return "skipped", "只能删除无效果任务"

    if await task_has_retention_traces(db, task.id, task=task):
        task.is_archived = True
        task.archived_at = datetime.now(UTC)
        return "archived", None

    await db.delete(task)
    return "deleted", None
