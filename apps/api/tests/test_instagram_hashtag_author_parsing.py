"""Instagram hashtag post author extraction edge cases."""

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services.apify_instagram import discover_post_authors_from_hashtags


@pytest.mark.anyio
async def test_hashtag_posts_extract_author_from_alternate_fields(monkeypatch):
    monkeypatch.setattr(settings, "apify_instagram_hashtag_actor_id", "apify~instagram-hashtag-scraper")

    async def fake_actor(actor_id, run_input, **kwargs):
        return [
            {
                "owner": {"username": "nested_owner"},
                "shortCode": "AAA111",
                "caption": "HOMEHIVE clear PVC jewelry bags",
            },
            {
                "ownerProfileUrl": "https://www.instagram.com/owner_profile/",
                "shortCode": "BBB222",
            },
            {
                "userUrl": "https://www.instagram.com/user_url/",
                "shortCode": "CCC333",
            },
            {
                "author": {"url": "https://www.instagram.com/author_url/"},
                "shortCode": "DDD444",
            },
            {
                "inputUrl": "https://www.instagram.com/input_url/",
                "shortCode": "EEE555",
            },
        ]

    with patch("app.services.apify_instagram._require_real_collector"):
        with patch("app.services.apify_instagram.run_actor_sync", side_effect=fake_actor):
            result = await discover_post_authors_from_hashtags(["HOMEHIVEjewelrybags"], limit=10)

    usernames = {candidate.username for candidate in result.candidates}
    assert usernames == {"nested_owner", "owner_profile", "user_url", "author_url", "input_url"}
    assert not any("无法提取 ownerUsername/ownerUrl" in err for err in result.errors)


@pytest.mark.anyio
async def test_hashtag_posts_extract_author_from_deep_raw_payload(monkeypatch):
    monkeypatch.setattr(settings, "apify_instagram_hashtag_actor_id", "apify~instagram-hashtag-scraper")

    async def fake_actor(actor_id, run_input, **kwargs):
        return [
            {
                "shortCode": "RAW111",
                "url": "https://www.instagram.com/p/RAW111/",
                "latestComments": [
                    {
                        "owner": {
                            "username": "comment_owner_should_not_win",
                        }
                    }
                ],
                "node": {
                    "edge_media_to_caption": {"edges": []},
                    "owner": {"username": "deep_owner"},
                },
            }
        ]

    with patch("app.services.apify_instagram._require_real_collector"):
        with patch("app.services.apify_instagram.run_actor_sync", side_effect=fake_actor):
            result = await discover_post_authors_from_hashtags(["HOMEHIVEjewelrybags"], limit=10)

    assert [candidate.username for candidate in result.candidates] == ["deep_owner"]
    assert result.candidates[0].profile_url == "https://www.instagram.com/deep_owner/"
    assert not result.errors


@pytest.mark.anyio
async def test_hashtag_post_author_missing_includes_raw_field_summary(monkeypatch):
    monkeypatch.setattr(settings, "apify_instagram_hashtag_actor_id", "apify~instagram-hashtag-scraper")

    async def fake_actor(actor_id, run_input, **kwargs):
        return [
            {
                "shortCode": "MISS111",
                "url": "https://www.instagram.com/p/MISS111/",
                "caption": "HOMEHIVE clear PVC jewelry bags",
                "owner": {"id": "123"},
                "metadata": {"source": "hashtag"},
            }
        ]

    with patch("app.services.apify_instagram._require_real_collector"):
        with patch("app.services.apify_instagram.run_actor_sync", side_effect=fake_actor):
            result = await discover_post_authors_from_hashtags(["HOMEHIVEjewelrybags"], limit=10)

    assert not result.candidates
    assert result.errors
    assert "post_author_missing" in result.errors[0]
    assert "raw_fields=" in result.errors[0]
    assert "shortCode" in result.errors[0]
    assert "owner.id" in result.errors[0]


@pytest.mark.anyio
async def test_single_bad_hashtag_does_not_stop_later_keyword_discovery(monkeypatch):
    from app.models.collection_task import CollectionTask
    from app.services.apify_instagram import DiscoveryResult, PostAuthorCandidate
    from app.services import keyword_discovery

    calls: list[str] = []

    async def fake_discover(tags, *, limit):
        tag = tags[0]
        calls.append(tag)
        if tag == "badtag":
            return DiscoveryResult(
                errors=["Hashtag 帖子 post#1 post_author_missing: 无法提取作者主页"],
                post_count=1,
                hashtag_count=1,
            )
        return DiscoveryResult(
            candidates=[
                PostAuthorCandidate(
                    username="creator",
                    profile_url="https://www.instagram.com/creator/",
                    source_hashtag=tag,
                    source_discovery_type="post_author",
                )
            ],
            post_count=1,
            hashtag_count=1,
        )

    monkeypatch.setattr(keyword_discovery, "ensure_instagram_provider_ready", lambda: None)
    monkeypatch.setattr(keyword_discovery, "expand_keywords_to_hashtags", lambda *_args, **_kwargs: ["badtag", "goodtag"])
    monkeypatch.setattr(keyword_discovery, "discover_post_authors_from_hashtags", fake_discover)
    monkeypatch.setattr(settings, "collection_search_concurrency", 1)

    task = CollectionTask(
        name="ig",
        platform="instagram",
        platforms=["instagram"],
        keywords=["HOMEHIVE clear PVC jewelry bags"],
        collection_mode="competitor_product",
        discovery_limit=10,
    )

    result = await keyword_discovery.discover_candidates_from_keywords(task, limit=10, include_comments=False)

    assert calls == ["badtag", "goodtag"]
    assert [candidate.username for candidate in result.candidates] == ["creator"]
    assert result.hashtag_api_all_failed is False
