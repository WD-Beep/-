"""Facebook Apify 平台 provider（关键词搜索 + Page URL 导入 + 主页补采）。"""

from __future__ import annotations

import asyncio
import logging
import time

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.apify_client import ApifyError, run_actor_sync
from app.services.collection_targets import discovery_fetch_limit
from app.services.concurrency import map_bounded
from app.services.discovery_progress import report_discovery_progress
from app.services.platform_types import PlatformCapability, PlatformCandidateProfile, PlatformDiscoveryResult
from app.services.platform_utils import dedupe_profiles, parse_count_text, profile_to_collected
from app.services.platform_providers.facebook_api_direct import (
    _is_supported_page_url,
    _username_from_page_url,
)
from app.services.task_run_progress import RunCheckpoint, STAGE_DISCOVERY, STAGE_HYDRATION

logger = logging.getLogger(__name__)

APIFY_KEYWORD_CONCURRENCY_CAP = 3
APIFY_PROFILE_CONCURRENCY_CAP = 3


def _append_error(errors: list[str], message: str) -> None:
    text = (message or "").strip()
    if text:
        errors.append(text)


def _is_timeout_error(message: str) -> bool:
    lowered = message.lower()
    return "超时" in message or "timeout" in lowered


def _is_memory_limit_error(message: str) -> bool:
    lowered = (message or "").lower()
    return "actor-memory-limit-exceeded" in lowered or "memory limit" in lowered or "内存" in lowered


def _facebook_keyword_timeout_message(*, keyword: str) -> str:
    return (
        f"Facebook Apify 搜索「{keyword}」超时，建议调大 "
        f"APIFY_FACEBOOK_TIMEOUT_SECONDS（当前 {settings.apify_facebook_timeout_seconds}）/"
        f"FACEBOOK_DISCOVERY_KEYWORD_TIMEOUT_SECONDS（当前 {settings.facebook_discovery_keyword_timeout_seconds}），"
        f"已跳过该关键词并继续"
    )


def _facebook_profile_timeout_message(*, profile_url: str) -> str:
    return (
        f"Facebook Apify 主页补采超时（{profile_url}），建议调大 "
        f"FACEBOOK_APIFY_PROFILE_TIMEOUT_SECONDS（当前 {settings.facebook_apify_profile_timeout_seconds}），"
        f"已跳过该主页并继续"
    )


def _effective_keyword_concurrency() -> int:
    return max(1, min(APIFY_KEYWORD_CONCURRENCY_CAP, settings.facebook_apify_keyword_concurrency))


def _effective_profile_concurrency() -> int:
    return max(1, min(APIFY_PROFILE_CONCURRENCY_CAP, settings.facebook_apify_profile_concurrency))


def _discovery_deadline(task=None) -> float:
    if task is not None:
        from app.services.competitor_product_discovery import is_competitor_product_task

        if is_competitor_product_task(task):
            return time.perf_counter() + max(30, settings.competitor_product_platform_timeout_seconds)
    return time.perf_counter() + max(30, settings.facebook_discovery_max_duration_seconds)


def _count_value(value) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return parse_count_text(value)
    return None


def _has_text(value: str | None) -> bool:
    return bool(value and str(value).strip())


def _profile_has_sufficient_fields(profile: PlatformCandidateProfile) -> bool:
    """搜索/补采结果是否已具备足够主页字段，避免重复补采。"""
    bio_ok = _has_text(profile.bio)
    followers_ok = profile.followers_count is not None and profile.followers_count > 0
    contact_ok = _has_text(profile.email) or _has_text(profile.website)
    return bio_ok and followers_ok and contact_ok


