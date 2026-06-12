"""Facebook 发现阶段并发、超时与进度摘要测试。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.collection_funnel import build_running_discovery_summary
from app.services.platform_providers.facebook_apify import (
    FacebookApifyProvider,
    _needs_profile_hydration,
    _profile_from_search_item,
)
from app.services.platform_providers.youtube_apify import YouTubeApifyProvider


def _search_item(keyword: str, *, page_id: str) -> dict:
    return {
        "query": keyword,
        "url": f"https://www.facebook.com/{page_id}",
        "name": f"Page {page_id}",
        "followers": 1200,
    }


def _page_item(url: str) -> dict:
    return {
        "facebookUrl": url,
        "title": "Hydrated Page",
        "followers": 5000,
        "email": "contact@example.com",
        "intro": "About text",
    }


@pytest.mark.anyio
async def test_facebook_apify_runs_keywords_with_configured_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "facebook_apify_keyword_concurrency", 2)
    monkeypatch.setattr(settings, "facebook_apify_profile_concurrency", 1)
    monkeypatch.setattr(settings, "facebook_discovery_keyword_timeout_seconds", 30)
    monkeypatch.setattr(settings, "apify_facebook_timeout_seconds", 30)
    monkeypatch.setattr(settings, "facebook_apify_profile_timeout_seconds", 30)
    monkeypatch.setattr(settings, "facebook_discovery_max_duration_seconds", 60)

    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_actor(actor_id, run_input, **_kwargs):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.08)
        async with lock:
            active -= 1
        if "queries" in run_input:
            keyword = run_input["queries"][0]
            return [_search_item(keyword, page_id=f"page-{keyword}")]
        url = run_input["startUrls"][0]["url"]
        return [_page_item(url)]

    task = CollectionTask(
        name="fb-concurrency",
        platform="facebook",
        platforms=["facebook"],
        keywords=["a", "b", "c", "d"],
        collection_mode="keyword",
        discovery_limit=10,
    )

    with patch(
        "app.services.platform_providers.facebook_apify.run_actor_sync",
        side_effect=fake_actor,
    ):
        with patch(
            "app.services.platform_providers.facebook_apify.report_discovery_progress",
            new_callable=AsyncMock,
        ):
            result = await FacebookApifyProvider.discover(task)

    assert peak >= 2
    assert result.discovered_count >= 4
    assert result.fatal is False


@pytest.mark.anyio
async def test_facebook_apify_keyword_timeout_skips_without_blocking(monkeypatch):
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "facebook_apify_keyword_concurrency", 1)
    monkeypatch.setattr(settings, "facebook_discovery_keyword_timeout_seconds", 1)
    monkeypatch.setattr(settings, "apify_facebook_timeout_seconds", 1)
    monkeypatch.setattr(settings, "facebook_apify_profile_timeout_seconds", 1)
    monkeypatch.setattr(settings, "facebook_discovery_max_duration_seconds", 30)

    async def slow_actor(actor_id, run_input, **_kwargs):
        await asyncio.sleep(10)
        return []

    task = CollectionTask(
        name="fb-timeout",
        platform="facebook",
        platforms=["facebook"],
        keywords=["slow-one", "slow-two"],
        collection_mode="keyword",
        discovery_limit=5,
    )

    started = time.perf_counter()
    with patch(
        "app.services.platform_providers.facebook_apify.run_actor_sync",
        side_effect=slow_actor,
    ):
        with patch(
            "app.services.platform_providers.facebook_apify.report_discovery_progress",
            new_callable=AsyncMock,
        ):
            result = await FacebookApifyProvider.discover(task)

    elapsed = time.perf_counter() - started
    assert elapsed < 12
    assert result.fatal is False
    assert result.errors
    assert all(err.strip() for err in result.errors)
    assert any("FACEBOOK_DISCOVERY_KEYWORD_TIMEOUT_SECONDS" in err for err in result.errors)


@pytest.mark.anyio
async def test_facebook_apify_profile_timeout_skips_without_blocking(monkeypatch):
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "facebook_apify_keyword_concurrency", 1)
    monkeypatch.setattr(settings, "facebook_apify_profile_concurrency", 2)
    monkeypatch.setattr(settings, "facebook_discovery_keyword_timeout_seconds", 30)
    monkeypatch.setattr(settings, "apify_facebook_timeout_seconds", 30)
    monkeypatch.setattr(settings, "facebook_apify_profile_timeout_seconds", 1)
    monkeypatch.setattr(settings, "facebook_discovery_max_duration_seconds", 30)

    async def mixed_actor(actor_id, run_input, **_kwargs):
        if "queries" in run_input:
            keyword = run_input["queries"][0]
            return [_search_item(keyword, page_id="page-1")]
        await asyncio.sleep(10)
        return []

    task = CollectionTask(
        name="fb-profile-timeout",
        platform="facebook",
        platforms=["facebook"],
        keywords=["brand"],
        collection_mode="keyword",
        discovery_limit=5,
    )

    started = time.perf_counter()
    with patch(
        "app.services.platform_providers.facebook_apify.run_actor_sync",
        side_effect=mixed_actor,
    ):
        with patch(
            "app.services.platform_providers.facebook_apify.report_discovery_progress",
            new_callable=AsyncMock,
        ):
            result = await FacebookApifyProvider.discover(task)

    elapsed = time.perf_counter() - started
    assert elapsed < 12
    assert result.discovered_count >= 1
    assert result.fatal is False
    assert any("FACEBOOK_APIFY_PROFILE_TIMEOUT_SECONDS" in err for err in result.errors)


@pytest.mark.anyio
async def test_youtube_apify_runs_keywords_with_configured_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "youtube_apify_keyword_concurrency", 2)
    monkeypatch.setattr(settings, "youtube_discovery_keyword_timeout_seconds", 30)
    monkeypatch.setattr(settings, "apify_youtube_timeout_seconds", 30)
    monkeypatch.setattr(settings, "youtube_discovery_max_duration_seconds", 60)
    monkeypatch.setattr(settings, "apify_youtube_max_retries", 0)

    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_actor(*_args, **_kwargs):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.08)
        async with lock:
            active -= 1
        return []

    task = CollectionTask(
        name="yt-concurrency",
        platform="youtube",
        platforms=["youtube"],
        keywords=["a", "b", "c", "d"],
        collection_mode="keyword",
        discovery_limit=10,
    )

    with patch(
        "app.services.platform_providers.youtube_apify.run_actor_sync",
        side_effect=fake_actor,
    ):
        with patch(
            "app.services.platform_providers.youtube_apify.report_discovery_progress",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.platform_providers.youtube_apify._hydrate_profiles_about",
                side_effect=lambda profiles: profiles,
            ):
                await YouTubeApifyProvider.discover(task)

    assert peak >= 2


def test_profile_has_sufficient_fields_skips_hydration():
    profile = _profile_from_search_item(
        {
            "url": "https://www.facebook.com/brand-page",
            "name": "Brand",
            "followers": 5000,
            "description": "About us",
            "email": "hello@brand.com",
        },
        source_keyword="brand",
    )
    assert profile is not None
    assert profile.source_meta.get("profile_hydrated") is True
    assert _needs_profile_hydration(profile) is False


def test_profile_partial_fields_triggers_hydration():
    profile = _profile_from_search_item(
        {
            "url": "https://www.facebook.com/partial-page",
            "name": "Partial",
            "email": "hello@partial.com",
        },
        source_keyword="partial",
    )
    assert profile is not None
    assert profile.source_meta.get("profile_hydrated") is False
    assert _needs_profile_hydration(profile) is True


@pytest.mark.anyio
async def test_facebook_apify_skips_hydration_when_search_fields_sufficient(monkeypatch):
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "facebook_apify_keyword_concurrency", 1)
    monkeypatch.setattr(settings, "facebook_apify_profile_concurrency", 2)
    monkeypatch.setattr(settings, "facebook_discovery_keyword_timeout_seconds", 30)
    monkeypatch.setattr(settings, "apify_facebook_timeout_seconds", 30)
    monkeypatch.setattr(settings, "facebook_apify_profile_timeout_seconds", 30)
    monkeypatch.setattr(settings, "facebook_discovery_max_duration_seconds", 60)

    hydration_calls = 0

    async def fake_actor(actor_id, run_input, **_kwargs):
        nonlocal hydration_calls
        if "queries" in run_input:
            keyword = run_input["queries"][0]
            return [
                {
                    "query": keyword,
                    "url": "https://www.facebook.com/full-page",
                    "name": "Full Page",
                    "followers": 8000,
                    "description": "Complete bio",
                    "email": "full@example.com",
                }
            ]
        hydration_calls += 1
        return [_page_item(run_input["startUrls"][0]["url"])]

    task = CollectionTask(
        name="fb-skip-hydration",
        platform="facebook",
        platforms=["facebook"],
        keywords=["brand"],
        collection_mode="keyword",
        discovery_limit=5,
    )

    with patch(
        "app.services.platform_providers.facebook_apify.run_actor_sync",
        side_effect=fake_actor,
    ):
        with patch(
            "app.services.platform_providers.facebook_apify.report_discovery_progress",
            new_callable=AsyncMock,
        ):
            result = await FacebookApifyProvider.discover(task)

    assert result.discovered_count >= 1
    assert hydration_calls == 0


@pytest.mark.anyio
async def test_facebook_apify_hydrates_when_search_fields_partial(monkeypatch):
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "facebook_apify_keyword_concurrency", 1)
    monkeypatch.setattr(settings, "facebook_apify_profile_concurrency", 2)
    monkeypatch.setattr(settings, "facebook_discovery_keyword_timeout_seconds", 30)
    monkeypatch.setattr(settings, "apify_facebook_timeout_seconds", 30)
    monkeypatch.setattr(settings, "facebook_apify_profile_timeout_seconds", 30)
    monkeypatch.setattr(settings, "facebook_discovery_max_duration_seconds", 60)

    hydration_calls = 0

    async def fake_actor(actor_id, run_input, **_kwargs):
        nonlocal hydration_calls
        if "queries" in run_input:
            keyword = run_input["queries"][0]
            return [
                {
                    "query": keyword,
                    "url": "https://www.facebook.com/partial-page",
                    "name": "Partial Page",
                    "description": "Only bio, no followers or contact",
                }
            ]
        hydration_calls += 1
        return [_page_item(run_input["startUrls"][0]["url"])]

    task = CollectionTask(
        name="fb-hydrate-partial",
        platform="facebook",
        platforms=["facebook"],
        keywords=["brand"],
        collection_mode="keyword",
        discovery_limit=5,
    )

    with patch(
        "app.services.platform_providers.facebook_apify.run_actor_sync",
        side_effect=fake_actor,
    ):
        with patch(
            "app.services.platform_providers.facebook_apify.report_discovery_progress",
            new_callable=AsyncMock,
        ):
            result = await FacebookApifyProvider.discover(task)

    assert result.discovered_count >= 1
    assert hydration_calls == 1


def test_build_running_discovery_summary_includes_hydration_and_skip_note():
    text = build_running_discovery_summary(
        phase="hydration",
        target=10,
        discovered=7,
        deduped=7,
        profile_fetched=2,
        inserted=0,
        slow_api=True,
        provider="apify",
        platform="facebook",
        profiles_hydrating_total=7,
        profiles_hydrating_completed=2,
        partial_skip_note="Facebook Apify 主页补采超时，已跳过该主页并继续",
    )
    assert "补采主页（2/7）" in text
    assert "接口响应较慢" in text
    assert "部分请求已跳过并继续处理" in text
