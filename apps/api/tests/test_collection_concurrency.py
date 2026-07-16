"""Multi-user / multi-platform collection concurrency tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.main import app
from app.models.enums import CollectionTaskStatus
from app.services.collection_lease import CollectionLeaseService, task_platform_list
from app.services.collection_queue import (
    QUEUE_REASON_GLOBAL_FULL,
    QUEUE_REASON_PLATFORM_FULL,
    QUEUE_REASON_USER_LIMIT,
    CollectionQueueService,
)
from app.services.collection_runner import CollectionRunnerService
from app.services.collection_task import CollectionTaskService


def _task(**overrides):
    base = dict(
        id=1,
        user_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        platforms=["youtube"],
        platform="youtube",
        run_checkpoint={},
        current_stage=None,
        status_summary=None,
        error_message=None,
        last_error=None,
        batch_group_id=None,
        batch_round_count=None,
        parent_task_id=None,
        worker_id=None,
        heartbeat_at=None,
        run_started_at=None,
        updated_at=None,
        created_at=None,
        name="t",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_fairness_other_user_can_run_when_one_user_at_limit(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 10)
    monkeypatch.setattr(settings, "collection_max_concurrency_per_user", 3)
    monkeypatch.setattr(settings, "collection_max_concurrency_per_platform", 10)
    monkeypatch.setattr(
        CollectionRunnerService,
        "reconcile_in_process_runs",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(CollectionRunnerService, "has_active_collection_run", lambda: False)
    monkeypatch.setattr(CollectionRunnerService, "active_collection_run_count", lambda: 0)
    running = [
        _task(id=i, user_id=1, status=CollectionTaskStatus.RUNNING.value, platforms=["youtube"])
        for i in range(1, 4)
    ]
    other = _task(id=10, user_id=2, status=CollectionTaskStatus.DRAFT.value, platforms=["tiktok"])

    async def _run():
        db = AsyncMock()
        result = MagicMock()
        result.scalars.side_effect = lambda: iter(running)
        db.execute = AsyncMock(return_value=result)
        return await CollectionQueueService.queue_or_start(db, other, resume=False)

    status = anyio.run(_run)
    assert status == CollectionTaskStatus.RUNNING
    assert other.status == CollectionTaskStatus.RUNNING.value


def test_global_capacity_allows_more_than_one_running_task(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 10)
    monkeypatch.setattr(settings, "collection_max_concurrency_per_user", 10)
    monkeypatch.setattr(settings, "collection_max_concurrency_per_platform", 10)
    monkeypatch.setattr(
        CollectionRunnerService,
        "reconcile_in_process_runs",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(CollectionRunnerService, "has_active_collection_run", lambda: False)
    running = [
        _task(id=1, user_id=1, status=CollectionTaskStatus.RUNNING.value, platforms=["youtube"])
    ]
    second = _task(id=2, user_id=2, status=CollectionTaskStatus.DRAFT.value, platforms=["tiktok"])

    async def _run():
        db = AsyncMock()
        result = MagicMock()
        result.scalars.side_effect = lambda: iter(running)
        db.execute = AsyncMock(return_value=result)
        return await CollectionQueueService.queue_or_start(db, second, resume=False)

    status = anyio.run(_run)
    assert status == CollectionTaskStatus.RUNNING
    assert second.status == CollectionTaskStatus.RUNNING.value


def test_eleventh_task_queues_when_global_capacity_is_full(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 10)
    monkeypatch.setattr(settings, "collection_max_concurrency_per_user", 10)
    monkeypatch.setattr(settings, "collection_max_concurrency_per_platform", 10)
    monkeypatch.setattr(
        CollectionRunnerService,
        "reconcile_in_process_runs",
        AsyncMock(return_value=0),
    )
    running = [
        _task(id=i, user_id=i, status=CollectionTaskStatus.RUNNING.value, platforms=["youtube"])
        for i in range(1, 11)
    ]
    eleventh = _task(id=11, user_id=11, status=CollectionTaskStatus.DRAFT.value, platforms=["tiktok"])

    async def _run():
        db = AsyncMock()
        result = MagicMock()
        result.scalars.side_effect = lambda: iter(running)
        db.execute = AsyncMock(return_value=result)
        return await CollectionQueueService.queue_or_start(db, eleventh, resume=False)

    status = anyio.run(_run)
    assert status == CollectionTaskStatus.QUEUED
    assert eleventh.status == CollectionTaskStatus.QUEUED.value
    assert eleventh.run_checkpoint["queue_reasons"] == [QUEUE_REASON_GLOBAL_FULL]


def test_platform_concurrency_limit_queues_same_platform(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 10)
    monkeypatch.setattr(settings, "collection_max_concurrency_per_user", 10)
    monkeypatch.setattr(settings, "collection_max_concurrency_per_platform", 2)
    monkeypatch.setattr(
        CollectionRunnerService,
        "reconcile_in_process_runs",
        AsyncMock(return_value=0),
    )
    running = [
        _task(id=1, user_id=1, platforms=["youtube"], status=CollectionTaskStatus.RUNNING.value),
        _task(id=2, user_id=2, platforms=["youtube"], status=CollectionTaskStatus.RUNNING.value),
    ]
    blocked = _task(id=3, user_id=3, platforms=["youtube"], status=CollectionTaskStatus.DRAFT.value)
    other_platform = _task(
        id=4, user_id=4, platforms=["tiktok"], status=CollectionTaskStatus.DRAFT.value
    )

    async def _run():
        db = AsyncMock()
        live = list(running)

        def _scalars():
            return iter([t for t in live if t.status == CollectionTaskStatus.RUNNING.value])

        result = MagicMock()
        result.scalars.side_effect = _scalars
        db.execute = AsyncMock(return_value=result)
        s1 = await CollectionQueueService.queue_or_start(db, blocked, resume=False)
        if blocked.status == CollectionTaskStatus.RUNNING.value:
            live.append(blocked)
        s2 = await CollectionQueueService.queue_or_start(db, other_platform, resume=False)
        return s1, s2

    s1, s2 = anyio.run(_run)
    assert s1 == CollectionTaskStatus.QUEUED
    assert blocked.run_checkpoint["queue_reasons"] == [QUEUE_REASON_PLATFORM_FULL]
    assert s2 == CollectionTaskStatus.RUNNING


def test_capacity_reasons_user_limit():
    running = [
        _task(id=i, user_id=9, platforms=["instagram"], status=CollectionTaskStatus.RUNNING.value)
        for i in range(3)
    ]
    task = _task(id=99, user_id=9, platforms=["instagram"])
    reasons = CollectionLeaseService.capacity_reasons(task, running)
    assert QUEUE_REASON_USER_LIMIT in reasons


def test_task_platform_list_from_multi():
    task = _task(platforms=["YouTube", "tiktok"], platform="multi")
    assert task_platform_list(task) == ["youtube", "tiktok"]


@pytest.mark.anyio
async def test_concurrency_status_route_is_not_captured_by_task_id(monkeypatch):
    sentinel = {
        "global_running": 7,
        "global_capacity": 10,
        "user_running": 2,
        "user_capacity": 3,
        "platform_capacity": 3,
        "queued_count": 4,
        "worker_count": 4,
    }
    monkeypatch.setattr(
        CollectionTaskService,
        "reconcile_stale_running_tasks",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        CollectionQueueService,
        "concurrency_overview",
        AsyncMock(return_value=sentinel),
    )

    async def fake_db():
        return object()

    async def fake_tenant():
        return TenantContext(user_id=42, product_id=1, workspace_id=1, is_admin=False)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_tenant_context] = fake_tenant
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/collection-tasks/concurrency-status")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_tenant_context, None)

    assert response.status_code == 200
    assert response.json() == sentinel
