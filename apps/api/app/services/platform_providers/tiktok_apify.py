"""TikTok Apify 平台 provider（clockworks/tiktok-scraper）。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.apify_client import ApifyError, run_actor_sync
from app.services.collection_targets import discovery_fetch_limit
from app.services.concurrency import map_bounded
from app.services.platform_types import PlatformCapability, PlatformCandidateProfile, PlatformDiscoveryResult
from app.services.task_run_progress import classify_provider_unavailable_state
from app.services.platform_utils import (
    dedupe_profiles,
    engagement_rate_from_metrics,
    parse_count_text,
    profile_to_collected,
)
from app.services.contact_discovery import extract_emails_from_text, normalize_email

from app.services.platform_providers.tiktok_api_direct import _tiktok_profile_url

logger = logging.getLogger(__name__)


def _actor_id(value: str | None, fallback: str | None = None) -> str:
    chosen = (value or "").strip() or (fallback or "").strip()
    return chosen or settings.apify_tiktok_actor_id


def _main_search_actor() -> str:
    return _actor_id(getattr(settings, "apify_tiktok_scraper_actor_id", ""), settings.apify_tiktok_actor_id)


def _hashtag_actor() -> str:
    return _actor_id(getattr(settings, "apify_tiktok_hashtag_actor_id", ""), _main_search_actor())


def _video_actor() -> str:
    return _actor_id(getattr(settings, "apify_tiktok_video_actor_id", ""), _main_search_actor())


def _profile_actor() -> str:
    return _actor_id(getattr(settings, "apify_tiktok_profile_actor_id", ""), _main_search_actor())


def _fallback_actor() -> str:
    return _actor_id(getattr(settings, "apify_tiktok_fallback_actor_id", ""), settings.apify_tiktok_actor_id)


def _get_nested(item: dict, *paths: str) -> Any:
    for path in paths:
        current: Any = item
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return current
    return None


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        return parse_count_text(value)
    return None


def _normalize_tiktok_username(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lstrip("@")
    return text or None


def _run_id_from_items(items: list[dict]) -> str | None:
    for item in items:
        for key in ("runId", "run_id", "apifyRunId", "actorRunId"):
            value = item.get(key)
            if value:
                return str(value)
    return None


def _is_tiktok_video_url(url: str | None) -> bool:
    text = (url or "").lower()
    return "tiktok.com" in text and ("/video/" in text or "/t/" in text)


def _is_tiktok_profile_url(url: str | None) -> bool:
    text = (url or "").lower()
    return "tiktok.com/@" in text and not _is_tiktok_video_url(text)


def _username_from_profile_url(url: str | None) -> str | None:
    text = (url or "").strip()
    if "/@" not in text:
        return None
    return text.split("/@", 1)[-1].split("/", 1)[0].split("?", 1)[0].strip() or None


async def _run_tiktok_actor(
    actor_id: str,
    run_input: dict,
    *,
    timeout: int,
    max_retries: int,
    memory_mbytes: int | None = None,
) -> tuple[list[dict], str, str | None]:
    primary = _actor_id(actor_id, _main_search_actor())
    try:
        items = await run_actor_sync(
            primary,
            run_input,
            timeout=timeout,
            max_retries=max_retries,
            memory_mbytes=memory_mbytes,
        )
        return items, primary, None
    except ApifyError as exc:
        fallback = _fallback_actor()
        if not fallback or fallback.replace("/", "~") == primary.replace("/", "~"):
            raise
        items = await run_actor_sync(
            fallback,
            run_input,
            timeout=timeout,
            max_retries=max_retries,
            memory_mbytes=memory_mbytes,
        )
        return items, fallback, str(exc)


async def _run_tiktok_actor_direct(
    actor_id: str,
    run_input: dict,
    *,
    timeout: int,
    max_retries: int,
    memory_mbytes: int | None = None,
) -> tuple[list[dict], str]:
    primary = _actor_id(actor_id, _main_search_actor())
    items = await run_actor_sync(
        primary,
        run_input,
        timeout=timeout,
        max_retries=max_retries,
        memory_mbytes=memory_mbytes,
    )
    return items, primary


def _same_actor(left: str | None, right: str | None) -> bool:
    return (left or "").strip().replace("/", "~").lower() == (right or "").strip().replace("/", "~").lower()


def _is_memory_limit_error(message: str) -> bool:
    lowered = (message or "").lower()
    return "memory-limit-exceeded" in lowered or "memory limit" in lowered or "内存" in lowered


def _is_timeout_error(message: str) -> bool:
    lowered = (message or "").lower()
    return "timeout" in lowered or "超时" in message or "瓒呮椂" in message


def _author_meta(item: dict) -> dict:
    meta = item.get("authorMeta")
    if isinstance(meta, dict):
        return meta
    return {}


def _profile_from_apify_item(
    item: dict,
    *,
    source_keyword: str | None,
    source_hashtag: str | None = None,
    source_input_url: str | None = None,
    actor_id: str | None = None,
    discovery_type: str = "video_author",
) -> PlatformCandidateProfile | None:
    meta = _author_meta(item)
    author = _normalize_tiktok_username(
        _get_nested(
            item,
            "authorMeta.name",
            "authorMeta.uniqueId",
            "author.uniqueId",
            "author.username",
            "author.name",
            "user.uniqueId",
            "user.username",
            "username",
            "uniqueId",
            "author",
        )
    )

    if not author:
        return None

    play_count = _parse_int(_get_nested(item, "playCount", "stats.playCount", "stats.play_count", "play_count", "views", "avgViews"))
    likes = _parse_int(_get_nested(item, "diggCount", "stats.diggCount", "stats.likeCount", "stats.likes", "likes", "avgLikes"))
    comments = _parse_int(_get_nested(item, "commentCount", "stats.commentCount", "stats.comments", "comments", "avgComments"))
    followers = _parse_int(
        _get_nested(
            item,
            "authorMeta.fans",
            "authorMeta.followers",
            "authorStats.followerCount",
            "author.followers",
            "stats.followerCount",
            "followers",
            "followerCount",
        )
    )
    following = _parse_int(_get_nested(item, "authorMeta.following", "authorStats.followingCount", "following", "followingCount"))
    hearts = _parse_int(_get_nested(item, "authorMeta.heart", "authorStats.heartCount", "heart", "hearts", "total_likes", "totalLikes"))
    bio = _get_nested(item, "authorMeta.signature", "author.signature", "user.signature", "signature", "bio", "desc")
    caption = _get_nested(item, "text", "desc", "description", "caption", "title")
    avatar = _get_nested(item, "authorMeta.avatar", "author.avatar", "author.avatarThumb", "avatar", "avatarUrl")
    video_url = _get_nested(item, "webVideoUrl", "url", "videoUrl", "video.url")
    profile_url = _get_nested(item, "authorMeta.profileUrl", "author.profileUrl", "profileUrl", "profile_url")
    if not isinstance(profile_url, str) or "tiktok.com" not in profile_url:
        profile_url = _tiktok_profile_url(author)
    display_name = _get_nested(item, "authorMeta.nickName", "authorMeta.nickname", "author.nickname", "nickname", "display_name")
    email = None
    for value in (item.get("email"), item.get("businessEmail"), bio, caption):
        normalized = normalize_email(value) if isinstance(value, str) else None
        if normalized:
            email = normalized
            break
        if isinstance(value, str):
            found = extract_emails_from_text(value, "tiktok_bio")
            if found:
                email = found[0].email
                break

    source_meta = {
        "provider": "apify",
        "actor": actor_id or settings.apify_tiktok_actor_id,
        "source_keyword": source_keyword,
        "source_hashtag": source_hashtag,
        "source_caption": caption if isinstance(caption, str) else None,
        "source_post_url": video_url if isinstance(video_url, str) else None,
        "source_input_url": source_input_url,
        "following_count": following,
        "total_likes": hearts,
        "run_id": item.get("runId") or item.get("run_id"),
    }
    if email:
        source_meta["email_source"] = "tiktok_public_text"

    return PlatformCandidateProfile(
        platform="tiktok",
        username=author,
        profile_url=profile_url,
        display_name=display_name if isinstance(display_name, str) else None,
        avatar_url=avatar if isinstance(avatar, str) else None,
        bio=bio if isinstance(bio, str) else None,
        followers_count=followers,
        avg_views=play_count,
        avg_likes=likes,
        avg_comments=comments,
        engagement_rate=engagement_rate_from_metrics(
            views=play_count,
            likes=likes,
            comments=comments,
            followers=followers,
        ),
        website=_get_nested(item, "website", "bioLink.link", "bioLink.url"),
        email=email,
        recent_post_titles=[caption] if isinstance(caption, str) and caption else [],
        recent_post_urls=[video_url] if isinstance(video_url, str) and video_url else [],
        source_url=video_url if isinstance(video_url, str) else source_input_url,
        source_post_url=video_url if isinstance(video_url, str) else None,
        source_input_url=source_input_url,
        source_caption=caption if isinstance(caption, str) else None,
        source_hashtag=source_hashtag,
        source_type="keyword_video_author" if not source_input_url else "input_url",
        source_discovery_type=discovery_type,
        source_meta={key: value for key, value in source_meta.items() if value is not None},
    )


async def scrape_tiktok_profile(
    *,
    username: str | None = None,
    profile_url: str | None = None,
) -> tuple[PlatformCandidateProfile | None, str | None]:
    handle = _normalize_tiktok_username(username) or _username_from_profile_url(profile_url)
    url = (profile_url or "").strip() or (_tiktok_profile_url(handle) if handle else "")
    if not handle and not url:
        return None, "missing_tiktok_profile_input"
    run_input = {
        "profiles": [url or handle],
        "usernames": [handle] if handle else [],
        "startUrls": [{"url": url}] if url else [],
        "resultsPerPage": 12,
        "shouldDownloadVideos": False,
        "shouldDownloadAvatars": False,
        "shouldDownloadCovers": False,
    }
    try:
        items, actor_id = await _run_tiktok_actor_direct(
            _profile_actor(),
            run_input,
            timeout=max(1, settings.apify_tiktok_timeout_seconds),
            max_retries=settings.apify_tiktok_max_retries,
            memory_mbytes=max(512, settings.tiktok_apify_memory_mbytes),
        )
        fallback_error = None
    except Exception as exc:
        return None, str(exc).strip() or exc.__class__.__name__

    dict_items = [item for item in items if isinstance(item, dict)]
    profile = None
    for item in dict_items:
        profile = _profile_from_apify_item(
            item,
            source_keyword=None,
            source_input_url=url or profile_url,
            actor_id=actor_id,
            discovery_type="profile_recrawl",
        )
        if profile:
            break
    if not profile:
        return None, "missing_profile_detail"
    meta = dict(profile.source_meta or {})
    meta["tiktok_profile_recrawl"] = {
        "actor": actor_id,
        "run_id": _run_id_from_items(dict_items),
        "input_count": 1,
        "success_count": 1,
        "error": fallback_error,
    }
    profile.source_meta = meta
    return profile, None


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
                endpoints=[
                    _main_search_actor(),
                    _hashtag_actor(),
                    _profile_actor(),
                    _video_actor(),
                    _fallback_actor(),
                ],
            )
        return PlatformCapability(
            platform="tiktok",
            label="TikTok",
            status="supported",
            message="TikTok 关键词/hashtag 视频搜索走 Apify TikTok Scraper",
            endpoints=[
                _main_search_actor(),
                _hashtag_actor(),
                _profile_actor(),
                _video_actor(),
                _fallback_actor(),
            ],
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

        raw_keywords = [str(k).strip() for k in (task.keywords or []) if k and str(k).strip()]
        keywords = [k.lstrip("#") for k in raw_keywords]
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
            is_hashtag = f"#{keyword}".lower() in {value.lower() for value in raw_keywords} or " " not in keyword
            actor_id = _hashtag_actor() if is_hashtag else _main_search_actor()

            def _run_input(results_per_page: int) -> dict:
                value: dict = {
                    "searchQueries": [keyword],
                    "hashtags": [keyword] if is_hashtag else [],
                    "resultsPerPage": results_per_page,
                    "shouldDownloadVideos": False,
                    "shouldDownloadAvatars": False,
                    "shouldDownloadCovers": False,
                }
                return value

            run_input = _run_input(max_results)

            fallback_diagnostics: dict | None = None

            async def _run_search(current_input: dict, *, current_memory: int) -> tuple[list[dict], str, str | None]:
                nonlocal fallback_diagnostics
                try:
                    items, used_actor = await asyncio.wait_for(
                        _run_tiktok_actor_direct(
                            actor_id,
                            current_input,
                            timeout=apify_timeout,
                            max_retries=settings.apify_tiktok_max_retries,
                            memory_mbytes=current_memory,
                        ),
                        timeout=keyword_timeout + 5,
                    )
                    return items, used_actor, None
                except asyncio.TimeoutError:
                    detail = f"timeout after {keyword_timeout}s"
                    items, used_actor, fallback_diagnostics = await _run_fallback_search(
                        current_input,
                        current_memory=current_memory,
                        primary_error=detail,
                    )
                    return items, used_actor, detail
                except ApifyError as exc:
                    detail = str(exc)
                    if "(429)" in detail or "429" in detail:
                        raise
                    items, used_actor, fallback_diagnostics = await _run_fallback_search(
                        current_input,
                        current_memory=current_memory,
                        primary_error=detail,
                    )
                    return items, used_actor, detail

            async def _run_fallback_search(
                current_input: dict,
                *,
                current_memory: int,
                primary_error: str,
            ) -> tuple[list[dict], str, dict]:
                fallback_actors: list[str] = []
                hashtag_actor = _hashtag_actor()
                generic_fallback = _fallback_actor()
                if not _same_actor(actor_id, hashtag_actor):
                    fallback_actors.append(hashtag_actor)
                if generic_fallback and all(
                    not _same_actor(generic_fallback, existing)
                    for existing in [actor_id, *fallback_actors]
                ):
                    fallback_actors.append(generic_fallback)

                last_error = primary_error
                for fallback_actor in fallback_actors:
                    try:
                        items, used_actor = await asyncio.wait_for(
                            _run_tiktok_actor_direct(
                                fallback_actor,
                                current_input,
                                timeout=apify_timeout,
                                max_retries=settings.apify_tiktok_max_retries,
                                memory_mbytes=current_memory,
                            ),
                            timeout=keyword_timeout + 5,
                        )
                        return items, used_actor, {
                            "primary_actor": actor_id,
                            "fallback_actor": used_actor,
                            "error": primary_error,
                        }
                    except Exception as exc:
                        last_error = str(exc).strip() or exc.__class__.__name__
                        local_errors.append(
                            f"query {keyword}: TikTok Apify fallback actor {fallback_actor} failed: {last_error}"
                        )
                raise ApifyError(last_error)

            try:
                items, used_actor_id, fallback_error = await _run_search(run_input, current_memory=memory_mbytes)
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
                        items, used_actor_id, fallback_error = await _run_search(_run_input(retry_results), current_memory=retry_memory)
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
                source_hashtag = keyword if is_hashtag or _same_actor(used_actor_id, _hashtag_actor()) else None
                profile = _profile_from_apify_item(
                    item,
                    source_keyword=None if source_hashtag else keyword,
                    source_hashtag=source_hashtag,
                    actor_id=used_actor_id,
                    discovery_type="hashtag_video_author" if source_hashtag else "video_author",
                )
                if profile:
                    if fallback_diagnostics:
                        profile.source_meta["tiktok_actor_fallback"] = fallback_diagnostics
                    local_profiles.append(profile)
            if fallback_error:
                local_errors.append(f"TikTok Apify fallback used after primary failed: {fallback_error}")

            logger.info(
                "TikTok Apify keyword search keyword=%s elapsed=%.2fs profiles=%d items=%d",
                keyword,
                time.perf_counter() - started,
                len(local_profiles),
                len(items),
            )
            return keyword, local_profiles, local_errors, local_rate_limits

        async def _discover_input_url(url: str) -> tuple[str, list[PlatformCandidateProfile], list[str], int]:
            local_profiles: list[PlatformCandidateProfile] = []
            local_errors: list[str] = []
            local_rate_limits = 0
            started = time.perf_counter()

            if _is_tiktok_video_url(url):
                run_input = {
                    "startUrls": [{"url": url}],
                    "postURLs": [url],
                    "resultsPerPage": 1,
                    "shouldDownloadVideos": False,
                    "shouldDownloadAvatars": False,
                    "shouldDownloadCovers": False,
                }
                try:
                    items, used_actor_id, fallback_error = await asyncio.wait_for(
                        _run_tiktok_actor(
                            _video_actor(),
                            run_input,
                            timeout=apify_timeout,
                            max_retries=settings.apify_tiktok_max_retries,
                            memory_mbytes=memory_mbytes,
                        ),
                        timeout=keyword_timeout + 5,
                    )
                except Exception as exc:
                    local_errors.append(f"url {url}: TikTok video actor error: {exc}")
                    return url, local_profiles, local_errors, local_rate_limits

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    profile = _profile_from_apify_item(
                        item,
                        source_keyword=None,
                        source_input_url=url,
                        actor_id=used_actor_id,
                        discovery_type="video_author",
                    )
                    if profile:
                        local_profiles.append(profile)
                if fallback_error:
                    local_errors.append(f"TikTok Apify fallback used after primary failed: {fallback_error}")
                logger.info(
                    "TikTok Apify video url url=%s elapsed=%.2fs profiles=%d items=%d",
                    url,
                    time.perf_counter() - started,
                    len(local_profiles),
                    len(items),
                )
                return url, local_profiles, local_errors, local_rate_limits

            if _is_tiktok_profile_url(url):
                profile, error = await scrape_tiktok_profile(profile_url=url)
                if profile:
                    meta = dict(profile.source_meta or {})
                    meta["source_input_url"] = url
                    profile.source_input_url = url
                    profile.source_type = "input_url"
                    profile.source_discovery_type = "profile_url"
                    profile.source_meta = meta
                    local_profiles.append(profile)
                elif error:
                    local_errors.append(f"url {url}: TikTok profile actor error: {error}")
                return url, local_profiles, local_errors, local_rate_limits

            return url, local_profiles, [f"url {url}: unsupported TikTok URL"], local_rate_limits

        if input_urls:
            tiktok_urls = [url for url in input_urls if "tiktok.com" in url.lower()]
            for chunk_start in range(0, len(tiktok_urls), concurrency):
                if len(profiles) >= limit:
                    break
                chunk = tiktok_urls[chunk_start : chunk_start + concurrency]
                outcomes = await map_bounded(chunk, _discover_input_url, concurrency=len(chunk))
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        errors.append(str(outcome))
                        continue
                    _url, local_profiles, local_errors, local_rate_limits = outcome
                    attempted_queries += 1
                    rate_limit_count += local_rate_limits
                    errors.extend(local_errors)
                    for profile in local_profiles:
                        if len(profiles) >= limit:
                            break
                        profiles.append(profile)
                    if len(profiles) >= limit:
                        break

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
                if local_rate_limits:
                    provider_unavailable_state = {
                        "status": "provider_unavailable",
                        "reason": "rate_limit",
                        "message": "TikTok Apify rate limit; skipped remaining TikTok queries for this run",
                        "api_calls": attempted_queries,
                    }
                if any(_is_memory_limit_error(err) for err in local_errors):
                    provider_unavailable_state = {
                        "status": "provider_unavailable",
                        "reason": "apify_memory_limit_exceeded",
                        "message": "Apify 内存额度已满/并发 actor 过多，已短路跳过后续 TikTok query",
                        "api_calls": attempted_queries,
                    }
                elif any(_is_timeout_error(err) for err in local_errors):
                    provider_unavailable_state = classify_provider_unavailable_state(
                        "tiktok",
                        next(err for err in local_errors if _is_timeout_error(err)),
                        api_calls=attempted_queries,
                    )
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
