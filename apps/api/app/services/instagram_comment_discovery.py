# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：instagram comment discovery
"""Instagram 评论区用户发现：帖子/Reel/主页 → 评论 → 评论者候选。"""

from __future__ import annotations

import logging
import re

from app.core.config import settings
from app.services.apify_client import ApifyError, run_actor_sync
from app.services.apify_instagram import (
    DiscoveryResult,
    PostAuthorCandidate,
    _require_real_collector,
    _username_from_url,
)
from app.services.instagram_provider import (
    PROVIDER_API_DIRECT,
    active_provider_name,
    scrape_instagram_profiles,
)
from app.services.instagram_urls import (
    is_instagram_post_url,
    normalize_instagram_post_url,
    post_url_from_apify_raw,
    profile_url_from_apify_raw,
    sanitize_url_text,
)

logger = logging.getLogger(__name__)

POST_PATH_RE = re.compile(r"instagram\.com/(p|reel|tv)/([^/?#]+)", re.I)
PROFILE_RESERVED = frozenset({"p", "reel", "reels", "tv", "explore", "stories", "accounts"})


def classify_instagram_input_url(url: str) -> str:
    lower = url.strip().lower()
    if POST_PATH_RE.search(lower):
        return "post"
    if "instagram.com" in lower:
        return "profile"
    return "unknown"


def _normalize_post_url(url: str) -> str:
    normalized = normalize_instagram_post_url(url)
    if normalized:
        return normalized
    return sanitize_url_text(url).split("?")[0].rstrip("/") + "/"


async def _recent_post_urls_from_profile(profile_url: str, *, limit: int) -> tuple[list[str], list[str]]:
    if active_provider_name() == PROVIDER_API_DIRECT:
        from app.services.api_direct_instagram import recent_post_urls_for_profile

        return await recent_post_urls_for_profile(profile_url, limit=limit)

    scrape = await scrape_instagram_profiles([profile_url])
    errors = list(scrape.errors)
    if scrape.profiles:
        posts = scrape.profiles[0].recent_post_urls or []
        if posts:
            return [_normalize_post_url(u) for u in posts[:limit]], errors
        errors.append(f"主页 {profile_url} 未解析到近期帖子/Reel 链接")
        return [], errors
    if scrape.failed_profiles:
        detail = scrape.failed_profiles[0].detail or "主页补采失败"
        errors.append(f"无法从主页获取近期帖子: {detail}")
    return [], errors


async def resolve_target_post_urls(
    input_urls: list[str],
    *,
    posts_per_profile: int = 5,
) -> tuple[list[str], list[str]]:
    """将主页/帖子/Reel 输入统一解析为待抓评论的帖子 URL 列表。"""
    post_urls: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()

    for raw in input_urls:
        text = raw.strip()
        if not text:
            continue
        kind = classify_instagram_input_url(text)
        if kind == "post":
            key = _normalize_post_url(text).lower()
            if key not in seen:
                seen.add(key)
                post_urls.append(_normalize_post_url(text))
            continue
        if kind == "profile":
            resolved, profile_errors = await _recent_post_urls_from_profile(
                sanitize_url_text(text),
                limit=posts_per_profile,
            )
            errors.extend(profile_errors)
            for post in resolved:
                key = post.lower()
                if key not in seen:
                    seen.add(key)
                    post_urls.append(post)
            continue
        errors.append(f"无法识别的 Instagram 链接: {text}")

    return post_urls, errors


def _comment_text_from_raw(raw: dict) -> str | None:
    for key in ("text", "comment", "commentText", "caption", "content"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:2000]
    return None


def _comment_author_from_raw(raw: dict, *, source_post_url: str) -> PostAuthorCandidate | None:
    url = profile_url_from_apify_raw(raw)
    if not url:
        return None
    username = _username_from_url(url)
    if not username or username.lower() in PROFILE_RESERVED:
        return None
    comment_text = _comment_text_from_raw(raw)
    comment_url = raw.get("commentUrl")
    if isinstance(comment_url, str):
        comment_url = sanitize_url_text(comment_url)
        if not comment_url or is_instagram_post_url(comment_url):
            comment_url = None
    else:
        comment_url = None
    return PostAuthorCandidate(
        username=username,
        profile_url=url,
        source_post_url=normalize_instagram_post_url(source_post_url) or source_post_url,
        source_caption=comment_text,
        source_comment_text=comment_text,
        source_comment_url=str(comment_url) if comment_url else None,
        source_discovery_type="comment_author",
    )


