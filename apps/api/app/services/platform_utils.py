"""API Direct 多平台通用工具。"""

from __future__ import annotations

import re
from typing import Any

from app.collectors.base import CollectedInfluencer
from app.core.config import settings
from app.services.platform_types import PlatformCandidateProfile

_COUNT_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_YOUTUBE_UC_CHANNEL_RE = re.compile(r"youtube\.com/channel/(UC[\w-]{10,})", re.I)


def parse_count_text(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = re.match(r"^([\d.]+)\s*([kmbKMB])?$", text)
    if not match:
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None
    number = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = _COUNT_SUFFIX.get(suffix, 1)
    return int(number * multiplier)


def parse_views_from_time_and_views(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"([\d,.]+)\s*([kmbKMB])?\s*views?", text, re.I)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    suffix = (match.group(2) or "").lower()
    try:
        number = float(raw)
    except ValueError:
        return None
    return int(number * _COUNT_SUFFIX.get(suffix, 1))


def engagement_rate_from_metrics(
    *,
    views: int | None,
    likes: int | None,
    comments: int | None,
    followers: int | None = None,
) -> float | None:
    if likes is None and comments is None:
        return None
    interactions = (likes or 0) + (comments or 0)
    denominator = views or followers
    if not denominator or denominator <= 0:
        return None
    return round(interactions / denominator * 100, 2)


def tiktok_pages_param() -> int:
    default_pages = max(1, settings.api_direct_tiktok_default_pages)
    max_pages = max(1, settings.api_direct_max_pages_per_request)
    return max(1, min(default_pages, max_pages))


_COUNTRY_TO_TIKTOK_REGION = {
    "us": "us",
    "usa": "us",
    "united states": "us",
    "gb": "gb",
    "uk": "gb",
    "united kingdom": "gb",
    "jp": "jp",
    "japan": "jp",
    "kr": "kr",
    "korea": "kr",
    "south korea": "kr",
    "de": "de",
    "germany": "de",
    "fr": "fr",
    "france": "fr",
    "ca": "ca",
    "canada": "ca",
    "au": "au",
    "australia": "au",
    "br": "br",
    "brazil": "br",
    "in": "in",
    "india": "in",
}


def tiktok_region_from_task(task) -> str | None:
    country = (getattr(task, "country", None) or "").strip().lower()
    if not country:
        return None
    if len(country) == 2 and country.isalpha():
        return country
    return _COUNTRY_TO_TIKTOK_REGION.get(country)


def normalize_profile_url(profile_url: str) -> str:
    return (profile_url or "").strip().lower().rstrip("/")


def resolve_youtube_channel_id(
    *,
    channel_id: str | None = None,
    profile_url: str | None = None,
    platform_unique_id: str | None = None,
) -> str | None:
    for candidate in (platform_unique_id, channel_id):
        text = (candidate or "").strip()
        if text.upper().startswith("UC"):
            return text
    if profile_url:
        match = _YOUTUBE_UC_CHANNEL_RE.search(profile_url)
        if match:
            return match.group(1)
    return None


def resolve_platform_unique_id(
    platform: str,
    profile_url: str,
    *,
    channel_id: str | None = None,
    platform_unique_id: str | None = None,
) -> str | None:
    if (platform or "").strip().lower() != "youtube":
        return None
    return resolve_youtube_channel_id(
        channel_id=channel_id,
        profile_url=profile_url,
        platform_unique_id=platform_unique_id,
    )


def platform_identity_key(
    platform: str,
    profile_url: str,
    *,
    platform_unique_id: str | None = None,
    channel_id: str | None = None,
) -> tuple[str, str]:
    platform_norm = (platform or "").strip().lower()
    if platform_norm == "youtube":
        uid = resolve_youtube_channel_id(
            channel_id=channel_id,
            profile_url=profile_url,
            platform_unique_id=platform_unique_id,
        )
        if uid:
            return (platform_norm, f"channel:{uid.lower()}")
        return (platform_norm, f"url:{normalize_profile_url(profile_url)}")
    return (platform_norm, normalize_profile_url(profile_url))


def profile_identity_key(profile: PlatformCandidateProfile) -> tuple[str, str]:
    return platform_identity_key(
        profile.platform,
        profile.profile_url,
        channel_id=profile.channel_id,
    )


def collected_identity_key(item: CollectedInfluencer) -> tuple[str, str]:
    return platform_identity_key(
        item.platform,
        item.profile_url,
        platform_unique_id=item.platform_unique_id,
    )


def profile_outcome_key(
    platform: str,
    profile_url: str,
    *,
    platform_unique_id: str | None = None,
    channel_id: str | None = None,
) -> tuple[str, str]:
    return platform_identity_key(
        platform,
        profile_url,
        platform_unique_id=platform_unique_id,
        channel_id=channel_id,
    )


def dedupe_collected_items(items: list[CollectedInfluencer]) -> list[CollectedInfluencer]:
    seen: set[tuple[str, str]] = set()
    result: list[CollectedInfluencer] = []
    for item in items:
        key = collected_identity_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def profile_to_collected(profile: PlatformCandidateProfile) -> CollectedInfluencer:
    from app.services.contact_discovery import extract_emails_from_text, normalize_email
    from app.services.contact_signals import (
        apply_bio_contact_hints,
        classify_aggregator_url,
        classify_commercial_storefront,
        classify_contact_page_url,
        merge_other_social_links,
    )
    from app.services.business_quality import apply_creator_quality

    item = CollectedInfluencer(
        platform=profile.platform,
        username=profile.username,
        profile_url=profile.profile_url,
        platform_unique_id=resolve_platform_unique_id(
            profile.platform,
            profile.profile_url,
            channel_id=profile.channel_id,
        ),
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        followers_count=profile.followers_count,
        avg_views=profile.avg_views,
        avg_likes=profile.avg_likes,
        avg_comments=profile.avg_comments,
        engagement_rate=profile.engagement_rate,
        email=profile.email,
        website=profile.website,
        other_social_links=list(profile.other_social_links or []),
        recent_post_titles=list(profile.recent_post_titles or []),
        recent_post_urls=list(profile.recent_post_urls or []),
        source_discovery_type=profile.source_discovery_type,
        source_post_url=profile.source_url,
        tags=["api_direct"],
    )

    apply_bio_contact_hints(item)

    for link in profile.other_social_links or []:
        if not isinstance(link, dict):
            continue
        url = str(link.get("url") or "").strip()
        if not url:
            continue
        storefront = classify_commercial_storefront(url)
        aggregator = classify_aggregator_url(url)
        if aggregator == "linktree" and not item.linktree_url:
            item.linktree_url = url
        elif aggregator in {"beacons", "stan_store", "carrd"} and not item.website:
            item.website = url
        elif classify_contact_page_url(url) and not item.contact_page:
            item.contact_page = url
        elif storefront:
            pass
        elif aggregator == "linktree":
            pass
        elif not item.website:
            item.website = url

    if item.linktree_url and item.website == item.linktree_url:
        item.website = None

    storefront_label = classify_commercial_storefront(profile.profile_url)
    if storefront_label:
        item.other_social_links = merge_other_social_links(
            item.other_social_links,
            [
                {
                    "type": storefront_label.lower().replace(" ", "_"),
                    "label": storefront_label,
                    "url": profile.profile_url,
                }
            ],
        )

    if profile.email:
        normalized = normalize_email(profile.email)
        if normalized:
            item.email = normalized
            item.final_email = normalized
    elif profile.bio:
        for candidate in extract_emails_from_text(profile.bio, f"{profile.platform}_bio"):
            if candidate.email:
                item.email = candidate.email
                item.final_email = candidate.email
                item.email_source = candidate.source_type
                break

    if profile.platform == "youtube" and (profile.source_meta or {}).get("email_verification_required"):
        item.contact_fetch_status = "verification_required"
        item.contact_fetch_error = "YouTube 邮箱需人工验证，请勿自动绕过验证码"
    elif profile.platform == "youtube" and (profile.source_meta or {}).get("about_links_fetch") in {"empty_or_unreachable", "failed"}:
        if item.other_social_links or item.website or item.linktree_url:
            item.contact_fetch_status = "partial_failed"
            item.contact_fetch_error = (
                "About/Shop 聚合外链需 youtube.com 公开页补采（API Direct /channels 不提供）；"
                "当前仅保留视频描述等可见外链"
            )
        else:
            item.contact_fetch_status = "partial_failed"
            item.contact_fetch_error = (
                "About/更多外链需 youtube.com 可达；API Direct /channels 不含该字段"
            )

    apply_creator_quality(item)

    return item


def dedupe_profiles(profiles: list[PlatformCandidateProfile]) -> list[PlatformCandidateProfile]:
    seen: set[tuple[str, str]] = set()
    result: list[PlatformCandidateProfile] = []
    for profile in profiles:
        key = profile_identity_key(profile)
        if key in seen:
            continue
        seen.add(key)
        result.append(profile)
    return result


def candidate_row_from_profile(
    profile: PlatformCandidateProfile,
    *,
    status: str,
    collection_mode: str | None = None,
    source_keyword: str | None = None,
    failure_reason: str | None = None,
    failure_detail: str | None = None,
    product_influencer_id: int | None = None,
    global_influencer_id: int | None = None,
    product_id: int | None = None,
    user_id: int | None = None,
    followers_count: int | None = None,
    engagement_rate: float | None = None,
) -> dict[str, Any]:
    return {
        "username": profile.username,
        "profile_url": profile.profile_url,
        "platform": profile.platform,
        "source_type": profile.source_type,
        "source_keyword": source_keyword,
        "source_post_url": profile.source_url,
        "source_discovery_type": profile.source_discovery_type,
        "source_meta": profile.source_meta or None,
        "followers_count": followers_count if followers_count is not None else profile.followers_count,
        "engagement_rate": engagement_rate if engagement_rate is not None else profile.engagement_rate,
        "status": status,
        "failure_reason": failure_reason,
        "failure_detail": failure_detail,
        "product_influencer_id": product_influencer_id,
        "global_influencer_id": global_influencer_id,
        "product_id": product_id,
        "user_id": user_id,
    }
