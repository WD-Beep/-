"""YouTube Apify 平台 provider（streamers/youtube-scraper）。"""



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

from app.services.platform_utils import dedupe_profiles, engagement_rate_from_metrics, parse_count_text, profile_to_collected

from app.services.task_run_progress import RunCheckpoint, STAGE_DISCOVERY, STAGE_HYDRATION



from app.services.platform_providers.youtube_api_direct import (
    CHANNEL_URL_RE,
    _append_link,
    _extract_description_signals,
    _hydrate_profiles_about,
    _merge_link_dicts,
    _normalize_url,
    _profile_from_input_url,
)
from app.services.platform_providers.youtube_dedupe import (
    YouTubeDedupeStats,
    apify_search_max_results,
    dedupe_apify_items,
    dedupe_youtube_profiles,
    extract_video_id,
    normalize_keywords,
)



logger = logging.getLogger(__name__)

APIFY_KEYWORD_CONCURRENCY_CAP = 3


def _append_error(errors: list[str], message: str) -> None:
    text = (message or "").strip()
    if text:
        errors.append(text)


def _is_timeout_error(message: str) -> bool:
    lowered = message.lower()
    return "超时" in message or "timeout" in lowered


def _youtube_apify_timeout_message(*, keyword: str | None = None, url_import: bool = False) -> str:
    tuning = (
        "Apify YouTube 请求超时，建议调大 "
        f"APIFY_YOUTUBE_TIMEOUT_SECONDS（当前 {settings.apify_youtube_timeout_seconds}）/"
        f"YOUTUBE_DISCOVERY_KEYWORD_TIMEOUT_SECONDS（当前 {settings.youtube_discovery_keyword_timeout_seconds}）"
    )
    if keyword:
        return f"YouTube Apify 搜索「{keyword}」{tuning}，已跳过该关键词并继续"
    if url_import:
        return f"YouTube Apify 频道链接采集{tuning}"
    return tuning


def _format_worker_exception(exc: BaseException, *, keyword: str | None = None) -> tuple[str, bool]:
    detail = str(exc).strip() or type(exc).__name__
    if _is_timeout_error(detail):
        return _youtube_apify_timeout_message(keyword=keyword), True
    if keyword:
        return f"YouTube Apify 搜索「{keyword}」: {detail}", False
    return f"YouTube Apify: {detail}", False





def _channel_id_from_url(url: str | None) -> str | None:

    if not url:

        return None

    match = CHANNEL_URL_RE.search(url)

    if not match:

        return None

    return match.group(1)





def _extract_apify_links(item: dict) -> list[dict[str, str]]:

    links: list[dict[str, str]] = []

    seen: set[str] = set()

    for container_key in ("channelDescriptionLinks", "descriptionLinks", "links"):

        raw_links = item.get(container_key)

        if not isinstance(raw_links, list):

            continue

        for link in raw_links:

            if not isinstance(link, dict):

                continue

            _append_link(links, seen, link.get("url") or link.get("href"), link.get("text") or link.get("label"))

    return links





