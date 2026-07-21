# 文件说明：后端平台采集服务，负责不同平台的数据获取和标准化；当前文件：youtube official
"""YouTube official Data API v3 provider and Apify fallback wrapper."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.collection_targets import discovery_fetch_limit
from app.services.discovery_progress import report_discovery_progress
from app.services.http_retry import execute_with_retry
from app.services.platform_providers.youtube_apify import YouTubeApifyProvider
from app.services.platform_providers.youtube_dedupe import dedupe_youtube_profiles, normalize_keywords
from app.services.platform_types import PlatformCandidateProfile, PlatformCapability, PlatformDiscoveryResult
from app.services.platform_utils import engagement_rate_from_metrics, profile_to_collected
from app.services.task_run_progress import STAGE_DISCOVERY, STAGE_HYDRATION

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
ENDPOINTS = [
    f"{YOUTUBE_API_BASE}/search",
    f"{YOUTUBE_API_BASE}/channels",
    f"{YOUTUBE_API_BASE}/videos",
]
CHANNEL_BATCH_SIZE = 50


@dataclass
class YouTubeOfficialError(Exception):
    reason: str
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        return self.message


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _best_thumbnail(snippet: dict[str, Any]) -> str | None:
    thumbnails = snippet.get("thumbnails")
    if not isinstance(thumbnails, dict):
        return None
    for key in ("high", "medium", "default"):
        item = thumbnails.get(key)
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return None


def _youtube_error_reason(status_code: int, payload: Any) -> tuple[str, str]:
    error = payload.get("error") if isinstance(payload, dict) else None
    errors = error.get("errors") if isinstance(error, dict) else None
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    api_reason = str(first.get("reason") or error.get("status") if isinstance(error, dict) else "").strip()
    api_message = str(first.get("message") or error.get("message") if isinstance(error, dict) else "").strip()
    lowered = f"{api_reason} {api_message}".lower()

    if status_code == 403 and any(marker in lowered for marker in ("quotaexceeded", "dailylimitexceeded", "quota")):
        return "quota_exceeded", "YouTube 官方 API 配额已用尽，稍后重试或切换 Apify。"
    if status_code in (401, 403):
        return "auth_error", "YouTube 官方 API 鉴权失败，请检查 YOUTUBE_API_KEY 和 YouTube Data API v3 是否启用。"
    if status_code == 429:
        return "rate_limited", "YouTube 官方 API 限流，已降低请求量。"
    if status_code == 400:
        return "bad_request", f"YouTube 官方 API 请求参数有误：{api_message or api_reason or 'bad request'}"
    if status_code >= 500:
        return "server_error", "YouTube 官方 API 服务暂时不可用。"
    return "request_failed", f"YouTube 官方 API 请求失败（HTTP {status_code}）：{api_message or api_reason or 'unknown error'}"


def _result_for_official_error(exc: YouTubeOfficialError, *, api_requests: int) -> PlatformDiscoveryResult:
    return PlatformDiscoveryResult(
        platform="youtube",
        fatal=True,
        skipped=exc.reason in {"missing_key", "quota_exceeded", "auth_error", "rate_limited", "network_error", "timeout", "server_error"},
        skip_reason=exc.message,
        errors=[exc.message],
        api_requests=api_requests,
        rate_limited=exc.reason == "rate_limited",
        rate_limit_count=1 if exc.reason in {"quota_exceeded", "rate_limited"} else 0,
        provider_availability_state={
            "youtube": {
                "status": "provider_unavailable",
                "reason": exc.reason,
                "message": exc.message,
                "api_calls": api_requests,
            }
        },
    )


def _profile_from_channel(channel: dict[str, Any], *, source_keyword: str | None) -> PlatformCandidateProfile | None:
    channel_id = str(channel.get("id") or "").strip()
    if not channel_id:
        return None

    snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
    statistics = channel.get("statistics") if isinstance(channel.get("statistics"), dict) else {}
    title = str(snippet.get("title") or "").strip()
    custom_url = str(snippet.get("customUrl") or "").strip()
    username = custom_url or title or channel_id
    subscriber_count = None if statistics.get("hiddenSubscriberCount") is True else _to_int(statistics.get("subscriberCount"))
    video_count = _to_int(statistics.get("videoCount"))
    view_count = _to_int(statistics.get("viewCount"))
    description = str(snippet.get("description") or "").strip() or None

    return PlatformCandidateProfile(
        platform="youtube",
        username=username,
        profile_url=f"https://www.youtube.com/channel/{channel_id}",
        display_name=title or None,
        avatar_url=_best_thumbnail(snippet),
        bio=description,
        followers_count=subscriber_count,
        avg_views=(view_count // video_count) if view_count is not None and video_count else None,
        engagement_rate=engagement_rate_from_metrics(views=view_count, likes=None, comments=None, followers=subscriber_count),
        source_type="official_keyword_channel",
        source_discovery_type="keyword_channel",
        channel_id=channel_id,
        source_meta={
            "provider": "youtube_official",
            "source": "youtube_official",
            "source_keyword": source_keyword,
            "channel_id": channel_id,
            "published_at": snippet.get("publishedAt"),
            "custom_url": custom_url or None,
            "country": snippet.get("country"),
            "video_count": video_count,
            "view_count": view_count,
            "hidden_subscriber_count": statistics.get("hiddenSubscriberCount") is True,
        },
    )


def _fallback_reason(result: PlatformDiscoveryResult) -> str | None:
    state = (result.provider_availability_state or {}).get("youtube")
    reason = str((state or {}).get("reason") or "").strip()
    if reason:
        return reason
    text = " ".join([result.skip_reason or "", *(result.errors or [])]).lower()
    if "未配置" in text or "youtube_api_key" in text or "missing" in text:
        return "missing_key"
    if "配额" in text or "quota" in text:
        return "quota_exceeded"
    if "限流" in text or "429" in text or "rate" in text:
        return "rate_limited"
    if "timeout" in text or "超时" in text:
        return "timeout"
    return None


def _should_fallback(result: PlatformDiscoveryResult) -> bool:
    if result.profiles or result.items:
        return False
    return _fallback_reason(result) in {
        "missing_key",
        "quota_exceeded",
        "auth_error",
        "rate_limited",
        "timeout",
        "network_error",
        "server_error",
        "request_failed",
    }


def _fallback_message(reason: str | None) -> str:
    if reason == "missing_key":
        return "未配置 YOUTUBE_API_KEY，已切换 Apify"
    if reason == "quota_exceeded":
        return "官方 API 配额已用尽，已切换 Apify"
    if reason == "rate_limited":
        return "官方 API 限流，已切换 Apify"
    if reason in {"timeout", "network_error", "server_error", "request_failed", "auth_error"}:
        return "官方 API 请求失败，已切换 Apify"
    return "官方 API 不可用，已切换 Apify"


class YouTubeOfficialProvider:
    platform = "youtube"

    @staticmethod
    def capability() -> PlatformCapability:
        if not settings.is_youtube_configured:
            return PlatformCapability(
                platform="youtube",
                label="YouTube",
                status="not_configured",
                message="未配置 YOUTUBE_API_KEY，YouTube 官方 Data API v3 不可用。",
                endpoints=ENDPOINTS,
            )
        return PlatformCapability(
            platform="youtube",
            label="YouTube",
            status="supported",
            message="YouTube 官方 Data API v3 已配置，关键词发现优先使用 search.list + channels.list 小批量采集。",
            endpoints=ENDPOINTS,
        )

    @staticmethod
    async def _get_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {**params, "key": settings.youtube_api_key}
        url = f"{YOUTUBE_API_BASE}/{path}"
        timeout = max(1, settings.youtube_official_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await execute_with_retry(
                    lambda: client.get(url, params=query),
                    label=f"YouTube official {path}",
                    max_retries=settings.youtube_official_max_retries,
                    backoff_seconds=settings.youtube_official_retry_backoff_seconds,
                )
        except httpx.TimeoutException as exc:
            raise YouTubeOfficialError("timeout", "YouTube 官方 API 请求超时，已降低请求量后仍失败。") from exc
        except (httpx.NetworkError, httpx.ConnectError) as exc:
            raise YouTubeOfficialError("network_error", "YouTube 官方 API 网络请求失败，请检查服务器网络。") from exc

        if response.status_code >= 400:
            try:
                payload: Any = response.json()
            except ValueError:
                payload = {}
            reason, message = _youtube_error_reason(response.status_code, payload)
            raise YouTubeOfficialError(reason, message, response.status_code)

        data = response.json()
        if not isinstance(data, dict):
            raise YouTubeOfficialError("request_failed", "YouTube 官方 API 返回格式异常。")
        return data

    @staticmethod
    async def _search_channel_ids(keyword: str) -> tuple[list[str], int]:
        max_results = max(1, min(50, settings.youtube_official_max_results_per_keyword))
        max_pages = max(1, settings.youtube_official_search_max_pages)
        channel_ids: list[str] = []
        seen: set[str] = set()
        page_token: str | None = None
        api_requests = 0

        for _page in range(max_pages):
            params: dict[str, Any] = {
                "part": "snippet",
                "q": keyword,
                "type": "channel,video",
                "maxResults": max_results,
                "safeSearch": "none",
            }
            if page_token:
                params["pageToken"] = page_token
            data = await YouTubeOfficialProvider._get_json("search", params)
            api_requests += 1
            for item in data.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id") if isinstance(item.get("id"), dict) else {}
                snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
                channel_id = item_id.get("channelId") or snippet.get("channelId")
                if isinstance(channel_id, str) and channel_id.strip() and channel_id not in seen:
                    seen.add(channel_id)
                    channel_ids.append(channel_id)
            page_token = str(data.get("nextPageToken") or "").strip() or None
            if not page_token:
                break
        return channel_ids, api_requests

    @staticmethod
    async def _fetch_channels(channel_ids: list[str]) -> tuple[list[dict[str, Any]], int]:
        channels: list[dict[str, Any]] = []
        api_requests = 0
        for start in range(0, len(channel_ids), CHANNEL_BATCH_SIZE):
            chunk = channel_ids[start : start + CHANNEL_BATCH_SIZE]
            if not chunk:
                continue
            data = await YouTubeOfficialProvider._get_json(
                "channels",
                {
                    "part": "snippet,statistics",
                    "id": ",".join(chunk),
                    "maxResults": len(chunk),
                },
            )
            api_requests += 1
            channels.extend([item for item in data.get("items") or [] if isinstance(item, dict)])
        return channels, api_requests

    @staticmethod
    async def discover(
        task: CollectionTask,
        *,
        checkpoint=None,
    ) -> PlatformDiscoveryResult:
        _ = checkpoint
        if not settings.is_youtube_configured:
            return _result_for_official_error(
                YouTubeOfficialError("missing_key", "未配置 YOUTUBE_API_KEY，YouTube 官方 Data API v3 不可用。"),
                api_requests=0,
            )

        keywords = normalize_keywords([str(k) for k in (task.keywords or [])])
        input_urls = [u.strip() for u in (task.input_urls or []) if u and str(u).strip()]
        if not keywords and input_urls:
            return PlatformDiscoveryResult(
                platform="youtube",
                errors=["YouTube 官方 API 暂仅支持关键词发现；频道链接导入请使用 auto/apify fallback。"],
                skip_reason="YouTube 官方 API 暂仅支持关键词发现；频道链接导入请使用 auto/apify fallback。",
                provider_availability_state={"youtube": {"reason": "request_failed"}},
            )
        if not keywords:
            msg = "YouTube 采集需要关键词或 YouTube 频道链接。"
            return PlatformDiscoveryResult(platform="youtube", errors=[msg], skip_reason=msg)

        limit = discovery_fetch_limit(task)
        api_requests = 0
        profiles: list[PlatformCandidateProfile] = []
        errors: list[str] = []

        await report_discovery_progress(
            phase=STAGE_DISCOVERY,
            discovered_count=0,
            deduped_count=0,
            profile_fetched_count=0,
            provider="youtube_official",
            keywords_completed=0,
            keywords_total=len(keywords),
        )

        try:
            for index, keyword in enumerate(keywords):
                if len(profiles) >= limit:
                    break
                await report_discovery_progress(
                    phase=STAGE_DISCOVERY,
                    discovered_count=len(profiles),
                    deduped_count=len(profiles),
                    profile_fetched_count=0,
                    provider="youtube_official",
                    current_keyword=keyword,
                    keywords_completed=index,
                    keywords_total=len(keywords),
                )
                channel_ids, search_requests = await YouTubeOfficialProvider._search_channel_ids(keyword)
                api_requests += search_requests
                channels, channel_requests = await YouTubeOfficialProvider._fetch_channels(channel_ids)
                api_requests += channel_requests
                for channel in channels:
                    profile = _profile_from_channel(channel, source_keyword=keyword)
                    if profile:
                        profiles.append(profile)
                profiles, _stats = dedupe_youtube_profiles(profiles)
                await report_discovery_progress(
                    phase=STAGE_DISCOVERY,
                    discovered_count=len(profiles),
                    deduped_count=len(profiles),
                    profile_fetched_count=0,
                    provider="youtube_official",
                    current_keyword=keyword,
                    keywords_completed=index + 1,
                    keywords_total=len(keywords),
                )
        except YouTubeOfficialError as exc:
            return _result_for_official_error(exc, api_requests=api_requests)

        profiles, _stats = dedupe_youtube_profiles(profiles)
        deduped = profiles[:limit]
        if not deduped:
            errors.append(f"YouTube 官方 API 未找到匹配频道（共搜索 {len(keywords)} 个关键词）。")

        await report_discovery_progress(
            phase=STAGE_HYDRATION,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=len(deduped),
            provider="youtube_official",
            keywords_completed=min(len(keywords), len(keywords)),
            keywords_total=len(keywords),
        )

        items = [profile_to_collected(profile) for profile in deduped]
        for item in items:
            if "youtube_official" not in item.tags:
                item.tags.append("youtube_official")

        return PlatformDiscoveryResult(
            platform="youtube",
            items=items,
            profiles=deduped,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=len(deduped),
            api_requests=api_requests,
            errors=errors,
            fatal=False,
        )


class YouTubeAutoProvider:
    platform = "youtube"

    @staticmethod
    def capability() -> PlatformCapability:
        official = YouTubeOfficialProvider.capability()
        if official.status == "supported":
            return official
        apify = YouTubeApifyProvider.capability()
        if apify.status == "supported":
            apify.message = f"{official.message} auto 模式将 fallback 到 Apify。"
            return apify
        return official

    @staticmethod
    async def discover(
        task: CollectionTask,
        *,
        checkpoint=None,
    ) -> PlatformDiscoveryResult:
        official = await YouTubeOfficialProvider.discover(task, checkpoint=checkpoint)
        if not _should_fallback(official):
            return official

        reason = _fallback_reason(official)
        fallback_note = _fallback_message(reason)
        logger.warning("YouTube official unavailable, fallback to Apify: %s", fallback_note)
        apify = await YouTubeApifyProvider.discover(task, checkpoint=checkpoint)
        apify.api_requests += official.api_requests
        fallback_success = bool(apify.profiles or apify.items)
        if fallback_success:
            apify.fatal = False
        note = "YouTube 官方 API 不可用，已 fallback Apify，最终成功" if fallback_success else fallback_note
        apify.errors = [note, *(official.errors or []), *(apify.errors or [])]
        apify.provider_availability_state.update(official.provider_availability_state or {})
        state = apify.provider_availability_state.setdefault("youtube", {})
        state["actual_provider"] = "apify"
        state["fallback_provider"] = "apify"
        state["fallback_success"] = fallback_success
        state["fallback_note"] = note
        return apify
