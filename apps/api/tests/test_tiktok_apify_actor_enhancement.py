from __future__ import annotations

import asyncio

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateFailureReason, CandidateStatus, CollectionMode
from app.services.apify_client import ApifyError
from app.services.platform_providers.tiktok_apify import TikTokApifyProvider
from app.services.task_candidate_recrawl import TaskCandidateRecrawlService


def _task(**overrides) -> CollectionTask:
    data = {
        "name": "tiktok-actors",
        "platform": "tiktok",
        "platforms": ["tiktok"],
        "collection_mode": CollectionMode.KEYWORD.value,
        "keywords": ["#amazonfinds"],
        "input_urls": [],
        "product_id": 1,
        "user_id": 1,
        "workspace_id": 1,
        "min_followers_count": 10_000,
        "min_engagement_rate": 1.0,
    }
    data.update(overrides)
    return CollectionTask(**data)


def _candidate(task: CollectionTask, **overrides) -> CollectionTaskCandidate:
    data = {
        "task_id": task.id,
        "product_id": task.product_id,
        "user_id": task.user_id,
        "username": "creator",
        "profile_url": "https://www.tiktok.com/@creator",
        "platform": "tiktok",
        "source_type": "keyword_video_author",
        "source_keyword": "amazonfinds",
        "source_post_url": "https://www.tiktok.com/@creator/video/123",
        "source_caption": "great amazon find",
        "source_discovery_type": "video_author",
        "source_meta": {"original": "kept"},
        "status": CandidateStatus.PROFILE_FAILED.value,
        "failure_reason": CandidateFailureReason.MISSING_PROFILE_DETAIL.value,
        "failure_detail": "missing_profile_detail",
    }
    data.update(overrides)
    return CollectionTaskCandidate(**data)


