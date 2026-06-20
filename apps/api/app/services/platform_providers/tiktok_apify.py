"""TikTok Apify 平台 provider（clockworks/tiktok-scraper）。"""

from __future__ import annotations

import asyncio
import logging
import time

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.apify_client import ApifyError, run_actor_sync
from app.services.collection_targets import discovery_fetch_limit
from app.services.concurrency import map_bounded
from app.services.platform_types import PlatformCapability, PlatformCandidateProfile, PlatformDiscoveryResult
from app.services.platform_utils import (
    dedupe_profiles,
    engagement_rate_from_metrics,
    parse_count_text,
    profile_to_collected,
    tiktok_region_from_task,
)

from app.services.platform_providers.tiktok_api_direct import _tiktok_profile_url

logger = logging.getLogger(__name__)


def _is_memory_limit_error(message: str) -> bool:
    lowered = (message or "").lower()
    return "memory-limit-exceeded" in lowered or "memory limit" in lowered or "内存" in lowered


def _author_meta(item: dict) -> dict:
    meta = item.get("authorMeta")
    if isinstance(meta, dict):
        return meta
    return {}


def _profile_from_apify_item(item: dict, *, source_keyword: str | None) -> PlatformCandidateProfile | None:
    meta = _author_meta(item)
    author = str(item.get("authorMeta.name") or meta.get("name") or item.get("author") or "").strip().lstrip("@")
    if not author:
        return None

    play_count = item.get("playCount")
    if play_count is None:
        play_count = meta.get("playCount")
    if isinstance(play_count, str):
        play_count = parse_count_text(play_count)
    likes = item.get("diggCount")
    if isinstance(likes, str):
        likes = parse_count_text(likes)
    comments = item.get("commentCount")
    if isinstance(comments, str):
        comments = parse_count_text(comments)
    followers = item.get("authorMeta.fans") or meta.get("fans")
    if isinstance(followers, str):
        followers = parse_count_text(followers)

    bio = meta.get("signature") or item.get("authorMeta.signature") or item.get("text")
    avatar = meta.get("avatar") or item.get("authorMeta.avatar")
    video_url = item.get("webVideoUrl") or item.get("url")

    return PlatformCandidateProfile(
        platform="tiktok",
        username=author,
        profile_url=_tiktok_profile_url(author),
        display_name=meta.get("nickName") or meta.get("nickname") or item.get("authorMeta.nickName"),
        avatar_url=avatar if isinstance(avatar, str) else None,
        bio=bio if isinstance(bio, str) else None,
        followers_count=followers if isinstance(followers, int) else None,
        avg_views=play_count if isinstance(play_count, int) else None,
        avg_likes=likes if isinstance(likes, int) else None,
        avg_comments=comments if isinstance(comments, int) else None,
        engagement_rate=engagement_rate_from_metrics(
            views=play_count if isinstance(play_count, int) else None,
            likes=likes if isinstance(likes, int) else None,
            comments=comments if isinstance(comments, int) else None,
        ),
        source_url=video_url if isinstance(video_url, str) else None,
        source_type="keyword_video_author",
        source_discovery_type="video_author",
        source_meta={
            "provider": "apify",
            "actor": settings.apify_tiktok_actor_id,
            "source_keyword": source_keyword,
            "video_title": item.get("text") if isinstance(item.get("text"), str) else None,
        },
    )


