"""采集进度、checkpoint 与 HTTP 重试测试。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.routes.collection_tasks import run_collection_task
from app.core.config import settings
from app.models.enums import CollectionTaskStatus
from app.services.collection_runner import CollectionRunnerService
from app.services.collection_task import CollectionTaskService
from app.services.http_retry import RETRYABLE_STATUS, should_retry
from app.services.task_run_progress import (
    RunCheckpoint,
    STAGE_AI_COMPLETED,
    STAGE_DISCOVERY,
    profile_checkpoint_key,
    reset_run_progress,
    update_task_progress,
)


def _task(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": 1,
        "name": "test task",
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
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


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


def test_should_retry_rules():
    assert should_retry(429, None) is True
    assert should_retry(500, None) is True
    assert should_retry(401, None) is False
    assert should_retry(403, None) is False
    assert should_retry(None, httpx.TimeoutException("timeout")) is True
    assert 401 not in RETRYABLE_STATUS


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
        with pytest.raises(HTTPException) as exc:
            await run_collection_task(2, BackgroundTasks(), db)
        assert exc.value.status_code == 409
        assert "YouTube 验证" in exc.value.detail

    anyio.run(_run)


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

    async def _run():
        with pytest.raises(HTTPException) as exc:
            await run_collection_task(2, BackgroundTasks(), db)
        assert exc.value.status_code == 409
        assert "TikTok 类目采集" in exc.value.detail

    anyio.run(_run)


def test_run_rejects_fresh_running_task(monkeypatch):
    task = _task(status=CollectionTaskStatus.RUNNING.value)
    db = AsyncMock()

    async def _get_task(_db, _task_id):
        return task

    monkeypatch.setattr(CollectionTaskService, "get_task", _get_task)

    async def _run():
        with pytest.raises(HTTPException) as exc:
            await run_collection_task(1, BackgroundTasks(), db)
        assert exc.value.status_code == 409

    anyio.run(_run)


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
        result = await run_collection_task(1, background_tasks, db)
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
        result = await run_collection_task(1, background_tasks, db)
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
        result = await run_collection_task(1, background_tasks, db)
        assert result.status == CollectionTaskStatus.RUNNING

    anyio.run(_run)

    assert task.current_stage == "persist"
    assert task.processed_count == 5
    assert task.success_count == 2
    assert task.run_checkpoint["persisted_profiles"]
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
    assert results[2] == 3
