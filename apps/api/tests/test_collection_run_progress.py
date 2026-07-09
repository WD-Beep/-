"""采集进度、checkpoint 与 HTTP 重试测试。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.routes.collection_tasks import bulk_run_collection_tasks, run_collection_task
from app.core.config import settings
from app.deps.tenant import TenantContext
from app.models.enums import CollectionTaskStatus
from app.schemas.collection_task import CollectionTaskBulkRun
from app.services.collection_runner import CollectionRunCapacityError, CollectionRunnerService
from app.services import collection_runner as collection_runner_module
from app.services.collection_task import CollectionTaskService
from app.services.collection_queue import CollectionQueueService, QUEUE_REASON_GLOBAL_FULL
from app.services.http_retry import RETRYABLE_STATUS, should_retry
from app.services.task_run_progress import (
    RunCheckpoint,
    STAGE_AI_COMPLETED,
    STAGE_AI_PROCESSING,
    STAGE_COMPLETED,
    STAGE_DISCOVERY,
    apply_terminal_task_state,
    profile_checkpoint_key,
    reset_run_progress,
    should_commit_progress,
    update_task_progress,
)


def _task(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": 1,
        "name": "test task",
        "user_id": 1,
        "product_id": 1,
        "collection_mode": "keyword",
        "platform": "instagram",
        "platforms": ["instagram"],
        "keywords": ["travel"],
        "input_urls": [],
        "country": None,
        "category": None,
        "discovery_limit": 100,
        "min_engagement_rate": 2.0,
        "min_followers_count": 50000,
        "max_followers_count": None,
        "filter_include_keywords": [],
        "filter_exclude_keywords": [],
        "comment_discovery_enabled": False,
        "status": CollectionTaskStatus.DRAFT.value,
        "schedule_enabled": False,
        "schedule_cron": None,
        "email_enabled": False,
        "email_recipients": [],
        "outreach_enabled": False,
        "outreach_provider": "smtp",
        "outreach_dry_run": True,
        "outreach_templates": {},
        "last_run_at": None,
        "next_run_at": None,
        "result_count": 0,
        "email_count": 0,
        "missing_contact_count": 0,
        "discovered_count": 0,
        "deduped_count": 0,
        "profile_fetched_count": 0,
        "profile_failed_count": 0,
        "filtered_out_count": 0,
        "inserted_count": 0,
        "hashtag_count": 0,
        "post_count": 0,
        "comment_author_count": 0,
        "filtered_below_min_followers_count": 0,
        "filtered_excluded_keyword_count": 0,
        "processed_count": 0,
        "success_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "total_estimate": 0,
        "current_stage": None,
        "last_error": None,
        "run_checkpoint": {},
        "status_summary": None,
        "error_message": None,
        "is_archived": False,
        "archived_at": None,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _tenant_ctx() -> TenantContext:
    return TenantContext(user_id=1, product_id=1, workspace_id=1, is_admin=True)


@pytest.fixture(autouse=True)
def _clear_collection_run_claims():
    collection_runner_module._active_collection_task_ids.clear()
    yield
    collection_runner_module._active_collection_task_ids.clear()


def test_profile_checkpoint_key_normalizes():
    key = profile_checkpoint_key("Instagram", "https://instagram.com/User/")
    assert key == "instagram:https://instagram.com/user"


def test_checkpoint_hashtag_skip():
    cp = RunCheckpoint(completed_hashtags=["amazon"])
    assert cp.hashtag_done("amazon") is True
    assert cp.hashtag_done("#Amazon") is True
    assert cp.hashtag_done("travel") is False
    cp.mark_hashtag("travel")
    assert cp.hashtag_done("travel") is True


def test_checkpoint_persisted_skip():
    cp = RunCheckpoint()
    cp.mark_persisted("youtube", "https://youtube.com/channel/abc")
    assert cp.persisted_done("youtube", "https://youtube.com/channel/abc") is True
    assert cp.persisted_done("youtube", "https://youtube.com/channel/xyz") is False


def test_run_checkpoint_preserves_product_and_provider_context():
    task = _task(
        run_checkpoint={
            "amazon_product_seeds": [
                {
                    "asin": "B0D9W576KQ",
                    "brand": "HOMEHIVE",
                    "normalized_url": "https://www.amazon.com/dp/B0D9W576KQ",
                }
            ],
            "provider_availability_state": {
                "tiktok": {
                    "status": "provider_unavailable",
                    "reason": "apify_memory_limit_exceeded",
                }
            },
            "platform_api_counts": {"tiktok": 0, "youtube": 8},
            "completed_search_keys": ["youtube:B0D9W576KQ"],
        }
    )

    checkpoint = RunCheckpoint.from_task(task)
    checkpoint.mark_search("facebook", "HOMEHIVE clear PVC jewelry bags")
    data = checkpoint.to_dict()

    assert data["amazon_product_seeds"][0]["asin"] == "B0D9W576KQ"
    assert data["provider_availability_state"]["tiktok"]["reason"] == "apify_memory_limit_exceeded"
    assert data["platform_api_counts"] == {"tiktok": 0, "youtube": 8}
    assert "facebook:homehive clear pvc jewelry bags" in data["completed_search_keys"]


def test_terminal_success_state_clears_stale_ai_progress_summary():
    task = _task(
        status=CollectionTaskStatus.RUNNING.value,
        current_stage=STAGE_AI_PROCESSING,
        status_summary="AI 评分中… 已处理 20/97，成功 18",
        processed_count=20,
        success_count=18,
        inserted_count=30,
        result_count=21,
    )

    apply_terminal_task_state(
        task,
        status=CollectionTaskStatus.COMPLETED_WITH_RESULTS,
        summary="采集完成：合格入库 30 个",
        inserted_count=30,
    )

    assert task.status == CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
    assert task.current_stage == STAGE_COMPLETED
    assert task.inserted_count == 30
    assert task.result_count == 30
    assert task.success_count == 30
    assert "AI 评分中" not in (task.status_summary or "")
    assert "AI 完成中" not in (task.status_summary or "")

def test_should_retry_rules():
    assert should_retry(429, None) is True
    assert should_retry(500, None) is True
    assert should_retry(401, None) is False
    assert should_retry(403, None) is False
    assert should_retry(None, httpx.TimeoutException("timeout")) is True
    assert 401 not in RETRYABLE_STATUS


def test_apify_network_error_is_classified_as_unreachable():
    from app.services.apify_client import is_apify_network_unreachable

    assert is_apify_network_unreachable(httpx.NetworkError("All connection attempts failed")) is True
    assert is_apify_network_unreachable(Exception("Apify 网络错误: All connection attempts failed")) is True
    assert is_apify_network_unreachable(Exception("actor-memory-limit-exceeded")) is False


@pytest.mark.parametrize("status_code", [401, 403, 400])
def test_apify_client_does_not_retry_client_errors(status_code):
    from app.services.apify_client import ApifyError, run_actor_sync

    async def _run():
        response = MagicMock()
        response.status_code = status_code
        response.text = "denied"
        response.json.return_value = {"error": "denied"}

        with patch("app.services.apify_client.settings") as mock_settings:
            mock_settings.is_apify_configured = True
            mock_settings.apify_token = "token"
            mock_settings.apify_timeout_seconds = 30
            with patch("app.services.apify_client.execute_with_retry", new_callable=AsyncMock) as mock_retry:
                mock_retry.return_value = response
                with pytest.raises(ApifyError):
                    await run_actor_sync("actor/id", {})
                assert mock_retry.await_count == 1

    anyio.run(_run)


@pytest.mark.anyio
async def test_apify_client_wraps_httpx_timeout_with_readable_message():
    from app.services.apify_client import ApifyError, format_apify_timeout_error, run_actor_sync
    import httpx

    async def _run():
        with patch("app.services.apify_client.settings") as mock_settings:
            mock_settings.is_apify_configured = True
            mock_settings.apify_token = "token"
            mock_settings.apify_timeout_seconds = 30
            with patch("app.services.apify_client.execute_with_retry", new_callable=AsyncMock) as mock_retry:
                mock_retry.side_effect = httpx.ReadTimeout("read timed out")
                with pytest.raises(ApifyError) as exc_info:
                    await run_actor_sync("streamers~youtube-scraper", {}, timeout=25)
                message = str(exc_info.value)
                assert message == format_apify_timeout_error(timeout=25, exc=mock_retry.side_effect)
                assert "超时" in message
                assert message.strip()

    await _run()


@pytest.mark.anyio
async def test_apify_client_aborts_remote_run_after_local_timeout():
    from app.services.apify_client import ApifyError, run_actor_sync
    import httpx

    class FakeResponse:
        status_code = 201
        text = "{}"

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    class FakeClient:
        aborted: list[str] = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **_kwargs):
            if url.endswith("/abort"):
                self.aborted.append(url)
                return FakeResponse({"data": {"status": "ABORTING"}})
            return FakeResponse({"data": {"id": "run-123", "defaultDatasetId": "dataset-123"}})

        async def get(self, url, **_kwargs):
            if "/actor-runs/run-123" in url:
                raise httpx.ReadTimeout("poll timed out")
            return FakeResponse([])

    with patch("app.services.apify_client.settings") as mock_settings:
        mock_settings.is_apify_configured = True
        mock_settings.apify_token = "token"
        mock_settings.apify_timeout_seconds = 30
        with patch("app.services.apify_client.httpx.AsyncClient", FakeClient):
            with pytest.raises(ApifyError) as exc_info:
                await run_actor_sync("streamers~youtube-scraper", {}, timeout=1, max_retries=0)

    assert "已尝试停止远端运行" in str(exc_info.value)
    assert FakeClient.aborted
    assert FakeClient.aborted[0].endswith("/actor-runs/run-123/abort")


def test_reset_run_progress_clears_checkpoint():
    task = MagicMock()
    task.run_checkpoint = {"completed_hashtags": ["a"]}
    reset_run_progress(task)
    assert task.processed_count == 0
    assert task.run_checkpoint == {}


def test_task_read_includes_progress_and_backend_stale_flags(monkeypatch):
    monkeypatch.setattr(settings, "collection_running_stale_seconds", 300)
    task = _task(
        status=CollectionTaskStatus.RUNNING.value,
        updated_at=datetime.now(UTC) - timedelta(seconds=301),
        processed_count=7,
        success_count=3,
        failed_count=1,
        skipped_count=2,
        total_estimate=10,
        current_stage="persist",
        last_error="temporary failure",
        run_checkpoint={"persisted_profiles": ["instagram:https://example.com/a"]},
    )

    data = CollectionTaskService.task_read(task)

    assert data.processed_count == 7
    assert data.success_count == 3
    assert data.failed_count == 1
    assert data.skipped_count == 2
    assert data.total_estimate == 10
    assert data.current_stage == "persist"
    assert data.last_error == "temporary failure"
    assert data.run_checkpoint["persisted_profiles"]
    assert data.stale is True
    assert data.recoverable is True
    assert data.stale_after_seconds == 300


def test_running_stale_uses_backend_threshold(monkeypatch):
    monkeypatch.setattr(settings, "collection_running_stale_seconds", 300)
    now = datetime.now(UTC)
    fresh = _task(
        status=CollectionTaskStatus.RUNNING.value,
        updated_at=now - timedelta(seconds=250),
    )
    stale = _task(
        status=CollectionTaskStatus.RUNNING.value,
        updated_at=now - timedelta(seconds=301),
    )

    assert CollectionTaskService.is_running_stale(fresh, now=now) is False
    assert CollectionTaskService.is_running_stale(stale, now=now) is True


def test_collection_stability_defaults_are_conservative():
    assert settings.collection_max_running_tasks == 2
    assert settings.apify_youtube_timeout_seconds == 90
    assert settings.youtube_discovery_keyword_timeout_seconds == 90
    assert settings.youtube_apify_keyword_concurrency == 2
    assert settings.apify_tiktok_timeout_seconds == 90
    assert settings.tiktok_apify_keyword_concurrency == 2
    assert settings.apify_facebook_timeout_seconds == 90
    assert settings.facebook_discovery_keyword_timeout_seconds == 90
    assert settings.facebook_apify_keyword_concurrency == 1
    assert settings.facebook_apify_profile_concurrency == 1
    assert settings.collection_profile_enrich_concurrency == 3
    assert settings.collection_contact_concurrency == 2
    assert settings.collection_ai_concurrency == 1


def test_update_task_progress_can_clear_last_error():
    task = _task(
        current_stage=STAGE_AI_COMPLETED,
        last_error="old error",
        processed_count=1,
        total_estimate=1,
    )

    async def _run():
        db = AsyncMock()
        await update_task_progress(db, task, stage=STAGE_AI_COMPLETED, last_error=None)
        db.commit.assert_awaited_once()

    anyio.run(_run)
    assert task.last_error is None


def _patch_no_blocking_running_task(monkeypatch) -> None:
    async def _no_blocking(_db, *, exclude_id=None):
        return None

    monkeypatch.setattr(CollectionTaskService, "get_blocking_running_task", _no_blocking)


def test_bulk_run_reconciles_stale_in_process_slots_before_capacity_check(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 2)
    task = _task(id=3, status=CollectionTaskStatus.DRAFT.value)
    db = AsyncMock()
    background_tasks = BackgroundTasks()

    stale_result = MagicMock()
    stale_result.all.return_value = []
    count_result = MagicMock()
    count_result.scalars.return_value = iter([])
    db.execute = AsyncMock(side_effect=[stale_result, count_result])

    async def _get_task(_db, task_id):
        return task if task_id == 3 else None

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    _patch_no_blocking_running_task(monkeypatch)

    async def _run():
        collection_runner_module._active_collection_task_ids.clear()
        collection_runner_module._active_collection_task_ids.update({100, 101})
        try:
            result = await bulk_run_collection_tasks(
                CollectionTaskBulkRun(task_ids=[3]),
                background_tasks,
                db,
                ctx=_tenant_ctx(),
            )
            return result
        finally:
            collection_runner_module._active_collection_task_ids.clear()

    result = anyio.run(_run)

    assert result.started_ids == [3]
    assert result.skipped_ids == []
    assert result.active_count == 1
    assert task.status == CollectionTaskStatus.RUNNING.value
    assert background_tasks.tasks[0].kwargs == {"resume": False}


def test_run_starts_after_stale_in_process_slots_reconciled(monkeypatch):
    task = _task(id=2, status=CollectionTaskStatus.DRAFT.value)
    db = AsyncMock()
    background_tasks = BackgroundTasks()

    stale_result = MagicMock()
    stale_result.all.return_value = []
    count_result = MagicMock()
    count_result.scalars.return_value = iter([])
    db.execute = AsyncMock(side_effect=[stale_result, stale_result, count_result])

    async def _get_task(_db, task_id):
        return task if task_id == 2 else None

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    _patch_no_blocking_running_task(monkeypatch)

    async def _run():
        collection_runner_module._active_collection_task_ids.clear()
        collection_runner_module._active_collection_task_ids.update({100, 101})
        try:
            result = await run_collection_task(2, background_tasks, db, ctx=_tenant_ctx())
            assert result.status == CollectionTaskStatus.RUNNING
        finally:
            collection_runner_module._active_collection_task_ids.clear()

    anyio.run(_run)
    assert task.status == CollectionTaskStatus.RUNNING.value
    assert background_tasks.tasks[0].kwargs == {"resume": False}


def test_run_rejects_when_in_process_collection_active(monkeypatch):
    task = _task(id=2, status=CollectionTaskStatus.DRAFT.value)
    db = AsyncMock()

    async def _get_task(_db, task_id):
        if task_id == 2:
            return task
        if task_id == 9:
            blocking = _task(id=9, name="YouTube 验证", status=CollectionTaskStatus.RUNNING.value)
            return blocking
        return None

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    _patch_no_blocking_running_task(monkeypatch)
    monkeypatch.setattr(CollectionRunnerService, "has_active_collection_run", lambda: True)
    monkeypatch.setattr(CollectionRunnerService, "get_active_collection_task_id", lambda: 9)

    async def _run():
        result = await run_collection_task(2, BackgroundTasks(), db, ctx=_tenant_ctx())
        assert result.status == CollectionTaskStatus.QUEUED

    anyio.run(_run)
    assert task.status == CollectionTaskStatus.QUEUED.value
    assert task.run_checkpoint["queue_reasons"] == ["global_concurrency_full"]


def test_run_rejects_when_other_task_running(monkeypatch):
    task = _task(id=2, status=CollectionTaskStatus.DRAFT.value)
    blocking = _task(id=1, name="TikTok 类目采集", status=CollectionTaskStatus.RUNNING.value)
    db = AsyncMock()

    async def _get_task(_db, task_id):
        return task if task_id == 2 else None

    async def _blocking(_db, *, exclude_id=None):
        return blocking if exclude_id == 2 else None

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    monkeypatch.setattr(CollectionTaskService, "get_blocking_running_task", _blocking)
    result = MagicMock()
    result.scalars.return_value = iter([blocking])
    db.execute = AsyncMock(return_value=result)

    async def _run():
        result = await run_collection_task(2, BackgroundTasks(), db, ctx=_tenant_ctx())
        assert result.status == CollectionTaskStatus.QUEUED

    anyio.run(_run)
    assert task.status == CollectionTaskStatus.QUEUED.value
    assert task.run_checkpoint["queue_reasons"] == ["user_already_running"]


def test_queue_allows_first_ten_and_queues_eleventh(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 10)
    tasks: list[SimpleNamespace] = []
    monkeypatch.setattr(
        CollectionRunnerService,
        "reconcile_in_process_runs",
        AsyncMock(return_value=0),
    )

    async def _run():
        db = AsyncMock()
        result = MagicMock()
        result.scalars.side_effect = lambda: iter(
            [task for task in tasks if task.status == CollectionTaskStatus.RUNNING.value]
        )
        db.execute = AsyncMock(return_value=result)

        statuses = []
        for task_id in range(1, 12):
            task = _task(id=task_id, user_id=task_id, status=CollectionTaskStatus.DRAFT.value)
            statuses.append(await CollectionQueueService.queue_or_start(db, task, resume=False))
            tasks.append(task)
        return statuses, tasks

    statuses, tasks = anyio.run(_run)

    assert statuses[:10] == [CollectionTaskStatus.RUNNING] * 10
    assert [task.status for task in tasks[:10]] == [CollectionTaskStatus.RUNNING.value] * 10
    assert statuses[10] == CollectionTaskStatus.QUEUED
    assert tasks[10].status == CollectionTaskStatus.QUEUED.value
    assert tasks[10].run_checkpoint["queue_reasons"] == [QUEUE_REASON_GLOBAL_FULL]


def test_queue_same_salesperson_repeated_start(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 10)
    running = [_task(id=1, user_id=7, status=CollectionTaskStatus.RUNNING.value)]
    new_task = _task(id=2, user_id=7, status=CollectionTaskStatus.DRAFT.value)
    monkeypatch.setattr(
        CollectionRunnerService,
        "reconcile_in_process_runs",
        AsyncMock(return_value=0),
    )

    async def _run():
        db = AsyncMock()
        result = MagicMock()
        result.scalars.side_effect = lambda: iter(running)
        db.execute = AsyncMock(return_value=result)
        await CollectionQueueService.queue_or_start(db, new_task, resume=False)

    anyio.run(_run)

    assert new_task.status == CollectionTaskStatus.QUEUED.value
    assert new_task.run_checkpoint["queue_reasons"] == ["user_already_running"]


def test_dispatch_releases_slot_and_starts_next(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 1)
    queued = _task(id=2, user_id=2, status=CollectionTaskStatus.QUEUED.value)
    started: list[tuple[int, bool]] = []

    async def starter(task_id: int, *, resume: bool = False):
        started.append((task_id, resume))

    async def _run():
        db = AsyncMock()
        queued_result = MagicMock()
        queued_result.scalars.side_effect = [iter([queued]), iter([])]
        empty_running = MagicMock()
        empty_running.scalars.return_value = iter([])
        db.execute = AsyncMock(side_effect=[queued_result, empty_running, queued_result])

        await CollectionQueueService.dispatch_queued_tasks(db=db, starter=starter)

    anyio.run(_run)

    assert queued.status == CollectionTaskStatus.RUNNING.value
    assert queued.run_checkpoint.get("queue_reasons") is None
    assert started == [(2, False)]


def test_scheduled_queued_task_starts_after_slot_released(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 1)
    scheduled = _task(id=2, user_id=2, status=CollectionTaskStatus.DRAFT.value, schedule_enabled=True)
    running = _task(id=1, user_id=1, status=CollectionTaskStatus.RUNNING.value)
    started: list[tuple[int, bool]] = []

    class Session:
        async def __aenter__(self):
            db = AsyncMock()
            db.get = AsyncMock(return_value=scheduled)
            result = MagicMock()
            result.scalars.return_value = iter([running])
            db.execute = AsyncMock(return_value=result)
            return db

        async def __aexit__(self, *_args):
            return None

    async def starter(task_id: int, *, resume: bool = False):
        started.append((task_id, resume))

    async def _run():
        await CollectionRunnerService._claim_collection_run(running.id)
        monkeypatch.setattr("app.scheduler.manager.async_session_factory", lambda: Session())
        monkeypatch.setattr("app.scheduler.manager.SchedulerManager.sync_next_run_at", AsyncMock())
        await run_scheduled_collection(2)

        assert scheduled.status == CollectionTaskStatus.QUEUED.value
        assert scheduled.run_checkpoint["queue_reasons"] == [QUEUE_REASON_GLOBAL_FULL]

        await CollectionRunnerService._release_collection_run(running.id)
        dispatch_db = AsyncMock()
        queued_result = MagicMock()
        queued_result.scalars.side_effect = [iter([scheduled]), iter([])]
        empty_running = MagicMock()
        empty_running.scalars.return_value = iter([])
        dispatch_db.execute = AsyncMock(side_effect=[queued_result, empty_running, queued_result])
        await CollectionQueueService.dispatch_queued_tasks(db=dispatch_db, starter=starter)

    from app.scheduler.manager import run_scheduled_collection

    anyio.run(_run)

    assert scheduled.status == CollectionTaskStatus.RUNNING.value
    assert started == [(2, False)]


def test_scheduled_collection_queues_when_capacity_full(monkeypatch):
    from app.scheduler.manager import run_scheduled_collection

    monkeypatch.setattr(settings, "collection_max_running_tasks", 1)
    scheduled = _task(id=2, user_id=2, status=CollectionTaskStatus.DRAFT.value, schedule_enabled=True)
    running = [_task(id=1, user_id=1, status=CollectionTaskStatus.RUNNING.value)]

    class Session:
        async def __aenter__(self):
            db = AsyncMock()
            db.get = AsyncMock(return_value=scheduled)
            result = MagicMock()
            result.scalars.return_value = iter(running)
            db.execute = AsyncMock(return_value=result)
            return db

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr("app.scheduler.manager.async_session_factory", lambda: Session())
    monkeypatch.setattr("app.scheduler.manager.SchedulerManager.sync_next_run_at", AsyncMock())

    anyio.run(run_scheduled_collection, 2)

    assert scheduled.status == CollectionTaskStatus.QUEUED.value
    assert scheduled.run_checkpoint["queue_reasons"] == ["global_concurrency_full"]


def test_scheduled_collection_runs_after_queue_start_claim(monkeypatch):
    from app.scheduler.manager import run_scheduled_collection

    monkeypatch.setattr(settings, "collection_max_running_tasks", 1)
    scheduled = _task(id=12, user_id=12, status=CollectionTaskStatus.DRAFT.value, schedule_enabled=True)
    run_calls: list[bool] = []

    class Session:
        async def __aenter__(self):
            db = AsyncMock()
            db.get = AsyncMock(return_value=scheduled)
            result = MagicMock()
            result.scalars.return_value = iter([])
            db.execute = AsyncMock(return_value=result)
            return db

        async def __aexit__(self, *_args):
            return None

    async def _run_task(_db, task, *, allow_running: bool = False, **_kwargs):
        run_calls.append(allow_running)
        if task.status == CollectionTaskStatus.RUNNING.value and not allow_running:
            raise ValueError("Task is already running")
        task.status = CollectionTaskStatus.COMPLETED_NO_RESULTS.value

    monkeypatch.setattr("app.scheduler.manager.async_session_factory", lambda: Session())
    monkeypatch.setattr("app.scheduler.manager.SchedulerManager.sync_next_run_at", AsyncMock())
    monkeypatch.setattr(CollectionRunnerService, "run_task", _run_task)

    anyio.run(run_scheduled_collection, 12)

    assert run_calls == [True]
    assert scheduled.status == CollectionTaskStatus.COMPLETED_NO_RESULTS.value


def test_queue_or_start_claim_failure_returns_to_queue(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 1)
    task = _task(id=2, user_id=2, status=CollectionTaskStatus.DRAFT.value)
    monkeypatch.setattr(
        CollectionRunnerService,
        "reconcile_in_process_runs",
        AsyncMock(return_value=0),
    )

    async def _claim_fails(_task_id: int):
        raise CollectionRunCapacityError("capacity full")

    monkeypatch.setattr(CollectionRunnerService, "_claim_collection_run", _claim_fails)

    async def _run():
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value = iter([])
        db.execute = AsyncMock(return_value=result)
        return await CollectionQueueService.queue_or_start(db, task, resume=False)

    result_status = anyio.run(_run)

    assert result_status == CollectionTaskStatus.QUEUED
    assert task.status == CollectionTaskStatus.QUEUED.value
    assert task.run_checkpoint["queue_reasons"] == [QUEUE_REASON_GLOBAL_FULL]


def test_background_business_value_error_is_not_restored_to_queue(monkeypatch):
    task = _task(id=4, user_id=4, status=CollectionTaskStatus.RUNNING.value)

    async def _get_task(_db, task_id):
        return task if task_id == 4 else None

    async def _run_task(_db, _task, **_kwargs):
        task.status = CollectionTaskStatus.FAILED.value
        raise ValueError("business validation failed")

    class Session:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr("app.services.collection_queue.async_session_factory", lambda: Session())
    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    monkeypatch.setattr(CollectionRunnerService, "run_task", _run_task)
    monkeypatch.setattr(CollectionQueueService, "dispatch_queued_tasks", AsyncMock(return_value=0))

    anyio.run(CollectionQueueService._run_task_and_dispatch, 4)

    assert task.status == CollectionTaskStatus.FAILED.value
    assert task.run_checkpoint.get("queue_reasons") is None


def test_background_claim_failure_does_not_leave_fake_running(monkeypatch):
    task = _task(id=3, user_id=3, status=CollectionTaskStatus.RUNNING.value)

    async def _get_task(_db, task_id):
        return task if task_id == 3 else None

    async def _run_task(_db, _task, **_kwargs):
        raise CollectionRunCapacityError("capacity full")

    class Session:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr("app.services.collection_queue.async_session_factory", lambda: Session())
    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    monkeypatch.setattr(CollectionRunnerService, "run_task", _run_task)
    monkeypatch.setattr(CollectionQueueService, "dispatch_queued_tasks", AsyncMock(return_value=0))

    anyio.run(CollectionQueueService._run_task_and_dispatch, 3)

    assert task.status == CollectionTaskStatus.QUEUED.value
    assert task.run_checkpoint["queue_reasons"] == [QUEUE_REASON_GLOBAL_FULL]


def test_run_returns_current_state_for_fresh_running_task(monkeypatch):
    task = _task(status=CollectionTaskStatus.RUNNING.value)
    db = AsyncMock()
    background_tasks = BackgroundTasks()

    async def _get_task(_db, _task_id):
        return task

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)

    async def _run():
        result = await run_collection_task(1, background_tasks, db, ctx=_tenant_ctx())
        assert result.status == CollectionTaskStatus.RUNNING

    anyio.run(_run)
    assert background_tasks.tasks == []


def test_run_returns_current_state_for_queued_task(monkeypatch):
    task = _task(status=CollectionTaskStatus.QUEUED.value)
    db = AsyncMock()
    background_tasks = BackgroundTasks()

    async def _get_task(_db, _task_id):
        return task

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)

    async def _run():
        result = await run_collection_task(1, background_tasks, db, ctx=_tenant_ctx())
        assert result.status == CollectionTaskStatus.QUEUED

    anyio.run(_run)
    assert background_tasks.tasks == []


def test_run_starts_new_task_with_reset_progress(monkeypatch):
    task = _task(
        status=CollectionTaskStatus.DRAFT.value,
        processed_count=9,
        success_count=4,
        failed_count=1,
        skipped_count=2,
        total_estimate=20,
        current_stage="persist",
        last_error="old error",
        run_checkpoint={"persisted_profiles": ["x"]},
    )
    db = AsyncMock()
    background_tasks = BackgroundTasks()

    async def _get_task(_db, _task_id):
        return task

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    _patch_no_blocking_running_task(monkeypatch)

    async def _run():
        result = await run_collection_task(1, background_tasks, db, ctx=_tenant_ctx())
        assert result.status == CollectionTaskStatus.RUNNING

    anyio.run(_run)

    assert task.current_stage == STAGE_DISCOVERY
    assert task.processed_count == 0
    assert task.success_count == 0
    assert task.failed_count == 0
    assert task.skipped_count == 0
    assert task.total_estimate == 0
    assert task.last_error is None
    assert task.run_checkpoint == {}
    assert background_tasks.tasks[0].kwargs == {"resume": False}


def test_run_start_message_uses_task_platform(monkeypatch):
    task = _task(
        status=CollectionTaskStatus.DRAFT.value,
        platform="youtube",
        platforms=["youtube"],
    )
    db = AsyncMock()
    background_tasks = BackgroundTasks()

    async def _get_task(_db, _task_id):
        return task

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    _patch_no_blocking_running_task(monkeypatch)

    async def _run():
        result = await run_collection_task(1, background_tasks, db, ctx=_tenant_ctx())
        assert result.status_summary
        assert "youtube" in result.status_summary
        assert "Instagram" not in result.status_summary

    anyio.run(_run)


def test_run_stale_running_uses_resume_checkpoint(monkeypatch):
    monkeypatch.setattr(settings, "collection_running_stale_seconds", 300)
    task = _task(
        status=CollectionTaskStatus.RUNNING.value,
        updated_at=datetime.now(UTC) - timedelta(seconds=301),
        processed_count=5,
        success_count=2,
        current_stage="persist",
        run_checkpoint={"persisted_profiles": ["instagram:https://example.com/a"]},
    )
    db = AsyncMock()
    background_tasks = BackgroundTasks()

    async def _get_task(_db, _task_id):
        return task

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    _patch_no_blocking_running_task(monkeypatch)

    async def _run():
        result = await run_collection_task(1, background_tasks, db, ctx=_tenant_ctx())
        assert result.status == CollectionTaskStatus.RUNNING

    anyio.run(_run)

    assert task.current_stage == "persist"
    assert task.processed_count == 5
    assert task.success_count == 2
    assert task.run_checkpoint["persisted_profiles"]
    assert background_tasks.tasks[0].kwargs == {"resume": True}


def test_run_stale_running_message_says_continue_from_checkpoint(monkeypatch):
    monkeypatch.setattr(settings, "collection_running_stale_seconds", 300)
    task = _task(
        status=CollectionTaskStatus.RUNNING.value,
        updated_at=datetime.now(UTC) - timedelta(seconds=301),
        current_stage="discovery",
        run_checkpoint={"completed_search_keys": ["youtube:amazon"]},
    )
    db = AsyncMock()
    background_tasks = BackgroundTasks()

    async def _get_task(_db, _task_id):
        return task

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)
    _patch_no_blocking_running_task(monkeypatch)

    async def _run():
        result = await run_collection_task(1, background_tasks, db, ctx=_tenant_ctx())
        assert result.status_summary
        assert "checkpoint" in result.status_summary

    anyio.run(_run)
    assert task.run_checkpoint["completed_search_keys"] == ["youtube:amazon"]
    assert background_tasks.tasks[0].kwargs == {"resume": True}


def test_map_bounded_partial_failure():
    from app.services.concurrency import map_bounded

    async def worker(value: int) -> int:
        if value == 2:
            raise RuntimeError("fail")
        return value

    async def _run():
        return await map_bounded([1, 2, 3], worker, concurrency=3)

    results = anyio.run(_run)
    assert results[0] == 1
    assert isinstance(results[1], RuntimeError)
    assert str(results[1]) == "fail"
    assert results[2] == 3


def test_map_bounded_incremental_reports_progress():
    from app.services.concurrency import map_bounded_incremental

    seen: list[int] = []

    async def worker(value: int) -> int:
        return value * 2

    async def on_complete(item: int, outcome: int | BaseException) -> None:
        seen.append(item if isinstance(outcome, int) else -item)

    async def _run():
        return await map_bounded_incremental([1, 2, 3], worker, concurrency=2, on_complete=on_complete)

    results = anyio.run(_run)
    assert sorted(results) == [2, 4, 6]
    assert sorted(seen) == [1, 2, 3]


def test_get_blocking_returns_task_when_capacity_is_full(monkeypatch):
    monkeypatch.setattr(settings, "collection_max_running_tasks", 2)
    running_a = _task(id=1, name="A", status=CollectionTaskStatus.RUNNING.value)
    running_b = _task(id=2, name="B", status=CollectionTaskStatus.RUNNING.value)

    async def _run():
        db = AsyncMock()

        async def _execute(_query):
            result = MagicMock()
            result.scalars.return_value = iter([running_a, running_b])
            return result

        db.execute = AsyncMock(side_effect=_execute)
        blocking = await CollectionTaskService.get_blocking_running_task(db, exclude_id=3)
        return blocking

    blocking = anyio.run(_run)
    assert blocking == running_a


def test_collection_runner_capacity_claim_and_release():
    async def _run():
        collection_runner_module._active_collection_task_ids.clear()
        monkey_cap = settings.collection_max_running_tasks
        try:
            settings.collection_max_running_tasks = 2
            await CollectionRunnerService._claim_collection_run(1)
            await CollectionRunnerService._claim_collection_run(2)
            with pytest.raises(CollectionRunCapacityError):
                await CollectionRunnerService._claim_collection_run(3)
            await CollectionRunnerService._release_collection_run(1)
            await CollectionRunnerService._claim_collection_run(3)
        finally:
            settings.collection_max_running_tasks = monkey_cap
            collection_runner_module._active_collection_task_ids.clear()

    anyio.run(_run)


def test_should_commit_progress_batches_db_writes():
    assert should_commit_progress(0, 100, every=20) is False
    assert should_commit_progress(20, 100, every=20) is True
    assert should_commit_progress(21, 100, every=20) is False
    assert should_commit_progress(100, 100, every=20) is True
    assert should_commit_progress(5, 0, every=20) is False
