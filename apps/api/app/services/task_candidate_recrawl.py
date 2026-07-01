from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import CollectedInfluencer
from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateFailureReason, CandidateStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.services.apify_instagram import PostAuthorCandidate
from app.services.candidate_pool import hard_filter_failure_detail
from app.services.collection_filters import evaluate_post_hydration_hard_filter
from app.services.high_value_filter import (
    assessment_row_fields,
    evaluate_high_value_assessment,
    should_skip_insert,
    should_strict_filter_out,
)
from app.services.influencer_persistence import (
    InfluencerPersistenceService,
    apply_global_profile_data,
    apply_product_influencer_data,
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
    global_profile_has_changes,
    identity_key_for_item,
    product_record_has_changes,
    should_refresh_global_profile,
)
from app.services.influencer_source import InfluencerSourceService
from app.services.instagram_provider import scrape_instagram_profiles
from app.services.platform_types import URL_ONLY_PLATFORMS, PlatformCandidateProfile
from app.services.platform_providers.tiktok_apify import scrape_tiktok_profile
from app.services.platform_utils import profile_to_collected
from app.services.task_candidate import TaskCandidateService
from app.services.task_influencer import TaskInfluencerService


RECOVERABLE_FAILURE_REASONS = frozenset(
    {
        CandidateFailureReason.MISSING_PROFILE_DETAIL.value,
        CandidateFailureReason.PROFILE_FETCH_FAILED.value,
        CandidateFailureReason.API_FAILED.value,
        CandidateFailureReason.UNKNOWN.value,
        "scraper_blocked",
        "provider_timeout",
        "timeout",
    }
)
UNRECOVERABLE_FAILURE_REASONS = frozenset(
    {
        CandidateFailureReason.PRIVATE_ACCOUNT.value,
        CandidateFailureReason.DISABLED_OR_DELETED.value,
        CandidateFailureReason.INVALID_USERNAME.value,
        CandidateFailureReason.BELOW_MIN_FOLLOWERS.value,
        CandidateFailureReason.BELOW_MIN_ENGAGEMENT_RATE.value,
        CandidateFailureReason.ABOVE_MAX_FOLLOWERS.value,
        CandidateFailureReason.DUPLICATE.value,
    }
)
RECOVERABLE_DETAIL_MARKERS = (
    "missing_profile_detail",
    "profile_failed",
    "profile fetch",
    "profile_fetch",
    "provider timeout",
    "timeout",
    "主页数据缺失",
    "未获取到主页数据",
    "补采失败",
    "post_author_missing",
)
UNRECOVERABLE_DETAIL_MARKERS = (
    "private account",
    "private",
    "invalid url",
    "invalid username",
    "not found",
    "404",
    "duplicate",
    "below_min_followers",
)


@dataclass
class CandidateRecrawlResult:
    candidate_id: int
    task_id: int
    status: str
    attempted: bool = True
    message: str | None = None
    global_influencer_id: int | None = None
    product_influencer_id: int | None = None


@dataclass
class CandidateBatchRecrawlResult:
    task_id: int
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[CandidateRecrawlResult] = field(default_factory=list)


