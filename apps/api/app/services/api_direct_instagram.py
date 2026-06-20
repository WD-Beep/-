"""通过 API Direct (apidirect.io) 采集 Instagram 数据。"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.collectors.base import CollectedInfluencer
from app.models.enums import ProfileFailureReason
from app.services.apify_instagram import (
    DiscoveryResult,
    FailedProfile,
    PostAuthorCandidate,
    ProfileScrapeResult,
    _caption_from_raw,
    _normalize_profile_url,
    _post_type_from_raw,
    _source_fields_from_meta,
    _username_from_url,
    classify_profile_failure,
    map_apify_instagram_profile,
)
from app.services.collection_filters import is_valid_instagram_username
from app.services.instagram_urls import (
    extract_profile_username,
    normalize_instagram_post_url,
    normalize_instagram_profile_url,
    sanitize_url_text,
)
from app.services.api_direct_client import ApiDirectError, ad_get
from app.services.concurrency import map_bounded, map_bounded_incremental
from app.core.config import settings

logger = logging.getLogger(__name__)

PROVIDER_TAG = "api_direct"
POST_PATH_RE = re.compile(r"instagram\.com/(p|reel|tv)/([^/?#]+)", re.I)


def _replace_provider_tag(profile: CollectedInfluencer) -> CollectedInfluencer:
    if profile.tags:
        profile.tags = [PROVIDER_TAG if t == "apify" else t for t in profile.tags]
    return profile


def user_to_apify_raw(user: dict) -> dict:
    """API Direct user 对象 → map_apify_instagram_profile 字段。"""
    bio_links = []
    for link in user.get("bio_links") or []:
        if isinstance(link, dict):
            bio_links.append(link)

    public_email = user.get("public_email")
    if isinstance(public_email, str) and not public_email.strip():
        public_email = None

    return {
        "username": user.get("username"),
        "name": user.get("full_name"),
        "bio": user.get("biography"),
        "followers": user.get("follower_count"),
        "businessEmail": public_email,
        "profilePicUrl": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
        "homepage": user.get("external_url"),
        "isVerified": user.get("is_verified"),
        "isPrivate": user.get("is_private"),
        "bioLinks": bio_links,
        "isBusinessAccount": user.get("is_business"),
        "images": [],
    }


def post_item_to_apify_raw(post: dict) -> dict:
    """搜索帖子条目 → 含作者信息的扁平 dict。"""
    author = post.get("author") or ""
    username = str(author).lstrip("@") if author else None
    profile_url = _normalize_profile_url(username) if username else None
    post_url = post.get("url")
    media_type = post.get("media_type")
    post_type = "reel" if media_type in ("clips", "reel") else "post"
    shortcode = None
    if post_url:
        match = POST_PATH_RE.search(post_url)
        if match:
            shortcode = match.group(2)

    return {
        "username": username,
        "ownerUsername": username,
        "profileUrl": profile_url,
        "url": post_url,
        "shortcode": shortcode,
        "caption": post.get("snippet"),
        "type": post_type,
        "likes": post.get("likes"),
        "commentsCount": post.get("comments"),
        "views": post.get("views"),
    }


def _pages_for_limit(limit: int) -> int:
    return max(1, min(10, (limit + 9) // 10))


def _shortcode_from_post_url(url: str) -> str | None:
    match = POST_PATH_RE.search(url)
    return match.group(2) if match else None


async def _scrape_one_profile(
    item: str,
    *,
    candidate_meta: dict[str, PostAuthorCandidate],
) -> tuple[CollectedInfluencer | None, str | None, FailedProfile | None]:
    text = item.strip()
    if not text:
        return None, None, None
    if "instagram.com" in text:
        username = _username_from_url(text)
        profile_url = normalize_instagram_profile_url(text) or sanitize_url_text(text)
        params: dict[str, str] = {"url": profile_url}
    else:
        username = text.lstrip("@")
        profile_url = _normalize_profile_url(username)
        params = {"username": username}

    if not username or not is_valid_instagram_username(username):
        return None, f"无效用户名: {text}", None

    key = username.lower()
    meta = candidate_meta.get(key)

    try:
        payload = await asyncio.wait_for(
            ad_get("/v1/instagram/user", params=params, platform="instagram"),
            timeout=max(5, settings.collection_profile_request_timeout_seconds),
        )
    except asyncio.TimeoutError:
        detail = f"@{username} 主页请求超时（{settings.collection_profile_request_timeout_seconds}s）"
        failed = FailedProfile(
            username=username,
            profile_url=profile_url,
            reason=ProfileFailureReason.SCRAPER_BLOCKED,
            detail=detail,
            **_source_fields_from_meta(meta),
        )
        return None, detail, failed
    except ApiDirectError as exc:
        detail = str(exc)
        failed = FailedProfile(
            username=username,
            profile_url=profile_url,
            reason=classify_profile_failure(detail),
            detail=detail,
            **_source_fields_from_meta(meta),
        )
        return None, detail, failed

    user = payload.get("user")
    if not isinstance(user, dict) or not user.get("username"):
        detail = f"未获取到主页数据: @{username}"
        failed = FailedProfile(
            username=username,
            profile_url=profile_url,
            reason=ProfileFailureReason.MISSING_PROFILE_DETAIL,
            detail=detail,
            **_source_fields_from_meta(meta),
        )
        return None, detail, failed

    raw = user_to_apify_raw(user)
    if raw.get("isPrivate"):
        detail = f"@{username} 为私密账号"
        failed = FailedProfile(
            username=username,
            profile_url=profile_url,
            reason=ProfileFailureReason.PRIVATE_ACCOUNT,
            detail=detail,
            **_source_fields_from_meta(meta),
        )
        return None, detail, failed

    try:
        profile = map_apify_instagram_profile(raw, fallback_url=profile_url)
        return _replace_provider_tag(profile), None, None
    except ValueError as exc:
        detail = f"@{username} 映射失败: {exc}"
        failed = FailedProfile(
            username=username,
            profile_url=profile_url,
            reason=ProfileFailureReason.MISSING_PROFILE_DETAIL,
            detail=detail,
            **_source_fields_from_meta(meta),
        )
        return None, detail, failed


async def scrape_instagram_profiles(
    urls_or_usernames: list[str],
    *,
    candidate_meta: dict[str, PostAuthorCandidate] | None = None,
    on_item_complete: Callable[[str, CollectedInfluencer | FailedProfile | None, str | None], Awaitable[None]]
    | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ProfileScrapeResult:
    if not urls_or_usernames:
        return ProfileScrapeResult()

    candidate_meta = candidate_meta or {}
    results: list[CollectedInfluencer] = []
    errors: list[str] = []
    failed_profiles: list[FailedProfile] = []
    failed_keys: set[str] = set()

    async def _worker(item: str) -> tuple[CollectedInfluencer | None, str | None, FailedProfile | None]:
        return await _scrape_one_profile(item, candidate_meta=candidate_meta)

    async def _on_complete(
        item: str,
        outcome: tuple[CollectedInfluencer | None, str | None, FailedProfile | None] | BaseException,
    ) -> None:
        if isinstance(outcome, BaseException):
            errors.append(str(outcome))
            if on_item_complete is not None:
                await on_item_complete(item, None, str(outcome))
            return
        profile, err, failed = outcome
        if err:
            errors.append(err)
        if failed:
            key = failed.username.lower()
            if key not in failed_keys:
                failed_keys.add(key)
                failed_profiles.append(failed)
        if profile:
            results.append(profile)
        if on_item_complete is not None:
            await on_item_complete(item, profile if profile else failed, err)

    await map_bounded_incremental(
        urls_or_usernames,
        _worker,
        concurrency=settings.effective_profile_enrich_concurrency,
        on_complete=_on_complete,
        should_stop=should_stop,
    )

    return ProfileScrapeResult(profiles=results, errors=errors, failed_profiles=failed_profiles)


async def discover_post_authors_from_hashtags(
    hashtags: list[str],
    *,
    limit: int = 100,
) -> DiscoveryResult:
    clean_tags = [tag.strip().lstrip("#") for tag in hashtags if tag and tag.strip()]
    if not clean_tags:
        return DiscoveryResult(errors=["未提供有效的 hashtag"])

    candidates: list[PostAuthorCandidate] = []
    profile_urls: list[str] = []
    post_urls: list[str] = []
    errors: list[str] = []
    seen_authors: set[str] = set()
    seen_posts: set[str] = set()
    raw_total = 0
    pages = _pages_for_limit(limit)

    async def _fetch_tag(tag: str):
        try:
            payload = await ad_get(
                "/v1/instagram/posts",
                params={"query": tag, "pages": str(pages)},
                platform="instagram",
            )
            return tag, payload, None
        except ApiDirectError as exc:
            return tag, None, str(exc)

    tag_outcomes = await map_bounded(
        clean_tags,
        _fetch_tag,
        concurrency=settings.collection_search_concurrency,
    )

    for outcome in tag_outcomes:
        if isinstance(outcome, BaseException):
            errors.append(str(outcome))
            continue
        tag, payload, err = outcome
        if err:
            errors.append(f"Hashtag #{tag}: {err}")
            continue
        posts = (payload or {}).get("posts") or []
        if not isinstance(posts, list):
            posts = []
        raw_total += len(posts)

        for raw in posts:
            if not isinstance(raw, dict):
                continue
            mapped = post_item_to_apify_raw(raw)
            post_url = mapped.get("url")
            if post_url:
                pk = post_url.lower()
                if pk not in seen_posts:
                    seen_posts.add(pk)
                    post_urls.append(post_url)

            username = mapped.get("username")
            if not username:
                continue

            profile_url = _normalize_profile_url(str(username))
            key = profile_url.lower()
            if key in seen_authors:
                continue
            seen_authors.add(key)
            profile_urls.append(profile_url)
            candidates.append(
                PostAuthorCandidate(
                    username=str(username),
                    profile_url=profile_url,
                    source_hashtag=tag,
                    source_post_url=post_url,
                    source_caption=_caption_from_raw(mapped),
                    post_type=_post_type_from_raw(mapped),
                    source_discovery_type="post_author",
                )
            )
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    if not candidates and clean_tags and not errors:
        errors.append(f"Hashtag {clean_tags} 未解析到任何作者（可尝试换关键词）")

    return DiscoveryResult(
        profile_urls=profile_urls,
        post_urls=post_urls,
        errors=errors,
        candidates=candidates,
        post_count=raw_total,
        hashtag_count=len(clean_tags),
    )


async def discover_post_authors_from_post_urls(
    post_urls: list[str],
    *,
    limit: int = 100,
) -> DiscoveryResult:
    clean_urls: list[str] = []
    seen: set[str] = set()
    for raw in post_urls:
        url = (raw or "").strip()
        if not url or "instagram.com" not in url.lower():
            continue
        key = url.lower().split("?")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            clean_urls.append(url)

    if not clean_urls:
        return DiscoveryResult(errors=["未提供有效的 Instagram 帖子/Reel 链接"])

    candidates: list[PostAuthorCandidate] = []
    errors: list[str] = []
    seen_authors: set[str] = set()
    scraped = 0
    target_urls = clean_urls[:20]

    async def _fetch_post(url: str):
        shortcode = _shortcode_from_post_url(url)
        if not shortcode:
            return url, None, f"帖子 {url}: 无法解析 shortcode"
        try:
            payload = await ad_get(
                "/v1/instagram/posts",
                params={"query": shortcode, "pages": "1"},
                platform="instagram",
            )
            return url, payload, None
        except ApiDirectError as exc:
            return url, None, str(exc)

    post_outcomes = await map_bounded(
        target_urls,
        _fetch_post,
        concurrency=settings.collection_search_concurrency,
    )

    for outcome in post_outcomes:
        if isinstance(outcome, BaseException):
            errors.append(str(outcome))
            continue
        url, payload, err = outcome
        if err:
            errors.append(err if err.startswith("帖子") else f"帖子 {url}: {err}")
            continue

        posts = (payload or {}).get("posts") or []
        if not isinstance(posts, list):
            posts = []

        matched = None
        url_key = url.lower().split("?")[0].rstrip("/")
        shortcode = _shortcode_from_post_url(url) or ""
        for item in posts:
            if not isinstance(item, dict):
                continue
            item_url = (item.get("url") or "").lower().split("?")[0].rstrip("/")
            if shortcode.lower() in item_url or item_url == url_key:
                matched = item
                break
        if matched is None and posts:
            matched = posts[0]

        if not matched:
            errors.append(f"帖子 {url}: 未在搜索结果中找到作者")
            continue

        scraped += 1
        mapped = post_item_to_apify_raw(matched)
        post_url = mapped.get("url") or url
        username = mapped.get("username")
        if not username:
            errors.append(f"帖子 {post_url} 无法提取作者")
            continue

        profile_url = _normalize_profile_url(str(username))
        key = profile_url.lower()
        if key in seen_authors:
            continue
        seen_authors.add(key)
        candidates.append(
            PostAuthorCandidate(
                username=str(username) or extract_profile_username(profile_url) or "",
                profile_url=normalize_instagram_profile_url(profile_url) or profile_url,
                source_post_url=normalize_instagram_post_url(post_url) or post_url,
                source_caption=_caption_from_raw(mapped),
                post_type=_post_type_from_raw(mapped),
                source_discovery_type="post_author",
            )
        )
        if len(candidates) >= limit:
            break

    return DiscoveryResult(
        candidates=candidates,
        post_urls=clean_urls,
        errors=errors,
        post_count=scraped or len(clean_urls),
    )


async def recent_post_urls_for_profile(profile_url: str, *, limit: int = 5) -> tuple[list[str], list[str]]:
    """通过帖子搜索获取用户近期帖子链接（API Direct 无 timeline 字段）。"""
    from app.services.instagram_comment_discovery import _normalize_post_url

    username = _username_from_url(profile_url)
    errors: list[str] = []
    if not username:
        return [], [f"无效主页链接: {profile_url}"]

    try:
        payload = await ad_get(
            "/v1/instagram/posts",
            params={"query": username, "pages": "1"},
        )
    except ApiDirectError as exc:
        return [], [str(exc)]

    posts = payload.get("posts") or []
    urls: list[str] = []
    seen: set[str] = set()
    for raw in posts:
        if not isinstance(raw, dict):
            continue
        author = (raw.get("author") or "").lstrip("@").lower()
        if author and author != username.lower():
            continue
        post_url = raw.get("url")
        if not post_url:
            continue
        normalized = _normalize_post_url(post_url)
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append(normalized)
        if len(urls) >= limit:
            break

    if not urls:
        errors.append(f"主页 {profile_url} 未搜索到近期帖子/Reel 链接")
    return urls, errors


async def discover_comment_authors_from_post_urls(
    post_urls: list[str],
    *,
    limit: int = 100,
) -> DiscoveryResult:
    """API Direct 暂无 Instagram 评论列表接口，返回说明性错误。"""
    del limit
    clean = [u for u in post_urls if u and u.strip()]
    if not clean:
        return DiscoveryResult(errors=["未提供有效的帖子/Reel URL"])
    return DiscoveryResult(
        errors=[
            "评论发现: API Direct 暂不支持 Instagram 评论区用户抓取，已跳过。"
            "如需该功能可保留 APIFY_TOKEN 并将评论步骤切回 Apify，或仅使用帖子/Hashtag 作者发现。"
        ]
    )
