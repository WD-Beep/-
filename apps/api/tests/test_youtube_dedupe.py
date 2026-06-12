"""YouTube 全链路去重与唯一键测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.platform_providers.youtube_apify import _profile_from_apify_item
from app.services.platform_providers.youtube_dedupe import (
    dedupe_apify_items,
    dedupe_youtube_profiles,
    normalize_keywords,
)
from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import (
    collected_identity_key,
    dedupe_collected_items,
    platform_identity_key,
    profile_to_collected,
)


def test_dedupe_apify_items_by_video_id():
    items = [
        {"videoId": "dQw4w9WgXcQ", "title": "A", "url": "https://youtube.com/watch?v=dQw4w9WgXcQ"},
        {"videoId": "dQw4w9WgXcQ", "title": "A dup", "url": "https://youtube.com/watch?v=dQw4w9WgXcQ"},
        {"videoId": "abc12345678", "title": "B", "url": "https://youtube.com/watch?v=abc12345678"},
    ]
    deduped, stats = dedupe_apify_items(items)
    assert len(deduped) == 2
    assert stats.item_duplicates_removed == 1


def test_dedupe_youtube_profiles_merges_same_channel_id():
    p1 = _profile_from_apify_item(
        {
            "channelId": "UC1234567890",
            "channelName": "Creator A",
            "channelUrl": "https://www.youtube.com/channel/UC1234567890",
            "title": "Video 1",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
        source_keyword="test",
    )
    p2 = _profile_from_apify_item(
        {
            "channelId": "UC1234567890",
            "channelName": "Creator A",
            "channelUrl": "https://www.youtube.com/@CreatorA",
            "title": "Video 2",
            "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        },
        source_keyword="test",
    )
    assert p1 is not None and p2 is not None
    merged, stats = dedupe_youtube_profiles([p1, p2])
    assert len(merged) == 1
    assert stats.profile_duplicates_removed == 1


def test_platform_identity_key_prefers_channel_id_over_url_variants():
    key_a = platform_identity_key(
        "youtube",
        "https://www.youtube.com/channel/UC1234567890",
        channel_id="UC1234567890",
    )
    key_b = platform_identity_key(
        "youtube",
        "https://www.youtube.com/@CreatorA",
        channel_id="UC1234567890",
    )
    assert key_a == key_b == ("youtube", "channel:uc1234567890")


def test_dedupe_collected_items_merges_youtube_url_variants():
    from app.collectors.base import CollectedInfluencer

    item_a = CollectedInfluencer(
        platform="youtube",
        username="creator",
        profile_url="https://www.youtube.com/channel/UC1234567890",
        platform_unique_id="UC1234567890",
    )
    item_b = CollectedInfluencer(
        platform="youtube",
        username="creator",
        profile_url="https://www.youtube.com/@CreatorA",
        platform_unique_id="UC1234567890",
    )
    deduped = dedupe_collected_items([item_a, item_b, item_a])
    assert len(deduped) == 1
    assert collected_identity_key(deduped[0]) == ("youtube", "channel:uc1234567890")


def test_normalize_keywords_deduplicates_case_and_whitespace():
    assert normalize_keywords(["Travel", "travel", " travel "]) == ["Travel"]


def test_profile_to_collected_sets_platform_unique_id():
    profile = PlatformCandidateProfile(
        platform="youtube",
        username="creator",
        profile_url="https://www.youtube.com/@CreatorA",
        channel_id="UC1234567890",
    )
    item = profile_to_collected(profile)
    assert item.platform_unique_id == "UC1234567890"


@pytest.mark.anyio
async def test_find_existing_batch_matches_youtube_channel_id_not_only_profile_url():
    from app.collectors.base import CollectedInfluencer
    from app.models.influencer import Influencer
    from app.services.collection_runner import CollectionRunnerService

    existing = Influencer(
        id=1,
        platform="youtube",
        username="creator",
        profile_url="https://www.youtube.com/channel/UC1234567890",
        platform_unique_id="UC1234567890",
    )
    db = AsyncMock()
    youtube_result = MagicMock()
    youtube_result.scalars.return_value = [existing]
    url_result = MagicMock()
    url_result.scalars.return_value = []
    db.execute = AsyncMock(side_effect=[youtube_result, url_result])
    incoming = CollectedInfluencer(
        platform="youtube",
        username="creator",
        profile_url="https://www.youtube.com/@CreatorA",
        platform_unique_id="UC1234567890",
    )
    result = await CollectionRunnerService._find_existing_batch(db, [incoming])
    key = collected_identity_key(incoming)
    assert key in result
    assert result[key].id == 1


def test_build_platform_candidate_rows_skips_duplicate_youtube_profiles():
    from app.models.collection_task import CollectionTask
    from app.services.collection_runner import CollectionRunnerService

    task = CollectionTask(name="t", platform="youtube", keywords=["travel"])
    profiles = [
        PlatformCandidateProfile(
            platform="youtube",
            username="creator",
            profile_url="https://www.youtube.com/channel/UC1234567890",
            channel_id="UC1234567890",
        ),
        PlatformCandidateProfile(
            platform="youtube",
            username="creator",
            profile_url="https://www.youtube.com/@CreatorA",
            channel_id="UC1234567890",
        ),
    ]
    rows = CollectionRunnerService._build_platform_candidate_rows(
        task,
        profiles,
        {},
        run_at=datetime.now(timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0]["profile_url"] == "https://www.youtube.com/channel/UC1234567890"


@pytest.mark.anyio
async def test_youtube_api_direct_searches_each_normalized_keyword_once(monkeypatch):
    from app.models.collection_task import CollectionTask
    from app.services.platform_providers import youtube_api_direct as mod

    searched_keywords: list[str] = []

    async def fake_ad_get_timed(path, **kwargs):
        params = kwargs.get("params") or {}
        if "query" in params:
            searched_keywords.append(str(params["query"]))
        if path == "/v1/youtube/channels":
            return {"channels": []}
        if path == "/v1/youtube/posts":
            return {"posts": []}
        return {}

    monkeypatch.setattr(mod, "_ad_get_timed", fake_ad_get_timed)
    monkeypatch.setattr(mod, "overfetch_pages_for_limit", lambda _limit: 1)
    monkeypatch.setattr(mod, "discovery_fetch_limit", lambda _task: 10)
    monkeypatch.setattr(mod, "_discovery_deadline", lambda: float("inf"))
    monkeypatch.setattr(mod, "report_discovery_progress", AsyncMock())
    monkeypatch.setattr(mod, "_hydrate_profiles_about", AsyncMock(side_effect=lambda profiles: profiles))
    monkeypatch.setattr(mod.settings, "api_direct_api_key", "test-key")
    monkeypatch.setattr(mod.settings, "youtube_discovery_keyword_timeout_seconds", 30)
    monkeypatch.setattr(mod.settings, "youtube_discovery_max_duration_seconds", 600)
    monkeypatch.setattr(mod.settings, "youtube_discovery_slow_threshold_seconds", 9999)

    task = CollectionTask(
        name="kw-dedupe",
        platform="youtube",
        platforms=["youtube"],
        keywords=["Travel", "travel", " travel "],
        collection_mode="keyword",
    )

    await mod.YouTubeApiDirectProvider.discover(task)
    assert searched_keywords == ["Travel", "Travel"]
    assert len(set(searched_keywords)) == 1
