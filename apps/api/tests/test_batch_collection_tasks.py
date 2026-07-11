from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.api.routes.collection_tasks import _start_next_batch_child, run_collection_task
from app.core.config import settings
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionMode, CollectionTaskStatus
from app.schemas.collection_task import CollectionTaskCreate, CollectionTaskUpdate
from app.services import collection_runner as collection_runner_module
from app.services.collection_queue import CollectionQueueService
from app.services.collection_runner import CollectionRunnerService
from app.services.collection_task import CollectionTaskService


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _batch_payload(**overrides) -> CollectionTaskCreate:
    payload = {
        "name": f"batch-{uuid.uuid4().hex[:8]}",
        "collection_mode": CollectionMode.DISCOVERY,
        "platform": "youtube",
        "platforms": ["youtube"],
        "keywords": ["makeup bag", "cosmetic bag", "toiletry bag", "travel essentials"],
        "country": "US",
        "category": "beauty",
        "discovery_limit": 200,
        "min_followers_count": 5000,
        "min_engagement_rate": 1.2,
        "require_email": True,
        "require_contact": True,
        "outreach_enabled": True,
        "outreach_provider": "smtp",
        "outreach_dry_run": False,
        "outreach_templates": {"micro_subject": "Hi"},
        "batch_round_enabled": True,
        "batch_total_limit": 200,
        "batch_round_size": 50,
        "batch_round_count": 4,
    }
    payload.update(overrides)
    return CollectionTaskCreate(**payload)


def _cleanup_tasks(task_ids: list[int]):
    async def _cleanup():
        collection_runner_module._active_collection_task_ids.clear()
        async with async_session_factory() as db:
            for task_id in task_ids:
                await CollectionRunnerService._release_collection_run(task_id)
            for task_id in task_ids:
                row = await db.get(CollectionTask, task_id)
                if row:
                    await db.delete(row)
            await db.commit()

    return _cleanup()


@pytest.mark.anyio
async def test_batch_create_generates_parent_and_round_children():
    data = _batch_payload()
    created_ids: list[int] = []
    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(
            db,
            data,
            user_id=11,
            workspace_id=1,
            product_id=1,
        )
        created_ids.append(parent.id)
        rows = (
            await db.execute(
                select(CollectionTask)
                .where(CollectionTask.batch_group_id == parent.batch_group_id)
                .order_by(CollectionTask.batch_round_index.asc().nullsfirst(), CollectionTask.id.asc())
            )
        ).scalars().all()
        created_ids.extend(row.id for row in rows if row.id != parent.id)

        children = [row for row in rows if row.parent_task_id == parent.id]
        assert parent.parent_task_id is None
        assert parent.batch_round_index is None
        assert parent.batch_round_count == 4
        assert parent.discovery_limit == 200
        assert parent.status == CollectionTaskStatus.DRAFT.value
        assert len(children) == 4
        assert [child.name for child in children] == [f"{data.name} - 第{i}轮" for i in range(1, 5)]
        assert [child.discovery_limit for child in children] == [50, 50, 50, 50]
        assert [child.batch_round_index for child in children] == [1, 2, 3, 4]
        assert all(child.batch_round_count == 4 for child in children)
        assert all(child.user_id == 11 for child in children)
        assert all(child.workspace_id == 1 for child in children)
        assert all(child.product_id == 1 for child in children)
        assert all(child.platform == "youtube" and child.platforms == ["youtube"] for child in children)
        assert all(child.country == "US" and child.category == "beauty" for child in children)
        assert all(child.min_followers_count == 5000 for child in children)
        assert all(child.min_engagement_rate == 1.2 for child in children)
        assert all(child.require_email is True and child.require_contact is True for child in children)
        assert all(child.outreach_enabled is True and child.outreach_dry_run is False for child in children)
        assert all(child.outreach_templates == {"micro_subject": "Hi"} for child in children)
        assert all(child.keywords == data.keywords for child in children)
    await _cleanup_tasks(created_ids)


@pytest.mark.anyio
async def test_batch_create_calculates_rounds_and_last_round_limit():
    data = _batch_payload(
        discovery_limit=120,
        batch_total_limit=120,
        batch_round_size=50,
        batch_round_count=None,
    )
    created_ids: list[int] = []
    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=11, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        children = (
            await db.execute(
                select(CollectionTask)
                .where(CollectionTask.parent_task_id == parent.id)
                .order_by(CollectionTask.batch_round_index.asc())
            )
        ).scalars().all()
        created_ids.extend(child.id for child in children)

        assert parent.batch_round_count == 3
        assert parent.discovery_limit == 120
        assert [child.discovery_limit for child in children] == [50, 50, 20]
        assert all(child.keywords == data.keywords for child in children)
    await _cleanup_tasks(created_ids)


