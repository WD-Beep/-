from datetime import UTC, datetime

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import get_collector
from app.collectors.base import CollectedInfluencer
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.models.influencer import Influencer
from app.models.product_influencer import ProductInfluencer
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
from app.core.config import settings
from app.db.session import async_session_factory
from app.services.ai_service import analyze_influencer
from app.services.influencer_source import InfluencerSourceService
from app.services.instagram_urls import (
    normalize_instagram_post_url,
    normalize_instagram_profile_url,
)
from app.services.email import EmailService
from app.services.instagram_pipeline import InstagramCollectionPipeline, InstagramPipelineResult, PipelineRunStats
from app.services.link_import import LinkImportService
from app.services.multi_platform_runner import (
    build_multi_platform_error_prefix,
    build_multi_platform_summary,
    determine_multi_platform_status,
    merge_platform_results,
)
from app.services.api_direct_provider import discover_non_instagram_platforms, task_platforms
from app.services.scoring import (
    calculate_composite_score_from_metrics,
    calculate_influencer_composite_score,
    calculate_risk_level,
    calculate_score,
)
from app.services.business_quality import apply_creator_quality

logger = logging.getLogger(__name__)

_collection_run_lock = asyncio.Lock()
_active_collection_task_ids: set[int] = set()
KEYWORD_SEED_PLATFORMS = frozenset({"pinterest", "shopmy"})
KEYWORD_SEED_COLLECTION_MODES = frozenset(
    {
        CollectionMode.KEYWORD.value,
        CollectionMode.DISCOVERY.value,
        CollectionMode.MIXED.value,
    }
)


def _split_keyword_seed_platforms(
    task: CollectionTask,
    platforms: list[str],
) -> tuple[list[str], list[str]]:
    if (task.collection_mode or "") not in KEYWORD_SEED_COLLECTION_MODES:
        return platforms, []
    seed_platforms = [platform for platform in platforms if platform in KEYWORD_SEED_PLATFORMS]
    discovery_platforms = [platform for platform in platforms if platform not in KEYWORD_SEED_PLATFORMS]
    return discovery_platforms, seed_platforms


async def run_instagram_pipeline_with_provider_check(
    task: CollectionTask,
    *,
    db: AsyncSession,
    checkpoint,
) -> InstagramPipelineResult:
    """Instagram provider 未配置时返回明确错误，避免阻断多平台任务中的其他平台。"""
    try:
        get_collector(task)
    except RuntimeError as exc:
        message = str(exc).strip() or "Instagram 采集未配置"
        return InstagramPipelineResult(
            errors=[f"[instagram] {message}"],
            stats=PipelineRunStats(discovery_api_failed=True),
        )
    return await InstagramCollectionPipeline.run(task, db=db, checkpoint=checkpoint)


def _annotate_instagram_failure_in_aggregate(aggregate, pipeline_result: InstagramPipelineResult | None) -> None:
    if not pipeline_result or not getattr(pipeline_result.stats, "discovery_api_failed", False):
        return
    if not pipeline_result.errors:
        return
    reason = pipeline_result.errors[0]
    if not any(entry.startswith("instagram:") for entry in aggregate.platform_failures):
        aggregate.platform_failures.append(reason if reason.startswith("[instagram]") else f"instagram: {reason}")
    if aggregate.platform_successes:
        aggregate.has_api_warnings = True


from app.services.candidate_pool import hard_filter_failure_detail, meta_source_fields
from app.services.category_discovery import apply_category_discovery_expansion
from app.services.collection_filters import (
    PostHydrationHardFilterResult,
    evaluate_post_hydration_hard_filter,
    get_quality_preference_mismatch_reasons,
)
from app.services.high_value_filter import (
    assessment_row_fields,
    evaluate_high_value_assessment,
    should_skip_insert,
    should_strict_filter_out,
)
from app.services.collection_funnel import (
    CollectionFunnelStats,
    append_target_qualified_summary,
    build_status_summary,
    determine_task_status,
)
from app.services.collection_targets import (
    CollectionRunContext,
    RATE_LIMIT_STOP_REASON,
    discovery_fetch_limit,
    max_candidates_to_process,
    max_overfetch_rounds_for_task,
    should_stop_overfetch_round,
    reset_run_context,
    set_run_context,
    target_qualified_count,
)
from app.services.discovery_progress import DiscoveryProgressReporter, reset_discovery_reporter, set_discovery_reporter
from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import (
    candidate_row_from_profile,
    collected_identity_key,
    dedupe_collected_items,
    profile_identity_key,
    profile_to_collected,
    platform_identity_key,
    resolve_platform_unique_id,
)
from app.services.concurrency import map_bounded
from app.services.cross_platform_instagram_enrichment import enrich_profiles_with_instagram_email
from app.services.task_influencer import TaskInfluencerService
from app.services.task_candidate import TaskCandidateService
from app.services.task_run_progress import (
    RunCheckpoint,
    STAGE_AI_COMPLETED,
    STAGE_AI_PROCESSING,
    STAGE_COMPLETED,
    STAGE_DISCOVERY,
    STAGE_FAILED,
    STAGE_PERSIST,
    apply_terminal_task_state,
    clear_interrupted_checkpoint,
    clear_task_error_fields,
    is_terminal_success_status,
    reset_run_progress,
    update_task_progress,
)


