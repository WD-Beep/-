"""采集任务效果分类：有效果 / 无价值结果 / 无结果。"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionTaskStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.models.product_influencer_source import ProductInfluencerSource
from app.services.influencer_profile_value import global_profile_valuable_sql, is_influencer_profile_valuable

EffectivenessCategory = Literal["high_value", "effective", "low_value_result", "no_result", "failed"]

_RUNNING = CollectionTaskStatus.RUNNING.value
_COMPLETED_WITH_RESULTS = CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
_INSERTED = CandidateStatus.INSERTED.value
_LOW_VALUE_SEED_FAILURE = "low_value_seed"


def effective_result_count(task: CollectionTask) -> int:
    return max(
        int(task.inserted_count or 0),
        int(task.result_count or 0),
        int(task.success_count or 0),
    )


def inserted_count(task: CollectionTask) -> int:
    return effective_result_count(task)


def is_high_value_task(task: CollectionTask) -> bool:
    inserted = effective_result_count(task)
    result = int(task.result_count or 0)
    discovered = int(task.discovered_count or 0)
    fetched = int(task.profile_fetched_count or 0)
    email = int(task.email_count or 0)
    if inserted >= 5 or result >= 5:
        return True
    if discovered >= 50 and inserted >= 1:
        return True
    if fetched >= 20 and inserted >= 1:
        return True
    if email >= 1 and inserted >= 1:
        return True
    if (
        (task.status or "") in {
            CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
            CollectionTaskStatus.PARTIAL_FAILED.value,
        }
        and inserted > 0
        and discovered >= inserted
        and fetched >= inserted
        and (discovered >= 10 or fetched >= 10)
    ):
        return True
    return False


def has_insert_records(task: CollectionTask) -> bool:
    if effective_result_count(task) > 0:
        return True
    if (task.status or "") == _COMPLETED_WITH_RESULTS:
        return True
    return False


def _global_profile_valuable_sql():
    return global_profile_valuable_sql()


def _candidate_valuable_sql():
    return or_(
        CollectionTaskCandidate.is_high_value.is_(True),
        CollectionTaskCandidate.has_email.is_(True),
        CollectionTaskCandidate.has_contact.is_(True),
        CollectionTaskCandidate.followers_count.isnot(None),
        CollectionTaskCandidate.engagement_rate.isnot(None),
    )


def _task_has_valuable_insert_sql():
    return or_(
        exists(
            select(1)
            .select_from(ProductInfluencerSource)
            .join(ProductInfluencer, ProductInfluencer.id == ProductInfluencerSource.product_influencer_id)
            .join(
                GlobalInfluencerProfile,
                GlobalInfluencerProfile.id == ProductInfluencer.global_influencer_id,
            )
            .where(
                ProductInfluencerSource.task_id == CollectionTask.id,
                _global_profile_valuable_sql(),
            )
        ),
        exists(
            select(1)
            .select_from(CollectionTaskCandidate)
            .where(
                CollectionTaskCandidate.task_id == CollectionTask.id,
                CollectionTaskCandidate.status == _INSERTED,
                _candidate_valuable_sql(),
            )
        ),
    )


def _has_insert_records_clause():
    return or_(
        func.coalesce(CollectionTask.inserted_count, 0) > 0,
        func.coalesce(CollectionTask.result_count, 0) > 0,
        func.coalesce(CollectionTask.success_count, 0) > 0,
        CollectionTask.status == _COMPLETED_WITH_RESULTS,
    )


def _task_has_low_value_seed_candidate_sql():
    return exists(
        select(1)
        .select_from(CollectionTaskCandidate)
        .where(
            CollectionTaskCandidate.task_id == CollectionTask.id,
            CollectionTaskCandidate.failure_reason == _LOW_VALUE_SEED_FAILURE,
        )
    )


def _task_has_low_value_seed_marker(task: CollectionTask) -> bool:
    checkpoint = task.run_checkpoint or {}
    enrichment = checkpoint.get("link_seed_enrichment") or {}
    return int(enrichment.get("low_value_seed_count") or 0) > 0


def classify_task_effectiveness(task: CollectionTask, *, has_valuable_insert: bool | None = None) -> EffectivenessCategory:
    if task.status == _RUNNING:
        return "no_result"
    if is_high_value_task(task):
        return "high_value"
    if not has_insert_records(task):
        if has_valuable_insert is True:
            return "effective"
        if task.status == CollectionTaskStatus.FAILED.value:
            return "failed"
        if has_valuable_insert is False and _task_has_low_value_seed_marker(task):
            return "low_value_result"
        return "no_result"
    inserted = effective_result_count(task)
    discovered = int(task.discovered_count or 0)
    if has_valuable_insert is True:
        return "effective"
    if inserted == 1 and discovered <= 3:
        return "low_value_result"
    if has_valuable_insert is False:
        return "effective" if inserted > 0 else "low_value_result"
    return "effective"


def is_collection_task_effective(task: CollectionTask, *, has_valuable_insert: bool | None = None) -> bool:
    if has_valuable_insert is True:
        return True
    if has_valuable_insert is False:
        return False
    return classify_task_effectiveness(task, has_valuable_insert=has_valuable_insert) == "effective"


def is_collection_task_ineffective(task: CollectionTask, *, has_valuable_insert: bool | None = None) -> bool:
    """可批量清理：无结果或无价值结果（非有效果）。"""
    if task.status == _RUNNING:
        return False
    if is_high_value_task(task):
        return False
    if has_valuable_insert is True:
        return False
    if not has_insert_records(task):
        return True
    if has_valuable_insert is False:
        return True
    return False


def has_effective_results(task: CollectionTask) -> bool:
    return is_collection_task_effective(task)


def no_result_sql_condition():
    return and_(
        CollectionTask.status != _RUNNING,
        not_(_has_insert_records_clause()),
        not_(_task_has_low_value_seed_candidate_sql()),
    )


def high_value_sql_condition():
    inserted = func.coalesce(CollectionTask.inserted_count, CollectionTask.result_count, 0)
    result = func.coalesce(CollectionTask.result_count, 0)
    discovered = func.coalesce(CollectionTask.discovered_count, 0)
    fetched = func.coalesce(CollectionTask.profile_fetched_count, 0)
    email = func.coalesce(CollectionTask.email_count, 0)
    return and_(
        CollectionTask.status != _RUNNING,
        or_(
            inserted >= 5,
            result >= 5,
            and_(discovered >= 50, inserted >= 1),
            and_(fetched >= 20, inserted >= 1),
            and_(email >= 1, inserted >= 1),
            and_(
                CollectionTask.status.in_(
                    [
                        CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
                        CollectionTaskStatus.PARTIAL_FAILED.value,
                    ]
                ),
                inserted > 0,
                discovered >= inserted,
                fetched >= inserted,
                or_(discovered >= 10, fetched >= 10),
            ),
        ),
    )


def low_value_result_sql_condition():
    inserted = func.coalesce(CollectionTask.inserted_count, CollectionTask.result_count, 0)
    discovered = func.coalesce(CollectionTask.discovered_count, 0)
    return and_(
        CollectionTask.status != _RUNNING,
        not_(high_value_sql_condition()),
        or_(
            and_(
                _has_insert_records_clause(),
                inserted == 1,
                discovered <= 3,
            ),
            and_(
                not_(_has_insert_records_clause()),
                _task_has_low_value_seed_candidate_sql(),
            ),
        ),
    )


def effective_sql_condition():
    return and_(
        CollectionTask.status != _RUNNING,
        not_(high_value_sql_condition()),
        not_(low_value_result_sql_condition()),
        or_(_has_insert_records_clause(), _task_has_valuable_insert_sql()),
    )


def ineffective_sql_condition():
    """无效果 = 非运行中且非有效果（含无结果与无价值结果）。"""
    return and_(
        CollectionTask.status != _RUNNING,
        not_(high_value_sql_condition()),
        not_(effective_sql_condition()),
    )


async def batch_task_has_valuable_insert(
    db: AsyncSession,
    task_ids: list[int],
) -> dict[int, bool]:
    if not task_ids:
        return {}

    source_rows = await db.execute(
        select(ProductInfluencerSource.task_id, GlobalInfluencerProfile)
        .join(ProductInfluencer, ProductInfluencer.id == ProductInfluencerSource.product_influencer_id)
        .join(GlobalInfluencerProfile, GlobalInfluencerProfile.id == ProductInfluencer.global_influencer_id)
        .where(ProductInfluencerSource.task_id.in_(task_ids))
    )
    flags = {task_id: False for task_id in task_ids}
    for task_id, profile in source_rows.all():
        if task_id is None:
            continue
        if is_influencer_profile_valuable(profile):
            flags[int(task_id)] = True

    candidate_rows = await db.execute(
        select(CollectionTaskCandidate)
        .where(
            CollectionTaskCandidate.task_id.in_(task_ids),
            CollectionTaskCandidate.status == _INSERTED,
        )
    )
    from app.services.influencer_profile_value import is_candidate_row_valuable

    for candidate in candidate_rows.scalars().all():
        if is_candidate_row_valuable(candidate):
            flags[candidate.task_id] = True

    return flags


async def batch_task_effectiveness_categories(
    db: AsyncSession,
    tasks: list[CollectionTask],
) -> dict[int, EffectivenessCategory]:
    valuable = await batch_task_has_valuable_insert(db, [t.id for t in tasks])
    low_value_seed_task_ids: set[int] = set()
    task_ids = [t.id for t in tasks]
    if task_ids:
        rows = await db.execute(
            select(CollectionTaskCandidate.task_id)
            .where(
                CollectionTaskCandidate.task_id.in_(task_ids),
                CollectionTaskCandidate.failure_reason == _LOW_VALUE_SEED_FAILURE,
            )
            .distinct()
        )
        low_value_seed_task_ids = {int(task_id) for task_id in rows.scalars().all() if task_id is not None}

    result: dict[int, EffectivenessCategory] = {}
    for task in tasks:
        has_valuable = valuable.get(task.id, False)
        if not has_insert_records(task) and not has_valuable:
            if _task_has_low_value_seed_marker(task) or task.id in low_value_seed_task_ids:
                category: EffectivenessCategory = "low_value_result"
            elif task.status == CollectionTaskStatus.FAILED.value:
                category = "failed"
            else:
                category = "no_result"
        else:
            category = classify_task_effectiveness(task, has_valuable_insert=has_valuable)
        result[task.id] = category
    return result
