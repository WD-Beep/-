# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：link seed enrichment
"""LTK / ShopMy / Pinterest 链接 seed：反查社媒主页并合并资料。"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
from app.collectors.base import CollectedInfluencer
from app.core.config import settings
from app.services.apify_client import ApifyError, run_actor_sync
from app.services.contact_discovery import ContactDiscoveryService
from app.services.high_value_filter import has_collection_contact_channel, has_collection_email
from app.services.influencer_profile_value import is_influencer_profile_valuable
from app.services.instagram_provider import scrape_instagram_profiles
from app.services.platform_utils import profile_to_collected
from app.services.url_parser import detect_platform, tiktok_profile_from_url

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


INSTAGRAM_DETAIL_FETCHED_TAG = "instagram_detail_fetched"
LTK_OFFICIAL_SOCIAL_HANDLES = {
    "shop.ltk",
    "ltk.home",
    "ltk.family",
    "ltk.europe",
    "ltk.brasil",
    "ltk.australia",
    "ltk.asia",
}


def platform_detail_fetched_tag(platform: str) -> str:
    return f"{(platform or '').strip().lower()}_detail_fetched"


def is_platform_detail_fetched(item: CollectedInfluencer) -> bool:
    platform = (getattr(item, "platform", None) or "").strip().lower()
    tags = list(getattr(item, "tags", None) or [])
    if platform == "instagram" and INSTAGRAM_DETAIL_FETCHED_TAG in tags:
        return True
    return platform_detail_fetched_tag(platform) in tags


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
    instagram_detail_fetched: bool = False
    platform_detail_fetched: bool = False
    enriched_profile_url: str | None = None
    selected_reason: str | None = None
    enrichment_candidates: list[dict] = field(default_factory=list)
    enrichment_notes: list[str] = field(default_factory=list)
    search_keywords: list[str] = field(default_factory=list)
    seed_source_meta: dict = field(default_factory=dict)


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

    ig_detail_fetched = bool(enrichment_meta and enrichment_meta.get("instagram_detail_fetched"))
    if enrichment_meta and enrichment_meta.get("enrichment_attempted"):
        if final_key and final_key != seed_key:
            final_label = final_platform_display(final_key)
            if final_key == "instagram" and ig_detail_fetched:
                return f"已通过 {seed_label} 补全为 {final_label}，并完成 Instagram 详情采集"
            return f"已通过 {seed_label} seed 补全为 {final_label}"
        if final_key == seed_key:
            return f"{seed_label} seed（未找到其他社媒主页）"
        return f"已尝试 {seed_label} seed 补全"

    if final_key and final_key != seed_key:
        final_label = final_platform_display(final_key)
        if final_key == "instagram" and ig_detail_fetched:
            return f"已通过 {seed_label} 补全为 {final_label}，并完成 Instagram 详情采集"
        return f"已通过 {seed_label} seed 补全为 {final_label}"
    return ""


def is_link_seed_enriched_instagram(item: CollectedInfluencer) -> bool:
    """LTK/ShopMy/Pinterest seed 已补全为 Instagram 且完成详情采集。"""
    return _is_link_seed_enriched_platform(item, "instagram")


def _is_link_seed_enriched_platform(item: CollectedInfluencer, platform: str) -> bool:
    expected = (platform or "").strip().lower()
    item_platform = (getattr(item, "platform", None) or "").strip().lower()
    if item_platform != expected:
        return False
    if is_platform_detail_fetched(item):
        return True
    tags = list(getattr(item, "tags", None) or [])
    return any(str(tag).startswith("link_seed:") for tag in tags)


def is_link_seed_enriched_with_detail(item: CollectedInfluencer) -> bool:
    platform = (getattr(item, "platform", None) or "").strip().lower()
    if not platform or platform in LINK_SEED_PLATFORMS:
        return False
    if not is_platform_detail_fetched(item):
        tags = list(getattr(item, "tags", None) or [])
        if platform == "instagram" and INSTAGRAM_DETAIL_FETCHED_TAG in tags:
            return True
        return False
    return any(str(tag).startswith("link_seed:") for tag in (getattr(item, "tags", None) or []))


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
    """兼容旧逻辑：平台优先级兜底排序。"""
    platform_rank = PLATFORM_PRIORITY.get((item.platform or "").lower(), 50)
    metric_bonus = int(_compute_enrichment_score(item))
    return (-metric_bonus, platform_rank)


def _compute_enrichment_score(item: CollectedInfluencer) -> float:
    """联系方式 > 粉丝/互动 > 资料完整度；平台优先级仅作微弱 tie-break。"""
    score = 0.0
    if has_collection_email(item):
        score += 45.0
    elif has_collection_contact_channel(item):
        score += 28.0
    followers = item.followers_count
    if followers is not None:
        if followers >= 100_000:
            score += 22.0
        elif followers >= 10_000:
            score += 16.0
        else:
            score += min(12.0, followers / 5000.0)
    rate = item.engagement_rate
    if rate is not None:
        score += min(18.0, rate * 4.0)
    if item.bio:
        score += 6.0
    if item.display_name:
        score += 2.0
    if item.avatar_url:
        score += 2.0
    platform = (item.platform or "").lower()
    score -= PLATFORM_PRIORITY.get(platform, 50) * 0.05
    return round(score, 1)


def _candidate_record_from_item(
    item: CollectedInfluencer | None,
    *,
    platform: str,
    status: str,
    profile_url: str | None = None,
    error: str | None = None,
) -> dict:
    if item is None:
        record = {
            "platform": platform,
            "profile_url": profile_url,
            "status": status,
            "followers_count": None,
            "engagement_rate": None,
            "has_email": False,
            "has_contact": False,
            "score": 0.0,
        }
        if error:
            record["error"] = error
        return record
    record = {
        "platform": (item.platform or platform).lower(),
        "profile_url": item.profile_url,
        "status": status,
        "followers_count": item.followers_count,
        "engagement_rate": item.engagement_rate,
        "has_email": has_collection_email(item),
        "has_contact": has_collection_contact_channel(item),
        "score": _compute_enrichment_score(item),
    }
    if error:
        record["error"] = error
    return record


async def _record_platform_hydrate(
    platform: str,
    coro,
    *,
    profile_url: str | None = None,
) -> tuple[CollectedInfluencer | None, dict]:
    """逐平台容错：记录候选状态，异常不中断其他平台。"""
    try:
        timeout = max(0.01, min(25.0, float(settings.link_seed_enrich_timeout_seconds)))
        item, fetched = await asyncio.wait_for(coro, timeout=timeout)
        if item is None:
            status = "failed"
        elif fetched:
            status = "fetched"
        else:
            status = "shell_only"
        record = _candidate_record_from_item(
            item,
            platform=platform,
            status=status,
            profile_url=profile_url or (item.profile_url if item else None),
        )
        return item, record
    except TimeoutError:
        logger.warning("Link seed %s enrichment timed out", platform)
        record = _candidate_record_from_item(
            None,
            platform=platform,
            status="timeout",
            profile_url=profile_url,
            error="platform_detail_timeout",
        )
        return None, record
    except Exception as exc:
        logger.warning("Link seed %s enrichment failed: %s", platform, exc)
        record = _candidate_record_from_item(
            None,
            platform=platform,
            status="failed",
            profile_url=profile_url,
            error=str(exc)[:200],
        )
        return None, record


async def _safe_contact_enrich_collected(item: CollectedInfluencer) -> bool:
    try:
        timeout = max(0.01, min(15.0, float(settings.link_seed_enrich_timeout_seconds)))
        await asyncio.wait_for(ContactDiscoveryService.enrich_collected(item), timeout=timeout)
        return True
    except TimeoutError:
        logger.warning("Contact discovery timed out for %s %s", item.platform, item.profile_url)
        item.contact_fetch_status = item.contact_fetch_status or "timeout"
        return False
    except Exception as exc:
        logger.warning("Contact discovery failed for %s %s: %s", item.platform, item.profile_url, exc)
        item.contact_fetch_status = item.contact_fetch_status or "failed"
        item.contact_fetch_error = str(exc)[:200]
        return False


def _build_selected_reason(primary: CollectedInfluencer, candidates: list[dict]) -> str:
    label = final_platform_display(primary.platform)
    score = _compute_enrichment_score(primary)
    parts: list[str] = [f"{label} 综合评分最高（{score}）"]
    if has_collection_email(primary):
        parts.append("有公开邮箱")
    elif has_collection_contact_channel(primary):
        parts.append("有联系方式")
    if primary.followers_count is not None:
        parts.append(f"粉丝 {primary.followers_count:,}")
    if primary.engagement_rate is not None:
        parts.append(f"互动率 {primary.engagement_rate:.2f}%")
    alts = [
        c for c in candidates
        if c.get("platform") != (primary.platform or "").lower() and c.get("status") == "fetched"
    ]
    if alts:
        best_alt = max(alts, key=lambda c: float(c.get("score") or 0))
        alt_label = final_platform_display(str(best_alt.get("platform")))
        parts.append(f"优于 {alt_label}（{best_alt.get('score')}）")
    return "；".join(parts)


def _pick_best_profile(candidates: list[CollectedInfluencer]) -> CollectedInfluencer | None:
    if not candidates:
        return None
    valuable = [c for c in candidates if is_influencer_profile_valuable(c)]
    pool = valuable or [c for c in candidates if c.followers_count is not None or c.bio]
    if not pool:
        pool = candidates
    return max(pool, key=lambda item: (_compute_enrichment_score(item), -PLATFORM_PRIORITY.get((item.platform or "").lower(), 50)))


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


def _shopmy_profile_snapshot_from_item(username: str, row: dict) -> dict:
    profile_url = (
        row.get("profileUrl")
        or row.get("profileURL")
        or row.get("url")
        or row.get("creatorUrl")
        or f"https://shopmy.us/{username}"
    )
    name = row.get("name") or row.get("displayName") or row.get("full_name") or row.get("creator") or username
    brands = row.get("brands") if isinstance(row.get("brands"), list) else []
    collections = row.get("collections") if isinstance(row.get("collections"), list) else []
    picks = row.get("picks") if isinstance(row.get("picks"), list) else []
    for collection in collections:
        if isinstance(collection, dict) and isinstance(collection.get("picks"), list):
            picks.extend(collection["picks"])
    social_links = []
    for key in ("instagram", "tiktok", "youtube", "pinterest", "website"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            social_links.append({"type": key, "url": value.strip(), "label": key.title()})
    return {
        "platform": "shopmy",
        "username": username,
        "profile_url": str(profile_url),
        "display_name": str(name) if name is not None else username,
        "bio": row.get("bio") or row.get("description"),
        "avatar_url": row.get("profile_image") or row.get("avatarUrl") or row.get("avatar_url"),
        "followers_count": row.get("follower_count") or row.get("followers_count"),
        "following_count": row.get("following_count"),
        "collection_count": row.get("collection_count"),
        "total_picks": row.get("total_picks"),
        "brands": brands,
        "collections": collections,
        "picks": picks,
        "social_links": social_links,
        "raw": row,
    }


async def _hydrate_shopmy_seed_detail(seed: CollectedInfluencer) -> tuple[CollectedInfluencer, bool]:
    username = (seed.username or "").strip().lstrip("@")
    if not username or not settings.is_apify_configured or not settings.apify_shopmy_creator_actor_id.strip():
        return seed, False
    run_input = {
        "creators": [username],
        "includeCollectionsAndPicks": True,
        "maxCollectionsPerCreator": max(1, settings.apify_shopmy_creator_max_collections),
        "maxConcurrentFetches": max(1, settings.apify_shopmy_creator_max_concurrency),
    }
    try:
        rows = await run_actor_sync(
            settings.apify_shopmy_creator_actor_id,
            run_input,
            timeout=settings.apify_shopmy_creator_timeout_seconds,
            max_retries=settings.apify_shopmy_creator_max_retries,
            memory_mbytes=settings.apify_shopmy_creator_memory_mbytes,
        )
    except ApifyError as exc:
        logger.warning("ShopMy Apify seed hydrate failed for %s: %s", username, exc)
        return seed, False
    if not rows:
        return seed, False
    row = rows[0] if isinstance(rows[0], dict) else {}
    if not row:
        return seed, False
    if row.get("error"):
        logger.info("ShopMy Apify seed hydrate returned error for %s: %s", username, row.get("error"))
        return seed, False
    snapshot = _shopmy_profile_snapshot_from_item(username, row)
    seed.display_name = snapshot.get("display_name") or seed.display_name
    seed.bio = snapshot.get("bio") or seed.bio
    seed.avatar_url = snapshot.get("avatar_url") or seed.avatar_url
    seed.profile_url = str(snapshot.get("profile_url") or seed.profile_url)
    if snapshot.get("followers_count") is not None:
        seed.followers_count = snapshot.get("followers_count")
    if snapshot.get("social_links"):
        links = list(seed.other_social_links or [])
        existing = {
            (link.get("url") or "").strip().lower().rstrip("/")
            for link in links
            if isinstance(link, dict)
        }
        for link in snapshot["social_links"]:
            url = (link.get("url") or "").strip()
            if url and url.lower().rstrip("/") not in existing:
                links.append(link)
                existing.add(url.lower().rstrip("/"))
        seed.other_social_links = links
    seed.source_discovery_type = seed.source_discovery_type or "link_seed_expanded"
    tags = list(seed.tags or [])
    for tag in ("link_seed:shopmy", platform_detail_fetched_tag("shopmy")):
        if tag not in tags:
            tags.append(tag)
    seed.tags = tags
    source_meta = dict(getattr(seed, "source_meta", {}) or {})
    source_meta["shopmy_profile_snapshot"] = snapshot
    source_meta["shopmy_detail_fetched"] = True
    setattr(seed, "source_meta", source_meta)
    return seed, True


def _parse_count_text(value: str | None) -> int | None:
    text = (value or "").strip().lower().replace(",", "")
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([km]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2)
    if suffix == "k":
        number *= 1_000
    elif suffix == "m":
        number *= 1_000_000
    return int(number)


def _social_platform_from_url(url: str | None) -> str | None:
    text = (url or "").strip()
    if not text:
        return None
    platform = detect_platform(text)
    if platform in {"instagram", "tiktok", "youtube", "facebook", "pinterest"}:
        return platform
    host = urlparse(text).netloc.lower()
    if "pinterest." in host:
        return "pinterest"
    return None


def _is_ltk_official_social_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    handle = parsed.path.strip("/").split("/")[0].lower()
    if "instagram.com" in host and handle in LTK_OFFICIAL_SOCIAL_HANDLES:
        return True
    if "facebook.com" in host and "liketoknowit" in parsed.path.lower():
        return True
    if "youtube.com" in host and "ucw_wzudmpb0tdpWxtbowkka".lower() in parsed.path.lower():
        return True
    return False


def _dedupe_social_links(links: list[dict]) -> list[dict]:
    output: list[dict] = []
    seen: set[str] = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        url = str(link.get("url") or link.get("href") or "").strip()
        platform = _social_platform_from_url(url)
        if not url or not platform:
            continue
        key = url.lower().rstrip("/")
        if key in seen or _is_ltk_official_social_url(url):
            continue
        seen.add(key)
        output.append({"type": platform, "url": url, "label": link.get("label") or platform.title()})
    return output


def _extract_ltk_profile_snapshot_from_html(username: str, profile_url: str, text: str) -> dict:
    snapshot: dict = {
        "platform": "ltk",
        "username": username,
        "profile_url": profile_url,
        "display_name": username,
        "social_links": [],
    }

    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        text,
        flags=re.I | re.S,
    ):
        raw = html.unescape(match.group(1)).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_url = str(row.get("url") or "").strip()
            row_name = str(row.get("founder") or row.get("name") or "").strip()
            if row_url and "/explore/" not in row_url:
                continue
            if row_name:
                snapshot["display_name"] = row_name.replace("'s LTK Shop", "")
            if row.get("description"):
                snapshot["bio"] = str(row.get("description"))
            if row.get("image"):
                snapshot["avatar_url"] = str(row.get("image"))

    if not snapshot.get("avatar_url"):
        avatar = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|branch:deeplink:avatarUrl)["\'][^>]+content=["\']([^"\']+)', text, re.I)
        if avatar:
            snapshot["avatar_url"] = html.unescape(avatar.group(1))
    if not snapshot.get("bio"):
        desc = re.search(r'<meta[^>]+(?:property|name)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)', text, re.I)
        if desc:
            snapshot["bio"] = html.unescape(desc.group(1))

    follower = re.search(r"([\d,.]+)\s*([kKmM]?)\s+followers?", text)
    if follower:
        snapshot["followers_count"] = _parse_count_text("".join(follower.groups()))

    social_links: list[dict] = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', text, flags=re.I):
        url = html.unescape(href)
        platform = _social_platform_from_url(url)
        if platform:
            social_links.append({"type": platform, "url": url, "label": platform.title()})
    snapshot["social_links"] = _dedupe_social_links(social_links)
    return snapshot


async def _hydrate_ltk_seed_detail(seed: CollectedInfluencer) -> tuple[CollectedInfluencer, bool]:
    username = (seed.username or "").strip().lstrip("@")
    profile_url = (seed.profile_url or f"https://www.shopltk.com/explore/{username}").strip()
    if not username or not profile_url:
        return seed, False
    try:
        async with httpx.AsyncClient(
            timeout=max(5, min(20, settings.link_seed_enrich_timeout_seconds)),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        ) as client:
            response = await client.get(profile_url)
            response.raise_for_status()
    except Exception as exc:
        logger.info("LTK seed hydrate failed for %s: %s", username, exc)
        return seed, False

    snapshot = _extract_ltk_profile_snapshot_from_html(username, profile_url, response.text)
    seed.display_name = snapshot.get("display_name") or seed.display_name or username
    seed.bio = snapshot.get("bio") or seed.bio
    seed.avatar_url = snapshot.get("avatar_url") or seed.avatar_url
    if snapshot.get("followers_count") is not None:
        seed.followers_count = snapshot.get("followers_count")
    seed.profile_url = str(snapshot.get("profile_url") or profile_url)
    seed.other_social_links = _dedupe_social_links(list(seed.other_social_links or []) + snapshot.get("social_links", []))
    seed.source_discovery_type = seed.source_discovery_type or "link_seed_expanded"
    tags = list(seed.tags or [])
    for tag in ("link_seed:ltk", platform_detail_fetched_tag("ltk")):
        if tag not in tags:
            tags.append(tag)
    seed.tags = tags
    source_meta = dict(getattr(seed, "source_meta", {}) or {})
    source_meta["ltk_profile_snapshot"] = snapshot
    source_meta["ltk_detail_fetched"] = True
    setattr(seed, "source_meta", source_meta)
    return seed, True


def _instagram_profile_shell(username: str) -> CollectedInfluencer | None:
    handle = (username or "").strip().lstrip("@")
    if not handle:
        return None
    return CollectedInfluencer(
        platform="instagram",
        username=handle,
        profile_url=f"https://www.instagram.com/{handle}/",
    )


def _username_from_instagram_profile_url(profile_url: str | None) -> str | None:
    text = (profile_url or "").strip().rstrip("/")
    if not text:
        return None
    marker = "instagram.com/"
    idx = text.lower().find(marker)
    if idx < 0:
        return None
    handle = text[idx + len(marker):].split("/")[0].strip().lstrip("@")
    return handle or None


def _pick_instagram_profile_from_scrape(
    profiles: list[CollectedInfluencer],
    *,
    profile_url: str | None,
    username: str | None,
) -> CollectedInfluencer | None:
    if not profiles:
        return None
    handle = (username or _username_from_instagram_profile_url(profile_url) or "").strip().lstrip("@")
    if handle:
        for profile in profiles:
            if profile.username and profile.username.lower() == handle.lower():
                return profile
    return profiles[0]


async def _hydrate_instagram_profile_detail(profile_url: str) -> tuple[CollectedInfluencer | None, bool]:
    """对发现的 Instagram profile_url 执行 Apify 详情采集与联系方式补全。"""
    url = (profile_url or "").strip()
    if not url:
        return None, False
    normalized = url.rstrip("/") + "/"
    scrape = await scrape_instagram_profiles([normalized])
    profile = _pick_instagram_profile_from_scrape(
        scrape.profiles,
        profile_url=normalized,
        username=_username_from_instagram_profile_url(normalized),
    )
    if profile is None:
        return None, False
    await _safe_contact_enrich_collected(profile)
    tags = list(profile.tags or [])
    if INSTAGRAM_DETAIL_FETCHED_TAG not in tags:
        tags.append(INSTAGRAM_DETAIL_FETCHED_TAG)
    plat_tag = platform_detail_fetched_tag("instagram")
    if plat_tag not in tags:
        tags.append(plat_tag)
    profile.tags = tags
    return profile, True


async def _hydrate_tiktok_profile_detail(username: str) -> tuple[CollectedInfluencer | None, bool]:
    from app.services.api_direct_provider import discover_platform

    handle = (username or "").strip().lstrip("@")
    if not handle:
        return None, False
    url = f"https://www.tiktok.com/@{handle}"
    mini_task = SimpleNamespace(
        keywords=[],
        platform="tiktok",
        platforms=["tiktok"],
        input_urls=[url],
        discovery_limit=3,
        collection_mode="urls",
        country=None,
        category=None,
        min_followers_count=None,
    )
    try:
        result = await discover_platform(mini_task, "tiktok")
    except Exception as exc:
        logger.warning("TikTok seed hydrate failed for %s: %s", handle, exc)
        return None, False
    for profile in result.profiles or []:
        item = profile_to_collected(profile)
        if is_influencer_profile_valuable(item) or item.followers_count is not None or item.bio:
            tags = list(item.tags or [])
            plat_tag = platform_detail_fetched_tag("tiktok")
            if plat_tag not in tags:
                tags.append(plat_tag)
            item.tags = tags
            return item, True
    if result.profiles:
        item = profile_to_collected(result.profiles[0])
        tags = list(item.tags or [])
        plat_tag = platform_detail_fetched_tag("tiktok")
        if plat_tag not in tags:
            tags.append(plat_tag)
        item.tags = tags
        return item, True
    return None, False


async def _hydrate_youtube_profile_detail(username: str, display_name: str | None) -> tuple[CollectedInfluencer | None, bool]:
    item = await _try_youtube_profile(username, display_name)
    if item is None:
        return None, False
    await _safe_contact_enrich_collected(item)
    tags = list(item.tags or [])
    plat_tag = platform_detail_fetched_tag("youtube")
    if plat_tag not in tags:
        tags.append(plat_tag)
    item.tags = tags
    return item, True


async def _try_facebook_profile(username: str) -> CollectedInfluencer | None:
    from app.services.api_direct_provider import discover_platform

    handle = (username or "").strip().lstrip("@")
    if not handle:
        return None
    url = f"https://www.facebook.com/{handle}"
    mini_task = SimpleNamespace(
        keywords=[],
        platform="facebook",
        platforms=["facebook"],
        input_urls=[url],
        discovery_limit=3,
        collection_mode="urls",
        country=None,
        category=None,
        min_followers_count=None,
    )
    try:
        result = await discover_platform(mini_task, "facebook")
    except Exception as exc:
        logger.warning("Facebook seed hydrate failed for %s: %s", handle, exc)
        return None
    for profile in result.profiles or []:
        item = profile_to_collected(profile)
        if is_influencer_profile_valuable(item) or item.followers_count is not None:
            return item
    if result.profiles:
        return profile_to_collected(result.profiles[0])
    return None


async def _hydrate_facebook_profile_detail(username: str) -> tuple[CollectedInfluencer | None, bool]:
    item = await _try_facebook_profile(username)
    if item is None:
        return None, False
    await _safe_contact_enrich_collected(item)
    tags = list(item.tags or [])
    plat_tag = platform_detail_fetched_tag("facebook")
    if plat_tag not in tags:
        tags.append(plat_tag)
    item.tags = tags
    return item, True


async def _try_instagram_profile(username: str) -> CollectedInfluencer | None:
    shell = _instagram_profile_shell(username)
    if shell is None:
        return None
    detail, fetched = await _hydrate_instagram_profile_detail(shell.profile_url)
    return detail if fetched else shell


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
    """用 seed 用户名反查社媒主页、采集详情并选择最优平台 profile。"""
    platform = (seed.platform or "").strip().lower()
    username = (seed.username or "").strip()
    display_name = getattr(seed, "display_name", None)
    search_keywords = build_seed_search_keywords(username, display_name)
    notes: list[str] = []
    candidate_records: list[dict] = []
    hydrated_candidates: list[CollectedInfluencer] = []
    seed_detail_fetched = False

    if platform == "shopmy":
        seed, seed_detail_fetched = await _hydrate_shopmy_seed_detail(seed)
        if seed_detail_fetched:
            notes.append("ShopMy")
    elif platform == "ltk":
        seed, seed_detail_fetched = await _hydrate_ltk_seed_detail(seed)
        if seed_detail_fetched:
            notes.append("LTK")

    hydrate_jobs = []
    hydrated_social_keys: set[str] = set()
    explicit_social_platforms: set[str] = set()
    for link in _dedupe_social_links(list(seed.other_social_links or [])):
        link_url = str(link.get("url") or "").strip()
        link_platform = _social_platform_from_url(link_url)
        if not link_url or not link_platform:
            continue
        explicit_social_platforms.add(link_platform)
        key = f"{link_platform}:{link_url.lower().rstrip('/')}"
        if key in hydrated_social_keys:
            continue
        hydrated_social_keys.add(key)
        if link_platform == "instagram":
            hydrate_jobs.append(
                _record_platform_hydrate(
                    "instagram",
                    _hydrate_instagram_profile_detail(link_url),
                    profile_url=link_url,
                )
            )
        elif link_platform == "tiktok":
            profile = tiktok_profile_from_url(link_url)
            handle = profile.username if profile else None
            if handle:
                hydrate_jobs.append(
                    _record_platform_hydrate(
                        "tiktok",
                        _hydrate_tiktok_profile_detail(handle),
                        profile_url=link_url,
                    )
                )

    if username:
        ig_shell = _instagram_profile_shell(username)
        ig_key = f"instagram:{ig_shell.profile_url.lower().rstrip('/')}" if ig_shell else None
        if ig_shell and ig_key not in hydrated_social_keys and "instagram" not in explicit_social_platforms:
            hydrate_jobs.append(
                _record_platform_hydrate(
                    "instagram",
                    _hydrate_instagram_profile_detail(ig_shell.profile_url),
                    profile_url=ig_shell.profile_url,
                )
            )

        if "tiktok" not in explicit_social_platforms:
            hydrate_jobs.append(
                _record_platform_hydrate(
                    "tiktok",
                    _hydrate_tiktok_profile_detail(username),
                )
            )
        hydrate_jobs.append(
            _record_platform_hydrate(
                "facebook",
                _hydrate_facebook_profile_detail(username),
            )
        )

    hydrate_jobs.append(
        _record_platform_hydrate(
            "youtube",
            _hydrate_youtube_profile_detail(username, display_name),
        )
    )

    platform_labels = {
        "instagram": "Instagram",
        "tiktok": "TikTok",
        "facebook": "Facebook",
        "youtube": "YouTube",
    }
    for item, record in await asyncio.gather(*hydrate_jobs):
        candidate_records.append(record)
        platform_key = str(record.get("platform") or "").strip().lower()
        if item and (
            platform_key != "instagram"
            or record.get("status") == "fetched"
            or item.followers_count is not None
            or item.bio
        ):
            hydrated_candidates.append(item)
            if record.get("status") == "fetched":
                label = platform_labels.get(platform_key)
                if label:
                    notes.append(label)

    instagram_detail_fetched = any(
        is_platform_detail_fetched(c) or INSTAGRAM_DETAIL_FETCHED_TAG in (c.tags or [])
        for c in hydrated_candidates
        if (c.platform or "").lower() == "instagram"
    )
    platform_detail_fetched = any(is_platform_detail_fetched(c) for c in hydrated_candidates)

    primary = _pick_best_profile(hydrated_candidates)
    if primary and (primary.platform or "").lower() not in LINK_SEED_PLATFORMS:
        merged = merge_seed_into_primary(seed, primary)
        plat = (merged.platform or "").lower()
        if plat == "instagram" and merged.profile_url and not is_platform_detail_fetched(merged):
            detail, fetched = await _hydrate_instagram_profile_detail(merged.profile_url)
            if detail:
                merged = merge_seed_into_primary(seed, detail)
                instagram_detail_fetched = True
                platform_detail_fetched = True
        elif not is_platform_detail_fetched(merged):
            await _safe_contact_enrich_collected(merged)
            tags = list(merged.tags or [])
            tag = platform_detail_fetched_tag(plat)
            if tag not in tags:
                tags.append(tag)
            merged.tags = tags
            platform_detail_fetched = True
        else:
            await _safe_contact_enrich_collected(merged)

        selected_reason = _build_selected_reason(merged, candidate_records)
        contact_found = has_collection_contact_channel(merged)
        valuable = is_influencer_profile_valuable(merged)
        return LinkSeedEnrichmentResult(
            item=merged,
            seed_platform=platform,
            seed_profile_url=seed.profile_url,
            seed_username=username,
            enrichment_attempted=True,
            social_profiles_found=len(hydrated_candidates),
            contact_found=contact_found,
            primary_platform=merged.platform,
            is_valuable=valuable,
            instagram_detail_fetched=instagram_detail_fetched or is_platform_detail_fetched(merged),
            platform_detail_fetched=platform_detail_fetched or is_platform_detail_fetched(merged),
            enriched_profile_url=merged.profile_url,
            selected_reason=selected_reason,
            enrichment_candidates=candidate_records,
            enrichment_notes=notes,
            search_keywords=search_keywords,
            seed_source_meta=dict(getattr(seed, "source_meta", {}) or {}),
        )

    await _safe_contact_enrich_collected(seed)
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
        social_profiles_found=len(hydrated_candidates),
        contact_found=contact_found,
        primary_platform=seed.platform,
        is_valuable=valuable,
        instagram_detail_fetched=False,
        platform_detail_fetched=seed_detail_fetched,
        enriched_profile_url=None,
        selected_reason=None,
        enrichment_candidates=candidate_records,
        enrichment_notes=notes,
        search_keywords=search_keywords,
        seed_source_meta=dict(getattr(seed, "source_meta", {}) or {}),
    )


def collected_profile_snapshot(item: CollectedInfluencer) -> dict:
    """候选池 source_meta 中保留的 Instagram/社媒详情快照。"""
    links = item.other_social_links or []
    return {
        "platform": item.platform,
        "username": item.username,
        "profile_url": item.profile_url,
        "display_name": item.display_name,
        "avatar_url": item.avatar_url,
        "bio": item.bio,
        "followers_count": item.followers_count,
        "engagement_rate": item.engagement_rate,
        "email": item.email,
        "final_email": item.final_email,
        "public_email": item.public_email,
        "business_email": item.business_email,
        "email_source": item.email_source,
        "website": item.website,
        "contact_page": item.contact_page,
        "linktree_url": item.linktree_url,
        "whatsapp": item.whatsapp,
        "telegram": item.telegram,
        "contact_fetch_status": item.contact_fetch_status,
        "other_social_links": links if isinstance(links, list) else [],
    }


def enrichment_meta_dict(result: LinkSeedEnrichmentResult) -> dict:
    primary_plat = str(
        result.primary_platform or getattr(result.item, "platform", None) or ""
    ).strip().lower() or None
    enriched_platform = None
    if primary_plat and primary_plat not in LINK_SEED_PLATFORMS:
        enriched_platform = primary_plat
    meta = dict(result.seed_source_meta or {})
    meta.update({
        "link_seed_platform": result.seed_platform,
        "link_seed_profile_url": result.seed_profile_url,
        "link_seed_username": result.seed_username,
        "enrichment_attempted": result.enrichment_attempted,
        "social_profiles_found": result.social_profiles_found,
        "contact_found": result.contact_found,
        "primary_platform": primary_plat,
        "enriched_platform": enriched_platform,
        "enriched_profile_url": result.enriched_profile_url,
        "instagram_detail_fetched": result.instagram_detail_fetched,
        "platform_detail_fetched": result.platform_detail_fetched,
        "enrichment_candidates": list(result.enrichment_candidates or []),
        "selected_reason": result.selected_reason,
        "is_valuable": result.is_valuable,
        "enrichment_notes": result.enrichment_notes,
        "search_keywords": result.search_keywords,
    })
    return meta
