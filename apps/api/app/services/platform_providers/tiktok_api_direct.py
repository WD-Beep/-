# 文件说明：后端平台采集服务，负责不同平台的数据获取和标准化；当前文件：tiktok api direct
"""TikTok API Direct 平台 provider。"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.api_direct_client import ApiDirectError, ad_get, get_request_count
from app.services.platform_types import PlatformCapability, PlatformCandidateProfile, PlatformDiscoveryResult
from app.services.collection_targets import (
    discovery_fetch_limit,
    overfetch_pages_for_limit,
    target_qualified_count,
)
from app.services.platform_utils import (
    dedupe_profiles,
    engagement_rate_from_metrics,
    profile_to_collected,
    tiktok_pages_param,
    tiktok_region_from_task,
)

logger = logging.getLogger(__name__)

ENDPOINTS = [
    "/v1/tiktok/videos",
    "/v1/tiktok/users",
    "/v1/tiktok/user",
    "/v1/tiktok/video",
]
PROFILE_HYDRATION_UNAVAILABLE = "profile_hydration_unavailable"
PROFILE_HYDRATION_USERS = "api_direct_users"
PROFILE_HYDRATION_SKIPPED = "hydration_skipped_quota"


def _tiktok_profile_url(username: str) -> str:
    handle = username.lstrip("@").strip()
    return f"https://www.tiktok.com/@{handle}"


def _needs_follower_hydration(task: CollectionTask) -> bool:
    return task.min_followers_count is not None and task.min_followers_count > 0


def _api_budget_remaining(platform: str = "tiktok") -> int | None:
    limit = settings.api_direct_max_requests_per_platform
    if limit <= 0:
        return None
    return max(0, limit - get_request_count(platform))


def _tiktok_keyword_search_cap(task: CollectionTask, keyword_count: int) -> int:
    """按目标与额度限制关键词搜索次数，避免视频 API 占满预算。"""
    target = target_qualified_count(task)
    desired = max(2, min(keyword_count, 3 + target // 4))
    remaining = _api_budget_remaining()
    if remaining is None:
        return desired
    # 至少留 60% 预算给主页补采（粉丝数）
    max_for_search = max(1, remaining // 3)
    return max(1, min(desired, max_for_search))


def _tiktok_hydration_cap(task: CollectionTask, *, deduped_count: int) -> int:
    """只补采可能入库的候选数量，达标即停。"""
    if not _needs_follower_hydration(task):
        return 0
    target = target_qualified_count(task)
    desired = min(deduped_count, max(target * 2, target + 4))
    remaining = _api_budget_remaining()
    if remaining is None:
        return desired
    return max(0, min(desired, remaining))


def _prioritize_tiktok_keywords(keywords: list[str]) -> list[str]:
    """短词优先、去重，提高单次搜索命中率。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in sorted(keywords, key=lambda item: (len(item), item.lower())):
        clean = raw.strip().lstrip("#")
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(clean)
    return ordered


def _profile_discovery_priority(profile: PlatformCandidateProfile) -> int:
    views = profile.avg_views or 0
    likes = profile.avg_likes or 0
    comments = profile.avg_comments or 0
    return views + likes * 25 + comments * 50


def _profile_passes_follower_gate(profile: PlatformCandidateProfile, task: CollectionTask) -> bool:
    required = task.min_followers_count
    if required is None:
        return True
    followers = profile.followers_count
    return followers is not None and followers >= required


