import asyncio

import pytest

from app.collectors.base import CollectedInfluencer
from app.core.config import settings
from app.services.apify_instagram import ProfileScrapeResult
from app.services.cross_platform_instagram_enrichment import enrich_profiles_with_instagram_email
from app.services.high_value_filter import CONTACT_FOUND
from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import candidate_row_from_profile


def _profile(**overrides):
    data = {
        "platform": "youtube",
        "username": "themaker",
        "display_name": "The Maker",
        "profile_url": "https://youtube.com/@themaker",
        "bio": None,
        "website": None,
        "other_social_links": [],
        "source_meta": {},
    }
    data.update(overrides)
    return PlatformCandidateProfile(**data)


def _ig(username="themaker", email="hello@brand.co", **overrides):
    data = {
        "platform": "instagram",
        "username": username,
        "profile_url": f"https://www.instagram.com/{username}/",
        "email": email,
        "final_email": email,
        "public_email": None,
        "business_email": None,
    }
    data.update(overrides)
    return CollectedInfluencer(**data)


@pytest.mark.asyncio
async def test_youtube_candidate_with_instagram_link_gets_email_backfilled():
    profile = _profile(
        other_social_links=[
            {
                "type": "instagram",
                "label": "Instagram",
                "url": "https://www.instagram.com/themaker/",
            }
        ]
    )

    calls = []

    async def scrape(urls, **kwargs):
        calls.append(urls)
        return ProfileScrapeResult(profiles=[_ig(email="creator@brand.co")])

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert calls == [["https://www.instagram.com/themaker/"]]
    assert items[0].final_email == "creator@brand.co"
    assert items[0].email == "creator@brand.co"
    assert profile.email == "creator@brand.co"
    assert profile.source_meta["email_enriched_from"] == "instagram"
    assert profile.source_meta["instagram_contact_profile_url"] == "https://www.instagram.com/themaker/"
    assert profile.source_meta["instagram_contact_confidence"] == "high"
    assert profile.source_meta["instagram_contact_reason"] == "explicit_instagram_link"
    assert profile.source_meta["has_email"] is True
    assert profile.source_meta["has_contact"] is True
    assert profile.source_meta["contact_status"] == CONTACT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_meta", {"links": [{"url": "https://www.instagram.com/themaker/"}]}),
        ("website", "https://www.instagram.com/themaker/"),
        ("contact_page", "https://www.instagram.com/themaker/"),
        ("profile_url", "https://www.instagram.com/themaker/"),
    ],
)
async def test_instagram_profile_link_is_discovered_from_profile_fields(field, value):
    profile = _profile()
    if field == "contact_page":
        setattr(profile, "contact_page", value)
    else:
        setattr(profile, field, value)

    calls = []

    async def scrape(urls, **kwargs):
        calls.append(urls)
        return ProfileScrapeResult(profiles=[_ig(email="field@brand.co")])

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert calls == [["https://www.instagram.com/themaker/"]]
    assert items[0].final_email == "field@brand.co"
    assert profile.source_meta["instagram_contact_confidence"] == "high"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("final_email", "final@brand.co"),
        ("email", "email@brand.co"),
        ("public_email", "public@brand.co"),
        ("business_email", "business@brand.co"),
    ],
)
async def test_instagram_email_fields_are_used_for_enrichment(field, value):
    profile = _profile(bio="IG https://instagram.com/themaker")
    ig_fields = {"email": None, "final_email": None, "public_email": None, "business_email": None}
    ig_fields[field] = value
    ig = _ig(**ig_fields)

    async def scrape(urls, **kwargs):
        return ProfileScrapeResult(profiles=[ig])

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email == value
    assert profile.email == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("bio", "For collabs: bio@brand.co", "bio@brand.co"),
        ("website", "https://example.com/contact?email=web@brand.co", "web@brand.co"),
        ("contact_page", "mailto:contact@brand.co", "contact@brand.co"),
        ("linktree_url", "https://linktr.ee/maker?ref=links@brand.co", "links@brand.co"),
    ],
)
async def test_instagram_text_contact_fields_are_scanned_for_email(field, value, expected):
    profile = _profile(bio="IG https://instagram.com/themaker")
    ig = _ig(email=None, final_email=None)
    setattr(ig, field, value)

    async def scrape(urls, **kwargs):
        return ProfileScrapeResult(profiles=[ig])

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email == expected
    assert profile.email == expected


@pytest.mark.asyncio
async def test_enriched_profile_writes_candidate_row_contact_fields_from_source_meta():
    profile = _profile(bio="IG https://instagram.com/themaker")

    async def scrape(urls, **kwargs):
        return ProfileScrapeResult(profiles=[_ig(email="creator@brand.co")])

    await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    row = candidate_row_from_profile(profile, status="inserted")

    assert row["has_email"] is True
    assert row["has_contact"] is True
    assert row["contact_status"] == CONTACT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["tiktok", "facebook", "pinterest", "ltk", "shopmy"])
