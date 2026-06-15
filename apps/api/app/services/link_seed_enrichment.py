"""LTK / ShopMy / Pinterest 链接 seed：反查社媒主页并合并资料。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace

from app.collectors.base import CollectedInfluencer
from app.services.contact_discovery import ContactDiscoveryService
from app.services.high_value_filter import has_collection_contact_channel
from app.services.influencer_profile_value import is_influencer_profile_valuable
from app.services.instagram_provider import scrape_instagram_profiles
from app.services.platform_utils import profile_to_collected
from app.services.url_parser import tiktok_profile_from_url

logger = logging.getLogger(__name__)

LINK_SEED_PLATFORMS = frozenset({"ltk", "shopmy", "pinterest"})

LINK_SEED_PLATFORM_LABELS: dict[str, str] = {
    "ltk": "LTK",
    "shopmy": "ShopMy",
    "pinterest": "Pinterest",
}

FINAL_PLATFORM_LABELS: dict[str, str] = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "pinterest": "Pinterest",
    "ltk": "LTK",
    "shopmy": "ShopMy",
}

PLATFORM_PRIORITY = {
    "instagram": 0,
    "tiktok": 1,
    "youtube": 2,
    "facebook": 3,
    "pinterest": 4,
    "ltk": 9,
    "shopmy": 9,
}


@dataclass
class LinkSeedEnrichmentResult:
    item: CollectedInfluencer
    seed_platform: str
    seed_profile_url: str
    seed_username: str
    enrichment_attempted: bool = False
    social_profiles_found: int = 0
    contact_found: bool = False
    primary_platform: str | None = None
    is_valuable: bool = False
    enrichment_notes: list[str] = field(default_factory=list)
    search_keywords: list[str] = field(default_factory=list)


def link_seed_low_value_detail(platform: str) -> str:
    key = (platform or "").strip().lower()
    label = LINK_SEED_PLATFORM_LABELS.get(key, platform or "链接")
    return (
        f"仅导入 {label} 链接，缺少社媒主页、粉丝、互动和联系方式，"
        f"建议补采社媒主页或人工补充联系方式"
    )


def link_seed_platform_display(platform: str | None) -> str:
    key = (platform or "").strip().lower()
    if not key:
        return ""
    return LINK_SEED_PLATFORM_LABELS.get(key, platform or "")


def final_platform_display(platform: str | None) -> str:
    key = (platform or "").strip().lower()
    if not key:
        return ""
    return FINAL_PLATFORM_LABELS.get(key, platform or "")


def resolve_seed_platform_from_input_url(url: str | None) -> str | None:
    from app.services.url_parser import detect_platform

    text = (url or "").strip()
    if not text:
        return None
    detected = detect_platform(text)
    if detected and detected in LINK_SEED_PLATFORMS:
        return detected
    return None


def build_seed_enrichment_status(
    *,
    enrichment_meta: dict | None = None,
    source_input_url: str | None = None,
    final_platform: str | None = None,
    failure_reason: str | None = None,
) -> str:
    seed_key = None
    if enrichment_meta:
        seed_key = str(enrichment_meta.get("link_seed_platform") or "").strip().lower() or None
    if not seed_key:
        seed_key = resolve_seed_platform_from_input_url(source_input_url)
    if not seed_key:
        return ""

    seed_label = link_seed_platform_display(seed_key)

    if failure_reason == "low_value_seed":
        return f"未补全（{seed_label} seed 资料不足）"

    primary = None
    if enrichment_meta:
        primary = str(enrichment_meta.get("primary_platform") or "").strip().lower() or None
    final_key = (final_platform or primary or "").strip().lower() or None

    if enrichment_meta and enrichment_meta.get("enrichment_attempted"):
        if final_key and final_key != seed_key:
            return f"已通过 {seed_label} seed 补全为 {final_platform_display(final_key)}"
        if final_key == seed_key:
            return f"{seed_label} seed（未找到其他社媒主页）"
        return f"已尝试 {seed_label} seed 补全"

    if final_key and final_key != seed_key:
        return f"已通过 {seed_label} seed 补全为 {final_platform_display(final_key)}"
    return ""


def compute_seed_source_export_fields(
    sources: list | None,
    *,
    final_platform: str | None = None,
) -> dict[str, str]:
    """从来源记录推断 Seed 平台与补全状态（红人库导出）。"""
    if not sources:
        return {"seed_platform": "", "seed_enrichment_status": ""}

    seed_labels: list[str] = []
    statuses: list[str] = []
    source_labels: list[str] = []

    for row in sources:
        inp = getattr(row, "source_input_url", None)
        row_platform = str(getattr(row, "source_platform", None) or "").strip().lower()
        seed_key = resolve_seed_platform_from_input_url(inp)
        if not seed_key and row_platform in LINK_SEED_PLATFORMS:
            seed_key = row_platform

        if seed_key:
            label = link_seed_platform_display(seed_key)
            if label and label not in seed_labels:
                seed_labels.append(label)
            status = build_seed_enrichment_status(
                source_input_url=inp,
                final_platform=final_platform,
            )
            if status and status not in statuses:
                statuses.append(status)
            if label and label not in source_labels:
                source_labels.append(label)
        elif row_platform:
            label = final_platform_display(row_platform)
            if label and label not in source_labels:
                source_labels.append(label)

    return {
        "source_platform": "\n".join(source_labels),
        "seed_platform": "\n".join(seed_labels),
        "seed_enrichment_status": "\n".join(statuses),
    }


def build_seed_search_keywords(username: str, display_name: str | None = None) -> list[str]:
    handle = (username or "").strip()
    name = (display_name or "").strip()
    keywords: list[str] = []
    if handle:
        keywords.extend(
            [
                f"{handle} Instagram",
                f"{handle} TikTok",
                f"{handle} YouTube",
                f"{handle} shopltk",
                f"{handle} LTK",
                f"{handle} email",
                f"{handle} link in bio",
            ]
        )
    if name and name.lower() != handle.lower():
        keywords.extend([f"{name} influencer", f"{name} Instagram"])
    return list(dict.fromkeys(keywords))


def _append_seed_link(item: CollectedInfluencer, seed: CollectedInfluencer) -> None:
    seed_url = (seed.profile_url or "").strip()
    if not seed_url:
        return
    links = list(item.other_social_links or [])
    seed_type = (seed.platform or "link_seed").strip().lower()
    if any(
        (link.get("url") or link.get("href") or "").strip().lower().rstrip("/")
        == seed_url.lower().rstrip("/")
        for link in links
        if isinstance(link, dict)
    ):
        return
    links.append({"type": seed_type, "url": seed_url, "label": seed_type.upper()})
    item.other_social_links = links


def _profile_score(item: CollectedInfluencer) -> tuple[int, int]:
    platform_rank = PLATFORM_PRIORITY.get((item.platform or "").lower(), 50)
    metric_bonus = 0
    if item.followers_count is not None:
        metric_bonus += 20
    if item.engagement_rate is not None:
        metric_bonus += 10
    if is_influencer_profile_valuable(item):
        metric_bonus += 30
    return (-metric_bonus, platform_rank)


def _pick_best_profile(candidates: list[CollectedInfluencer]) -> CollectedInfluencer | None:
    if not candidates:
        return None
    valuable = [c for c in candidates if is_influencer_profile_valuable(c)]
    pool = valuable or [c for c in candidates if c.followers_count is not None or c.bio]
    if not pool:
        pool = candidates
    return min(pool, key=_profile_score)


def merge_seed_into_primary(seed: CollectedInfluencer, primary: CollectedInfluencer) -> CollectedInfluencer:
    """将 seed 链接并入主 profile，不覆盖 profile_url / source_post_url。"""
    merged = CollectedInfluencer(
        platform=primary.platform,
        username=primary.username,
        profile_url=primary.profile_url,
        display_name=primary.display_name or seed.display_name,
        avatar_url=primary.avatar_url or seed.avatar_url,
        country=primary.country or seed.country,
        language=primary.language or seed.language,
        category=primary.category or seed.category,
        niche=primary.niche or seed.niche,
        bio=primary.bio or seed.bio,
        followers_count=primary.followers_count,
        avg_views=primary.avg_views,
        avg_likes=primary.avg_likes,
        avg_comments=primary.avg_comments,
        engagement_rate=primary.engagement_rate,
        email=primary.email or seed.email,
        final_email=primary.final_email or seed.final_email,
        public_email=primary.public_email or seed.public_email,
        business_email=primary.business_email or seed.business_email,
        email_source=primary.email_source or seed.email_source,
        website=primary.website or seed.website,
        contact_page=primary.contact_page or seed.contact_page,
        linktree_url=primary.linktree_url or seed.linktree_url,
        whatsapp=primary.whatsapp or seed.whatsapp,
        telegram=primary.telegram or seed.telegram,
        other_social_links=list(primary.other_social_links or []),
        content_topics=list(primary.content_topics or seed.content_topics or []),
        recent_post_titles=list(primary.recent_post_titles or seed.recent_post_titles or []),
        recent_post_urls=list(primary.recent_post_urls or seed.recent_post_urls or []),
        source_post_url=primary.source_post_url or seed.source_post_url,
        source_discovery_type=primary.source_discovery_type or "link_seed_expanded",
        contact_fetch_status=primary.contact_fetch_status or seed.contact_fetch_status,
        platform_unique_id=primary.platform_unique_id or seed.platform_unique_id,
        tags=list(dict.fromkeys((primary.tags or []) + (seed.tags or []) + [f"link_seed:{seed.platform}"])),
    )
    _append_seed_link(merged, seed)
    if seed.source_post_url and not merged.source_post_url:
        merged.source_post_url = seed.source_post_url
    return merged


async def _try_instagram_profile(username: str) -> CollectedInfluencer | None:
    handle = (username or "").strip().lstrip("@")
    if not handle:
        return None
    url = f"https://www.instagram.com/{handle}/"
    scrape = await scrape_instagram_profiles([url])
    for profile in scrape.profiles:
        if profile.username and profile.username.lower() == handle.lower():
            return profile
    return scrape.profiles[0] if scrape.profiles else None


async def _try_tiktok_profile(username: str) -> CollectedInfluencer | None:
    handle = (username or "").strip().lstrip("@")
    if not handle:
        return None
    profile = tiktok_profile_from_url(f"https://www.tiktok.com/@{handle}")
    if profile is None:
        return None
    from app.services.platform_providers.tiktok_api_direct import _hydrate_tiktok_profile

    errors: list[str] = []
    hydrated = await _hydrate_tiktok_profile(profile, errors=errors)
    if errors:
        logger.info("TikTok seed hydrate notes for @%s: %s", handle, errors[0][:120])
    item = profile_to_collected(hydrated)
    if item.followers_count is None and not item.bio:
        return None
    return item


async def _try_youtube_profile(username: str, display_name: str | None) -> CollectedInfluencer | None:
    from app.services.api_direct_provider import discover_platform

    query = (display_name or username or "").strip()
    if not query:
        return None
    mini_task = SimpleNamespace(
        keywords=[f"{query} YouTube"],
        platform="youtube",
        platforms=["youtube"],
        discovery_limit=5,
        collection_mode="keyword",
        input_urls=[],
        country=None,
        category=None,
    )
    try:
        result = await discover_platform(mini_task, "youtube")
    except Exception as exc:
        logger.warning("YouTube seed search failed for %s: %s", query, exc)
        return None
    for profile in result.profiles or []:
        item = profile_to_collected(profile)
        if is_influencer_profile_valuable(item) or item.followers_count is not None:
            return item
    if result.profiles:
        return profile_to_collected(result.profiles[0])
    return None


async def enrich_link_seed_item(seed: CollectedInfluencer) -> LinkSeedEnrichmentResult:
    """用 seed 用户名反查 IG/TikTok/YouTube 并合并为可入库 profile。"""
    platform = (seed.platform or "").strip().lower()
    username = (seed.username or "").strip()
    display_name = getattr(seed, "display_name", None)
    search_keywords = build_seed_search_keywords(username, display_name)
    notes: list[str] = []
    candidates: list[CollectedInfluencer] = []

    if username:
        ig = await _try_instagram_profile(username)
        if ig:
            candidates.append(ig)
            notes.append("Instagram")
        tt = await _try_tiktok_profile(username)
        if tt:
            candidates.append(tt)
            notes.append("TikTok")

    yt = await _try_youtube_profile(username, display_name)
    if yt:
        candidates.append(yt)
        notes.append("YouTube")

    primary = _pick_best_profile(candidates)
    if primary and (primary.platform or "").lower() not in LINK_SEED_PLATFORMS:
        merged = merge_seed_into_primary(seed, primary)
        await ContactDiscoveryService.enrich_collected(merged)
        contact_found = has_collection_contact_channel(merged)
        valuable = is_influencer_profile_valuable(merged)
        return LinkSeedEnrichmentResult(
            item=merged,
            seed_platform=platform,
            seed_profile_url=seed.profile_url,
            seed_username=username,
            enrichment_attempted=True,
            social_profiles_found=len(candidates),
            contact_found=contact_found,
            primary_platform=merged.platform,
            is_valuable=valuable,
            enrichment_notes=notes,
            search_keywords=search_keywords,
        )

    await ContactDiscoveryService.enrich_collected(seed)
    contact_found = has_collection_contact_channel(seed)
    valuable = is_influencer_profile_valuable(seed)
    if notes:
        notes.append("未找到可用社媒主页")
    return LinkSeedEnrichmentResult(
        item=seed,
        seed_platform=platform,
        seed_profile_url=seed.profile_url,
        seed_username=username,
        enrichment_attempted=True,
        social_profiles_found=len(candidates),
        contact_found=contact_found,
        primary_platform=seed.platform,
        is_valuable=valuable,
        enrichment_notes=notes,
        search_keywords=search_keywords,
    )


def enrichment_meta_dict(result: LinkSeedEnrichmentResult) -> dict:
    return {
        "link_seed_platform": result.seed_platform,
        "link_seed_profile_url": result.seed_profile_url,
        "link_seed_username": result.seed_username,
        "enrichment_attempted": result.enrichment_attempted,
        "social_profiles_found": result.social_profiles_found,
        "contact_found": result.contact_found,
        "primary_platform": result.primary_platform,
        "is_valuable": result.is_valuable,
        "enrichment_notes": result.enrichment_notes,
        "search_keywords": result.search_keywords,
    }
