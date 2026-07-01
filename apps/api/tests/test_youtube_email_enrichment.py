from __future__ import annotations

import asyncio

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.services.youtube_email_enrichment import YouTubeEmailEnrichmentService


def _task(**overrides) -> CollectionTask:
    data = {
        "name": "youtube-email-enrichment",
        "platform": "youtube",
        "platforms": ["youtube"],
        "collection_mode": CollectionMode.KEYWORD.value,
        "keywords": ["home decor"],
        "input_urls": [],
        "product_id": 1,
        "user_id": 1,
        "workspace_id": 1,
    }
    data.update(overrides)
    return CollectionTask(**data)


def _candidate(task: CollectionTask, **overrides) -> CollectionTaskCandidate:
    data = {
        "task_id": task.id,
        "product_id": task.product_id,
        "user_id": task.user_id,
        "username": "creator",
        "profile_url": "https://www.youtube.com/@creator",
        "platform": "youtube",
        "followers_count": 50_000,
        "engagement_rate": 3.2,
        "is_high_value": True,
        "has_email": False,
        "has_contact": False,
        "contact_status": "missing",
        "status": CandidateStatus.INSERTED.value,
        "source_meta": {"original": "kept"},
    }
    data.update(overrides)
    return CollectionTaskCandidate(**data)


def test_single_youtube_email_enrichment_writes_back_email(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append((actor_id, run_input))
        return [
            {
                "channelUrl": "https://www.youtube.com/@creator",
                "businessEmail": "hello@creator.com",
                "runId": "run-123",
            }
        ]

    monkeypatch.setattr("app.services.youtube_email_enrichment.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            db.add(task)
            await db.flush()
            candidate = _candidate(task)
            db.add(candidate)
            await db.flush()

            result = await YouTubeEmailEnrichmentService.enrich_candidate(db, candidate.id, task_id=task.id)

            assert result.status == "email_found"
            assert candidate.has_email is True
            assert candidate.has_contact is True
            assert candidate.contact_status == "found"
            assert candidate.source_meta["original"] == "kept"
            diagnostics = candidate.source_meta["youtube_email_enrichment"]
            assert diagnostics["actor"] == "dataovercoffee/Youtube-Channel-Business-Email-Scraper"
            assert diagnostics["run_id"] == "run-123"
            assert diagnostics["email_found"] is True
            assert diagnostics["last_email_enriched_at"]
            assert diagnostics["error"] is None
            assert candidate.global_influencer_id is not None
            assert candidate.product_influencer_id is not None

            global_profile = await db.get(GlobalInfluencerProfile, candidate.global_influencer_id)
            product_record = await db.get(ProductInfluencer, candidate.product_influencer_id)
            assert global_profile.final_email == "hello@creator.com"
            assert global_profile.business_email == "hello@creator.com"
            assert product_record.global_influencer_id == global_profile.id
            assert calls[0][0] == "dataovercoffee/Youtube-Channel-Business-Email-Scraper"
            assert "https://www.youtube.com/@creator" in str(calls[0][1])

            await db.rollback()

    asyncio.run(_run())


def test_single_youtube_email_enrichment_no_email_keeps_missing_and_writes_diagnostics(monkeypatch):
    async def fake_run_actor(actor_id, run_input, **kwargs):
        return [{"channelUrl": "https://www.youtube.com/@creator", "runId": "run-empty"}]

    monkeypatch.setattr("app.services.youtube_email_enrichment.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            db.add(task)
            await db.flush()
            candidate = _candidate(task)
            db.add(candidate)
            await db.flush()

            result = await YouTubeEmailEnrichmentService.enrich_candidate(db, candidate.id, task_id=task.id)

            assert result.status == "email_not_found"
            assert candidate.has_email is False
            assert candidate.contact_status == "missing"
            diagnostics = candidate.source_meta["youtube_email_enrichment"]
            assert diagnostics["email_found"] is False
            assert diagnostics["run_id"] == "run-empty"
            assert diagnostics["error"] is None

            await db.rollback()

    asyncio.run(_run())


def test_single_youtube_email_enrichment_mismatched_channel_marks_needs_review(monkeypatch):
    async def fake_run_actor(actor_id, run_input, **kwargs):
        return [
            {
                "channelUrl": "https://www.youtube.com/@othercreator",
                "handle": "@othercreator",
                "businessEmail": "sales@unrelated.example",
                "runId": "run-mismatch",
            }
        ]

    monkeypatch.setattr("app.services.youtube_email_enrichment.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            db.add(task)
            await db.flush()
            candidate = _candidate(
                task,
                username="creator",
                profile_url="https://www.youtube.com/@creator",
            )
            db.add(candidate)
            await db.flush()

            result = await YouTubeEmailEnrichmentService.enrich_candidate(db, candidate.id, task_id=task.id)

            assert result.status == "needs_review"
            assert result.email == "sales@unrelated.example"
            assert candidate.has_email is False
            assert candidate.has_contact is False
            assert candidate.contact_status == "needs_review"
            assert candidate.global_influencer_id is None
            assert candidate.product_influencer_id is None
            diagnostics = candidate.source_meta["youtube_email_enrichment"]
            assert diagnostics["email_found"] is True
            assert diagnostics["confidence"] == "low"
            assert diagnostics["mismatch_reason"] == "channel_identity_mismatch"
            assert diagnostics["run_id"] == "run-mismatch"

            await db.rollback()

    asyncio.run(_run())


def test_batch_youtube_email_enrichment_only_processes_current_task_youtube_missing_email(monkeypatch):
    calls: list[dict] = []

    async def fake_run_actor(actor_id, run_input, **kwargs):
        calls.append(run_input)
        return [{"email": "batch@brandmail.com", "runId": "run-batch"}]

    monkeypatch.setattr("app.services.youtube_email_enrichment.run_actor_sync", fake_run_actor)

    async def _run() -> None:
        async with async_session_factory() as db:
            task = _task()
            other_task = _task(name="other")
            db.add_all([task, other_task])
            await db.flush()
            high_value = _candidate(task, username="high", profile_url="https://www.youtube.com/@high", is_high_value=True)
            low_value = _candidate(task, username="low", profile_url="https://www.youtube.com/@low", is_high_value=False)
            has_email = _candidate(task, username="done", profile_url="https://www.youtube.com/@done", has_email=True)
            instagram = _candidate(task, username="ig", profile_url="https://www.instagram.com/ig/", platform="instagram")
            tiktok = _candidate(task, username="tt", profile_url="https://www.tiktok.com/@tt", platform="tiktok")
            other = _candidate(other_task, username="other", profile_url="https://www.youtube.com/@other")
            db.add_all([low_value, high_value, has_email, instagram, tiktok, other])
            await db.flush()

            result = await YouTubeEmailEnrichmentService.enrich_missing_for_task(db, task.id, limit=10)

            assert result.attempted == 2
            assert result.succeeded == 2
            assert result.skipped == 3
            assert [item.candidate_id for item in result.items] == [high_value.id, low_value.id]
            assert len(calls) == 2
            assert high_value.has_email is True
            assert low_value.has_email is True
            assert has_email.has_email is True
            assert instagram.has_email is False
            assert tiktok.has_email is False
            assert other.has_email is False

            await db.rollback()

    asyncio.run(_run())