def test_tiktok_hashtag_actor_maps_video_author_and_source_fields(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append((actor_id, run_input))
        return [
            {
                "id": "video-1",
                "text": "Amazon finds haul hello@creator.com",
                "webVideoUrl": "https://www.tiktok.com/@creator/video/123",
                "authorMeta": {
                    "name": "creator",
                    "nickName": "Creator Home",
                    "signature": "business hello@creator.com",
                    "fans": 45000,
                    "heart": 120000,
                    "following": 50,
                },
                "playCount": 10000,
                "diggCount": 700,
                "commentCount": 30,
            }
        ]

    monkeypatch.setattr("app.services.platform_providers.tiktok_apify.run_actor_sync", fake_run_actor)

    result = asyncio.run(TikTokApifyProvider.discover(_task()))

    assert calls[0][0] == "clockworks/tiktok-hashtag-scraper"
    assert result.profiles[0].username == "creator"
    assert result.profiles[0].source_hashtag == "amazonfinds"
    assert result.profiles[0].source_post_url == "https://www.tiktok.com/@creator/video/123"
    assert result.profiles[0].source_meta["source_caption"] == "Amazon finds haul hello@creator.com"
    assert result.profiles[0].source_meta["following_count"] == 50
    assert result.profiles[0].email == "hello@creator.com"


def test_tiktok_apify_keyword_search_omits_proxy_country_to_avoid_actor_stall(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append((actor_id, run_input))
        return [
            {
                "text": "makeup bag travel pouch",
                "webVideoUrl": "https://www.tiktok.com/@creator/video/123",
                "authorMeta": {"name": "creator", "fans": 45000},
                "playCount": 10000,
                "diggCount": 700,
                "commentCount": 30,
            }
        ]

    monkeypatch.setattr("app.services.platform_providers.tiktok_apify.run_actor_sync", fake_run_actor)

    result = asyncio.run(TikTokApifyProvider.discover(_task(keywords=["makeup bag"], country="DE")))

    assert result.profiles
    assert "proxyCountryCode" not in calls[0][1]


def test_tiktok_video_actor_maps_input_url_author(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append((actor_id, run_input))
        return [
            {
                "url": "https://www.tiktok.com/@videoauthor/video/999",
                "desc": "external product proof",
                "author": {"uniqueId": "videoauthor", "nickname": "Video Author", "signature": "DM for collab"},
                "authorStats": {"followerCount": 32000},
                "stats": {"playCount": 8000, "diggCount": 500, "commentCount": 20},
            }
        ]

    monkeypatch.setattr("app.services.platform_providers.tiktok_apify.run_actor_sync", fake_run_actor)

    task = _task(keywords=[], input_urls=["https://www.tiktok.com/@videoauthor/video/999"])
    result = asyncio.run(TikTokApifyProvider.discover(task))

    assert calls[0][0] == "clockworks/tiktok-video-scraper"
    assert result.profiles[0].username == "videoauthor"
    assert result.profiles[0].source_post_url == "https://www.tiktok.com/@videoauthor/video/999"
    assert result.profiles[0].source_input_url == "https://www.tiktok.com/@videoauthor/video/999"
    assert result.profiles[0].source_discovery_type == "video_author"


def test_tiktok_keyword_timeout_falls_back_to_hashtag_actor_and_keeps_source_fields(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append((actor_id, run_input))
        if actor_id == "clockworks/tiktok-scraper":
            raise ApifyError("timeout after 120s")
        if actor_id == "clockworks/tiktok-hashtag-scraper":
            return [
                {
                    "text": "makeup bag travel pouch",
                    "webVideoUrl": "https://www.tiktok.com/@fallbackcreator/video/321",
                    "authorMeta": {
                        "name": "fallbackcreator",
                        "nickName": "Fallback Creator",
                        "signature": "beauty tools",
                        "fans": 38000,
                    },
                    "playCount": 9000,
                    "diggCount": 500,
                    "commentCount": 25,
                }
            ]
        raise AssertionError(f"unexpected actor {actor_id}")

    monkeypatch.setattr("app.services.platform_providers.tiktok_apify.run_actor_sync", fake_run_actor)

    result = asyncio.run(TikTokApifyProvider.discover(_task(keywords=["makeup bag"])))

    assert [actor for actor, _ in calls] == [
        "clockworks/tiktok-scraper",
        "clockworks/tiktok-hashtag-scraper",
    ]
    assert result.profiles[0].username == "fallbackcreator"
    assert result.profiles[0].source_hashtag == "makeup bag"
    assert result.profiles[0].source_post_url == "https://www.tiktok.com/@fallbackcreator/video/321"
    assert result.profiles[0].source_caption == "makeup bag travel pouch"
    diagnostics = result.profiles[0].source_meta["tiktok_actor_fallback"]
    assert diagnostics["primary_actor"] == "clockworks/tiktok-scraper"
    assert diagnostics["fallback_actor"] == "clockworks/tiktok-hashtag-scraper"
    assert "timeout" in diagnostics["error"]


def test_tiktok_profile_actor_recrawl_inserts_candidate(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append((actor_id, run_input))
        return [
            {
                "username": "creator",
                "nickname": "Creator Home",
                "signature": "business hello@creator.com",
                "followers": 55000,
                "avgViews": 12000,
                "avgLikes": 900,
                "avgComments": 50,
                "profileUrl": "https://www.tiktok.com/@creator",
                "runId": "profile-run-1",
            }
        ]

    monkeypatch.setattr("app.services.platform_providers.tiktok_apify.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            db.add(task)
            await db.flush()
            candidate = _candidate(task)
            db.add(candidate)
            await db.flush()

            result = await TaskCandidateRecrawlService.recrawl_candidate(db, candidate.id)

            assert calls[0][0] == "clockworks/tiktok-profile-scraper"
            assert result.status == CandidateStatus.INSERTED.value
            assert candidate.status == CandidateStatus.INSERTED.value
            assert candidate.followers_count == 55000
            assert candidate.has_email is True
            assert candidate.global_influencer_id is not None
            assert candidate.product_influencer_id is not None
            diagnostics = candidate.source_meta["tiktok_profile_recrawl"]
            assert diagnostics["actor"] == "clockworks/tiktok-profile-scraper"
            assert diagnostics["run_id"] == "profile-run-1"
            assert diagnostics["input_count"] == 1
            assert diagnostics["success_count"] == 1
            assert diagnostics["error"] is None
            await db.rollback()

    asyncio.run(_run())


def test_tiktok_profile_actor_low_quality_recrawl_becomes_filtered_out(monkeypatch):
    async def fake_run_actor(actor_id, run_input, **kwargs):
        return [
            {
                "username": "small",
                "signature": "new creator",
                "followers": 500,
                "avgViews": 100,
                "avgLikes": 1,
                "avgComments": 0,
                "profileUrl": "https://www.tiktok.com/@small",
            }
        ]

    monkeypatch.setattr("app.services.platform_providers.tiktok_apify.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task(strict_quality_filter=True)
            db.add(task)
            await db.flush()
            candidate = _candidate(task, username="small", profile_url="https://www.tiktok.com/@small")
            db.add(candidate)
            await db.flush()

            result = await TaskCandidateRecrawlService.recrawl_candidate(db, candidate.id)

            assert result.status == CandidateStatus.FILTERED_OUT.value
            assert candidate.status == CandidateStatus.FILTERED_OUT.value
            assert candidate.failure_reason == CandidateFailureReason.BELOW_MIN_FOLLOWERS.value
            assert candidate.product_influencer_id is None
            await db.rollback()

    asyncio.run(_run())


def test_tiktok_batch_recrawl_skips_private_invalid_duplicate(monkeypatch):
    calls: list[dict] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append(run_input)
        return [{"username": "recoverable", "followers": 50000, "avgViews": 10000, "avgLikes": 500}]

    monkeypatch.setattr("app.services.platform_providers.tiktok_apify.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            db.add(task)
            await db.flush()
            recoverable = _candidate(task, username="recoverable", profile_url="https://www.tiktok.com/@recoverable")
            private = _candidate(
                task,
                username="private",
                profile_url="https://www.tiktok.com/@private",
                failure_reason=CandidateFailureReason.PRIVATE_ACCOUNT.value,
                failure_detail="private account",
            )
            invalid = _candidate(
                task,
                username="invalid",
                profile_url="https://www.tiktok.com/@invalid",
                failure_reason=CandidateFailureReason.INVALID_USERNAME.value,
                failure_detail="invalid url",
            )
            duplicate = _candidate(
                task,
                username="duplicate",
                profile_url="https://www.tiktok.com/@duplicate",
                status=CandidateStatus.DUPLICATE.value,
                failure_reason=CandidateFailureReason.DUPLICATE.value,
            )
            db.add_all([recoverable, private, invalid, duplicate])
            await db.flush()

            result = await TaskCandidateRecrawlService.recrawl_failed_candidates_for_task(db, task.id)

            assert result.attempted == 1
            assert result.skipped == 3
            assert len(calls) == 1
            assert recoverable.status == CandidateStatus.INSERTED.value
            assert private.status == CandidateStatus.PROFILE_FAILED.value
            assert invalid.status == CandidateStatus.PROFILE_FAILED.value
            assert duplicate.status == CandidateStatus.DUPLICATE.value
            await db.rollback()

    asyncio.run(_run())


def test_tiktok_profile_actor_error_updates_only_current_candidate_diagnostics(monkeypatch):
    calls: list[dict] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append(run_input)
        if len(calls) == 1:
            raise ApifyError("provider timeout")
        return [{"username": "second", "followers": 50000, "avgViews": 10000, "avgLikes": 600}]

    monkeypatch.setattr("app.services.platform_providers.tiktok_apify.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            db.add(task)
            await db.flush()
            first = _candidate(task, username="first", profile_url="https://www.tiktok.com/@first")
            second = _candidate(task, username="second", profile_url="https://www.tiktok.com/@second")
            db.add_all([first, second])
            await db.flush()

            result = await TaskCandidateRecrawlService.recrawl_failed_candidates_for_task(db, task.id)

            assert result.attempted == 2
            assert result.failed == 1
            assert result.succeeded == 1
            assert first.status == CandidateStatus.PROFILE_FAILED.value
            assert first.source_meta["retry_count"] == 1
            assert first.source_meta["tiktok_profile_recrawl"]["actor"] == "clockworks/tiktok-profile-scraper"
            assert first.source_meta["tiktok_profile_recrawl"]["error"] == "provider timeout"
            assert second.status == CandidateStatus.INSERTED.value
            await db.rollback()

    asyncio.run(_run())
