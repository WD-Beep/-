"""多平台 API Direct 采集测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateStatus
from app.services.api_direct_client import reset_request_budget
from app.services.api_direct_provider import (
    discover_platform,
    list_platform_capabilities,
    normalize_platforms,
)
from app.services.collection_filters import evaluate_post_hydration_hard_filter
from app.services.collection_runner import CollectionRunnerService
from app.services.multi_platform_runner import determine_multi_platform_status, merge_platform_results
from app.services.platform_providers.facebook_api_direct import FacebookApiDirectProvider
from app.services.platform_providers.tiktok_api_direct import (
    TikTokApiDirectProvider,
    _extract_author_from_video,
)
from app.services.platform_providers.youtube_api_direct import _profile_from_channel
from app.services.platform_types import PlatformCandidateProfile, PlatformDiscoveryResult
from app.services.platform_utils import candidate_row_from_profile, dedupe_profiles, profile_outcome_key, profile_to_collected
from app.services.value_tier import classify_value_tier
from app.models.enums import CollectionTaskStatus
from app.collectors import get_collector


def test_normalize_platforms_from_legacy_platform():
    assert normalize_platforms("instagram", []) == ["instagram"]
    assert normalize_platforms("instagram", ["tiktok", "youtube"]) == ["tiktok", "youtube"]


def test_dedupe_profiles_by_platform_and_profile_url():
    from app.services.platform_types import PlatformCandidateProfile

    profiles = [
        PlatformCandidateProfile(
            platform="tiktok",
            username="a",
            profile_url="https://www.tiktok.com/@a",
        ),
        PlatformCandidateProfile(
            platform="tiktok",
            username="a",
            profile_url="https://www.tiktok.com/@a/",
        ),
        PlatformCandidateProfile(
            platform="youtube",
            username="a",
            profile_url="https://www.youtube.com/@a",
        ),
    ]
    deduped = dedupe_profiles(profiles)
    assert len(deduped) == 2


def test_extract_tiktok_author_from_video():
    profile = _extract_author_from_video(
        {
            "author": "chefmike",
            "author_name": "Chef Mike",
            "author_avatar": "https://cdn.example/avatar.jpg",
            "url": "https://www.tiktok.com/@chefmike/video/1",
            "play_count": 1000,
            "likes": 100,
            "comments": 10,
        },
        source_keyword="cooking",
    )
    assert profile is not None
    assert profile.username == "chefmike"
    assert profile.display_name == "Chef Mike"
    assert profile.profile_url == "https://www.tiktok.com/@chefmike"
    assert profile.source_meta.get("profile_hydration") == "profile_hydration_unavailable"


def test_tiktok_unknown_followers_blocked_when_min_followers_set():
    task = CollectionTask(
        name="t",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["cooking"],
        min_followers_count=10_000,
    )
    item = SimpleNamespace(
        platform="tiktok",
        username="chef",
        profile_url="https://www.tiktok.com/@chef",
        followers_count=None,
        bio="cooking",
        display_name=None,
        category=None,
        niche=None,
        country=None,
        language=None,
        content_topics=None,
        recent_post_titles=None,
        tags=None,
        collaboration_formats=None,
        engagement_rate=None,
    )
    result = evaluate_post_hydration_hard_filter(item, task)
    assert not result.passed
    assert result.reason == "below_min_followers"


def test_tiktok_provider_fails_without_apify_token():
    from app.services.platform_providers.tiktok_apify import TikTokApifyProvider

    task = CollectionTask(
        name="t",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["cooking"],
        collection_mode="discovery",
    )
    with patch.object(settings, "tiktok_data_provider", "apify"):
        with patch.object(settings, "api_direct_api_key", "test-key"):
            with patch.object(settings, "apify_token", ""):
                cap = TikTokApifyProvider.capability()
                assert cap.status == "not_configured"

                async def _run():
                    return await TikTokApifyProvider.discover(task)

                result = anyio.run(_run)
    assert result.skipped is True
    assert result.fatal is True
    assert "APIFY_TOKEN" in (result.skip_reason or "")


def test_youtube_not_configured_returns_clear_error():
    from app.services.platform_providers.youtube_api_direct import YouTubeApiDirectProvider

    task = CollectionTask(
        name="t",
        platform="youtube",
        platforms=["youtube"],
        keywords=["tutorial"],
        collection_mode="keyword",
    )
    with patch.object(settings, "api_direct_api_key", ""):
        async def _run():
            return await YouTubeApiDirectProvider.discover(task)

        result = anyio.run(_run)
    assert result.skipped is True
    assert "未配置" in (result.skip_reason or "")


def test_youtube_collect_snippet_links_from_real_post_shape():
    from app.services.platform_providers.youtube_api_direct import _collect_snippet_links_by_channel

    posts = [
        {
            "channel_id": "UCjFszKQ1yE9FJhHHqb5HQpg",
            "snippet": "Home Decor Ideas! Shop My Home: https://urlgeni.us/amzn/shopmyhomehere If you've ever watched",
        }
    ]
    links = _collect_snippet_links_by_channel(posts)
    assert "UCjFszKQ1yE9FJhHHqb5HQpg" in links
    assert links["UCjFszKQ1yE9FJhHHqb5HQpg"][0]["label"] == "Shop"
    assert "urlgeni.us/amzn/shopmyhomehere" in links["UCjFszKQ1yE9FJhHHqb5HQpg"][0]["url"]


def test_youtube_about_html_extracts_lnktr_shop_link():
    from app.services.platform_providers.youtube_api_direct import _extract_about_links_from_html

    html = """
    "channelExternalLinkViewModel": {
      "title": {"content": "Shop"},
      "link": {"content": "https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Flnktr.ee%2FTheSommerHomeYT"}
    }
    """
    links = _extract_about_links_from_html(html)
    assert any("lnktr.ee/TheSommerHomeYT" in link["url"] for link in links)
    assert any(link["label"] == "Shop" for link in links)


def test_youtube_about_html_extracts_visible_channel_links():
    from app.services.platform_providers.youtube_api_direct import _extract_about_links_from_html

    html = """
    <span>Sell.Amazon.com</span>
    <a href="https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Famzn.to%2F3RQibsQ">amzn.to/3RQibsQ</a>
    <a href="https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Finstagram.com%2Fsellonamazon">Instagram</a>
    <a href="https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Ffacebook.com%2FSellonAmazon">Facebook</a>
    <a href="https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Flinkedin.com%2Fshowcase%2Fsellwithamazon">LinkedIn</a>
    <a href="https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Ftwitter.com%2FSell_on_amazon">X</a>
    """
    links = _extract_about_links_from_html(html)
    urls = {link["url"] for link in links}
    assert "https://amzn.to/3RQibsQ" in urls
    assert "https://instagram.com/sellonamazon" in urls
    assert "https://facebook.com/SellonAmazon" in urls
    assert "https://linkedin.com/showcase/sellwithamazon" in urls
    assert "https://twitter.com/Sell_on_amazon" in urls
    amazon = next(link for link in links if link["url"] == "https://amzn.to/3RQibsQ")
    assert amazon["type"] == "amazon_storefront"


def test_youtube_yt_initial_data_extracts_lnktr_shop_link():
    from app.services.platform_providers.youtube_api_direct import _extract_about_links_from_html

    html = """
    <script>var ytInitialData = {
      "contents": {
        "aboutChannelRenderer": {
          "links": [{
            "channelExternalLinkViewModel": {
              "title": {"simpleText": "Shop"},
              "link": {"content": "https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Flnktr.ee%2FTheSommerHomeYT"}
            }
          }]
        }
      }
    };</script>
    """
    links = _extract_about_links_from_html(html)
    assert any("lnktr.ee/TheSommerHomeYT" in link["url"] for link in links)
    assert any(link["label"] == "Shop" for link in links)


def test_youtube_innertube_payload_extracts_lnktr_shop_link():
    from app.services.platform_providers.youtube_api_direct import _extract_links_from_yt_payload

    payload = {
        "onResponseReceivedEndpoints": [
            {
                "appendContinuationItemsAction": {
                    "continuationItems": [
                        {
                            "aboutChannelRenderer": {
                                "metadata": {
                                    "aboutChannelViewModel": {
                                        "links": [
                                            {
                                                "channelExternalLinkViewModel": {
                                                    "title": {"content": "Shop"},
                                                    "link": {
                                                        "content": "https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Flnktr.ee%2FTheSommerHomeYT"
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        ]
    }
    links = _extract_links_from_yt_payload(payload)
    assert any("lnktr.ee/TheSommerHomeYT" in link["url"] for link in links)
    assert any(link["label"] == "Shop" for link in links)


def test_youtube_capability_notes_about_link_limit():
    from app.services.platform_providers.youtube_api_direct import YouTubeApiDirectProvider

    with patch.object(settings, "api_direct_api_key", "test-key"):
        cap = YouTubeApiDirectProvider.capability()
    assert cap.status == "supported"
    assert "About" in cap.message
    assert "/v1/youtube/channels" in cap.message


def test_collection_runner_detects_other_social_link_changes():
    from types import SimpleNamespace

    from app.services.collection_runner import CollectionRunnerService

    existing = SimpleNamespace(
        username="creator",
        display_name="Creator",
        bio="bio",
        followers_count=1000,
        engagement_rate=1.0,
        email=None,
        final_email=None,
        website=None,
        contact_page=None,
        linktree_url=None,
        whatsapp=None,
        telegram=None,
        contact_fetch_status=None,
        product_fit=None,
        travel_fit_score=None,
        purchasing_power_score=None,
        sales_potential_score=None,
        audience_match_score=None,
        roi_forecast=None,
        other_social_links=[],
        category=None,
        country=None,
        language=None,
    )
    data = SimpleNamespace(
        username="creator",
        display_name="Creator",
        bio="bio",
        followers_count=1000,
        engagement_rate=1.0,
        email=None,
        final_email=None,
        website=None,
        contact_page=None,
        linktree_url="https://lnktr.ee/TheSommerHomeYT",
        whatsapp=None,
        telegram=None,
        contact_fetch_status=None,
        product_fit=None,
        travel_fit_score=None,
        purchasing_power_score=None,
        sales_potential_score=None,
        audience_match_score=None,
        roi_forecast=None,
        other_social_links=[{"type": "linktree", "label": "Shop", "url": "https://lnktr.ee/TheSommerHomeYT"}],
        score=None,
        risk_level=None,
        category=None,
        country=None,
        language=None,
    )
    assert CollectionRunnerService._has_changes(existing, data, None)


def test_youtube_channel_shop_lnktr_link_preserved():
    profile = _profile_from_channel(
        {
            "channel_id": "UCsommer",
            "title": "The Sommer Home",
            "url": "https://www.youtube.com/channel/UCsommer",
            "description": "Home decor and Amazon finds",
            "subscriber_count": "125K",
            "links": [
                {
                    "title": "Shop",
                    "url": "https://www.youtube.com/redirect?event=channel_description&q=https%3A%2F%2Flnktr.ee%2FTheSommerHomeYT",
                },
            ],
        },
        source_keyword="home decor",
        source_type="keyword_channel",
    )

    assert profile is not None
    shop_links = [link for link in profile.other_social_links if "lnktr.ee" in link["url"]]
    assert shop_links
    assert shop_links[0]["label"] == "Shop"
    assert shop_links[0]["type"] == "linktree"

    item = profile_to_collected(profile)
    assert item.linktree_url == "https://lnktr.ee/TheSommerHomeYT"
    assert any(link.get("label") == "Shop" for link in item.other_social_links or [])
    assert classify_value_tier(item)[0] == "direct_contact"


def test_youtube_channel_about_links_are_collected_and_mapped():
    profile = _profile_from_channel(
        {
            "channel_id": "UC123",
            "title": "Landing Cube",
            "url": "https://www.youtube.com/channel/UC123",
            "description": "Amazon seller tips",
            "subscriber_count": "12.5K",
            "links": [
                {"title": "Check it Out", "url": "https://landingcube.com"},
                {"title": "Community", "url": "https://facebook.com/groups/amazon.brand.building"},
                {"title": "Twitter", "url": "https://twitter.com/LandingCube"},
                {"title": "Instagram", "url": "https://instagram.com/landingcube"},
            ],
        },
        source_keyword="amazon",
        source_type="keyword_channel",
    )

    assert profile is not None
    assert profile.website == "https://landingcube.com"
    assert {link["label"] for link in profile.other_social_links} >= {
        "Check it Out",
        "Facebook",
        "Twitter",
        "Instagram",
    }

    item = profile_to_collected(profile)
    assert item.website == "https://landingcube.com"
    assert [link["url"] for link in item.other_social_links] == [
        "https://landingcube.com",
        "https://facebook.com/groups/amazon.brand.building",
        "https://twitter.com/LandingCube",
        "https://instagram.com/landingcube",
    ]
    assert classify_value_tier(item)[0] == "direct_contact"


def test_youtube_channel_linktree_outside_bio_becomes_contact_link():
    profile = _profile_from_channel(
        {
            "channel_id": "UC456",
            "title": "Creator Shop",
            "url": "https://www.youtube.com/channel/UC456",
            "description": "Reviews and deals",
            "external_links": [
                {"label": "Links", "url": "https://linktr.ee/creator.shop"},
            ],
        },
        source_keyword="deals",
        source_type="keyword_channel",
    )

    assert profile is not None
    item = profile_to_collected(profile)
    assert item.linktree_url == "https://linktr.ee/creator.shop"
    assert classify_value_tier(item)[0] == "direct_contact"


def test_youtube_channel_unwraps_redirected_amazon_short_link():
    profile = _profile_from_channel(
        {
            "channel_id": "UC789",
            "title": "Amazon Finds",
            "url": "https://www.youtube.com/channel/UC789",
            "description": "Amazon finds and product reviews",
            "links": [
                {
                    "title": "亚马逊",
                    "url": "https://www.youtube.com/redirect?event=channel_description&redir_token=abc&q=https%3A%2F%2Famzn.to%2F3XENIP0",
                },
            ],
        },
        source_keyword="amazon",
        source_type="keyword_channel",
    )

    assert profile is not None
    assert len(profile.other_social_links) == 1
    assert profile.other_social_links[0]["type"] == "amazon_storefront"
    assert profile.other_social_links[0]["url"] == "https://amzn.to/3XENIP0"
    item = profile_to_collected(profile)
    assert classify_value_tier(item)[0] == "direct_contact"


def test_youtube_instagram_only_external_link_is_direct_contact():
    profile = _profile_from_channel(
        {
            "channel_id": "UC999",
            "title": "Creator Only IG",
            "url": "https://www.youtube.com/channel/UC999",
            "description": "Find me on Instagram",
            "links": [
                {"title": "Instagram", "url": "https://instagram.com/creator.only"},
            ],
        },
        source_keyword="creator",
        source_type="keyword_channel",
    )
    item = profile_to_collected(profile)
    assert classify_value_tier(item)[0] == "direct_contact"


def test_youtube_email_verification_required_marks_manual_status():
    profile = _profile_from_channel(
        {
            "channel_id": "UC888",
            "title": "Verified Email Channel",
            "url": "https://www.youtube.com/channel/UC888",
            "email": "creator@example.com",
            "email_verification_required": True,
        },
        source_keyword="creator",
        source_type="keyword_channel",
    )
    item = profile_to_collected(profile)
    assert item.contact_fetch_status == "verification_required"
    tier, _, reason = classify_value_tier(item)
    assert tier == "direct_contact"
    assert "人工验证" in reason


def test_youtube_video_titles_merge_into_collected_item():
    from app.services.platform_providers.youtube_api_direct import _merge_channel_details, _profile_from_post

    video = _profile_from_post(
        {
            "channel_id": "UC777",
            "author": "Deal Reviewer",
            "title": "Amazon product review and shopping deals",
            "url": "https://www.youtube.com/watch?v=abc",
            "views": 88000,
        },
        source_keyword="amazon",
    )
    channel = _profile_from_channel(
        {
            "channel_id": "UC777",
            "title": "Deal Reviewer",
            "url": "https://www.youtube.com/channel/UC777",
            "subscriber_count": "120K",
            "links": [{"title": "ShopMy", "url": "https://shopmy.us/dealreviewer"}],
        },
        source_keyword="amazon",
        source_type="keyword_channel",
    )
    merged = _merge_channel_details([video], [channel])[0]
    item = profile_to_collected(merged)
    assert "Amazon product review" in " ".join(item.recent_post_titles)
    assert item.other_social_links
    assert classify_value_tier(item)[0] != "skip"


def test_youtube_discover_uses_configured_keyword_concurrency():
    from app.services.platform_providers.youtube_api_direct import YouTubeApiDirectProvider

    task = CollectionTask(
        name="t",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazon", "home", "deals"],
        collection_mode="discovery",
        discovery_limit=10,
    )
    observed: list[int] = []

    async def fake_map_bounded(items, worker, *, concurrency):
        observed.append(concurrency)
        return []

    async def _run():
        reset_request_budget()
        with patch.object(settings, "api_direct_api_key", "test-key"):
            with patch.object(settings, "youtube_api_direct_keyword_concurrency", 2):
                with patch.object(settings, "collection_search_concurrency", 4):
                    with patch(
                        "app.services.platform_providers.youtube_api_direct.map_bounded",
                        side_effect=fake_map_bounded,
                    ):
                        await YouTubeApiDirectProvider.discover(task)

    anyio.run(_run)
    assert observed
    assert observed[0] == 2

    from app.services.platform_providers.facebook_api_direct import FacebookApiDirectProvider

    task = CollectionTask(
        name="t",
        platform="facebook",
        platforms=["facebook"],
        keywords=["tech"],
        collection_mode="keyword",
    )
    with patch.object(settings, "api_direct_api_key", ""):
        async def _run():
            return await FacebookApiDirectProvider.discover(task)

        result = anyio.run(_run)
    assert result.skipped is True
    assert "未配置" in (result.skip_reason or "")


def test_multi_platform_one_failure_other_continues():
    ok = PlatformDiscoveryResult(
        platform="tiktok",
        items=[object()],
        discovered_count=1,
        deduped_count=1,
        profile_fetched_count=1,
        api_requests=1,
    )
    bad = PlatformDiscoveryResult(
        platform="youtube",
        fatal=True,
        skipped=True,
        skip_reason="未配置 API_DIRECT_API_KEY",
        errors=["未配置 API_DIRECT_API_KEY"],
    )
    aggregate = merge_platform_results(
        instagram_result=None,
        instagram_funnel=None,
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[bad, ok],
    )
    status = determine_multi_platform_status(
        aggregate,
        inserted_count=1,
        instagram_only=False,
        instagram_fatal=False,
    )
    assert status == CollectionTaskStatus.PARTIAL_FAILED
    assert "tiktok" in aggregate.platform_successes
    assert aggregate.platform_failures


def test_nonfatal_youtube_timeout_without_results_is_not_platform_failure():
    slow_no_result = PlatformDiscoveryResult(
        platform="youtube",
        api_requests=1,
        errors=["YouTube Apify 搜索「amazonfinds」超时（>25s），已跳过该关键词并继续"],
        fatal=False,
    )
    aggregate = merge_platform_results(
        instagram_result=None,
        instagram_funnel=None,
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[slow_no_result],
    )
    status = determine_multi_platform_status(
        aggregate,
        inserted_count=0,
        instagram_only=False,
        instagram_fatal=False,
    )
    assert status == CollectionTaskStatus.COMPLETED_NO_RESULTS
    assert aggregate.platform_failures == []
    assert aggregate.collection_errors


def test_list_platform_capabilities_includes_four_platforms():
    with patch.object(settings, "api_direct_api_key", "test-key"):
        caps = list_platform_capabilities()
    platforms = {cap.platform for cap in caps}
    assert platforms == {
        "instagram",
        "tiktok",
        "youtube",
        "facebook",
        "pinterest",
        "ltk",
        "shopmy",
        "amazon",
    }
    status_by_platform = {cap.platform: cap.status for cap in caps}
    assert status_by_platform["pinterest"] == "url_only"
    assert status_by_platform["ltk"] == "url_only"
    assert status_by_platform["shopmy"] == "url_only"
    flags = {cap.platform: cap.keyword_discovery for cap in caps}
    assert flags["instagram"] is True
    assert flags["pinterest"] is False
    assert flags["amazon"] is False


def test_url_only_platforms_parse_input_urls():
    cases = [
        ("pinterest", "https://www.pinterest.com/targetcreator/", "targetcreator"),
        ("ltk", "https://www.shopltk.com/explore/targetcreator/product/abc", "targetcreator"),
        ("shopmy", "https://shopmy.us/targetcreator", "targetcreator"),
    ]

    async def _run(platform: str, url: str):
        task = CollectionTask(
            name="t",
            platform=platform,
            platforms=[platform],
            input_urls=[url],
            collection_mode="urls",
        )
        return await discover_platform(task, platform)

    for platform, url, username in cases:
        result = anyio.run(_run, platform, url)
        assert result.skipped is False
        assert result.items
        assert result.items[0].platform == platform
        assert result.items[0].username == username
        assert result.items[0].source_discovery_type == "url_import"


def test_url_only_platform_keyword_only_is_clear_skip():
    task = CollectionTask(
        name="t",
        platform="pinterest",
        platforms=["pinterest"],
        keywords=["home decor"],
        collection_mode="keyword",
    )

    async def _run():
        return await discover_platform(task, "pinterest")

    result = anyio.run(_run)
    assert result.skipped is True
    assert result.fatal is True
    assert "URL" in (result.skip_reason or "")


def test_tiktok_discover_parses_videos_response():
    task = CollectionTask(
        name="t",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["cooking"],
        collection_mode="discovery",
        discovery_limit=10,
    )
    api_payload = {
        "videos": [
            {
                "author": "chef",
                "author_name": "Chef",
                "url": "https://www.tiktok.com/@chef/video/1",
                "play_count": 500,
                "likes": 50,
                "comments": 5,
            }
        ],
        "count": 1,
        "pages": 1,
    }

    async def _run():
        reset_request_budget()
        with patch.object(settings, "api_direct_api_key", "test-key"):
            with patch(
                "app.services.platform_providers.tiktok_api_direct.ad_get",
                new_callable=AsyncMock,
                return_value=api_payload,
            ):
                return await TikTokApiDirectProvider.discover(task)

    result = anyio.run(_run)
    assert len(result.items) == 1
    assert result.items[0].username == "chef"
    assert result.deduped_count == 1


def test_unknown_platform_returns_not_available():
    task = CollectionTask(name="t", platform="twitter", platforms=["twitter"], keywords=["x"])

    async def _run():
        return await discover_platform(task, "twitter")

    result = anyio.run(_run)
    assert result.skipped is True
    assert "暂未接入" in (result.skip_reason or "")


def test_get_collector_allows_instagram_when_api_direct_missing_for_other_platforms():
    task = CollectionTask(
        name="t",
        platform="multi",
        platforms=["instagram", "tiktok"],
        keywords=["travel"],
        collection_mode="discovery",
    )
    with patch.object(settings, "api_direct_api_key", ""):
        with patch("app.services.instagram_provider.ensure_instagram_provider_ready"):
            collector = get_collector(task)
    assert collector is not None


def test_facebook_provider_uses_pages_and_page_endpoints():
    task = CollectionTask(
        name="t",
        platform="facebook",
        platforms=["facebook"],
        keywords=["nike"],
        input_urls=["https://www.facebook.com/Meta"],
        collection_mode="keyword",
        discovery_limit=5,
    )
    calls: list[tuple[str, dict | None]] = []

    async def fake_ad_get(path, *, params=None, platform=None):
        calls.append((path, params))
        if path == "/v1/facebook/pages":
            return {
                "results": [
                    {
                        "name": "Nike",
                        "facebook_id": "15087023444",
                        "url": "https://www.facebook.com/nike",
                        "profile_url": "https://www.facebook.com/nike",
                        "image_url": "https://cdn.example/nike.jpg",
                        "is_verified": True,
                    }
                ],
                "count": 1,
                "pages": 1,
            }
        if path == "/v1/facebook/page":
            if (params or {}).get("url") == "https://www.facebook.com/nike":
                return {
                    "page": {
                        "name": "Nike",
                        "page_id": "15087023444",
                        "url": "https://www.facebook.com/nike",
                        "followers": "2.1M",
                        "intro": "Nike page",
                        "website": "https://nike.example",
                    }
                }
            return {
                "page": {
                    "name": "Meta",
                    "page_id": "139654476388086",
                    "url": "https://www.facebook.com/Meta",
                    "followers": 1000,
                    "intro": "Meta page",
                }
            }
        raise AssertionError(f"unexpected endpoint: {path}")

    async def _run():
        reset_request_budget()
        with patch.object(settings, "api_direct_api_key", "test-key"):
            with patch(
                "app.services.platform_providers.facebook_api_direct.ad_get",
                side_effect=fake_ad_get,
            ):
                return await FacebookApiDirectProvider.discover(task)

    result = anyio.run(_run)
    paths = [path for path, _ in calls]
    assert "/v1/facebook/pages" in paths
    assert "/v1/facebook/page" in paths
    assert "/v1/facebook/videos" not in paths
    assert len(result.items) >= 2
    assert not result.candidate_rows
    assert len(result.profiles) >= 2
    nike = next(profile for profile in result.profiles if profile.username == "nike")
    assert nike.followers_count == 2_100_000
    assert nike.website == "https://nike.example"


def test_facebook_provider_filters_low_value_people_results():
    task = CollectionTask(
        name="t",
        platform="facebook",
        platforms=["facebook"],
        keywords=["amazonfinds"],
        collection_mode="keyword",
        discovery_limit=5,
    )

    async def fake_ad_get(path, *, params=None, platform=None):
        if path == "/v1/facebook/pages":
            return {
                "results": [
                    {
                        "name": "Amazon Finds",
                        "facebook_id": "61590582474898",
                        "url": "https://www.facebook.com/people/Amazonfinds/61590582474898/",
                    },
                    {
                        "name": "Real Deals",
                        "facebook_id": "100063934985259",
                        "url": "https://www.facebook.com/realdeals",
                    },
                ],
                "count": 2,
                "pages": 1,
            }
        if path == "/v1/facebook/page":
            return {
                "page": {
                    "name": "Real Deals",
                    "page_id": "100063934985259",
                    "url": "https://www.facebook.com/realdeals",
                    "followers": 12000,
                    "intro": "Amazon product reviews and deals",
                }
            }
        raise AssertionError(f"unexpected endpoint: {path}")

    async def _run():
        reset_request_budget()
        with patch.object(settings, "api_direct_api_key", "test-key"):
            with patch(
                "app.services.platform_providers.facebook_api_direct.ad_get",
                side_effect=fake_ad_get,
            ):
                return await FacebookApiDirectProvider.discover(task)

    result = anyio.run(_run)
    assert [profile.profile_url for profile in result.profiles] == [
        "https://www.facebook.com/realdeals"
    ]
    assert result.profiles[0].followers_count == 12000


def test_platform_candidate_rows_match_upsert_outcomes():
    from datetime import UTC, datetime

    task = CollectionTask(
        name="t",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["cooking"],
        collection_mode="discovery",
    )
    profile = PlatformCandidateProfile(
        platform="tiktok",
        username="chef",
        profile_url="https://www.tiktok.com/@chef",
        source_type="keyword_video_author",
        source_discovery_type="video_author",
        source_meta={"source_keyword": "cooking", "endpoint": "/v1/tiktok/videos"},
    )
    item = SimpleNamespace(
        platform="tiktok",
        username="chef",
        profile_url="https://www.tiktok.com/@chef",
        followers_count=None,
        engagement_rate=1.2,
    )
    key = profile_outcome_key("tiktok", profile.profile_url)
    outcomes = {
        key: {"status": "inserted", "item": item, "product_influencer_id": 42, "global_influencer_id": 7},
    }
    rows = CollectionRunnerService._build_platform_candidate_rows(
        task,
        [profile],
        outcomes,
        run_at=datetime.now(UTC),
    )
    assert len(rows) == 1
    assert rows[0]["status"] == CandidateStatus.INSERTED.value
    assert rows[0]["product_influencer_id"] == 42
    assert rows[0]["global_influencer_id"] == 7
    assert rows[0]["platform"] == "tiktok"


def test_tiktok_hydration_stops_after_enough_qualified_profiles():
    task = CollectionTask(
        name="t",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["cooking"],
        collection_mode="discovery",
        discovery_limit=2,
        min_followers_count=10_000,
    )
    video_payload = {
        "videos": [
            {
                "author": f"creator{i}",
                "author_name": f"Creator {i}",
                "url": f"https://www.tiktok.com/@creator{i}/video/1",
                "play_count": 1000 * (10 - i),
                "likes": 100 * (10 - i),
                "comments": 10,
            }
            for i in range(1, 7)
        ],
        "count": 6,
        "pages": 1,
    }
    user_calls: list[str] = []

    async def fake_ad_get(path, *, params=None, platform=None):
        if path == "/v1/tiktok/videos":
            return video_payload
        handle = (params or {}).get("query")
        user_calls.append(str(handle))
        return {
            "users": [
                {
                    "username": handle,
                    "nickname": handle,
                    "followers": 50_000,
                    "bio": "amazon finds",
                    "url": f"https://www.tiktok.com/@{handle}",
                }
            ]
        }

    async def _run():
        reset_request_budget()
        with patch.object(settings, "api_direct_api_key", "test-key"):
            with patch.object(settings, "api_direct_max_requests_per_platform", 20):
                with patch(
                    "app.services.platform_providers.tiktok_api_direct.ad_get",
                    side_effect=fake_ad_get,
                ):
                    return await TikTokApiDirectProvider.discover(task)

    result = anyio.run(_run)
    assert result.deduped_count == 6
    assert len(user_calls) <= 6
    assert len(user_calls) >= 2
    assert result.profile_fetched_count >= 2
    assert result.api_requests <= 20


def test_tiktok_pages_default_to_one_and_region_from_country():
    task = CollectionTask(
        name="t",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["cooking"],
        country="US",
        collection_mode="discovery",
        discovery_limit=10,
    )
    captured: list[dict] = []

    async def fake_ad_get(path, *, params=None, platform=None):
        captured.append(params or {})
        return {"videos": [], "count": 0, "pages": 1}

    async def _run():
        reset_request_budget()
        with patch.object(settings, "api_direct_api_key", "test-key"):
            with patch.object(settings, "api_direct_tiktok_default_pages", 1):
                with patch.object(settings, "api_direct_max_pages_per_request", 1):
                    with patch(
                        "app.services.platform_providers.tiktok_api_direct.ad_get",
                        side_effect=fake_ad_get,
                    ):
                        return await TikTokApiDirectProvider.discover(task)

    anyio.run(_run)
    assert captured
    assert captured[0]["pages"] >= 1
    assert captured[0]["region"] == "us"


def test_youtube_search_and_about_concurrency_helpers():
    from app.services.platform_providers import youtube_api_direct as mod

    with patch.object(settings, "youtube_api_direct_keyword_concurrency", 2):
        with patch.object(settings, "collection_search_concurrency", 4):
            assert mod._youtube_keyword_search_concurrency() == 2
    with patch.object(settings, "youtube_api_direct_keyword_concurrency", 5):
        with patch.object(settings, "collection_search_concurrency", 3):
            assert mod._youtube_keyword_search_concurrency() == 3
    assert mod.YOUTUBE_ABOUT_HYDRATION_CONCURRENCY == 2


def test_is_rate_limit_error_detects_api_direct_429():
    from app.services.api_direct_client import ApiDirectError, is_rate_limit_error

    assert is_rate_limit_error(ApiDirectError("限流", status_code=429))
    assert is_rate_limit_error(ApiDirectError("API Direct 请求失败 (429): too many"))
    assert not is_rate_limit_error(ApiDirectError("bad request", status_code=400))


def test_youtube_html_href_redirect_unwraps_amzn_to():
    from app.services.platform_providers.youtube_api_direct import _extract_about_links_from_html

    html = (
        '<a href="https://www.youtube.com/redirect?event=channel_description&amp;q='
        'https%3A%2F%2Famzn.to%2F3RQibsQ">Shop</a>'
        '<a href="https://www.youtube.com/redirect?q=https%3A%2F%2Finstagram.com%2Fsellonamazon">Instagram</a>'
    )
    links = _extract_about_links_from_html(html)
    urls = {link["url"] for link in links}
    assert "https://amzn.to/3RQibsQ" in urls
    assert "https://instagram.com/sellonamazon" in urls
    shop = next(link for link in links if "amzn.to" in link["url"])
    assert shop["type"] == "amazon_storefront"


def test_youtube_discover_marks_rate_limited_without_fatal_when_partial_results():
    from app.services.platform_providers.youtube_api_direct import YouTubeApiDirectProvider
    from app.services.api_direct_client import ApiDirectError

    task = CollectionTask(
        name="yt-rate",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazon seller"],
        collection_mode="keyword",
        discovery_limit=5,
    )

    calls = {"n": 0}

    async def fake_ad_get(path, *, params=None, platform=None):
        calls["n"] += 1
        if path == "/v1/youtube/channels":
            return {
                "channels": [
                    {
                        "channel_id": "UC123",
                        "title": "Sell on Amazon",
                        "url": "https://www.youtube.com/channel/UC123",
                        "subscriber_count": "100K",
                    }
                ]
            }
        if path == "/v1/youtube/posts":
            raise ApiDirectError("API Direct 请求失败 (429): rate", status_code=429)
        return {"posts": [], "count": 0, "pages": 1}

    async def _run():
        reset_request_budget()
        with patch.object(settings, "api_direct_api_key", "test-key"):
            with patch(
                "app.services.platform_providers.youtube_api_direct.ad_get",
                side_effect=fake_ad_get,
            ):
                with patch(
                    "app.services.platform_providers.youtube_api_direct._hydrate_profiles_about",
                    side_effect=lambda profiles: profiles,
                ):
                    return await YouTubeApiDirectProvider.discover(task)

    result = anyio.run(_run)
    assert result.rate_limited is True
    assert result.rate_limit_count >= 1
    assert result.deduped_count >= 1
    assert result.fatal is False
    assert any("限流" in err for err in result.errors)


def test_youtube_apify_profile_maps_channel_links_and_amazon():
    from app.services.platform_providers.youtube_apify import _profile_from_apify_item

    profile = _profile_from_apify_item(
        {
            "channelName": "Sell on Amazon",
            "channelUrl": "https://www.youtube.com/@SellOnAmazon",
            "numberOfSubscribers": 120000,
            "title": "How to sell on Amazon",
            "url": "https://www.youtube.com/watch?v=abc123",
            "viewCount": 50000,
            "channelDescriptionLinks": [
                {"text": "Amazon Shop", "url": "https://amzn.to/3RQibsQ"},
                {"text": "Instagram", "url": "https://instagram.com/sellonamazon"},
            ],
        },
        source_keyword="amazon seller",
    )
    assert profile is not None
    assert profile.followers_count == 120000
    assert profile.source_meta.get("provider") == "apify"
    link_types = {link["type"] for link in profile.other_social_links}
    assert "amazon_storefront" in link_types
    assert "instagram" in link_types


def test_tiktok_provider_routes_to_apify_when_configured():
    from app.services.api_direct_provider import _provider_cls

    with patch.object(settings, "tiktok_data_provider", "apify"):
        assert _provider_cls("tiktok").__name__ == "TikTokApifyProvider"


def test_tiktok_apify_profile_maps_author_from_item():
    from app.services.platform_providers.tiktok_apify import _profile_from_apify_item

    profile = _profile_from_apify_item(
        {
            "authorMeta": {
                "name": "chefmike",
                "nickName": "Chef Mike",
                "fans": 120000,
                "avatar": "https://example.com/a.jpg",
                "signature": "Cooking daily",
            },
            "playCount": 50000,
            "diggCount": 1200,
            "commentCount": 88,
            "webVideoUrl": "https://www.tiktok.com/@chefmike/video/1",
            "text": "Best pasta",
        },
        source_keyword="cooking",
    )
    assert profile is not None
    assert profile.username == "chefmike"
    assert profile.followers_count == 120000
    assert profile.source_meta.get("provider") == "apify"


@pytest.mark.anyio
async def test_tiktok_apify_memory_limit_retries_with_lower_memory(monkeypatch):
    from app.services.apify_client import ApifyError
    from app.services.platform_providers.tiktok_apify import TikTokApifyProvider

    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "apify_tiktok_timeout_seconds", 30)
    monkeypatch.setattr(settings, "competitor_product_keyword_timeout_seconds", 30)
    monkeypatch.setattr(settings, "tiktok_apify_keyword_concurrency", 2)
    monkeypatch.setattr(settings, "tiktok_apify_memory_mbytes", 2048)

    calls = []

    async def fake_actor(actor_id, run_input, **kwargs):
        calls.append((run_input["searchQueries"][0], run_input["resultsPerPage"], kwargs.get("memory_mbytes")))
        if len(calls) == 1:
            raise ApifyError(
                "memory-limit-exceeded: current used: 5120MB, requested: 4096MB, account limit: 8192MB"
            )
        return [
            {
                "authorMeta": {"name": "homehivecreator", "fans": 12000},
                "text": "HOMEHIVE clear PVC jewelry bags review",
                "webVideoUrl": "https://www.tiktok.com/@homehivecreator/video/1",
            }
        ]

    task = CollectionTask(
        name="homehive",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["HOMEHIVE clear PVC jewelry bags"],
        collection_mode="competitor_product",
        discovery_limit=5,
    )

    with patch("app.services.platform_providers.tiktok_apify.run_actor_sync", side_effect=fake_actor):
        result = await TikTokApifyProvider.discover(task)

    assert result.fatal is False
    assert result.profiles
    assert len(calls) == 2
    assert calls[1][1] < calls[0][1]
    assert calls[1][2] <= calls[0][2]
    assert any("内存限制" in err and "降级重试 1 次" in err for err in result.errors)


@pytest.mark.anyio
async def test_tiktok_apify_timeout_continues_other_queries(monkeypatch):
    from app.services.platform_providers.tiktok_apify import TikTokApifyProvider

    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "apify_tiktok_timeout_seconds", 1)
    monkeypatch.setattr(settings, "competitor_product_keyword_timeout_seconds", 1)
    monkeypatch.setattr(settings, "tiktok_apify_keyword_concurrency", 1)
    monkeypatch.setattr(settings, "tiktok_apify_memory_mbytes", 2048)

    async def fake_actor(actor_id, run_input, **kwargs):
        keyword = run_input["searchQueries"][0]
        if keyword == "HOMEHIVE clear PVC jewelry bags":
            raise asyncio.TimeoutError()
        return [
            {
                "authorMeta": {"name": "variantcreator", "fans": 22000},
                "text": "HOMEHIVE 20 Clear Bags in clear PVC",
                "webVideoUrl": "https://www.tiktok.com/@variantcreator/video/1",
            }
        ]

    task = CollectionTask(
        name="homehive",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["HOMEHIVE clear PVC jewelry bags", "HOMEHIVE 20 Clear Bags"],
        collection_mode="competitor_product",
        discovery_limit=5,
    )

    with patch("app.services.platform_providers.tiktok_apify.run_actor_sync", side_effect=fake_actor):
        result = await TikTokApifyProvider.discover(task)

    assert result.fatal is False
    assert [profile.username for profile in result.profiles] == ["variantcreator"]
    assert any("query HOMEHIVE clear PVC jewelry bags" in err and "超时" in err for err in result.errors)


@pytest.mark.anyio
async def test_tiktok_apify_timeout_without_candidates_sets_provider_state(monkeypatch):
    from app.services.apify_client import ApifyError
    from app.services.platform_providers.tiktok_apify import TikTokApifyProvider

    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "apify_tiktok_timeout_seconds", 30)
    monkeypatch.setattr(settings, "competitor_product_keyword_timeout_seconds", 30)
    monkeypatch.setattr(settings, "tiktok_apify_keyword_concurrency", 1)

    async def fake_actor(actor_id, run_input, **kwargs):
        raise ApifyError("Apify 请求超时（>120s）")

    task = CollectionTask(
        name="amazon cn",
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["亚马逊带货红人"],
        collection_mode="discovery",
        discovery_limit=5,
    )

    with patch("app.services.platform_providers.tiktok_apify.run_actor_sync", side_effect=fake_actor):
        result = await TikTokApifyProvider.discover(task)

    state = result.provider_availability_state["tiktok"]
    assert state["reason"] == "timeout"
    assert state["api_calls"] == 1
    assert any("Apify 请求超时" in err for err in result.errors)


def test_youtube_provider_routes_to_apify_when_configured():
    from app.services.api_direct_provider import get_platform_capability

    with patch.object(settings, "youtube_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test"):
            cap = get_platform_capability("youtube")
    assert cap.status == "supported"


def test_facebook_provider_routes_to_apify_when_configured():
    from app.services.api_direct_provider import _provider_cls, get_platform_capability

    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test"):
            assert _provider_cls("facebook").__name__ == "FacebookApifyProvider"
            cap = get_platform_capability("facebook")
    assert cap.status == "supported"
    assert "Apify" in cap.message
    assert "Apify" in cap.message


def test_youtube_about_html_extracts_multiple_commercial_and_social_links():
    from app.services.platform_providers.youtube_api_direct import _extract_about_links_from_html

    html = """
    <a href="https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.tiktok.com%2F%40creator.shop">TikTok</a>
    <a href="https://www.youtube.com/redirect?q=https%3A%2F%2Finstagram.com%2Fcreator.shop">Instagram</a>
    <a href="https://www.youtube.com/redirect?q=https%3A%2F%2Fshopmy.us%2Fcreator-shop">ShopMy</a>
    <a href="https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.shopltk.com%2Fexplore%2Fcreator_shop">LTK</a>
    <a href="https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.amazon.com%2Fshop%2Fcreator.shop">Amazon storefront</a>
    <a href="https://www.youtube.com/redirect?q=https%3A%2F%2Flinktr.ee%2Fcreator.shop">Links</a>
    <a href="https://www.youtube.com/redirect?q=https%3A%2F%2Fcreator-shop.com">Website</a>
    """
    links = _extract_about_links_from_html(html)
    by_url = {link["url"]: link for link in links}

    assert by_url["https://www.tiktok.com/@creator.shop"]["type"] == "tiktok"
    assert by_url["https://instagram.com/creator.shop"]["type"] == "instagram"
    assert by_url["https://shopmy.us/creator-shop"]["type"] == "shopmy"
    assert by_url["https://www.shopltk.com/explore/creator_shop"]["type"] == "ltk"
    assert by_url["https://www.amazon.com/shop/creator.shop"]["type"] == "amazon_storefront"
    assert by_url["https://linktr.ee/creator.shop"]["type"] == "linktree"
    assert by_url["https://creator-shop.com"]["type"] == "website"


def test_youtube_profile_collects_all_about_and_homepage_links_for_explanations():
    profile = _profile_from_channel(
        {
            "channel_id": "UCmulti123",
            "title": "Creator Commerce Hub",
            "url": "https://www.youtube.com/channel/UCmulti123",
            "description": "Deals, reviews, and creator storefronts",
            "links": [
                {"title": "Amazon", "url": "https://www.amazon.com/shop/creator.shop"},
                {"title": "TikTok", "url": "https://www.tiktok.com/@creator.shop"},
                {"title": "Instagram", "url": "https://instagram.com/creator.shop"},
                {"title": "ShopMy", "url": "https://shopmy.us/creator-shop"},
                {"title": "LTK", "url": "https://www.shopltk.com/explore/creator_shop"},
                {"title": "Website", "url": "https://creator-shop.com"},
            ],
        },
        source_keyword="creator deals",
        source_type="keyword_channel",
    )

    assert profile is not None
    assert profile.website == "https://creator-shop.com"
    assert {link["type"] for link in profile.other_social_links} >= {
        "amazon_storefront",
        "tiktok",
        "instagram",
        "shopmy",
        "ltk",
        "website",
    }
    assert (profile.source_meta or {}).get("external_link_count", 0) >= 6
    assert set((profile.source_meta or {}).get("external_link_types") or []) >= {
        "amazon_storefront",
        "tiktok",
        "instagram",
        "shopmy",
        "ltk",
        "website",
    }


def test_youtube_more_dialog_extracts_links_email_and_contact_button():
    from app.services.platform_providers.youtube_api_direct import _extract_about_signals_from_html

    html = """
    <script>var ytInitialData = {
      "metadata": {
        "aboutChannelViewModel": {
          "description": "Business inquiries: business@thedealguy.com Visit https://thedealguy.com/deals",
          "links": [
            {"channelExternalLinkViewModel": {
              "title": {"content": "website"},
              "link": {"content": "https://www.youtube.com/redirect?q=https%3A%2F%2Fthedealguy.com"}
            }},
            {"channelExternalLinkViewModel": {
              "title": {"content": "Facebook"},
              "link": {"content": "https://www.youtube.com/redirect?q=https%3A%2F%2Ffacebook.com%2FTheDealGuy"}
            }},
            {"channelExternalLinkViewModel": {
              "title": {"content": "Twitter/X"},
              "link": {"content": "https://www.youtube.com/redirect?q=https%3A%2F%2Fx.com%2Fthedealguy"}
            }},
            {"channelExternalLinkViewModel": {
              "title": {"content": "Instagram"},
              "link": {"content": "https://www.youtube.com/redirect?q=https%3A%2F%2Finstagram.com%2Fthedealguy"}
            }}
          ],
          "actionButtons": [{"buttonViewModel": {"title": "View email address"}}]
        }
      }
    };</script>
    """

    signals = _extract_about_signals_from_html(html)
    by_type = {link["type"]: link for link in signals.links}

    assert by_type["website"]["url"] == "https://thedealguy.com"
    assert by_type["facebook"]["url"] == "https://facebook.com/TheDealGuy"
    assert by_type["twitter"]["url"] == "https://x.com/thedealguy"
    assert by_type["instagram"]["url"] == "https://instagram.com/thedealguy"
    assert signals.email == "business@thedealguy.com"
    assert signals.contact_button_present is True
    assert signals.email_unexpanded is True


def test_youtube_channel_description_extracts_email_and_urls():
    profile = _profile_from_channel(
        {
            "channel_id": "UCemail123",
            "title": "Creator With Email",
            "url": "https://www.youtube.com/channel/UCemail123",
            "description": "Business: Business@Creator-Shop.com Links: https://creator-shop.com https://linktr.ee/creator.shop",
        },
        source_keyword="deals",
        source_type="keyword_channel",
    )

    assert profile is not None
    assert profile.email == "business@creator-shop.com"
    assert profile.website == "https://creator-shop.com"
    assert {link["type"] for link in profile.other_social_links} >= {"website", "linktree"}
    assert profile.source_meta.get("email_source") == "youtube_description"


def test_youtube_redirect_normalizes_google_and_youtube_targets():
    from app.services.platform_providers.youtube_api_direct import _append_link

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    _append_link(
        links,
        seen,
        "https://www.google.com/url?q=https%3A%2F%2Fwww.instagram.com%2Fcreator.shop&sa=D",
        "Instagram",
    )
    _append_link(
        links,
        seen,
        "https://www.youtube.com/redirect?event=channel_description&url=https%3A%2F%2Fwww.tiktok.com%2F%40creator.shop",
        "TikTok",
    )

    assert links == [
        {"type": "instagram", "label": "Instagram", "url": "https://www.instagram.com/creator.shop"},
        {"type": "tiktok", "label": "TikTok", "url": "https://www.tiktok.com/@creator.shop"},
    ]


def test_youtube_hydration_failure_keeps_snippet_links_and_marks_status():
    from app.services.platform_providers.youtube_api_direct import _hydrate_profiles_about

    profile = PlatformCandidateProfile(
        platform="youtube",
        username="UCfallback",
        profile_url="https://www.youtube.com/channel/UCfallback",
        display_name="Fallback Creator",
        channel_id="UCfallback",
        other_social_links=[{"type": "linktree", "label": "Shop", "url": "https://linktr.ee/fallback"}],
    )

    async def _run():
        with patch(
            "app.services.platform_providers.youtube_api_direct._fetch_channel_about_signals",
            side_effect=RuntimeError("network blocked"),
        ):
            return await _hydrate_profiles_about([profile])

    hydrated = anyio.run(_run)[0]

    assert hydrated.other_social_links == profile.other_social_links
    assert hydrated.source_meta["about_links_hydrated"] is False
    assert hydrated.source_meta["about_links_fetch"] == "failed"
    assert "network blocked" in hydrated.source_meta["about_links_error"]
    item = profile_to_collected(hydrated)
    assert item.contact_fetch_status == "partial_failed"


def test_youtube_contact_button_present_without_email_is_recorded():
    from app.services.platform_providers.youtube_api_direct import _extract_about_signals_from_html

    html = """
    <script>var ytInitialData = {
      "metadata": {
        "aboutChannelViewModel": {
          "description": "For business inquiries use the button below.",
          "buttons": [{"buttonViewModel": {"title": "View email address"}}]
        }
      }
    };</script>
    """

    signals = _extract_about_signals_from_html(html)

    assert signals.email is None
    assert signals.contact_button_present is True
    assert signals.email_unexpanded is True


def test_youtube_apify_profile_extracts_description_email_and_links():
    from app.services.platform_providers.youtube_apify import _profile_from_apify_item

    profile = _profile_from_apify_item(
        {
            "channelName": "Deal Creator",
            "channelUrl": "https://www.youtube.com/@DealCreator",
            "channelDescription": "Business: deals@example.com Website https://dealcreator.com",
            "channelDescriptionLinks": [
                {"text": "Facebook", "url": "https://facebook.com/dealcreator"},
                {"text": "X", "url": "https://x.com/dealcreator"},
                {"text": "Instagram", "url": "https://instagram.com/dealcreator"},
            ],
        },
        source_keyword="deals",
    )

    assert profile is not None
    assert profile.email == "deals@example.com"
    assert profile.website == "https://dealcreator.com"
    assert {link["type"] for link in profile.other_social_links} >= {
        "website",
        "facebook",
        "twitter",
        "instagram",
    }
