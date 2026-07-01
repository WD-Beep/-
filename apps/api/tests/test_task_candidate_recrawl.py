from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateFailureReason, CandidateStatus, CollectionMode, ProfileFailureReason
from app.services.apify_instagram import FailedProfile, ProfileScrapeResult
from app.services.task_candidate_recrawl import TaskCandidateRecrawlService


def _task(**overrides) -> CollectionTask:
    data = {
        "name": "candidate-recrawl",
        "platform": "instagram",
        "platforms": ["instagram"],
        "collection_mode": CollectionMode.COMMENT_AUTHORS.value,
        "keywords": [],
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
        "username": "retry_creator",
        "profile_url": "https://www.instagram.com/retry_creator/",
        "platform": "instagram",
        "source_type": "comment_author",
        "source_post_url": "https://www.instagram.com/p/source/",
        "source_comment_text": "nice find",
        "source_discovery_type": "comment_author",
        "source_meta": {"original": "kept"},
        "status": CandidateStatus.PROFILE_FAILED.value,
        "failure_reason": CandidateFailureReason.MISSING_PROFILE_DETAIL.value,
        "failure_detail": "主页数据缺失",
    }
    data.update(overrides)
    return CollectionTaskCandidate(**data)


def _profile(**overrides) -> CollectedInfluencer:
    data = {
        "platform": "instagram",
        "username": "retry_creator",
        "profile_url": "https://www.instagram.com/retry_creator/",
        "followers_count": 45_000,
        "engagement_rate": 2.5,
        "bio": "home creator business hello@example.com",
        "final_email": "hello@example.com",
        "email": "hello@example.com",
    }
    data.update(overrides)
    return CollectedInfluencer(**data)


def test_instagram_failed_candidate_recrawl_inserts_and_updates_status(monkeypatch):
    async def fake_scrape(urls, **kwargs):
        assert urls == ["https://www.instagram.com/retry_creator/"]
        return ProfileScrapeResult(profiles=[_profile()])

    monkeypatch.setattr("app.services.task_candidate_recrawl.scrape_instagram_profiles", fake_scrape)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            db.add(task)
            await db.flush()
            candidate = _candidate(task)
            db.add(candidate)
            await db.flush()

            result = await TaskCandidateRecrawlService.recrawl_candidate(db, candidate.id)

            assert result.status == CandidateStatus.INSERTED.value
            assert candidate.status == CandidateStatus.INSERTED.value
            assert candidate.global_influencer_id is not None
            assert candidate.product_influencer_id is not None
            assert candidate.followers_count == 45_000
            assert candidate.engagement_rate == 2.5
            assert candidate.profile_fetched_at is not None
            assert candidate.failure_reason is None
            assert candidate.source_post_url == "https://www.instagram.com/p/source/"
            assert candidate.source_comment_text == "nice find"
            assert candidate.source_meta["original"] == "kept"
            assert candidate.has_email is True
            assert candidate.has_contact is True
            assert task.inserted_count == 1

            await db.rollback()

    asyncio.run(_run())


def test_recrawl_success_but_quality_blocked_becomes_filtered_out(monkeypatch):
    async def fake_scrape(urls, **kwargs):
        return ProfileScrapeResult(profiles=[_profile(followers_count=1_000, engagement_rate=0.2)])

    monkeypatch.setattr("app.services.task_candidate_recrawl.scrape_instagram_profiles", fake_scrape)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task(strict_quality_filter=True, min_followers_count=10_000)
            db.add(task)
            await db.flush()
            candidate = _candidate(task)
            db.add(candidate)
            await db.flush()

            result = await TaskCandidateRecrawlService.recrawl_candidate(db, candidate.id)

            assert result.status == CandidateStatus.FILTERED_OUT.value
            assert candidate.status == CandidateStatus.FILTERED_OUT.value
            assert candidate.failure_reason == CandidateFailureReason.BELOW_MIN_FOLLOWERS.value
            assert candidate.product_influencer_id is None
            assert candidate.global_influencer_id is None
            assert candidate.followers_count == 1_000
            assert candidate.profile_fetched_at is not None

            await db.rollback()

    asyncio.run(_run())


def test_batch_recrawl_skips_private_invalid_duplicate_and_other_tasks(monkeypatch):
    calls: list[str] = []

    async def fake_scrape(urls, **kwargs):
        calls.extend(urls)
        return ProfileScrapeResult(profiles=[_profile()])

    monkeypatch.setattr("app.services.task_candidate_recrawl.scrape_instagram_profiles", fake_scrape)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            other_task = _task(name="other-task")
            db.add_all([task, other_task])
            await db.flush()
            recoverable = _candidate(task, username="recoverable", profile_url="https://www.instagram.com/recoverable/")
            private = _candidate(
                task,
                username="private_one",
                profile_url="https://www.instagram.com/private_one/",
                failure_reason=CandidateFailureReason.PRIVATE_ACCOUNT.value,
                failure_detail="private account",
            )
            invalid = _candidate(
                task,
                username="invalid_one",
                profile_url="https://www.instagram.com/invalid_one/",
                failure_reason=CandidateFailureReason.INVALID_USERNAME.value,
                failure_detail="invalid url",
            )
            duplicate = _candidate(
                task,
                username="dup_one",
                profile_url="https://www.instagram.com/dup_one/",
                status=CandidateStatus.DUPLICATE.value,
                failure_reason=CandidateFailureReason.DUPLICATE.value,
            )
            other = _candidate(other_task, username="other", profile_url="https://www.instagram.com/other/")
            db.add_all([recoverable, private, invalid, duplicate, other])
            await db.flush()

            result = await TaskCandidateRecrawlService.recrawl_failed_candidates_for_task(db, task.id, concurrency=2)

            assert result.attempted == 1
            assert result.succeeded == 1
            assert result.skipped == 3
            assert calls == ["https://www.instagram.com/recoverable/"]
            assert recoverable.status == CandidateStatus.INSERTED.value
            assert private.status == CandidateStatus.PROFILE_FAILED.value
            assert invalid.status == CandidateStatus.PROFILE_FAILED.value
            assert duplicate.status == CandidateStatus.DUPLICATE.value
            assert other.status == CandidateStatus.PROFILE_FAILED.value

            await db.rollback()

    asyncio.run(_run())


def test_provider_error_keeps_failure_status_and_writes_retry_diagnostics(monkeypatch):
    async def fake_scrape(urls, **kwargs):
        return ProfileScrapeResult(
            errors=["provider timeout"],
            failed_profiles=[
                FailedProfile(
                    username="retry_creator",
                    profile_url="https://www.instagram.com/retry_creator/",
                    reason=ProfileFailureReason.SCRAPER_BLOCKED,
                    detail="provider timeout",
                )
            ],
        )

    monkeypatch.setattr("app.services.task_candidate_recrawl.scrape_instagram_profiles", fake_scrape)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            db.add(task)
            await db.flush()
            candidate = _candidate(task, source_meta={"retry_count": 2})
            db.add(candidate)
            await db.flush()

            result = await TaskCandidateRecrawlService.recrawl_candidate(db, candidate.id)

            assert result.status == CandidateStatus.PROFILE_FAILED.value
            assert candidate.status == CandidateStatus.PROFILE_FAILED.value
            assert candidate.failure_detail == "provider timeout"
            assert candidate.source_meta["retry_count"] == 3
            assert candidate.source_meta["last_retry_error"] == "provider timeout"
            assert candidate.source_meta["last_retry_at"]

            await db.rollback()

    asyncio.run(_run())
