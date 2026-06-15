"""Pinterest / LTK / ShopMy 链接导入识别、候选池与高价值筛选。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.schemas.collection_task import build_link_import_task_fields
from app.services.link_import import LinkImportService
from app.services.platform_providers.url_only import PARSERS
from app.services.platform_utils import profile_to_collected
from app.services.task_candidate import TaskCandidateService
from app.services.url_parser import detect_platform, parse_raw_urls, validate_link_import_url_lines


URL_CASES = [
    ("pinterest_pin", "https://www.pinterest.com/pin/123/", "pinterest", "pin_123"),
    ("pinterest_profile", "https://www.pinterest.com/example_user/", "pinterest", "example_user"),
    ("ltk", "https://www.shopltk.com/explore/example_user", "ltk", "example_user"),
    ("ltk_no_www", "https://shopltk.com/explore/example_user", "ltk", "example_user"),
    ("shopmy", "https://shopmy.us/example_user", "shopmy", "example_user"),
]


@pytest.mark.parametrize("label,url,platform,username", URL_CASES)
def test_url_parser_and_build_task_fields(label, url, platform, username):
    del label
    assert detect_platform(url) == platform
    valid, invalid = parse_raw_urls(url)
    assert invalid == []
    assert len(valid) == 1
    assert valid[0]["platform"] == platform

    fields = build_link_import_task_fields(validate_link_import_url_lines([url]))
    assert fields["collection_mode"] == CollectionMode.LINK_IMPORT
    assert platform in fields["platforms"]
    assert fields["run_checkpoint"]["link_import_platforms"] == fields["platforms"]
    assert url.rstrip("/") in fields["input_urls"][0] or fields["input_urls"][0].rstrip("/") in url.rstrip("/")

    profile = PARSERS[platform](url)
    assert profile is not None
    item = profile_to_collected(profile)
    assert item.platform == platform
    assert item.username == username
    assert item.profile_url
    assert item.contact_fetch_status == "pending"


def _task_from_url(url: str, **kwargs) -> CollectionTask:
    valid = validate_link_import_url_lines([url])
    fields = build_link_import_task_fields(valid)
    defaults = {
        "name": "url-only-import",
        "collection_mode": fields["collection_mode"].value
        if hasattr(fields["collection_mode"], "value")
        else fields["collection_mode"],
        "platform": fields["platform"],
        "platforms": fields["platforms"],
        "input_urls": fields["input_urls"],
        "keywords": [],
        "product_id": 1,
        "user_id": 1,
        "workspace_id": 1,
        "status": CollectionTaskStatus.DRAFT.value,
        "min_engagement_rate": None,
        "filter_include_keywords": [],
        "filter_exclude_keywords": [],
        "require_email": False,
        "require_contact": False,
        "strict_quality_filter": False,
        "insert_qualified_only": False,
        "run_checkpoint": fields["run_checkpoint"],
    }
    defaults.update(kwargs)
    return CollectionTask(**defaults)


@pytest.mark.parametrize("label,url,platform,username", URL_CASES)
def test_link_import_run_writes_pending_candidate(label, url, platform, username, monkeypatch):
    del label, username

    async def _noop_enrich(seed):
        from app.services.link_seed_enrichment import LinkSeedEnrichmentResult

        return LinkSeedEnrichmentResult(
            item=seed,
            seed_platform=platform,
            seed_profile_url=seed.profile_url,
            seed_username=seed.username,
            enrichment_attempted=True,
            is_valuable=False,
        )

    monkeypatch.setattr("app.services.link_import.enrich_link_seed_item", _noop_enrich)
    upsert_calls: list[str] = []

    async def _upsert(db, item, run_at, *, product_id, task=None):
        del db, item, run_at, product_id, task
        upsert_calls.append("upsert")
        return "new", SimpleNamespace(id=900)

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    task = _task_from_url(url)

    async def _run() -> None:
        async with async_session_factory() as db:
            db.add(task)
            await db.flush()
            result = await LinkImportService.run_collection_task(db, task)
            await db.refresh(task)

            assert upsert_calls == []
            assert result["inserted_count"] == 0
            assert task.inserted_count == 0
            assert task.result_count == 0
            assert task.status == CollectionTaskStatus.COMPLETED_NO_RESULTS.value

            page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
            assert page.total == 1
            candidate = page.items[0]
            assert candidate.platform == platform
            assert candidate.status == CandidateStatus.NOT_INSERTED.value
            assert candidate.failure_reason == "low_value_seed"
            assert candidate.username
            assert candidate.profile_url
            assert candidate.source_type == "input_profile"
            assert candidate.source_discovery_type == "url_profile"
            assert candidate.is_high_value is False
            assert candidate.source_input_url

            await db.rollback()

    asyncio.run(_run())


def test_multi_platform_url_only_link_import_stats_and_candidate_filter(monkeypatch):
    upsert_calls: list[str] = []

    async def _upsert(db, item, run_at, *, product_id, task=None):
        del db, item, run_at, product_id, task
        upsert_calls.append("upsert")
        return "new", SimpleNamespace(id=901)

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    urls = [
        "https://www.pinterest.com/example_user/",
        "https://shopltk.com/explore/example_user",
        "https://shopmy.us/example_user",
    ]
    valid = validate_link_import_url_lines(urls)
    fields = build_link_import_task_fields(valid)
    task = CollectionTask(
        name="multi-url-only",
        collection_mode=CollectionMode.LINK_IMPORT.value,
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

    async def _run() -> None:
        async with async_session_factory() as db:
            db.add(task)
            await db.flush()
            result = await LinkImportService.run_collection_task(db, task)
            await db.refresh(task)

            assert upsert_calls == []
            assert result["inserted_count"] == 0
            assert task.discovered_count == 3
            assert task.platform == "multi"
            assert set(task.platforms or []) == {"pinterest", "ltk", "shopmy"}
            assert task.run_checkpoint.get("link_import_platforms") == ["pinterest", "ltk", "shopmy"]

            all_candidates = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
            assert all_candidates.total == 3

            pinterest_only = await TaskCandidateService.list_for_task(
                db,
                task.id,
                page=1,
                page_size=20,
                platform="pinterest",
            )
            assert pinterest_only.total == 1
            assert pinterest_only.items[0].platform == "pinterest"

            export_rows = await TaskCandidateService.list_for_export(
                db,
                task.id,
                product_id=1,
                platform="shopmy",
            )
            assert len(export_rows) == 1
            assert export_rows[0][0].platform == "shopmy"

            await db.rollback()

    asyncio.run(_run())


def test_url_only_link_import_insert_qualified_only_not_inserted(monkeypatch):
    upsert_calls: list[str] = []

    async def _upsert(db, item, run_at, *, product_id, task=None):
        del db, item, run_at, product_id, task
        upsert_calls.append("upsert")
        return "new", SimpleNamespace(id=902)

    monkeypatch.setattr(LinkImportService, "_upsert_product_influencer", _upsert)
    monkeypatch.setattr(LinkImportService, "_analyze_product_influencer", AsyncMock())

    task = _task_from_url(
        "https://shopmy.us/example_user",
        min_followers_count=1_000,
        insert_qualified_only=True,
    )

    async def _run() -> None:
        async with async_session_factory() as db:
            db.add(task)
            await db.flush()
            await LinkImportService.run_collection_task(db, task)
            await db.refresh(task)

            assert upsert_calls == []
            page = await TaskCandidateService.list_for_task(db, task.id, page=1, page_size=20)
            assert page.total == 1
            candidate = page.items[0]
            assert candidate.status == CandidateStatus.NOT_INSERTED.value
            assert candidate.platform == "shopmy"
            assert candidate.is_high_value is False
            assert candidate.insert_blocked_reason

            await db.rollback()

    asyncio.run(_run())