class CollectionRunnerService:
    @staticmethod
    def get_active_collection_task_ids() -> set[int]:
        return set(_active_collection_task_ids)

    @staticmethod
    def get_active_collection_task_id() -> int | None:
        if not _active_collection_task_ids:
            return None
        return next(iter(_active_collection_task_ids))

    @staticmethod
    def active_collection_run_count() -> int:
        return len(_active_collection_task_ids)

    @staticmethod
    def collection_run_capacity() -> int:
        return max(1, settings.collection_max_running_tasks)

    @staticmethod
    def has_active_collection_run() -> bool:
        return len(_active_collection_task_ids) >= CollectionRunnerService.collection_run_capacity()

    @staticmethod
    def is_task_active_in_process(task_id: int) -> bool:
        return task_id in _active_collection_task_ids

    @staticmethod
    async def reconcile_in_process_runs(db: AsyncSession) -> int:
        """Drop in-memory run claims that no longer match RUNNING rows in DB."""
        async with _collection_run_lock:
            if not _active_collection_task_ids:
                return 0
            result = await db.execute(
                select(CollectionTask.id).where(
                    CollectionTask.id.in_(_active_collection_task_ids),
                    CollectionTask.status == CollectionTaskStatus.RUNNING.value,
                )
            )
            live_ids = {row[0] for row in result.all()}
            stale_ids = _active_collection_task_ids - live_ids
            for task_id in stale_ids:
                _active_collection_task_ids.discard(task_id)
            return len(stale_ids)

    @staticmethod
    async def _claim_collection_run(task_id: int) -> None:
        async with _collection_run_lock:
            if task_id in _active_collection_task_ids:
                return
            capacity = CollectionRunnerService.collection_run_capacity()
            if len(_active_collection_task_ids) >= capacity:
                other_id = next(iter(_active_collection_task_ids))
                raise ValueError(
                    f"已有 {len(_active_collection_task_ids)} 个任务在采集中（上限 {capacity}），"
                    f"请等待任务 {other_id} 完成后再运行"
                )
            _active_collection_task_ids.add(task_id)

    @staticmethod
    async def _release_collection_run(task_id: int) -> None:
        async with _collection_run_lock:
            _active_collection_task_ids.discard(task_id)

    @staticmethod
    def _collect_external_link_funnel_stats(
        profiles: list[PlatformCandidateProfile],
        funnel: CollectionFunnelStats,
    ) -> None:
        type_order: list[str] = []
        seen_types: set[str] = set()
        external_link_count = 0
        commercial_link_count = 0
        social_only_link_count = 0
        missing_contact_or_landing_count = 0

        commercial_types = {
            "amazon_storefront",
            "shopmy",
            "ltk",
            "linktree",
            "beacons",
            "stan_store",
            "carrd",
            "website",
        }
        social_types = {"instagram", "tiktok", "facebook", "twitter", "linkedin"}

        for profile in profiles:
            links = list(profile.other_social_links or [])
            if not links:
                continue
            external_link_count += len(links)
            link_types = {
                str(link.get("type") or "").strip().lower()
                for link in links
                if isinstance(link, dict) and str(link.get("type") or "").strip()
            }
            for link_type in link_types:
                if link_type not in seen_types:
                    seen_types.add(link_type)
                    type_order.append(link_type)
            commercial_link_count += sum(1 for link_type in link_types if link_type in commercial_types)
            if link_types and link_types.issubset(social_types):
                social_only_link_count += 1

            item = profile_to_collected(profile)
            has_contact_or_landing = bool(
                item.final_email
                or item.email
                or item.website
                or item.contact_page
                or item.linktree_url
                or item.whatsapp
                or item.telegram
            )
            if not has_contact_or_landing:
                missing_contact_or_landing_count += 1

        funnel.external_link_count = external_link_count
        funnel.commercial_link_count = commercial_link_count
        funnel.social_only_link_count = social_only_link_count
        funnel.missing_contact_or_landing_count = missing_contact_or_landing_count
        funnel.external_link_types = type_order

    @staticmethod
    def _task_source_keyword(task: CollectionTask) -> str | None:
        keywords = task.keywords or []
        for kw in keywords:
            text = (kw or "").strip()
            if text:
                return text.lstrip("#")
        return None

    @staticmethod
    def _build_candidate_rows(
        task: CollectionTask,
        pipeline_result: InstagramPipelineResult,
        *,
        run_at: datetime,
        outcomes: dict[str, dict],
        filtered_below: int,
        filtered_excluded: int,
    ) -> list[dict]:
        del filtered_below, filtered_excluded
        platform = (task.platform or "instagram").strip().lower()
        source_keyword = CollectionRunnerService._task_source_keyword(task)
        failed_by_key = {
            (f.username or "").lower(): f for f in pipeline_result.failed_profiles
        }
        rows: list[dict] = []

        for dup in pipeline_result.discovery_duplicates:
            rows.append(
                TaskCandidateService.row_from_duplicate(
                    meta=dup,
                    username=dup.username,
                    profile_url=dup.profile_url,
                    platform=platform,
                    collection_mode=task.collection_mode,
                    source_keyword=source_keyword,
                    detail="发现阶段重复，未重复补采",
                )
            )

        for invalid in pipeline_result.early_invalid:
            meta = invalid.candidate
            key = meta.profile_url.lower()
            rows.append(
                TaskCandidateService.row_from_filtered(
                    username=meta.username,
                    profile_url=meta.profile_url,
                    failure_reason=invalid.failure_reason,
                    failure_detail=invalid.failure_detail,
                    platform=platform,
                    source_keyword=source_keyword,
                    source_hashtag=meta.source_hashtag,
                    source_post_url=meta.source_post_url,
                    source_caption=meta.source_caption,
                    source_comment_url=meta.source_comment_url,
                    source_comment_text=meta.source_comment_text,
                    source_discovery_type=meta.source_discovery_type,
                    source_type=meta_source_fields(meta, collection_mode=task.collection_mode).get(
                        "source_type"
                    ),
                    source_meta=meta.source_meta,
                )
            )

        for key, meta in pipeline_result.candidate_meta.items():
            failed = failed_by_key.get(key)
            if failed:
                rows.append(
                    TaskCandidateService.row_from_failed(
                        username=failed.username,
                        profile_url=failed.profile_url,
                        failure_reason=failed.reason.value,
                        failure_detail=failed.detail,
                        platform=platform,
                        source_hashtag=failed.source_hashtag or meta.source_hashtag,
                        source_keyword=source_keyword,
                        source_post_url=failed.source_post_url or meta.source_post_url,
                        source_caption=failed.source_caption or meta.source_caption,
                        source_comment_url=failed.source_comment_url or meta.source_comment_url,
                        source_comment_text=failed.source_comment_text or meta.source_comment_text,
                        source_discovery_type=failed.source_discovery_type or meta.source_discovery_type,
                        source_type=meta_source_fields(meta, collection_mode=task.collection_mode).get(
                            "source_type"
                        ),
                        source_meta=meta.source_meta,
                    )
                )
                continue

            outcome = outcomes.get(key)
            if outcome and outcome.get("status") == "filtered_out":
                item = outcome["item"]
                hard = outcome["hard"]
                quality = outcome.get("quality")
                failure_detail = (
                    quality.filter_detail
                    if quality and quality.filter_detail
                    else hard_filter_failure_detail(
                        hard.reason,
                        task=task,
                        followers_count=item.followers_count,
                        platform=platform,
                    )
                )
                row = TaskCandidateService.row_from_filtered(
                    username=item.username,
                    profile_url=item.profile_url,
                    failure_reason=hard.reason,
                    failure_detail=failure_detail,
                    platform=platform,
                    source_keyword=source_keyword,
                    source_hashtag=meta.source_hashtag,
                    source_post_url=meta.source_post_url or item.source_post_url,
                    source_caption=meta.source_caption,
                    source_comment_url=meta.source_comment_url or item.source_comment_url,
                    source_comment_text=meta.source_comment_text or item.source_comment_text,
                    source_discovery_type=meta.source_discovery_type or item.source_discovery_type,
                    source_type=meta_source_fields(meta, collection_mode=task.collection_mode).get(
                        "source_type"
                    ),
                    source_meta=meta.source_meta,
                    followers_count=item.followers_count,
                    engagement_rate=item.engagement_rate,
                    profile_fetched_at=run_at,
                )
                if quality:
                    row.update(assessment_row_fields(quality))
                rows.append(row)
                continue

            if outcome and outcome.get("status") == "not_inserted":
                item = outcome["item"]
                quality = outcome.get("quality")
                row = TaskCandidateService.row_from_not_inserted(
                    username=item.username,
                    profile_url=item.profile_url,
                    failure_reason=quality.filter_reason if quality else None,
                    failure_detail=quality.insert_blocked_reason if quality else None,
                    insert_blocked_reason=quality.insert_blocked_reason if quality else None,
                    platform=platform,
                    source_keyword=source_keyword,
                    source_hashtag=meta.source_hashtag,
                    source_post_url=meta.source_post_url or item.source_post_url,
                    source_caption=meta.source_caption,
                    source_comment_url=meta.source_comment_url or item.source_comment_url,
                    source_comment_text=meta.source_comment_text or item.source_comment_text,
                    source_discovery_type=meta.source_discovery_type or item.source_discovery_type,
                    source_type=meta_source_fields(meta, collection_mode=task.collection_mode).get(
                        "source_type"
                    ),
                    source_meta=meta.source_meta,
                    followers_count=item.followers_count,
                    engagement_rate=item.engagement_rate,
                    profile_fetched_at=run_at,
                )
                if quality:
                    row.update(assessment_row_fields(quality))
                rows.append(row)
                continue

            if outcome and outcome.get("status") == "duplicate":
                item = outcome.get("item")
                rows.append(
                    TaskCandidateService.row_from_duplicate(
                        meta=meta,
                        username=meta.username,
                        profile_url=meta.profile_url,
                        platform=platform,
                        collection_mode=task.collection_mode,
                        source_keyword=source_keyword,
                        followers_count=item.followers_count if item else None,
                        engagement_rate=item.engagement_rate if item else None,
                        profile_fetched_at=run_at,
                        detail=outcome.get("detail"),
                    )
                )
                continue

            if outcome and outcome.get("status") == "inserted":
                item = outcome["item"]
                quality = outcome.get("quality")
                row = TaskCandidateService.row_from_inserted(
                    meta=meta,
                    username=item.username,
                    profile_url=item.profile_url,
                    platform=platform,
                    collection_mode=task.collection_mode,
                    product_influencer_id=outcome.get("product_influencer_id"),
                    global_influencer_id=outcome.get("global_influencer_id"),
                    product_id=task.product_id,
                    user_id=task.user_id,
                    followers_count=item.followers_count,
                    engagement_rate=item.engagement_rate,
                    profile_fetched_at=run_at,
                    source_keyword=source_keyword,
                )
                if quality:
                    row.update(assessment_row_fields(quality))
                rows.append(row)
                continue

            rows.append(
                TaskCandidateService.row_from_discovered(
                    meta=meta,
                    platform=platform,
                    collection_mode=task.collection_mode,
                    source_keyword=source_keyword,
                )
            )

        return rows

    @staticmethod
    def _build_platform_candidate_rows(
        task: CollectionTask,
        profiles: list[PlatformCandidateProfile],
        outcomes: dict[tuple[str, str], dict],
        *,
        run_at: datetime,
    ) -> list[dict]:
        source_keyword = CollectionRunnerService._task_source_keyword(task)
        rows: list[dict] = []
        seen_profile_keys: set[tuple[str, str]] = set()
        for profile in profiles:
            key = profile_identity_key(profile)
            if key in seen_profile_keys:
                continue
            seen_profile_keys.add(key)
            outcome = outcomes.get(key)
            keyword = (profile.source_meta or {}).get("source_keyword") or source_keyword
            if not outcome:
                rows.append(
                    candidate_row_from_profile(
                        profile,
                        status=CandidateStatus.DISCOVERED.value,
                        collection_mode=task.collection_mode,
                        source_keyword=keyword,
                    )
                )
                continue

            status = outcome.get("status")
            item = outcome.get("item")
            if status == "filtered_out":
                hard = outcome["hard"]
                quality = outcome.get("quality")
                failure_detail = (
                    quality.filter_detail
                    if quality and quality.filter_detail
                    else hard_filter_failure_detail(
                        hard.reason,
                        task=task,
                        followers_count=getattr(item, "followers_count", None),
                        platform=profile.platform,
                    )
                )
                row = candidate_row_from_profile(
                    profile,
                    status=CandidateStatus.FILTERED_OUT.value,
                    collection_mode=task.collection_mode,
                    source_keyword=keyword,
                    failure_reason=hard.reason,
                    failure_detail=failure_detail,
                    followers_count=getattr(item, "followers_count", None),
                    engagement_rate=getattr(item, "engagement_rate", None),
                )
                if quality:
                    row.update(assessment_row_fields(quality))
                rows.append(row)
                continue

            if status == "not_inserted":
                quality = outcome.get("quality")
                row = candidate_row_from_profile(
                    profile,
                    status=CandidateStatus.NOT_INSERTED.value,
                    collection_mode=task.collection_mode,
                    source_keyword=keyword,
                    failure_reason=quality.filter_reason if quality else None,
                    failure_detail=quality.insert_blocked_reason if quality else None,
                    insert_blocked_reason=quality.insert_blocked_reason if quality else None,
                    followers_count=getattr(item, "followers_count", None) if item else None,
                    engagement_rate=getattr(item, "engagement_rate", None) if item else None,
                )
                if quality:
                    row.update(assessment_row_fields(quality))
                rows.append(row)
                continue

            if status == "duplicate":
                rows.append(
                    candidate_row_from_profile(
                        profile,
                        status=CandidateStatus.DUPLICATE.value,
                        collection_mode=task.collection_mode,
                        source_keyword=keyword,
                        failure_reason="duplicate",
                        failure_detail=outcome.get("detail"),
                        product_influencer_id=outcome.get("product_influencer_id"),
                        global_influencer_id=outcome.get("global_influencer_id"),
                        product_id=task.product_id,
                        user_id=task.user_id,
                        followers_count=getattr(item, "followers_count", None) if item else None,
                        engagement_rate=getattr(item, "engagement_rate", None) if item else None,
                    )
                )
                continue

            if status == "inserted":
                quality = outcome.get("quality")
                row = candidate_row_from_profile(
                    profile,
                    status=CandidateStatus.INSERTED.value,
                    collection_mode=task.collection_mode,
                    source_keyword=keyword,
                    product_influencer_id=outcome.get("product_influencer_id"),
                    global_influencer_id=outcome.get("global_influencer_id"),
                    product_id=task.product_id,
                    user_id=task.user_id,
                    followers_count=getattr(item, "followers_count", None) if item else None,
                    engagement_rate=getattr(item, "engagement_rate", None) if item else None,
                )
                if quality:
                    row.update(assessment_row_fields(quality))
                rows.append(row)
                continue

            rows.append(
                candidate_row_from_profile(
                    profile,
                    status=CandidateStatus.DISCOVERED.value,
                    collection_mode=task.collection_mode,
                    source_keyword=keyword,
                )
            )
        return rows

    @staticmethod
    def _normalize_item_urls(data: CollectedInfluencer) -> None:
        from app.services.instagram_urls import sanitize_url_text

        platform = (data.platform or "").strip().lower()
        if platform == "instagram":
            profile = normalize_instagram_profile_url(data.profile_url, username=data.username)
            if profile:
                data.profile_url = profile
        else:
            data.profile_url = sanitize_url_text(data.profile_url) or data.profile_url

        if platform == "youtube":
            uid = resolve_platform_unique_id(
                data.platform,
                data.profile_url,
                platform_unique_id=data.platform_unique_id,
            )
            if uid:
                data.platform_unique_id = uid

        if data.source_post_url:
            if platform == "instagram":
                post = normalize_instagram_post_url(data.source_post_url)
                if post:
                    data.source_post_url = post
            else:
                data.source_post_url = sanitize_url_text(data.source_post_url) or data.source_post_url

        if data.source_comment_url:
            if platform == "instagram":
                comment = normalize_instagram_post_url(data.source_comment_url)
                if comment:
                    data.source_comment_url = comment
                else:
                    cleaned = sanitize_url_text(data.source_comment_url)
                    data.source_comment_url = cleaned or None
            else:
                cleaned = sanitize_url_text(data.source_comment_url)
                data.source_comment_url = cleaned or None

        if data.recent_post_urls:
            normalized_recent: list[str] = []
            for url in data.recent_post_urls:
                if platform == "instagram":
                    post = normalize_instagram_post_url(url)
                    if post:
                        normalized_recent.append(post)
                else:
                    cleaned = sanitize_url_text(url)
                    if cleaned:
                        normalized_recent.append(cleaned)
            data.recent_post_urls = normalized_recent

    @staticmethod
    def _apply_collected_data(
        influencer: Influencer,
        data: CollectedInfluencer,
        task: CollectionTask | None,
        run_at: datetime,
    ) -> None:
        CollectionRunnerService._normalize_item_urls(data)
        apply_creator_quality(data, task)
        score = data.score if data.score is not None else calculate_score(data, task)
        risk_level = data.risk_level or calculate_risk_level(score)

        influencer.profile_url = data.profile_url
        if data.platform_unique_id:
            influencer.platform_unique_id = data.platform_unique_id
        influencer.username = data.username
        influencer.display_name = data.display_name
        influencer.avatar_url = data.avatar_url
        influencer.country = data.country
        influencer.language = data.language
        influencer.category = data.category
        influencer.niche = data.niche
        influencer.bio = data.bio
        influencer.followers_count = data.followers_count
        influencer.avg_views = data.avg_views
        influencer.avg_likes = data.avg_likes
        influencer.avg_comments = data.avg_comments
        influencer.engagement_rate = data.engagement_rate
        influencer.email = data.final_email or data.email
        influencer.final_email = data.final_email or data.email
        influencer.public_email = data.public_email
        influencer.business_email = data.business_email
        influencer.email_source = data.email_source
        influencer.contact_credibility = data.contact_credibility
        influencer.contact_score = data.contact_score
        influencer.contact_credibility_level = getattr(data, "contact_credibility_level", None)
        influencer.website = data.website
        influencer.contact_page = data.contact_page
        influencer.linktree_url = data.linktree_url
        influencer.whatsapp = data.whatsapp
        influencer.telegram = data.telegram
        influencer.other_social_links = data.other_social_links or []
        influencer.contact_discovered_at = getattr(data, "contact_discovered_at", None)
        influencer.contact_sources = getattr(data, "contact_sources", None) or []
        influencer.contact_fetch_status = getattr(data, "contact_fetch_status", None)
        influencer.contact_fetch_error = getattr(data, "contact_fetch_error", None)
        influencer.product_fit = data.product_fit
        influencer.data_completeness = data.data_completeness
        influencer.has_brand_collaboration = data.has_brand_collaboration
        influencer.estimated_collab_price = data.estimated_collab_price
        influencer.collaboration_formats = data.collaboration_formats or []
        influencer.content_topics = data.content_topics or []
        influencer.audience_country = data.audience_country
        influencer.audience_language = data.audience_language
        influencer.travel_fit_score = data.travel_fit_score
        influencer.purchasing_power_score = data.purchasing_power_score
        influencer.sales_potential_score = data.sales_potential_score
        influencer.audience_match_score = data.audience_match_score
        influencer.roi_forecast = data.roi_forecast
        influencer.recent_post_titles = data.recent_post_titles or []
        influencer.recent_post_urls = data.recent_post_urls or []
        influencer.last_post_at = data.last_post_at
        influencer.posting_frequency = data.posting_frequency
        influencer.tags = data.tags
        influencer.engagement_score = data.engagement_score
        influencer.content_match_score = data.content_match_score
        influencer.contactability_score = data.contactability_score
        influencer.commercial_signal_score = data.commercial_signal_score
        influencer.activity_score = data.activity_score
        influencer.risk_score = data.risk_score
        influencer.final_priority = data.final_priority
        influencer.score = score
        influencer.risk_level = risk_level
        influencer.last_collected_at = run_at
        if data.source_discovery_type:
            influencer.source_discovery_type = data.source_discovery_type
        if data.source_post_url:
            influencer.source_post_url = data.source_post_url
        if data.source_comment_url:
            influencer.source_comment_url = data.source_comment_url
        if data.source_comment_text:
            influencer.source_comment_text = data.source_comment_text

    @staticmethod
    def _has_changes(existing: Influencer, data: CollectedInfluencer, task: CollectionTask | None) -> bool:
        score = calculate_score(data, task)
        risk_level = calculate_risk_level(score)

        comparisons = {
            "username": data.username,
            "display_name": data.display_name,
            "bio": data.bio,
            "followers_count": data.followers_count,
            "engagement_rate": data.engagement_rate,
            "email": data.email,
            "final_email": data.final_email,
            "website": data.website,
            "contact_page": data.contact_page,
            "linktree_url": data.linktree_url,
            "whatsapp": data.whatsapp,
            "telegram": data.telegram,
            "contact_fetch_status": getattr(data, "contact_fetch_status", None),
            "product_fit": data.product_fit,
            "travel_fit_score": data.travel_fit_score,
            "purchasing_power_score": data.purchasing_power_score,
            "sales_potential_score": data.sales_potential_score,
            "audience_match_score": data.audience_match_score,
            "roi_forecast": data.roi_forecast,
            "score": score,
            "risk_level": risk_level,
        }
        for field, new_value in comparisons.items():
            if getattr(existing, field) != new_value:
                return True
        if (existing.other_social_links or []) != (data.other_social_links or []):
            return True
        return False

    @staticmethod
    async def _find_existing_batch(
        db: AsyncSession,
        items: list,
    ) -> dict[tuple[str, str], Influencer]:
        if not items:
            return {}

        result_map: dict[tuple[str, str], Influencer] = {}

        youtube_ids = {
            item.platform_unique_id
            for item in items
            if getattr(item, "platform", None) == "youtube" and getattr(item, "platform_unique_id", None)
        }
        if youtube_ids:
            rows = await db.execute(
                select(Influencer).where(
                    Influencer.platform == "youtube",
                    Influencer.platform_unique_id.in_(youtube_ids),
                )
            )
            for row in rows.scalars():
                key = platform_identity_key(
                    row.platform,
                    row.profile_url,
                    platform_unique_id=row.platform_unique_id,
                )
                result_map[key] = row

        platforms = {item.platform for item in items}
        urls = {item.profile_url for item in items}
        result = await db.execute(
            select(Influencer).where(
                Influencer.platform.in_(platforms),
                Influencer.profile_url.in_(urls),
            )
        )
        for row in result.scalars():
            key = platform_identity_key(
                row.platform,
                row.profile_url,
                platform_unique_id=row.platform_unique_id,
            )
            if key not in result_map:
                result_map[key] = row

        return result_map

    @staticmethod
    def _progress_summary(
        *,
        processed: int,
        total: int,
        success: int,
        skipped: int,
        failed: int,
        stage: str = "入库",
    ) -> str:
        return (
            f"{stage}中… 已处理 {processed}/{total}，"
            f"成功 {success}，跳过 {skipped}，失败 {failed}"
        )

    @staticmethod
    async def _touch_task_progress(
        db: AsyncSession,
        task: CollectionTask,
        *,
        processed: int,
        total: int,
        success: int,
        skipped: int,
        failed: int,
        stage: str = "入库",
        funnel: CollectionFunnelStats | None = None,
    ) -> None:
        task.status_summary = CollectionRunnerService._progress_summary(
            processed=processed,
            total=total,
            success=success,
            skipped=skipped,
            failed=failed,
            stage=stage,
        )
        task.inserted_count = success
        task.result_count = success
        if funnel:
            task.discovered_count = funnel.discovered_count
            task.deduped_count = funnel.deduped_count
            task.profile_fetched_count = funnel.profile_fetched_count
            task.profile_failed_count = funnel.profile_failed_count
            task.filtered_out_count = funnel.filtered_out_count
        await db.commit()

    @staticmethod
    async def _find_existing(
        db: AsyncSession,
        platform: str,
        profile_url: str,
    ) -> Influencer | None:
        result = await db.execute(
            select(Influencer).where(
                Influencer.platform == platform,
                Influencer.profile_url == profile_url,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _apply_analysis_to_influencer(influencer: Influencer, analysis) -> None:
        influencer.ai_summary = analysis.ai_summary or None
        influencer.ai_collaboration_suggestion = analysis.ai_collaboration_suggestion or None
        influencer.ai_outreach_message = analysis.ai_outreach_message or None
        influencer.tags = analysis.tags
        influencer.risk_level = analysis.risk_level
        influencer.score_reason = analysis.score_reason
        influencer.product_fit = analysis.product_fit
        influencer.travel_fit_score = analysis.travel_fit_score
        influencer.purchasing_power_score = analysis.purchasing_power_score
        influencer.sales_potential_score = analysis.sales_potential_score
        influencer.audience_match_score = analysis.audience_match_score
        influencer.roi_forecast = analysis.roi_forecast
        composite = calculate_composite_score_from_metrics(
            product_fit=influencer.product_fit,
            travel_fit_score=influencer.travel_fit_score,
            purchasing_power_score=influencer.purchasing_power_score,
            sales_potential_score=influencer.sales_potential_score,
            audience_match_score=influencer.audience_match_score,
            engagement_rate=influencer.engagement_rate,
            email=influencer.final_email or influencer.email,
        )
        if composite is not None:
            influencer.score = composite
            influencer.risk_level = calculate_risk_level(composite)

    @staticmethod
    async def _analyze_collected_influencers(
        db: AsyncSession,
        influencers: list[Influencer],
    ) -> None:
        pending = [
            influencer
            for influencer in influencers
            if not (
                getattr(influencer, "ai_summary", None)
                and getattr(influencer, "score_reason", None)
            )
        ]
        if not pending:
            return

        async def _analyze_one(influencer: Influencer) -> None:
            try:
                analysis = await analyze_influencer(influencer)
                CollectionRunnerService._apply_analysis_to_influencer(influencer, analysis)
            except Exception as exc:
                logger.warning(
                    "AI analyze failed for influencer %s, skip AI fields: %s",
                    influencer.username,
                    exc,
                )

        outcomes = await map_bounded(
            pending,
            _analyze_one,
            concurrency=settings.collection_ai_concurrency,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                logger.warning("AI analyze worker failed: %s", outcome)
        await db.commit()

    @staticmethod
    async def _analyze_collected_product_influencers(
        db: AsyncSession,
        pairs: list[tuple[ProductInfluencer, "GlobalInfluencerProfile"]],
    ) -> None:
        from app.models.global_influencer_profile import GlobalInfluencerProfile
        from app.services.influencer_projection import apply_ai_to_product_record, merged_influencer_for_ai

        pending = [
            (product_row, global_row)
            for product_row, global_row in pairs
            if not (product_row.ai_summary and product_row.score_reason)
        ]
        if not pending:
            return

        async def _analyze_one(product_row: ProductInfluencer, global_row: GlobalInfluencerProfile) -> None:
            try:
                merged = merged_influencer_for_ai(product_row, global_row)
                analysis = await analyze_influencer(merged)
                apply_ai_to_product_record(product_row, analysis, global_row=global_row)
            except Exception as exc:
                logger.warning(
                    "AI analyze failed for product influencer %s, skip AI fields: %s",
                    global_row.username,
                    exc,
                )

        outcomes = await map_bounded(
            pending,
            lambda pair: _analyze_one(pair[0], pair[1]),
            concurrency=settings.collection_ai_concurrency,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                logger.warning("AI analyze worker failed: %s", outcome)
        await db.commit()

    @staticmethod
    def schedule_influencer_ai_analysis(task_id: int, influencer_ids: list[int]) -> None:
        ids = [item for item in influencer_ids if item]
        if not ids:
            return
        asyncio.create_task(CollectionRunnerService._run_ai_analysis_job(task_id, ids))

    @staticmethod
    async def _run_ai_analysis_job(task_id: int, influencer_ids: list[int]) -> None:
        batch_size = max(1, settings.collection_ai_concurrency * 5)
        try:
            async with async_session_factory() as db:
                task = await db.get(CollectionTask, task_id)
                if not task:
                    return
                await update_task_progress(
                    db,
                    task,
                    stage=STAGE_AI_PROCESSING,
                    commit=True,
                )
                for offset in range(0, len(influencer_ids), batch_size):
                    chunk = influencer_ids[offset : offset + batch_size]
                    from app.models.global_influencer_profile import GlobalInfluencerProfile

                    rows = await db.execute(
                        select(ProductInfluencer, GlobalInfluencerProfile)
                        .join(
                            GlobalInfluencerProfile,
                            ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id,
                        )
                        .where(ProductInfluencer.id.in_(chunk))
                    )
                    pairs = list(rows.all())
                    if pairs:
                        await CollectionRunnerService._analyze_collected_product_influencers(db, pairs)
                await update_task_progress(
                    db,
                    task,
                    stage=STAGE_AI_COMPLETED,
                    last_error=None,
                    commit=True,
                )
                if task.status_summary and "AI 评分处理中" in task.status_summary:
                    task.status_summary = task.status_summary.replace("；AI 评分处理中", "").replace(
                        "AI 评分处理中", "AI 评分已完成"
                    )
                    if "AI 评分已完成" not in (task.status_summary or ""):
                        task.status_summary = f"{task.status_summary}；AI 评分已完成"
                    await db.commit()
        except Exception as exc:
            logger.exception("Background AI analysis job failed: %s", exc)
            try:
                async with async_session_factory() as db:
                    task = await db.get(CollectionTask, task_id)
                    if task:
                        await update_task_progress(
                            db,
                            task,
                            stage=STAGE_FAILED,
                            last_error=str(exc),
                            commit=True,
                        )
            except Exception:
                logger.exception("Failed to persist AI job failure for task %s", task_id)

    @staticmethod
    async def run_task(
        db: AsyncSession,
        task: CollectionTask,
        *,
        allow_running: bool = False,
        resume: bool = False,
    ) -> dict[str, int]:
        if task.status == CollectionTaskStatus.RUNNING.value and not allow_running:
            raise ValueError("Task is already running")

        await CollectionRunnerService._claim_collection_run(task.id)

        task.status = CollectionTaskStatus.RUNNING.value
        clear_task_error_fields(task)
        if not resume:
            task.status_summary = None
            reset_run_progress(task)
        checkpoint = RunCheckpoint.from_task(task)
        await db.commit()
        await db.refresh(task)

        new_count = 0
        updated_count = 0
        skipped_count = 0
        filtered_count = 0
        preference_mismatch_count = 0
        seen_keys: set[tuple[str, str]] = set()
        touched_influencers: list[ProductInfluencer] = []
        candidate_rows: list[dict] = []
        outcomes: dict[str, dict] = {}
        platform_outcomes: dict[tuple[str, str], dict] = {}
        filtered_below_min = 0
        filtered_excluded = 0

        try:
            if task.collection_mode == CollectionMode.LINK_IMPORT.value:
                return await LinkImportService.run_collection_task(db, task)

            if task.collection_mode == CollectionMode.LINK_SEED_DISCOVERY.value:
                from app.services.shopping_seed_runner import ShoppingSeedDiscoveryService

                return await ShoppingSeedDiscoveryService.run_collection_task(db, task)

            apply_category_discovery_expansion(task)
            run_at = datetime.now(UTC)
            platforms = task_platforms(task)
            discovery_platforms, keyword_seed_platforms = _split_keyword_seed_platforms(task, platforms)
            instagram_only = discovery_platforms == ["instagram"] and not keyword_seed_platforms
            non_instagram = [p for p in discovery_platforms if p != "instagram"]
            qualified_target = target_qualified_count(task)
            max_candidates = max_candidates_to_process(task)
            run_ctx = CollectionRunContext(
                target_qualified_count=qualified_target,
                max_candidates=max_candidates,
                fetch_limit=discovery_fetch_limit(task, round_index=0),
            )
            run_ctx_token = set_run_context(run_ctx)
            overfetch_stop_reason: str | None = None
            total_candidates_seen = 0
            discovery_reporter: DiscoveryProgressReporter | None = None
            discovery_reporter_token = None

            pipeline_result = None
            collected: list = []
            collection_errors: list[str] = []
            stats = CollectionFunnelStats()
            platform_results = []
            competitor_timed_out = False

            async def _run_instagram_pipeline():
                return await run_instagram_pipeline_with_provider_check(task, db=db, checkpoint=checkpoint)

            async def _run_non_instagram_discovery():
                return await discover_non_instagram_platforms(
                    task,
                    non_instagram,
                    checkpoint=checkpoint,
                )

            if "instagram" in discovery_platforms and non_instagram:
                discovery_reporter = DiscoveryProgressReporter(db, task, checkpoint, qualified_target)
                discovery_reporter_token = set_discovery_reporter(discovery_reporter)
                discovery_tasks: list[asyncio.Task] = [
                    asyncio.create_task(_run_instagram_pipeline()),
                    asyncio.create_task(_run_non_instagram_discovery()),
                ]
                if task.collection_mode == CollectionMode.COMPETITOR_PRODUCT.value:
                    total_timeout = max(60, settings.competitor_product_task_timeout_seconds)
                    done, pending = await asyncio.wait(discovery_tasks, timeout=total_timeout)
                    for pending_task in pending:
                        pending_task.cancel()
                        competitor_timed_out = True
                    ig_task = discovery_tasks[0]
                    plat_task = discovery_tasks[1]
                    if ig_task in done:
                        try:
                            pipeline_result = ig_task.result()
                        except Exception as exc:
                            collection_errors.append(str(exc))
                    if plat_task in done:
                        try:
                            platform_results = plat_task.result()
                        except Exception as exc:
                            collection_errors.append(str(exc))
                    if competitor_timed_out:
                        collection_errors.append(
                            "已达到任务最大耗时，部分平台/API 响应慢，已结束本轮采集"
                        )
                        checkpoint_extra = dict(task.run_checkpoint or {})
                        checkpoint_extra["competitor_discovery_timed_out"] = True
                        task.run_checkpoint = checkpoint_extra
                    if pipeline_result is not None:
                        collected = list(pipeline_result.items)
                        collection_errors.extend(pipeline_result.errors)
                        stats = pipeline_result.stats
                else:
                    pipeline_result, platform_results = await asyncio.gather(
                        _run_instagram_pipeline(),
                        _run_non_instagram_discovery(),
                    )
                    collected = list(pipeline_result.items)
                    collection_errors = list(pipeline_result.errors)
                    stats = pipeline_result.stats
            else:
                if "instagram" in discovery_platforms:
                    pipeline_result = await run_instagram_pipeline_with_provider_check(
                        task,
                        db=db,
                        checkpoint=checkpoint,
                    )
                    collected = list(pipeline_result.items)
                    collection_errors = list(pipeline_result.errors)
                    stats = pipeline_result.stats

                if non_instagram:
                    discovery_reporter = DiscoveryProgressReporter(db, task, checkpoint, qualified_target)
                    discovery_reporter_token = set_discovery_reporter(discovery_reporter)
                    if task.collection_mode == CollectionMode.COMPETITOR_PRODUCT.value:
                        total_timeout = max(60, settings.competitor_product_task_timeout_seconds)
                        plat_task = asyncio.create_task(_run_non_instagram_discovery())
                        done, pending = await asyncio.wait([plat_task], timeout=total_timeout)
                        for pending_task in pending:
                            pending_task.cancel()
                            competitor_timed_out = True
                        if plat_task in done:
                            try:
                                platform_results = plat_task.result()
                            except Exception as exc:
                                collection_errors.append(str(exc))
                        if competitor_timed_out:
                            collection_errors.append(
                                "已达到任务最大耗时，部分平台/API 响应慢，已结束本轮采集"
                            )
                            checkpoint_extra = dict(task.run_checkpoint or {})
                            checkpoint_extra["competitor_discovery_timed_out"] = True
                            task.run_checkpoint = checkpoint_extra
                    else:
                        platform_results = await _run_non_instagram_discovery()

            if task.collection_mode == CollectionMode.COMPETITOR_PRODUCT.value and platform_results:
                from app.services.competitor_product_discovery import discover_instagram_from_cross_platform_evidence

                existing_ig_usernames = {
                    (getattr(item, "username", "") or "").strip().lower()
                    for item in collected
                    if getattr(item, "platform", None) == "instagram"
                }
                instagram_probe_result = await discover_instagram_from_cross_platform_evidence(
                    task,
                    platform_results,
                    existing_usernames=existing_ig_usernames,
                )
                if instagram_probe_result is not None:
                    platform_results.append(instagram_probe_result)

            aggregate = merge_platform_results(
                instagram_result=pipeline_result,
                instagram_funnel=stats if pipeline_result else None,
                instagram_errors=collection_errors,
                instagram_candidate_rows=[],
                instagram_collected=collected,
                platform_results=platform_results,
            )
            _annotate_instagram_failure_in_aggregate(aggregate, pipeline_result)
            collected = dedupe_collected_items(aggregate.collected_items)
            collection_errors = aggregate.collection_errors
            total_count = len(collected)
            stats = aggregate.funnel
            total_candidates_seen += total_count

            keyword_seed_result = None
            if keyword_seed_platforms:
                from app.services.shopping_seed_runner import ShoppingSeedDiscoveryService

                keyword_seed_result = await ShoppingSeedDiscoveryService.run_keyword_seed_discovery(
                    db,
                    task,
                    run_at=run_at,
                )
                seed_exec = keyword_seed_result.exec_result
                collection_errors.extend(seed_exec.import_errors)

            funnel = CollectionFunnelStats(
                discovered_count=stats.discovered_count
                + (keyword_seed_result.discovered_count if keyword_seed_result else 0),
                deduped_count=stats.deduped_count
                + (keyword_seed_result.discovered_count if keyword_seed_result else 0),
                profile_fetched_count=stats.profile_fetched_count
                + (keyword_seed_result.exec_result.hydrated_profile_count if keyword_seed_result else 0),
                profile_failed_count=stats.profile_failed_count
                + (keyword_seed_result.exec_result.import_failed if keyword_seed_result else 0),
                filtered_out_count=(keyword_seed_result.exec_result.filtered_out_count if keyword_seed_result else 0),
                inserted_count=(
                    keyword_seed_result.exec_result.new_count + keyword_seed_result.exec_result.updated_count
                    if keyword_seed_result
                    else 0
                ),
                preference_mismatch_count=0,
                hashtag_count=getattr(stats, "hashtag_count", 0),
                post_count=getattr(stats, "post_count", 0),
                comment_author_count=getattr(stats, "comment_author_count", 0),
                filtered_below_min_followers_count=0,
                filtered_excluded_keyword_count=0,
                target_qualified_count=qualified_target,
            )
            target_reached = False

            if discovery_reporter:
                await discovery_reporter.update(
                    phase=STAGE_DISCOVERY,
                    discovered_count=funnel.discovered_count,
                    deduped_count=funnel.deduped_count,
                    profile_fetched_count=funnel.profile_fetched_count,
                    inserted_count=0,
                    rate_limited=any(
                        "429" in err or "限流" in err for err in collection_errors
                    ),
                )

            if non_instagram and qualified_target > 0:
                seen_profile_keys = {collected_identity_key(item) for item in collected}
                if not collected:
                    overfetch_stop_reason = "平台无更多结果"
                for round_idx in range(1, max_overfetch_rounds_for_task(task)):
                    if overfetch_stop_reason:
                        break
                    if len(collected) >= max_candidates:
                        overfetch_stop_reason = "已达安全上限"
                        break
                    run_ctx.round_index = round_idx
                    run_ctx.fetch_limit = discovery_fetch_limit(task, round_index=round_idx)
                    extra_results = await discover_non_instagram_platforms(
                        task,
                        non_instagram,
                        checkpoint=checkpoint,
                    )
                    if any(getattr(result, "rate_limited", False) for result in extra_results):
                        overfetch_stop_reason = RATE_LIMIT_STOP_REASON
                    new_items = []
                    for result in extra_results:
                        for item in getattr(result, "items", None) or []:
                            pk = collected_identity_key(item)
                            if pk in seen_profile_keys:
                                continue
                            seen_profile_keys.add(pk)
                            new_items.append(item)
                        extra_profiles = getattr(result, "profiles", None) or []
                        if extra_profiles:
                            aggregate.platform_profiles.extend(extra_profiles)
                    empty_round_reason = should_stop_overfetch_round(new_unique_count=len(new_items))
                    if overfetch_stop_reason == RATE_LIMIT_STOP_REASON and not new_items:
                        break
                    if empty_round_reason:
                        if not overfetch_stop_reason:
                            overfetch_stop_reason = empty_round_reason
                        break
                    collected.extend(new_items)
                    funnel.discovered_count += len(new_items)
                    total_candidates_seen += len(new_items)
                    if discovery_reporter:
                        await discovery_reporter.update(
                            phase=STAGE_DISCOVERY,
                            discovered_count=funnel.discovered_count,
                            deduped_count=len(collected),
                            profile_fetched_count=funnel.profile_fetched_count,
                            rate_limited=overfetch_stop_reason == RATE_LIMIT_STOP_REASON,
                            rate_limit_note=RATE_LIMIT_STOP_REASON if overfetch_stop_reason == RATE_LIMIT_STOP_REASON else None,
                        )
                    if overfetch_stop_reason == RATE_LIMIT_STOP_REASON:
                        break
                total_count = len(collected)

            if discovery_reporter_token is not None:
                reset_discovery_reporter(discovery_reporter_token)
                discovery_reporter_token = None

            if aggregate.platform_profiles:
                enriched_items = await enrich_profiles_with_instagram_email(aggregate.platform_profiles)
                enriched_by_key = {collected_identity_key(item): item for item in enriched_items}
                collected = [
                    enriched_by_key.get(collected_identity_key(item), item)
                    for item in collected
                ]

            await update_task_progress(
                db,
                task,
                stage=STAGE_PERSIST,
                processed=checkpoint.persisted_profiles and len(checkpoint.persisted_profiles) or 0,
                total=total_count,
                success=task.success_count or 0,
                skipped=task.skipped_count or 0,
                failed=task.failed_count or 0,
                checkpoint=checkpoint,
                commit=True,
            )

            product_id = task.product_id or 1
            global_map = await InfluencerPersistenceService.find_global_profiles_batch(db, collected)
            product_map = await InfluencerPersistenceService.find_product_influencers_batch(
                db, product_id, collected, global_map=global_map
            )
            processed_count = len(checkpoint.persisted_profiles)
            batch_commit_size = max(1, settings.collection_batch_commit_size)
            persist_failed_count = 0
            if resume:
                skipped_count = task.skipped_count or 0
                filtered_count = task.failed_count or 0
                new_count = 0
                updated_count = task.success_count or 0

            for item in collected:
                if target_reached:
                    break
                try:
                    if checkpoint.persisted_done(
                        item.platform,
                        item.profile_url,
                        platform_unique_id=item.platform_unique_id,
                    ):
                        if resume:
                            identity_key = identity_key_for_item(item)
                            product_record = product_map.get(identity_key)
                            global_profile = global_map.get(identity_key)
                            if product_record and product_record.is_inserted:
                                user_key = (item.username or "").lower()
                                profile_key = collected_identity_key(item)
                                assessment = evaluate_high_value_assessment(item, task)
                                outcome = {
                                    "status": "inserted",
                                    "item": item,
                                    "product_influencer_id": product_record.id,
                                    "global_influencer_id": (
                                        global_profile.id
                                        if global_profile
                                        else product_record.global_influencer_id
                                    ),
                                    "quality": assessment,
                                }
                                platform_outcomes[profile_key] = outcome
                                if item.platform == "instagram":
                                    outcomes[user_key] = outcome
                        continue

                    hard = evaluate_post_hydration_hard_filter(item, task)
                    user_key = (item.username or "").lower()
                    profile_key = collected_identity_key(item)
                    if not hard.passed:
                        filtered_count += 1
                        if hard.reason == "below_min_followers":
                            filtered_below_min += 1
                        elif hard.reason and hard.reason.startswith("excluded_keyword:"):
                            filtered_excluded += 1
                        outcome = {
                            "status": "filtered_out",
                            "item": item,
                            "hard": hard,
                        }
                        platform_outcomes[profile_key] = outcome
                        if item.platform == "instagram":
                            outcomes[user_key] = outcome
                        checkpoint.mark_persisted(
                            item.platform,
                            item.profile_url,
                            platform_unique_id=item.platform_unique_id,
                        )
                        continue

                    assessment = evaluate_high_value_assessment(item, task)
                    if should_strict_filter_out(task, assessment):
                        filtered_count += 1
                        if assessment.filter_reason == "below_min_followers":
                            filtered_below_min += 1
                        outcome = {
                            "status": "filtered_out",
                            "item": item,
                            "hard": PostHydrationHardFilterResult(False, assessment.filter_reason),
                            "quality": assessment,
                        }
                        platform_outcomes[profile_key] = outcome
                        if item.platform == "instagram":
                            outcomes[user_key] = outcome
                        checkpoint.mark_persisted(
                            item.platform,
                            item.profile_url,
                            platform_unique_id=item.platform_unique_id,
                        )
                        continue

                    if should_skip_insert(task, assessment):
                        skipped_count += 1
                        outcome = {
                            "status": "not_inserted",
                            "item": item,
                            "quality": assessment,
                        }
                        platform_outcomes[profile_key] = outcome
                        if item.platform == "instagram":
                            outcomes[user_key] = outcome
                        checkpoint.mark_persisted(
                            item.platform,
                            item.profile_url,
                            platform_unique_id=item.platform_unique_id,
                        )
                        continue

                    if not assessment.is_high_value:
                        preference_mismatch_count += 1
                        mismatch = list(assessment.mismatch_codes) or get_quality_preference_mismatch_reasons(
                            item, task
                        )
                        logger.debug(
                            "Quality preference mismatch @%s: %s",
                            item.username,
                            ",".join(mismatch),
                        )

                    key = collected_identity_key(item)
                    if key in seen_keys:
                        skipped_count += 1
                        outcome = {
                            "status": "duplicate",
                            "item": item,
                            "detail": "本次任务内重复主页，已跳过",
                        }
                        platform_outcomes[profile_key] = outcome
                        if item.platform == "instagram":
                            outcomes[user_key] = outcome
                        checkpoint.mark_persisted(
                            item.platform,
                            item.profile_url,
                            platform_unique_id=item.platform_unique_id,
                        )
                        continue
                    seen_keys.add(key)

                    identity_key = identity_key_for_item(item)
                    global_profile = global_map.get(identity_key)
                    product_record = product_map.get(identity_key)

                    if product_record:
                        if not product_record_has_changes(product_record, item, task):
                            await InfluencerSourceService.record_from_collected(
                                db, product_record, item, task=task, run_at=run_at
                            )
                            skipped_count += 1
                            outcome = {
                                "status": "duplicate",
                                "item": item,
                                "detail": "当前产品下已存在且业务数据无变化，未重复写入",
                                "product_influencer_id": product_record.id,
                                "global_influencer_id": global_profile.id if global_profile else None,
                            }
                            platform_outcomes[profile_key] = outcome
                            if item.platform == "instagram":
                                outcomes[user_key] = outcome
                            checkpoint.mark_persisted(
                                item.platform,
                                item.profile_url,
                                platform_unique_id=item.platform_unique_id,
                            )
                            continue
                        if global_profile and (
                            should_refresh_global_profile(global_profile, now=run_at)
                            or global_profile_has_changes(global_profile, item)
                        ):
                            apply_global_profile_data(global_profile, item, run_at=run_at)
                        apply_product_influencer_data(product_record, item, task, run_at=run_at)
                        await InfluencerSourceService.record_from_collected(
                            db, product_record, item, task=task, run_at=run_at
                        )
                        touched_influencers.append(product_record)
                        updated_count += 1
                        outcome = {
                            "status": "inserted",
                            "item": item,
                            "product_influencer_id": product_record.id,
                            "global_influencer_id": global_profile.id if global_profile else None,
                            "quality": assessment,
                        }
                        platform_outcomes[profile_key] = outcome
                        if item.platform == "instagram":
                            outcomes[user_key] = outcome
                        checkpoint.mark_persisted(
                            item.platform,
                            item.profile_url,
                            platform_unique_id=item.platform_unique_id,
                        )
                        if (new_count + updated_count) >= qualified_target:
                            target_reached = True
                            break
                    else:
                        CollectionRunnerService._normalize_item_urls(item)
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
                        global_map[identity_key] = global_profile
                        await InfluencerSourceService.record_from_collected(
                            db, product_record, item, task=task, run_at=run_at
                        )
                        touched_influencers.append(product_record)
                        product_map[identity_key] = product_record
                        new_count += 1
                        outcome = {
                            "status": "inserted",
                            "item": item,
                            "product_influencer_id": None,
                            "global_influencer_id": global_profile.id if global_profile else None,
                            "_product_influencer": product_record,
                            "quality": assessment,
                        }
                        platform_outcomes[profile_key] = outcome
                        if item.platform == "instagram":
                            outcomes[user_key] = outcome
                        checkpoint.mark_persisted(
                            item.platform,
                            item.profile_url,
                            platform_unique_id=item.platform_unique_id,
                        )
                        if (new_count + updated_count) >= qualified_target:
                            target_reached = True
                            break
                except Exception as exc:
                    persist_failed_count += 1
                    filtered_count += 1
                    user_key = (item.username or "").lower()
                    profile_key = collected_identity_key(item)
                    detail = str(exc).strip()[:500] or exc.__class__.__name__
                    logger.exception(
                        "Persist failed for @%s (%s): %s",
                        item.username,
                        item.platform,
                        detail,
                    )
                    outcome = {
                        "status": "profile_failed",
                        "item": item,
                        "detail": detail,
                    }
                    platform_outcomes[profile_key] = outcome
                    if item.platform == "instagram":
                        outcomes[user_key] = outcome
                    checkpoint.mark_persisted(
                        item.platform,
                        item.profile_url,
                        platform_unique_id=item.platform_unique_id,
                    )
                finally:
                    processed_count += 1
                    if processed_count % batch_commit_size == 0 or processed_count == total_count:
                        await db.flush()
                        for outcome in platform_outcomes.values():
                            pending = outcome.get("_product_influencer")
                            if pending is not None and pending.id:
                                outcome["product_influencer_id"] = pending.id
                                if pending.global_influencer_id:
                                    outcome["global_influencer_id"] = pending.global_influencer_id
                        funnel.filtered_out_count = filtered_count
                        funnel.inserted_count = new_count + updated_count
                        logger.info(
                            "[Persist] batch commit processed=%d/%d inserted=%d updated=%d "
                            "skipped=%d filtered=%d persist_errors=%d",
                            processed_count,
                            total_count,
                            new_count,
                            updated_count,
                            skipped_count,
                            filtered_count,
                            persist_failed_count,
                        )
                        await update_task_progress(
                            db,
                            task,
                            stage=STAGE_PERSIST,
                            processed=processed_count,
                            total=total_count,
                            success=new_count + updated_count,
                            skipped=skipped_count,
                            failed=filtered_count,
                            checkpoint=checkpoint,
                            target_qualified=qualified_target,
                            commit=True,
                        )
                        task.discovered_count = funnel.discovered_count
                        task.deduped_count = funnel.deduped_count
                        task.profile_fetched_count = funnel.profile_fetched_count
                        task.profile_failed_count = funnel.profile_failed_count
                        task.filtered_out_count = funnel.filtered_out_count

            candidate_rows = CollectionRunnerService._build_candidate_rows(
                task,
                pipeline_result,
                run_at=run_at,
                outcomes=outcomes,
                filtered_below=filtered_below_min,
                filtered_excluded=filtered_excluded,
            ) if pipeline_result else []

            if aggregate.platform_profiles:
                candidate_rows.extend(
                    CollectionRunnerService._build_platform_candidate_rows(
                        task,
                        aggregate.platform_profiles,
                        platform_outcomes,
                        run_at=run_at,
                    )
                )

            # Include same-product filtered diagnostic rows from aggregate
            if aggregate.candidate_rows:
                candidate_rows.extend(aggregate.candidate_rows)

            amazon_product_video_rows = []
            if task.collection_mode == CollectionMode.COMPETITOR_PRODUCT.value:
                from app.services.competitor_product_discovery import amazon_product_video_candidate_rows

                amazon_product_video_rows = amazon_product_video_candidate_rows(task)
                if amazon_product_video_rows:
                    candidate_rows.extend(amazon_product_video_rows)

            if keyword_seed_result and keyword_seed_result.exec_result.candidate_rows:
                candidate_rows.extend(keyword_seed_result.exec_result.candidate_rows)

            await db.flush()

            seed_new_count = keyword_seed_result.exec_result.new_count if keyword_seed_result else 0
            seed_updated_count = keyword_seed_result.exec_result.updated_count if keyword_seed_result else 0
            seed_filtered_count = keyword_seed_result.exec_result.filtered_out_count if keyword_seed_result else 0
            seed_not_inserted_count = keyword_seed_result.exec_result.not_inserted_count if keyword_seed_result else 0
            inserted_count = new_count + updated_count + seed_new_count + seed_updated_count
            # Include same-product filtered_out counts from aggregate (merge_platform_results)
            same_product_filtered = aggregate.funnel.filtered_out_count
            funnel.filtered_out_count = filtered_count + same_product_filtered + seed_filtered_count
            if amazon_product_video_rows:
                funnel.discovered_count += len(amazon_product_video_rows)
                funnel.deduped_count += len(amazon_product_video_rows)
            funnel.inserted_count = inserted_count
            funnel.preference_mismatch_count = preference_mismatch_count
            funnel.filtered_below_min_followers_count = filtered_below_min + (
                keyword_seed_result.exec_result.filtered_below_min if keyword_seed_result else 0
            )
            funnel.filtered_excluded_keyword_count = filtered_excluded + (
                keyword_seed_result.exec_result.filtered_excluded if keyword_seed_result else 0
            )
            CollectionRunnerService._collect_external_link_funnel_stats(
                aggregate.platform_profiles or [],
                funnel,
            )
            aggregate.funnel = funnel
            if keyword_seed_result:
                checkpoint_extra = dict(task.run_checkpoint or {})
                checkpoint_extra["link_seed_enrichment"] = {
                    "attempted": keyword_seed_result.exec_result.seed_enrichment_attempted,
                    "social_profiles_found": keyword_seed_result.exec_result.seed_social_profiles_found,
                    "low_value_seed_count": keyword_seed_result.exec_result.low_value_seed_count,
                    "mode": task.collection_mode,
                    "platforms": keyword_seed_platforms,
                }
                checkpoint_extra["keyword_seed_discovery"] = {
                    "seed_platforms": keyword_seed_platforms,
                    "discovered_count": keyword_seed_result.discovered_count,
                    "seed_enriched_count": keyword_seed_result.seed_enriched_count,
                    "platform_failed_count": keyword_seed_result.platform_failed_count,
                    "skipped_platform_count": keyword_seed_result.skipped_platform_count,
                    "new_count": seed_new_count,
                    "updated_count": seed_updated_count,
                    "not_inserted_count": seed_not_inserted_count,
                    "filtered_out_count": seed_filtered_count,
                }
                task.run_checkpoint = checkpoint_extra
            if aggregate.provider_availability_state or aggregate.platform_api_counts:
                checkpoint_extra = dict(task.run_checkpoint or {})
                if aggregate.provider_availability_state:
                    state = dict(checkpoint_extra.get("provider_availability_state") or {})
                    state.update(aggregate.provider_availability_state)
                    checkpoint_extra["provider_availability_state"] = state
                if aggregate.platform_api_counts:
                    checkpoint_extra["platform_api_counts"] = dict(aggregate.platform_api_counts)
                task.run_checkpoint = checkpoint_extra
            if amazon_product_video_rows:
                checkpoint_extra = dict(task.run_checkpoint or {})
                checkpoint_extra["amazon_product_page_strong_leads_count"] = len(amazon_product_video_rows)
                task.run_checkpoint = checkpoint_extra
            discovery_api_failed = getattr(stats, "discovery_api_failed", False) if pipeline_result else aggregate.discovery_api_failed
            has_api_warnings = bool(
                aggregate.has_api_warnings
                or (
                    not discovery_api_failed
                    and collection_errors
                    and any(
                        marker in err
                        for err in collection_errors
                        for marker in ("评论发现:", "Hashtag #", "APIFY", "Apify", "未配置", "[tiktok]", "[youtube]", "[facebook]")
                    )
                )
            )
            final_status = determine_multi_platform_status(
                aggregate,
                inserted_count=inserted_count,
                instagram_only=instagram_only,
                instagram_fatal=discovery_api_failed,
            ) if not instagram_only else determine_task_status(
                inserted_count=inserted_count,
                profile_failed_count=stats.profile_failed_count,
                discovered_count=stats.discovered_count,
                fatal_error=discovery_api_failed,
                has_api_warnings=has_api_warnings,
            )

            task.last_run_at = run_at
            task.discovered_count = funnel.discovered_count
            task.deduped_count = funnel.deduped_count
            task.profile_fetched_count = funnel.profile_fetched_count
            task.profile_failed_count = funnel.profile_failed_count
            task.filtered_out_count = funnel.filtered_out_count
            task.inserted_count = funnel.inserted_count
            task.hashtag_count = funnel.hashtag_count
            task.post_count = funnel.post_count
            task.comment_author_count = funnel.comment_author_count
            task.filtered_below_min_followers_count = funnel.filtered_below_min_followers_count
            task.filtered_excluded_keyword_count = funnel.filtered_excluded_keyword_count
            task.result_count = inserted_count
            funnel.overfetch_stop_reason = overfetch_stop_reason
            if inserted_count < qualified_target and not overfetch_stop_reason:
                if total_candidates_seen >= max_candidates:
                    funnel.overfetch_stop_reason = "已达安全上限"
                elif any("429" in err or "限流" in err for err in collection_errors):
                    funnel.overfetch_stop_reason = RATE_LIMIT_STOP_REASON
                elif not non_instagram:
                    funnel.overfetch_stop_reason = "平台无更多结果"

            task.status_summary = build_status_summary(
                funnel,
                status=final_status,
                collection_mode=task.collection_mode,
                competitor_meta=getattr(pipeline_result, "competitor_meta", None) if pipeline_result else None,
            ) if instagram_only else build_multi_platform_summary(
                aggregate,
                status=final_status,
                inserted_count=inserted_count,
                target_qualified_count=qualified_target,
                overfetch_stop_reason=funnel.overfetch_stop_reason,
                filtered_below_min=funnel.filtered_below_min_followers_count,
                filtered_excluded=funnel.filtered_excluded_keyword_count,
                filtered_out=funnel.filtered_out_count,
            )
            if competitor_timed_out and task.status_summary:
                task.status_summary = (
                    f"{task.status_summary}。已达到任务最大耗时，部分平台/API 响应慢，已结束本轮采集"
                )
            if discovery_api_failed and instagram_only:
                task.status_summary = (
                    "Instagram 采集 API 全部失败，未获得任何候选账号，请查看错误详情"
                )
            apply_terminal_task_state(
                task,
                status=final_status,
                errors=collection_errors,
                prefix=build_multi_platform_error_prefix(
                    aggregate,
                    discovery_api_failed=discovery_api_failed,
                    instagram_only=instagram_only,
                ),
                summary=task.status_summary,
                inserted_count=inserted_count,
            )

            await TaskCandidateService.clear_for_task(db, task.id)
            if candidate_rows:
                await TaskCandidateService.bulk_insert(
                    db,
                    task.id,
                    candidate_rows,
                    run_at=run_at,
                    product_id=task.product_id,
                    user_id=task.user_id,
                )

            await db.flush()
            await TaskCandidateService.sync_task_inserted_stats(db, task)
            await TaskInfluencerService.refresh_task_stats(db, task)
            if is_terminal_success_status(final_status):
                clear_task_error_fields(task)
                task.run_checkpoint = clear_interrupted_checkpoint(
                    task.run_checkpoint if isinstance(task.run_checkpoint, dict) else {}
                )
            await db.commit()

            ai_ids = [inf.id for inf in touched_influencers if inf.id]
            if ai_ids:
                if inserted_count > 0 and final_status.value in {
                    CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
                    CollectionTaskStatus.PARTIAL_FAILED.value,
                    CollectionTaskStatus.COMPLETED.value,
                }:
                    task.current_stage = STAGE_COMPLETED
                    await db.commit()
                CollectionRunnerService.schedule_influencer_ai_analysis(task.id, ai_ids)
            else:
                task.current_stage = STAGE_COMPLETED
                await db.commit()

            result_count = task.result_count
            if task.email_enabled:
                await db.refresh(task)
                await EmailService.send_task_email_after_collection(db, task, total_count=result_count)
            if task.outreach_enabled:
                await db.refresh(task)
                await EmailService.sync_outreach_contacts_after_collection(db, task)

            return {
                "new_count": new_count + seed_new_count,
                "updated_count": updated_count + seed_updated_count,
                "skipped_count": skipped_count + seed_not_inserted_count,
                "filtered_count": filtered_count + seed_filtered_count,
                "total_count": total_count + (keyword_seed_result.discovered_count if keyword_seed_result else 0),
                "discovered_count": funnel.discovered_count,
                "deduped_count": funnel.deduped_count,
                "profile_fetched_count": funnel.profile_fetched_count,
                "profile_failed_count": funnel.profile_failed_count,
                "filtered_out_count": funnel.filtered_out_count,
                "inserted_count": funnel.inserted_count,
                "hashtag_count": funnel.hashtag_count,
                "post_count": funnel.post_count,
                "comment_author_count": funnel.comment_author_count,
                "email_count": task.email_count,
                "missing_contact_count": task.missing_contact_count,
                "status_summary": task.status_summary,
            }

        except NotImplementedError as exc:
            error = str(exc)[:2000]
            task.status = CollectionTaskStatus.FAILED.value
            task.error_message = error
            task.current_stage = STAGE_FAILED
            task.last_error = error
            task.last_run_at = datetime.now(UTC)
            await db.commit()
            raise

        except Exception as exc:
            error = str(exc)[:2000]
            task.status = CollectionTaskStatus.FAILED.value
            task.error_message = error
            task.current_stage = STAGE_FAILED
            task.last_error = error
            task.last_run_at = datetime.now(UTC)
            await db.commit()
            raise
        finally:
            await CollectionRunnerService._release_collection_run(task.id)
            if "run_ctx_token" in locals():
                reset_run_context(run_ctx_token)
