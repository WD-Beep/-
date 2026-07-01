from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import CollectedInfluencer
from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.services.apify_client import run_actor_sync
from app.services.contact_discovery import EMAIL_RE, normalize_email
from app.services.high_value_filter import assessment_row_fields, evaluate_high_value_assessment
from app.services.influencer_persistence import (
    InfluencerPersistenceService,
    apply_global_profile_data,
    apply_product_influencer_data,
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
    identity_key_for_item,
)
from app.services.influencer_source import InfluencerSourceService
from app.services.task_candidate import TaskCandidateService
from app.services.task_influencer import TaskInfluencerService


DEFAULT_YOUTUBE_EMAIL_BATCH_LIMIT = 20
EMAIL_DIAGNOSTIC_KEY = "youtube_email_enrichment"
YOUTUBE_CHANNEL_ID_RE = re.compile(r"/channel/([^/?#]+)", re.I)
YOUTUBE_HANDLE_RE = re.compile(r"(?:youtube\.com/)?@([^/?#]+)", re.I)


@dataclass
class YouTubeEmailEnrichmentResult:
    candidate_id: int
    task_id: int
    status: str
    attempted: bool = True
    message: str | None = None
    email: str | None = None
    global_influencer_id: int | None = None
    product_influencer_id: int | None = None


@dataclass
class YouTubeEmailBatchEnrichmentResult:
    task_id: int
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[YouTubeEmailEnrichmentResult] = field(default_factory=list)