@pytest.mark.anyio
async def test_batch_parent_update_rebuilds_unstarted_child_rounds():
    data = _batch_payload(batch_total_limit=100, batch_round_size=50, batch_round_count=2)
    created_ids: list[int] = []
    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=11, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        original_children = await CollectionTaskService.get_batch_children(db, parent.id)
        created_ids.extend(child.id for child in original_children)

        updated = await CollectionTaskService.update_task(
            db,
            parent,
            CollectionTaskUpdate(
                name=f"{data.name}-edited",
                keywords=["edited keyword"],
                batch_round_enabled=True,
                batch_total_limit=120,
                batch_round_size=50,
                batch_round_count=1,
            ),
        )
        children = await CollectionTaskService.get_batch_children(db, updated.id)
        created_ids.extend(child.id for child in children)

        assert updated.batch_round_count == 3
        assert updated.discovery_limit == 120
        assert updated.run_checkpoint["batch_total_limit"] == 120
        assert updated.run_checkpoint["batch_round_size"] == 50
        assert len(children) == 3
        assert [child.discovery_limit for child in children] == [50, 50, 20]
        assert all(child.keywords == ["edited keyword"] for child in children)
        assert all(child.batch_round_count == 3 for child in children)
        assert not {child.id for child in original_children} & {child.id for child in children}
    await _cleanup_tasks(created_ids)


@pytest.mark.anyio
async def test_batch_parent_update_rejects_started_parent():
    data = _batch_payload(batch_total_limit=100, batch_round_size=50, batch_round_count=2)
    created_ids: list[int] = []
    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=11, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        children = await CollectionTaskService.get_batch_children(db, parent.id)
        created_ids.extend(child.id for child in children)
        parent.status = CollectionTaskStatus.RUNNING.value
        await db.commit()

        with pytest.raises(ValueError, match="cannot be changed after the parent task has started"):
            await CollectionTaskService.update_task(
                db,
                parent,
                CollectionTaskUpdate(
                    batch_round_enabled=True,
                    batch_total_limit=120,
                    batch_round_size=50,
                    batch_round_count=1,
                ),
            )
    await _cleanup_tasks(created_ids)


@pytest.mark.anyio
async def test_running_parent_batch_starts_first_pending_child(monkeypatch):
    data = _batch_payload(batch_total_limit=120, batch_round_size=50, batch_round_count=3)
    created_ids: list[int] = []
    started: list[tuple[int, bool]] = []

    async def _fake_queue_or_start(db, task, *, resume=False):
        task.status = CollectionTaskStatus.RUNNING.value
        await db.commit()
        await db.refresh(task)
        return CollectionTaskStatus.RUNNING

    async def _fake_background(task_id: int, *, resume: bool = False) -> None:
        started.append((task_id, resume))

    monkeypatch.setattr("app.api.routes.collection_tasks.CollectionQueueService.queue_or_start", _fake_queue_or_start)
    monkeypatch.setattr("app.api.routes.collection_tasks._run_collection_task_in_background", _fake_background)

    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=11, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        children = (
            await db.execute(
                select(CollectionTask)
                .where(CollectionTask.parent_task_id == parent.id)
                .order_by(CollectionTask.batch_round_index.asc())
            )
        ).scalars().all()
        created_ids.extend(child.id for child in children)

        background_tasks = BackgroundTasks()
        result = await run_collection_task(parent.id, background_tasks, db, ctx=_tenant_ctx())

        assert result.task_id == parent.id
        assert result.status == CollectionTaskStatus.RUNNING
        assert len(background_tasks.tasks) == 1
        assert children[0].status == CollectionTaskStatus.RUNNING.value
        assert started == []
        await db.refresh(parent)
        assert parent.status == CollectionTaskStatus.RUNNING.value
        assert "batch_current_round" in (parent.run_checkpoint or {})
    await _cleanup_tasks(created_ids)


@pytest.mark.anyio
async def test_parent_batch_task_run_starts_child_round(monkeypatch):
    data = _batch_payload(batch_round_count=2, batch_total_limit=20, batch_round_size=10)
    created_ids: list[int] = []
    started: list[int] = []

    async def _fake_queue_or_start(db, task, *, resume=False):
        task.status = CollectionTaskStatus.RUNNING.value
        await db.commit()
        await db.refresh(task)
        return CollectionTaskStatus.RUNNING

    async def _fake_background(task_id: int, *, resume: bool = False) -> None:
        started.append(task_id)

    monkeypatch.setattr("app.api.routes.collection_tasks.CollectionQueueService.queue_or_start", _fake_queue_or_start)
    monkeypatch.setattr("app.api.routes.collection_tasks._run_collection_task_in_background", _fake_background)

    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=11, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        children = (
            await db.execute(
                select(CollectionTask)
                .where(CollectionTask.parent_task_id == parent.id)
                .order_by(CollectionTask.batch_round_index.asc())
            )
        ).scalars().all()
        created_ids.extend(child.id for child in children)
        background_tasks = BackgroundTasks()
        result = await run_collection_task(parent.id, background_tasks, db, ctx=_tenant_ctx())
        assert result.status == CollectionTaskStatus.RUNNING
        assert len(background_tasks.tasks) == 1
        assert children[0].status == CollectionTaskStatus.RUNNING.value
        assert started == []
    await _cleanup_tasks(created_ids)