def _profile_from_apify_item(item: dict, *, source_keyword: str | None) -> PlatformCandidateProfile | None:

    channel_url = _normalize_url(item.get("channelUrl") or item.get("inputChannelUrl"))

    channel_name = (item.get("channelName") or item.get("author") or "").strip()

    channel_id = item.get("channelId") or item.get("channelID") or _channel_id_from_url(channel_url)

    if not channel_url and not channel_id and not channel_name:

        return None

    if not channel_url:

        if channel_id:

            channel_url = f"https://www.youtube.com/channel/{channel_id}"

        elif channel_name:

            handle = channel_name.replace(" ", "")

            channel_url = f"https://www.youtube.com/@{handle}" if handle else None

    if not channel_url:

        return None



    username = channel_id or channel_name.replace(" ", "_") or channel_url.rstrip("/").split("/")[-1]

    video_title = (item.get("title") or "").strip()

    video_url = _normalize_url(item.get("url"))

    views = item.get("viewCount") or item.get("views")

    if isinstance(views, str):

        views = parse_count_text(views)

    subscribers = item.get("numberOfSubscribers") or item.get("subscriberCount")

    if isinstance(subscribers, str):

        subscribers = parse_count_text(subscribers)



    external_links = _extract_apify_links(item)

    bio = item.get("channelDescription") or item.get("text") or item.get("description")
    description_signals = _extract_description_signals(bio)
    external_links = _merge_link_dicts(external_links, description_signals.links)

    website = None

    for link in external_links:

        if link.get("type") == "website":

            website = link.get("url")

            break



    about_hydrated = bool(external_links) or bool(bio)
    video_id = extract_video_id(item)
    source_meta = {
            "provider": "apify",
            "actor": settings.apify_youtube_actor_id,
            "source_keyword": source_keyword,
            "video_title": video_title or None,
            "video_id": video_id,
            "about_links_hydrated": about_hydrated,
        }
    if description_signals.email:
        source_meta["email_source"] = "youtube_description"



    return PlatformCandidateProfile(

        platform="youtube",

        username=username,

        profile_url=channel_url,

        display_name=channel_name or None,

        avatar_url=item.get("channelAvatarUrl") or item.get("thumbnailUrl"),

        bio=bio if isinstance(bio, str) else None,

        followers_count=subscribers if isinstance(subscribers, int) else None,

        avg_views=views if isinstance(views, int) else None,

        engagement_rate=engagement_rate_from_metrics(

            views=views if isinstance(views, int) else None,

            likes=item.get("likes") if isinstance(item.get("likes"), int) else None,

            comments=item.get("commentsCount") if isinstance(item.get("commentsCount"), int) else None,

        ),

        website=website,
        email=description_signals.email,

        other_social_links=external_links,

        source_url=video_url,
        source_post_url=video_url,
        recent_post_titles=[video_title] if video_title else [],

        recent_post_urls=[video_url] if video_url else [],

        source_type="keyword_video_channel",

        source_discovery_type="video_channel",

        channel_id=channel_id,

        source_meta=source_meta,

    )





def _apify_proxy_config() -> dict:

    return {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}





def _discovery_deadline(task: CollectionTask | None = None) -> float:

    if task is not None:
        from app.services.competitor_product_discovery import is_competitor_product_task

        if is_competitor_product_task(task):
            return time.perf_counter() + max(
                30,
                settings.competitor_product_platform_timeout_seconds,
            )

    return time.perf_counter() + max(30, settings.youtube_discovery_max_duration_seconds)





