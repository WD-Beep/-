"""YouTube official Data API provider routing and fallback tests."""

from __future__ import annotations

import anyio
import pytest

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.platform_types import PlatformCandidateProfile, PlatformDiscoveryResult


def _task() -> CollectionTask:
    return CollectionTask(
        name="yt official",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazon finds"],
        collection_mode="discovery",
        discovery_limit=10,
    )


def test_official_provider_maps_channel_payload(monkeypatch):
    from app.services.platform_providers.youtube_official import YouTubeOfficialProvider

    search_payload = {
        "items": [
            {"id": {"kind": "youtube#channel", "channelId": "UCabc1234567890"}},
            {
                "id": {"kind": "youtube#video", "videoId": "vid12345678"},
                "snippet": {"channelId": "UCvideo1234567890", "title": "Video title"},
            },
        ]
    }
    channels_payload = {
        "items": [
            {
                "id": "UCabc1234567890",
                "snippet": {
                    "title": "Creator A",
                    "description": "Home finds",
                    "customUrl": "@creatora",
                    "country": "US",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "thumbnails": {"default": {"url": "https://img.example/a.jpg"}},
                },
                "statistics": {
                    "subscriberCount": "12000",
                    "hiddenSubscriberCount": False,
                    "videoCount": "42",
                    "viewCount": "900000",
                },
            },
            {
                "id": "UCvideo1234567890",
                "snippet": {"title": "Creator B", "description": "", "customUrl": "creatorb"},
                "statistics": {"hiddenSubscriberCount": True, "videoCount": "5", "viewCount": "1000"},
            },
        ]
    }
    calls = []

    async def fake_get_json(path, params):
        calls.append((path, params))
        if path == "search":
            return search_payload
        if path == "channels":
            return channels_payload
        raise AssertionError(path)

    monkeypatch.setattr(settings, "youtube_api_key", "yt-key")
    monkeypatch.setattr(settings, "youtube_official_search_max_pages", 1, raising=False)
    monkeypatch.setattr(settings, "youtube_official_max_results_per_keyword", 25, raising=False)
    monkeypatch.setattr(YouTubeOfficialProvider, "_get_json", fake_get_json)
    async def noop_progress(**_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.platform_providers.youtube_official.report_discovery_progress",
        noop_progress,
    )

    result = anyio.run(YouTubeOfficialProvider.discover, _task())

    assert [path for path, _params in calls] == ["search", "channels"]
    assert result.errors == []
    assert result.api_requests == 2
    assert len(result.profiles) == 2
    first = result.profiles[0]
    assert first.platform == "youtube"
    assert first.username == "@creatora"
    assert first.display_name == "Creator A"
    assert first.profile_url == "https://www.youtube.com/channel/UCabc1234567890"
    assert first.followers_count == 12000
    assert first.source_meta["provider"] == "youtube_official"
    assert first.source_meta["view_count"] == 900000
    assert result.items[0].platform_unique_id == "UCabc1234567890"
    assert result.items[0].country == "US"
    assert result.profiles[1].followers_count is None


def test_auto_provider_uses_official_success_without_apify(monkeypatch):
    from app.services.platform_providers.youtube_official import YouTubeAutoProvider

    calls = []
    official_result = PlatformDiscoveryResult(
        platform="youtube",
        profiles=[
            PlatformCandidateProfile(
                platform="youtube",
                username="creator",
                profile_url="https://www.youtube.com/channel/UCcreator123",
            )
        ],
        items=[object()],
        discovered_count=1,
        deduped_count=1,
        profile_fetched_count=1,
        api_requests=2,
    )

    async def official(_task, **_kwargs):
        calls.append("official")
        return official_result

    async def apify(_task, **_kwargs):
        calls.append("apify")
        raise AssertionError("Apify should not run after official results")

    monkeypatch.setattr("app.services.platform_providers.youtube_official.YouTubeOfficialProvider.discover", official)
    monkeypatch.setattr("app.services.platform_providers.youtube_official.YouTubeApifyProvider.discover", apify)

    result = anyio.run(YouTubeAutoProvider.discover, _task())

    assert result is official_result
    assert calls == ["official"]


