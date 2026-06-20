"""导购型 seed 自动发现 + 多平台补全测试。"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.collectors.base import CollectedInfluencer
from app.services.apify_client import ApifyError
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateSourceType, CandidateStatus, CollectionMode, CollectionTaskStatus
from app.services.apify_instagram import ProfileScrapeResult
from app.services.high_value_filter import evaluate_high_value_assessment
from app.services.link_import import LinkImportService
from app.services.link_seed_enrichment import (
    enrich_link_seed_item,
    enrichment_meta_dict,
    merge_seed_into_primary,
    _compute_enrichment_score,
    _hydrate_ltk_seed_detail,
    _hydrate_tiktok_profile_detail,
    _pick_best_profile,
)
from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import profile_to_collected
from app.services.shopping_seed_discovery import (
    build_shopping_seed_search_keywords_for_task,
    discover_shopping_seeds_from_task,
    discover_shopping_seed_profiles,
    expand_keyword_to_handles,
    _seed_matches_amazon_product_evidence,
)
from app.services.shopping_seed_discovery_provider import (
    build_seed_search_diagnostics,
    build_social_search_queries,
    build_seed_search_plan,
    discover_shopping_seeds_via_social_search,
    extract_seed_refs_from_collected,
    extract_seed_urls_from_collected,
    extract_seed_urls_from_text,
)
from app.services.shopping_seed_runner import ShoppingSeedDiscoveryService
from app.services.task_candidate import TaskCandidateService
import app.services.shopping_seed_discovery_provider as provider


INSTAGRAM_SCRAPE_PATCH_TARGETS = (
    "app.services.link_seed_enrichment.scrape_instagram_profiles",
    "app.services.instagram_provider.scrape_instagram_profiles",
)


def _ltk_seed(username: str = "seed_creator") -> CollectedInfluencer:
    profile = PlatformCandidateProfile(
        platform="ltk",
        username=username,
        profile_url=f"https://www.shopltk.com/explore/{username}",
        display_name="Seed Creator",
    )
    return profile_to_collected(profile)


def _mock_enrichment_platforms(monkeypatch, profiles: dict[str, CollectedInfluencer | None]) -> list[list[str]]:
    scrape_calls: list[list[str]] = []

    async def _scrape(urls):
        scrape_calls.append(list(urls))
        ig = profiles.get("instagram")
        if ig:
            return ProfileScrapeResult(profiles=[ig], errors=[])
        return ProfileScrapeResult(profiles=[], errors=[])

    scrape_mock = AsyncMock(side_effect=_scrape)
    for target in INSTAGRAM_SCRAPE_PATCH_TARGETS:
        monkeypatch.setattr(target, scrape_mock)

    async def _tt(username):
        item = profiles.get("tiktok")
        return (item, bool(item)) if item else (None, False)

    async def _yt(username, display_name):
        del username, display_name
        item = profiles.get("youtube")
        return (item, bool(item)) if item else (None, False)

    async def _fb(username):
        del username
        item = profiles.get("facebook")
        return (item, bool(item)) if item else (None, False)

    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_tiktok_profile_detail", _tt)
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_youtube_profile_detail", _yt)
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_facebook_profile_detail", _fb)
    monkeypatch.setattr(
        "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )
    return scrape_calls


def test_expand_keyword_to_handles():
    handles = expand_keyword_to_handles("Fashion Blogger")
    assert "fashionblogger" in handles
    assert "fashion_blogger" in handles


def test_build_social_search_queries_for_ltk():
    queries = build_social_search_queries("fashion blogger", ["ltk"])
    assert "fashion blogger shopltk" in queries
    assert any("LTK" in q for q in queries)


def test_extract_seed_urls_from_text():
    found = extract_seed_urls_from_text(
        "Shop my looks https://www.shopltk.com/explore/real_seed_creator",
        {"ltk"},
    )
    assert found == [("ltk", "https://www.shopltk.com/explore/real_seed_creator")]


def test_extract_seed_urls_from_text_supports_shopmy_shop_path():
    found = extract_seed_urls_from_text(
        "Shop my list https://shopmy.us/shop/real_seed_creator?utm=abc",
        {"shopmy"},
    )
    assert found == [("shopmy", "https://shopmy.us/real_seed_creator")]


def test_extract_seed_urls_from_text_rejects_shopmy_static_assets():
    found = extract_seed_urls_from_text(
        "Assets https://shopmy.us/favicon.ico https://shopmy.us/manifest.json https://shopmy.us/apple-app-site-association",
        {"shopmy"},
    )
    assert found == []


def test_extract_seed_urls_from_text_rejects_ltk_reserved_platform_handle():
    found = extract_seed_urls_from_text(
        "Official app https://www.shopltk.com/explore/LTK",
        {"ltk"},
    )
    assert found == []


def test_seed_search_plan_does_not_send_bare_asin_to_ltk_site_search():
    from app.services.shopping_seed_discovery_provider import should_use_ltk_site_search

    assert should_use_ltk_site_search("B0D9W576KQ") is False
    assert should_use_ltk_site_search("HOMEHIVE LTK") is True
    assert should_use_ltk_site_search("jewelry storage LTK") is True
    assert should_use_ltk_site_search("HOMEHIVE ShopMy") is False
    assert should_use_ltk_site_search("jewelry storage Pinterest") is False
    assert should_use_ltk_site_search("HOMEHIVE Amazon finds") is True


def test_extract_seed_urls_from_collected_scans_captions_and_source_meta():
    item = CollectedInfluencer(
        platform="tiktok",
        username="source_creator",
        profile_url="https://www.tiktok.com/@source_creator",
        bio="bio https://www.shopltk.com/explore/bio_seed",
        source_post_url="https://www.tiktok.com/@source_creator/video/1",
        recent_post_titles=["caption https://shopmy.us/shop/caption_seed"],
    )
    item.source_comment_text = "comment https://www.pinterest.com/comment_seed/"
    item.source_meta = {
        "caption": "watch https://www.shopltk.com/explore/meta_caption_seed",
        "external_links": [{"url": "https://shopmy.us/meta_link_seed"}],
        "video_description": "desc https://www.pinterest.com/video_desc_seed/",
    }

    found = extract_seed_urls_from_collected(item, {"ltk", "shopmy", "pinterest"})
    assert ("ltk", "https://www.shopltk.com/explore/bio_seed") in found
    assert ("shopmy", "https://shopmy.us/caption_seed") in found
    assert ("pinterest", "https://www.pinterest.com/comment_seed/") in found
    assert ("ltk", "https://www.shopltk.com/explore/meta_caption_seed") in found
    assert ("shopmy", "https://shopmy.us/meta_link_seed") in found
    assert ("pinterest", "https://www.pinterest.com/video_desc_seed/") in found


def test_extract_seed_refs_preserve_source_evidence_fields():
    item = CollectedInfluencer(
        platform="youtube",
        username="source_creator",
        profile_url="https://www.youtube.com/@source_creator",
        bio="Shop my links https://shopmy.us/shop/source_seed",
    )

    refs = extract_seed_refs_from_collected(item, {"shopmy"}, discovery_query="HOMEHIVE ShopMy")

    assert refs == [
        {
            "link_seed_platform": "shopmy",
            "link_seed_profile_url": "https://shopmy.us/source_seed",
            "link_seed_username": "source_seed",
            "discovery_source": "youtube_bio",
            "discovery_query": "HOMEHIVE ShopMy",
            "source_platform": "youtube",
            "source_profile_url": "https://www.youtube.com/@source_creator",
            "source_post_url": "",
            "source_input_url": "https://www.youtube.com/@source_creator",
            "provider": "youtube",
            "raw_url": "https://shopmy.us/source_seed",
            "normalized_seed_url": "https://shopmy.us/source_seed",
            "extraction_reason": "youtube_bio_seed_link",
        }
    ]


def test_link_seed_discovery_accepts_amazon_asin_without_manual_seed_link():
    from app.schemas.collection_task import CollectionTaskCreate

    task = CollectionTaskCreate(
        name="amazon seed discovery",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY,
        platform="ltk",
        platforms=["ltk", "shopmy"],
        keywords=["HOMEHIVE jewelry storage bags"],
        input_urls=["B0D9W576KQ"],
        product_id=1,
    )

    assert task.collection_mode == CollectionMode.LINK_SEED_DISCOVERY
    assert task.input_urls
    seeds = task.run_checkpoint.get("amazon_product_seeds") or []
    assert seeds and seeds[0]["asin"] == "B0D9W576KQ"
    assert seeds[0]["brand"] == "HOMEHIVE"


def test_amazon_seed_queries_include_brand_product_variant_and_shopping_terms():
    task = CollectionTask(
        name="amazon seed query",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="ltk",
        platforms=["ltk", "shopmy"],
        keywords=[],
        input_urls=["B0D9W576KQ"],
        product_id=1,
        user_id=1,
        workspace_id=1,
    )
    keywords = build_shopping_seed_search_keywords_for_task(task)

    assert "B0D9W576KQ" in keywords
    assert any("HOMEHIVE" in q and "PVC" in q for q in keywords)
    assert "HOMEHIVE LTK" in keywords
    assert "HOMEHIVE ShopMy" in keywords
    assert "HOMEHIVE Pinterest" in keywords
    assert "HOMEHIVE Amazon finds" in keywords
    assert "jewelry storage LTK" in keywords
    assert "jewelry storage ShopMy" in keywords
    assert "jewelry storage Pinterest" in keywords
    assert "jewelry storage Amazon finds" in keywords
    assert any("influencer" in q for q in keywords)
    assert any("blogger" in q for q in keywords)
    assert any(q.startswith("site:shopmy.us HOMEHIVE ") and "jewelry" in q for q in keywords)
    assert any(q.startswith("site:pinterest.com HOMEHIVE ") and "jewelry" in q for q in keywords)
    assert any(q.startswith("site:shopltk.com HOMEHIVE ") and "jewelry" in q for q in keywords)


@pytest.mark.anyio
async def test_seed_evidence_matcher_rejects_ltk_profile_without_amazon_product_terms():
    from app.services.competitor_product_discovery import parse_competitor_product_inputs

    amazon_url = "https://www.amazon.com/Laundry-Washable-Organizer-Drawstring%EF%BC%8CLarge-Essentials/dp/B0CPF3W9B2"
    task = CollectionTask(
        name="amazon exact seed",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="ltk",
        platforms=["ltk"],
        keywords=[],
        input_urls=[amazon_url],
        product_id=1,
        user_id=1,
        workspace_id=1,
    )
    info = parse_competitor_product_inputs(task)
    seed = _ltk_seed("false_positive")
    seed.source_meta = {"search_query": "B0CPF3W9B2 shopltk", "source_keyword": "B0CPF3W9B2"}

    assert not _seed_matches_amazon_product_evidence(
        seed,
        info,
        "Travel finds, packing cubes, Amazon favorites, and home organization",
    )
    assert _seed_matches_amazon_product_evidence(
        seed,
        info,
        "Aegero travel laundry bag review, drawstring laundry bag for dirty clothes organizer",
    )


@pytest.mark.anyio
async def test_amazon_seed_discovery_filters_ltk_profiles_without_product_evidence(monkeypatch):
    good = _ltk_seed("matched_seed")
    bad = _ltk_seed("generic_seed")
    amazon_url = "https://www.amazon.com/Laundry-Washable-Organizer-Drawstring%EF%BC%8CLarge-Essentials/dp/B0CPF3W9B2"
    task = CollectionTask(
        name="amazon exact seed",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="ltk",
        platforms=["ltk"],
        keywords=[],
        input_urls=[amazon_url],
        product_id=1,
        user_id=1,
        workspace_id=1,
    )

    async def _fake_discover(**kwargs):
        del kwargs
        return [good, bad]

    html_by_url = {
        good.profile_url: "Aegero travel laundry bag review with drawstring laundry bag for dirty clothes",
        bad.profile_url: "Amazon travel finds and home organization ideas",
    }

    async def _fake_fetch(url):
        return html_by_url[url]

    monkeypatch.setattr("app.services.shopping_seed_discovery.discover_shopping_seed_profiles", _fake_discover)
    monkeypatch.setattr("app.services.shopping_seed_discovery._fetch_seed_profile_text", _fake_fetch)

    seeds = await discover_shopping_seeds_from_task(task)

    assert [seed.username for seed in seeds] == ["matched_seed"]
    diagnostics = task.run_checkpoint.get("shopping_seed_discovery") or {}
    assert diagnostics.get("product_evidence_filtered_count") == 1


@pytest.mark.anyio
async def test_amazon_seed_discovery_records_zero_reason_when_all_seeds_lack_product_evidence(monkeypatch):
    bad = _ltk_seed("generic_seed")
    amazon_url = "https://www.amazon.com/Laundry-Washable-Organizer-Drawstring%EF%BC%8CLarge-Essentials/dp/B0CPF3W9B2"
    task = CollectionTask(
        name="amazon exact seed all filtered",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="ltk",
        platforms=["ltk"],
        keywords=[],
        input_urls=[amazon_url],
        product_id=1,
        user_id=1,
        workspace_id=1,
    )

    async def _fake_discover(**kwargs):
        del kwargs
        return [bad]

    async def _fake_fetch(url):
        del url
        return "Amazon travel finds and home organization ideas"

    monkeypatch.setattr("app.services.shopping_seed_discovery.discover_shopping_seed_profiles", _fake_discover)
    monkeypatch.setattr("app.services.shopping_seed_discovery._fetch_seed_profile_text", _fake_fetch)

    seeds = await discover_shopping_seeds_from_task(task)

    assert seeds == []
    diagnostics = task.run_checkpoint.get("shopping_seed_discovery") or {}
    assert diagnostics.get("product_evidence_filtered_count") == 1
    assert diagnostics.get("product_evidence_verified_count") == 0
    assert diagnostics.get("zero_seed_reason") == "seed_found_but_no_product_evidence"


def test_seed_search_plan_caps_provider_calls_and_prioritizes_high_signal_queries():
    keywords = [
        "B0D9W576KQ",
        "HOMEHIVE HOMEHIVE 20 Clear PVC Jewelry Storage Bags Anti Tarnish Zipper Bags",
        "HOMEHIVE clear PVC",
        "HOMEHIVE LTK",
        "HOMEHIVE ShopMy",
        "HOMEHIVE Amazon finds",
        "HOMEHIVE jewelry storage bags influencer",
        "HOMEHIVE jewelry storage bags blogger",
        "extra query should be capped",
    ]

    plan = build_seed_search_plan(
        keywords=keywords,
        seed_platforms=["ltk", "shopmy", "pinterest"],
        max_queries=12,
    )

    assert len(plan) <= 12
    assert any(item["query"] == "B0D9W576KQ" for item in plan)
    assert any("HOMEHIVE LTK" in item["query"] for item in plan)
    assert any("HOMEHIVE ShopMy" in item["query"] for item in plan)
    assert not any("extra query should be capped" in item["query"] for item in plan)


def test_seed_search_plan_keeps_one_query_per_seed_platform():
    plan = build_seed_search_plan(
        keywords=[
            "amazon finds",
            "amazon must haves",
            "amazon storefront",
            "amazon influencer",
            "amazon product recommendations",
            "AmazonFinds",
        ],
        seed_platforms=["ltk", "shopmy", "pinterest"],
        max_queries=10,
    )
    queries = [item["query"].lower() for item in plan]

    assert any("ltk" in query or "shopltk" in query for query in queries)
    assert any("shopmy" in query for query in queries)
    assert any("pinterest" in query for query in queries)
    assert len(queries) <= 10


@pytest.mark.anyio
async def test_seed_search_skips_completed_queries_and_marks_new_queries(monkeypatch):
    calls: list[str] = []
    completed: list[str] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 4, raising=False)

    async def _fake_public_search(query, allowed_platforms, *, limit=20):
        calls.append(query)
        username = query.replace(" ", "")
        return [
            {
                "link_seed_platform": "shopmy",
                "link_seed_profile_url": f"https://shopmy.us/{username}",
                "link_seed_username": username,
                "discovery_source": "search_result",
                "discovery_query": query,
                "source_platform": "public_web",
                "source_input_url": f"https://shopmy.us/{username}",
            }
        ]

    async def _mark_done(query: str, count: int):
        completed.append(f"{query}:{count}")

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _fake_public_search)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["done query", "new query"],
        seed_platforms=["shopmy"],
        completed_queries={"done query"},
        on_query_complete=_mark_done,
        limit=5,
    )

    assert "done query" not in calls
    assert not any(call.startswith("done query") for call in calls)
    assert any(call.startswith("new query") for call in calls)
    assert completed
    assert seeds


@pytest.mark.anyio
async def test_seed_search_provider_error_does_not_complete_query_and_records_error(monkeypatch):
    completed: list[str] = []
    errors: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 2, raising=False)

    async def _failing_public_search(query, allowed_platforms, *, limit=20):
        raise TimeoutError("provider timeout")

    async def _mark_done(query: str, count: int):
        completed.append(query)

    async def _mark_error(query: str, query_errors: list[str]):
        errors.append((query, query_errors))

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _failing_public_search)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["timeout query"],
        seed_platforms=["shopmy"],
        on_query_complete=_mark_done,
        on_query_error=_mark_error,
        limit=5,
    )

    assert seeds == []
    assert completed == []
    assert errors
    assert errors[0][0].startswith("timeout query")
    assert any("public_web" in item for item in errors[0][1])


@pytest.mark.anyio
async def test_query_error_checkpoint_is_persisted_and_retried(monkeypatch):
    class FakeDb:
        def __init__(self):
            self.commits = 0

        async def commit(self):
            self.commits += 1

    calls: list[str] = []
    fail = True

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 2, raising=False)

    async def _public_search(query, allowed_platforms, *, limit=20):
        calls.append(query)
        if fail:
            raise TimeoutError("provider timeout")
        return [
            {
                "link_seed_platform": "shopmy",
                "link_seed_profile_url": "https://shopmy.us/retried_seed",
                "link_seed_username": "retried_seed",
                "discovery_source": "search_result",
                "discovery_query": query,
                "source_platform": "public_web",
                "source_input_url": "https://shopmy.us/retried_seed",
            }
        ]

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _public_search)
    task = CollectionTask(
        name="query-error-checkpoint",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="multi",
        platforms=["shopmy"],
        keywords=["retry query"],
        product_id=1,
        user_id=1,
        workspace_id=1,
    )
    db = FakeDb()

    seeds = await discover_shopping_seeds_from_task(task, db=db)
    checkpoint = task.run_checkpoint or {}

    assert seeds == []
    assert checkpoint.get("completed_queries") in (None, [])
    assert checkpoint.get("failed_queries")
    assert checkpoint.get("query_errors")
    assert db.commits >= 2

    fail = False
    seeds = await discover_shopping_seeds_from_task(task, db=db)

    assert len(seeds) == 1
    assert len(calls) >= 2
    assert (task.run_checkpoint or {}).get("completed_queries")


@pytest.mark.anyio
async def test_seed_search_runs_with_configured_concurrency(monkeypatch):
    running = 0
    max_running = 0
    calls: list[str] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_concurrency", 2, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 6, raising=False)

    async def _fake_public_search(query, allowed_platforms, *, limit=20):
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        calls.append(query)
        await asyncio.sleep(0.01)
        running -= 1
        return []

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _fake_public_search)

    await discover_shopping_seeds_via_social_search(
        keywords=[f"query {idx}" for idx in range(6)],
        seed_platforms=["shopmy"],
        limit=10,
    )

    assert len(calls) >= 2
    assert max_running == 2


def test_seed_search_diagnostics_uses_public_web_provider(monkeypatch):
    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.settings.shopping_seed_search_provider",
        "public_web",
    )
    diag = build_seed_search_diagnostics(
        keywords=["HOMEHIVE LTK", "HOMEHIVE ShopMy"],
        seed_platforms=["ltk", "shopmy"],
        profiles_returned_count=0,
        seed_extracted_count=0,
    )

    assert diag["seed_search_disabled"] is False
    assert diag["search_platforms"] == ["public_web"]
    assert diag["provider_call_count"] > 0
    assert diag["zero_seed_reason"] == "seed_search_no_profiles_returned"


def test_shopmy_only_diagnostics_do_not_count_pinterest_apify(monkeypatch):
    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.settings.shopping_seed_search_provider",
        "public_web,pinterest_apify",
    )
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 3, raising=False)

    diag = build_seed_search_diagnostics(
        keywords=["amazon finds", "amazon storefront"],
        seed_platforms=["shopmy"],
        profiles_returned_count=0,
        seed_extracted_count=0,
    )

    assert diag["search_platforms"] == ["public_web"]
    assert diag["provider_call_count"] == diag["query_count"]
    assert diag["zero_seed_reason"] == "shopmy_keyword_search_requires_authenticated_provider"
    assert "shopmy" in diag["platform_provider_notes"]


def test_pinterest_diagnostics_count_pinterest_apify(monkeypatch):
    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.settings.shopping_seed_search_provider",
        "public_web,pinterest_apify",
    )
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 3, raising=False)

    diag = build_seed_search_diagnostics(
        keywords=["amazon finds"],
        seed_platforms=["pinterest"],
        profiles_returned_count=0,
        seed_extracted_count=0,
    )

    assert diag["search_platforms"] == ["public_web", "pinterest_apify"]
    assert diag["provider_call_count"] == diag["query_count"] * 2


def test_pinterest_apify_default_timeout_is_bounded_for_seed_discovery():
    from app.core.config import Settings

    assert Settings().apify_pinterest_search_timeout_seconds <= 45


def test_facebook_seed_hydration_deadline_uses_global_settings_for_url_tasks():
    from app.services.platform_providers.facebook_apify import _discovery_deadline

    deadline = _discovery_deadline(SimpleNamespace(collection_mode="urls"))

    assert isinstance(deadline, float)


def test_seed_search_diagnostics_does_not_mark_successful_search_as_zero(monkeypatch):
    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.settings.shopping_seed_search_provider",
        "public_web",
    )
    diag = build_seed_search_diagnostics(
        keywords=["HOMEHIVE LTK"],
        seed_platforms=["ltk"],
        profiles_returned_count=1,
        seed_extracted_count=1,
    )

    assert diag["seed_search_disabled"] is False
    assert diag["zero_seed_reason"] is None


def test_seed_search_diagnostics_query_count_uses_configured_max(monkeypatch):
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 3, raising=False)

    diag = build_seed_search_diagnostics(
        keywords=[f"HOMEHIVE query {idx}" for idx in range(10)],
        seed_platforms=["ltk", "shopmy", "pinterest"],
        profiles_returned_count=0,
        seed_extracted_count=0,
    )

    assert diag["query_count"] == 3
    assert len(diag["queries"]) == 3


@pytest.mark.anyio
async def test_discover_shopping_seed_profiles_no_social_search_calls(monkeypatch):
    """导购 seed 自动发现不再调用 Instagram / TikTok / YouTube / Facebook 的 discover_platform。"""
    discover_calls: list[str] = []

    async def _fake_discover(task, platform):
        discover_calls.append(platform)
        return SimpleNamespace(profiles=[], errors=[])

    monkeypatch.setattr(
        "app.services.api_direct_provider.discover_platform",
        _fake_discover,
    )

    async def _empty_public_search(query, allowed_platforms, *, limit=20):
        del query, allowed_platforms, limit
        return []

    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.search_public_web_for_seed_refs",
        _empty_public_search,
    )

    seeds = await discover_shopping_seed_profiles(
        keywords=["fashion blogger"],
        seed_platforms=["ltk"],
        limit=10,
    )
    # SEED_SOCIAL_SEARCH_PLATFORMS is empty → no social platform calls
    assert len(seeds) == 0
    assert discover_calls == []


@pytest.mark.anyio
async def test_configured_social_seed_search_extracts_seed_refs_from_social_fields(monkeypatch):
    discover_calls: list[str] = []

    profiles_by_platform = {
        "instagram": PlatformCandidateProfile(
            platform="instagram",
            username="ig_creator",
            profile_url="https://www.instagram.com/ig_creator/",
            bio="Shop my LTK https://www.shopltk.com/explore/ig_seed",
        ),
        "youtube": PlatformCandidateProfile(
            platform="youtube",
            username="yt_creator",
            profile_url="https://www.youtube.com/@yt_creator",
            source_meta={"video_description": "ShopMy list https://shopmy.us/shop/yt_seed"},
        ),
        "tiktok": PlatformCandidateProfile(
            platform="tiktok",
            username="tt_creator",
            profile_url="https://www.tiktok.com/@tt_creator",
            source_meta={"caption": "Pins https://www.pinterest.com/tt_seed/"},
        ),
        "facebook": PlatformCandidateProfile(
            platform="facebook",
            username="fb_creator",
            profile_url="https://www.facebook.com/fb_creator",
            bio="More looks https://www.shopltk.com/explore/fb_seed",
        ),
    }

    async def _fake_discover(task, platform):
        del task
        discover_calls.append(platform)
        return SimpleNamespace(profiles=[profiles_by_platform[platform]], errors=[])

    async def _empty_public_search(query, allowed_platforms, *, limit=20):
        del query, allowed_platforms, limit
        return []

    monkeypatch.setattr("app.services.api_direct_provider.discover_platform", _fake_discover)
    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.search_public_web_for_seed_refs",
        _empty_public_search,
    )
    monkeypatch.setattr(provider.settings, "shopping_seed_search_provider", "disabled", raising=False)
    monkeypatch.setattr(
        provider.settings,
        "shopping_seed_social_search_platforms",
        "instagram,youtube,tiktok,facebook",
        raising=False,
    )
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 1, raising=False)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["HOMEHIVE"],
        seed_platforms=["ltk", "shopmy", "pinterest"],
        limit=10,
    )

    assert discover_calls == ["instagram", "youtube", "tiktok", "facebook"]
    by_url = {seed.profile_url: getattr(seed, "source_meta", {}) for seed in seeds}
    assert "https://www.shopltk.com/explore/ig_seed" in by_url
    assert "https://shopmy.us/yt_seed" in by_url
    assert "https://www.pinterest.com/tt_seed/" in by_url
    assert "https://www.shopltk.com/explore/fb_seed" in by_url
    assert by_url["https://www.shopltk.com/explore/ig_seed"]["provider"] == "instagram"
    assert by_url["https://shopmy.us/yt_seed"]["provider"] == "youtube"
    assert by_url["https://www.pinterest.com/tt_seed/"]["provider"] == "tiktok"
    assert by_url["https://www.shopltk.com/explore/fb_seed"]["provider"] == "facebook"


@pytest.mark.anyio
async def test_discovered_seed_source_meta_survives_to_seed_item(monkeypatch):
    """即使社交搜索被禁用，如果未来启用，source_meta 仍应正确传递。

    本测试通过直接调用内部逻辑验证 source_meta 结构正确性，
    不依赖社交平台搜索（SEED_SOCIAL_SEARCH_PLATFORMS 为空）。
    """
    ig_profile = PlatformCandidateProfile(
        platform="instagram",
        username="found_user",
        profile_url="https://www.instagram.com/found_user/",
        bio="Check https://shopmy.us/shop/real_seed_creator",
        source_post_url="https://www.instagram.com/p/post1/",
        source_meta={"source_input_url": "https://www.instagram.com/found_user/"},
    )

    async def _fake_discover(task, platform):
        del platform
        return SimpleNamespace(profiles=[ig_profile], errors=[])

    monkeypatch.setattr(
        "app.services.api_direct_provider.discover_platform",
        _fake_discover,
    )
    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.settings.shopping_seed_search_provider",
        "disabled",
    )

    # 直接调用 via_social_search 并临时注入非空平台列表来验证 meta 逻辑
    from app.services.shopping_seed_discovery_provider import (
        discover_shopping_seeds_via_social_search,
        SEED_SOCIAL_SEARCH_PLATFORMS,
    )

    original = list(SEED_SOCIAL_SEARCH_PLATFORMS)  # type: ignore[assignment]
    try:
        # Temporarily enable Instagram to exercise the full extraction path
        import app.services.shopping_seed_discovery_provider as _mod

        _mod.SEED_SOCIAL_SEARCH_PLATFORMS = ("instagram",)  # type: ignore[attr-defined]
        seeds = await discover_shopping_seeds_via_social_search(
            keywords=["HOMEHIVE ShopMy"],
            seed_platforms=["shopmy"],
            limit=10,
        )
    finally:
        _mod.SEED_SOCIAL_SEARCH_PLATFORMS = tuple(original)  # type: ignore[attr-defined]

    assert len(seeds) >= 1
    meta = getattr(seeds[0], "source_meta", {})
    assert meta["link_seed_platform"] == "shopmy"
    assert meta["provider"] == "instagram"


@pytest.mark.anyio
async def test_discover_shopping_seed_profiles_returns_empty_when_search_empty(monkeypatch):
    async def _empty_public_search(query, allowed_platforms, *, limit=20):
        del query, allowed_platforms, limit
        return []

    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.search_public_web_for_seed_refs",
        _empty_public_search,
    )
    seeds = await discover_shopping_seed_profiles(
        keywords=["fashion blogger"],
        seed_platforms=["ltk"],
        limit=5,
    )
    assert seeds == []


@pytest.mark.anyio
async def test_public_web_seed_search_discovers_real_seed_without_manual_link(monkeypatch):
    search_calls: list[str] = []
    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.settings.shopping_seed_search_provider",
        "public_web",
    )

    async def _fake_public_search(query, allowed_platforms, *, limit=20):
        del limit
        search_calls.append(query)
        assert allowed_platforms == {"ltk", "shopmy", "pinterest"}
        if "HOMEHIVE" not in query:
            return []
        return [
            {
                "link_seed_platform": "ltk",
                "link_seed_profile_url": "https://www.shopltk.com/explore/homehive_creator",
                "link_seed_username": "homehive_creator",
                "discovery_source": "search_result",
                "discovery_query": query,
                "source_platform": "public_web",
                "source_profile_url": "",
                "source_post_url": "",
                "source_input_url": "https://www.shopltk.com/explore/homehive_creator",
                "search_result_url": "https://www.shopltk.com/explore/homehive_creator",
            }
        ]

    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.search_public_web_for_seed_refs",
        _fake_public_search,
    )

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["HOMEHIVE LTK"],
        seed_platforms=["ltk", "shopmy", "pinterest"],
        limit=10,
    )

    assert search_calls
    assert len(seeds) == 1
    assert seeds[0].platform == "ltk"
    assert seeds[0].username == "homehive_creator"
    assert seeds[0].profile_url == "https://www.shopltk.com/explore/homehive_creator"
    meta = getattr(seeds[0], "source_meta", {}) or {}
    assert meta["discovery_source"] == "search_result"
    assert meta["source_platform"] == "public_web"
    assert meta["search_platform"] == "public_web"


@pytest.mark.anyio
async def test_public_web_seed_search_extracts_bing_result_when_duckduckgo_fails(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    calls: list[str] = []
    monkeypatch.setattr(provider.settings, "shopping_seed_public_search_engines", "duckduckgo,bing")

    class _Response:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def get(self, url):
            calls.append(url)
            if "duckduckgo" in url:
                raise provider.httpx.ConnectTimeout("")
            return _Response(
                '<a href="https://www.bing.com/ck/a?u=aHR0cHM6Ly93d3cuc2hvcGx0ay5jb20vZXhwbG9yZS9iaW5nX3NlZWQ&ntb=1">seed</a>'
            )

    monkeypatch.setattr(provider.httpx, "AsyncClient", _Client)

    refs = await provider.search_public_web_for_seed_refs("HOMEHIVE LTK", {"ltk"}, limit=5)

    assert any("duckduckgo" in call for call in calls)
    assert any("bing" in call for call in calls)
    assert refs[0]["link_seed_profile_url"] == "https://www.shopltk.com/explore/bing_seed"


@pytest.mark.anyio
async def test_public_web_seed_search_extracts_ltk_search_profiles(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    class _Response:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def get(self, url):
            if "shopltk.com/search" in url:
                return _Response('profiles:{profiles:{"1":{displayName:"real_ltk_creator",fullName:"Real Creator"}}}')
            return _Response("")

    monkeypatch.setattr(provider.httpx, "AsyncClient", _Client)

    refs = await provider.search_public_web_for_seed_refs("fashion LTK", {"ltk"}, limit=5)

    assert refs[0]["link_seed_profile_url"] == "https://www.shopltk.com/explore/real_ltk_creator"
    assert refs[0]["discovery_source"] == "ltk_search_result"


@pytest.mark.anyio
async def test_public_web_seed_search_extracts_shopmy_direct_search_profiles(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    calls: list[str] = []
    monkeypatch.setattr(provider.settings, "shopping_seed_public_search_engines", "shopmy")

    class _Response:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def get(self, url):
            calls.append(url)
            return _Response(
                '<a href="/shop/real_shopmy_creator">Real ShopMy Creator</a>'
                '<a href="https://shopmy.us/another_creator">Another Creator</a>'
            )

    monkeypatch.setattr(provider.httpx, "AsyncClient", _Client)

    refs = await provider.search_public_web_for_seed_refs("amazon finds shopmy", {"shopmy"}, limit=5)

    assert calls
    assert any("shopmy.us" in call and "search" in call for call in calls)
    assert refs[0]["link_seed_profile_url"] == "https://shopmy.us/real_shopmy_creator"
    assert refs[0]["link_seed_username"] == "real_shopmy_creator"
    assert refs[0]["search_result_url"] == "https://shopmy.us/shop/real_shopmy_creator"


@pytest.mark.anyio
async def test_pinterest_apify_search_discovers_pinterest_seed(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    actor_calls: list[tuple[str, dict]] = []

    async def _fake_actor(actor_id, run_input, **kwargs):
        del kwargs
        actor_calls.append((actor_id, run_input))
        return [
            {
                "profileUrl": "https://www.pinterest.com/homehive_creator/",
                "username": "homehive_creator",
                "pinUrl": "https://www.pinterest.com/pin/123/",
                "title": "HOMEHIVE jewelry storage bags",
            }
        ]

    monkeypatch.setattr(provider.settings, "apify_token", "apify_test")
    monkeypatch.setattr(provider.settings, "shopping_seed_search_provider", "pinterest_apify")
    monkeypatch.setattr(provider, "run_actor_sync", _fake_actor)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["HOMEHIVE jewelry storage"],
        seed_platforms=["pinterest"],
        limit=5,
    )

    assert actor_calls
    assert actor_calls[0][0] == "easyapi/pinterest-search-scraper"
    assert actor_calls[0][1]["query"].startswith("HOMEHIVE jewelry storage")
    assert actor_calls[0][1]["filter"] == "all"
    assert seeds[0].platform == "pinterest"
    assert seeds[0].profile_url == "https://www.pinterest.com/homehive_creator/"
    meta = getattr(seeds[0], "source_meta", {}) or {}
    assert meta["discovery_source"] == "pinterest_apify_search_result"
    assert meta["source_post_url"] == "https://www.pinterest.com/pin/123/"


@pytest.mark.anyio
async def test_pinterest_apify_search_parses_pinner_object(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    async def _fake_actor(actor_id, run_input, **kwargs):
        del actor_id, run_input, kwargs
        return [
            {
                "id": "159314905561864531",
                "title": "Amazon finds",
                "pinner": {
                    "id": "159315042976717963",
                    "username": "amazonfinds_creator",
                    "fullName": "Amazon Finds Creator",
                    "followers": 12000,
                },
                "url": "https://www.pinterest.com/pin/159314905561864531/",
            }
        ]

    monkeypatch.setattr(provider.settings, "apify_token", "apify_test")
    monkeypatch.setattr(provider.settings, "shopping_seed_search_provider", "pinterest_apify")
    monkeypatch.setattr(provider, "run_actor_sync", _fake_actor)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds"],
        seed_platforms=["pinterest"],
        limit=5,
    )

    assert len(seeds) == 1
    assert seeds[0].platform == "pinterest"
    assert seeds[0].username == "amazonfinds_creator"
    assert seeds[0].profile_url == "https://www.pinterest.com/amazonfinds_creator/"


@pytest.mark.anyio
async def test_pinterest_apify_search_parses_board_owner_object(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    async def _fake_actor(actor_id, run_input, **kwargs):
        del actor_id, run_input, kwargs
        return [
            {
                "query": "amazon finds",
                "id": "59743201246160912",
                "name": "amazon finds",
                "slashURL": "https://www.pinterest.com/tldoerr/amazon-finds/",
                "type": "board",
                "owner": {
                    "id": "59743269965266945",
                    "username": "tldoerr",
                    "fullName": "Haus of LoveJoy",
                    "followers": 10021,
                },
            }
        ]

    monkeypatch.setattr(provider.settings, "apify_token", "apify_test")
    monkeypatch.setattr(provider.settings, "shopping_seed_search_provider", "pinterest_apify")
    monkeypatch.setattr(provider, "run_actor_sync", _fake_actor)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds"],
        seed_platforms=["pinterest"],
        limit=5,
    )

    assert len(seeds) == 1
    assert seeds[0].platform == "pinterest"
    assert seeds[0].username == "tldoerr"
    assert seeds[0].profile_url == "https://www.pinterest.com/tldoerr/"
    meta = getattr(seeds[0], "source_meta", {}) or {}
    assert meta["source_post_url"] == "https://www.pinterest.com/tldoerr/amazon-finds/"


@pytest.mark.anyio
async def test_slow_pinterest_apify_does_not_block_public_web_ltk_seed(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    errors: list[tuple[str, list[str]]] = []
    completed: list[tuple[str, int]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web", "pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 2, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_timeout_seconds", 1, raising=False)
    monkeypatch.setattr(provider.settings, "apify_pinterest_search_timeout_seconds", 1, raising=False)

    async def _public_web(query, allowed_platforms, *, limit=20):
        del allowed_platforms, limit
        return [
            {
                "link_seed_platform": "ltk",
                "link_seed_profile_url": "https://www.shopltk.com/explore/real_ltk_seed",
                "link_seed_username": "real_ltk_seed",
                "discovery_source": "ltk_search_result",
                "discovery_query": query,
                "source_platform": "public_web",
                "source_input_url": "https://www.shopltk.com/explore/real_ltk_seed",
            }
        ]

    async def _slow_pinterest(query, *, limit=20):
        del query, limit
        await asyncio.sleep(4)
        return []

    async def _mark_error(query: str, query_errors: list[str]):
        errors.append((query, query_errors))

    async def _mark_done(query: str, count: int):
        completed.append((query, count))

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _public_web)
    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _slow_pinterest)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds"],
        seed_platforms=["ltk", "pinterest"],
        on_query_error=_mark_error,
        on_query_complete=_mark_done,
        limit=5,
    )

    assert [seed.profile_url for seed in seeds] == ["https://www.shopltk.com/explore/real_ltk_seed"]
    assert completed == [("amazon finds shopltk", 1)]
    assert errors
    assert errors[0][0] == "amazon finds pinterest creator"
    assert any("pinterest_apify" in error for error in errors[0][1])


@pytest.mark.anyio
async def test_pinterest_apify_uses_own_timeout_not_public_web_timeout(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    errors: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 1, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_timeout_seconds", 1, raising=False)
    monkeypatch.setattr(provider.settings, "apify_pinterest_search_timeout_seconds", 5, raising=False)

    async def _pinterest(query, *, limit=20):
        del query, limit
        await asyncio.sleep(2)
        return [
            {
                "link_seed_platform": "pinterest",
                "link_seed_profile_url": "https://www.pinterest.com/real_seed/",
                "link_seed_username": "real_seed",
                "discovery_source": "pinterest_apify_search_result",
                "discovery_query": "amazon finds",
                "source_platform": "pinterest_apify",
                "source_input_url": "https://www.pinterest.com/real_seed/",
            }
        ]

    async def _mark_error(query: str, query_errors: list[str]):
        errors.append((query, query_errors))

    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _pinterest)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds"],
        seed_platforms=["pinterest"],
        on_query_error=_mark_error,
        limit=5,
    )

    assert [seed.profile_url for seed in seeds] == ["https://www.pinterest.com/real_seed/"]
    assert errors == []


@pytest.mark.anyio
async def test_link_seed_enrichment_hydrates_platforms_concurrently(monkeypatch):
    seed = _ltk_seed("slow_seed")

    async def _slow_none(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.05)
        return None, False

    async def _contact(item):
        del item

    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_instagram_profile_detail", _slow_none)
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_ltk_seed_detail", AsyncMock(return_value=(seed, True)))
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_tiktok_profile_detail", _slow_none)
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_youtube_profile_detail", _slow_none)
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_facebook_profile_detail", _slow_none)
    monkeypatch.setattr("app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected", _contact)

    started = time.perf_counter()
    result = await enrich_link_seed_item(seed)
    elapsed = time.perf_counter() - started

    assert result.enrichment_attempted is True
    assert elapsed < 0.15


@pytest.mark.anyio
async def test_mixed_seed_search_does_not_call_pinterest_apify_for_ltk_or_shopmy_queries(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    pinterest_calls: list[str] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web", "pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 6, raising=False)

    async def _public_web(query, allowed_platforms, *, limit=20):
        del query, allowed_platforms, limit
        return []

    async def _pinterest(query, *, limit=20):
        del limit
        pinterest_calls.append(query)
        return []

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _public_web)
    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _pinterest)

    await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds", "amazon influencer"],
        seed_platforms=["ltk", "shopmy", "pinterest"],
        limit=5,
    )

    assert "amazon finds" in pinterest_calls
    assert not any("ltk" in query.lower() for query in pinterest_calls)
    assert not any("shopmy" in query.lower() or "shopltk" in query.lower() for query in pinterest_calls)


@pytest.mark.anyio
async def test_pinterest_apify_error_is_reported_to_query_errors(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    errors: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 1, raising=False)

    async def _failing_actor(query, *, limit=20):
        del query, limit
        raise ApifyError("actor-memory-limit-exceeded")

    async def _mark_error(query: str, query_errors: list[str]):
        errors.append((query, query_errors))

    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _failing_actor)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds"],
        seed_platforms=["pinterest"],
        on_query_error=_mark_error,
        limit=5,
    )

    assert seeds == []
    assert errors == [
        (
            "amazon finds pinterest creator",
            ["pinterest_apify:apify_memory_limit_exceeded:actor-memory-limit-exceeded"],
        )
    ]


@pytest.mark.anyio
async def test_pinterest_apify_memory_limit_short_circuits_remaining_queries(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    pinterest_calls: list[str] = []
    errors: list[tuple[str, list[str]]] = []
    unavailable: list[tuple[str, dict]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_concurrency", 1, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 4, raising=False)

    async def _pinterest(query, *, limit=20):
        del limit
        pinterest_calls.append(query)
        raise ApifyError("actor-memory-limit-exceeded")

    async def _mark_error(query: str, query_errors: list[str]):
        errors.append((query, query_errors))

    async def _mark_unavailable(provider_name: str, state: dict):
        unavailable.append((provider_name, state))

    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _pinterest)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds", "amazon storefront", "amazon influencer"],
        seed_platforms=["pinterest"],
        on_query_error=_mark_error,
        on_provider_unavailable=_mark_unavailable,
        limit=5,
    )

    assert seeds == []
    assert pinterest_calls == ["amazon finds pinterest creator"]
    assert unavailable
    assert unavailable[0][0] == "pinterest_apify"
    assert unavailable[0][1]["reason"] == "apify_memory_limit_exceeded"
    assert errors[0] == (
        "amazon finds pinterest creator",
        ["pinterest_apify:apify_memory_limit_exceeded:actor-memory-limit-exceeded"],
    )
    assert any(
        err == ["pinterest_apify:provider_unavailable:apify_memory_limit_exceeded"]
        for _, err in errors[1:]
    )


@pytest.mark.anyio
async def test_pinterest_apify_network_unreachable_short_circuits_remaining_queries(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    public_calls: list[str] = []
    pinterest_calls: list[str] = []
    completed: list[str] = []
    errors: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web", "pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_concurrency", 1, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 4, raising=False)

    async def _public_web(query, allowed_platforms, *, limit=20):
        del allowed_platforms, limit
        public_calls.append(query)
        return []

    async def _pinterest(query, *, limit=20):
        del limit
        pinterest_calls.append(query)
        raise ApifyError("Apify 网络错误: All connection attempts failed")

    async def _mark_done(query: str, count: int):
        del count
        completed.append(query)

    async def _mark_error(query: str, query_errors: list[str]):
        errors.append((query, query_errors))

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _public_web)
    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _pinterest)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds", "amazon storefront", "amazon influencer"],
        seed_platforms=["pinterest"],
        on_query_complete=_mark_done,
        on_query_error=_mark_error,
        limit=5,
    )

    assert seeds == []
    assert public_calls
    assert len(public_calls) >= 2
    assert pinterest_calls == ["amazon finds pinterest creator"]
    assert completed == []
    assert len(errors) >= 2
    assert errors[0][0] == "amazon finds pinterest creator"
    assert any("network_unreachable" in error for error in errors[0][1])
    assert any(
        error == "pinterest_apify:provider_unavailable:network_unreachable"
        for _, query_errors in errors[1:]
        for error in query_errors
    )


@pytest.mark.anyio
async def test_pinterest_apify_timeout_short_circuits_remaining_queries(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    public_calls: list[str] = []
    pinterest_calls: list[str] = []
    errors: list[tuple[str, list[str]]] = []
    unavailable: list[tuple[str, dict]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web", "pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_concurrency", 1, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 4, raising=False)

    async def _public_web(query, allowed_platforms, *, limit=20):
        del allowed_platforms, limit
        public_calls.append(query)
        return []

    async def _pinterest(query, *, limit=20):
        del limit
        pinterest_calls.append(query)
        raise TimeoutError()

    async def _mark_error(query: str, query_errors: list[str]):
        errors.append((query, query_errors))

    async def _mark_unavailable(provider_name: str, state: dict):
        unavailable.append((provider_name, state))

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _public_web)
    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _pinterest)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds", "amazon storefront", "amazon influencer"],
        seed_platforms=["pinterest"],
        on_query_error=_mark_error,
        on_provider_unavailable=_mark_unavailable,
        limit=5,
    )

    assert seeds == []
    assert len(public_calls) >= 2
    assert pinterest_calls == ["amazon finds pinterest creator"]
    assert unavailable == [
        (
            "pinterest_apify",
            {
                "status": "provider_unavailable",
                "reason": "query_timeout",
                "message": "Pinterest Apify 搜索请求超时，已跳过后续 Pinterest Apify 查询",
                "provider": "pinterest_apify",
            },
        )
    ]
    assert errors[0] == ("amazon finds pinterest creator", ["pinterest_apify:query_timeout"])
    assert any(
        query_errors == ["pinterest_apify:provider_unavailable:query_timeout"]
        for _, query_errors in errors[1:]
    )


@pytest.mark.anyio
async def test_pinterest_apify_timeout_does_not_trigger_global_empty_query_stop(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    public_calls: list[str] = []
    pinterest_calls: list[str] = []
    skipped: list[tuple[str, str]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web", "pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_concurrency", 1, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 5, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_empty_query_stop_count", 1, raising=False)

    async def _public_web(query, allowed_platforms, *, limit=20):
        del allowed_platforms, limit
        public_calls.append(query)
        return []

    async def _pinterest(query, *, limit=20):
        del limit
        pinterest_calls.append(query)
        raise TimeoutError()

    async def _mark_skip(query: str, reason: str):
        skipped.append((query, reason))

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _public_web)
    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _pinterest)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["HOMEHIVE Amazon finds", "HOMEHIVE LTK", "HOMEHIVE ShopMy"],
        seed_platforms=["ltk", "shopmy", "pinterest"],
        on_query_skip=_mark_skip,
        limit=5,
    )

    assert seeds == []
    assert pinterest_calls == ["HOMEHIVE Amazon finds pinterest creator"]
    assert len(public_calls) >= 3
    assert not any(reason == "empty_query_stop" for _, reason in skipped)


@pytest.mark.anyio
async def test_pinterest_apify_network_unreachable_short_circuits_concurrent_batch(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    public_calls: list[str] = []
    pinterest_calls: list[str] = []
    errors: list[tuple[str, list[str]]] = []
    unavailable: list[tuple[str, dict]] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["public_web", "pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_concurrency", 3, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 5, raising=False)

    async def _public_web(query, allowed_platforms, *, limit=20):
        del allowed_platforms, limit
        public_calls.append(query)
        return []

    async def _pinterest(query, *, limit=20):
        del limit
        pinterest_calls.append(query)
        raise ApifyError("Apify 网络错误: All connection attempts failed")

    async def _mark_error(query: str, query_errors: list[str]):
        errors.append((query, query_errors))

    async def _mark_unavailable(provider_name: str, state: dict):
        unavailable.append((provider_name, state))

    monkeypatch.setattr(provider, "search_public_web_for_seed_refs", _public_web)
    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _pinterest)

    seeds = await discover_shopping_seeds_via_social_search(
        keywords=["amazon finds", "amazon storefront", "amazon influencer"],
        seed_platforms=["pinterest"],
        on_query_error=_mark_error,
        on_provider_unavailable=_mark_unavailable,
        limit=5,
    )

    assert seeds == []
    assert len(public_calls) >= 3
    assert pinterest_calls == ["amazon finds pinterest creator"]
    assert unavailable == [
        (
            "pinterest_apify",
            {
                "status": "provider_unavailable",
                "reason": "network_unreachable",
                "message": "当前环境无法连接 Apify（api.apify.com:443）",
                "provider": "pinterest_apify",
            },
        )
    ]
    assert any(
        error == "pinterest_apify:provider_unavailable:network_unreachable"
        for _, query_errors in errors[1:]
        for error in query_errors
    )


@pytest.mark.anyio
async def test_pinterest_network_unreachable_checkpoint_is_retriable(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    class FakeDb:
        def __init__(self):
            self.commits = 0

        async def commit(self):
            self.commits += 1

    fail = True
    pinterest_calls: list[str] = []

    monkeypatch.setattr(provider, "configured_seed_search_platforms", lambda: ["pinterest_apify"])
    monkeypatch.setattr(provider.settings, "shopping_seed_search_concurrency", 1, raising=False)
    monkeypatch.setattr(provider.settings, "shopping_seed_search_max_queries", 1, raising=False)

    async def _pinterest(query, *, limit=20):
        del limit
        pinterest_calls.append(query)
        if fail:
            raise ApifyError("Apify 网络错误: All connection attempts failed")
        return [
            {
                "link_seed_platform": "pinterest",
                "link_seed_profile_url": "https://www.pinterest.com/retried_seed/",
                "link_seed_username": "retried_seed",
                "discovery_source": "pinterest_apify_search_result",
                "discovery_query": query,
                "source_platform": "pinterest_apify",
                "source_input_url": "https://www.pinterest.com/retried_seed/",
            }
        ]

    monkeypatch.setattr(provider, "search_pinterest_apify_for_seed_refs", _pinterest)

    task = CollectionTask(
        name="pinterest-network-retry",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="pinterest",
        platforms=["pinterest"],
        keywords=["amazon finds"],
        product_id=1,
        user_id=1,
        workspace_id=1,
    )
    db = FakeDb()

    seeds = await discover_shopping_seeds_from_task(task, db=db)
    checkpoint = task.run_checkpoint or {}

    assert seeds == []
    assert checkpoint.get("completed_queries") in (None, [])
    assert checkpoint.get("failed_queries")
    assert checkpoint.get("query_errors")
    assert checkpoint.get("provider_availability_state", {}).get("pinterest_apify", {}).get("reason") == "network_unreachable"

    fail = False
    seeds = await discover_shopping_seeds_from_task(task, db=db)

    assert [seed.profile_url for seed in seeds] == ["https://www.pinterest.com/retried_seed/"]
    assert len(pinterest_calls) == 2
    assert (task.run_checkpoint or {}).get("completed_queries")


@pytest.mark.anyio
async def test_pinterest_apify_search_raises_provider_errors(monkeypatch):
    from app.services import shopping_seed_discovery_provider as provider

    async def _failing_actor(actor_id, run_input, **kwargs):
        del actor_id, run_input, kwargs
        raise ApifyError("actor-memory-limit-exceeded")

    monkeypatch.setattr(provider.settings, "apify_token", "apify_test")
    monkeypatch.setattr(provider, "run_actor_sync", _failing_actor)

    with pytest.raises(ApifyError, match="actor-memory-limit-exceeded"):
        await provider.search_pinterest_apify_for_seed_refs("amazon finds", limit=5)


def test_pick_best_profile_prefers_email_over_instagram_followers():
    ig = CollectedInfluencer(
        platform="instagram",
        username="creator_a",
        profile_url="https://www.instagram.com/creator_a/",
        followers_count=500_000,
        engagement_rate=3.0,
        bio="Fashion",
    )
    tt = CollectedInfluencer(
        platform="tiktok",
        username="creator_a",
        profile_url="https://www.tiktok.com/@creator_a",
        followers_count=40_000,
        engagement_rate=4.0,
        bio="DM for collab",
        final_email="creator@brand.com",
        email="creator@brand.com",
    )
    best = _pick_best_profile([ig, tt])
    assert best is not None
    assert best.platform == "tiktok"
    assert _compute_enrichment_score(tt) > _compute_enrichment_score(ig)


@pytest.mark.anyio
async def test_enrich_seed_tiktok_detail(monkeypatch):
    seed = _ltk_seed("seed_creator")
    tt = CollectedInfluencer(
        platform="tiktok",
        username="seed_creator",
        profile_url="https://www.tiktok.com/@seed_creator",
        followers_count=80_000,
        engagement_rate=3.5,
        bio="Outfits",
    )
    _mock_enrichment_platforms(monkeypatch, {"tiktok": tt})
    result = await enrich_link_seed_item(seed)
    assert result.item.platform == "tiktok"
    assert result.platform_detail_fetched
    assert result.enriched_profile_url == tt.profile_url
    assert any(c.get("platform") == "tiktok" and c.get("status") == "fetched" for c in result.enrichment_candidates)


@pytest.mark.anyio
async def test_hydrate_ltk_seed_detail_reads_public_profile_html(monkeypatch):
    seed = _ltk_seed("RachelTheEverydayMom")
    html = """
    <html>
      <head>
        <script type="application/ld+json">{
          "@context": "http://schema.org/",
          "@type": "OnlineStore",
          "name": "RachelTheEverydayMom's LTK Shop",
          "founder": "RachelTheEverydayMom",
          "description": "Amazon home finds and mom favorites",
          "image": "https://avatar-cdn.liketoknow.it/avatar.jpg",
          "url": "https://www.shopltk.com/explore/RachelTheEverydayMom"
        }</script>
      </head>
      <body>
        <div class="disabled-grey--text">7 followers</div>
        <a href="https://www.instagram.com/rachel_everyday/">Instagram</a>
        <a href="https://www.instagram.com/shop.LTK/?hl=en">Official LTK</a>
      </body>
    </html>
    """

    class _Response:
        status_code = 200
        text = html

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            assert url == seed.profile_url
            return _Response()

    monkeypatch.setattr("app.services.link_seed_enrichment.httpx.AsyncClient", lambda **kwargs: _Client())

    item, fetched = await _hydrate_ltk_seed_detail(seed)

    assert fetched
    assert item.bio == "Amazon home finds and mom favorites"
    assert item.avatar_url == "https://avatar-cdn.liketoknow.it/avatar.jpg"
    assert item.followers_count == 7
    assert any(link["url"] == "https://www.instagram.com/rachel_everyday/" for link in item.other_social_links)
    assert not any(link["url"].startswith("https://www.instagram.com/shop.LTK") for link in item.other_social_links)
    assert not any(link["type"] == "ltk" for link in item.other_social_links)
    assert "ltk_detail_fetched" in item.tags


@pytest.mark.anyio
async def test_enrich_ltk_seed_uses_social_link_from_ltk_profile(monkeypatch):
    seed = _ltk_seed("RachelTheEverydayMom")
    seed.other_social_links = [
        {"type": "instagram", "url": "https://www.instagram.com/rachel_everyday/", "label": "Instagram"}
    ]
    ig = CollectedInfluencer(
        platform="instagram",
        username="rachel_everyday",
        profile_url="https://www.instagram.com/rachel_everyday/",
        followers_count=42_000,
        bio="Amazon home finds",
        tags=["instagram_detail_fetched"],
    )

    monkeypatch.setattr(
        "app.services.link_seed_enrichment._hydrate_ltk_seed_detail",
        AsyncMock(return_value=(seed, True)),
    )
    monkeypatch.setattr(
        "app.services.link_seed_enrichment._hydrate_instagram_profile_detail",
        AsyncMock(return_value=(ig, True)),
    )
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_tiktok_profile_detail", AsyncMock(return_value=(None, False)))
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_youtube_profile_detail", AsyncMock(return_value=(None, False)))
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_facebook_profile_detail", AsyncMock(return_value=(None, False)))
    monkeypatch.setattr(
        "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )

    result = await enrich_link_seed_item(seed)

    assert result.item.platform == "instagram"
    assert result.item.username == "rachel_everyday"
    assert result.enriched_profile_url == "https://www.instagram.com/rachel_everyday/"
    assert result.social_profiles_found == 1
    assert any(c.get("profile_url") == "https://www.instagram.com/rachel_everyday/" for c in result.enrichment_candidates)


@pytest.mark.anyio
async def test_enrich_seed_platform_timeout_keeps_fast_candidate(monkeypatch):
    seed = _ltk_seed("seed_creator")
    tt = CollectedInfluencer(
        platform="tiktok",
        username="seed_creator",
        profile_url="https://www.tiktok.com/@seed_creator",
        followers_count=80_000,
        bio="Amazon finds",
        tags=["tiktok_detail_fetched"],
    )

    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_ltk_seed_detail", AsyncMock(return_value=(seed, True)))
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_instagram_profile_detail", AsyncMock(return_value=(None, False)))
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_tiktok_profile_detail", AsyncMock(return_value=(tt, True)))
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_facebook_profile_detail", AsyncMock(return_value=(None, False)))

    async def _slow_youtube(username, display_name):
        del username, display_name
        await asyncio.sleep(0.05)
        return None, False

    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_youtube_profile_detail", _slow_youtube)
    monkeypatch.setattr("app.services.link_seed_enrichment.settings.link_seed_enrich_timeout_seconds", 0.01)
    monkeypatch.setattr(
        "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )

    result = await enrich_link_seed_item(seed)

    assert result.item.platform == "tiktok"
    assert any(c.get("platform") == "youtube" and c.get("status") == "timeout" for c in result.enrichment_candidates)


@pytest.mark.anyio
async def test_enrich_seed_youtube_detail(monkeypatch):
    seed = _ltk_seed("seed_creator")
    yt = CollectedInfluencer(
        platform="youtube",
        username="seed_creator",
        profile_url="https://www.youtube.com/@seed_creator",
        followers_count=120_000,
        engagement_rate=2.8,
        bio="Reviews",
    )
    _mock_enrichment_platforms(monkeypatch, {"youtube": yt})
    result = await enrich_link_seed_item(seed)
    assert result.item.platform == "youtube"
    assert result.platform_detail_fetched


@pytest.mark.anyio
async def test_enrich_seed_instagram_fail_continues_tiktok(monkeypatch):
    seed = _ltk_seed("seed_creator")
    tt = CollectedInfluencer(
        platform="tiktok",
        username="seed_creator",
        profile_url="https://www.tiktok.com/@seed_creator",
        followers_count=80_000,
        engagement_rate=3.5,
        bio="Daily fashion",
        tags=["tiktok_detail_fetched"],
    )

    async def _fail_scrape(urls):
        del urls
        raise RuntimeError("instagram provider down")

    scrape_mock = AsyncMock(side_effect=_fail_scrape)
    for target in INSTAGRAM_SCRAPE_PATCH_TARGETS:
        monkeypatch.setattr(target, scrape_mock)

    async def _tt(username):
        del username
        return tt, True

    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_tiktok_profile_detail", _tt)
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_youtube_profile_detail", AsyncMock(return_value=(None, False)))
    monkeypatch.setattr("app.services.link_seed_enrichment._hydrate_facebook_profile_detail", AsyncMock(return_value=(None, False)))
    monkeypatch.setattr(
        "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )

    result = await enrich_link_seed_item(seed)
    assert any(c.get("platform") == "instagram" and c.get("status") == "failed" for c in result.enrichment_candidates)
    assert result.item.platform == "tiktok"


@pytest.mark.anyio
async def test_hydrate_tiktok_uses_discover_platform(monkeypatch):
    tt = CollectedInfluencer(
        platform="tiktok",
        username="seed_creator",
        profile_url="https://www.tiktok.com/@seed_creator",
        followers_count=50_000,
        bio="Fashion",
    )
    discover_calls: list[str] = []

    async def _fake_discover(task, platform):
        discover_calls.append(platform)
        profile = PlatformCandidateProfile(
            platform="tiktok",
            username="seed_creator",
            profile_url="https://www.tiktok.com/@seed_creator",
            bio="Fashion",
            followers_count=50_000,
        )
        return SimpleNamespace(profiles=[profile], errors=[])

    monkeypatch.setattr("app.services.api_direct_provider.discover_platform", _fake_discover)

    item, fetched = await _hydrate_tiktok_profile_detail("seed_creator")
    assert discover_calls == ["tiktok"]
    assert fetched
    assert item is not None
    assert item.platform == "tiktok"


@pytest.mark.anyio
async def test_hydrate_facebook_uses_discover_platform(monkeypatch):
    from app.services.link_seed_enrichment import _hydrate_facebook_profile_detail

    discover_calls: list[str] = []

    async def _fake_discover(task, platform):
        discover_calls.append(platform)
        profile = PlatformCandidateProfile(
            platform="facebook",
            username="seed_creator",
            profile_url="https://www.facebook.com/seed_creator",
            followers_count=20_000,
            bio="Home decor",
        )
        return SimpleNamespace(profiles=[profile], errors=[])

    monkeypatch.setattr("app.services.api_direct_provider.discover_platform", _fake_discover)
    monkeypatch.setattr(
        "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )

    item, fetched = await _hydrate_facebook_profile_detail("seed_creator")
    assert discover_calls == ["facebook"]
    assert fetched
    assert item is not None
    assert item.platform == "facebook"


@pytest.mark.anyio
async def test_link_seed_discovery_tiktok_inserts(monkeypatch):
    seed = _ltk_seed("seed_creator")
    seed.source_meta = {
        "link_seed_platform": "ltk",
        "link_seed_profile_url": seed.profile_url,
        "link_seed_username": seed.username,
        "discovery_source": "instagram_bio",
        "discovery_query": "HOMEHIVE LTK",
        "source_platform": "instagram",
        "source_profile_url": "https://www.instagram.com/source_creator/",
        "source_post_url": "https://www.instagram.com/p/post1/",
        "source_input_url": "https://www.instagram.com/source_creator/",
    }
    tt = CollectedInfluencer(
        platform="tiktok",
        username="seed_creator",
        profile_url="https://www.tiktok.com/@seed_creator",
        followers_count=80_000,
        engagement_rate=3.5,
        bio="Collab hello@brand.com",
        final_email="hello@brand.com",
        email="hello@brand.com",
        tags=["tiktok_detail_fetched", "link_seed:ltk"],
    )

    async def _fake_discover(task):
        del task
        return [seed]

    monkeypatch.setattr(
        "app.services.shopping_seed_runner.discover_shopping_seeds_from_task",
        _fake_discover,
    )

    async def _fake_enrich(seed_item):
        from app.services.link_seed_enrichment import LinkSeedEnrichmentResult

        merged = merge_seed_into_primary(seed_item, tt)
        return LinkSeedEnrichmentResult(
            item=merged,
            seed_platform="ltk",
            seed_profile_url=seed_item.profile_url,
            seed_username=seed_item.username,
            enrichment_attempted=True,
            is_valuable=True,
            social_profiles_found=1,
            platform_detail_fetched=True,
            enriched_profile_url=tt.profile_url,
            enrichment_candidates=[
                {
                    "platform": "tiktok",
                    "profile_url": tt.profile_url,
                    "status": "fetched",
                    "followers_count": 80000,
                    "has_email": True,
                    "score": 90,
                }
            ],
            selected_reason="TikTok 有公开联系方式",
        )

    monkeypatch.setattr("app.services.shopping_seed_runner.enrich_link_seed_item", _fake_enrich)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    task = CollectionTask(
        name="seed-discovery-tiktok",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="ltk",
        platforms=["ltk"],
        keywords=["fashion creator"],
        input_urls=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        min_followers_count=10_000,
        min_engagement_rate=2.0,
        require_email=True,
        insert_qualified_only=True,
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await ShoppingSeedDiscoveryService.run_collection_task(db, task)
        await db.refresh(task)
        assert task.inserted_count == 1

        page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
        cand = page.items[0]
        assert cand.status == CandidateStatus.INSERTED.value
        assert cand.platform == "tiktok"
        assert cand.profile_url == tt.profile_url
        assert cand.source_input_url == seed.profile_url
        assert cand.source_type == "link_seed_discovered"
        meta = cand.source_meta or {}
        assert meta.get("link_seed_platform") == "ltk"
        assert meta.get("discovery_source") == "instagram_bio"
        assert meta.get("discovery_query") == "HOMEHIVE LTK"
        assert meta.get("source_platform") == "instagram"
        assert meta.get("source_profile_url") == "https://www.instagram.com/source_creator/"
        assert meta.get("source_post_url") == "https://www.instagram.com/p/post1/"
        assert meta.get("source_input_url") == "https://www.instagram.com/source_creator/"
        assert meta.get("enriched_platform") == "tiktok"
        assert meta.get("enriched_profile_url") == tt.profile_url
        assert meta.get("selected_reason")
        assert meta.get("profile_snapshot", {}).get("profile_url") == tt.profile_url
        checkpoint = task.run_checkpoint or {}
        assert checkpoint.get("seed_discovered_count") == 1
        assert checkpoint.get("seed_enriched_count") == 1
        assert checkpoint.get("social_profiles_found_count") == 1
        assert checkpoint.get("inserted_count") == 1
        assert "filtered_by_product_match_count" in checkpoint
        assert "filtered_by_quality_count" in checkpoint
        assert "platform_failed_count" in checkpoint
        assert "skipped_platform_count" in checkpoint
        await db.rollback()


@pytest.mark.anyio
async def test_link_seed_discovery_no_email_keeps_snapshot(monkeypatch):
    seed = _ltk_seed("seed_creator")
    tt = CollectedInfluencer(
        platform="tiktok",
        username="seed_creator",
        profile_url="https://www.tiktok.com/@seed_creator",
        followers_count=80_000,
        engagement_rate=3.5,
        bio="Daily fashion",
        display_name="Seed Creator TT",
        avatar_url="https://cdn.example.com/tt.jpg",
        contact_fetch_status="success",
        tags=["tiktok_detail_fetched", "link_seed:ltk"],
    )

    async def _fake_discover(task):
        del task
        return [seed]

    monkeypatch.setattr(
        "app.services.shopping_seed_runner.discover_shopping_seeds_from_task",
        _fake_discover,
    )

    async def _fake_enrich(seed_item):
        from app.services.link_seed_enrichment import LinkSeedEnrichmentResult

        merged = merge_seed_into_primary(seed_item, tt)
        return LinkSeedEnrichmentResult(
            item=merged,
            seed_platform="ltk",
            seed_profile_url=seed_item.profile_url,
            seed_username=seed_item.username,
            enrichment_attempted=True,
            is_valuable=True,
            social_profiles_found=1,
            platform_detail_fetched=True,
            enriched_profile_url=tt.profile_url,
            enrichment_candidates=[],
        )

    monkeypatch.setattr("app.services.shopping_seed_runner.enrich_link_seed_item", _fake_enrich)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    task = CollectionTask(
        name="seed-discovery-no-email",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="ltk",
        platforms=["ltk"],
        keywords=["fashion creator"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        min_followers_count=10_000,
        require_email=True,
        insert_qualified_only=True,
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await ShoppingSeedDiscoveryService.run_collection_task(db, task)
        await db.refresh(task)
        assert task.inserted_count == 0

        page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
        cand = page.items[0]
        assert cand.failure_reason == "missing_email"
        assert "TikTok 详情已采集，未发现公开邮箱" in (cand.insert_blocked_reason or "")
        snapshot = (cand.source_meta or {}).get("profile_snapshot") or {}
        assert snapshot.get("bio") == tt.bio
        assert snapshot.get("display_name") == tt.display_name
        await db.rollback()


@pytest.mark.anyio
async def test_keyword_discovery_seed_platform_processes_seed_results(monkeypatch):
    seed = CollectedInfluencer(
        platform="shopmy",
        username="seed_creator",
        profile_url="https://shopmy.us/seed_creator",
        display_name="Seed Creator",
    )
    seed.source_meta = {
        "link_seed_platform": "shopmy",
        "link_seed_profile_url": seed.profile_url,
        "link_seed_username": seed.username,
        "discovery_source": "public_web_search",
        "discovery_query": "travel bag shopmy",
        "source_platform": "public_web",
        "source_input_url": seed.profile_url,
    }
    tt = CollectedInfluencer(
        platform="tiktok",
        username="seed_creator",
        profile_url="https://www.tiktok.com/@seed_creator",
        followers_count=80_000,
        engagement_rate=3.5,
        bio="Collab hello@brand.com",
        final_email="hello@brand.com",
        email="hello@brand.com",
        tags=["tiktok_detail_fetched", "link_seed:shopmy"],
    )

    async def _fake_discover(task):
        assert task.collection_mode == CollectionMode.DISCOVERY.value
        assert task.platforms == ["instagram", "shopmy"]
        return [seed]

    monkeypatch.setattr(
        "app.services.shopping_seed_runner.discover_shopping_seeds_from_task",
        _fake_discover,
    )

    async def _fake_enrich(seed_item):
        from app.services.link_seed_enrichment import LinkSeedEnrichmentResult

        merged = merge_seed_into_primary(seed_item, tt)
        return LinkSeedEnrichmentResult(
            item=merged,
            seed_platform="shopmy",
            seed_profile_url=seed_item.profile_url,
            seed_username=seed_item.username,
            enrichment_attempted=True,
            is_valuable=True,
            social_profiles_found=1,
            platform_detail_fetched=True,
            enriched_profile_url=tt.profile_url,
            enrichment_candidates=[],
            selected_reason="TikTok has public email",
        )

    monkeypatch.setattr("app.services.shopping_seed_runner.enrich_link_seed_item", _fake_enrich)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    task = CollectionTask(
        name="keyword-seed-discovery",
        collection_mode=CollectionMode.DISCOVERY.value,
        platform="multi",
        platforms=["instagram", "shopmy"],
        keywords=["travel bag"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        min_followers_count=10_000,
        min_engagement_rate=2.0,
        require_email=True,
        insert_qualified_only=True,
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        result = await ShoppingSeedDiscoveryService.run_keyword_seed_discovery(db, task)

        assert result.discovered_count == 1
        assert result.seed_enriched_count == 1
        assert result.exec_result.new_count + result.exec_result.updated_count == 1
        assert result.exec_result.seed_social_profiles_found == 1
        assert result.exec_result.candidate_rows
        row = result.exec_result.candidate_rows[0]
        assert row["status"] == CandidateStatus.INSERTED.value
        assert row["platform"] == "tiktok"
        assert row["source_type"] == CandidateSourceType.LINK_SEED_DISCOVERED.value
        assert row["source_discovery_type"] == "link_seed_expanded"
        assert row["source_input_url"] == seed.profile_url
        await db.rollback()


@pytest.mark.anyio
async def test_keyword_seed_runner_skips_completed_seed_urls_and_enriches_concurrently(monkeypatch):
    seeds = [
        CollectedInfluencer(
            platform="shopmy",
            username="done_seed",
            profile_url="https://shopmy.us/done_seed",
            display_name="Done Seed",
        ),
        CollectedInfluencer(
            platform="shopmy",
            username="seed_one",
            profile_url="https://shopmy.us/seed_one",
            display_name="Seed One",
        ),
        CollectedInfluencer(
            platform="shopmy",
            username="seed_two",
            profile_url="https://shopmy.us/seed_two",
            display_name="Seed Two",
        ),
    ]
    running = 0
    max_running = 0
    enriched: list[str] = []

    async def _fake_discover(task):
        return seeds

    async def _fake_enrich(seed_item):
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0.01)
        running -= 1
        enriched.append(seed_item.profile_url)
        return SimpleNamespace(
            item=CollectedInfluencer(
                platform="shopmy",
                username=seed_item.username,
                profile_url=seed_item.profile_url,
                display_name=seed_item.display_name,
            ),
            enriched_profile_url=seed_item.profile_url,
            primary_platform="shopmy",
            enrichment_attempted=True,
            social_profiles_found=0,
            enrichment_candidates=[],
        )

    async def _fake_process(*args, **kwargs):
        exec_result = kwargs["exec_result"]
        exec_result.not_inserted_count += 1

    monkeypatch.setattr("app.services.shopping_seed_runner.discover_shopping_seeds_from_task", _fake_discover)
    monkeypatch.setattr("app.services.shopping_seed_runner.enrich_link_seed_item", _fake_enrich)
    monkeypatch.setattr("app.services.shopping_seed_runner.enrichment_meta_dict", lambda enrichment: {})
    monkeypatch.setattr(LinkImportService, "_process_import_item", _fake_process)
    monkeypatch.setattr("app.core.config.settings.link_seed_enrich_concurrency", 2)

    task = CollectionTask(
        name="keyword-seed-checkpoint",
        collection_mode=CollectionMode.DISCOVERY.value,
        platform="shopmy",
        platforms=["shopmy"],
        keywords=["amazon finds"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        run_checkpoint={"completed_seed_urls": ["https://shopmy.us/done_seed"]},
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        result = await ShoppingSeedDiscoveryService.run_keyword_seed_discovery(db, task)

        assert result.discovered_count == 3
        assert "https://shopmy.us/done_seed" not in enriched
        assert set(enriched) == {"https://shopmy.us/seed_one", "https://shopmy.us/seed_two"}
        assert max_running == 2
        checkpoint = task.run_checkpoint or {}
        assert checkpoint["skipped_due_checkpoint_count"] >= 1
        assert "https://shopmy.us/seed_one" in checkpoint["completed_seed_urls"]
        assert "https://shopmy.us/seed_two" in checkpoint["completed_seed_urls"]
        await db.rollback()


@pytest.mark.anyio
async def test_keyword_seed_runner_skips_completed_profile_and_platform_detail(monkeypatch):
    seeds = [
        CollectedInfluencer(
            platform="shopmy",
            username="seed_one",
            profile_url="https://shopmy.us/seed_one",
            display_name="Seed One",
        ),
        CollectedInfluencer(
            platform="shopmy",
            username="seed_two",
            profile_url="https://shopmy.us/seed_two",
            display_name="Seed Two",
        ),
    ]
    enriched: list[str] = []
    processed: list[str] = []

    async def _fake_discover(task):
        return seeds

    async def _fake_enrich(seed_item):
        enriched.append(seed_item.profile_url)
        final_url = (
            "https://www.tiktok.com/@done_creator"
            if seed_item.username == "seed_one"
            else "https://www.instagram.com/done_creator/"
        )
        return SimpleNamespace(
            item=CollectedInfluencer(
                platform="tiktok" if seed_item.username == "seed_one" else "instagram",
                username="done_creator",
                profile_url=final_url,
                display_name="Done Creator",
            ),
            enriched_profile_url=final_url,
            primary_platform="tiktok" if seed_item.username == "seed_one" else "instagram",
            enrichment_attempted=True,
            social_profiles_found=1,
            enrichment_candidates=[],
        )

    async def _fake_process(*args, **kwargs):
        processed.append(args[1].profile_url)

    monkeypatch.setattr("app.services.shopping_seed_runner.discover_shopping_seeds_from_task", _fake_discover)
    monkeypatch.setattr("app.services.shopping_seed_runner.enrich_link_seed_item", _fake_enrich)
    monkeypatch.setattr("app.services.shopping_seed_runner.enrichment_meta_dict", lambda enrichment: {})
    monkeypatch.setattr(LinkImportService, "_process_import_item", _fake_process)

    task = CollectionTask(
        name="keyword-seed-profile-checkpoint",
        collection_mode=CollectionMode.DISCOVERY.value,
        platform="shopmy",
        platforms=["shopmy"],
        keywords=["amazon finds"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        run_checkpoint={
            "completed_profile_urls": ["https://www.tiktok.com/@done_creator"],
            "platform_detail_completed": {"instagram": ["https://www.instagram.com/done_creator/"]},
        },
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        result = await ShoppingSeedDiscoveryService.run_keyword_seed_discovery(db, task)

        assert result.discovered_count == 2
        assert len(enriched) == 2
        assert processed == []
        checkpoint = task.run_checkpoint or {}
        assert checkpoint["skipped_due_checkpoint_count"] >= 2
        assert "https://shopmy.us/seed_one" in checkpoint["completed_seed_urls"]
        assert "https://shopmy.us/seed_two" in checkpoint["completed_seed_urls"]
        await db.rollback()


@pytest.mark.anyio
async def test_seed_and_profile_checkpoints_are_persisted_after_each_stage(monkeypatch):
    class FakeDb:
        def __init__(self):
            self.commits = 0

        async def commit(self):
            self.commits += 1

    seed = CollectedInfluencer(
        platform="shopmy",
        username="seed_one",
        profile_url="https://shopmy.us/seed_one",
        display_name="Seed One",
    )

    async def _fake_enrich(seed_item):
        return SimpleNamespace(
            item=CollectedInfluencer(
                platform="tiktok",
                username="seed_one",
                profile_url="https://www.tiktok.com/@seed_one",
                display_name="Seed One",
            ),
            enriched_profile_url="https://www.tiktok.com/@seed_one",
            primary_platform="tiktok",
            enrichment_attempted=True,
            social_profiles_found=1,
            enrichment_candidates=[],
        )

    async def _fake_process(*args, **kwargs):
        kwargs["exec_result"].new_count += 1

    monkeypatch.setattr("app.services.shopping_seed_runner.enrich_link_seed_item", _fake_enrich)
    monkeypatch.setattr("app.services.shopping_seed_runner.enrichment_meta_dict", lambda enrichment: {})
    monkeypatch.setattr(LinkImportService, "_process_import_item", _fake_process)

    task = CollectionTask(
        name="seed-profile-persist",
        collection_mode=CollectionMode.DISCOVERY.value,
        platform="shopmy",
        platforms=["shopmy"],
        keywords=["amazon finds"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
    )
    db = FakeDb()

    result, seed_enriched_count, _, _ = await ShoppingSeedDiscoveryService._process_seed_items(
        db,
        task,
        [seed],
        run_at=datetime.now(UTC),
    )

    checkpoint = task.run_checkpoint or {}
    assert result.new_count == 1
    assert seed_enriched_count == 1
    assert "https://shopmy.us/seed_one" in checkpoint["completed_seed_urls"]
    assert "https://www.tiktok.com/@seed_one" in checkpoint["completed_profile_urls"]
    assert "https://www.tiktok.com/@seed_one" in checkpoint["platform_detail_completed"]["tiktok"]
    assert db.commits >= 1


@pytest.mark.anyio
async def test_keyword_seed_runner_stops_after_target_qualified_count(monkeypatch):
    seeds = [
        CollectedInfluencer(
            platform="shopmy",
            username=f"seed_{idx}",
            profile_url=f"https://shopmy.us/seed_{idx}",
            display_name=f"Seed {idx}",
        )
        for idx in range(3)
    ]
    enriched: list[str] = []

    async def _fake_discover(task):
        return seeds

    async def _fake_enrich(seed_item):
        enriched.append(seed_item.profile_url)
        return SimpleNamespace(
            item=CollectedInfluencer(
                platform="shopmy",
                username=seed_item.username,
                profile_url=seed_item.profile_url,
                display_name=seed_item.display_name,
            ),
            enriched_profile_url=seed_item.profile_url,
            primary_platform="shopmy",
            enrichment_attempted=True,
            social_profiles_found=0,
            enrichment_candidates=[],
        )

    async def _fake_process(*args, **kwargs):
        exec_result = kwargs["exec_result"]
        exec_result.new_count += 1

    monkeypatch.setattr("app.services.shopping_seed_runner.discover_shopping_seeds_from_task", _fake_discover)
    monkeypatch.setattr("app.services.shopping_seed_runner.enrich_link_seed_item", _fake_enrich)
    monkeypatch.setattr("app.services.shopping_seed_runner.enrichment_meta_dict", lambda enrichment: {})
    monkeypatch.setattr(LinkImportService, "_process_import_item", _fake_process)
    monkeypatch.setattr("app.core.config.settings.link_seed_enrich_concurrency", 1)

    task = CollectionTask(
        name="keyword-seed-early-stop",
        collection_mode=CollectionMode.DISCOVERY.value,
        platform="shopmy",
        platforms=["shopmy"],
        keywords=["amazon finds"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        discovery_limit=1,
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        result = await ShoppingSeedDiscoveryService.run_keyword_seed_discovery(db, task)

        assert result.exec_result.new_count == 1
        assert enriched == ["https://shopmy.us/seed_0"]
        await db.rollback()


@pytest.mark.anyio
async def test_link_seed_discovery_zero_seed_records_search_diagnostics(monkeypatch):
    task = CollectionTask(
        name="seed-discovery-zero-diag",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="multi",
        platforms=["ltk", "shopmy", "pinterest"],
        keywords=["AmazonFinds"],
        input_urls=["https://www.amazon.com/dp/B0D9W576KQ?th=1"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        discovery_limit=50,
    )

    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())
    monkeypatch.setattr(
        "app.services.shopping_seed_discovery_provider.settings.shopping_seed_search_provider",
        "disabled",
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await ShoppingSeedDiscoveryService.run_collection_task(db, task)
        await db.refresh(task)

        checkpoint = task.run_checkpoint or {}
        diag = checkpoint.get("shopping_seed_discovery") or {}
        assert checkpoint.get("seed_discovered_count") == 0
        assert diag.get("seed_search_disabled") is True
        assert diag.get("zero_seed_reason") == "seed_search_provider_not_configured"
        assert diag.get("provider_call_count") == 0
        assert diag.get("profiles_returned_count") == 0
        assert diag.get("seed_extracted_count") == 0
        assert diag.get("search_platforms") == []
        queries = diag.get("queries") or []
        assert "B0D9W576KQ" in queries
        assert any("HOMEHIVE" in q and "ShopMy" in q for q in queries)
        assert "未配置 seed 搜索来源" in (task.status_summary or "")
        await db.rollback()

@pytest.mark.anyio
async def test_link_seed_runner_merges_product_evidence_diagnostics(monkeypatch):
    task = CollectionTask(
        name="seed-discovery-product-filter-diag",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="multi",
        platforms=["ltk"],
        keywords=["Aegero travel laundry bag"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        discovery_limit=50,
        run_checkpoint={
            "completed_queries": ["Aegero LTK"],
            "failed_queries": ["Aegero Pinterest"],
            "skipped_low_signal_queries": ["amazon finds"],
            "query_errors": {"Aegero Pinterest": ["pinterest_apify:provider_unavailable:network_unreachable"]},
            "provider_availability_state": {
                "pinterest_apify": {"status": "provider_unavailable", "reason": "network_unreachable"}
            },
            "shopping_seed_discovery": {
                "queries": ["Aegero LTK", "Aegero Pinterest"],
                "query_count": 2,
                "provider_call_count": 2,
                "product_evidence_filter_enabled": True,
                "product_evidence_filtered_count": 3,
                "product_evidence_verified_count": 0,
                "zero_seed_reason": "seed_found_but_no_product_evidence",
            },
            "seed_product_evidence_filtered_count": 3,
        },
    )

    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())
    monkeypatch.setattr("app.services.shopping_seed_runner.discover_shopping_seeds_from_task", AsyncMock(return_value=[]))

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await ShoppingSeedDiscoveryService.run_collection_task(db, task)
        await db.refresh(task)

        checkpoint = task.run_checkpoint or {}
        diag = checkpoint.get("shopping_seed_discovery") or {}
        assert checkpoint.get("completed_queries") == ["Aegero LTK"]
        assert checkpoint.get("failed_queries") == ["Aegero Pinterest"]
        assert checkpoint.get("skipped_low_signal_queries") == ["amazon finds"]
        assert checkpoint.get("query_errors")
        assert checkpoint.get("provider_availability_state", {}).get("pinterest_apify", {}).get("reason") == "network_unreachable"
        assert checkpoint.get("filtered_by_product_match_count") == 3
        assert diag.get("product_evidence_filtered_count") == 3
        assert diag.get("product_evidence_verified_count") == 0
        assert diag.get("zero_seed_reason") == "seed_found_but_no_product_evidence"
        assert diag.get("provider_call_count") == 2
        await db.rollback()


@pytest.mark.anyio
async def test_zero_seed_reason_provider_failed_but_fallback_no_results(monkeypatch):
    task = CollectionTask(
        name="seed-discovery-provider-fallback-zero",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        platform="multi",
        platforms=["ltk", "shopmy", "pinterest"],
        keywords=["HOMEHIVE clear PVC jewelry bags"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        discovery_limit=50,
        run_checkpoint={
            "completed_queries": ["HOMEHIVE LTK", "HOMEHIVE ShopMy"],
            "failed_queries": ["HOMEHIVE Pinterest"],
            "query_errors": {"HOMEHIVE Pinterest": ["pinterest_apify:provider_unavailable:query_timeout"]},
            "provider_availability_state": {
                "pinterest_apify": {
                    "status": "provider_unavailable",
                    "reason": "query_timeout",
                    "message": "Pinterest Apify 搜索请求超时，已跳过后续 Pinterest Apify 查询",
                }
            },
            "shopping_seed_discovery": {
                "queries": ["HOMEHIVE LTK", "HOMEHIVE ShopMy", "HOMEHIVE Pinterest"],
                "query_count": 3,
                "provider_call_count": 5,
                "public_web_query_count": 3,
                "zero_seed_reason": "seed_search_no_profiles_returned",
                "provider_availability_state": {
                    "pinterest_apify": {
                        "status": "provider_unavailable",
                        "reason": "query_timeout",
                    }
                },
            },
        },
    )

    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())
    monkeypatch.setattr("app.services.shopping_seed_runner.discover_shopping_seeds_from_task", AsyncMock(return_value=[]))

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await ShoppingSeedDiscoveryService.run_collection_task(db, task)
        await db.refresh(task)

        diag = (task.run_checkpoint or {}).get("shopping_seed_discovery") or {}
        assert diag.get("zero_seed_reason") == "provider_failed_but_fallback_no_results"
        assert diag.get("provider_availability_state", {}).get("pinterest_apify", {}).get("reason") == "query_timeout"
        assert diag.get("public_web_query_count") == 3
        await db.rollback()


def test_tiktok_missing_email_detail_after_seed_enrichment():
    item = CollectedInfluencer(
        platform="tiktok",
        username="seed_creator",
        profile_url="https://www.tiktok.com/@seed_creator",
        followers_count=80_000,
        engagement_rate=3.5,
        tags=["link_seed:ltk", "tiktok_detail_fetched"],
        contact_fetch_status="success",
    )
    task = CollectionTask(
        name="assess",
        platform="tiktok",
        platforms=["tiktok"],
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY.value,
        keywords=["fashion"],
        product_id=1,
        user_id=1,
        workspace_id=1,
        require_email=True,
        insert_qualified_only=True,
        min_followers_count=10_000,
    )
    assessment = evaluate_high_value_assessment(item, task)
    assert assessment.insert_blocked_reason == "TikTok 详情已采集，未发现公开邮箱"


# ---------------------------------------------------------------------------
# 新增测试：验证 seed 发现不再使用社交平台搜索
# ---------------------------------------------------------------------------


def test_seed_platforms_only_ltk_shopmy_pinterest():
    """seed 平台只包含 LTK / ShopMy / Pinterest，不含社交平台。"""
    from app.services.shopping_seed_discovery_provider import _SEED_PARSERS

    assert set(_SEED_PARSERS.keys()) == {"ltk", "shopmy", "pinterest"}


def test_seed_social_search_platforms_is_empty():
    """SEED_SOCIAL_SEARCH_PLATFORMS 为空，不执行任何社交平台搜索。"""
    from app.services.shopping_seed_discovery_provider import SEED_SOCIAL_SEARCH_PLATFORMS

    assert SEED_SOCIAL_SEARCH_PLATFORMS == ()
    # 确认不包含 Instagram / TikTok / YouTube / Facebook
    for p in ("instagram", "tiktok", "youtube", "facebook"):
        assert p not in SEED_SOCIAL_SEARCH_PLATFORMS


def test_search_plan_does_not_include_social_platforms():
    """搜索计划生成的 query 只围绕 LTK/ShopMy/Pinterest，
    不会产生 Instagram/TikTok/YouTube/Facebook discovery calls。"""
    keywords = [
        "B0D9W576KQ",
        "HOMEHIVE LTK",
        "HOMEHIVE ShopMy",
        "HOMEHIVE Pinterest",
    ]
    plan = build_seed_search_plan(
        keywords=keywords,
        seed_platforms=["ltk", "shopmy", "pinterest"],
        max_queries=12,
    )
    # 搜索计划应只含导购平台相关的 query（query 中包含 ltk/shopmy/pinterest）
    for item in plan:
        query = item["query"]
        has_shopping_platform = any(p in query.lower() for p in ("ltk", "shopmy", "pinterest"))
        has_social_platform = any(p in query.lower() for p in ("instagram", "tiktok", "youtube", "facebook"))
        # query 应围绕导购平台或 ASIN/品牌词，不应以社交平台名为目标
        assert not has_social_platform or has_shopping_platform
    # 确认不使用社交平台作为搜索 target
    from app.services.shopping_seed_discovery_provider import (
        SEED_SOCIAL_SEARCH_PLATFORMS,
    )

    assert len(SEED_SOCIAL_SEARCH_PLATFORMS) == 0


def test_query_cap_preserves_ltk_shopmy_and_site_fallback_queries():
    keywords = [
        "B0D9W576KQ",
        "HOMEHIVE clear PVC jewelry bags",
        "HOMEHIVE LTK",
        "HOMEHIVE ShopMy",
        "HOMEHIVE Pinterest",
        "HOMEHIVE Amazon finds",
        "HOMEHIVE clear PVC jewelry bags influencer",
        "HOMEHIVE clear PVC jewelry bags blogger",
        "site:shopltk.com/explore HOMEHIVE clear PVC jewelry bags",
        "site:shopmy.us HOMEHIVE clear PVC jewelry bags",
        "site:pinterest.com HOMEHIVE clear PVC jewelry bags",
        '"HOMEHIVE" "clear PVC jewelry bags" "shopltk"',
        '"HOMEHIVE" "clear PVC jewelry bags" "shopmy"',
    ]

    plan = build_seed_search_plan(
        keywords=keywords,
        seed_platforms=["ltk", "shopmy", "pinterest"],
        max_queries=8,
    )
    queries = [item["query"] for item in plan]

    assert any("HOMEHIVE LTK" == query or "shopltk" in query.lower() for query in queries)
    assert any("HOMEHIVE ShopMy" == query or "shopmy" in query.lower() for query in queries)
    assert any(query.startswith("site:shopltk.com/explore") for query in queries)
    assert any(query.startswith("site:shopmy.us") for query in queries)


def test_ui_payload_seed_discovery_platforms_only_shopping():
    """UI payload 中 link_seed_discovery 的 platforms 只提交 ltk/shopmy/pinterest。"""
    from app.services.shopping_seed_discovery import LINK_SEED_PLATFORMS

    assert set(LINK_SEED_PLATFORMS) == {"ltk", "shopmy", "pinterest"}
    for p in ("instagram", "tiktok", "youtube", "facebook"):
        assert p not in LINK_SEED_PLATFORMS