def _profile_from_search_item(item: dict, *, source_keyword: str | None) -> PlatformCandidateProfile | None:
    url = (item.get("url") or item.get("facebookUrl") or item.get("pageUrl") or "").strip()
    if not url or not _is_supported_page_url(url):
        return None
    if item.get("error"):
        return None

    username = _username_from_page_url(url) or (item.get("slug") or item.get("pageName") or "").strip()
    if not username:
        return None

    followers = _count_value(item.get("followers")) or _count_value(item.get("likes"))
    # description 为空时回退用 about（搜索结果已返回该字段，零额外成本）
    bio = item.get("description") or item.get("about")
    bio = bio if isinstance(bio, str) and bio.strip() else None
    website = item.get("website") if isinstance(item.get("website"), str) else None
    email = item.get("email") if isinstance(item.get("email"), str) else None
    candidate = PlatformCandidateProfile(
        platform="facebook",
        username=username,
        profile_url=url,
        display_name=(item.get("name") or item.get("title") or None),
        avatar_url=item.get("profilePicUrl") if isinstance(item.get("profilePicUrl"), str) else None,
        bio=bio,
        followers_count=followers,
        website=website,
        email=email,
        source_type="keyword_page",
        source_discovery_type="page_search",
        source_meta={
            "provider": "apify",
            "actor": settings.apify_facebook_search_actor_id,
            "source_keyword": source_keyword or item.get("query"),
            "page_id": item.get("pageId"),
            "category": item.get("category"),
            "verified": item.get("verified"),
            "profile_hydrated": False,
        },
    )
    candidate.source_meta["profile_hydrated"] = _profile_has_sufficient_fields(candidate)
    return candidate


def _profile_from_pages_item(item: dict, *, input_url: str) -> PlatformCandidateProfile | None:
    url = (
        item.get("facebookUrl")
        or item.get("pageUrl")
        or item.get("url")
        or input_url
    )
    if isinstance(url, str):
        url = url.strip()
    else:
        url = input_url.strip()
    if not url or not _is_supported_page_url(url):
        return None

    username = (
        _username_from_page_url(url)
        or (item.get("pageName") or "").strip()
        or str(item.get("pageId") or "").strip()
    )
    if not username:
        return None

    followers = _count_value(item.get("followers")) or _count_value(item.get("likes"))
    website = item.get("website")
    if isinstance(website, list):
        website = website[0] if website else None

    return PlatformCandidateProfile(
        platform="facebook",
        username=username,
        profile_url=url,
        display_name=(item.get("title") or item.get("pageName") or None),
        avatar_url=item.get("profilePictureUrl") if isinstance(item.get("profilePictureUrl"), str) else None,
        bio=item.get("intro") if isinstance(item.get("intro"), str) else None,
        followers_count=followers,
        website=website if isinstance(website, str) else None,
        email=item.get("email") if isinstance(item.get("email"), str) else None,
        source_type="input_url",
        source_discovery_type="url_import",
        source_meta={
            "provider": "apify",
            "actor": settings.apify_facebook_pages_actor_id,
            "input_url": input_url,
            "page_id": item.get("pageId") or item.get("facebookId"),
            "profile_hydrated": True,
        },
    )


def _merge_profile_details(
    base: PlatformCandidateProfile,
    detail: PlatformCandidateProfile,
) -> PlatformCandidateProfile:
    meta = dict(base.source_meta or {})
    detail_meta = detail.source_meta or {}
    meta.update(detail_meta)
    meta["profile_hydrated"] = True
    return PlatformCandidateProfile(
        platform=base.platform,
        username=base.username,
        profile_url=base.profile_url,
        display_name=detail.display_name or base.display_name,
        avatar_url=detail.avatar_url or base.avatar_url,
        bio=detail.bio or base.bio,
        followers_count=detail.followers_count if detail.followers_count is not None else base.followers_count,
        website=detail.website or base.website,
        email=detail.email or base.email,
        source_type=base.source_type,
        source_discovery_type=base.source_discovery_type,
        source_meta=meta,
    )


def _needs_profile_hydration(profile: PlatformCandidateProfile) -> bool:
    if profile.source_type != "keyword_page":
        return False
    if not _is_supported_page_url(profile.profile_url):
        return False
    return not _profile_has_sufficient_fields(profile)