def test_auto_provider_falls_back_to_apify_on_official_quota_error(monkeypatch):
    from app.services.platform_providers.youtube_official import YouTubeAutoProvider

    official_result = PlatformDiscoveryResult(
        platform="youtube",
        fatal=True,
        errors=["YouTube 官方 API 配额已用尽"],
        skipped=True,
        skip_reason="YouTube 官方 API 配额已用尽",
        api_requests=1,
        provider_availability_state={"youtube": {"reason": "quota_exceeded"}},
    )
    apify_result = PlatformDiscoveryResult(
        platform="youtube",
        profiles=[
            PlatformCandidateProfile(
                platform="youtube",
                username="fallback",
                profile_url="https://www.youtube.com/channel/UCfallback123",
            )
        ],
        items=[object()],
        discovered_count=1,
        deduped_count=1,
        profile_fetched_count=1,
        api_requests=1,
    )

    async def official(_task, **_kwargs):
        return official_result

    async def apify(_task, **_kwargs):
        return apify_result

    monkeypatch.setattr("app.services.platform_providers.youtube_official.YouTubeOfficialProvider.discover", official)
    monkeypatch.setattr("app.services.platform_providers.youtube_official.YouTubeApifyProvider.discover", apify)

    result = anyio.run(YouTubeAutoProvider.discover, _task())

    assert result is apify_result
    assert result.api_requests == 2
    assert any("官方 API 配额已用尽，已切换 Apify" in err for err in result.errors)


def test_auto_provider_marks_successful_apify_fallback_without_youtube_failure(monkeypatch):
    from app.services.platform_providers.youtube_official import YouTubeAutoProvider

    official_result = PlatformDiscoveryResult(
        platform="youtube",
        fatal=True,
        errors=["YouTube 官方 API 请求超时"],
        skipped=True,
        skip_reason="YouTube 官方 API 请求超时",
        api_requests=1,
        provider_availability_state={
            "youtube": {
                "status": "provider_unavailable",
                "reason": "timeout",
                "message": "YouTube 官方 API 请求超时",
                "api_calls": 1,
            }
        },
    )
    apify_result = PlatformDiscoveryResult(
        platform="youtube",
        profiles=[
            PlatformCandidateProfile(
                platform="youtube",
                username="fallback",
                profile_url="https://www.youtube.com/channel/UCfallback123",
            )
        ],
        items=[object()],
        discovered_count=1,
        deduped_count=1,
        profile_fetched_count=1,
        api_requests=1,
        fatal=True,
    )

    async def official(_task, **_kwargs):
        return official_result

    async def apify(_task, **_kwargs):
        return apify_result

    monkeypatch.setattr("app.services.platform_providers.youtube_official.YouTubeOfficialProvider.discover", official)
    monkeypatch.setattr("app.services.platform_providers.youtube_official.YouTubeApifyProvider.discover", apify)

    result = anyio.run(YouTubeAutoProvider.discover, _task())

    assert result.profiles
    assert result.fatal is False
    assert any("YouTube 官方 API 不可用，已 fallback Apify，最终成功" in err for err in result.errors)
    state = result.provider_availability_state["youtube"]
    assert state["reason"] == "timeout"
    assert state["actual_provider"] == "apify"
    assert state["fallback_success"] is True


def test_auto_provider_does_not_fallback_on_bad_request(monkeypatch):
    from app.services.platform_providers.youtube_official import YouTubeAutoProvider

    official_result = PlatformDiscoveryResult(
        platform="youtube",
        fatal=True,
        errors=["YouTube 官方 API 请求参数有误"],
        provider_availability_state={"youtube": {"reason": "bad_request"}},
    )

    async def official(_task, **_kwargs):
        return official_result

    async def apify(_task, **_kwargs):
        raise AssertionError("Bad request should not blindly fallback to Apify")

    monkeypatch.setattr("app.services.platform_providers.youtube_official.YouTubeOfficialProvider.discover", official)
    monkeypatch.setattr("app.services.platform_providers.youtube_official.YouTubeApifyProvider.discover", apify)

    result = anyio.run(YouTubeAutoProvider.discover, _task())

    assert result is official_result
