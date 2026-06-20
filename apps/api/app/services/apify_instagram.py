"""通过 Apify 采集 Instagram 主页真实数据。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.collectors.base import CollectedInfluencer
from app.models.enums import ProfileFailureReason

logger = logging.getLogger(__name__)
from collections.abc import Awaitable, Callable

from app.core.config import settings
from app.core.exceptions import APIFY_NOT_CONFIGURED_MSG, MOCK_COLLECTOR_DISABLED_MSG
from app.services.apify_client import ApifyError, run_actor_sync
from app.services.collection_filters import is_valid_instagram_username
from app.services.concurrency import map_bounded_incremental
from app.services.instagram_urls import (
    extract_profile_username,
    normalize_instagram_post_url,
    normalize_instagram_profile_url,
    post_url_from_apify_raw,
    profile_url_from_apify_raw,
    sanitize_url_text,
)


def _require_real_collector() -> None:
    from app.services.instagram_provider import InstagramProviderError, ensure_instagram_provider_ready

    try:
        ensure_instagram_provider_ready()
    except InstagramProviderError as exc:
        raise ApifyError(str(exc)) from exc

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


@dataclass
class PostAuthorCandidate:
    username: str
    profile_url: str
    source_hashtag: str | None = None
    source_post_url: str | None = None
    source_input_url: str | None = None
    source_caption: str | None = None
    post_type: str | None = None
    source_comment_url: str | None = None
    source_comment_text: str | None = None
    source_discovery_type: str | None = None
    source_meta: dict | None = None


@dataclass
class FailedProfile:
    username: str
    profile_url: str
    reason: ProfileFailureReason
    detail: str | None = None
    source_hashtag: str | None = None
    source_post_url: str | None = None
    source_caption: str | None = None
    source_comment_url: str | None = None
    source_comment_text: str | None = None
    source_discovery_type: str | None = None


@dataclass
class ProfileScrapeResult:
    profiles: list[CollectedInfluencer] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed_profiles: list[FailedProfile] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    profile_urls: list[str] = field(default_factory=list)
    post_urls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    candidates: list[PostAuthorCandidate] = field(default_factory=list)
    post_count: int = 0
    hashtag_count: int = 0


def _post_url_from_raw(raw: dict) -> str | None:
    return post_url_from_apify_raw(raw)


def _caption_from_raw(raw: dict) -> str | None:
    for key in ("caption", "text", "title", "description"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    captions = raw.get("captions")
    if isinstance(captions, list) and captions:
        first = captions[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    return None


def _post_type_from_raw(raw: dict) -> str | None:
    value = raw.get("type") or raw.get("productType") or raw.get("mediaType")
    return str(value) if value else None


def _source_fields_from_meta(meta: PostAuthorCandidate | None) -> dict:
    if not meta:
        return {}
    return {
        "source_hashtag": meta.source_hashtag,
        "source_post_url": meta.source_post_url,
        "source_caption": meta.source_caption,
        "source_comment_url": meta.source_comment_url,
        "source_comment_text": meta.source_comment_text,
        "source_discovery_type": meta.source_discovery_type,
    }


def classify_profile_failure(detail: str | None, *, raw: dict | None = None) -> ProfileFailureReason:
    text = (detail or "").lower()
    if raw:
        if raw.get("isPrivate") or raw.get("private"):
            return ProfileFailureReason.PRIVATE_ACCOUNT
    if any(token in text for token in ("private", "私密", "not public")):
        return ProfileFailureReason.PRIVATE_ACCOUNT
    if any(token in text for token in ("blocked", "rate limit", "429", "403", "challenge", "login")):
        return ProfileFailureReason.SCRAPER_BLOCKED
    if any(token in text for token in ("not found", "404", "does not exist", "不存在", "invalid user")):
        return ProfileFailureReason.PROFILE_NOT_FOUND
    if any(token in text for token in ("invalid", "malformed")):
        return ProfileFailureReason.INVALID_USERNAME
    return ProfileFailureReason.MISSING_PROFILE_DETAIL


def _username_from_url(url: str) -> str:
    return extract_profile_username(url) or ""


def _normalize_profile_url(username: str) -> str:
    return normalize_instagram_profile_url(username) or f"https://www.instagram.com/{username.strip().lstrip('@')}/"


def _username_from_any(raw: dict) -> str | None:
    for key in (
        "ownerUsername",
        "owner_user_name",
        "ownerUserName",
        "authorUsername",
        "author_user_name",
        "userUsername",
        "user_name",
        "username",
        "handle",
        "screenName",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            username = _username_from_url(value) if "instagram.com" in value else value.strip().lstrip("@")
            if username:
                return username

    for key in ("owner", "author", "user", "profile"):
        value = raw.get(key)
        if isinstance(value, dict):
            username = _username_from_any(value)
            if username:
                return username
        elif isinstance(value, str) and value.strip() and "instagram.com" not in value:
            return value.strip().lstrip("@")

    return None


def _profile_url_from_any(raw: dict) -> str | None:
    return profile_url_from_apify_raw(raw)


def _raw_field_summary(raw: dict, *, max_fields: int = 18) -> str:
    fields: list[str] = []

    def walk(value, prefix: str = "", depth: int = 0) -> None:
        if len(fields) >= max_fields or depth > 3:
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                if len(fields) >= max_fields:
                    return
                path = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(nested, dict):
                    fields.append(path)
                    walk(nested, path, depth + 1)
                elif isinstance(nested, list):
                    fields.append(f"{path}[]")
                    for item in nested[:2]:
                        walk(item, path, depth + 1)
                else:
                    fields.append(path)

    if isinstance(raw, dict):
        walk(raw)
    return ",".join(dict.fromkeys(fields)) or "empty"


def _post_author_missing_error(prefix: str, post_ref: str, raw: dict) -> str:
    return (
        f"{prefix} {post_ref} post_author_missing: 无法提取作者主页 "
        f"raw_fields={_raw_field_summary(raw)}"
    )


def _extract_emails(*texts: str | None) -> list[str]:
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in EMAIL_RE.findall(text):
            email = match.lower()
            if email not in found and not email.endswith((".png", ".jpg", ".jpeg")):
                found.append(email)
    return found


def _post_stats(images: list[dict]) -> tuple[int | None, int | None, int | None]:
    if not images:
        return None, None, None
    sample = images[:12]
    likes = [int(p["likes"]) for p in sample if p.get("likes") is not None]
    comments = [int(p["commentsCount"]) for p in sample if p.get("commentsCount") is not None]
    views = [int(p["views"]) for p in sample if p.get("views") is not None]
    avg_likes = int(sum(likes) / len(likes)) if likes else None
    avg_comments = int(sum(comments) / len(comments)) if comments else None
    avg_views = int(sum(views) / len(views)) if views else None
    return avg_views, avg_likes, avg_comments


def _profile_category_text(bio: str | None, raw: dict | None = None) -> str:
    parts: list[str] = []
    if bio:
        parts.append(bio)
    if raw:
        homepage = raw.get("homepage")
        if homepage:
            parts.append(str(homepage))
        for link in raw.get("bioLinks") or []:
            if isinstance(link, dict):
                if link.get("url"):
                    parts.append(str(link["url"]))
                if link.get("title"):
                    parts.append(str(link["title"]))
    return " ".join(parts)


def _has_amazon_commerce_intent(text: str) -> bool:
    lower = text.lower()
    strong_signals = (
        "amazon storefront",
        "amazon finds",
        "amzn.to",
        "amazon.com/shop",
        "amazon.com/stores",
        "storefront",
    )
    if any(signal in lower for signal in strong_signals):
        return True
    if "亚马逊" in text:
        return True
    if "amazon" in lower and any(word in lower for word in ("shop", "store", "deals", "finds")):
        return True
    if "amazon" in lower:
        return True
    return False


def _guess_category(bio: str | None, *, raw: dict | None = None) -> str:
    text = _profile_category_text(bio, raw)
    if not text.strip():
        return "lifestyle"
    lower = text.lower()
    if _has_amazon_commerce_intent(text):
        if any(
            signal in lower
            for signal in (
                "storefront",
                "amzn.to",
                "amazon storefront",
                "amazon finds",
                "amazon.com/shop",
                "amazon.com/stores",
            )
        ) or "亚马逊" in text:
            return "amazon_commerce"
        return "shopping"
    for keyword, category in [
        ("beauty", "beauty"),
        ("skincare", "beauty"),
        ("fashion", "fashion"),
        ("fitness", "fitness"),
        ("gaming", "gaming"),
        ("tech", "tech"),
        ("food", "food"),
        ("travel", "travel"),
        ("home", "home"),
    ]:
        if keyword in lower:
            return category
    return "lifestyle"


def _clamp_score(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, value)), 1)


def _followers_tier_score(followers: int | None) -> float:
    if not followers:
        return 35.0
    if followers >= 1_000_000:
        return 92.0
    if followers >= 500_000:
        return 86.0
    if followers >= 100_000:
        return 78.0
    if followers >= 50_000:
        return 70.0
    if followers >= 10_000:
        return 58.0
    return 45.0


def _engagement_signal(rate: float | None) -> float:
    if rate is None:
        return 45.0
    if rate >= 8:
        return 95.0
    if rate >= 5:
        return 86.0
    if rate >= 3:
        return 75.0
    if rate >= 1.5:
        return 62.0
    if rate >= 0.5:
        return 46.0
    return 30.0


def _topic_signals(category: str, bio: str | None) -> tuple[list[str], list[str], float]:
    text = (bio or "").lower()
    topic_map = {
        "beauty": ["skincare", "makeup", "beauty"],
        "fashion": ["fashion", "outfit", "style"],
        "fitness": ["fitness", "training", "wellness"],
        "travel": ["travel", "outdoor", "city guide"],
        "food": ["food", "recipe", "restaurant"],
        "tech": ["tech", "gadget", "review"],
        "shopping": ["amazon finds", "shopping", "deals"],
        "amazon_commerce": ["amazon", "storefront", "deals", "finds"],
        "gaming": ["gaming", "setup", "streaming"],
    }
    topics = topic_map.get(category, [category, "lifestyle", "review"])
    commerce_words = ("amazon", "shop", "store", "coupon", "affiliate", "discount", "code", "collab", "review")
    commerce_signal = 12.0 if any(word in text for word in commerce_words) else 0.0
    collaboration_formats = ["Reels 短视频", "Story 种草"]
    if category in {"tech", "shopping", "beauty", "fashion", "fitness"}:
        collaboration_formats.append("产品测评")
    if category in {"travel", "food"}:
        collaboration_formats.append("场景 Vlog")
    return topics, collaboration_formats, commerce_signal


def _estimate_price(followers: int | None, engagement_rate: float | None) -> str | None:
    if not followers:
        return None
    engagement_boost = 1.25 if engagement_rate and engagement_rate >= 3 else 1.0
    if followers >= 1_000_000:
        return f"${int(8000 * engagement_boost):,}-${int(25000 * engagement_boost):,}"
    if followers >= 100_000:
        return f"${int(1200 * engagement_boost):,}-${int(6000 * engagement_boost):,}"
    if followers >= 10_000:
        return f"${int(250 * engagement_boost):,}-${int(1200 * engagement_boost):,}"
    return f"${int(50 * engagement_boost):,}-${int(250 * engagement_boost):,}"


def map_apify_instagram_profile(raw: dict, *, fallback_url: str | None = None) -> CollectedInfluencer:
    username = raw.get("username") or _username_from_url(fallback_url or "")
    if not username:
        raise ValueError("Apify 结果缺少 username")

    profile_url = _normalize_profile_url(username)
    bio = raw.get("bio") or raw.get("biography") or ""
    followers = raw.get("followers") or raw.get("followersCount")
    if followers is not None:
        followers = int(followers)

    images = raw.get("images") or []
    avg_views, avg_likes, avg_comments = _post_stats(images)

    engagement_rate = None
    if followers and avg_likes is not None:
        comments_part = avg_comments or 0
        engagement_rate = round((avg_likes + comments_part) / max(followers, 1) * 100, 2)

    emails = _extract_emails(bio, raw.get("businessEmail"))
    all_emails = raw.get("allEmails") or []
    if isinstance(all_emails, list):
        for item in all_emails:
            if isinstance(item, str):
                emails.extend(_extract_emails(item))
            elif isinstance(item, dict) and item.get("email"):
                emails.append(item["email"].lower())
    emails = list(dict.fromkeys(emails))

    business_email = raw.get("businessEmail")
    if business_email:
        business_email = str(business_email).lower()
    public_email = emails[0] if emails else None
    final_email = business_email or public_email

    homepage = raw.get("homepage")
    linktree_url = None
    if homepage and "link" in homepage.lower():
        linktree_url = homepage
    for link in raw.get("bioLinks") or []:
        if isinstance(link, dict) and link.get("url"):
            url = link["url"]
            if "link" in url.lower() or "bio" in url.lower():
                linktree_url = linktree_url or url

    recent_titles: list[str] = []
    recent_urls: list[str] = []
    last_post_at: datetime | None = None
    for post in images[:5]:
        captions = post.get("captions") or []
        if captions and captions[0]:
            recent_titles.append(str(captions[0])[:200])
        shortcode = post.get("shortcode")
        if shortcode:
            recent_urls.append(
                normalize_instagram_post_url(None, {"shortcode": shortcode, "type": post.get("type")})
                or f"https://www.instagram.com/p/{shortcode}/"
            )
        taken_at = post.get("takenAt")
        if taken_at and last_post_at is None:
            last_post_at = datetime.fromtimestamp(int(taken_at), tz=UTC)

    category = _guess_category(bio, raw=raw)
    content_topics, collaboration_formats, commerce_signal = _topic_signals(category, bio)
    tags = ["instagram", "apify", category]
    if raw.get("isVerified"):
        tags.append("verified")

    other_links = []
    for link in raw.get("bioLinks") or []:
        if isinstance(link, dict) and link.get("url"):
            other_links.append({"label": link.get("title") or "link", "url": link["url"]})

    completeness = 40.0
    if bio:
        completeness += 15
    if followers:
        completeness += 15
    if final_email:
        completeness += 15
    if avg_likes is not None:
        completeness += 15

    follower_score = _followers_tier_score(followers)
    engagement_score = _engagement_signal(engagement_rate)
    contact_bonus = 10.0 if final_email else (5.0 if linktree_url else 0.0)
    product_fit = _clamp_score(52.0 + engagement_score * 0.25 + commerce_signal + contact_bonus)
    travel_fit_score = _clamp_score(82.0 if category == "travel" else 58.0 + (8.0 if "outdoor" in (bio or "").lower() else 0.0))
    purchasing_power_score = _clamp_score(45.0 + follower_score * 0.35 + (8.0 if category in {"fashion", "beauty", "tech", "shopping"} else 0.0))
    sales_potential_score = _clamp_score(38.0 + engagement_score * 0.35 + follower_score * 0.2 + commerce_signal + contact_bonus)
    audience_match_score = _clamp_score(60.0 + (15.0 if category in {"beauty", "fashion", "fitness", "travel", "shopping"} else 5.0))
    roi_forecast = round(max(1.0, (sales_potential_score / 32.0) + (engagement_rate or 0) / 10.0), 1)

    avatar_url=(
        raw.get("profilePicUrl")
        or raw.get("profilePicture")
        or raw.get("profilePicUrlHD")
        or raw.get("profileImageHD")
        or raw.get("profileImage")
        or raw.get("profile_image_url")
        or raw.get("avatar_url")
        or raw.get("avatar")
    )

    # 调试日志：打印 Apify 返回中所有可能含头像/图片的字段
    avatar_fields = {k: str(v)[:100] for k, v in raw.items() if any(kw in k.lower() for kw in ["avatar", "pic", "image", "photo", "picture"])}
    logger.debug("[Apify] username=%s | avatar=%s | avatar相关字段: %s", username, avatar_url, avatar_fields)

    return CollectedInfluencer(
        platform="instagram",
        username=username,
        display_name=raw.get("name") or raw.get("fullName") or username,
        profile_url=profile_url,
        avatar_url=avatar_url,
        language="en",
        category=category,
        niche=category,
        bio=bio,
        followers_count=followers,
        avg_views=avg_views,
        avg_likes=avg_likes,
        avg_comments=avg_comments,
        engagement_rate=engagement_rate,
        email=final_email,
        final_email=final_email,
        public_email=public_email,
        business_email=business_email,
        email_source="bio" if public_email else ("business_profile" if business_email else None),
        contact_credibility=80.0 if final_email else None,
        contact_score=75.0 if final_email else (50.0 if linktree_url else None),
        website=homepage if homepage and "instagram" not in homepage else None,
        linktree_url=linktree_url,
        other_social_links=other_links,
        product_fit=product_fit,
        data_completeness=min(100.0, completeness),
        has_brand_collaboration=raw.get("isProfessionalAccount") or raw.get("isBusinessAccount"),
        estimated_collab_price=_estimate_price(followers, engagement_rate),
        collaboration_formats=collaboration_formats,
        content_topics=content_topics,
        audience_country="US",
        audience_language="en",
        travel_fit_score=travel_fit_score,
        purchasing_power_score=purchasing_power_score,
        sales_potential_score=sales_potential_score,
        audience_match_score=audience_match_score,
        roi_forecast=roi_forecast,
        recent_post_titles=recent_titles,
        recent_post_urls=recent_urls,
        last_post_at=last_post_at,
        posting_frequency="近 12 条内容估算" if images else None,
        tags=tags,
    )


async def scrape_instagram_profiles(
    urls_or_usernames: list[str],
    *,
    candidate_meta: dict[str, PostAuthorCandidate] | None = None,
    on_item_complete: Callable[[str, CollectedInfluencer | FailedProfile | None, str | None], Awaitable[None]]
    | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ProfileScrapeResult:
    """Step3 Hydration：批量/并发补采 Instagram 主页详情。"""
    if not urls_or_usernames:
        return ProfileScrapeResult()

    _require_real_collector()
    candidate_meta = candidate_meta or {}

    targets: list[str] = []
    url_by_username: dict[str, str] = {}
    requested_labels: dict[str, str] = {}
    for item in urls_or_usernames:
        text = item.strip()
        if not text:
            continue
        if "instagram.com" in text:
            username = _username_from_url(text)
            if username:
                targets.append(username)
                key = username.lower()
                url_by_username[key] = normalize_instagram_profile_url(text) or sanitize_url_text(text)
                requested_labels[key] = text
        else:
            username = text.lstrip("@")
            targets.append(username)
            key = username.lower()
            url_by_username[key] = _normalize_profile_url(username)
            requested_labels[key] = text

    unique_targets = list(dict.fromkeys(targets))
    if not unique_targets:
        return ProfileScrapeResult(errors=["未解析到有效的 Instagram 用户名或主页链接"])

    results: list[CollectedInfluencer] = []
    errors: list[str] = []
    failed_profiles: list[FailedProfile] = []
    seen: set[str] = set()
    hydrated_usernames: set[str] = set()
    failed_keys: set[str] = set()
    chunk_size = max(1, min(10, settings.effective_profile_enrich_concurrency * 2))

    async def _notify(label: str, profile: CollectedInfluencer | None, failed: FailedProfile | None, err: str | None) -> None:
        if on_item_complete is None:
            return
        item_result = profile if profile is not None else failed
        await on_item_complete(label, item_result, err)

    async def _scrape_chunk(chunk: list[str]) -> None:
        run_input = {
            "usernames": chunk,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
            },
        }
        raw_items = await run_actor_sync(settings.apify_instagram_actor_id, run_input)
        for raw in raw_items:
            username_raw = raw.get("username") or _username_from_url(str(raw.get("url") or ""))
            label = f"@{username_raw}" if username_raw else "unknown"
            key = (username_raw or "").lower()
            if raw.get("success") is False:
                detail = raw.get("error") or raw.get("errorMessage") or raw.get("message") or "success=false"
                errors.append(f"Apify 主页采集失败 {label}: {detail}")
                if key and key not in failed_keys:
                    failed_keys.add(key)
                    meta = candidate_meta.get(key)
                    failed = FailedProfile(
                        username=username_raw or key,
                        profile_url=url_by_username.get(key, _normalize_profile_url(username_raw or key)),
                        reason=classify_profile_failure(str(detail), raw=raw),
                        detail=str(detail),
                        **_source_fields_from_meta(meta),
                    )
                    failed_profiles.append(failed)
                    await _notify(requested_labels.get(key, label), None, failed, str(detail))
                continue
            username = key
            if not username or username in seen:
                continue
            seen.add(username)
            hydrated_usernames.add(username)
            fallback = url_by_username.get(username)
            try:
                profile = map_apify_instagram_profile(raw, fallback_url=fallback)
                results.append(profile)
                await _notify(requested_labels.get(username, label), profile, None, None)
            except ValueError as exc:
                errors.append(f"主页数据映射失败 {label}: {exc}")
                if username not in failed_keys:
                    failed_keys.add(username)
                    meta = candidate_meta.get(username)
                    failed = FailedProfile(
                        username=username_raw or username,
                        profile_url=fallback or _normalize_profile_url(username),
                        reason=ProfileFailureReason.MISSING_PROFILE_DETAIL,
                        detail=str(exc),
                        **_source_fields_from_meta(meta),
                    )
                    failed_profiles.append(failed)
                    await _notify(requested_labels.get(username, label), None, failed, str(exc))

    chunks = [unique_targets[i : i + chunk_size] for i in range(0, len(unique_targets), chunk_size)]

    async def _run_chunk(chunk: list[str]) -> None:
        try:
            await _scrape_chunk(chunk)
        except Exception as exc:
            detail = str(exc)
            for username in chunk:
                key = username.lower()
                if key in hydrated_usernames or key in failed_keys:
                    continue
                errors.append(f"Apify 主页批次失败 @{username}: {detail}")
                failed_keys.add(key)
                meta = candidate_meta.get(key)
                failed = FailedProfile(
                    username=username,
                    profile_url=url_by_username.get(key, _normalize_profile_url(username)),
                    reason=classify_profile_failure(detail),
                    detail=detail,
                    **_source_fields_from_meta(meta),
                )
                failed_profiles.append(failed)
                await _notify(requested_labels.get(key, username), None, failed, detail)

    await map_bounded_incremental(
        chunks,
        _run_chunk,
        concurrency=settings.effective_profile_enrich_concurrency,
        should_stop=should_stop,
    )

    for key, label in requested_labels.items():
        if key in hydrated_usernames or key in failed_keys:
            continue
        detail = f"未获取到主页数据: {label}"
        errors.append(detail)
        meta = candidate_meta.get(key)
        failed = FailedProfile(
            username=key,
            profile_url=url_by_username.get(key, label),
            reason=ProfileFailureReason.MISSING_PROFILE_DETAIL,
            detail=detail,
            **_source_fields_from_meta(meta),
        )
        failed_profiles.append(failed)
        await _notify(label, None, failed, detail)

    return ProfileScrapeResult(profiles=results, errors=errors, failed_profiles=failed_profiles)


async def discover_post_authors_from_hashtags(
    hashtags: list[str],
    *,
    limit: int = 100,
) -> DiscoveryResult:
    """Step1 Discovery：hashtag -> 帖子/Reels -> 提取作者 username/profileUrl。"""
    _require_real_collector()

    if not settings.apify_instagram_hashtag_actor_id:
        raise ApifyError("APIFY_INSTAGRAM_HASHTAG_ACTOR_ID is not configured")

    clean_tags = [tag.strip().lstrip("#") for tag in hashtags if tag and tag.strip()]
    if not clean_tags:
        return DiscoveryResult(errors=["未提供有效的 hashtag"])

    run_input = {
        "hashtags": clean_tags,
        "resultsLimit": max(limit * 3, limit),
        "resultsType": "posts",
        "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }
    raw_items = await run_actor_sync(settings.apify_instagram_hashtag_actor_id, run_input)

    candidates: list[PostAuthorCandidate] = []
    profile_urls: list[str] = []
    post_urls: list[str] = []
    errors: list[str] = []
    seen_authors: set[str] = set()
    seen_posts: set[str] = set()
    source_tag = clean_tags[0] if len(clean_tags) == 1 else ",".join(clean_tags)

    for index, raw in enumerate(raw_items, start=1):
        post_url = _post_url_from_raw(raw)
        if post_url:
            post_key = post_url.lower()
            if post_key not in seen_posts:
                seen_posts.add(post_key)
                post_urls.append(post_url)

        url = _profile_url_from_any(raw)
        if not url:
            post_ref = raw.get("shortCode") or raw.get("id") or f"post#{index}"
            errors.append(_post_author_missing_error("Hashtag 帖子", str(post_ref), raw))
            continue
        username = _username_from_url(url)
        key = url.lower()
        if key in seen_authors:
            continue
        seen_authors.add(key)
        normalized_profile = normalize_instagram_profile_url(url) or url
        candidate = PostAuthorCandidate(
            username=username or extract_profile_username(normalized_profile) or "",
            profile_url=normalized_profile,
            source_hashtag=raw.get("hashtag") or raw.get("inputUrl") or source_tag,
            source_post_url=post_url,
            source_caption=_caption_from_raw(raw),
            post_type=_post_type_from_raw(raw),
            source_discovery_type="post_author",
        )
        candidates.append(candidate)
        profile_urls.append(url)
        if len(candidates) >= limit:
            break

    if not candidates and raw_items:
        errors.append(f"Hashtag {clean_tags} 共 {len(raw_items)} 条帖子，但未解析到任何作者主页")

    logger.info(
        "[Discovery] hashtags=%s posts=%d unique_authors=%d errors=%d",
        clean_tags,
        len(raw_items),
        len(candidates),
        len(errors),
    )
    return DiscoveryResult(
        profile_urls=profile_urls,
        post_urls=post_urls,
        errors=errors,
        candidates=candidates,
        post_count=len(raw_items),
        hashtag_count=len(clean_tags),
    )


async def discover_post_authors_from_post_urls(
    post_urls: list[str],
    *,
    limit: int = 100,
) -> DiscoveryResult:
    """帖子/Reel 直链 → 通过 Apify 拉取帖子详情并提取作者。"""
    _require_real_collector()

    if not settings.apify_instagram_post_actor_id:
        return DiscoveryResult(errors=["APIFY_INSTAGRAM_POST_ACTOR_ID 未配置，无法从帖子/Reel 提取作者"])

    clean_urls = []
    seen: set[str] = set()
    for raw in post_urls:
        url = (raw or "").strip()
        if not url or "instagram.com" not in url.lower():
            continue
        key = url.lower().split("?")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            clean_urls.append(url.strip())

    if not clean_urls:
        return DiscoveryResult(errors=["未提供有效的 Instagram 帖子/Reel 链接"])

    run_input = {
        "username": clean_urls[: max(1, min(20, len(clean_urls)))],
        "resultsLimit": max(limit, len(clean_urls)),
    }
    raw_items = await run_actor_sync(settings.apify_instagram_post_actor_id, run_input)

    candidates: list[PostAuthorCandidate] = []
    errors: list[str] = []
    seen_authors: set[str] = set()

    for index, raw in enumerate(raw_items, start=1):
        post_url = _post_url_from_raw(raw) or (clean_urls[index - 1] if index <= len(clean_urls) else None)
        url = _profile_url_from_any(raw)
        if not url:
            post_ref = raw.get("shortCode") or raw.get("id") or post_url or f"post#{index}"
            errors.append(_post_author_missing_error("帖子", str(post_ref), raw))
            continue
        username = _username_from_url(url)
        key = url.lower()
        if key in seen_authors:
            continue
        seen_authors.add(key)
        normalized_profile = normalize_instagram_profile_url(url) or url
        candidates.append(
            PostAuthorCandidate(
                username=username or extract_profile_username(normalized_profile) or "",
                profile_url=normalized_profile,
                source_post_url=post_url,
                source_caption=_caption_from_raw(raw),
                post_type=_post_type_from_raw(raw),
                source_discovery_type="post_author",
            )
        )
        if len(candidates) >= limit:
            break

    if not candidates and raw_items:
        errors.append(f"共 {len(raw_items)} 条帖子数据，但未解析到任何作者主页")

    logger.info(
        "[Discovery] post_urls=%d raw_items=%d authors=%d errors=%d",
        len(clean_urls),
        len(raw_items),
        len(candidates),
        len(errors),
    )
    return DiscoveryResult(
        candidates=candidates,
        post_urls=clean_urls,
        errors=errors,
        post_count=len(raw_items) or len(clean_urls),
    )


async def discover_candidate_profile_urls(
    hashtags: list[str],
    *,
    limit: int = 100,
) -> DiscoveryResult:
    """兼容旧调用：返回帖子作者候选主页 URL。"""
    return await discover_post_authors_from_hashtags(hashtags, limit=limit)


async def discover_instagram_profiles_by_hashtags(
    hashtags: list[str],
    *,
    limit: int = 100,
) -> list[CollectedInfluencer]:
    """Discovery + Hydration（兼容旧调用）。"""
    discovery = await discover_candidate_profile_urls(hashtags, limit=limit)
    scrape = await scrape_instagram_profiles(discovery.profile_urls)
    scrape.errors = [*discovery.errors, *scrape.errors]
    return scrape.profiles


def _uses_thenetaji_related_actor(actor_id: str) -> bool:
    slug = actor_id.lower().replace("/", "~")
    return "instagram-related-user-scraper" in slug or slug.startswith("thenetaji~")


def _related_discovery_run_input(seeds: list[str], limit: int) -> dict:
    """按 Actor 类型构造入参（thenetaji 用 username/maxItem，其它用 startUrls）。"""
    actor_id = settings.apify_instagram_related_actor_id
    if actor_id and _uses_thenetaji_related_actor(actor_id):
        usernames: list[str] = []
        for seed in seeds:
            text = seed.strip()
            if not text:
                continue
            username = _username_from_url(text) if "instagram.com" in text else text.lstrip("@").strip()
            if username and is_valid_instagram_username(username):
                usernames.append(username)
        usernames = list(dict.fromkeys(usernames))[:limit]
        return {
            "type": "similar_users",
            "username": usernames,
            "maxItem": limit,
        }
    return {
        "startUrls": [{"url": url} for url in seeds],
        "resultsLimit": limit,
        "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }


async def discover_related_candidate_urls(
    seed_urls: list[str],
    *,
    limit: int = 100,
) -> tuple[list[str], list[str]]:
    """Step1 Discovery：从种子账号发现相关创作者主页 URL。"""
    _require_real_collector()
    seeds = list(dict.fromkeys(u.strip() for u in seed_urls if u and u.strip()))[:limit]
    if not settings.apify_instagram_related_actor_id:
        return seeds, []

    run_input = _related_discovery_run_input(seeds, limit)
    if _uses_thenetaji_related_actor(settings.apify_instagram_related_actor_id):
        usernames = run_input.get("username") or []
        if not usernames:
            return seeds, ["关联发现需要有效的种子 Instagram 用户名或主页链接"]
    raw_items = await run_actor_sync(settings.apify_instagram_related_actor_id, run_input)

    profile_urls: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items, start=1):
        url = _profile_url_from_any(raw)
        if not url:
            errors.append(f"关联发现条目 #{index} 无法提取主页链接")
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        profile_urls.append(url)
        if len(profile_urls) >= limit:
            break
    if not profile_urls:
        return seeds, errors or ["关联发现未返回主页，已回退使用种子链接"]
    return profile_urls, errors


async def discover_related_instagram_profiles(
    seed_urls: list[str],
    *,
    limit: int = 100,
) -> list[CollectedInfluencer]:
    """Discovery + Hydration（兼容旧调用）。"""
    profile_urls, discovery_errors = await discover_related_candidate_urls(seed_urls, limit=limit)
    scrape = await scrape_instagram_profiles(profile_urls)
    scrape.errors.extend(discovery_errors)
    return scrape.profiles


async def scrape_instagram_url(url: str) -> CollectedInfluencer:
    scrape = await scrape_instagram_profiles([url])
    if not scrape.profiles:
        detail = scrape.errors[0] if scrape.errors else f"未能从 Apify 获取 Instagram 资料: {url}"
        raise ApifyError(detail)
    return scrape.profiles[0]
