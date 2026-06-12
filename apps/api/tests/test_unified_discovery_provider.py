from unittest.mock import AsyncMock, patch

import anyio

from app.services.apify_instagram import DiscoveryResult, PostAuthorCandidate
from app.services.discovery_accumulator import DiscoveryAccumulator
from app.services.instagram_unified_discovery import enrich_with_comment_discovery


def test_comment_discovery_uses_active_provider_wrapper():
    acc = DiscoveryAccumulator()
    candidate = PostAuthorCandidate(
        username="travel_creator",
        profile_url="https://www.instagram.com/travel_creator/",
        source_discovery_type="comment_author",
    )

    async def _run():
        with patch(
            "app.services.instagram_unified_discovery.active_provider_name",
            return_value="api_direct",
        ), patch(
            "app.services.instagram_unified_discovery.discover_comment_authors_from_post_urls",
            new_callable=AsyncMock,
            return_value=DiscoveryResult(candidates=[candidate]),
        ) as mock_discover:
            errors: list[str] = []
            added = await enrich_with_comment_discovery(
                acc,
                ["https://www.instagram.com/p/ABC123/"],
                limit=10,
                errors=errors,
            )
        return added, errors, mock_discover

    added, errors, mock_discover = anyio.run(_run)

    assert added == 1
    assert errors == []
    mock_discover.assert_awaited_once()


def test_collection_task_defaults_are_value_oriented():
    from app.schemas.collection_task import CollectionTaskCreate

    task = CollectionTaskCreate(
        name="US travel",
        platform="instagram",
        collection_mode="discovery",
        keywords=["travelgear"],
    )

    assert task.min_followers_count == 50_000
    assert task.min_engagement_rate == 2.0
    assert task.comment_discovery_enabled is False
