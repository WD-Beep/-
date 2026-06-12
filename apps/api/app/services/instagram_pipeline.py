"""Instagram 内容作者优先采集流水线：统一发现 → 去重 → 主页补采 → 质量评分。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.collectors.base import CollectedInfluencer
from app.models.collection_task import CollectionTask
from app.services.apify_instagram import FailedProfile, PostAuthorCandidate
from app.services.collection_filters import (
    is_valid_instagram_username,
    is_valid_profile_url,
)
from app.services.contact_discovery import ContactDiscoveryService
from app.services.concurrency import map_bounded
from app.core.config import settings
from app.services.task_run_progress import RunCheckpoint, STAGE_HYDRATION, update_task_progress
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.instagram_provider import scrape_instagram_profiles
from app.services.instagram_quality import apply_quality_scores_to_item, compute_quality_scores
from app.services.collection_targets import discovery_fetch_limit
from app.services.instagram_unified_discovery import unified_discover_candidates

logger = logging.getLogger(__name__)


@dataclass
class EarlyInvalidCandidate:
    candidate: PostAuthorCandidate
    failure_reason: str
    failure_detail: str


@dataclass
class PipelineRunStats:
    discovered_count: int = 0
    deduped_count: int = 0
    duplicate_count: int = 0
    profile_fetched_count: int = 0
    profile_failed_count: int = 0
    filtered_out_count: int = 0
    inserted_count: int = 0
    hydrated_count: int = 0
    scored_count: int = 0
    priority_p0: int = 0
    priority_p1: int = 0
    priority_p2: int = 0
    priority_p3: int = 0
    hashtag_count: int = 0
    post_count: int = 0
    comment_author_count: int = 0
    discovery_api_failed: bool = False


@dataclass
class InstagramPipelineResult:
    items: list[CollectedInfluencer] = field(default_factory=list)
    stats: PipelineRunStats = field(default_factory=PipelineRunStats)
    errors: list[str] = field(default_factory=list)
    failed_profiles: list[FailedProfile] = field(default_factory=list)
    candidate_meta: dict[str, PostAuthorCandidate] = field(default_factory=dict)
    discovery_duplicates: list[PostAuthorCandidate] = field(default_factory=list)
    early_invalid: list[EarlyInvalidCandidate] = field(default_factory=list)
    competitor_meta: object | None = None


def _apply_task_context(items: list[CollectedInfluencer], task: CollectionTask) -> list[CollectedInfluencer]:
    results: list[CollectedInfluencer] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item.platform, item.profile_url)
        if key in seen:
            continue
        seen.add(key)
        if task.category:
            item.category = task.category
        if task.country:
            item.country = task.country
        results.append(item)
    return results


def _partition_early_filter(
    candidates: list[PostAuthorCandidate],
    task: CollectionTask,
) -> tuple[list[PostAuthorCandidate], list[EarlyInvalidCandidate]]:
    del task
    valid: list[PostAuthorCandidate] = []
    invalid: list[EarlyInvalidCandidate] = []
    for candidate in candidates:
        if not is_valid_instagram_username(candidate.username):
            invalid.append(
                EarlyInvalidCandidate(
                    candidate=candidate,
                    failure_reason="invalid_username",
                    failure_detail=f"用户名 @{candidate.username} 不符合 Instagram 规范或为保留路径",
                )
            )
            continue
        if not is_valid_profile_url(candidate.profile_url):
            invalid.append(
                EarlyInvalidCandidate(
                    candidate=candidate,
                    failure_reason="invalid_username",
                    failure_detail=f"主页链接无效或不可采集: {candidate.profile_url}",
                )
            )
            continue
        valid.append(candidate)
    return valid, invalid


class InstagramCollectionPipeline:
    @staticmethod
    async def run(
        task: CollectionTask,
        *,
        db: AsyncSession | None = None,
        checkpoint: RunCheckpoint | None = None,
    ) -> InstagramPipelineResult:
        checkpoint = checkpoint or RunCheckpoint()
        limit = discovery_fetch_limit(task)
        stats = PipelineRunStats()
        all_errors: list[str] = []

        discovery = await unified_discover_candidates(
            task,
            limit=limit,
            db=db,
            checkpoint=checkpoint,
        )
        all_errors.extend(discovery.errors)
        stats.discovered_count = len(discovery.raw_candidates)
        stats.deduped_count = len(discovery.deduped_candidates)
        stats.duplicate_count = discovery.duplicate_count
        stats.discovery_api_failed = discovery.discovery_api_failed

        stats.hashtag_count = discovery.hashtag_count
        stats.post_count = discovery.post_count
        stats.comment_author_count = discovery.comment_author_count

        early_candidates, early_invalid = _partition_early_filter(discovery.deduped_candidates, task)

        logger.info(
            "[Pipeline] Step1 unified task=%s mode=%s raw=%d deduped=%d dup=%d valid=%d invalid=%d",
            task.id,
            task.collection_mode,
            stats.discovered_count,
            stats.deduped_count,
            stats.duplicate_count,
            len(early_candidates),
            len(early_invalid),
        )

        if not early_candidates:
            if not early_invalid and not discovery.discovery_duplicates:
                if not all_errors:
                    all_errors.append("未发现任何有效候选账号（帖子作者/评论用户/链接输入）")
            return InstagramPipelineResult(
                items=[],
                stats=stats,
                errors=all_errors,
                discovery_duplicates=discovery.discovery_duplicates,
                early_invalid=early_invalid,
                competitor_meta=discovery.competitor_meta,
            )

        candidate_meta = {c.username.lower(): c for c in early_candidates}
        profile_urls = [
            c.profile_url
            for c in early_candidates
            if not checkpoint.hydrated_done("instagram", c.profile_url)
        ]

        if db is not None:
            await update_task_progress(
                db,
                task,
                stage=STAGE_HYDRATION,
                total=len(early_candidates),
                processed=len(checkpoint.hydrated_profiles),
                checkpoint=checkpoint,
                commit=True,
            )

        scrape_result = await scrape_instagram_profiles(profile_urls, candidate_meta=candidate_meta)
        for profile in scrape_result.profiles:
            checkpoint.mark_hydrated("instagram", profile.profile_url)
        if db is not None:
            await update_task_progress(
                db,
                task,
                stage=STAGE_HYDRATION,
                total=len(early_candidates),
                processed=min(len(checkpoint.hydrated_profiles), len(early_candidates)),
                failed=len(scrape_result.failed_profiles),
                checkpoint=checkpoint,
                commit=True,
            )
        all_errors.extend(scrape_result.errors)
        stats.profile_fetched_count = len(scrape_result.profiles)
        stats.profile_failed_count = len(scrape_result.failed_profiles)
        stats.hydrated_count = stats.profile_fetched_count

        logger.info(
            "[Pipeline] Step2 Hydration fetched=%d failed=%d",
            stats.profile_fetched_count,
            stats.profile_failed_count,
        )

        if not scrape_result.profiles and not scrape_result.failed_profiles and not all_errors:
            all_errors.append("Profile Hydration 未返回任何有效红人资料")

        hydrated = _apply_task_context(scrape_result.profiles, task)
        contact_fetch_issues = 0

        async def _enrich_contact(item: CollectedInfluencer) -> CollectedInfluencer:
            await ContactDiscoveryService.enrich_collected(item)
            return item

        enrich_outcomes = await map_bounded(
            hydrated,
            _enrich_contact,
            concurrency=settings.collection_contact_concurrency,
        )
        for outcome in enrich_outcomes:
            if isinstance(outcome, BaseException):
                contact_fetch_issues += 1
                continue
            if outcome.contact_fetch_status in {"partial_failed", "failed"}:
                contact_fetch_issues += 1
        if contact_fetch_issues:
            all_errors.append(f"部分联系方式深挖失败: {contact_fetch_issues} 条")

        for item in hydrated:
            meta = candidate_meta.get((item.username or "").lower())
            if not meta:
                continue
            item.source_discovery_type = meta.source_discovery_type
            from app.services.instagram_urls import normalize_instagram_post_url, normalize_instagram_profile_url

            if meta.source_post_url:
                item.source_post_url = (
                    normalize_instagram_post_url(meta.source_post_url) or meta.source_post_url
                )
            if meta.source_comment_url:
                item.source_comment_url = (
                    normalize_instagram_post_url(meta.source_comment_url) or meta.source_comment_url
                )
            normalized_profile = normalize_instagram_profile_url(meta.profile_url, username=meta.username)
            if normalized_profile:
                item.profile_url = normalized_profile
            item.source_comment_text = meta.source_comment_text or meta.source_caption
            tags = list(item.tags or [])
            if meta.source_discovery_type == "comment_author" and "comment_discovery" not in tags:
                tags.append("comment_discovery")
            elif meta.source_discovery_type == "competitor_product" and "competitor_product" not in tags:
                tags.append("competitor_product")
            elif meta.source_discovery_type in ("post_author", None) and "keyword_discovery" not in tags:
                tags.append("keyword_discovery")
            item.tags = tags

        scored: list[CollectedInfluencer] = []
        for item in hydrated:
            scores = compute_quality_scores(item, task)
            apply_quality_scores_to_item(item, scores)
            scored.append(item)
            if scores.final_priority == "P0":
                stats.priority_p0 += 1
            elif scores.final_priority == "P1":
                stats.priority_p1 += 1
            elif scores.final_priority == "P2":
                stats.priority_p2 += 1
            else:
                stats.priority_p3 += 1
        stats.scored_count = len(scored)

        return InstagramPipelineResult(
            items=scored,
            stats=stats,
            errors=all_errors,
            failed_profiles=scrape_result.failed_profiles,
            candidate_meta=candidate_meta,
            discovery_duplicates=discovery.discovery_duplicates,
            early_invalid=early_invalid,
            competitor_meta=discovery.competitor_meta,
        )
