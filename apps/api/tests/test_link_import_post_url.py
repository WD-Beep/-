"""链接导入应区分 profile_url 与 source_post_url。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.collectors.base import CollectedInfluencer
from app.services.apify_instagram import DiscoveryResult, PostAuthorCandidate, ProfileScrapeResult
from app.services.export import CANDIDATE_BUSINESS_EXPORT_COLUMNS
from app.services.link_import import (
    LinkImportExecuteResult,
    LinkImportService,
    _match_item_to_entry,
    _process_provider_import_items,
)
from app.services.link_import_url import parse_import_link
from app.services.platform_providers.youtube_api_direct import _profile_from_input_url
from app.services.platform_utils import profile_to_collected
from app.services.url_parser import detect_platform, parse_raw_urls, tiktok_profile_from_url, validate_link_import_url_lines


TIKTOK_VIDEO = "https://www.tiktok.com/@hoodeditz559/video/7234567890123456789"
TIKTOK_PROFILE = "https://www.tiktok.com/@hoodeditz559"
YOUTUBE_VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
INSTAGRAM_POST = "https://www.instagram.com/p/ABC123/"


def test_parse_import_link_tiktok_video():
    parsed = parse_import_link(TIKTOK_VIDEO)
    assert parsed is not None
    assert parsed.platform == "tiktok"
    assert parsed.link_type == "post"
    assert parsed.profile_url == "https://www.tiktok.com/@hoodeditz559"
    assert parsed.source_post_url == TIKTOK_VIDEO
    assert parsed.username == "hoodeditz559"


def test_parse_import_link_tiktok_profile():
    parsed = parse_import_link(TIKTOK_PROFILE)
    assert parsed is not None
    assert parsed.link_type == "profile"
    assert parsed.profile_url == TIKTOK_PROFILE
    assert parsed.source_post_url is None


def test_detect_platform_rejects_tiktok_discover():
    assert detect_platform("https://www.tiktok.com/discover") is None


def test_parse_raw_urls_rejects_tiktok_discover():
    valid, invalid = parse_raw_urls("https://www.tiktok.com/discover")
    assert not valid
    assert invalid


def test_tiktok_profile_from_url_preserves_post_link():
    profile = tiktok_profile_from_url(TIKTOK_VIDEO)
    assert profile is not None
    assert profile.profile_url == "https://www.tiktok.com/@hoodeditz559"
    assert profile.source_post_url == TIKTOK_VIDEO
    assert profile.username == "hoodeditz559"


def test_profile_to_collected_keeps_separate_urls():
    profile = tiktok_profile_from_url(TIKTOK_VIDEO)
    assert profile is not None
    item = profile_to_collected(profile)
    assert item.profile_url == "https://www.tiktok.com/@hoodeditz559"
    assert item.source_post_url == TIKTOK_VIDEO


def test_validate_link_import_url_lines_includes_post_fields():
    valid = validate_link_import_url_lines([TIKTOK_VIDEO])
    assert len(valid) == 1
    entry = valid[0]
    assert entry["platform"] == "tiktok"
    assert entry["profile_url"] == "https://www.tiktok.com/@hoodeditz559"
    assert entry["source_post_url"] == TIKTOK_VIDEO
    assert entry["link_type"] == "post"


def test_parse_raw_urls_accepts_youtube_video():
    valid, invalid = parse_raw_urls(YOUTUBE_VIDEO)
    assert not invalid
    assert len(valid) == 1
    assert valid[0]["platform"] == "youtube"
    assert valid[0]["link_type"] == "post"
    assert valid[0]["source_post_url"]


def test_youtube_profile_from_input_url_video():
    profile = _profile_from_input_url(YOUTUBE_VIDEO)
    assert profile is not None
    assert profile.source_post_url == YOUTUBE_VIDEO
    assert profile.source_meta.get("video_id") == "dQw4w9WgXcQ"
    assert profile.source_meta.get("profile_hydration") == "url_only_pending_video_lookup"


def test_match_item_to_entry_prefers_video_url_over_profile_url():
    entry = {
        "url": YOUTUBE_VIDEO,
        "platform": "youtube",
        "link_type": "post",
        "source_post_url": YOUTUBE_VIDEO,
    }
    item = CollectedInfluencer(
        platform="youtube",
        username="channel123",
        profile_url="https://www.youtube.com/channel/UC1234567890",
        source_post_url=YOUTUBE_VIDEO,
        recent_post_urls=[YOUTUBE_VIDEO],
    )
    matched = _match_item_to_entry(item, [entry], matched_entry_urls=set())
    assert matched is entry


def test_match_item_to_entry_does_not_false_match_profile_only():
    entry = {
        "url": YOUTUBE_VIDEO,
        "platform": "youtube",
        "link_type": "post",
        "source_post_url": YOUTUBE_VIDEO,
    }
    item = CollectedInfluencer(
        platform="youtube",
        username="other",
        profile_url="https://www.youtube.com/channel/UC9999999999",
    )
    matched = _match_item_to_entry(item, [entry], matched_entry_urls=set())
    assert matched is None


@pytest.mark.anyio
async def test_process_provider_import_items_preserves_source_post_url(monkeypatch):
    from datetime import UTC, datetime

    entry = {
        "url": YOUTUBE_VIDEO,
        "platform": "youtube",
        "link_type": "post",
        "source_post_url": YOUTUBE_VIDEO,
    }
    item = CollectedInfluencer(
        platform="youtube",
        username="channel123",
        profile_url="https://www.youtube.com/channel/UC1234567890",
        source_post_url=YOUTUBE_VIDEO,
        recent_post_urls=[YOUTUBE_VIDEO],
    )
    exec_result = LinkImportExecuteResult()
    captured: dict[str, str | None] = {}

    async def _process_import_item(db, imported_item, *, source_post_url, source_input_url=None, run_at, product_id, task, exec_result):
        del db, imported_item, run_at, product_id, task, exec_result
        captured["source_post_url"] = source_post_url
        captured["source_input_url"] = source_input_url

    monkeypatch.setattr(LinkImportService, "_process_import_item", _process_import_item)
    monkeypatch.setattr(
        "app.services.link_import.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )

    await _process_provider_import_items(
        None,
        platform="youtube",
        entries=[entry],
        items=[item],
        product_id=1,
        task=object(),
        run_at=datetime.now(UTC),
        exec_result=exec_result,
    )

    assert captured["source_post_url"] == YOUTUBE_VIDEO
    assert captured["source_input_url"] == YOUTUBE_VIDEO


@pytest.mark.anyio
async def test_instagram_post_import_uses_post_author_discovery(monkeypatch):
    from datetime import UTC, datetime

    post_discovery = DiscoveryResult(
        candidates=[
            PostAuthorCandidate(
                username="creator",
                profile_url="https://www.instagram.com/creator/",
                source_post_url=INSTAGRAM_POST,
            )
        ],
        post_urls=[INSTAGRAM_POST],
    )
    scrape_result = ProfileScrapeResult(
        profiles=[
            CollectedInfluencer(
                platform="instagram",
                username="creator",
                profile_url="https://www.instagram.com/creator/",
                followers_count=1000,
                engagement_rate=2.0,
            )
        ]
    )

    discover_mock = AsyncMock(return_value=post_discovery)
    scrape_mock = AsyncMock(return_value=scrape_result)
    monkeypatch.setattr("app.services.link_import.resolve_import_link", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.link_import.discover_post_authors_from_post_urls", discover_mock)
    monkeypatch.setattr("app.services.link_import.scrape_instagram_profiles", scrape_mock)
    monkeypatch.setattr(
        "app.services.link_import.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )

    captured: dict[str, str | None] = {}

    async def _process_import_item(db, item, *, source_post_url, source_input_url=None, run_at, product_id, task, exec_result):
        del db, item, run_at, product_id, task, exec_result
        captured["source_post_url"] = source_post_url
        captured["source_input_url"] = source_input_url

    monkeypatch.setattr(LinkImportService, "_process_import_item", _process_import_item)

    exec_result = LinkImportExecuteResult()
    await LinkImportService._execute_url_import(
        None,
        valid_urls=[
            {
                "url": INSTAGRAM_POST,
                "platform": "instagram",
                "link_type": "post",
                "source_post_url": INSTAGRAM_POST,
            }
        ],
        invalid_urls=[],
        product_id=1,
        task=object(),
        run_at=datetime.now(UTC),
    )

    discover_mock.assert_awaited_once()
    scrape_mock.assert_awaited_once()
    assert captured["source_post_url"] == INSTAGRAM_POST
    assert captured["source_input_url"] == INSTAGRAM_POST


def test_ltk_product_url_preserves_source_post_url():
    from app.services.platform_providers.url_only import PARSERS

    url = "https://www.shopltk.com/explore/creator/product/123"
    profile = PARSERS["ltk"](url)
    assert profile is not None
    assert profile.profile_url == "https://www.shopltk.com/explore/creator"
    assert profile.source_post_url == url
    item = profile_to_collected(profile)
    assert item.profile_url == "https://www.shopltk.com/explore/creator"
    assert item.source_post_url == url


def test_export_column_label_source_post_url():
    labels = [label for _, label, _ in CANDIDATE_BUSINESS_EXPORT_COLUMNS]
    assert "来源作品链接" in labels
    assert "来源帖子" not in labels


@pytest.mark.anyio
async def test_hydrate_url_import_video_profiles_survives_connect_error(monkeypatch):
    import httpx

    from app.services.platform_providers.youtube_api_direct import _hydrate_url_import_video_profiles

    profile = _profile_from_input_url(YOUTUBE_VIDEO)
    assert profile is not None
    errors: list[str] = []

    async def _boom(*args, **kwargs):
        del args, kwargs
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(
        "app.services.platform_providers.youtube_api_direct._ad_get_timed",
        _boom,
    )
    result = await _hydrate_url_import_video_profiles([profile], errors=errors, keyword_timeout=1)
    assert len(result) == 1
    assert result[0].source_post_url == YOUTUBE_VIDEO
    assert errors
    assert "网络请求失败" in errors[0]
