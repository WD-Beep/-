import math
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionMode, CollectionTaskStatus
from app.schemas.collection_task import (
    CollectionTaskBulkManageResult,
    CollectionTaskCreate,
    CollectionTaskFilter,
    CollectionTaskRead,
    CollectionTaskUpdate,
    HIGH_VALUE_FIRST_MIN_FOLLOWERS,
    HIGH_VALUE_FIRST_MODES,
    build_link_import_task_fields,
    validate_seed_only_discovery_mode,
    validate_url_only_platforms_for_mode,
)
from app.services.url_parser import validate_link_import_url_lines
from app.services.task_effectiveness import (
    batch_task_effectiveness_categories,
    classify_task_effectiveness,
    effective_sql_condition,
    high_value_sql_condition,
    ineffective_sql_condition,
    is_high_value_task,
    low_value_result_sql_condition,
    no_result_sql_condition,
)
from app.services.task_retention import (
    batch_task_has_retention_traces,
    dispose_collection_task,
    task_has_obvious_retention,
)
from app.services.task_run_progress import STAGE_FAILED
from app.schemas.common import PaginatedResponse


class CollectionTaskService:
    TEST_HISTORY_NAME_RE = re.compile(
        r"(test|测试|验收|seed-discovery-tiktok|ins采集|ltk-import|demo)",
        re.I,
    )

    @staticmethod
    def task_duplicate_key(task: CollectionTask) -> tuple:
        keywords = tuple(sorted(str(item).strip().lower() for item in (task.keywords or []) if str(item).strip()))
        platforms = tuple(sorted(str(item).strip().lower() for item in (task.platforms or []) if str(item).strip()))
        return (
            (task.name or "").strip().lower(),
            task.collection_mode,
            task.platform,
            platforms,
            keywords,
            task.product_id,
        )

    @staticmethod
    def is_test_or_history_task(task: CollectionTask) -> bool:
        if CollectionTaskService.TEST_HISTORY_NAME_RE.search(task.name or ""):
            return True
        checkpoint = task.run_checkpoint if isinstance(task.run_checkpoint, dict) else {}
        if checkpoint.get("link_import_source") is True or checkpoint.get("legacy_link_import_batch") is True:
            return True
        created_at = CollectionTaskService._as_aware_utc(task.created_at)
        old_no_result = (
            task.status in {CollectionTaskStatus.FAILED.value, CollectionTaskStatus.COMPLETED_NO_RESULTS.value}
            and (task.result_count or 0) == 0
            and (task.inserted_count or 0) == 0
            and created_at is not None
            and datetime.now(UTC) - created_at > timedelta(days=14)
        )
        return old_no_result

    @staticmethod
    def management_tags_for_task(task: CollectionTask, *, duplicate: bool = False) -> list[str]:
        tags: list[str] = []
        if CollectionTaskService.TEST_HISTORY_NAME_RE.search(task.name or ""):
            tags.append("test_task")
        checkpoint = task.run_checkpoint if isinstance(task.run_checkpoint, dict) else {}
        if checkpoint.get("link_import_source") is True or checkpoint.get("legacy_link_import_batch") is True:
            tags.append("history_batch")
        category = classify_task_effectiveness(task)
        if category == "high_value":
            tags.append("high_value")
        if category == "no_result":
            tags.append("no_result")
        if category == "failed":
            tags.append("failed")
        if duplicate:
            tags.append("possible_duplicate")
        if task.is_archived:
            tags.append("archived")
        elif CollectionTaskService.is_test_or_history_task(task) or category not in {"high_value", "effective"}:
            tags.append("archivable")
        return list(dict.fromkeys(tags))

    @staticmethod
    def _as_aware_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    async def count_active_running_tasks(
        db: AsyncSession,
        *,
        exclude_id: int | None = None,
    ) -> int:
        from app.services.collection_runner import CollectionRunnerService

        await CollectionRunnerService.reconcile_in_process_runs(db)
        result = await db.execute(
            select(CollectionTask).where(CollectionTask.status == CollectionTaskStatus.RUNNING.value)
        )
        count = 0
        for task in result.scalars():
            if exclude_id is not None and task.id == exclude_id:
                continue
            if not CollectionTaskService.is_running_stale(task):
                count += 1
        return count

    @staticmethod
    async def get_blocking_running_task(
        db: AsyncSession,
        *,
        exclude_id: int | None = None,
    ) -> CollectionTask | None:
        """Return a running task when concurrent run capacity is exhausted."""
        from app.services.collection_runner import CollectionRunnerService

        await CollectionRunnerService.reconcile_in_process_runs(db)
        capacity = max(1, settings.collection_max_running_tasks)
        result = await db.execute(
            select(CollectionTask).where(CollectionTask.status == CollectionTaskStatus.RUNNING.value)
        )
        active: list[CollectionTask] = []
        for task in result.scalars():
            if exclude_id is not None and task.id == exclude_id:
                continue
            if not CollectionTaskService.is_running_stale(task):
                active.append(task)
        if len(active) >= capacity:
            return active[0]
        return None

    @staticmethod
    def is_running_stale(
        task: CollectionTask,
        *,
        now: datetime | None = None,
    ) -> bool:
        if task.status != CollectionTaskStatus.RUNNING.value:
            return False
        reference = (
            CollectionTaskService._as_aware_utc(task.updated_at)
            or CollectionTaskService._as_aware_utc(task.created_at)
        )
        if reference is None:
            return False
        threshold_seconds = max(settings.collection_running_stale_seconds, 0)
        current = now.astimezone(UTC) if now and now.tzinfo else (now.replace(tzinfo=UTC) if now else datetime.now(UTC))
        return current - reference > timedelta(seconds=threshold_seconds)

    @staticmethod
    def task_read(
        task: CollectionTask,
        *,
        has_retention_traces: bool | None = None,
        effectiveness_category: str | None = None,
        management_tags: list[str] | None = None,
        is_possible_duplicate: bool = False,
        child_tasks: list[dict] | None = None,
        aggregate_update: dict | None = None,
    ) -> CollectionTaskRead:
        stale = CollectionTaskService.is_running_stale(task)
        retention = (
            has_retention_traces
            if has_retention_traces is not None
            else task_has_obvious_retention(task)
        )
        category = effectiveness_category or classify_task_effectiveness(task)
        running = task.status == CollectionTaskStatus.RUNNING.value
        checkpoint = task.run_checkpoint if isinstance(task.run_checkpoint, dict) else {}
        interrupted = bool(checkpoint.get("interrupted"))
        terminal_success = task.status in {
            CollectionTaskStatus.COMPLETED.value,
            CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
            CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
        }
        update = {
                "stale": stale,
                "recoverable": (not terminal_success)
                and (
                    task.status == CollectionTaskStatus.PARTIAL_FAILED.value
                    or running
                )
                and (stale or interrupted),
                "stale_after_seconds": max(settings.collection_running_stale_seconds, 0),
                "effectiveness_category": category,
                "is_ineffective": (not running) and category not in {"high_value", "effective"},
                "has_retention_traces": retention,
                "management_tags": management_tags
                if management_tags is not None
                else CollectionTaskService.management_tags_for_task(
                    task,
                    duplicate=is_possible_duplicate,
                ),
                "is_possible_duplicate": is_possible_duplicate,
                "child_tasks": child_tasks or [],
        }
        if aggregate_update:
            update.update(aggregate_update)
        return CollectionTaskRead.model_validate(task).model_copy(update=update)

    @staticmethod
    def _is_batch_parent(task: CollectionTask) -> bool:
        return bool(
            getattr(task, "batch_group_id", None)
            and getattr(task, "batch_round_count", None)
            and getattr(task, "parent_task_id", None) is None
        )

    @staticmethod
    def _batch_child_summary(child: CollectionTask) -> dict:
        return {
            "id": child.id,
            "name": child.name,
            "status": child.status,
            "batch_round_index": child.batch_round_index,
            "batch_round_count": child.batch_round_count,
            "keywords": child.keywords or [],
            "discovery_limit": child.discovery_limit,
            "inserted_count": child.inserted_count or 0,
            "result_count": child.result_count or 0,
            "deduped_count": child.deduped_count or 0,
            "failed_count": child.failed_count or 0,
            "skipped_count": child.skipped_count or 0,
            "last_run_at": child.last_run_at,
            "status_summary": child.status_summary,
            "error_message": child.error_message,
        }

    @staticmethod
    def _batch_parent_aggregate(parent: CollectionTask, children: list[CollectionTask]) -> dict:
        if not children:
            return {}
        status_values = [child.status for child in children]
        terminal_statuses = {
            CollectionTaskStatus.COMPLETED.value,
            CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
            CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
            CollectionTaskStatus.PARTIAL_FAILED.value,
            CollectionTaskStatus.FAILED.value,
        }
        if any(status == CollectionTaskStatus.RUNNING.value for status in status_values):
            status_value = CollectionTaskStatus.RUNNING.value
        elif any(status == CollectionTaskStatus.QUEUED.value for status in status_values):
            status_value = CollectionTaskStatus.QUEUED.value
        elif all(status in terminal_statuses for status in status_values) and any(
            status in {CollectionTaskStatus.FAILED.value, CollectionTaskStatus.PARTIAL_FAILED.value}
            for status in status_values
        ):
            status_value = CollectionTaskStatus.PARTIAL_FAILED.value
        elif all(status in {
            CollectionTaskStatus.COMPLETED.value,
            CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
            CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
        } for status in status_values):
            status_value = (
                CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
                if sum(child.inserted_count or 0 for child in children) > 0
                else CollectionTaskStatus.COMPLETED_NO_RESULTS.value
            )
        else:
            status_value = parent.status
        running_child = next(
            (
                child
                for child in children
                if child.status == CollectionTaskStatus.RUNNING.value
            ),
            None,
        )
        terminal = all(status in terminal_statuses for status in status_values)
        current_stage = (
            "batch_completed"
            if terminal
            else running_child.current_stage if running_child else None
        )
        clear_error = status_value in {
            CollectionTaskStatus.RUNNING.value,
            CollectionTaskStatus.QUEUED.value,
        }
        return {
            "status": status_value,
            "discovery_limit": parent.discovery_limit
            or sum(child.discovery_limit or 0 for child in children),
            "result_count": sum(child.result_count or 0 for child in children),
            "inserted_count": sum(child.inserted_count or 0 for child in children),
            "deduped_count": sum(child.deduped_count or 0 for child in children),
            "discovered_count": sum(child.discovered_count or 0 for child in children),
            "profile_fetched_count": sum(child.profile_fetched_count or 0 for child in children),
            "profile_failed_count": sum(child.profile_failed_count or 0 for child in children),
            "filtered_out_count": sum(child.filtered_out_count or 0 for child in children),
            "failed_count": sum(child.failed_count or 0 for child in children),
            "skipped_count": sum(child.skipped_count or 0 for child in children),
            "current_stage": current_stage,
            "status_summary": CollectionTaskService._batch_parent_status_summary(parent, children),
            "error_message": None if clear_error else parent.error_message,
            "last_error": None if clear_error else parent.last_error,
            "last_run_at": max(
                (child.last_run_at for child in children if child.last_run_at),
                default=parent.last_run_at,
            ),
        }

    @staticmethod
    def _batch_parent_status_summary(parent: CollectionTask, children: list[CollectionTask]) -> str:
        completed = sum(
            1
            for child in children
            if child.status in {
                CollectionTaskStatus.COMPLETED.value,
                CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
                CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
            }
        )
        failed = sum(
            1
            for child in children
            if child.status in {CollectionTaskStatus.FAILED.value, CollectionTaskStatus.PARTIAL_FAILED.value}
        )
        skipped = sum(child.skipped_count or 0 for child in children)
        running_child = next(
            (
                child
                for child in children
                if child.status in {CollectionTaskStatus.RUNNING.value, CollectionTaskStatus.QUEUED.value}
            ),
            None,
        )
        current_round = running_child.batch_round_index if running_child else min(
            len(children),
            completed + failed + 1,
        )
        inserted = sum(child.inserted_count or 0 for child in children)
        total = parent.discovery_limit or sum(child.discovery_limit or 0 for child in children)
        return (
            f"多轮采集：第 {current_round}/{parent.batch_round_count or len(children)} 轮，"
            f"已入库 {inserted}/{total}，成功 {completed} 轮，失败 {failed} 轮，跳过 {skipped}"
        )

    @staticmethod
    def _serialize_task_data(data: dict) -> dict:
        for field in (
            "batch_round_enabled",
            "batch_total_limit",
            "batch_round_size",
            "batch_round_count",
        ):
            data.pop(field, None)
        if "status" in data and data["status"] is not None:
            data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
        if "collection_mode" in data and data["collection_mode"] is not None:
            mode = data["collection_mode"]
            data["collection_mode"] = mode.value if hasattr(mode, "value") else mode
        if "email_recipients" in data and data["email_recipients"] is not None:
            data["email_recipients"] = [str(email) for email in data["email_recipients"]]
        return data

    @staticmethod
    def _apply_high_value_first_defaults(payload: dict, fields_set: set[str]) -> dict:
        mode = payload.get("collection_mode")
        mode_value = mode.value if isinstance(mode, CollectionMode) else mode
        high_value_modes = {item.value for item in HIGH_VALUE_FIRST_MODES}
        if mode_value not in high_value_modes:
            return payload
        if "min_followers_count" not in fields_set:
            payload["min_followers_count"] = HIGH_VALUE_FIRST_MIN_FOLLOWERS
        if "min_engagement_rate" not in fields_set:
            payload["min_engagement_rate"] = None
        if "require_email" not in fields_set:
            payload["require_email"] = False
        if "require_contact" not in fields_set:
            payload["require_contact"] = False
        if "strict_quality_filter" not in fields_set:
            payload["strict_quality_filter"] = False
        if "insert_qualified_only" not in fields_set:
            payload["insert_qualified_only"] = True
        if "export_qualified_only" not in fields_set:
            payload["export_qualified_only"] = True
        checkpoint = dict(payload.get("run_checkpoint") or {})
        checkpoint.setdefault("quality_strategy", "high_value_first")
        payload["run_checkpoint"] = checkpoint
        return payload

    @staticmethod
    def _apply_stable_collection_defaults(payload: dict) -> dict:
        stable = bool(payload.pop("stable_collection_mode", False))
        if not stable:
            return payload
        platforms = [
            str(item).strip().lower()
            for item in (payload.get("platforms") or [])
            if str(item).strip()
        ]
        keyword_platforms = {"youtube", "facebook", "tiktok", "instagram"}
        primary = next((platform for platform in platforms if platform in keyword_platforms), None)
        if primary is None:
            platform = str(payload.get("platform") or "").strip().lower()
            primary = platform if platform in keyword_platforms else "youtube"
        payload["platform"] = primary
        payload["platforms"] = [primary]
        payload["discovery_limit"] = 20
        payload["require_email"] = False
        payload["require_contact"] = False
        payload["strict_quality_filter"] = False
        payload["insert_qualified_only"] = False
        payload["export_qualified_only"] = False
        checkpoint = dict(payload.get("run_checkpoint") or {})
        checkpoint["stable_collection_mode"] = True
        checkpoint["stable_collection_strategy"] = {
            "target": 20,
            "single_platform": primary,
            "require_email": False,
            "require_contact": False,
            "strict_quality_filter": False,
            "insert_qualified_only": False,
        }
        payload["run_checkpoint"] = checkpoint
        return payload

    @staticmethod
    def _validate_task_inputs(
        collection_mode: str,
        keywords: list[str],
        input_urls: list[str],
        email_enabled: bool,
        email_recipients: list,
        *,
        category: str | None = None,
    ) -> None:
        keywords = [k.strip() for k in keywords if k and str(k).strip()]
        input_urls = [u.strip() for u in input_urls if u and str(u).strip()]

        mode_value = (
            collection_mode.value
            if isinstance(collection_mode, CollectionMode)
            else collection_mode
        )

        if mode_value in (CollectionMode.KEYWORD.value, CollectionMode.DISCOVERY.value) and not keywords:
            raise ValueError("关键词采集模式至少需要一个关键词")
        if mode_value == CollectionMode.CATEGORY_DISCOVERY.value and not (category or "").strip():
            raise ValueError("类目采集模式必须填写类目")
        if mode_value == CollectionMode.LINK_IMPORT.value and not input_urls:
            raise ValueError("链接导入模式至少需要一个有效链接")
        if (
            mode_value == CollectionMode.LINK_SEED_DISCOVERY.value
            and not keywords
            and not input_urls
            and not (category or "").strip()
        ):
            raise ValueError("导购 seed 自动发现需填写关键词或类目")
        if mode_value in (CollectionMode.URLS.value, CollectionMode.CLUSTERING.value) and not input_urls:
            raise ValueError("链接采集模式至少需要一个主页链接")
        if mode_value == CollectionMode.MIXED.value and not keywords and not input_urls:
            raise ValueError("混合模式需要填写关键词或链接至少一项")
        if mode_value == CollectionMode.COMPETITOR_PRODUCT.value and not keywords and not input_urls:
            raise ValueError("竞品商品发现需填写 Amazon 链接、ASIN 或商品关键词")
        if email_enabled and not email_recipients:
            raise ValueError("启用邮件发送时请填写收件人邮箱")

    @staticmethod
    def _apply_filters(query, filters: CollectionTaskFilter):
        query = query.where(CollectionTask.parent_task_id.is_(None))
        if filters.task_view == "archived":
            query = query.where(CollectionTask.is_archived.is_(True))
        else:
            query = query.where(CollectionTask.is_archived.is_(False))
        if filters.product_id:
            query = query.where(CollectionTask.product_id == filters.product_id)
        if filters.owner_scope != "all" or not filters.owner_is_admin:
            query = query.where(CollectionTask.user_id == filters.owner_user_id)
        if filters.platform:
            query = query.where(CollectionTask.platform == filters.platform)
        if filters.status:
            query = query.where(CollectionTask.status == filters.status.value)
        if filters.search:
            term = f"%{filters.search}%"
            query = query.where(or_(CollectionTask.name.ilike(term), CollectionTask.category.ilike(term)))
        effective_filter = filters.effectiveness
        if filters.task_view in {"high_value", "effective", "ineffective", "low_value_result", "no_result"}:
            effective_filter = filters.task_view
        if effective_filter == "ineffective":
            query = query.where(ineffective_sql_condition())
        elif effective_filter == "high_value":
            query = query.where(high_value_sql_condition())
        elif effective_filter == "effective":
            query = query.where(effective_sql_condition())
        elif effective_filter == "low_value_result":
            query = query.where(low_value_result_sql_condition())
        elif effective_filter == "no_result":
            query = query.where(no_result_sql_condition())
        if filters.task_view == "test_history":
            query = query.where(
                or_(
                    CollectionTask.name.ilike("%test%"),
                    CollectionTask.name.ilike("%测试%"),
                    CollectionTask.name.ilike("%验收%"),
                    CollectionTask.name.ilike("%seed-discovery-tiktok%"),
                    CollectionTask.name.ilike("%ins采集%"),
                    CollectionTask.name.ilike("%ltk-import%"),
                    CollectionTask.name.ilike("%demo%"),
                    CollectionTask.run_checkpoint.contains({"link_import_source": True}),
                    CollectionTask.run_checkpoint.contains({"legacy_link_import_batch": True}),
                )
            )
        return query

    @staticmethod
    async def _duplicate_ids_for_rows(
        db: AsyncSession,
        rows: list[CollectionTask],
        *,
        product_id: int | None,
        owner_user_id: int | None = None,
        owner_scope: str = "mine",
        owner_is_admin: bool = False,
    ) -> set[int]:
        if not rows:
            return set()
        query = select(CollectionTask).where(CollectionTask.is_archived.is_(False))
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        if owner_scope != "all" or not owner_is_admin:
            query = query.where(CollectionTask.user_id == owner_user_id)
        result = await db.execute(query)
        all_rows = result.scalars().all()
        counts: dict[tuple, int] = {}
        for task in all_rows:
            key = CollectionTaskService.task_duplicate_key(task)
            counts[key] = counts.get(key, 0) + 1
        return {
            task.id
            for task in rows
            if counts.get(CollectionTaskService.task_duplicate_key(task), 0) > 1
        }

    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        filters: CollectionTaskFilter,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[CollectionTaskRead]:
        base_query = select(CollectionTask)
        base_query = CollectionTaskService._apply_filters(base_query, filters)

        total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
        total = total or 0

        query = base_query.order_by(CollectionTask.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        rows = result.scalars().all()
        child_rows_by_parent: dict[int, list[CollectionTask]] = {}
        parent_ids = [row.id for row in rows if CollectionTaskService._is_batch_parent(row)]
        if parent_ids:
            child_result = await db.execute(
                select(CollectionTask)
                .where(CollectionTask.parent_task_id.in_(parent_ids))
                .order_by(CollectionTask.batch_round_index.asc(), CollectionTask.id.asc())
            )
            for child in child_result.scalars().all():
                if child.parent_task_id is not None:
                    child_rows_by_parent.setdefault(child.parent_task_id, []).append(child)
        duplicate_ids = await CollectionTaskService._duplicate_ids_for_rows(
            db,
            rows,
            product_id=filters.product_id,
            owner_user_id=filters.owner_user_id,
            owner_scope=filters.owner_scope,
            owner_is_admin=filters.owner_is_admin,
        )
        retention_flags = await batch_task_has_retention_traces(
            db,
            [row.id for row in rows],
            tasks=rows,
        )
        categories = await batch_task_effectiveness_categories(db, rows)
        items = [
            CollectionTaskService.task_read(
                row,
                has_retention_traces=retention_flags.get(row.id, False),
                effectiveness_category=categories.get(row.id, "no_result"),
                is_possible_duplicate=row.id in duplicate_ids,
                child_tasks=[
                    CollectionTaskService._batch_child_summary(child)
                    for child in child_rows_by_parent.get(row.id, [])
                ],
                aggregate_update=CollectionTaskService._batch_parent_aggregate(
                    row,
                    child_rows_by_parent.get(row.id, []),
                )
                if CollectionTaskService._is_batch_parent(row)
                else None,
            )
            for row in rows
        ]

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def get_task(db: AsyncSession, task_id: int) -> CollectionTask | None:
        task = await db.get(CollectionTask, task_id)
        if task and task.is_archived:
            return None
        return task

    @staticmethod
    async def get_task_including_archived(db: AsyncSession, task_id: int) -> CollectionTask | None:
        """读取任务（含已归档），供候选池查询/导出等追溯场景使用。"""
        return await db.get(CollectionTask, task_id)

    @staticmethod
    async def get_batch_children(db: AsyncSession, parent_task_id: int) -> list[CollectionTask]:
        result = await db.execute(
            select(CollectionTask)
            .where(CollectionTask.parent_task_id == parent_task_id)
            .where(CollectionTask.is_archived.is_(False))
            .order_by(CollectionTask.batch_round_index.asc(), CollectionTask.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    def _batch_terminal_statuses() -> set[str]:
        return {
            CollectionTaskStatus.COMPLETED.value,
            CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
            CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
            CollectionTaskStatus.PARTIAL_FAILED.value,
            CollectionTaskStatus.FAILED.value,
        }

    @staticmethod
    async def next_batch_child_to_run(db: AsyncSession, parent_task_id: int) -> CollectionTask | None:
        terminal = CollectionTaskService._batch_terminal_statuses()
        children = await CollectionTaskService.get_batch_children(db, parent_task_id)
        for child in children:
            if child.status == CollectionTaskStatus.RUNNING.value and CollectionTaskService.is_running_stale(child):
                has_results = (child.inserted_count or 0) > 0 or (child.result_count or 0) > 0
                child.status = (
                    CollectionTaskStatus.PARTIAL_FAILED.value
                    if has_results
                    else CollectionTaskStatus.FAILED.value
                )
                reason = "Batch round timed out or became unstable before the parent continued."
                child.last_error = reason
                child.error_message = reason
                child.status_summary = reason
                child.current_stage = STAGE_FAILED
        await db.commit()
        for child in children:
            if child.status not in terminal and child.status != CollectionTaskStatus.RUNNING.value:
                return child
        return None

    @staticmethod
    async def refresh_batch_parent_state(db: AsyncSession, parent: CollectionTask) -> CollectionTask:
        children = await CollectionTaskService.get_batch_children(db, parent.id)
        aggregate = CollectionTaskService._batch_parent_aggregate(parent, children)
        for field, value in aggregate.items():
            setattr(parent, field, value)
        checkpoint = dict(parent.run_checkpoint or {})
        running_child = next(
            (
                child
                for child in children
                if child.status in {CollectionTaskStatus.RUNNING.value, CollectionTaskStatus.QUEUED.value}
            ),
            None,
        )
        if running_child:
            checkpoint["batch_current_round"] = running_child.batch_round_index
        elif children:
            terminal_count = sum(
                1 for child in children if child.status in CollectionTaskService._batch_terminal_statuses()
            )
            checkpoint["batch_current_round"] = min(len(children), terminal_count + 1)
        checkpoint["batch_completed_rounds"] = sum(
            1
            for child in children
            if child.status in {
                CollectionTaskStatus.COMPLETED.value,
                CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
                CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
            }
        )
        checkpoint["batch_failed_rounds"] = sum(
            1
            for child in children
            if child.status in {CollectionTaskStatus.FAILED.value, CollectionTaskStatus.PARTIAL_FAILED.value}
        )
        parent.run_checkpoint = checkpoint
        await db.commit()
        await db.refresh(parent)
        return parent

    @staticmethod
    async def create_task(
        db: AsyncSession,
        data: CollectionTaskCreate,
        *,
        user_id: int | None = None,
        workspace_id: int | None = None,
        product_id: int | None = None,
    ) -> CollectionTask:
        if data.batch_round_enabled:
            return await CollectionTaskService.create_batch_task(
                db,
                data,
                user_id=user_id,
                workspace_id=workspace_id,
                product_id=product_id,
            )
        payload = CollectionTaskService._serialize_task_data(data.model_dump())
        payload = CollectionTaskService._apply_high_value_first_defaults(
            payload,
            set(data.model_fields_set),
        )
        payload = CollectionTaskService._apply_stable_collection_defaults(payload)
        if user_id is not None:
            payload["user_id"] = user_id
        if workspace_id is not None:
            payload["workspace_id"] = workspace_id
        if product_id is not None:
            payload["product_id"] = product_id
        task = CollectionTask(**payload)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def create_batch_task(
        db: AsyncSession,
        data: CollectionTaskCreate,
        *,
        user_id: int | None = None,
        workspace_id: int | None = None,
        product_id: int | None = None,
    ) -> CollectionTask:
        round_size = int(data.batch_round_size or data.discovery_limit or 50)
        total_limit = int(data.batch_total_limit or data.discovery_limit or round_size)
        round_count = int(data.batch_round_count or math.ceil(total_limit / round_size))
        base_payload = CollectionTaskService._serialize_task_data(data.model_dump())
        base_payload = CollectionTaskService._apply_high_value_first_defaults(
            base_payload,
            set(data.model_fields_set),
        )
        base_payload = CollectionTaskService._apply_stable_collection_defaults(base_payload)
        if user_id is not None:
            base_payload["user_id"] = user_id
        if workspace_id is not None:
            base_payload["workspace_id"] = workspace_id
        if product_id is not None:
            base_payload["product_id"] = product_id

        batch_group_id = uuid.uuid4().hex
        parent_payload = {
            **base_payload,
            "discovery_limit": total_limit,
            "batch_group_id": batch_group_id,
            "batch_round_index": None,
            "batch_round_count": round_count,
            "status": CollectionTaskStatus.DRAFT.value,
        }
        checkpoint = dict(parent_payload.get("run_checkpoint") or {})
        checkpoint["batch_round_parent"] = True
        checkpoint["batch_total_limit"] = total_limit
        checkpoint["batch_round_size"] = round_size
        parent_payload["run_checkpoint"] = checkpoint

        parent = CollectionTask(**parent_payload)
        db.add(parent)
        await db.flush()

        for index in range(1, round_count + 1):
            remaining = max(total_limit - ((index - 1) * round_size), 0)
            current_round_limit = min(round_size, remaining) if remaining else round_size
            child_payload = {
                **base_payload,
                "name": f"{data.name} - 第{index}轮",
                "keywords": list(base_payload.get("keywords") or []),
                "discovery_limit": current_round_limit,
                "parent_task_id": parent.id,
                "batch_group_id": batch_group_id,
                "batch_round_index": index,
                "batch_round_count": round_count,
                "status": CollectionTaskStatus.DRAFT.value,
            }
            child_checkpoint = dict(child_payload.get("run_checkpoint") or {})
            child_checkpoint["batch_group_id"] = batch_group_id
            child_checkpoint["batch_round_index"] = index
            child_checkpoint["batch_round_count"] = round_count
            child_checkpoint["batch_parent_task_id"] = parent.id
            child_payload["run_checkpoint"] = child_checkpoint
            db.add(CollectionTask(**child_payload))

        await db.commit()
        await db.refresh(parent)
        return parent

    @staticmethod
    async def update_task(
        db: AsyncSession,
        task: CollectionTask,
        data: CollectionTaskUpdate,
    ) -> CollectionTask:
        raw_update_data = data.model_dump(exclude_unset=True)
        batch_fields_present = any(
            field in raw_update_data
            for field in (
                "batch_round_enabled",
                "batch_total_limit",
                "batch_round_size",
                "batch_round_count",
            )
        )
        batch_round_enabled = raw_update_data.get("batch_round_enabled")
        update_data = CollectionTaskService._serialize_task_data(dict(raw_update_data))

        merged_mode = update_data.get("collection_mode", task.collection_mode)
        merged_keywords = update_data.get("keywords", task.keywords or [])
        merged_urls = update_data.get("input_urls", task.input_urls or [])
        merged_category = update_data.get("category", task.category)
        merged_email_enabled = update_data.get("email_enabled", task.email_enabled)
        merged_recipients = update_data.get("email_recipients", task.email_recipients or [])

        merged_mode_value = (
            merged_mode.value if isinstance(merged_mode, CollectionMode) else merged_mode
        )
        merged_platform = update_data.get("platform", task.platform)
        merged_platforms = update_data.get("platforms", task.platforms or [])
        if any(key in update_data for key in ("collection_mode", "platform", "platforms")):
            mode = merged_mode if isinstance(merged_mode, CollectionMode) else CollectionMode(merged_mode_value)
            validate_seed_only_discovery_mode(
                mode,
                str(merged_platform or ""),
                list(merged_platforms or []),
            )
            validate_url_only_platforms_for_mode(
                mode,
                str(merged_platform or ""),
                list(merged_platforms or []),
            )
        if any(
            key in update_data
            for key in (
                "collection_mode",
                "keywords",
                "input_urls",
                "category",
                "email_enabled",
                "email_recipients",
            )
        ):
            CollectionTaskService._validate_task_inputs(
                merged_mode,
                merged_keywords,
                merged_urls,
                merged_email_enabled,
                merged_recipients,
                category=merged_category,
            )

        if merged_mode_value == CollectionMode.LINK_IMPORT.value and (
            "input_urls" in update_data or "collection_mode" in update_data
        ):
            valid = validate_link_import_url_lines(merged_urls)
            update_data.update(build_link_import_task_fields(valid))
            merged_keywords = update_data.get("keywords", merged_keywords)
            merged_mode = update_data.get("collection_mode", merged_mode)
            merged_mode_value = (
                merged_mode.value if isinstance(merged_mode, CollectionMode) else merged_mode
            )

        if merged_mode_value == CollectionMode.COMPETITOR_PRODUCT.value:
            update_data["comment_discovery_enabled"] = False

        if batch_fields_present and task.parent_task_id is not None:
            raise ValueError("Batch round settings can only be changed on the parent task.")

        if batch_fields_present and (
            batch_round_enabled is True
            or (batch_round_enabled is None and CollectionTaskService._is_batch_parent(task))
        ):
            await CollectionTaskService._ensure_batch_parent_can_be_rebuilt(db, task)
            round_size = int(
                raw_update_data.get("batch_round_size")
                or (task.run_checkpoint or {}).get("batch_round_size")
                or await CollectionTaskService._first_batch_child_limit(db, task.id)
                or task.discovery_limit
                or 50
            )
            total_limit = int(
                raw_update_data.get("batch_total_limit")
                or update_data.get("discovery_limit")
                or task.discovery_limit
                or round_size
            )
            round_count = math.ceil(total_limit / round_size)
            update_data["discovery_limit"] = total_limit

        for field, value in update_data.items():
            setattr(task, field, value)
        if batch_fields_present and batch_round_enabled is False and CollectionTaskService._is_batch_parent(task):
            await CollectionTaskService._ensure_batch_parent_can_be_rebuilt(db, task)
            await CollectionTaskService._delete_batch_children(db, task.id)
            task.batch_round_count = None
            task.batch_group_id = None
            task.run_checkpoint = {
                key: value
                for key, value in dict(task.run_checkpoint or {}).items()
                if not key.startswith("batch_")
            }
        elif batch_fields_present and (
            batch_round_enabled is True
            or (batch_round_enabled is None and CollectionTaskService._is_batch_parent(task))
        ):
            task.batch_round_count = round_count
            task.batch_round_index = None
            task.batch_group_id = task.batch_group_id or uuid.uuid4().hex
            checkpoint = dict(task.run_checkpoint or {})
            checkpoint["batch_round_parent"] = True
            checkpoint["batch_total_limit"] = total_limit
            checkpoint["batch_round_size"] = round_size
            task.run_checkpoint = checkpoint
            await db.flush()
            await CollectionTaskService._rebuild_batch_children(db, task, round_size, total_limit, round_count)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def _first_batch_child_limit(db: AsyncSession, parent_task_id: int) -> int | None:
        children = await CollectionTaskService.get_batch_children(db, parent_task_id)
        if not children:
            return None
        return children[0].discovery_limit

    @staticmethod
    async def _ensure_batch_parent_can_be_rebuilt(db: AsyncSession, task: CollectionTask) -> None:
        if task.status != CollectionTaskStatus.DRAFT.value:
            raise ValueError("Batch round settings cannot be changed after the parent task has started.")
        children = await CollectionTaskService.get_batch_children(db, task.id)
        if any(child.status != CollectionTaskStatus.DRAFT.value for child in children):
            raise ValueError("Batch round settings cannot be changed after any child round has started.")

    @staticmethod
    async def _delete_batch_children(db: AsyncSession, parent_task_id: int) -> None:
        children = await CollectionTaskService.get_batch_children(db, parent_task_id)
        for child in children:
            await db.delete(child)
        await db.flush()

    @staticmethod
    async def _rebuild_batch_children(
        db: AsyncSession,
        parent: CollectionTask,
        round_size: int,
        total_limit: int,
        round_count: int,
    ) -> None:
        await CollectionTaskService._delete_batch_children(db, parent.id)
        base_payload = {
            "user_id": parent.user_id,
            "workspace_id": parent.workspace_id,
            "product_id": parent.product_id,
            "collection_mode": parent.collection_mode,
            "platform": parent.platform,
            "platforms": list(parent.platforms or []),
            "keywords": list(parent.keywords or []),
            "input_urls": list(parent.input_urls or []),
            "country": parent.country,
            "category": parent.category,
            "min_engagement_rate": parent.min_engagement_rate,
            "min_followers_count": parent.min_followers_count,
            "max_followers_count": parent.max_followers_count,
            "filter_include_keywords": list(parent.filter_include_keywords or []),
            "filter_exclude_keywords": list(parent.filter_exclude_keywords or []),
            "require_email": parent.require_email,
            "require_contact": parent.require_contact,
            "strict_quality_filter": parent.strict_quality_filter,
            "insert_qualified_only": parent.insert_qualified_only,
            "export_qualified_only": parent.export_qualified_only,
            "comment_discovery_enabled": parent.comment_discovery_enabled,
            "schedule_enabled": parent.schedule_enabled,
            "schedule_cron": parent.schedule_cron,
            "email_enabled": parent.email_enabled,
            "email_recipients": list(parent.email_recipients or []),
            "outreach_enabled": parent.outreach_enabled,
            "outreach_provider": parent.outreach_provider,
            "outreach_dry_run": parent.outreach_dry_run,
            "outreach_templates": dict(parent.outreach_templates or {}),
        }
        for index in range(1, round_count + 1):
            remaining = max(total_limit - ((index - 1) * round_size), 0)
            current_round_limit = min(round_size, remaining) if remaining else round_size
            child_checkpoint = dict(parent.run_checkpoint or {})
            child_checkpoint["batch_group_id"] = parent.batch_group_id
            child_checkpoint["batch_round_index"] = index
            child_checkpoint["batch_round_count"] = round_count
            child_checkpoint["batch_parent_task_id"] = parent.id
            db.add(
                CollectionTask(
                    **base_payload,
                    name=f"{parent.name} - 第{index}轮",
                    discovery_limit=current_round_limit,
                    parent_task_id=parent.id,
                    batch_group_id=parent.batch_group_id,
                    batch_round_index=index,
                    batch_round_count=round_count,
                    status=CollectionTaskStatus.DRAFT.value,
                    run_checkpoint=child_checkpoint,
                )
            )
        await db.flush()

    @staticmethod
    async def dispose_task(
        db: AsyncSession,
        task: CollectionTask,
        *,
        require_ineffective: bool = True,
    ) -> str:
        action, reason = await dispose_collection_task(
            db, task, require_ineffective=require_ineffective
        )
        if action == "skipped":
            raise ValueError(reason or "无法删除该任务")
        await db.commit()
        return action

    @staticmethod
    async def dispose_tasks_bulk(
        db: AsyncSession,
        tasks: list[CollectionTask],
        *,
        require_ineffective: bool = True,
    ) -> dict[str, list[int]]:
        deleted_ids: list[int] = []
        archived_ids: list[int] = []
        skipped_ids: list[int] = []
        for task in tasks:
            action, _ = await dispose_collection_task(
                db, task, require_ineffective=require_ineffective
            )
            if action == "deleted":
                deleted_ids.append(task.id)
            elif action == "archived":
                archived_ids.append(task.id)
            else:
                skipped_ids.append(task.id)
        await db.commit()
        return {
            "deleted_ids": deleted_ids,
            "archived_ids": archived_ids,
            "skipped_ids": skipped_ids,
        }

    @staticmethod
    async def delete_task(db: AsyncSession, task: CollectionTask) -> str:
        return await CollectionTaskService.dispose_task(db, task, require_ineffective=True)

    @staticmethod
    async def delete_tasks_bulk(
        db: AsyncSession,
        tasks: list[CollectionTask],
        *,
        require_ineffective: bool = True,
    ) -> dict[str, list[int]]:
        return await CollectionTaskService.dispose_tasks_bulk(
            db, tasks, require_ineffective=require_ineffective
        )

    @staticmethod
    async def bulk_manage_tasks(
        db: AsyncSession,
        *,
        action: str,
        product_id: int,
        task_ids: list[int] | None = None,
        owner_user_id: int | None = None,
        owner_scope: str = "mine",
        owner_is_admin: bool = False,
    ) -> CollectionTaskBulkManageResult:
        id_filter = set(task_ids or [])
        query = select(CollectionTask).where(CollectionTask.product_id == product_id)
        if owner_scope != "all" or not owner_is_admin:
            query = query.where(CollectionTask.user_id == owner_user_id)
        if id_filter:
            query = query.where(CollectionTask.id.in_(id_filter))
        if action == "restore_archived":
            query = query.where(CollectionTask.is_archived.is_(True))
        else:
            query = query.where(CollectionTask.is_archived.is_(False))
        rows = (await db.execute(query)).scalars().all()
        categories = await batch_task_effectiveness_categories(db, rows)

        if action == "archive_test_history":
            rows = [task for task in rows if CollectionTaskService.is_test_or_history_task(task)]
        elif action == "delete_no_result":
            rows = [task for task in rows if categories.get(task.id) == "no_result"]
        elif action == "archive_duplicates":
            by_key: dict[tuple, list[CollectionTask]] = {}
            for task in rows:
                by_key.setdefault(CollectionTaskService.task_duplicate_key(task), []).append(task)
            rows = []
            for group in by_key.values():
                if len(group) <= 1:
                    continue
                high_value_group = [task for task in group if categories.get(task.id) == "high_value"]
                keeper_pool = high_value_group or group
                latest = max(
                    keeper_pool,
                    key=lambda task: (
                        task.last_run_at or task.updated_at or task.created_at or datetime.min.replace(tzinfo=UTC),
                        task.id,
                    ),
                )
                rows.extend(task for task in group if task.id != latest.id)

        result = CollectionTaskBulkManageResult(matched_count=len(rows))
        for task in rows:
            if task.status == CollectionTaskStatus.RUNNING.value:
                result.skipped_ids.append(task.id)
                result.skipped_reasons[str(task.id)] = "task_running"
                continue
            if action == "restore_archived":
                task.is_archived = False
                task.archived_at = None
                result.restored_ids.append(task.id)
                continue
            if categories.get(task.id) == "high_value" or is_high_value_task(task):
                result.skipped_ids.append(task.id)
                result.skipped_reasons[str(task.id)] = "high_value_protected"
                continue
            if action in {"archive_test_history", "archive_duplicates"}:
                task.is_archived = True
                task.archived_at = datetime.now(UTC)
                result.archived_ids.append(task.id)
                continue
            if action == "delete_no_result":
                action_taken, reason = await dispose_collection_task(db, task, require_ineffective=True)
                if action_taken == "deleted":
                    result.deleted_ids.append(task.id)
                elif action_taken == "archived":
                    result.archived_ids.append(task.id)
                else:
                    result.skipped_ids.append(task.id)
                    result.skipped_reasons[str(task.id)] = reason or "skipped"

        result.archived_count = len(result.archived_ids)
        result.deleted_count = len(result.deleted_ids)
        result.restored_count = len(result.restored_ids)
        result.skipped_count = len(result.skipped_ids)
        await db.commit()
        return result

    @staticmethod
    async def get_recent_tasks(
        db: AsyncSession,
        limit: int = 5,
        *,
        product_id: int | None = None,
    ) -> list[CollectionTaskRead]:
        query = (
            select(CollectionTask)
            .where(CollectionTask.is_archived.is_(False))
            .order_by(CollectionTask.updated_at.desc())
            .limit(limit)
        )
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        result = await db.execute(query)
        rows = result.scalars().all()
        retention_flags = await batch_task_has_retention_traces(
            db,
            [row.id for row in rows],
            tasks=rows,
        )
        return [
            CollectionTaskService.task_read(
                row,
                has_retention_traces=retention_flags.get(row.id, False),
            )
            for row in rows
        ]

    @staticmethod
    async def count_by_statuses(
        db: AsyncSession,
        statuses: list[CollectionTaskStatus],
        *,
        product_id: int | None = None,
    ) -> int:
        values = [status.value for status in statuses]
        query = (
            select(func.count())
            .select_from(CollectionTask)
            .where(CollectionTask.status.in_(values), CollectionTask.is_archived.is_(False))
        )
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        count = await db.scalar(query)
        return count or 0

    @staticmethod
    async def count_by_status(
        db: AsyncSession,
        status: CollectionTaskStatus,
        *,
        product_id: int | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(CollectionTask)
            .where(CollectionTask.status == status.value, CollectionTask.is_archived.is_(False))
        )
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        count = await db.scalar(query)
        return count or 0

    @staticmethod
    async def count_all(db: AsyncSession, *, product_id: int | None = None) -> int:
        query = select(func.count()).select_from(CollectionTask)
        if product_id is not None:
            query = query.where(CollectionTask.product_id == product_id)
        count = await db.scalar(query)
        return count or 0

    @staticmethod
    async def reconcile_stale_running_tasks(
        db: AsyncSession,
        *,
        exclude_id: int | None = None,
        exclude_ids: set[int] | None = None,
    ) -> int:
        """Mark long-idle running tasks as interrupted so the UI and mutex stay accurate."""
        from app.services.collection_runner import CollectionRunnerService

        skip_ids = set(exclude_ids or [])
        if exclude_id is not None:
            skip_ids.add(exclude_id)
        result = await db.execute(
            select(CollectionTask).where(CollectionTask.status == CollectionTaskStatus.RUNNING.value)
        )
        reconciled = 0
        threshold = max(settings.collection_running_stale_seconds, 0)
        for task in result.scalars():
            if task.id in skip_ids:
                continue
            if CollectionTaskService._is_batch_parent(task):
                continue
            if CollectionRunnerService.is_task_active_in_process(task.id):
                continue
            if not CollectionTaskService.is_running_stale(task):
                continue
            stage = task.current_stage or "unknown"
            updated = CollectionTaskService._as_aware_utc(task.updated_at)
            updated_label = updated.strftime("%Y-%m-%d %H:%M UTC") if updated else "未知"
            interrupted = (
                f"任务已超时中断（阶段：{stage}，最后更新 {updated_label}，超过 {threshold}s 无进度），"
                f"可重新运行从 checkpoint 继续"
            )
            task.status = CollectionTaskStatus.PARTIAL_FAILED.value
            task.current_stage = STAGE_FAILED
            task.status_summary = interrupted
            task.last_error = task.last_error or interrupted
            if not task.error_message:
                task.error_message = interrupted
            checkpoint = dict(task.run_checkpoint or {})
            checkpoint["interrupted"] = True
            checkpoint["interrupted_stage"] = stage
            checkpoint["interrupted_at"] = datetime.now(UTC).isoformat()
            task.run_checkpoint = checkpoint
            reconciled += 1
        if reconciled:
            await db.commit()
        return reconciled
