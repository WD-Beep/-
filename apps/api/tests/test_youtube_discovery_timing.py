"""YouTube 发现阶段超时、慢响应与进度摘要测试。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionTaskStatus
from app.services.api_direct_client import reset_request_budget
from app.services.collection_funnel import build_running_discovery_summary, determine_task_status
from app.services.discovery_progress import DiscoveryProgressReporter
from app.services.platform_providers.youtube_api_direct import YouTubeApiDirectProvider
from app.services.platform_providers.youtube_apify import YouTubeApifyProvider
from app.services.task_run_progress import RunCheckpoint


def test_build_running_discovery_summary_includes_keyword_and_provider():
    text = build_running_discovery_summary(
        phase="discovery",
        target=15,
        discovered=0,
        deduped=0,
        profile_fetched=0,
        inserted=0,
        slow_api=True,
        current_keyword="amazon seller",
        provider="apify",
        keywords_completed=2,
        keywords_total=10,
    )
    assert "amazon seller" in text
    assert "Apify" in text
    assert "2/10" in text


@pytest.mark.anyio
async def test_discovery_progress_marks_slow_api_after_threshold(monkeypatch):
    monkeypatch.setattr(settings, "youtube_discovery_slow_threshold_seconds", 0)

    class FakeTask:
        discovered_count = 0
        deduped_count = 0
        profile_fetched_count = 0
        filtered_out_count = 0
        inserted_count = 0
        success_count = 0
        result_count = 0
        processed_count = 0
        total_estimate = 0
        current_stage = None
        status_summary = None
        last_error = None
        run_checkpoint = {}

    task = FakeTask()
    reporter = DiscoveryProgressReporter(
        db=AsyncMock(),
        task=task,  # type: ignore[arg-type]
        checkpoint=RunCheckpoint(),
        target_qualified=15,
    )
    reporter.db.commit = AsyncMock()

    await reporter.update(
        phase="discovery",
        discovered_count=0,
        provider="apify",
        current_keyword="amazon seller",
        keywords_completed=0,
        keywords_total=5,
        commit=True,
    )

    assert task.run_checkpoint.get("slow_api") is True
    assert "amazon seller" in (task.status_summary or "")
    assert task.run_checkpoint.get("current_keyword") == "amazon seller"


@pytest.mark.anyio
async def test_discovery_progress_updates_do_not_commit_concurrently():
    class FakeTask:
        discovered_count = 0
        deduped_count = 0
        profile_fetched_count = 0
        filtered_out_count = 0
        inserted_count = 0
        success_count = 0
        result_count = 0
        processed_count = 0
        total_estimate = 0
        current_stage = None
        status_summary = None
        last_error = None
        run_checkpoint = {}

    active_commits = 0
    peak_commits = 0

    async def commit():
        nonlocal active_commits, peak_commits
        active_commits += 1
        peak_commits = max(peak_commits, active_commits)
        await asyncio.sleep(0.02)
        active_commits -= 1

    db = AsyncMock()
    db.commit = commit
    reporter = DiscoveryProgressReporter(
        db=db,
        task=FakeTask(),  # type: ignore[arg-type]
        checkpoint=RunCheckpoint(),
        target_qualified=15,
    )

    await asyncio.gather(
        reporter.update(
            phase="discovery",
            discovered_count=0,
            provider="apify",
            current_keyword="amazon seller",
            keywords_completed=0,
            keywords_total=5,
            commit=True,
        ),
        reporter.update(
            phase="discovery",
            discovered_count=0,
            provider="apify",
            current_keyword="fba",
            keywords_completed=1,
            keywords_total=5,
            commit=True,
        ),
    )

    assert peak_commits == 1


@pytest.mark.anyio
async def test_youtube_apify_keyword_timeout_skips_without_hanging(monkeypatch):
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "youtube_discovery_keyword_timeout_seconds", 1)
    monkeypatch.setattr(settings, "apify_youtube_timeout_seconds", 1)
    monkeypatch.setattr(settings, "apify_youtube_max_retries", 0)
    monkeypatch.setattr(settings, "youtube_apify_keyword_concurrency", 1)
    monkeypatch.setattr(settings, "youtube_discovery_max_duration_seconds", 30)

    async def slow_actor(*_args, **_kwargs):
        await asyncio.sleep(10)
        return []

    task = CollectionTask(
        name="yt-timeout",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazon seller", "fba"],
        collection_mode="keyword",
        discovery_limit=15,
    )

    started = time.perf_counter()
    with patch(
        "app.services.platform_providers.youtube_apify.run_actor_sync",
        side_effect=slow_actor,
    ):
        with patch(
            "app.services.platform_providers.youtube_apify.report_discovery_progress",
            new_callable=AsyncMock,
        ):
            result = await YouTubeApifyProvider.discover(task)

    elapsed = time.perf_counter() - started
    assert elapsed < 14
    assert result.discovered_count == 0
    assert result.fatal is False
    assert result.errors
    assert all(err.strip() for err in result.errors)
    assert any("APIFY_YOUTUBE_TIMEOUT_SECONDS" in err for err in result.errors)
    assert any("YOUTUBE_DISCOVERY_KEYWORD_TIMEOUT_SECONDS" in err for err in result.errors)


@pytest.mark.anyio
async def test_youtube_apify_apify_client_timeout_is_nonfatal_with_clear_error(monkeypatch):
    from app.services.apify_client import ApifyError

    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "youtube_discovery_keyword_timeout_seconds", 30)
    monkeypatch.setattr(settings, "apify_youtube_timeout_seconds", 25)
    monkeypatch.setattr(settings, "apify_youtube_max_retries", 0)
    monkeypatch.setattr(settings, "youtube_apify_keyword_concurrency", 1)
    monkeypatch.setattr(settings, "youtube_discovery_max_duration_seconds", 30)

    async def timeout_actor(*_args, **_kwargs):
        raise ApifyError("Apify 请求超时（>25s）")

    task = CollectionTask(
        name="yt-apify-timeout",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazon seller"],
        collection_mode="keyword",
        discovery_limit=15,
    )

    with patch(
        "app.services.platform_providers.youtube_apify.run_actor_sync",
        side_effect=timeout_actor,
    ):
        with patch(
            "app.services.platform_providers.youtube_apify.report_discovery_progress",
            new_callable=AsyncMock,
        ):
            result = await YouTubeApifyProvider.discover(task)

    assert result.fatal is False
    assert result.errors
    assert all(err.strip() for err in result.errors)
    assert any("APIFY_YOUTUBE_TIMEOUT_SECONDS" in err for err in result.errors)
    summary = build_running_discovery_summary(
        phase="discovery",
        target=15,
        discovered=0,
        deduped=0,
        profile_fetched=0,
        inserted=0,
        slow_api=True,
        provider="apify",
        current_keyword="amazon seller",
        keywords_completed=1,
        keywords_total=1,
    )
    assert "Apify/API 响应较慢" in summary
    assert result.errors[-1]


def test_youtube_apify_rate_limit_error_is_recorded():
    text = build_running_discovery_summary(
        phase="discovery",
        target=15,
        discovered=0,
        deduped=0,
        profile_fetched=0,
        inserted=0,
        rate_limited=True,
        provider="apify",
        current_keyword="amazon seller",
        keywords_completed=1,
        keywords_total=5,
    )
    assert "限流" in text
    assert "amazon seller" in text


def test_build_running_discovery_summary_shows_partial_skip_and_hydration():
    text = build_running_discovery_summary(
        phase="hydration",
        target=10,
        discovered=7,
        deduped=7,
        profile_fetched=3,
        inserted=0,
        slow_api=True,
        provider="apify",
        platform="facebook",
        profiles_hydrating_total=7,
        profiles_hydrating_completed=3,
        partial_skip_note="部分主页补采超时，已跳过并继续",
    )
    assert "补采主页（3/7）" in text
    assert "部分请求已跳过并继续处理" in text


def test_api_direct_empty_discovery_maps_to_completed_no_results():
    status = determine_task_status(
        inserted_count=0,
        profile_failed_count=0,
        discovered_count=0,
        fatal_error=False,
        has_api_warnings=False,
    )
    assert status == CollectionTaskStatus.COMPLETED_NO_RESULTS


def test_api_direct_api_warnings_without_results_is_partial_failed():
    status = determine_task_status(
        inserted_count=0,
        profile_failed_count=0,
        discovered_count=0,
        fatal_error=False,
        has_api_warnings=True,
    )
    assert status == CollectionTaskStatus.PARTIAL_FAILED


def test_overfetch_stops_when_round_has_no_new_unique_items(monkeypatch):
    from app.services.collection_runner import CollectionRunnerService
    from app.services.platform_types import PlatformDiscoveryResult, PlatformCandidateProfile
    from app.services.platform_utils import profile_to_collected

    task = CollectionTask(
        name="yt-overfetch-stop",
        platform="youtube",
        platforms=["youtube"],
        keywords=["a", "b"],
        collection_mode="discovery",
        discovery_limit=3,
    )

    calls = 0

    async def fake_discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            profile = PlatformCandidateProfile(
                platform="youtube",
                username="chan1",
                profile_url="https://www.youtube.com/channel/chan1",
            )
            item = profile_to_collected(profile)
            return [
                PlatformDiscoveryResult(
                    platform="youtube",
                    items=[item],
                    profiles=[profile],
                    discovered_count=1,
                    deduped_count=1,
                )
            ]
        return [PlatformDiscoveryResult(platform="youtube", discovered_count=0, deduped_count=0)]

    monkeypatch.setattr(
        "app.services.collection_runner.discover_non_instagram_platforms",
        fake_discover,
    )

    async def noop_async(*_args, **_kwargs):
        return None

    async def empty_existing(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(CollectionRunnerService, "_find_existing_batch", empty_existing)
    monkeypatch.setattr("app.services.collection_runner.TaskCandidateService.clear_for_task", noop_async)
    monkeypatch.setattr("app.services.collection_runner.TaskCandidateService.bulk_insert", noop_async)
    monkeypatch.setattr("app.services.collection_runner.TaskInfluencerService.refresh_task_stats", noop_async)

    async def _run():
        class FakeDb:
            async def commit(self):
                return None

            async def refresh(self, *_args, **_kwargs):
                return None

            async def execute(self, *_args, **_kwargs):
                return None

            async def flush(self):
                return None

        return await CollectionRunnerService.run_task(
            FakeDb(),  # type: ignore[arg-type]
            task,
            allow_running=True,
        )

    anyio.run(_run)
    assert calls == 2


def test_nonfatal_platform_no_results_does_not_request_overfetch_rounds(monkeypatch):
    from app.services.collection_runner import CollectionRunnerService
    from app.services.platform_types import PlatformDiscoveryResult

    task = CollectionTask(
        name="yt-no-overfetch",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazonfinds"],
        collection_mode="discovery",
        discovery_limit=1,
    )

    calls = 0

    async def fake_discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [
            PlatformDiscoveryResult(
                platform="youtube",
                api_requests=1,
                errors=["YouTube Apify 搜索「amazonfinds」超时（>25s），已跳过该关键词并继续"],
                fatal=False,
            )
        ]

    monkeypatch.setattr(
        "app.services.collection_runner.discover_non_instagram_platforms",
        fake_discover,
    )

    async def noop_async(*_args, **_kwargs):
        return None

    async def empty_existing(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(CollectionRunnerService, "_find_existing_batch", empty_existing)
    monkeypatch.setattr("app.services.collection_runner.TaskCandidateService.clear_for_task", noop_async)
    monkeypatch.setattr("app.services.collection_runner.TaskCandidateService.bulk_insert", noop_async)
    monkeypatch.setattr("app.services.collection_runner.TaskInfluencerService.refresh_task_stats", noop_async)

    async def _run():
        class FakeDb:
            async def commit(self):
                return None

            async def refresh(self, *_args, **_kwargs):
                return None

            async def execute(self, *_args, **_kwargs):
                return None

            async def flush(self):
                return None

        return await CollectionRunnerService.run_task(
            FakeDb(),  # type: ignore[arg-type]
            task,
            allow_running=True,
        )

    result = anyio.run(_run)

    assert calls == 1
    assert task.status == CollectionTaskStatus.COMPLETED_NO_RESULTS.value
    assert result["inserted_count"] == 0


@pytest.mark.anyio
async def test_youtube_api_direct_keyword_timeout_skips_without_hanging(monkeypatch):
    monkeypatch.setattr(settings, "api_direct_api_key", "test-key")
    monkeypatch.setattr(settings, "youtube_discovery_keyword_timeout_seconds", 1)
    monkeypatch.setattr(settings, "youtube_api_direct_keyword_concurrency", 1)
    monkeypatch.setattr(settings, "youtube_discovery_max_duration_seconds", 30)

    async def slow_ad_get(*_args, **_kwargs):
        await asyncio.sleep(10)
        return {"channels": [], "posts": []}

    task = CollectionTask(
        name="yt-api-direct-timeout",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazon seller", "fba"],
        collection_mode="keyword",
        discovery_limit=15,
    )

    reset_request_budget()
    started = time.perf_counter()
    with patch(
        "app.services.platform_providers.youtube_api_direct.ad_get",
        side_effect=slow_ad_get,
    ):
        with patch(
            "app.services.platform_providers.youtube_api_direct._hydrate_profiles_about",
            side_effect=lambda profiles: profiles,
        ):
            with patch(
                "app.services.platform_providers.youtube_api_direct.report_discovery_progress",
                new_callable=AsyncMock,
            ):
                result = await YouTubeApiDirectProvider.discover(task)

    elapsed = time.perf_counter() - started
    assert elapsed < 20
    assert result.discovered_count == 0
    assert result.fatal is False
    assert any("超时" in err for err in result.errors)


@pytest.mark.anyio
async def test_youtube_api_direct_runs_keywords_with_configured_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "api_direct_api_key", "test-key")
    monkeypatch.setattr(settings, "youtube_api_direct_keyword_concurrency", 2)
    monkeypatch.setattr(settings, "collection_search_concurrency", 4)

    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_ad_get(path, *, params=None, platform=None):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.08)
        async with lock:
            active -= 1
        if path == "/v1/youtube/channels":
            return {"channels": []}
        return {"posts": []}

    task = CollectionTask(
        name="yt-api-direct-concurrency",
        platform="youtube",
        platforms=["youtube"],
        keywords=["a", "b", "c", "d"],
        collection_mode="keyword",
        discovery_limit=15,
    )

    reset_request_budget()
    with patch(
        "app.services.platform_providers.youtube_api_direct.ad_get",
        side_effect=fake_ad_get,
    ):
        with patch(
            "app.services.platform_providers.youtube_api_direct._hydrate_profiles_about",
            side_effect=lambda profiles: profiles,
        ):
            with patch(
                "app.services.platform_providers.youtube_api_direct.report_discovery_progress",
                new_callable=AsyncMock,
            ):
                result = await YouTubeApiDirectProvider.discover(task)

    assert result.discovered_count == 0
    assert peak >= 2


def test_api_direct_rate_limit_summary_for_frontend():
    text = build_running_discovery_summary(
        phase="discovery",
        target=15,
        discovered=0,
        deduped=0,
        profile_fetched=0,
        inserted=0,
        rate_limited=True,
        provider="api_direct",
        current_keyword="amazon seller",
        keywords_completed=1,
        keywords_total=5,
    )
    assert "限流" in text
