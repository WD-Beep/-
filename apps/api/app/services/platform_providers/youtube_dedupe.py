"""YouTube Apify / 发现结果去重工具。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import platform_identity_key

logger = logging.getLogger(__name__)

_YOUTUBE_VIDEO_ID_RE = re.compile(
    r"(?:[?&]v=|/embed/|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})"
)


@dataclass
class YouTubeDedupeStats:
    raw_items: int = 0
    deduped_items: int = 0
    item_duplicates_removed: int = 0
    raw_profiles: int = 0
    deduped_profiles: int = 0
    profile_duplicates_removed: int = 0
    duplicate_keys: list[str] = field(default_factory=list)

    def log_summary(self, *, context: str) -> None:
        logger.info(
            "YouTube dedupe [%s] items %d -> %d (-%d) profiles %d -> %d (-%d)",
            context,
            self.raw_items,
            self.deduped_items,
            self.item_duplicates_removed,
            self.raw_profiles,
            self.deduped_profiles,
            self.profile_duplicates_removed,
        )


def extract_video_id(item: dict) -> str | None:
    """从 Apify item 或 URL 提取 YouTube videoId。"""
    for key in ("videoId", "videoID", "id"):
        raw = item.get(key)
        if isinstance(raw, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", raw.strip()):
            return raw.strip()
    url = str(item.get("url") or item.get("videoUrl") or "").strip()
    if url:
        match = _YOUTUBE_VIDEO_ID_RE.search(url)
        if match:
            return match.group(1)
    return None


def apify_item_dedupe_key(item: dict) -> str | None:
    """
    Apify 原始 item 唯一键，优先级：
    1. videoId
    2. url
    3. channelId + title
    """
    video_id = extract_video_id(item)
    if video_id:
        return f"video:{video_id}"

    url = str(item.get("url") or item.get("videoUrl") or "").strip().lower()
    if url:
        return f"url:{url.rstrip('/')}"

    channel_id = str(item.get("channelId") or item.get("channelID") or "").strip()
    title = str(item.get("title") or "").strip().lower()
    if channel_id and title:
        return f"channel_title:{channel_id.lower()}:{title}"

    channel_url = str(item.get("channelUrl") or item.get("inputChannelUrl") or "").strip().lower()
    if channel_url and title:
        return f"channel_url_title:{channel_url.rstrip('/')}:{title}"

    return None


def dedupe_apify_items(items: list[dict]) -> tuple[list[dict], YouTubeDedupeStats]:
    """Apify 返回结果按 videoId / url / channel+title 去重，保留首次出现顺序。"""
    stats = YouTubeDedupeStats(raw_items=len(items))
    seen: set[str] = set()
    result: list[dict] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        key = apify_item_dedupe_key(item)
        if key is None:
            result.append(item)
            continue
        if key in seen:
            stats.item_duplicates_removed += 1
            if len(stats.duplicate_keys) < 20:
                stats.duplicate_keys.append(key)
            continue
        seen.add(key)
        result.append(item)

    stats.deduped_items = len(result)
    return result, stats


def profile_dedupe_key(profile: PlatformCandidateProfile) -> str:
    """频道级 profile 唯一键，与 platform_identity_key 保持一致。"""
    platform, identity = platform_identity_key(
        profile.platform,
        profile.profile_url,
        channel_id=profile.channel_id,
    )
    return f"{platform}:{identity}"


def merge_youtube_profiles(profiles: list[PlatformCandidateProfile]) -> list[PlatformCandidateProfile]:
    """合并同一频道的多条 profile（merge + dedupe，非简单 append）。"""
    from app.services.platform_providers.youtube_api_direct import _merge_link_dicts

    by_key: dict[str, PlatformCandidateProfile] = {}
    order: list[str] = []

    for profile in profiles:
        key = profile_dedupe_key(profile)
        if key not in by_key:
            by_key[key] = profile
            order.append(key)
            continue

        existing = by_key[key]
        recent_titles = list(
            dict.fromkeys((existing.recent_post_titles or []) + (profile.recent_post_titles or []))
        )[:5]
        recent_urls = list(
            dict.fromkeys((existing.recent_post_urls or []) + (profile.recent_post_urls or []))
        )[:5]

        by_key[key] = PlatformCandidateProfile(
            platform=existing.platform,
            username=existing.username or profile.username,
            profile_url=existing.profile_url or profile.profile_url,
            display_name=existing.display_name or profile.display_name,
            avatar_url=existing.avatar_url or profile.avatar_url,
            bio=existing.bio or profile.bio,
            followers_count=existing.followers_count or profile.followers_count,
            avg_views=profile.avg_views or existing.avg_views,
            avg_likes=existing.avg_likes or profile.avg_likes,
            avg_comments=existing.avg_comments or profile.avg_comments,
            engagement_rate=profile.engagement_rate or existing.engagement_rate,
            website=existing.website or profile.website,
            email=existing.email or profile.email,
            other_social_links=_merge_link_dicts(existing.other_social_links, profile.other_social_links),
            recent_post_titles=recent_titles,
            recent_post_urls=recent_urls,
            source_url=profile.source_url or existing.source_url,
            source_type=existing.source_type or profile.source_type,
            source_discovery_type=existing.source_discovery_type or profile.source_discovery_type,
            source_meta={**(existing.source_meta or {}), **(profile.source_meta or {})},
            channel_id=existing.channel_id or profile.channel_id,
        )

    return [by_key[key] for key in order]


def dedupe_youtube_profiles(profiles: list[PlatformCandidateProfile]) -> tuple[list[PlatformCandidateProfile], YouTubeDedupeStats]:
    """频道 profile 最终去重：merge 后按唯一键保留一条。"""
    stats = YouTubeDedupeStats(raw_profiles=len(profiles))
    merged = merge_youtube_profiles(profiles)
    stats.deduped_profiles = len(merged)
    stats.profile_duplicates_removed = max(0, stats.raw_profiles - stats.deduped_profiles)
    return merged, stats


def normalize_keywords(keywords: list[str]) -> list[str]:
    """同一任务内关键词去重（忽略大小写与首尾空白），保留首次出现顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for raw in keywords:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def apify_search_max_results(*, limit: int) -> int:
    """关键词搜索保守 maxResults：20~30。"""
    return max(20, min(30, limit or 20))
