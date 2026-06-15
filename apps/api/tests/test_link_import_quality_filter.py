"""链接导入高价值筛选与候选池回归测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.services.apify_instagram import ProfileScrapeResult
from app.services.high_value_filter import (
    evaluate_high_value_assessment,
    has_collection_contact_channel,
    has_collection_email,
    should_skip_insert,
)
from app.services.link_import import LinkImportService
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services.task_candidate import TaskCandidateService
from app.services.task_influencer import TaskInfluencerService


def _instagram_item(**kwargs) -> CollectedInfluencer:
    defaults = {
        "platform": "instagram",
        "username": "low_follower",
        "profile_url": "https://www.instagram.com/low_follower/",
        "followers_count": 500,
        "engagement_rate": 3.0,
        "bio": "Creator",
        "contact_fetch_status": "success",
    }
    defaults.update(kwargs)
    return CollectedInfluencer(**defaults)


def _link_import_task(**kwargs) -> CollectionTask:
    defaults = {
        "name": "link-import-quality",
        "platform": "instagram",
        "platforms": ["instagram"],
        "collection_mode": CollectionMode.LINK_IMPORT.value,
        "input_urls": ["https://www.instagram.com/low_follower/"],
        "keywords": [],
        "product_id": 1,
        "user_id": 1,
        "workspace_id": 1,
        "status": CollectionTaskStatus.DRAFT.value,
        "min_engagement_rate": 0,
        "filter_include_keywords": [],
        "filter_exclude_keywords": [],
        "require_email": False,
        "require_contact": False,
        "strict_quality_filter": False,
        "insert_qualified_only": False,
    }
    defaults.update(kwargs)
    return CollectionTask(**defaults)


@pytest.fixture
def mock_instagram_scrape(monkeypatch):
    async def _scrape(urls):
        del urls
        return ProfileScrapeResult(
            profiles=[_instagram_item()],
            errors=[],
        )

    monkeypatch.setattr(
        "app.services.link_import.scrape_instagram_profiles",
        AsyncMock(side_effect=_scrape),
    )
    monkeypatch.setattr(
        "app.services.link_import.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.link_import.LinkImportService._analyze_product_influencer",
        AsyncMock(),
    )


def test_link_import_insert_qualified_only_keeps_low_followers_in_candidate_pool(
    monkeypatch,
    mock_instagram_scrape,
):
    upsert_calls: list[str] = []

    async def _upsert(db, item, run_at, *, product_id, task=None):
        del db, item, run_at, product_id, task
        upsert_calls.append("upsert")
        return "new", SimpleNamespace(id=101)

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)

    task = _link_import_task(
        min_followers_count=10_000,
        insert_qualified_only=True,
    )

    async def _run() -> None:
        async with async_session_factory() as db:
            db.add(task)
            await db.flush()
            result = await LinkImportService.run_collection_task(db, task)
            await db.refresh(task)

            assert upsert_calls == []
            assert result["inserted_count"] == 0
            assert result["skipped_count"] == 1
            assert task.inserted_count == 0

            page = await TaskCandidateService.list_for_task(
                db,
                task.id,
                page=1,
                page_size=20,
            )
            assert page.total == 1
            candidate = page.items[0]
            assert candidate.status == CandidateStatus.NOT_INSERTED.value
            assert candidate.followers_count == 500
            assert candidate.insert_blocked_reason
            assert candidate.is_high_value is False

            await db.rollback()

    asyncio.run(_run())


def test_link_import_strict_quality_filter_excludes_candidate_and_updates_stats(
    monkeypatch,
    mock_instagram_scrape,
):
    upsert_calls: list[str] = []

    async def _upsert(db, item, run_at, *, product_id, task=None):
        del db, item, run_at, product_id, task
        upsert_calls.append("upsert")
        return "new", SimpleNamespace(id=102)

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)

    task = _link_import_task(
        min_followers_count=10_000,
        strict_quality_filter=True,
    )

    async def _run() -> None:
        async with async_session_factory() as db:
            db.add(task)
            await db.flush()
            result = await LinkImportService.run_collection_task(db, task)
            await db.refresh(task)

            assert upsert_calls == []
            assert result["filtered_out_count"] == 1
            assert result["inserted_count"] == 0
            assert task.filtered_out_count == 1
            assert task.filtered_below_min_followers_count == 1

            page = await TaskCandidateService.list_for_task(
                db,
                task.id,
                page=1,
                page_size=20,
            )
            assert page.total == 1
            candidate = page.items[0]
            assert candidate.status == CandidateStatus.FILTERED_OUT.value
            assert candidate.failure_reason == "below_min_followers"

            await db.rollback()

    asyncio.run(_run())


def test_candidate_list_and_export_respect_follower_and_engagement_filters():
    run_at = datetime.now(UTC)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = CollectionTask(
                name="candidate-filter-task",
                platform="instagram",
                platforms=["instagram"],
                collection_mode=CollectionMode.LINK_IMPORT.value,
                input_urls=[],
                keywords=[],
                product_id=1,
                user_id=1,
                workspace_id=1,
            )
            db.add(task)
            await db.flush()

            await TaskCandidateService.bulk_insert(
                db,
                task.id,
                [
                    {
                        "username": "small",
                        "profile_url": "https://www.instagram.com/small/",
                        "platform": "instagram",
                        "followers_count": 1_000,
                        "engagement_rate": 0.5,
                        "status": CandidateStatus.INSERTED.value,
                    },
                    {
                        "username": "mid",
                        "profile_url": "https://www.instagram.com/mid/",
                        "platform": "instagram",
                        "followers_count": 20_000,
                        "engagement_rate": 2.5,
                        "status": CandidateStatus.INSERTED.value,
                    },
                    {
                        "username": "large",
                        "profile_url": "https://www.instagram.com/large/",
                        "platform": "instagram",
                        "followers_count": 80_000,
                        "engagement_rate": 5.0,
                        "status": CandidateStatus.INSERTED.value,
                    },
                ],
                run_at=run_at,
                product_id=1,
                user_id=1,
            )
            await db.flush()

            filtered = await TaskCandidateService.list_for_task(
                db,
                task.id,
                page=1,
                page_size=20,
                min_followers_count=10_000,
                max_followers_count=50_000,
                min_engagement_rate=2.0,
                max_engagement_rate=3.0,
            )
            assert filtered.total == 1
            assert filtered.items[0].username == "mid"

            export_rows = await TaskCandidateService.list_for_export(
                db,
                task.id,
                product_id=1,
                min_followers_count=10_000,
                max_followers_count=50_000,
                min_engagement_rate=2.0,
                max_engagement_rate=3.0,
            )
            assert len(export_rows) == 1
            assert export_rows[0][0].username == "mid"

            await db.rollback()

    asyncio.run(_run())


def test_multi_platform_link_import_refresh_task_stats_match_inserted_candidates():
    run_at = datetime.now(UTC)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = CollectionTask(
                name="multi-link-import-stats",
                platform="multi",
                platforms=["instagram", "pinterest"],
                collection_mode=CollectionMode.LINK_IMPORT.value,
                input_urls=[
                    "https://www.instagram.com/ig_creator/",
                    "https://www.pinterest.com/pinterest_creator/",
                ],
                keywords=[],
                product_id=1,
                user_id=1,
                workspace_id=1,
            )
            db.add(task)
            await db.flush()

            ig_item = CollectedInfluencer(
                platform="instagram",
                username="ig_creator",
                profile_url="https://www.instagram.com/ig_creator/",
                followers_count=50_000,
                engagement_rate=2.5,
                final_email="ig@brand.com",
            )
            pin_item = CollectedInfluencer(
                platform="pinterest",
                username="pinterest_creator",
                profile_url="https://www.pinterest.com/pinterest_creator/",
                followers_count=40_000,
                engagement_rate=3.0,
                final_email="pin@brand.com",
            )

            records: list[tuple[CollectedInfluencer, object]] = []
            for item in (ig_item, pin_item):
                global_profile = create_global_profile_from_collected(item, run_at=run_at)
                db.add(global_profile)
                await db.flush()
                product_record = create_product_influencer_from_collected(
                    product_id=1,
                    global_profile=global_profile,
                    data=item,
                    task=task,
                    run_at=run_at,
                )
                db.add(product_record)
                await db.flush()
                records.append((item, product_record))

            candidate_rows = []
            for item, product_record in records:
                candidate_rows.append(
                    TaskCandidateService.row_from_inserted(
                        meta=None,
                        username=item.username,
                        profile_url=item.profile_url,
                        platform=item.platform,
                        collection_mode=task.collection_mode,
                        product_influencer_id=product_record.id,
                        product_id=1,
                        user_id=1,
                        followers_count=item.followers_count,
                        engagement_rate=item.engagement_rate,
                        profile_fetched_at=run_at,
                        source_type="input_profile",
                        source_discovery_type="url_profile",
                        source_post_url=item.profile_url,
                    )
                )

            await TaskCandidateService.bulk_insert(
                db,
                task.id,
                candidate_rows,
                run_at=run_at,
                product_id=1,
                user_id=1,
            )

            task.inserted_count = len(candidate_rows)
            await TaskInfluencerService.refresh_task_stats(db, task)
            await db.flush()

            assert task.inserted_count == 2
            assert task.result_count == 2
            assert task.email_count == 2
            assert task.missing_contact_count == 0

            inserted_candidates = await TaskCandidateService.list_for_task(
                db,
                task.id,
                page=1,
                page_size=20,
                status=CandidateStatus.INSERTED.value,
            )
            assert inserted_candidates.total == 2

            influencers = await TaskInfluencerService.get_influencers_for_task(db, task)
            assert len(influencers) == 2
            assert {item.platform for item in influencers} == {"instagram", "pinterest"}

            await db.rollback()

    asyncio.run(_run())


def test_link_import_inserts_qualified_candidate_with_bio_only_email(monkeypatch):
    import uuid

    suffix = uuid.uuid4().hex[:8]
    username = f"bio_email_{suffix}"
    profile_url = f"https://www.instagram.com/{username}/"
    input_url = profile_url
    upsert_calls: list[str] = []

    async def _scrape(urls):
        del urls
        return ProfileScrapeResult(
            profiles=[
                _instagram_item(
                    username=username,
                    profile_url=profile_url,
                    followers_count=50_000,
                    engagement_rate=3.0,
                    bio="合作联系 hello@brand.com",
                    email=None,
                    final_email=None,
                    public_email=None,
                    business_email=None,
                    contact_fetch_status="success",
                )
            ],
            errors=[],
        )

    monkeypatch.setattr(
        "app.services.link_import.scrape_instagram_profiles",
        AsyncMock(side_effect=_scrape),
    )
    monkeypatch.setattr(
        "app.services.link_import.ContactDiscoveryService.enrich_collected",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.link_import.LinkImportService._analyze_product_influencer",
        AsyncMock(),
    )

    async def _upsert(db, item, run_at, *, product_id, task=None):
        global_profile = create_global_profile_from_collected(item, run_at=run_at)
        db.add(global_profile)
        await db.flush()
        product_record = create_product_influencer_from_collected(
            product_id=product_id,
            global_profile=global_profile,
            data=item,
            task=task,
            run_at=run_at,
        )
        db.add(product_record)
        await db.flush()
        upsert_calls.append(item.username)
        return "new", product_record

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)

    task = _link_import_task(
        input_urls=[input_url],
        min_followers_count=10_000,
        min_engagement_rate=2.0,
        require_email=True,
        require_contact=True,
        insert_qualified_only=True,
        strict_quality_filter=False,
    )

    item = _instagram_item(
        username=username,
        profile_url=profile_url,
        followers_count=50_000,
        engagement_rate=3.0,
        bio="合作联系 hello@brand.com",
        email=None,
        final_email=None,
        public_email=None,
        business_email=None,
        contact_fetch_status="success",
    )
    assessment = evaluate_high_value_assessment(item, task)
    assert has_collection_email(item)
    assert has_collection_contact_channel(item)
    assert assessment.has_email
    assert assessment.has_contact
    assert assessment.is_high_value
    assert "missing_email" not in assessment.mismatch_codes
    assert "missing_contact" not in assessment.mismatch_codes
    assert not should_skip_insert(task, assessment)

    async def _run() -> None:
        async with async_session_factory() as db:
            db.add(task)
            await db.flush()
            result = await LinkImportService.run_collection_task(db, task)
            await db.refresh(task)

            assert upsert_calls == [username]
            assert result["inserted_count"] == 1
            assert result["skipped_count"] == 0
            assert task.inserted_count == 1
            assert task.result_count == 1

            page = await TaskCandidateService.list_for_task(
                db,
                task.id,
                page=1,
                page_size=20,
            )
            assert page.total == 1
            candidate = page.items[0]
            assert candidate.status == CandidateStatus.INSERTED.value
            assert candidate.has_email is True
            assert candidate.has_contact is True
            assert candidate.is_high_value is True
            assert candidate.insert_blocked_reason in (None, "")
            assert candidate.failure_reason in (None, "")

            await db.rollback()

    asyncio.run(_run())