async def discover_comment_authors_from_post_urls(
    post_urls: list[str],
    *,
    limit: int = 100,
) -> DiscoveryResult:
    """从帖子/Reel URL 列表发现评论区用户（Apify Comment Scraper）。"""
    _require_real_collector()
    if not settings.apify_instagram_comment_actor_id:
        raise ApifyError("APIFY_INSTAGRAM_COMMENT_ACTOR_ID is not configured")

    clean_posts = list(dict.fromkeys(_normalize_post_url(u) for u in post_urls if u and u.strip()))
    if not clean_posts:
        return DiscoveryResult(errors=["未提供有效的帖子/Reel URL"])

    return await _scrape_comments_for_posts(clean_posts, limit=limit)


async def discover_comment_authors_from_inputs(
    input_urls: list[str],
    *,
    limit: int = 100,
    posts_per_profile: int = 5,
) -> DiscoveryResult:
    """从帖子/Reel/主页输入发现评论区用户。"""
    _require_real_collector()
    if not settings.apify_instagram_comment_actor_id:
        raise ApifyError("APIFY_INSTAGRAM_COMMENT_ACTOR_ID is not configured")

    clean_inputs = [u.strip() for u in input_urls if u and u.strip()]
    if not clean_inputs:
        return DiscoveryResult(errors=["未提供有效的 Instagram 主页/帖子/Reel 链接"])

    post_urls, resolve_errors = await resolve_target_post_urls(
        clean_inputs,
        posts_per_profile=posts_per_profile,
    )
    errors = list(resolve_errors)
    if not post_urls:
        if not errors:
            errors.append("未能解析到任何待采集评论的帖子/Reel URL")
        return DiscoveryResult(errors=errors)

    result = await _scrape_comments_for_posts(post_urls, limit=limit)
    result.errors = [*errors, *result.errors]
    return result


async def _scrape_comments_for_posts(post_urls: list[str], *, limit: int) -> DiscoveryResult:
    comments_per_post = max(20, min(200, limit * 2))
    run_input = {
        "directUrls": post_urls,
        "resultsLimit": comments_per_post * len(post_urls),
        "maxComments": comments_per_post,
        "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }

    try:
        raw_items = await run_actor_sync(settings.apify_instagram_comment_actor_id, run_input)
    except ApifyError:
        run_input_alt = {
            "startUrls": [{"url": u} for u in post_urls],
            "resultsLimit": comments_per_post * len(post_urls),
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
        raw_items = await run_actor_sync(settings.apify_instagram_comment_actor_id, run_input_alt)

    candidates: list[PostAuthorCandidate] = []
    errors: list[str] = []
    seen: set[str] = set()
    post_url_by_shortcode: dict[str, str] = {}
    for post in post_urls:
        match = POST_PATH_RE.search(post)
        if match:
            post_url_by_shortcode[match.group(2).lower()] = post

    for index, raw in enumerate(raw_items, start=1):
        source_post = post_url_from_apify_raw(raw) or raw.get("postUrl")
        if not source_post:
            input_url = raw.get("inputUrl")
            if isinstance(input_url, str) and is_instagram_post_url(input_url):
                source_post = input_url
        if not source_post:
            shortcode = raw.get("shortCode") or raw.get("shortcode") or raw.get("postShortCode")
            if shortcode:
                source_post = post_url_by_shortcode.get(str(shortcode).lower()) or post_urls[0]
            else:
                source_post = post_urls[0]
        source_post_url = _normalize_post_url(str(source_post))

        candidate = _comment_author_from_raw(raw, source_post_url=source_post_url)
        if not candidate:
            post_ref = raw.get("id") or f"comment#{index}"
            errors.append(f"评论条目 {post_ref} 无法提取评论者主页")
            continue
        key = candidate.profile_url.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) >= limit:
            break

    if not candidates and raw_items:
        errors.append(f"共 {len(raw_items)} 条评论，但未解析到有效评论者账号")

    logger.info(
        "[CommentDiscovery] posts=%d comments_raw=%d authors=%d errors=%d",
        len(post_urls),
        len(raw_items),
        len(candidates),
        len(errors),
    )
    return DiscoveryResult(
        candidates=candidates,
        errors=errors,
        post_count=len(raw_items),
    )
