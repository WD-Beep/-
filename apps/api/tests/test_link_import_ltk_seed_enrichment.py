"""LTK / ShopMy 链接 seed 补全与低价值判定测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateStatus, CollectionTaskStatus
from app.schemas.collection_task import build_link_import_task_fields
from app.services.influencer_profile_value import is_influencer_profile_valuable
from app.services.apify_instagram import ProfileScrapeResult
from app.services.high_value_filter import evaluate_high_value_assessment
from app.services.link_import import LinkImportService
from app.services.link_seed_enrichment import (
    build_seed_search_keywords,
    enrich_link_seed_item,
    enrichment_meta_dict,
    link_seed_low_value_detail,
    merge_seed_into_primary,
)
from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import profile_to_collected
from app.services.task_candidate import TaskCandidateService
from app.services.task_effectiveness import classify_task_effectiveness
from app.services.url_parser import validate_link_import_url_lines


LTK_URL = "https://www.shopltk.com/explore/ltk_creator"

LTK_URL_WITH_QUERY = (
    "https://www.shopltk.com/explore/ltk_creator?utm_source=ig&utm_medium=social"
    "&utm_content=link_in_bio"
)

INSTAGRAM_SCRAPE_PATCH_TARGETS = (
    "app.services.link_seed_enrichment.scrape_instagram_profiles",
    "app.services.instagram_provider.scrape_instagram_profiles",
)


def _instagram_profile_from_template(ig: CollectedInfluencer) -> CollectedInfluencer:
    return CollectedInfluencer(
        platform=ig.platform,
        username=ig.username,
        profile_url=ig.profile_url,
        display_name=ig.display_name,
        avatar_url=ig.avatar_url,
        bio=ig.bio,
        followers_count=ig.followers_count,
        engagement_rate=ig.engagement_rate,
        email=ig.email,
        final_email=ig.final_email,
        public_email=ig.public_email,
        business_email=ig.business_email,
        website=ig.website,
        contact_page=ig.contact_page,
        linktree_url=ig.linktree_url,
        whatsapp=ig.whatsapp,
        telegram=ig.telegram,
        contact_fetch_status=ig.contact_fetch_status,
        other_social_links=list(ig.other_social_links or []),
        tags=list(ig.tags or []),
    )


def _mock_instagram_scrape(monkeypatch, ig: CollectedInfluencer) -> list[list[str]]:
    """Mock Instagram provider / Apify 详情采集，禁止真实外网调用。"""
    scrape_calls: list[list[str]] = []

    async def _scrape(urls):
        scrape_calls.append(list(urls))
        return ProfileScrapeResult(profiles=[_instagram_profile_from_template(ig)], errors=[])

    scrape_mock = AsyncMock(side_effect=_scrape)
    for target in INSTAGRAM_SCRAPE_PATCH_TARGETS:
        monkeypatch.setattr(target, scrape_mock)
    monkeypatch.setattr(
        "app.services.link_seed_enrichment._try_tiktok_profile",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.link_seed_enrichment._try_youtube_profile",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.link_seed_enrichment._hydrate_tiktok_profile_detail",
        AsyncMock(return_value=(None, False)),
    )
    monkeypatch.setattr(
        "app.services.link_seed_enrichment._hydrate_youtube_profile_detail",
        AsyncMock(return_value=(None, False)),
    )
    monkeypatch.setattr(
        "app.services.link_seed_enrichment._hydrate_facebook_profile_detail",
        AsyncMock(return_value=(None, False)),
    )
    return scrape_calls


def _mock_seed_enrichment_no_network(monkeypatch) -> None:
    """默认空 scrape，避免未 mock 的 enrich 测试触发 Apify。"""

    async def _empty_scrape(urls):
        del urls
        return ProfileScrapeResult(profiles=[], errors=[])

    scrape_mock = AsyncMock(side_effect=_empty_scrape)
    for target in INSTAGRAM_SCRAPE_PATCH_TARGETS:
        monkeypatch.setattr(target, scrape_mock)
    monkeypatch.setattr(
        "app.services.link_seed_enrichment._try_tiktok_profile",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.link_seed_enrichment._try_youtube_profile",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )


def _ltk_shell() -> CollectedInfluencer:
    profile = PlatformCandidateProfile(
        platform="ltk",
        username="ltk_creator",
        profile_url="https://www.shopltk.com/explore/ltk_creator",
        display_name="LTK Creator",
    )
    return profile_to_collected(profile)


def _shopmy_shell() -> CollectedInfluencer:
    profile = PlatformCandidateProfile(
        platform="shopmy",
        username="shopmy_creator",
        profile_url="https://shopmy.us/shopmy_creator",
        display_name="ShopMy Creator",
    )
    return profile_to_collected(profile)


def test_build_seed_search_keywords():
    keys = build_seed_search_keywords("ltk_creator", "LTK Creator")
    assert "ltk_creator Instagram" in keys
    assert "ltk_creator TikTok" in keys
    assert "LTK Creator influencer" in keys


def test_link_seed_low_value_detail_per_platform():
    assert "LTK" in link_seed_low_value_detail("ltk")
    assert "ShopMy" in link_seed_low_value_detail("shopmy")
    assert "Pinterest" in link_seed_low_value_detail("pinterest")
    assert "社媒主页" in link_seed_low_value_detail("ltk")


def test_merge_seed_preserves_primary_profile_url():
    seed = _ltk_shell()
    primary = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        followers_count=12000,
        bio="Fashion blogger",
    )
    merged = merge_seed_into_primary(seed, primary)
    assert merged.profile_url == primary.profile_url
    assert any("shopltk" in (link.get("url") or "") for link in merged.other_social_links)


@pytest.mark.anyio
async def test_ltk_empty_enrichment_not_valuable(monkeypatch):
    shell = _ltk_shell()
    _mock_seed_enrichment_no_network(monkeypatch)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.link_seed_enrichment._try_instagram_profile",
            AsyncMock(return_value=None),
        )
        result = await enrich_link_seed_item(shell)
    assert result.is_valuable is False
    assert not is_influencer_profile_valuable(result.item)


@pytest.mark.anyio
async def test_shopmy_seed_hydrates_creator_snapshot_with_apify(monkeypatch):
    shell = _shopmy_shell()
    _mock_seed_enrichment_no_network(monkeypatch)
    actor_calls: list[tuple[str, dict]] = []

    async def _fake_actor(actor_id, run_input, **kwargs):
        del kwargs
        actor_calls.append((actor_id, run_input))
        return [
            {
                "creator": "shopmy_creator",
                "name": "ShopMy Creator",
                "profileUrl": "https://shopmy.us/shopmy_creator",
                "bio": "Curated jewelry storage finds",
                "brands": ["HOMEHIVE"],
                "collections": [{"title": "Amazon finds"}],
                "picks": [{"title": "HOMEHIVE jewelry bags", "url": "https://amazon.com/dp/B0D9W576KQ"}],
            }
        ]

    monkeypatch.setattr("app.services.link_seed_enrichment.settings.apify_token", "apify_test")
    monkeypatch.setattr("app.services.link_seed_enrichment.run_actor_sync", _fake_actor)

    result = await enrich_link_seed_item(shell)
    meta = enrichment_meta_dict(result)
    snapshot = meta.get("shopmy_profile_snapshot") or {}

    assert actor_calls
    assert actor_calls[0][0] == "vsekar91/shopmy-creator-scraper"
    assert actor_calls[0][1]["creators"] == ["shopmy_creator"]
    assert actor_calls[0][1]["includeCollectionsAndPicks"] is True
    assert actor_calls[0][1]["maxCollectionsPerCreator"] == 10
    assert snapshot["username"] == "shopmy_creator"
    assert snapshot["profile_url"] == "https://shopmy.us/shopmy_creator"
    assert snapshot["brands"] == ["HOMEHIVE"]
    assert snapshot["picks"][0]["url"] == "https://amazon.com/dp/B0D9W576KQ"
    assert result.item.bio == "Curated jewelry storage finds"
    assert "shopmy_detail_fetched" in (result.item.tags or [])


@pytest.mark.anyio
async def test_shopmy_seed_apify_error_is_not_marked_fetched(monkeypatch):
    shell = _shopmy_shell()

    async def _fake_actor(actor_id, run_input, **kwargs):
        del actor_id, run_input, kwargs
        return [{"url": "https://shopmy.us/shopmy_creator", "username": "shopmy_creator", "error": "http_400"}]

    monkeypatch.setattr("app.services.link_seed_enrichment.settings.apify_token", "apify_test")
    monkeypatch.setattr("app.services.link_seed_enrichment.run_actor_sync", _fake_actor)

    from app.services.link_seed_enrichment import _hydrate_shopmy_seed_detail

    item, fetched = await _hydrate_shopmy_seed_detail(shell)

    assert fetched is False
    assert "shopmy_detail_fetched" not in (item.tags or [])
    assert not ((getattr(item, "source_meta", {}) or {}).get("shopmy_profile_snapshot"))


@pytest.mark.anyio
async def test_ltk_enrichment_instagram_success_is_valuable(monkeypatch):
    shell = _ltk_shell()
    ig = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        followers_count=50000,
        bio="Daily outfits",
    )
    scrape_calls = _mock_instagram_scrape(monkeypatch, ig)
    result = await enrich_link_seed_item(shell)
    assert scrape_calls
    assert scrape_calls[0] == ["https://www.instagram.com/ltk_creator/"]
    assert result.is_valuable is True
    assert result.item.platform == "instagram"
    assert result.instagram_detail_fetched is True


@pytest.mark.anyio
async def test_ltk_link_import_low_value_not_effective(monkeypatch):
    async def _fake_enrich(seed):
        from app.services.link_seed_enrichment import LinkSeedEnrichmentResult

        return LinkSeedEnrichmentResult(
            item=seed,
            seed_platform="ltk",
            seed_profile_url=seed.profile_url,
            seed_username=seed.username,
            enrichment_attempted=True,
            is_valuable=False,
        )

    monkeypatch.setattr("app.services.link_import.enrich_link_seed_item", _fake_enrich)
    upsert_calls: list[str] = []

    async def _upsert(db, item, run_at, *, product_id, task=None):
        del db, item, run_at, product_id, task
        upsert_calls.append("upsert")
        return "new", SimpleNamespace(id=1, global_influencer_id=1)

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    fields = build_link_import_task_fields(validate_link_import_url_lines([LTK_URL]))
    task = CollectionTask(
        name="ltk-import",
        collection_mode=fields["collection_mode"].value,
        platform=fields["platform"],
        platforms=fields["platforms"],
        input_urls=fields["input_urls"],
        keywords=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        run_checkpoint=fields["run_checkpoint"],
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await LinkImportService.run_collection_task(db, task)
        await db.refresh(task)
        assert upsert_calls == []
        assert task.inserted_count == 0
        assert task.result_count == 0
        assert task.status == CollectionTaskStatus.COMPLETED_NO_RESULTS.value
        assert task.run_checkpoint.get("link_seed_enrichment", {}).get("low_value_seed_count") == 1
        assert classify_task_effectiveness(task, has_valuable_insert=False) == "low_value_result"
        page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
        cand = page.items[0]
        assert cand.status == CandidateStatus.NOT_INSERTED.value
        assert cand.failure_reason == "low_value_seed"
        assert link_seed_low_value_detail("ltk") in (cand.failure_detail or "")
        assert cand.source_input_url == LTK_URL
        await db.rollback()


@pytest.mark.anyio
async def test_ltk_enrichment_instagram_inserts_effective(monkeypatch):
    shell = _ltk_shell()
    ig = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        followers_count=50000,
        bio="Daily outfits",
    )

    async def _fake_enrich(seed):
        from app.services.link_seed_enrichment import LinkSeedEnrichmentResult

        merged = merge_seed_into_primary(seed, ig)
        return LinkSeedEnrichmentResult(
            item=merged,
            seed_platform="ltk",
            seed_profile_url=seed.profile_url,
            seed_username=seed.username,
            enrichment_attempted=True,
            is_valuable=True,
            social_profiles_found=1,
            instagram_detail_fetched=True,
        )

    monkeypatch.setattr("app.services.link_import.enrich_link_seed_item", _fake_enrich)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    fields = build_link_import_task_fields(validate_link_import_url_lines([LTK_URL]))
    task = CollectionTask(
        name="ltk-import-effective",
        collection_mode=fields["collection_mode"].value,
        platform=fields["platform"],
        platforms=fields["platforms"],
        input_urls=fields["input_urls"],
        keywords=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        run_checkpoint=fields["run_checkpoint"],
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await LinkImportService.run_collection_task(db, task)
        await db.refresh(task)
        assert task.inserted_count == 1
        assert classify_task_effectiveness(task, has_valuable_insert=True) == "effective"

        page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
        cand = page.items[0]
        assert cand.status == CandidateStatus.INSERTED.value
        assert cand.source_input_url == LTK_URL
        assert cand.platform == "instagram"
        await db.rollback()


@pytest.mark.anyio
async def test_ltk_display_name_only_not_effective(monkeypatch):
    shell = _ltk_shell()
    ig_shell = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        display_name="LTK Creator",
    )

    async def _fake_enrich(seed):
        from app.services.link_seed_enrichment import LinkSeedEnrichmentResult

        merged = merge_seed_into_primary(seed, ig_shell)
        return LinkSeedEnrichmentResult(
            item=merged,
            seed_platform="ltk",
            seed_profile_url=seed.profile_url,
            seed_username=seed.username,
            enrichment_attempted=True,
            is_valuable=False,
            social_profiles_found=1,
        )

    monkeypatch.setattr("app.services.link_import.enrich_link_seed_item", _fake_enrich)
    upsert_calls: list[str] = []

    async def _upsert(db, item, run_at, *, product_id, task=None):
        del db, item, run_at, product_id, task
        upsert_calls.append("upsert")
        return "new", SimpleNamespace(id=1, global_influencer_id=1)

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    fields = build_link_import_task_fields(validate_link_import_url_lines([LTK_URL]))
    task = CollectionTask(
        name="ltk-display-name-only",
        collection_mode=fields["collection_mode"].value,
        platform=fields["platform"],
        platforms=fields["platforms"],
        input_urls=fields["input_urls"],
        keywords=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        run_checkpoint=fields["run_checkpoint"],
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await LinkImportService.run_collection_task(db, task)
        await db.refresh(task)
        assert upsert_calls == []
        assert task.inserted_count == 0
        assert classify_task_effectiveness(task, has_valuable_insert=False) == "low_value_result"
        await db.rollback()


@pytest.mark.anyio
async def test_real_ltk_url_low_value_seed_writes_candidate_without_import_error(monkeypatch):
    valid = validate_link_import_url_lines([LTK_URL_WITH_QUERY])
    expected_input_url = valid[0]["url"]

    async def _fake_enrich(seed):
        from app.services.link_seed_enrichment import LinkSeedEnrichmentResult

        return LinkSeedEnrichmentResult(
            item=seed,
            seed_platform="ltk",
            seed_profile_url=seed.profile_url,
            seed_username=seed.username,
            enrichment_attempted=True,
            is_valuable=False,
        )

    monkeypatch.setattr("app.services.link_import.enrich_link_seed_item", _fake_enrich)
    upsert_calls: list[str] = []

    async def _upsert(db, item, run_at, *, product_id, task=None):
        del db, item, run_at, product_id, task
        upsert_calls.append("upsert")
        return "new", SimpleNamespace(id=1, global_influencer_id=1)

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    fields = build_link_import_task_fields(valid)
    task = CollectionTask(
        name="ltk-real-url-import",
        collection_mode=fields["collection_mode"].value,
        platform=fields["platform"],
        platforms=fields["platforms"],
        input_urls=fields["input_urls"],
        keywords=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        run_checkpoint=fields["run_checkpoint"],
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await LinkImportService.run_collection_task(db, task)
        await db.refresh(task)

        assert upsert_calls == []
        assert task.inserted_count == 0
        assert task.result_count == 0
        assert task.profile_failed_count == 0
        assert classify_task_effectiveness(task, has_valuable_insert=False) == "low_value_result"
        assert not task.error_message or "入库失败" not in task.error_message

        page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
        assert page.total == 1
        cand = page.items[0]
        assert cand.status == CandidateStatus.NOT_INSERTED.value
        assert cand.failure_reason == "low_value_seed"
        assert cand.source_input_url == expected_input_url
        assert "utm_source=ig" in (cand.source_input_url or "")
        assert cand.username == "ltk_creator"
        assert cand.platform == "ltk"
        assert cand.profile_url == "https://www.shopltk.com/explore/ltk_creator"
        assert link_seed_low_value_detail("ltk") in (cand.failure_detail or "")
        await db.rollback()


def _mock_ltk_ig_scrape(monkeypatch, ig: CollectedInfluencer) -> list[list[str]]:
    return _mock_instagram_scrape(monkeypatch, ig)


@pytest.mark.anyio
async def test_ltk_enrichment_calls_instagram_detail_hydrate(monkeypatch):
    shell = _ltk_shell()
    ig = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        followers_count=50000,
        engagement_rate=2.5,
        bio="Daily outfits",
    )
    scrape_calls = _mock_ltk_ig_scrape(monkeypatch, ig)
    result = await enrich_link_seed_item(shell)
    assert scrape_calls
    assert scrape_calls[0] == ["https://www.instagram.com/ltk_creator/"]
    assert result.instagram_detail_fetched is True
    assert result.item.platform == "instagram"
    assert result.item.profile_url == ig.profile_url
    assert result.item.followers_count == 50000
    meta = enrichment_meta_dict(result)
    assert meta["enriched_platform"] == "instagram"
    assert meta["instagram_detail_fetched"] is True


@pytest.mark.anyio
async def test_ltk_instagram_with_email_inserts(monkeypatch):
    ig = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        followers_count=50000,
        engagement_rate=2.5,
        bio="Collab brand@example.com",
        final_email="brand@example.com",
        email="brand@example.com",
    )
    _mock_ltk_ig_scrape(monkeypatch, ig)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    fields = build_link_import_task_fields(validate_link_import_url_lines([LTK_URL]))
    task = CollectionTask(
        name="ltk-import-email",
        collection_mode=fields["collection_mode"].value,
        platform=fields["platform"],
        platforms=fields["platforms"],
        input_urls=fields["input_urls"],
        keywords=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        run_checkpoint=fields["run_checkpoint"],
        require_email=True,
        insert_qualified_only=True,
        min_followers_count=10_000,
        min_engagement_rate=2.0,
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await LinkImportService.run_collection_task(db, task)
        await db.refresh(task)
        assert task.inserted_count == 1

        page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
        cand = page.items[0]
        assert cand.status == CandidateStatus.INSERTED.value
        assert cand.platform == "instagram"
        assert cand.profile_url == ig.profile_url
        assert cand.source_input_url == LTK_URL
        assert cand.has_email is True
        assert cand.source_type == "link_import"
        meta = cand.source_meta or {}
        assert meta.get("link_seed_platform") == "ltk"
        assert meta.get("enriched_platform") == "instagram"
        assert meta.get("instagram_detail_fetched") is True
        enrichment = meta.get("link_seed_enrichment") or {}
        assert enrichment.get("instagram_detail_fetched") is True
        await db.rollback()


@pytest.mark.anyio
async def test_ltk_instagram_no_email_keeps_full_detail_and_reason(monkeypatch):
    ig = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        followers_count=50000,
        engagement_rate=2.5,
        bio="Daily outfits and style tips",
        display_name="LTK Creator IG",
        avatar_url="https://cdn.example.com/avatar.jpg",
        linktree_url="https://linktr.ee/ltk_creator",
        contact_fetch_status="success",
    )
    _mock_ltk_ig_scrape(monkeypatch, ig)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    fields = build_link_import_task_fields(validate_link_import_url_lines([LTK_URL]))
    task = CollectionTask(
        name="ltk-import-no-email",
        collection_mode=fields["collection_mode"].value,
        platform=fields["platform"],
        platforms=fields["platforms"],
        input_urls=fields["input_urls"],
        keywords=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
        status=CollectionTaskStatus.DRAFT.value,
        run_checkpoint=fields["run_checkpoint"],
        require_email=True,
        insert_qualified_only=True,
        min_followers_count=10_000,
        min_engagement_rate=2.0,
    )

    async with async_session_factory() as db:
        db.add(task)
        await db.flush()
        await LinkImportService.run_collection_task(db, task)
        await db.refresh(task)
        assert task.inserted_count == 0

        page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
        cand = page.items[0]
        assert cand.status == CandidateStatus.NOT_INSERTED.value
        assert cand.failure_reason == "missing_email"
        assert cand.platform == "instagram"
        assert cand.profile_url == ig.profile_url
        assert cand.source_input_url == LTK_URL
        assert cand.followers_count == 50000
        assert cand.engagement_rate == 2.5
        assert "Instagram 详情已采集，未发现公开邮箱" in (cand.insert_blocked_reason or "")
        meta = cand.source_meta or {}
        assert meta.get("link_seed_platform") == "ltk"
        assert meta.get("enriched_platform") == "instagram"
        assert meta.get("instagram_detail_fetched") is True
        enrichment = meta.get("link_seed_enrichment") or {}
        assert enrichment.get("instagram_detail_fetched") is True
        snapshot = meta.get("profile_snapshot") or {}
        assert snapshot.get("bio") == ig.bio
        assert snapshot.get("display_name") == ig.display_name
        assert snapshot.get("avatar_url") == ig.avatar_url
        assert snapshot.get("linktree_url") == ig.linktree_url
        assert snapshot.get("followers_count") == 50000
        assert snapshot.get("engagement_rate") == 2.5
        await db.rollback()


def test_missing_email_detail_for_link_seed_enriched_instagram():
    item = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        followers_count=50000,
        engagement_rate=2.5,
        tags=["link_seed:ltk", "instagram_detail_fetched"],
        contact_fetch_status="success",
    )
    task = CollectionTask(
        name="assess",
        platform="instagram",
        platforms=["instagram"],
        collection_mode="link_import",
        input_urls=[LTK_URL],
        keywords=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
        require_email=True,
        insert_qualified_only=True,
        min_followers_count=10_000,
        min_engagement_rate=2.0,
    )
    assessment = evaluate_high_value_assessment(item, task)
    assert assessment.insert_blocked_reason == "Instagram 详情已采集，未发现公开邮箱"
