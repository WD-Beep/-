import asyncio

from app.core.config import settings
from app.services.apify_instagram import scrape_instagram_profiles


def test_profile_scrape_uses_fallback_actor_when_primary_returns_no_profile(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_run_actor(actor_id: str, run_input: dict, **kwargs):
        calls.append((actor_id, run_input))
        if actor_id == "logical_scrapers~instagram-profile-scraper":
            return []
        if actor_id == "coderx~instagram-profile-scraper-api":
            return [
                {
                    "username": "ig_etsybusiness",
                    "fullName": "IG Etsy Business",
                    "biography": "Handmade business hello@example.com",
                    "followersCount": 42_000,
                    "profilePicUrl": "https://example.com/avatar.jpg",
                    "externalUrl": "https://example.com",
                }
            ]
        raise AssertionError(f"unexpected actor {actor_id}")

    monkeypatch.setattr(settings, "collector_mode", "apify")
    monkeypatch.setattr(settings, "instagram_data_provider", "apify")
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "apify_instagram_actor_id", "logical_scrapers~instagram-profile-scraper")
    monkeypatch.setattr(settings, "apify_instagram_profile_fallback_enabled", True, raising=False)
    monkeypatch.setattr(
        settings,
        "apify_instagram_profile_fallback_actor_id",
        "coderx~instagram-profile-scraper-api",
        raising=False,
    )
    monkeypatch.setattr("app.services.apify_instagram.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        result = await scrape_instagram_profiles(["https://www.instagram.com/ig_etsybusiness/"])

        assert [actor for actor, _ in calls] == [
            "logical_scrapers~instagram-profile-scraper",
            "coderx~instagram-profile-scraper-api",
        ]
        assert calls[1][1]["targetUsernames"] == ["ig_etsybusiness"]
        assert calls[1][1]["usernames"] == ["ig_etsybusiness"]
        assert len(result.profiles) == 1
        assert result.profiles[0].username == "ig_etsybusiness"
        assert result.profiles[0].followers_count == 42_000
        assert result.profiles[0].final_email == "hello@example.com"
        assert result.failed_profiles == []

    asyncio.run(_run())


def test_profile_scrape_fallback_actor_recovers_primary_success_false(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_run_actor(actor_id: str, run_input: dict, **kwargs):
        calls.append((actor_id, run_input))
        if actor_id == "logical_scrapers~instagram-profile-scraper":
            return [
                {
                    "username": "sewcosybee",
                    "url": "https://www.instagram.com/sewcosybee/",
                    "success": False,
                    "error": "profile detail missing",
                }
            ]
        if actor_id == "coderx~instagram-profile-scraper-api":
            assert run_input["usernames"] == ["sewcosybee"]
            return [
                {
                    "username": "sewcosybee",
                    "full_name": "Sew Cosy Bee",
                    "biography": "Handmade pouches contact@sewcosybee.ca",
                    "followers_count": 25_000,
                    "profile_pic_url": "https://example.com/sew.jpg",
                }
            ]
        raise AssertionError(f"unexpected actor {actor_id}")

    monkeypatch.setattr(settings, "collector_mode", "apify")
    monkeypatch.setattr(settings, "instagram_data_provider", "apify")
    monkeypatch.setattr(settings, "apify_token", "apify_api_test")
    monkeypatch.setattr(settings, "apify_instagram_actor_id", "logical_scrapers~instagram-profile-scraper")
    monkeypatch.setattr(settings, "apify_instagram_profile_fallback_enabled", True, raising=False)
    monkeypatch.setattr(
        settings,
        "apify_instagram_profile_fallback_actor_id",
        "coderx~instagram-profile-scraper-api",
        raising=False,
    )
    monkeypatch.setattr("app.services.apify_instagram.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        result = await scrape_instagram_profiles(["https://www.instagram.com/sewcosybee/"])

        assert [actor for actor, _ in calls] == [
            "logical_scrapers~instagram-profile-scraper",
            "coderx~instagram-profile-scraper-api",
        ]
        assert len(result.profiles) == 1
        assert result.profiles[0].username == "sewcosybee"
        assert result.profiles[0].followers_count == 25_000
        assert result.profiles[0].final_email == "contact@sewcosybee.ca"
        assert result.failed_profiles == []

    asyncio.run(_run())
