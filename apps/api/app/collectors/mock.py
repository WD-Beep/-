from dataclasses import replace
from datetime import UTC, datetime

from app.collectors.base import BaseCollector, CollectedInfluencer
from app.models.collection_task import CollectionTask


def _mock_profile(
    username: str,
    *,
    display_name: str,
    followers: int,
    engagement: float,
    category: str = "travel",
    hashtag: str | None = None,
) -> CollectedInfluencer:
    tag = hashtag or category
    bio = f"Travel & lifestyle creator · #{tag} · DM for collabs"
    return CollectedInfluencer(
        platform="instagram",
        username=username,
        display_name=display_name,
        profile_url=f"https://www.instagram.com/{username}/",
        country="US",
        language="en",
        category=category,
        niche="travel",
        bio=bio,
        followers_count=followers,
        avg_likes=int(followers * engagement / 100 * 0.6),
        avg_comments=int(followers * engagement / 100 * 0.1),
        engagement_rate=engagement,
        email=f"{username}@example.com",
        final_email=f"{username}@example.com",
        public_email=f"{username}@example.com",
        email_source="bio",
        contact_credibility=72.0,
        contact_score=68.0,
        product_fit=78.0,
        travel_fit_score=82.0,
        purchasing_power_score=74.0,
        sales_potential_score=71.0,
        audience_match_score=76.0,
        roi_forecast=2.4,
        content_topics=["travel", "lifestyle", tag],
        audience_country="US",
        audience_language="en",
        collaboration_formats=["reel", "story"],
        tags=[tag, "mock", "instagram"],
        last_post_at=datetime.now(UTC),
        posting_frequency="周更 3-4 次",
    )


_MOCK_PROFILES = [
    _mock_profile("mock_travel_anna", display_name="Anna Travels", followers=125_000, engagement=4.2, hashtag="travel"),
    _mock_profile("mock_fit_james", display_name="James Fit", followers=48_000, engagement=5.8, category="fitness", hashtag="fitness"),
    _mock_profile("mock_food_luna", display_name="Luna Eats", followers=210_000, engagement=3.1, category="food", hashtag="foodie"),
]


class MockCollector(BaseCollector):
    """本地联调用 Mock 采集器，无需 Apify。"""

    async def collect(self, task: CollectionTask) -> list[CollectedInfluencer]:
        platform = (task.platform or "").lower()
        if platform != "instagram":
            return []

        results: list[CollectedInfluencer] = []
        seen: set[str] = set()

        for profile in _MOCK_PROFILES:
            key = profile.username
            if key in seen:
                continue
            seen.add(key)
            item = profile
            if task.category or task.country:
                item = replace(
                    profile,
                    category=task.category or profile.category,
                    country=task.country or profile.country,
                )
            results.append(item)

        keywords = [k.strip().lstrip("#") for k in (task.keywords or []) if k and k.strip()]
        for index, tag in enumerate(keywords[:3]):
            username = f"mock_tag_{tag.lower().replace(' ', '_')[:20]}"
            if username in seen:
                continue
            seen.add(username)
            results.append(
                _mock_profile(
                    username,
                    display_name=f"Creator #{tag}",
                    followers=35_000 + index * 12_000,
                    engagement=3.5 + index * 0.4,
                    hashtag=tag,
                )
            )

        urls = [u.strip() for u in (task.input_urls or []) if u.strip()]
        for index, url in enumerate(urls[:5]):
            handle = url.rstrip("/").split("/")[-1].lstrip("@") or f"mock_url_{index}"
            if handle in seen:
                continue
            seen.add(handle)
            results.append(
                _mock_profile(
                    handle,
                    display_name=f"@{handle}",
                    followers=22_000 + index * 8_000,
                    engagement=4.0,
                )
            )

        limit = task.discovery_limit or 100
        return results[:limit]


def mock_scrape_from_urls(urls_or_usernames: list[str]) -> list[CollectedInfluencer]:
    """链接导入 / 批量主页采集的 Mock 实现。"""
    results: list[CollectedInfluencer] = []
    seen: set[str] = set()
    for index, raw in enumerate(urls_or_usernames):
        text = raw.strip()
        if not text:
            continue
        if "instagram.com" in text:
            handle = text.rstrip("/").split("/")[-1].lstrip("@")
        else:
            handle = text.lstrip("@")
        if not handle or handle.lower() in seen:
            continue
        seen.add(handle.lower())
        results.append(
            _mock_profile(
                handle,
                display_name=f"@{handle}",
                followers=18_000 + index * 6_000,
                engagement=3.8 + (index % 3) * 0.5,
            )
        )
    return results