@pytest.mark.anyio
async def test_failed_batch_round_continues_to_next_round(monkeypatch):
    data = _batch_payload(batch_total_limit=30, batch_round_size=10, batch_round_count=3)
    created_ids: list[int] = []

    async def _fake_queue_or_start(db, task, *, resume=False):
        task.status = CollectionTaskStatus.RUNNING.value
        await db.commit()
        await db.refresh(task)
        return CollectionTaskStatus.RUNNING

    monkeypatch.setattr("app.api.routes.collection_tasks.CollectionQueueService.queue_or_start", _fake_queue_or_start)

    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=11, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        children = (
            await db.execute(
                select(CollectionTask)
                .where(CollectionTask.parent_task_id == parent.id)
                .order_by(CollectionTask.batch_round_index.asc())
            )
        ).scalars().all()
        created_ids.extend(child.id for child in children)

        children[0].status = CollectionTaskStatus.FAILED.value
        children[0].last_error = "provider timeout"
        children[0].status_summary = "provider timeout"
        await db.commit()

        result = await _start_next_batch_child(parent, BackgroundTasks(), db)

        assert result == CollectionTaskStatus.RUNNING
        await db.refresh(children[1])
        assert children[1].status == CollectionTaskStatus.RUNNING.value
        await db.refresh(parent)
        assert parent.status == CollectionTaskStatus.RUNNING.value
        assert parent.run_checkpoint["batch_current_round"] == 2

        children[1].status = CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
        children[1].inserted_count = 8
        children[1].result_count = 8
        children[2].status = CollectionTaskStatus.COMPLETED_NO_RESULTS.value
        await db.commit()
        await CollectionTaskService.refresh_batch_parent_state(db, parent)

        assert parent.status == CollectionTaskStatus.PARTIAL_FAILED.value
        assert parent.inserted_count == 8
        assert parent.result_count == 8
        assert parent.run_checkpoint["batch_failed_rounds"] == 1
        assert parent.run_checkpoint["batch_completed_rounds"] == 2
        assert "失败 1 轮" in (parent.status_summary or "")
    await _cleanup_tasks(created_ids)


@pytest.mark.anyio
async def test_stale_running_batch_round_is_failed_before_next_round(monkeypatch):
    data = _batch_payload(batch_total_limit=30, batch_round_size=10, batch_round_count=3)
    created_ids: list[int] = []

    async def _fake_queue_or_start(db, task, *, resume=False):
        task.status = CollectionTaskStatus.RUNNING.value
        await db.commit()
        await db.refresh(task)
        return CollectionTaskStatus.RUNNING

    monkeypatch.setattr("app.api.routes.collection_tasks.CollectionQueueService.queue_or_start", _fake_queue_or_start)

    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=11, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        children = await CollectionTaskService.get_batch_children(db, parent.id)
        created_ids.extend(child.id for child in children)

        children[0].status = CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
        children[0].inserted_count = 5
        children[1].status = CollectionTaskStatus.RUNNING.value
        children[1].updated_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()

        result = await _start_next_batch_child(parent, BackgroundTasks(), db)

        assert result == CollectionTaskStatus.RUNNING
        await db.refresh(children[1])
        await db.refresh(children[2])
        await db.refresh(parent)
        assert children[1].status == CollectionTaskStatus.FAILED.value
        assert "timed out" in (children[1].last_error or "")
        assert children[2].status == CollectionTaskStatus.RUNNING.value
        assert parent.status == CollectionTaskStatus.RUNNING.value
        assert parent.run_checkpoint["batch_current_round"] == 3
    await _cleanup_tasks(created_ids)


@pytest.mark.anyio
async def test_running_batch_parent_does_not_block_next_child_round(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 100)
    collection_runner_module._active_collection_task_ids.clear()
    data = _batch_payload(batch_total_limit=30, batch_round_size=10, batch_round_count=3)
    created_ids: list[int] = []
    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=1, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        children = await CollectionTaskService.get_batch_children(db, parent.id)
        created_ids.extend(child.id for child in children)

        parent.status = CollectionTaskStatus.RUNNING.value
        children[0].status = CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
        children[0].inserted_count = 10
        children[1].status = CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
        children[1].inserted_count = 10
        await db.commit()

        result = await CollectionQueueService.queue_or_start(db, children[2], resume=False)

        assert result == CollectionTaskStatus.RUNNING
        await db.refresh(children[2])
        assert children[2].status == CollectionTaskStatus.RUNNING.value
        assert children[2].run_checkpoint.get("queue_reasons") is None
    await _cleanup_tasks(created_ids)


def _tenant_ctx():
    from app.deps.tenant import TenantContext

    return TenantContext(
        user_id=11,
        workspace_id=1,
        product_id=1,
        is_admin=False,
    )