class YouTubeApifyProvider:

    platform = "youtube"



    @staticmethod

    def capability() -> PlatformCapability:

        if not settings.is_apify_configured:

            return PlatformCapability(

                platform="youtube",

                label="YouTube",

                status="not_configured",

                message="YouTube Apify 暂未配置（缺少 APIFY_TOKEN）",

                endpoints=[settings.apify_youtube_actor_id],

            )

        return PlatformCapability(

            platform="youtube",

            label="YouTube",

            status="supported",

            message="YouTube 关键词/频道发现走 Apify YouTube Scraper；About 外链优先使用 Actor 返回，缺失时公开页补采",

            endpoints=[settings.apify_youtube_actor_id],

        )



    @staticmethod

    async def discover(

        task: CollectionTask,

        *,

        checkpoint: RunCheckpoint | None = None,

    ) -> PlatformDiscoveryResult:

        _ = checkpoint

        cap = YouTubeApifyProvider.capability()

        if cap.status == "not_configured":

            return PlatformDiscoveryResult(

                platform="youtube",

                fatal=True,

                skipped=True,

                skip_reason=cap.message,

                errors=[cap.message],

            )



        keywords = normalize_keywords([str(k) for k in (task.keywords or [])])
        from app.services.competitor_product_discovery import (
            competitor_discovery_apify_timeout_seconds,
            competitor_discovery_keyword_timeout_seconds,
            filter_competitor_phrase_keywords,
            is_competitor_product_task,
        )

        if is_competitor_product_task(task):
            keywords = filter_competitor_phrase_keywords(keywords)

        input_urls = [u.strip() for u in (task.input_urls or []) if u and str(u).strip()]

        url_profiles = [_profile_from_input_url(u) for u in input_urls]

        url_profiles = [p for p in url_profiles if p]



        if not keywords and not url_profiles and not input_urls:

            msg = "YouTube 采集需要关键词或 YouTube 频道链接"

            return PlatformDiscoveryResult(platform="youtube", errors=[msg], skip_reason=msg)



        limit = discovery_fetch_limit(task)

        profiles: list[PlatformCandidateProfile] = list(url_profiles)

        errors: list[str] = []

        rate_limit_count = 0

        slow_api = False

        discovery_started = time.perf_counter()

        deadline = _discovery_deadline(task)



        await report_discovery_progress(

            phase=STAGE_DISCOVERY,

            discovered_count=len(profiles),

            deduped_count=len(profiles),

            profile_fetched_count=0,

            inserted_count=0,

            provider="apify",

            keywords_completed=0,

            keywords_total=len(keywords),

        )



        max_results = apify_search_max_results(limit=limit)

        total_item_stats = YouTubeDedupeStats()

        keyword_timeout = max(1, settings.youtube_discovery_keyword_timeout_seconds)
        apify_timeout = max(1, settings.apify_youtube_timeout_seconds)
        if is_competitor_product_task(task):
            keyword_timeout = competitor_discovery_keyword_timeout_seconds(keyword_timeout)
            apify_timeout = competitor_discovery_apify_timeout_seconds(apify_timeout)

        concurrency = max(1, min(APIFY_KEYWORD_CONCURRENCY_CAP, settings.youtube_apify_keyword_concurrency))



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



            run_input = {

                "searchQueries": [keyword],

                "maxResults": max_results,

                "maxResultsShorts": 0,

                "maxResultStreams": 0,

                "sortingOrder": "relevance",

                "proxyConfiguration": _apify_proxy_config(),

            }

            try:

                items = await asyncio.wait_for(

                    run_actor_sync(

                        settings.apify_youtube_actor_id,

                        run_input,

                        timeout=apify_timeout,

                        max_retries=settings.apify_youtube_max_retries,

                    ),

                    timeout=keyword_timeout + 5,

                )

            except asyncio.TimeoutError:

                local_slow = True

                _append_error(local_errors, _youtube_apify_timeout_message(keyword=keyword))

                logger.warning("YouTube Apify keyword timeout keyword=%s elapsed=%.2fs", keyword, time.perf_counter() - started)

                return keyword, local_profiles, local_errors, local_rate_limits, local_slow, YouTubeDedupeStats()

            except ApifyError as exc:

                detail = str(exc).strip() or "Apify 请求失败"

                if _is_timeout_error(detail):

                    local_slow = True

                    _append_error(local_errors, _youtube_apify_timeout_message(keyword=keyword))

                elif "(429)" in detail or "429" in detail:

                    local_rate_limits += 1

                    _append_error(local_errors, f"YouTube Apify 限流（关键词「{keyword}」）: {detail}")

                else:

                    _append_error(local_errors, f"YouTube Apify 搜索「{keyword}」: {detail}")

                logger.warning(

                    "YouTube Apify keyword failed keyword=%s elapsed=%.2fs error=%s",

                    keyword,

                    time.perf_counter() - started,

                    detail[:200],

                )

                return keyword, local_profiles, local_errors, local_rate_limits, local_slow, YouTubeDedupeStats()



            raw_items = [item for item in items if isinstance(item, dict)]

            deduped_items, item_stats = dedupe_apify_items(raw_items)

            item_stats.log_summary(context=f"keyword:{keyword}")



            for item in deduped_items:

                profile = _profile_from_apify_item(item, source_keyword=keyword)

                if profile:

                    local_profiles.append(profile)



            elapsed = time.perf_counter() - started

            logger.info(

                "YouTube Apify keyword search keyword=%s elapsed=%.2fs profiles=%d raw_items=%d deduped_items=%d removed=%d",

                keyword,

                elapsed,

                len(local_profiles),

                item_stats.raw_items,

                item_stats.deduped_items,

                item_stats.item_duplicates_removed,

            )

            if not local_profiles and elapsed >= settings.youtube_discovery_slow_threshold_seconds:

                local_slow = True

                local_errors.append(

                    f"YouTube Apify 搜索「{keyword}」耗时 {elapsed:.0f}s 但未返回候选，可能关键词无结果或平台响应慢"

                )

            return keyword, local_profiles, local_errors, local_rate_limits, local_slow, item_stats



        keywords_completed = 0
        timeout_skipped_keywords_count = 0

        for chunk_start in range(0, len(keywords), concurrency):

            if time.perf_counter() >= deadline:

                errors.append(

                    f"YouTube 发现阶段总耗时超过 {settings.youtube_discovery_max_duration_seconds}s，"

                    f"已停止剩余 {len(keywords) - keywords_completed} 个关键词"

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

                    msg, is_timeout = _format_worker_exception(outcome, keyword=chunk[0] if chunk else None)

                    slow_api = slow_api or is_timeout

                    _append_error(errors, msg)

                    continue

                _keyword, local_profiles, local_errors, local_rate_limits, local_slow, item_stats = outcome

                total_item_stats.raw_items += item_stats.raw_items

                total_item_stats.deduped_items += item_stats.deduped_items

                total_item_stats.item_duplicates_removed += item_stats.item_duplicates_removed

                rate_limit_count += local_rate_limits

                slow_api = slow_api or local_slow
                if local_slow:
                    timeout_skipped_keywords_count += 1

                errors.extend(local_errors)

                profiles.extend(local_profiles)

                profiles, _prof_stats = dedupe_youtube_profiles(profiles)

                await report_discovery_progress(

                    phase=STAGE_DISCOVERY,

                    discovered_count=len(profiles),

                    deduped_count=len(profiles),

                    profile_fetched_count=0,

                    rate_limited=rate_limit_count > 0,

                    slow_api=slow_api,

                    rate_limit_note=local_errors[-1] if local_rate_limits and local_errors else None,

                    provider="apify",

                    current_keyword=_keyword,

                    keywords_completed=keywords_completed,

                    keywords_total=len(keywords),
                    timeout_skipped_keywords_count=timeout_skipped_keywords_count,

                    timing_note=local_errors[-1] if local_errors else None,

                )

                if len(profiles) >= limit:

                    break



        if input_urls and not keywords:

            started = time.perf_counter()

            run_input = {

                "startUrls": [{"url": url} for url in input_urls],

                "maxResults": max_results,

                "maxResultsShorts": 0,

                "maxResultStreams": 0,

                "proxyConfiguration": _apify_proxy_config(),

            }

            try:

                items = await asyncio.wait_for(

                    run_actor_sync(

                        settings.apify_youtube_actor_id,

                        run_input,

                        timeout=apify_timeout,

                        max_retries=settings.apify_youtube_max_retries,

                    ),

                    timeout=keyword_timeout + 5,

                )

                raw_items = [item for item in items if isinstance(item, dict)]

                deduped_items, url_item_stats = dedupe_apify_items(raw_items)

                url_item_stats.log_summary(context="url_import")

                total_item_stats.raw_items += url_item_stats.raw_items

                total_item_stats.deduped_items += url_item_stats.deduped_items

                total_item_stats.item_duplicates_removed += url_item_stats.item_duplicates_removed



                for item in deduped_items:

                    profile = _profile_from_apify_item(item, source_keyword=None)

                    if profile:

                        profiles.append(profile)

                profiles, _url_prof_stats = dedupe_youtube_profiles(profiles)

                logger.info(

                    "YouTube Apify url import elapsed=%.2fs profiles=%d raw_items=%d deduped_items=%d",

                    time.perf_counter() - started,

                    len(profiles),

                    url_item_stats.raw_items,

                    url_item_stats.deduped_items,

                )

            except asyncio.TimeoutError:

                slow_api = True

                _append_error(errors, _youtube_apify_timeout_message(url_import=True))

            except ApifyError as exc:

                detail = str(exc).strip() or "Apify 请求失败"

                if _is_timeout_error(detail):

                    slow_api = True

                    _append_error(errors, _youtube_apify_timeout_message(url_import=True))

                else:

                    if "(429)" in detail or "429" in detail:

                        rate_limit_count += 1

                    _append_error(errors, f"YouTube Apify 频道链接采集: {detail}")



        profiles, final_profile_stats = dedupe_youtube_profiles(profiles)

        final_profile_stats.log_summary(context="final_profiles")

        total_item_stats.log_summary(context="task_total_items")

        deduped = profiles[:limit]



        await report_discovery_progress(

            phase=STAGE_HYDRATION,

            discovered_count=len(profiles),

            deduped_count=len(deduped),

            profile_fetched_count=0,

            rate_limited=rate_limit_count > 0,

            slow_api=slow_api,

            provider="apify",

            keywords_completed=keywords_completed,

            keywords_total=len(keywords),
            timeout_skipped_keywords_count=timeout_skipped_keywords_count,

        )



        hydration_started = time.perf_counter()

        needs_about = [

            profile

            for profile in deduped

            if not (profile.source_meta or {}).get("about_links_hydrated")

        ]

        if needs_about:

            deduped = await _hydrate_profiles_about(deduped)

        logger.info(

            "YouTube Apify hydration elapsed=%.2fs profiles=%d needs_about=%d",

            time.perf_counter() - hydration_started,

            len(deduped),

            len(needs_about),

        )



        rate_limited = rate_limit_count > 0

        if rate_limited:

            errors.append(

                f"YouTube Apify 限流 {rate_limit_count} 次；系统已降速重试，"

                f"已发现 {len(profiles)} 个候选，去重 {len(deduped)} 个"

            )



        if not deduped and not profiles:

            if rate_limited:

                empty_reason = "平台接口限流，暂无候选结果"

            elif slow_api or (time.perf_counter() - discovery_started) >= settings.youtube_discovery_slow_threshold_seconds:

                empty_reason = "Apify/API 响应较慢或关键词暂无匹配结果"

            else:

                empty_reason = "关键词/API 暂无候选结果"

            errors.append(f"YouTube 发现阶段结束：{empty_reason}（共搜索 {keywords_completed}/{len(keywords)} 个关键词）")



        await report_discovery_progress(

            phase=STAGE_DISCOVERY,

            discovered_count=len(profiles),

            deduped_count=len(deduped),

            profile_fetched_count=len(deduped),

            rate_limited=rate_limited,

            slow_api=slow_api,

            rate_limit_note=errors[-1] if rate_limited and errors else None,

            provider="apify",

            keywords_completed=keywords_completed,

            keywords_total=len(keywords),
            timeout_skipped_keywords_count=timeout_skipped_keywords_count,

        )



        items = [profile_to_collected(p) for p in deduped]

        logger.info(

            "YouTube Apify discover finished elapsed=%.2fs discovered=%d deduped=%d item_dup_removed=%d profile_dup_removed=%d errors=%d",

            time.perf_counter() - discovery_started,

            len(profiles),

            len(deduped),

            total_item_stats.item_duplicates_removed,

            final_profile_stats.profile_duplicates_removed,

            len(errors),

        )

        errors = [err for err in errors if err and err.strip()]

        return PlatformDiscoveryResult(

            platform="youtube",

            items=items,

            profiles=deduped,

            discovered_count=len(profiles),

            deduped_count=len(deduped),

            profile_fetched_count=len(deduped),

            api_requests=len(keywords) + (1 if input_urls and not keywords else 0),

            errors=errors,

            rate_limited=rate_limited,

            rate_limit_count=rate_limit_count,

            fatal=bool(errors) and not deduped and not rate_limited and not slow_api,

        )