def _extract_author_from_video(video: dict, *, source_keyword: str | None) -> PlatformCandidateProfile | None:
    author = (video.get("author") or "").strip().lstrip("@")
    if not author:
        return None
    play_count = video.get("play_count")
    likes = video.get("likes")
    comments = video.get("comments")
    return PlatformCandidateProfile(
        platform="tiktok",
        username=author,
        profile_url=_tiktok_profile_url(author),
        display_name=video.get("author_name"),
        avatar_url=video.get("author_avatar"),
        bio=(
            video.get("author_signature")
            or video.get("author_bio")
            or video.get("author_description")
        ),
        followers_count=None,
        avg_views=play_count if isinstance(play_count, int) else None,
        avg_likes=likes if isinstance(likes, int) else None,
        avg_comments=comments if isinstance(comments, int) else None,
        engagement_rate=engagement_rate_from_metrics(
            views=play_count if isinstance(play_count, int) else None,
            likes=likes if isinstance(likes, int) else None,
            comments=comments if isinstance(comments, int) else None,
        ),
        source_url=video.get("url"),
        source_post_url=str(video.get("url")) if video.get("url") else None,
        source_type="keyword_video_author",
        source_discovery_type="video_author",
        source_meta={
            "provider": "api_direct",
            "endpoint": "/v1/tiktok/videos",
            "profile_hydration": PROFILE_HYDRATION_UNAVAILABLE,
            "source_keyword": source_keyword,
            "video_title": video.get("title"),
        },
    )


async def _hydrate_tiktok_profile(
    profile: PlatformCandidateProfile,
    *,
    errors: list[str],
) -> PlatformCandidateProfile:
    handle = (profile.username or "").strip().lstrip("@")
    if not handle:
        return profile
    try:
        data = await ad_get(
            "/v1/tiktok/user",
            params={"username": handle},
            platform="tiktok",
        )
    except ApiDirectError as exc:
        errors.append(f"TikTok 主页补采 @{handle}: {exc}")
        return profile

    match = data.get("user")
    if not isinstance(match, dict):
        users = data.get("users") or []
        match = next(
            (row for row in users if (row.get("username") or "").lower() == handle.lower()),
            None,
        )
    if not match:
        return profile

    followers = match.get("followers")
    if isinstance(followers, (int, float)):
        profile.followers_count = int(followers)
    bio = match.get("bio")
    if isinstance(bio, str) and bio.strip():
        profile.bio = bio.strip()
    nickname = match.get("nickname")
    if isinstance(nickname, str) and nickname.strip():
        profile.display_name = nickname.strip()
    avatar = match.get("avatar")
    if isinstance(avatar, str) and avatar.strip():
        profile.avatar_url = avatar.strip()
    profile_url = match.get("url")
    if isinstance(profile_url, str) and profile_url.strip():
        profile.profile_url = profile_url.strip()
    meta = dict(profile.source_meta or {})
    meta["profile_hydration"] = PROFILE_HYDRATION_USERS
    meta["hydration_endpoint"] = "/v1/tiktok/user"
    profile.source_meta = meta
    if profile.followers_count:
        profile.engagement_rate = engagement_rate_from_metrics(
            views=profile.avg_views,
            likes=profile.avg_likes,
            comments=profile.avg_comments,
            followers=profile.followers_count,
        )
    return profile