class TaskCandidateRecrawlService:
    @staticmethod
    def is_recoverable(candidate: CollectionTaskCandidate) -> bool:
        if candidate.status not in {
            CandidateStatus.PROFILE_FAILED.value,
            CandidateStatus.NOT_INSERTED.value,
            CandidateStatus.PENDING_PROFILE.value,
        }:
            return False
        reason = (candidate.failure_reason or "").strip().lower()
        detail = (candidate.failure_detail or "").strip().lower()
        if reason in UNRECOVERABLE_FAILURE_REASONS:
            return False
        if any(marker in detail for marker in UNRECOVERABLE_DETAIL_MARKERS):
            return False
        if reason in RECOVERABLE_FAILURE_REASONS:
            return True
        return any(marker in detail for marker in RECOVERABLE_DETAIL_MARKERS)

    @staticmethod
    def _meta_for_candidate(candidate: CollectionTaskCandidate) -> PostAuthorCandidate:
        return PostAuthorCandidate(
            username=candidate.username,
            profile_url=candidate.profile_url,
            source_hashtag=candidate.source_hashtag,
            source_post_url=candidate.source_post_url,
            source_input_url=candidate.source_input_url,
            source_caption=candidate.source_caption,
            source_comment_url=candidate.source_comment_url,
            source_comment_text=candidate.source_comment_text,
            source_discovery_type=candidate.source_discovery_type,
            source_meta=dict(candidate.source_meta or {}),
        )

    @staticmethod
    def _retry_meta(candidate: CollectionTaskCandidate, error: str | None, *, run_at: datetime) -> dict:
        meta = dict(candidate.source_meta or {})
        retry_count = int(meta.get("retry_count") or 0) + 1
        meta.update(
            {
                "retry_count": retry_count,
                "last_retry_at": run_at.isoformat(),
                "last_retry_error": error,
            }
        )
        return meta

    @staticmethod
    def _apply_source_to_item(item: CollectedInfluencer, candidate: CollectionTaskCandidate) -> None:
        if candidate.source_post_url and not item.source_post_url:
            item.source_post_url = candidate.source_post_url
        if candidate.source_comment_url and not item.source_comment_url:
            item.source_comment_url = candidate.source_comment_url
        if candidate.source_comment_text and not item.source_comment_text:
            item.source_comment_text = candidate.source_comment_text
        if candidate.source_discovery_type and not item.source_discovery_type:
            item.source_discovery_type = candidate.source_discovery_type
        if candidate.source_input_url and not getattr(item, "source_input_url", None):
            item.source_input_url = candidate.source_input_url

    @staticmethod
    def _update_candidate_from_row(candidate: CollectionTaskCandidate, row: dict[str, Any]) -> None:
        preserve = {
            "source_type",
            "source_keyword",
            "source_hashtag",
            "source_post_url",
            "source_input_url",
            "source_caption",
            "source_comment_url",
            "source_comment_text",
            "source_discovery_type",
            "source_meta",
        }
        for key, value in row.items():
            if key in preserve and value is None:
                continue
            if hasattr(candidate, key):
                setattr(candidate, key, value)

    @staticmethod
    async def _mark_failure(
        db: AsyncSession,
        task: CollectionTask,
        candidate: CollectionTaskCandidate,
        *,
        reason: str,
        detail: str | None,
        run_at: datetime,
    ) -> CandidateRecrawlResult:
        candidate.status = CandidateStatus.PROFILE_FAILED.value
        candidate.failure_reason = reason
        candidate.failure_detail = detail
        candidate.profile_fetched_at = None
        candidate.source_meta = TaskCandidateRecrawlService._retry_meta(candidate, detail, run_at=run_at)
        await TaskCandidateService.sync_task_inserted_stats(db, task)
        await TaskInfluencerService.refresh_task_stats(db, task)
        await db.flush()
        return CandidateRecrawlResult(
            candidate_id=candidate.id,
            task_id=task.id,
            status=candidate.status,
            message=detail,
        )

    @staticmethod
    async def _persist_item(
        db: AsyncSession,
        task: CollectionTask,
        candidate: CollectionTaskCandidate,
        item: CollectedInfluencer,
        *,
        run_at: datetime,
    ) -> CandidateRecrawlResult:
        TaskCandidateRecrawlService._apply_source_to_item(item, candidate)
        product_id = task.product_id or candidate.product_id or 1

        hard = evaluate_post_hydration_hard_filter(item, task)
        if not hard.passed:
            failure_detail = hard_filter_failure_detail(
                hard.reason,
                task=task,
                followers_count=item.followers_count,
                platform=item.platform,
            )
            row = TaskCandidateService.row_from_filtered(
                username=item.username,
                profile_url=item.profile_url,
                failure_reason=hard.reason,
                failure_detail=failure_detail,
                platform=item.platform,
                source_hashtag=candidate.source_hashtag,
                source_keyword=candidate.source_keyword,
                source_post_url=candidate.source_post_url or item.source_post_url,
                source_caption=candidate.source_caption,
                source_comment_url=candidate.source_comment_url or item.source_comment_url,
                source_comment_text=candidate.source_comment_text or item.source_comment_text,
                source_discovery_type=candidate.source_discovery_type or item.source_discovery_type,
                source_type=candidate.source_type,
                source_meta=dict(candidate.source_meta or {}),
                source_input_url=candidate.source_input_url or getattr(item, "source_input_url", None),
                followers_count=item.followers_count,
                engagement_rate=item.engagement_rate,
                profile_fetched_at=run_at,
            )
            TaskCandidateRecrawlService._update_candidate_from_row(candidate, row)
            return CandidateRecrawlResult(candidate.id, task.id, candidate.status)

        assessment = evaluate_high_value_assessment(item, task)
        if should_strict_filter_out(task, assessment):
            row = TaskCandidateService.row_from_filtered(
                username=item.username,
                profile_url=item.profile_url,
                failure_reason=assessment.filter_reason,
                failure_detail=assessment.filter_detail,
                platform=item.platform,
                source_hashtag=candidate.source_hashtag,
                source_keyword=candidate.source_keyword,
                source_post_url=candidate.source_post_url or item.source_post_url,
                source_caption=candidate.source_caption,
                source_comment_url=candidate.source_comment_url or item.source_comment_url,
                source_comment_text=candidate.source_comment_text or item.source_comment_text,
                source_discovery_type=candidate.source_discovery_type or item.source_discovery_type,
                source_type=candidate.source_type,
                source_meta=dict(candidate.source_meta or {}),
                source_input_url=candidate.source_input_url or getattr(item, "source_input_url", None),
                followers_count=item.followers_count,
                engagement_rate=item.engagement_rate,
                profile_fetched_at=run_at,
            )
            row.update(assessment_row_fields(assessment))
            TaskCandidateRecrawlService._update_candidate_from_row(candidate, row)
            return CandidateRecrawlResult(candidate.id, task.id, candidate.status)

        if should_skip_insert(task, assessment):
            row = TaskCandidateService.row_from_not_inserted(
                username=item.username,
                profile_url=item.profile_url,
                failure_reason=assessment.filter_reason,
                failure_detail=assessment.insert_blocked_reason,
                insert_blocked_reason=assessment.insert_blocked_reason,
                platform=item.platform,
                source_hashtag=candidate.source_hashtag,
                source_keyword=candidate.source_keyword,
                source_post_url=candidate.source_post_url or item.source_post_url,
                source_caption=candidate.source_caption,
                source_comment_url=candidate.source_comment_url or item.source_comment_url,
                source_comment_text=candidate.source_comment_text or item.source_comment_text,
                source_discovery_type=candidate.source_discovery_type or item.source_discovery_type,
                source_type=candidate.source_type,
                source_meta=dict(candidate.source_meta or {}),
                source_input_url=candidate.source_input_url or getattr(item, "source_input_url", None),
                followers_count=item.followers_count,
                engagement_rate=item.engagement_rate,
                profile_fetched_at=run_at,
            )
            row.update(assessment_row_fields(assessment))
            TaskCandidateRecrawlService._update_candidate_from_row(candidate, row)
            return CandidateRecrawlResult(candidate.id, task.id, candidate.status)

        global_map = await InfluencerPersistenceService.find_global_profiles_batch(db, [item])
        product_map = await InfluencerPersistenceService.find_product_influencers_batch(
            db, product_id, [item], global_map=global_map
        )
        identity_key = identity_key_for_item(item)
        global_profile = global_map.get(identity_key)
        product_record = product_map.get(identity_key)

        if product_record:
            if global_profile and (
                should_refresh_global_profile(global_profile, now=run_at)
                or global_profile_has_changes(global_profile, item)
            ):
                apply_global_profile_data(global_profile, item, run_at=run_at)
            if product_record_has_changes(product_record, item, task):
                apply_product_influencer_data(product_record, item, task, run_at=run_at)
            await InfluencerSourceService.record_from_collected(db, product_record, item, task=task, run_at=run_at)
            status_value = CandidateStatus.INSERTED.value
        else:
            if not global_profile:
                global_profile = create_global_profile_from_collected(item, run_at=run_at)
                db.add(global_profile)
            elif should_refresh_global_profile(global_profile, now=run_at) or global_profile_has_changes(
                global_profile, item
            ):
                apply_global_profile_data(global_profile, item, run_at=run_at)
            product_record = create_product_influencer_from_collected(
                product_id=product_id,
                global_profile=global_profile,
                data=item,
                task=task,
                run_at=run_at,
            )
            if global_profile.id is None:
                product_record.global_profile = global_profile
            db.add(product_record)
            await db.flush()
            await InfluencerSourceService.record_from_collected(db, product_record, item, task=task, run_at=run_at)
            status_value = CandidateStatus.INSERTED.value

        await db.flush()
        row = TaskCandidateService.row_from_inserted(
            meta=None,
            username=item.username,
            profile_url=item.profile_url,
            platform=item.platform,
            collection_mode=task.collection_mode,
            product_influencer_id=product_record.id,
            global_influencer_id=global_profile.id if global_profile else product_record.global_influencer_id,
            product_id=product_id,
            user_id=task.user_id or candidate.user_id,
            followers_count=item.followers_count,
            engagement_rate=item.engagement_rate,
            profile_fetched_at=run_at,
            source_type=candidate.source_type,
            source_keyword=candidate.source_keyword,
            source_hashtag=candidate.source_hashtag,
            source_post_url=candidate.source_post_url or item.source_post_url,
            source_input_url=candidate.source_input_url or getattr(item, "source_input_url", None),
            source_caption=candidate.source_caption,
            source_comment_url=candidate.source_comment_url or item.source_comment_url,
            source_comment_text=candidate.source_comment_text or item.source_comment_text,
            source_discovery_type=candidate.source_discovery_type or item.source_discovery_type,
            source_meta=dict(candidate.source_meta or {}),
        )
        row["status"] = status_value
        row.update(assessment_row_fields(assessment))
        TaskCandidateRecrawlService._update_candidate_from_row(candidate, row)
        await TaskCandidateService.sync_task_inserted_stats(db, task)
        await TaskInfluencerService.refresh_task_stats(db, task)
        await db.flush()
        return CandidateRecrawlResult(
            candidate_id=candidate.id,
            task_id=task.id,
            status=candidate.status,
            global_influencer_id=candidate.global_influencer_id,
            product_influencer_id=candidate.product_influencer_id,
        )

    @staticmethod
    def _url_only_collected(candidate: CollectionTaskCandidate) -> CollectedInfluencer | None:
        platform = (candidate.platform or "").strip().lower()
        if platform not in URL_ONLY_PLATFORMS:
            return None
        profile = PlatformCandidateProfile(
            platform=platform,
            username=candidate.username,
            profile_url=candidate.profile_url,
            source_url=candidate.source_input_url or candidate.profile_url,
            source_post_url=candidate.source_post_url,
            source_input_url=candidate.source_input_url,
            source_type=candidate.source_type,
            source_discovery_type=candidate.source_discovery_type,
            source_meta=dict(candidate.source_meta or {}),
        )
        return profile_to_collected(profile)

    @staticmethod
    async def _scrape_candidate(candidate: CollectionTaskCandidate) -> tuple[CollectedInfluencer | None, str | None, str]:
        platform = (candidate.platform or "instagram").strip().lower()
        if platform == "instagram":
            meta = TaskCandidateRecrawlService._meta_for_candidate(candidate)
            key = (candidate.username or "").strip().lower()
            scrape = await scrape_instagram_profiles(
                [candidate.profile_url],
                candidate_meta={key: meta} if key else None,
            )
            if scrape.profiles:
                return scrape.profiles[0], None, CandidateStatus.INSERTED.value
            failed = scrape.failed_profiles[0] if scrape.failed_profiles else None
            detail = (
                failed.detail
                if failed and failed.detail
                else (scrape.errors[0] if scrape.errors else f"No profile data returned for {candidate.profile_url}")
            )
            reason = failed.reason.value if failed else CandidateFailureReason.MISSING_PROFILE_DETAIL.value
            return None, detail, reason

        if platform == "tiktok":
            profile, error = await scrape_tiktok_profile(
                username=candidate.username,
                profile_url=candidate.profile_url,
            )
            if profile:
                meta = dict(candidate.source_meta or {})
                meta.update(profile.source_meta or {})
                candidate.source_meta = meta
                return profile_to_collected(profile), None, CandidateStatus.INSERTED.value
            meta = dict(candidate.source_meta or {})
            meta["tiktok_profile_recrawl"] = {
                "actor": settings.apify_tiktok_profile_actor_id,
                "input_count": 1,
                "success_count": 0,
                "error": error,
            }
            candidate.source_meta = meta
            return None, error or "missing_profile_detail", CandidateFailureReason.MISSING_PROFILE_DETAIL.value

        item = TaskCandidateRecrawlService._url_only_collected(candidate)
        if item:
            return item, None, CandidateStatus.INSERTED.value
        return None, f"{platform} does not support single profile recrawl yet", CandidateFailureReason.PROFILE_FETCH_FAILED.value

    @staticmethod
    async def recrawl_candidate(
        db: AsyncSession,
        candidate_id: int,
        *,
        task_id: int | None = None,
        profile_url: str | None = None,
    ) -> CandidateRecrawlResult:
        query = select(CollectionTaskCandidate).where(CollectionTaskCandidate.id == candidate_id)
        if task_id is not None:
            query = query.where(CollectionTaskCandidate.task_id == task_id)
        result = await db.execute(query)
        candidate = result.scalar_one_or_none()
        if not candidate:
            raise ValueError("candidate_not_found")
        if profile_url and candidate.profile_url.rstrip("/") != profile_url.rstrip("/"):
            raise ValueError("candidate_profile_url_mismatch")
        task = await db.get(CollectionTask, candidate.task_id)
        if not task:
            raise ValueError("task_not_found")

        run_at = datetime.now(UTC)
        try:
            item, error, reason = await TaskCandidateRecrawlService._scrape_candidate(candidate)
            if not item:
                return await TaskCandidateRecrawlService._mark_failure(
                    db,
                    task,
                    candidate,
                    reason=reason,
                    detail=error,
                    run_at=run_at,
                )
            result = await TaskCandidateRecrawlService._persist_item(
                db,
                task,
                candidate,
                item,
                run_at=run_at,
            )
            await db.commit()
            return result
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            result = await TaskCandidateRecrawlService._mark_failure(
                db,
                task,
                candidate,
                reason=CandidateFailureReason.PROFILE_FETCH_FAILED.value,
                detail=detail[:500],
                run_at=run_at,
            )
            await db.commit()
            return result

    @staticmethod
    async def recrawl_failed_candidates_for_task(
        db: AsyncSession,
        task_id: int,
        *,
        concurrency: int = 3,
        limit: int | None = None,
    ) -> CandidateBatchRecrawlResult:
        task = await db.get(CollectionTask, task_id)
        if not task:
            raise ValueError("task_not_found")
        result = await db.execute(
            select(CollectionTaskCandidate)
            .where(CollectionTaskCandidate.task_id == task_id)
            .order_by(CollectionTaskCandidate.id.asc())
        )
        candidates = list(result.scalars().all())
        recoverable = [candidate for candidate in candidates if TaskCandidateRecrawlService.is_recoverable(candidate)]
        skipped = len(candidates) - len(recoverable)
        if limit is not None:
            skipped += max(0, len(recoverable) - limit)
            recoverable = recoverable[:limit]

        batch = CandidateBatchRecrawlResult(task_id=task_id, skipped=skipped)

        del concurrency
        outcomes: list[CandidateRecrawlResult | BaseException] = []
        for candidate in recoverable:
            try:
                outcomes.append(await TaskCandidateRecrawlService.recrawl_candidate(db, candidate.id))
            except BaseException as exc:
                outcomes.append(exc)
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                batch.failed += 1
                continue
            batch.items.append(outcome)
            batch.attempted += 1
            if outcome.status in {
                CandidateStatus.INSERTED.value,
                CandidateStatus.FILTERED_OUT.value,
                CandidateStatus.NOT_INSERTED.value,
                CandidateStatus.DUPLICATE.value,
            }:
                batch.succeeded += 1
            else:
                batch.failed += 1
        await TaskCandidateService.sync_task_inserted_stats(db, task)
        await TaskInfluencerService.refresh_task_stats(db, task)
        await db.commit()
        return batch