class TikTokApifyProvider:
    platform = "tiktok"

    @staticmethod
    def capability() -> PlatformCapability:
        if not settings.is_apify_configured:
            return PlatformCapability(
                platform="tiktok",
                label="TikTok",
                status="not_configured",
                message="TikTok Apify 暂未配置（缺少 APIFY_TOKEN）",
                endpoints=[settings.apify_tiktok_actor_id],
            )
        return PlatformCapability(
            platform="tiktok",
            label="TikTok",
            status="supported",
            message="TikTok 关键词/hashtag 视频搜索走 Apify TikTok Scraper",
            endpoints=[settings.apify_tiktok_actor_id],
        )

    @staticmethod
    async def discover(task: CollectionTask) -> PlatformDiscoveryResult:
        cap = TikTokApifyProvider.capability()
        if cap.status == "not_configured":
            return PlatformDiscoveryResult(
                platform="tiktok",
                fatal=True,
                skipped=True,
                skip_reason=cap.message,
                errors=[cap.message],
                provider_availability_state={
                    "tiktok": {
                        "status": "provider_unavailable",
                        "reason": "provider_not_configured",
                        "message": cap.message,
                        "api_calls": 0,
                    }
                },
            )

        keywords = [k.strip().lstrip("#") for k in (task.keywords or []) if k and str(k).strip()]
        from app.services.competitor_product_discovery import (
            competitor_discovery_apify_timeout_seconds,
            competitor_discovery_keyword_timeout_seconds,
            filter_competitor_phrase_keywords,
            is_competitor_product_task,
        )

        if is_competitor_product_task(task):
            keywords = filter_competitor_phrase_keywords(keywords)
        if not keywords:
            msg = "TikTok 采集至少需要一个关键词或 hashtag"
            return PlatformDiscoveryResult(platform="tiktok", errors=[msg], skip_reason=msg)

        limit = discovery_fetch_limit(task)
        max_results = min(max(limit * 3, 20), 100)
        keyword_timeout = max(1, settings.apify_tiktok_timeout_seconds)
        if is_competitor_product_task(task):
            keyword_timeout = competitor_discovery_keyword_timeout_seconds(keyword_timeout)
            apify_timeout = competitor_discovery_apify_timeout_seconds(keyword_timeout)
        else:
            apify_timeout = keyword_timeout
        concurrency = max(1, settings.tiktok_apify_keyword_concurrency)
        if is_competitor_product_task(task):
            concurrency = 1
        region = tiktok_region_from_task(task)
        memory_mbytes = max(512, settings.tiktok_apify_memory_mbytes)

        profiles: list[PlatformCandidateProfile] = []
        errors: list[str] = []
        rate_limit_count = 0
        provider_unavailable_state: dict | None = None
        attempted_queries = 0

        async def _search_keyword(keyword: str) -> tuple[str, list[PlatformCandidateProfile], list[str], int]:
            local_profiles: list[PlatformCandidateProfile] = []
            local_errors: list[str] = []
            local_rate_limits = 0
            started = time.perf_counter()

            def _run_input(results_per_page: int) -> dict:
                value: dict = {
                    "searchQueries": [keyword],
                    "resultsPerPage": results_per_page,
                    "shouldDownloadVideos": False,
                    "shouldDownloadAvatars": False,
                    "shouldDownloadCovers": False,
                }
                if region:
                    value["proxyCountryCode"] = region.upper()
                return value

            run_input = _run_input(max_results)

            async def _run_search(current_input: dict, *, current_memory: int) -> list[dict]:
                return await asyncio.wait_for(
                    run_actor_sync(
                        settings.apify_tiktok_actor_id,
                        current_input,
                        timeout=apify_timeout,
                        max_retries=settings.apify_tiktok_max_retries,
                        memory_mbytes=current_memory,
                    ),
                    timeout=keyword_timeout + 5,
                )

            try:
                items = await _run_search(run_input, current_memory=memory_mbytes)
            except asyncio.TimeoutError:
                local_errors.append(
                    f"query {keyword}: TikTok Apify 搜索超时（>{keyword_timeout}s），已继续其他 query"
                )
                logger.warning("TikTok Apify keyword timeout keyword=%s", keyword)
                return keyword, local_profiles, local_errors, local_rate_limits
            except ApifyError as exc:
                detail = str(exc)
                if _is_memory_limit_error(detail):
                    retry_results = max(5, min(max_results // 2, max_results - 1))
                    retry_memory = max(512, min(memory_mbytes, 1024))
                    local_errors.append(
                        f"query {keyword}: TikTok Apify 内存限制，已降级重试 1 次"
                    )
                    try:
                        items = await _run_search(_run_input(retry_results), current_memory=retry_memory)
                    except asyncio.TimeoutError:
                        local_errors.append(
                            f"query {keyword}: TikTok Apify 内存限制，已降级重试 1 次后超时（>{keyword_timeout}s）"
                        )
                        logger.warning("TikTok Apify memory retry timeout keyword=%s", keyword)
                        return keyword, local_profiles, local_errors, local_rate_limits
                    except ApifyError as retry_exc:
                        retry_detail = str(retry_exc)
                        local_errors.append(
                            f"query {keyword}: TikTok Apify 内存限制，已降级重试 1 次仍失败: {retry_detail}"
                        )
                        local_errors.append(
                            "actor-memory-limit-exceeded: Apify 内存额度已满/并发 actor 过多"
                        )
                        return keyword, local_profiles, local_errors, local_rate_limits
                elif "(429)" in detail or "429" in detail:
                    local_rate_limits += 1
                    local_errors.append(f"query {keyword}: TikTok Apify 限流: {detail}")
                    return keyword, local_profiles, local_errors, local_rate_limits
                else:
                    local_errors.append(f"query {keyword}: TikTok Apify provider error: {detail}")
                    return keyword, local_profiles, local_errors, local_rate_limits

            for item in items:
                if not isinstance(item, dict):
                    continue
                profile = _profile_from_apify_item(item, source_keyword=keyword)
                if profile:
                    local_profiles.append(profile)

            logger.info(
                "TikTok Apify keyword search keyword=%s elapsed=%.2fs profiles=%d items=%d",
                keyword,
                time.perf_counter() - started,
                len(local_profiles),
                len(items),
            )
            return keyword, local_profiles, local_errors, local_rate_limits

        for chunk_start in range(0, len(keywords), concurrency):
            if len(profiles) >= limit:
                break
            chunk = keywords[chunk_start : chunk_start + concurrency]
            outcomes = await map_bounded(chunk, _search_keyword, concurrency=len(chunk))
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    errors.append(str(outcome))
                    continue
                _keyword, local_profiles, local_errors, local_rate_limits = outcome
                attempted_queries += 1
                rate_limit_count += local_rate_limits
                errors.extend(local_errors)
                if any(_is_memory_limit_error(err) for err in local_errors):
                    provider_unavailable_state = {
                        "status": "provider_unavailable",
                        "reason": "apify_memory_limit_exceeded",
                        "message": "Apify 内存额度已满/并发 actor 过多，已短路跳过后续 TikTok query",
                        "api_calls": attempted_queries,
                    }
                for profile in local_profiles:
                    if len(profiles) >= limit:
                        break
                    profiles.append(profile)
                if len(profiles) >= limit:
                    break
            if provider_unavailable_state:
                break

        deduped = dedupe_profiles(profiles)[:limit]
        rate_limited = rate_limit_count > 0
        if rate_limited:
            errors.append(
                f"TikTok Apify 限流 {rate_limit_count} 次；系统已降速重试，"
                f"已发现 {len(profiles)} 个候选，去重 {len(deduped)} 个"
            )
        if not deduped and not profiles and errors:
            errors.append(f"TikTok 发现阶段结束：关键词/API 暂无候选结果（共搜索 {len(keywords)} 个关键词）")

        return PlatformDiscoveryResult(
            platform="tiktok",
            items=[profile_to_collected(p) for p in deduped],
            profiles=deduped,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=len(deduped),
            api_requests=attempted_queries,
            errors=errors,
            rate_limited=rate_limited,
            rate_limit_count=rate_limit_count,
            skipped=bool(provider_unavailable_state and not deduped),
            skip_reason=provider_unavailable_state.get("message") if provider_unavailable_state and not deduped else None,
            provider_availability_state={"tiktok": provider_unavailable_state} if provider_unavailable_state else {},
            fatal=bool(errors) and not deduped and not rate_limited and not provider_unavailable_state,
        )