class FacebookApifyProvider:
    platform = "facebook"

    @staticmethod
    def capability() -> PlatformCapability:
        if not settings.is_apify_configured:
            return PlatformCapability(
                platform="facebook",
                label="Facebook",
                status="not_configured",
                message="Facebook Apify 暂未配置（缺少 APIFY_TOKEN）",
                endpoints=[
                    settings.apify_facebook_search_actor_id,
                    settings.apify_facebook_pages_actor_id,
                ],
            )
        return PlatformCapability(
            platform="facebook",
            label="Facebook",
            status="supported",
            message="Facebook 关键词 Page 搜索与公开 Page URL 导入走 Apify；关键词并发补采主页",
            endpoints=[
                settings.apify_facebook_search_actor_id,
                settings.apify_facebook_pages_actor_id,
            ],
        )

    @staticmethod
    async def discover(
        task: CollectionTask,
        *,
        checkpoint: RunCheckpoint | None = None,
    ) -> PlatformDiscoveryResult:
        cap = FacebookApifyProvider.capability()
        if cap.status == "not_configured":
            return PlatformDiscoveryResult(
                platform="facebook",
                fatal=True,
                skipped=True,
                skip_reason=cap.message,
                errors=[cap.message],
                provider_availability_state={
                    "facebook": {
                        "status": "provider_unavailable",
                        "reason": "provider_not_configured",
                        "message": cap.message,
                        "api_calls": 0,
                    }
                },
            )

        checkpoint = checkpoint or RunCheckpoint.from_task(task)
        keywords = [k.strip() for k in (task.keywords or []) if k and str(k).strip()]
        from app.services.competitor_product_discovery import (
            competitor_discovery_apify_timeout_seconds,
            competitor_discovery_keyword_timeout_seconds,
            filter_competitor_phrase_keywords,
            is_competitor_product_task,
        )

        if is_competitor_product_task(task):
            keywords = filter_competitor_phrase_keywords(keywords)
        input_urls = [u.strip() for u in (task.input_urls or []) if u and str(u).strip()]
        if not keywords and not input_urls:
            msg = "Facebook 采集需要关键词或公开 Page URL"
            return PlatformDiscoveryResult(platform="facebook", errors=[msg], skip_reason=msg)

        limit = discovery_fetch_limit(task)
        profiles: list[PlatformCandidateProfile] = []
        errors: list[str] = []
        rate_limit_count = 0
        slow_api = False
        provider_unavailable_state: dict | None = None
        discovery_started = time.perf_counter()
        deadline = _discovery_deadline(task)
        keyword_timeout = max(1, settings.facebook_discovery_keyword_timeout_seconds)
        apify_timeout = max(1, settings.apify_facebook_timeout_seconds)
        if is_competitor_product_task(task):
            keyword_timeout = competitor_discovery_keyword_timeout_seconds(keyword_timeout)
            apify_timeout = competitor_discovery_apify_timeout_seconds(apify_timeout)
        profile_timeout = max(1, settings.facebook_apify_profile_timeout_seconds)
        concurrency = _effective_keyword_concurrency()

        await report_discovery_progress(
            phase=STAGE_DISCOVERY,
            discovered_count=0,
            deduped_count=0,
            profile_fetched_count=0,
            provider="apify",
            keywords_completed=0,
            keywords_total=len(keywords),
        )

        async def _search_keyword(keyword: str) -> tuple[str, list[PlatformCandidateProfile], list[str], int, bool]:
            local_profiles: list[PlatformCandidateProfile] = []
            local_errors: list[str] = []
            local_rate_limits = 0
            local_slow = False
            started = time.perf_counter()

            await report_discovery_progress(
                phase=STAGE_DISCOVERY,
                discovered_count=len(profiles),
                deduped_count=len(dedupe_profiles(profiles)),
                profile_fetched_count=0,
                provider="apify",
                current_keyword=keyword,
                keywords_completed=0,
                keywords_total=len(keywords),
            )

            per_query = max(3, min(25, limit // max(len(keywords), 1)))
            run_input = {
                "queries": [keyword],
                "searchType": "pages",
                "maxItems": min(limit, per_query),
            }
            try:
                items = await asyncio.wait_for(
                    run_actor_sync(
                        settings.apify_facebook_search_actor_id,
                        run_input,
                        timeout=apify_timeout,
                        max_retries=settings.apify_facebook_max_retries,
                    ),
                    timeout=keyword_timeout + 5,
                )
            except asyncio.TimeoutError:
                local_slow = True
                _append_error(local_errors, _facebook_keyword_timeout_message(keyword=keyword))
                logger.warning(
                    "Facebook Apify keyword timeout keyword=%s elapsed=%.2fs",
                    keyword,
                    time.perf_counter() - started,
                )
                return keyword, local_profiles, local_errors, local_rate_limits, local_slow
            except ApifyError as exc:
                detail = str(exc).strip() or "Apify 请求失败"
                if _is_timeout_error(detail):
                    local_slow = True
                    _append_error(local_errors, _facebook_keyword_timeout_message(keyword=keyword))
                elif "(429)" in detail or "429" in detail:
                    local_rate_limits += 1
                    _append_error(local_errors, f"Facebook Apify 限流（关键词「{keyword}」）: {detail}")
                elif _is_memory_limit_error(detail):
                    _append_error(
                        local_errors,
                        "actor-memory-limit-exceeded: Apify 内存额度已满/并发 actor 过多",
                    )
                else:
                    _append_error(local_errors, f"Facebook Apify 搜索「{keyword}」: {detail}")
                return keyword, local_profiles, local_errors, local_rate_limits, local_slow

            for item in items:
                if not isinstance(item, dict):
                    continue
                profile = _profile_from_search_item(item, source_keyword=keyword)
                if profile:
                    local_profiles.append(profile)
            checkpoint.mark_search("facebook", keyword)

            elapsed = time.perf_counter() - started
            if not local_profiles and elapsed >= settings.facebook_discovery_slow_threshold_seconds:
                local_slow = True
                local_errors.append(
                    f"Facebook Apify 搜索「{keyword}」耗时 {elapsed:.0f}s 但未返回候选，可能关键词无结果或平台响应慢"
                )
            logger.info(
                "Facebook Apify keyword search keyword=%s elapsed=%.2fs profiles=%d",
                keyword,
                elapsed,
                len(local_profiles),
            )
            return keyword, local_profiles, local_errors, local_rate_limits, local_slow

        keywords_completed = 0
        for chunk_start in range(0, len(keywords), concurrency):
            if time.perf_counter() >= deadline:
                _append_error(
                    errors,
                    f"Facebook 发现阶段总耗时超过 {settings.facebook_discovery_max_duration_seconds}s，"
                    f"已停止剩余 {len(keywords) - keywords_completed} 个关键词",
                )
                slow_api = True
                break
            if len(profiles) >= limit:
                break

            chunk = keywords[chunk_start : chunk_start + concurrency]
            await report_discovery_progress(
                phase=STAGE_DISCOVERY,
                discovered_count=len(profiles),
                deduped_count=len(dedupe_profiles(profiles)),
                profile_fetched_count=0,
                provider="apify",
                current_keyword=chunk[0],
                keywords_completed=keywords_completed,
                keywords_total=len(keywords),
            )

            outcomes = await map_bounded(chunk, _search_keyword, concurrency=len(chunk))
            for outcome in outcomes:
                keywords_completed += 1
                if isinstance(outcome, BaseException):
                    detail = str(outcome).strip() or type(outcome).__name__
                    slow_api = slow_api or _is_timeout_error(detail)
                    _append_error(errors, f"Facebook Apify 搜索: {detail}")
                    continue
                _keyword, local_profiles, local_errors, local_rate_limits, local_slow = outcome
                rate_limit_count += local_rate_limits
                slow_api = slow_api or local_slow
                errors.extend(local_errors)
                if any(_is_memory_limit_error(err) for err in local_errors):
                    provider_unavailable_state = {
                        "status": "provider_unavailable",
                        "reason": "apify_memory_limit_exceeded",
                        "message": "Apify 内存额度已满/并发 actor 过多，已短路跳过后续 Facebook query",
                        "api_calls": keywords_completed,
                    }
                profiles.extend(local_profiles)
                profiles = dedupe_profiles(profiles)
                await report_discovery_progress(
                    phase=STAGE_DISCOVERY,
                    discovered_count=len(profiles),
                    deduped_count=len(profiles),
                    profile_fetched_count=0,
                    rate_limited=rate_limit_count > 0,
                    slow_api=slow_api,
                    provider="apify",
                    current_keyword=_keyword,
                    keywords_completed=keywords_completed,
                    keywords_total=len(keywords),
                    timing_note=local_errors[-1] if local_errors else None,
                )
                if len(profiles) >= limit:
                    break
            if provider_unavailable_state:
                break

        if input_urls:
            started = time.perf_counter()
            try:
                items = await asyncio.wait_for(
                    run_actor_sync(
                        settings.apify_facebook_pages_actor_id,
                        {"startUrls": [{"url": url} for url in input_urls[:limit]]},
                        timeout=apify_timeout,
                        max_retries=settings.apify_facebook_max_retries,
                    ),
                    timeout=keyword_timeout + 5,
                )
                by_url = {
                    str(item.get("facebookUrl") or item.get("pageUrl") or "").lower().rstrip("/"): item
                    for item in items
                    if isinstance(item, dict)
                }
                for url in input_urls:
                    item = by_url.get(url.lower().rstrip("/"))
                    if not isinstance(item, dict):
                        for key, candidate in by_url.items():
                            if url.lower().rstrip("/") in key:
                                item = candidate
                                break
                    if isinstance(item, dict):
                        profile = _profile_from_pages_item(item, input_url=url)
                        if profile:
                            profiles.append(profile)
                profiles = dedupe_profiles(profiles)
                logger.info(
                    "Facebook Apify url import elapsed=%.2fs profiles=%d",
                    time.perf_counter() - started,
                    len(profiles),
                )
            except asyncio.TimeoutError:
                slow_api = True
                _append_error(
                    errors,
                    f"Facebook Apify Page URL 导入超时，建议调大 APIFY_FACEBOOK_TIMEOUT_SECONDS（当前 {apify_timeout}）",
                )
            except ApifyError as exc:
                detail = str(exc).strip() or "Apify 请求失败"
                if _is_timeout_error(detail):
                    slow_api = True
                if "(429)" in detail or "429" in detail:
                    rate_limit_count += 1
                if _is_memory_limit_error(detail):
                    provider_unavailable_state = {
                        "status": "provider_unavailable",
                        "reason": "apify_memory_limit_exceeded",
                        "message": "Apify 内存额度已满/并发 actor 过多，已跳过 Facebook Page URL 导入",
                        "api_calls": keywords_completed + 1,
                    }
                    _append_error(errors, "actor-memory-limit-exceeded: Apify 内存额度已满/并发 actor 过多")
                _append_error(errors, f"Facebook Page URL 导入: {detail}")

        deduped = dedupe_profiles(profiles)[:limit]
        hydration_targets = [profile for profile in deduped if _needs_profile_hydration(profile)]
        hydrated_count = 0
        profile_concurrency = _effective_profile_concurrency()

        await report_discovery_progress(
            phase=STAGE_HYDRATION,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=0,
            provider="apify",
            keywords_completed=keywords_completed,
            keywords_total=len(keywords),
            profiles_hydrating_total=len(hydration_targets),
            profiles_hydrating_completed=0,
        )

        async def _hydrate_profile(profile: PlatformCandidateProfile) -> tuple[PlatformCandidateProfile, str | None]:
            started = time.perf_counter()
            try:
                items = await asyncio.wait_for(
                    run_actor_sync(
                        settings.apify_facebook_pages_actor_id,
                        {"startUrls": [{"url": profile.profile_url}]},
                        timeout=profile_timeout,
                        max_retries=settings.apify_facebook_max_retries,
                    ),
                    timeout=profile_timeout + 5,
                )
            except asyncio.TimeoutError:
                msg = _facebook_profile_timeout_message(profile_url=profile.profile_url)
                logger.warning("Facebook Apify profile timeout url=%s", profile.profile_url)
                return profile, msg
            except ApifyError as exc:
                detail = str(exc).strip() or "Apify 请求失败"
                if _is_timeout_error(detail):
                    return profile, _facebook_profile_timeout_message(profile_url=profile.profile_url)
                if "(429)" in detail or "429" in detail:
                    return profile, f"Facebook Apify 主页补采限流（{profile.profile_url}）: {detail}"
                return profile, f"Facebook Apify 主页补采（{profile.profile_url}）: {detail}"

            item = next((row for row in items if isinstance(row, dict)), None)
            if not isinstance(item, dict):
                return profile, None
            detail = _profile_from_pages_item(item, input_url=profile.profile_url)
            if not detail:
                return profile, None
            logger.info(
                "Facebook Apify profile hydration url=%s elapsed=%.2fs",
                profile.profile_url,
                time.perf_counter() - started,
            )
            return _merge_profile_details(profile, detail), None

        if hydration_targets:
            for chunk_start in range(0, len(hydration_targets), profile_concurrency):
                if time.perf_counter() >= deadline:
                    _append_error(
                        errors,
                        f"Facebook 主页补采总耗时超过 {settings.facebook_discovery_max_duration_seconds}s，"
                        f"已跳过剩余 {len(hydration_targets) - hydrated_count} 个主页",
                    )
                    slow_api = True
                    break

                chunk = hydration_targets[chunk_start : chunk_start + profile_concurrency]
                await report_discovery_progress(
                    phase=STAGE_HYDRATION,
                    discovered_count=len(profiles),
                    deduped_count=len(deduped),
                    profile_fetched_count=hydrated_count,
                    provider="apify",
                    keywords_completed=keywords_completed,
                    keywords_total=len(keywords),
                    profiles_hydrating_total=len(hydration_targets),
                    profiles_hydrating_completed=hydrated_count,
                    current_profile_url=chunk[0].profile_url if chunk else None,
                )

                outcomes = await map_bounded(chunk, _hydrate_profile, concurrency=len(chunk))
                hydrated_map: dict[str, PlatformCandidateProfile] = {}
                for outcome in outcomes:
                    hydrated_count += 1
                    if isinstance(outcome, BaseException):
                        detail = str(outcome).strip() or type(outcome).__name__
                        slow_api = slow_api or _is_timeout_error(detail)
                        _append_error(errors, f"Facebook Apify 主页补采: {detail}")
                        continue
                    hydrated_profile, err = outcome
                    hydrated_map[hydrated_profile.profile_url.lower().rstrip("/")] = hydrated_profile
                    if err:
                        slow_api = slow_api or _is_timeout_error(err)
                        _append_error(errors, err)
                    if err and ("429" in err or "限流" in err):
                        rate_limit_count += 1

                deduped = [
                    hydrated_map.get(profile.profile_url.lower().rstrip("/"), profile)
                    for profile in deduped
                ]
                await report_discovery_progress(
                    phase=STAGE_HYDRATION,
                    discovered_count=len(profiles),
                    deduped_count=len(deduped),
                    profile_fetched_count=hydrated_count,
                    rate_limited=rate_limit_count > 0,
                    slow_api=slow_api,
                    provider="apify",
                    keywords_completed=keywords_completed,
                    keywords_total=len(keywords),
                    profiles_hydrating_total=len(hydration_targets),
                    profiles_hydrating_completed=hydrated_count,
                )

        rate_limited = rate_limit_count > 0
        if rate_limited:
            errors.append(
                f"Facebook Apify 限流 {rate_limit_count} 次；系统已降速重试，"
                f"已发现 {len(profiles)} 个候选，去重 {len(deduped)} 个"
            )

        if not deduped and not profiles:
            if rate_limited:
                empty_reason = "平台接口限流，暂无候选结果"
            elif slow_api or (time.perf_counter() - discovery_started) >= settings.facebook_discovery_slow_threshold_seconds:
                empty_reason = "Apify/API 响应较慢或关键词暂无匹配结果"
            else:
                empty_reason = "关键词/API 暂无候选结果"
            errors.append(
                f"Facebook 发现阶段结束：{empty_reason}（共搜索 {keywords_completed}/{len(keywords)} 个关键词）"
            )

        await report_discovery_progress(
            phase=STAGE_DISCOVERY,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=len(deduped),
            rate_limited=rate_limited,
            slow_api=slow_api,
            provider="apify",
            keywords_completed=keywords_completed,
            keywords_total=len(keywords),
            profiles_hydrating_total=len(hydration_targets),
            profiles_hydrating_completed=hydrated_count,
        )

        errors = [err for err in errors if err and err.strip()]
        items = [profile_to_collected(p) for p in deduped]
        from app.services.collect_errors import filter_fatal_discovery_errors

        fatal_errors = filter_fatal_discovery_errors(errors)
        api_calls = keywords_completed + len(hydration_targets) + (1 if input_urls else 0)
        empty_success = not deduped and not items and not fatal_errors
        return PlatformDiscoveryResult(
            platform="facebook",
            items=items,
            profiles=deduped,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=len(deduped),
            api_requests=api_calls,
            errors=errors,
            rate_limited=rate_limited,
            rate_limit_count=rate_limit_count,
            fatal=bool(fatal_errors)
            and not empty_success
            and not deduped
            and not rate_limited
            and not slow_api
            and not provider_unavailable_state,
            skipped=bool(provider_unavailable_state and not deduped),
            skip_reason=provider_unavailable_state.get("message") if provider_unavailable_state and not deduped else None,
            provider_availability_state={"facebook": provider_unavailable_state} if provider_unavailable_state else {},
        )