def _first_email_from_value(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = normalize_email(value)
        if normalized:
            return normalized
        for match in EMAIL_RE.findall(value):
            normalized = normalize_email(match)
            if normalized:
                return normalized
    if isinstance(value, list):
        for item in value:
            email = _first_email_from_value(item)
            if email:
                return email
    if isinstance(value, dict):
        preferred = (
            "businessEmail",
            "business_email",
            "channelEmail",
            "email",
            "emails",
            "publicEmail",
            "public_email",
        )
        for key in preferred:
            if key in value:
                email = _first_email_from_value(value.get(key))
                if email:
                    return email
        for nested in value.values():
            email = _first_email_from_value(nested)
            if email:
                return email
    return None


def _first_email_item(items: Any) -> tuple[str | None, dict[str, Any] | None]:
    if isinstance(items, list):
        for item in items:
            email = _first_email_from_value(item)
            if email:
                return email, item if isinstance(item, dict) else None
    email = _first_email_from_value(items)
    return email, items if isinstance(items, dict) else None


def _run_id_from_items(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        for key in ("runId", "run_id", "apifyRunId", "actorRunId"):
            value = item.get(key)
            if value:
                return str(value)
    return None


def _channel_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = YOUTUBE_CHANNEL_ID_RE.search(url)
    return match.group(1) if match else None


def _handle_from_candidate(candidate: CollectionTaskCandidate) -> str | None:
    for value in (candidate.username, candidate.profile_url):
        if not value:
            continue
        match = YOUTUBE_HANDLE_RE.search(value)
        if match:
            return f"@{match.group(1).strip()}"
    username = (candidate.username or "").strip()
    if username and not username.startswith("UC"):
        return username if username.startswith("@") else f"@{username}"
    return None


def _normalize_youtube_url(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower().split("?", 1)[0].rstrip("/")
    if text.startswith("http://"):
        text = "https://" + text.removeprefix("http://")
    return text or None


def _handle_from_value(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    match = YOUTUBE_HANDLE_RE.search(value)
    if match:
        return f"@{match.group(1).strip().lower()}"
    text = value.strip()
    if text.startswith("@"):
        return text.lower()
    return None


def _item_values(item: dict[str, Any] | None, *keys: str) -> list[Any]:
    if not isinstance(item, dict):
        return []
    values: list[Any] = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    return values


def _email_confidence_for_candidate(
    candidate: CollectionTaskCandidate,
    item: dict[str, Any] | None,
) -> tuple[str, str | None]:
    if not item:
        return "high", None

    expected_url = _normalize_youtube_url(candidate.profile_url)
    expected_handle = _handle_from_candidate(candidate)
    expected_handle = expected_handle.lower() if expected_handle else None
    expected_channel_id = _channel_id_from_url(candidate.profile_url)

    checks: list[bool] = []
    for value in _item_values(item, "channelUrl", "channel_url", "url", "profileUrl", "profile_url"):
        returned_url = _normalize_youtube_url(str(value))
        if returned_url and expected_url:
            checks.append(returned_url == expected_url)
    for value in _item_values(item, "handle", "channelHandle", "channel_handle", "username"):
        returned_handle = _handle_from_value(value)
        if returned_handle and expected_handle:
            checks.append(returned_handle == expected_handle)
    for value in _item_values(item, "channelId", "channel_id", "id"):
        if expected_channel_id:
            checks.append(str(value).strip() == expected_channel_id)

    if checks and not any(checks):
        return "low", "channel_identity_mismatch"
    return "high", None


def _actor_input_for_candidate(candidate: CollectionTaskCandidate) -> dict[str, Any]:
    channel_url = (candidate.profile_url or "").strip()
    channel_id = _channel_id_from_url(channel_url)
    handle = _handle_from_candidate(candidate)
    return {
        "channelUrls": [channel_url] if channel_url else [],
        "handles": [handle] if handle else [],
        "channelIds": [channel_id] if channel_id else [],
        "startUrls": [{"url": channel_url}] if channel_url else [],
    }


def _candidate_item(candidate: CollectionTaskCandidate, email: str | None = None) -> CollectedInfluencer:
    return CollectedInfluencer(
        platform="youtube",
        username=candidate.username,
        profile_url=candidate.profile_url,
        followers_count=candidate.followers_count,
        engagement_rate=candidate.engagement_rate,
        email=email,
        final_email=email,
        business_email=email,
        email_source="youtube_business_email_apify" if email else None,
        contact_credibility=90.0 if email else None,
        contact_score=85.0 if email else None,
        contact_credibility_level="high" if email else None,
        source_discovery_type=candidate.source_discovery_type,
        source_post_url=candidate.source_post_url,
        source_input_url=candidate.source_input_url,
        source_comment_url=candidate.source_comment_url,
        source_comment_text=candidate.source_comment_text,
        contact_discovered_at=datetime.now(UTC) if email else None,
        contact_sources=(
            [
                {
                    "type": "business_email",
                    "source": "apify_youtube_email_actor",
                    "url": candidate.profile_url,
                }
            ]
            if email
            else []
        ),
        contact_fetch_status="success" if email else "not_found",
    )


class YouTubeEmailEnrichmentService:
    @staticmethod
    def _has_candidate_email(candidate: CollectionTaskCandidate) -> bool:
        return candidate.has_email is True

    @staticmethod
    def _candidate_platform(candidate: CollectionTaskCandidate) -> str:
        return (candidate.platform or "").strip().lower()

    @staticmethod
    async def _global_has_email(db: AsyncSession, candidate: CollectionTaskCandidate) -> bool:
        if not candidate.global_influencer_id:
            return False
        profile = await db.get(GlobalInfluencerProfile, candidate.global_influencer_id)
        return bool(
            profile
            and (
                profile.final_email
                or profile.email
                or profile.public_email
                or profile.business_email
            )
        )

    @staticmethod
    async def is_eligible(db: AsyncSession, candidate: CollectionTaskCandidate) -> bool:
        if YouTubeEmailEnrichmentService._candidate_platform(candidate) != "youtube":
            return False
        if not candidate.profile_url:
            return False
        if YouTubeEmailEnrichmentService._has_candidate_email(candidate):
            return False
        return True

    @staticmethod
    def _with_diagnostics(
        candidate: CollectionTaskCandidate,
        *,
        run_at: datetime,
        email_found: bool,
        run_id: str | None = None,
        error: str | None = None,
        confidence: str | None = None,
        mismatch_reason: str | None = None,
    ) -> dict:
        meta = dict(candidate.source_meta or {})
        diagnostics = {
            "actor": settings.apify_youtube_email_actor_id,
            "run_id": run_id,
            "email_found": email_found,
            "last_email_enriched_at": run_at.isoformat(),
            "error": error,
        }
        if confidence:
            diagnostics["confidence"] = confidence
        if mismatch_reason:
            diagnostics["mismatch_reason"] = mismatch_reason
        meta[EMAIL_DIAGNOSTIC_KEY] = diagnostics
        return meta

    @staticmethod
    async def _persist_email(
        db: AsyncSession,
        task: CollectionTask,
        candidate: CollectionTaskCandidate,
        email: str,
        *,
        run_at: datetime,
    ) -> tuple[GlobalInfluencerProfile, ProductInfluencer]:
        item = _candidate_item(candidate, email=email)
        product_id = task.product_id or candidate.product_id or 1
        global_profile: GlobalInfluencerProfile | None = None
        product_record: ProductInfluencer | None = None

        if candidate.global_influencer_id:
            global_profile = await db.get(GlobalInfluencerProfile, candidate.global_influencer_id)
        if candidate.product_influencer_id:
            product_record = await db.get(ProductInfluencer, candidate.product_influencer_id)

        if not global_profile:
            global_map = await InfluencerPersistenceService.find_global_profiles_batch(db, [item])
            global_profile = global_map.get(identity_key_for_item(item))
        if not global_profile:
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db.add(global_profile)
            await db.flush()
        else:
            apply_global_profile_data(global_profile, item, run_at=run_at)

        if not product_record:
            product_map = await InfluencerPersistenceService.find_product_influencers_batch(
                db,
                product_id,
                [item],
                global_map={identity_key_for_item(item): global_profile},
            )
            product_record = product_map.get(identity_key_for_item(item))
        if not product_record:
            product_record = create_product_influencer_from_collected(
                product_id=product_id,
                global_profile=global_profile,
                data=item,
                task=task,
                run_at=run_at,
            )
            db.add(product_record)
            await db.flush()
        else:
            apply_product_influencer_data(product_record, item, task, run_at=run_at)

        await InfluencerSourceService.record_from_collected(db, product_record, item, task=task, run_at=run_at)
        return global_profile, product_record

    @staticmethod
    async def enrich_candidate(
        db: AsyncSession,
        candidate_id: int,
        *,
        task_id: int | None = None,
    ) -> YouTubeEmailEnrichmentResult:
        query = select(CollectionTaskCandidate).where(CollectionTaskCandidate.id == candidate_id)
        if task_id is not None:
            query = query.where(CollectionTaskCandidate.task_id == task_id)
        result = await db.execute(query)
        candidate = result.scalar_one_or_none()
        if not candidate:
            raise ValueError("candidate_not_found")
        task = await db.get(CollectionTask, candidate.task_id)
        if not task:
            raise ValueError("task_not_found")

        if not await YouTubeEmailEnrichmentService.is_eligible(db, candidate):
            return YouTubeEmailEnrichmentResult(
                candidate_id=candidate.id,
                task_id=task.id,
                status="skipped",
                attempted=False,
                message="candidate_not_eligible_for_youtube_email_enrichment",
                global_influencer_id=candidate.global_influencer_id,
                product_influencer_id=candidate.product_influencer_id,
            )

        run_at = datetime.now(UTC)
        actor_id = settings.apify_youtube_email_actor_id
        try:
            items = await run_actor_sync(
                actor_id,
                _actor_input_for_candidate(candidate),
                timeout=settings.apify_youtube_timeout_seconds,
                max_retries=settings.apify_youtube_max_retries,
            )
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            candidate.source_meta = YouTubeEmailEnrichmentService._with_diagnostics(
                candidate,
                run_at=run_at,
                email_found=False,
                error=detail[:500],
            )
            await db.commit()
            return YouTubeEmailEnrichmentResult(
                candidate_id=candidate.id,
                task_id=task.id,
                status="failed",
                message=detail[:500],
                global_influencer_id=candidate.global_influencer_id,
                product_influencer_id=candidate.product_influencer_id,
            )

        email, email_item = _first_email_item(items)
        run_id = _run_id_from_items([item for item in items if isinstance(item, dict)])
        if not email:
            candidate.has_email = False
            candidate.contact_status = candidate.contact_status or "missing"
            candidate.source_meta = YouTubeEmailEnrichmentService._with_diagnostics(
                candidate,
                run_at=run_at,
                email_found=False,
                run_id=run_id,
                error=None,
            )
            await db.commit()
            return YouTubeEmailEnrichmentResult(
                candidate_id=candidate.id,
                task_id=task.id,
                status="email_not_found",
                message="email_not_found",
                global_influencer_id=candidate.global_influencer_id,
                product_influencer_id=candidate.product_influencer_id,
            )

        confidence, mismatch_reason = _email_confidence_for_candidate(candidate, email_item)
        if confidence == "low":
            candidate.has_email = False
            candidate.has_contact = False
            candidate.contact_status = "needs_review"
            candidate.source_meta = YouTubeEmailEnrichmentService._with_diagnostics(
                candidate,
                run_at=run_at,
                email_found=True,
                run_id=run_id,
                error=None,
                confidence=confidence,
                mismatch_reason=mismatch_reason,
            )
            await db.commit()
            return YouTubeEmailEnrichmentResult(
                candidate_id=candidate.id,
                task_id=task.id,
                status="needs_review",
                message=mismatch_reason or "email_needs_review",
                email=email,
                global_influencer_id=candidate.global_influencer_id,
                product_influencer_id=candidate.product_influencer_id,
            )

        global_profile, product_record = await YouTubeEmailEnrichmentService._persist_email(
            db,
            task,
            candidate,
            email,
            run_at=run_at,
        )
        assessment = evaluate_high_value_assessment(_candidate_item(candidate, email=email), task)
        for key, value in assessment_row_fields(assessment).items():
            setattr(candidate, key, value)
        candidate.status = CandidateStatus.INSERTED.value
        candidate.failure_reason = None
        candidate.failure_detail = None
        candidate.insert_blocked_reason = None
        candidate.profile_fetched_at = candidate.profile_fetched_at or run_at
        candidate.global_influencer_id = global_profile.id
        candidate.product_influencer_id = product_record.id
        candidate.product_id = product_id = task.product_id or candidate.product_id or product_record.product_id
        candidate.user_id = task.user_id or candidate.user_id
        candidate.source_meta = YouTubeEmailEnrichmentService._with_diagnostics(
            candidate,
            run_at=run_at,
            email_found=True,
            run_id=run_id,
            error=None,
            confidence=confidence,
        )
        await TaskCandidateService.sync_task_inserted_stats(db, task)
        await TaskInfluencerService.refresh_task_stats(db, task)
        await db.commit()
        return YouTubeEmailEnrichmentResult(
            candidate_id=candidate.id,
            task_id=task.id,
            status="email_found",
            message="email_found",
            email=email,
            global_influencer_id=global_profile.id,
            product_influencer_id=product_record.id,
        )

    @staticmethod
    async def enrich_missing_for_task(
        db: AsyncSession,
        task_id: int,
        *,
        limit: int | None = DEFAULT_YOUTUBE_EMAIL_BATCH_LIMIT,
    ) -> YouTubeEmailBatchEnrichmentResult:
        task = await db.get(CollectionTask, task_id)
        if not task:
            raise ValueError("task_not_found")
        result = await db.execute(
            select(CollectionTaskCandidate)
            .where(CollectionTaskCandidate.task_id == task_id)
            .order_by(desc(CollectionTaskCandidate.is_high_value), CollectionTaskCandidate.id.asc())
        )
        candidates = list(result.scalars().all())
        eligible: list[CollectionTaskCandidate] = []
        skipped = 0
        for candidate in candidates:
            if await YouTubeEmailEnrichmentService.is_eligible(db, candidate):
                eligible.append(candidate)
            else:
                skipped += 1
        if limit is None:
            limit = DEFAULT_YOUTUBE_EMAIL_BATCH_LIMIT
        limit = max(1, min(int(limit), 100))
        skipped += max(0, len(eligible) - limit)
        eligible = eligible[:limit]

        batch = YouTubeEmailBatchEnrichmentResult(task_id=task_id, skipped=skipped)
        for candidate in eligible:
            try:
                item = await YouTubeEmailEnrichmentService.enrich_candidate(db, candidate.id, task_id=task_id)
            except BaseException as exc:
                batch.failed += 1
                batch.items.append(
                    YouTubeEmailEnrichmentResult(
                        candidate_id=candidate.id,
                        task_id=task_id,
                        status="failed",
                        message=str(exc)[:500],
                    )
                )
                continue
            batch.items.append(item)
            if item.attempted:
                batch.attempted += 1
            if item.status == "email_found":
                batch.succeeded += 1
            elif item.status == "failed":
                batch.failed += 1
        await TaskCandidateService.sync_task_inserted_stats(db, task)
        await TaskInfluencerService.refresh_task_stats(db, task)
        await db.commit()
        return batch