class TikTokApiDirectProvider:
    platform = "tiktok"

    @staticmethod
    def capability() -> PlatformCapability:
        if not settings.is_api_direct_configured:
            return PlatformCapability(
                platform="tiktok",
                label="TikTok",
                status="not_configured",
                message="API Direct 暂未配置（缺少 API_DIRECT_API_KEY）",
                endpoints=ENDPOINTS,
            )
        return PlatformCapability(
            platform="tiktok",
            label="TikTok",
            status="supported",
            message="API Direct 已支持（关键词视频搜索 + 按需主页补采粉丝数）",
            endpoints=ENDPOINTS,
        )

    @staticmethod
    async def discover(task: CollectionTask) -> PlatformDiscoveryResult:
        cap = TikTokApiDirectProvider.capability()
        if cap.status == "not_configured":
            return PlatformDiscoveryResult(
                platform="tiktok",
                fatal=True,
                skipped=True,
                skip_reason=cap.message,
                errors=[cap.message],
            )

        keywords = [k.strip().lstrip("#") for k in (task.keywords or []) if k and str(k).strip()]
        if not keywords:
            msg = "TikTok 采集至少需要一个关键词或 hashtag"
            return PlatformDiscoveryResult(
                platform="tiktok",
                errors=[msg],
                skip_reason=msg,
            )

        limit = discovery_fetch_limit(task)
        target = target_qualified_count(task)
        pages = max(tiktok_pages_param(), overfetch_pages_for_limit(limit))
        region = tiktok_region_from_task(task)
        profiles: list[PlatformCandidateProfile] = []
        errors: list[str] = []

        search_keywords = _prioritize_tiktok_keywords(keywords)
        keyword_cap = _tiktok_keyword_search_cap(task, len(search_keywords))
        search_keywords = search_keywords[:keyword_cap]
        if len(search_keywords) < len(keywords):
            skipped = len(keywords) - len(search_keywords)
            errors.append(
                f"TikTok 为节省 API 额度，仅搜索前 {len(search_keywords)} 个关键词（跳过 {skipped} 个）"
            )

        for keyword in search_keywords:
            if _api_budget_remaining() == 0:
                errors.append("TikTok 视频搜索：API 额度已用尽，停止继续搜索")
                break
            if len(profiles) >= limit:
                break
            params: dict[str, str | int] = {"query": keyword, "pages": pages}
            if region:
                params["region"] = region
            try:
                data = await ad_get(
                    "/v1/tiktok/videos",
                    params=params,
                    platform="tiktok",
                )
            except ApiDirectError as exc:
                errors.append(f"TikTok 关键词「{keyword}」: {exc}")
                continue

            for video in data.get("videos") or []:
                if not isinstance(video, dict):
                    continue
                profile = _extract_author_from_video(video, source_keyword=keyword)
                if profile:
                    profiles.append(profile)
                if len(profiles) >= limit:
                    break

        deduped = dedupe_profiles(profiles)[:limit]
        hydrate_cap = _tiktok_hydration_cap(task, deduped_count=len(deduped))
        hydration_target = max(target * 2, target + 4) if _needs_follower_hydration(task) else 0

        hydrated: list[PlatformCandidateProfile] = []
        hydrated_with_followers = 0
        qualified_count = 0
        skipped_hydration = 0

        if hydrate_cap > 0:
            ranked = sorted(deduped, key=_profile_discovery_priority, reverse=True)
            pending = ranked[:hydrate_cap]
            deferred = ranked[hydrate_cap:]

            for profile in pending:
                if _api_budget_remaining() == 0:
                    errors.append("TikTok 主页补采：API 额度已用尽，停止继续补采")
                    break
                if qualified_count >= hydration_target:
                    break
                updated = await _hydrate_tiktok_profile(profile, errors=errors)
                hydrated.append(updated)
                if updated.followers_count is not None:
                    hydrated_with_followers += 1
                if _profile_passes_follower_gate(updated, task):
                    qualified_count += 1

            for profile in deferred:
                meta = dict(profile.source_meta or {})
                meta["profile_hydration"] = PROFILE_HYDRATION_SKIPPED
                profile.source_meta = meta
                skipped_hydration += 1

            if deferred:
                errors.append(
                    f"TikTok 已优先补采热度最高的 {len(pending)} 个作者"
                    f"（跳过 {skipped_hydration} 个以节省 API 额度）"
                )
            hydrated.extend(deferred)
        else:
            hydrated = list(deduped)
            if _needs_follower_hydration(task):
                errors.append("TikTok 无剩余 API 额度用于主页补采粉丝数")

        if deduped and _needs_follower_hydration(task) and hydrated_with_followers == 0:
            errors.append(
                "TikTok 视频作者已发现，但主页补采未获得粉丝数；"
                "请检查 API Direct 额度或稍后重试"
            )

        logger.info(
            "[TikTok] task=%s keywords=%d/%d deduped=%d hydrated=%d qualified=%d api=%d",
            getattr(task, "id", None),
            len(search_keywords),
            len(keywords),
            len(deduped),
            hydrated_with_followers,
            qualified_count,
            get_request_count("tiktok"),
        )

        items = [profile_to_collected(p) for p in hydrated]

        return PlatformDiscoveryResult(
            platform="tiktok",
            items=items,
            profiles=hydrated,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=hydrated_with_followers,
            api_requests=get_request_count("tiktok"),
            errors=errors,
            fatal=bool(errors) and not deduped,
        )
