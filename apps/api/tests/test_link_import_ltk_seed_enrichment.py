"""LTK / ShopMy 链接 seed 补全与低价值判定测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateStatus, CollectionTaskStatus
from app.models.product_influencer_source import ProductInfluencerSource
from app.schemas.collection_task import build_link_import_task_fields
from app.services.influencer_profile_value import is_influencer_profile_valuable
from app.services.link_import import LinkImportService
from app.services.link_seed_enrichment import (
    build_seed_search_keywords,
    enrich_link_seed_item,
    link_seed_low_value_detail,
    merge_seed_into_primary,
)
from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import profile_to_collected
from app.services.task_candidate import TaskCandidateService
from app.services.task_effectiveness import classify_task_effectiveness
from app.services.url_parser import validate_link_import_url_lines


LTK_URL = "https://www.shopltk.com/explore/ltk_creator"

REAL_LTK_URL = (
    "https://www.shopltk.com/explore/apieceofmyhaven?utm_source=ig&utm_medium=social"
    "&utm_content=link_in_bio&fbclid=PAZXh0bgNhZW0CMTEAc3J0YwZhcHBfaWQPOTM2NjE5NzQzMzkyNDU5"
    "AAGn4qyFyo2YKRYp1ZZyXhp_1_Ii2s5r-yVr2Ggq_AFXj-23iAot5Y9HoH-jgL4_aem_FXzYV9OACROIIXBPS32ybw"
)


def _ltk_shell() -> CollectedInfluencer:
    profile = PlatformCandidateProfile(
        platform="ltk",
        username="ltk_creator",
        profile_url="https://www.shopltk.com/explore/ltk_creator",
        display_name="LTK Creator",
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
async def test_ltk_empty_enrichment_not_valuable():
    shell = _ltk_shell()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.link_seed_enrichment._try_instagram_profile",
            AsyncMock(return_value=None),
        )
        mp.setattr(
            "app.services.link_seed_enrichment._try_tiktok_profile",
            AsyncMock(return_value=None),
        )
        mp.setattr(
            "app.services.link_seed_enrichment._try_youtube_profile",
            AsyncMock(return_value=None),
        )
        mp.setattr(
            "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
            AsyncMock(),
        )
        result = await enrich_link_seed_item(shell)
    assert result.is_valuable is False
    assert not is_influencer_profile_valuable(result.item)


@pytest.mark.anyio
async def test_ltk_enrichment_instagram_success_is_valuable():
    shell = _ltk_shell()
    ig = CollectedInfluencer(
        platform="instagram",
        username="ltk_creator",
        profile_url="https://www.instagram.com/ltk_creator/",
        followers_count=50000,
        bio="Daily outfits",
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.link_seed_enrichment._try_instagram_profile",
            AsyncMock(return_value=ig),
        )
        mp.setattr(
            "app.services.link_seed_enrichment._try_tiktok_profile",
            AsyncMock(return_value=None),
        )
        mp.setattr(
            "app.services.link_seed_enrichment._try_youtube_profile",
            AsyncMock(return_value=None),
        )
        mp.setattr(
            "app.services.link_seed_enrichment.ContactDiscoveryService.enrich_collected",
            AsyncMock(),
        )
        result = await enrich_link_seed_item(shell)
    assert result.is_valuable is True
    assert result.item.platform == "instagram"


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

        sources = (
            await db.execute(
                select(ProductInfluencerSource).where(ProductInfluencerSource.task_id == task.id)
            )
        ).scalars().all()
        assert len(sources) == 1
        assert sources[0].source_input_url == LTK_URL
        assert "shopltk.com" in (sources[0].source_input_url or "")

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
    valid = validate_link_import_url_lines([REAL_LTK_URL])
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
        assert cand.username == "apieceofmyhaven"
        assert cand.platform == "ltk"
        assert cand.profile_url == "https://www.shopltk.com/explore/apieceofmyhaven"
        assert link_seed_low_value_detail("ltk") in (cand.failure_detail or "")
        await db.rollback()