async def test_non_instagram_platforms_can_trigger_enrichment(platform):
    profile = _profile(
        platform=platform,
        username="samehandle",
        profile_url=f"https://example.com/{platform}/samehandle",
        bio="IG: https://instagram.com/samehandle",
    )

    async def scrape(urls, **kwargs):
        return ProfileScrapeResult(profiles=[_ig(username="samehandle", business_email="biz@brand.co", email=None, final_email=None)])

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email == "biz@brand.co"
    assert profile.email == "biz@brand.co"
    assert profile.source_meta["instagram_contact_confidence"] == "high"


@pytest.mark.asyncio
async def test_existing_email_skips_instagram_enrichment():
    profile = _profile(email="existing@brand.co")

    async def scrape(urls, **kwargs):
        raise AssertionError("scrape should not be called")

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email == "existing@brand.co"
    assert profile.source_meta == {}


@pytest.mark.asyncio
async def test_username_match_without_explicit_link_is_medium_confidence_and_backfilled():
    profile = _profile(username="samehandle", display_name="Same Handle")

    async def scrape(urls, **kwargs):
        assert urls == ["https://www.instagram.com/samehandle/"]
        return ProfileScrapeResult(profiles=[_ig(username="samehandle", public_email="public@brand.co", email=None, final_email=None)])

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email == "public@brand.co"
    assert profile.source_meta["instagram_contact_confidence"] == "medium"
    assert profile.source_meta["instagram_contact_reason"] == "username_match"


@pytest.mark.asyncio
async def test_low_confidence_display_name_guess_does_not_write_email():
    profile = _profile(username="", display_name="Cozy Maker Studio")

    async def scrape(urls, **kwargs):
        assert urls == ["https://www.instagram.com/cozymakerstudio/"]
        return ProfileScrapeResult(profiles=[_ig(username="cozymakerstudio", email="guess@brand.co")])

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email is None
    assert profile.email is None
    assert profile.source_meta["instagram_contact_confidence"] == "low"
    assert profile.source_meta["instagram_contact_profile_url"] == "https://www.instagram.com/cozymakerstudio/"
    assert profile.source_meta["instagram_contact_candidate_email"] == "guess@brand.co"
    assert "email_enriched_from" not in profile.source_meta


@pytest.mark.asyncio
async def test_instagram_platform_itself_skips_cross_platform_enrichment():
    profile = _profile(platform="instagram", profile_url="https://www.instagram.com/themaker/")

    async def scrape(urls, **kwargs):
        raise AssertionError("scrape should not be called")

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email is None
    assert profile.source_meta == {}


@pytest.mark.asyncio
async def test_enrichment_failure_keeps_candidate_state_and_records_diagnostic():
    profile = _profile(
        other_social_links=[{"type": "instagram", "url": "https://www.instagram.com/themaker/"}]
    )

    async def scrape(urls, **kwargs):
        raise RuntimeError("provider unavailable")

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email is None
    assert profile.email is None
    assert profile.source_meta["instagram_contact_confidence"] == "high"
    assert "provider unavailable" in profile.source_meta["instagram_contact_error"]


@pytest.mark.asyncio
async def test_instagram_email_enrichment_respects_attempt_limit(monkeypatch):
    monkeypatch.setattr(settings, "collection_cross_platform_instagram_enrichment_limit", 2)
    profiles = [
        _profile(username=f"creator{i}", profile_url=f"https://www.tiktok.com/@creator{i}", platform="tiktok")
        for i in range(5)
    ]
    calls = []

    async def scrape(urls, **kwargs):
        calls.append(urls)
        return ProfileScrapeResult(profiles=[])

    items = await enrich_profiles_with_instagram_email(profiles, scrape_func=scrape)

    assert len(items) == 5
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_instagram_email_enrichment_timeout_is_best_effort(monkeypatch):
    monkeypatch.setattr(settings, "collection_cross_platform_instagram_enrichment_limit", 1)
    monkeypatch.setattr(settings, "collection_cross_platform_instagram_enrichment_timeout_seconds", 1)
    profile = _profile(username="slowcreator", profile_url="https://www.tiktok.com/@slowcreator", platform="tiktok")

    async def scrape(urls, **kwargs):
        await asyncio.sleep(2)
        return ProfileScrapeResult(profiles=[_ig(username="slowcreator", email="slow@brand.co")])

    items = await enrich_profiles_with_instagram_email([profile], scrape_func=scrape)

    assert items[0].final_email is None
    assert "instagram_contact_error" in profile.source_meta
