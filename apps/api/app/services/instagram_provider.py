"""Instagram 数据采集 Provider：api_direct（默认）/ apify / hikerapi / yepapi。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from app.core.config import settings
from app.core.exceptions import (
    APIFY_NOT_CONFIGURED_MSG,
    MOCK_COLLECTOR_DISABLED_MSG,
    API_DIRECT_NOT_CONFIGURED_MSG,
)
from app.services.apify_client import ApifyError

if TYPE_CHECKING:
    from app.collectors.base import CollectedInfluencer
    from app.services.apify_instagram import DiscoveryResult, PostAuthorCandidate, ProfileScrapeResult

logger = logging.getLogger(__name__)

PROVIDER_API_DIRECT = "api_direct"
PROVIDER_APIFY = "apify"
PROVIDER_HIKERAPI = "hikerapi"
PROVIDER_YEPAPI = "yepapi"


class InstagramProviderError(Exception):
    """第三方 Instagram 数据源未配置或不可用。"""


def active_provider_name() -> str:
    return settings.active_instagram_provider


def ensure_instagram_provider_ready() -> str:
    """校验当前 provider 配置；禁止 mock。返回 provider 名称。"""
    if settings.uses_mock_collector or settings.collector_mode.lower() == "mock":
        raise InstagramProviderError(MOCK_COLLECTOR_DISABLED_MSG)

    name = active_provider_name()
    if name == PROVIDER_API_DIRECT:
        if not settings.is_api_direct_configured:
            raise InstagramProviderError(API_DIRECT_NOT_CONFIGURED_MSG)
        return name

    if name == PROVIDER_APIFY:
        if not settings.is_apify_configured:
            raise InstagramProviderError(APIFY_NOT_CONFIGURED_MSG)
        if not settings.apify_instagram_hashtag_actor_id:
            raise InstagramProviderError("APIFY_INSTAGRAM_HASHTAG_ACTOR_ID 未配置")
        if not settings.apify_instagram_actor_id:
            raise InstagramProviderError("APIFY_INSTAGRAM_ACTOR_ID 未配置")
        return name

    if name == PROVIDER_HIKERAPI:
        if not settings.hikerapi_api_key.strip():
            raise InstagramProviderError(
                "HIKERAPI_API_KEY 未配置。请在 .env 设置密钥，或将 INSTAGRAM_DATA_PROVIDER 改为 api_direct"
            )
        return name

    if name == PROVIDER_YEPAPI:
        if not settings.yepapi_api_key.strip():
            raise InstagramProviderError(
                "YEPAPI_API_KEY 未配置。请在 .env 设置密钥，或将 INSTAGRAM_DATA_PROVIDER 改为 api_direct"
            )
        return name

    raise InstagramProviderError(
        f"未知 INSTAGRAM_DATA_PROVIDER={name}，支持: api_direct, apify, hikerapi, yepapi"
    )


def _hikerapi_headers() -> dict[str, str]:
    return {
        "x-access-key": settings.hikerapi_api_key.strip(),
        "accept": "application/json",
    }


async def _hikerapi_get(path: str, *, params: dict | None = None) -> dict | list:
    base = settings.hikerapi_base_url.rstrip("/")
    url = f"{base}{path}"
    timeout = settings.instagram_provider_timeout_seconds
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=_hikerapi_headers(), params=params or {})
    if response.status_code >= 400:
        detail = response.text[:500]
        raise InstagramProviderError(f"HikerAPI 请求失败 ({response.status_code}): {detail}")
    data = response.json()
    if isinstance(data, dict) and data.get("detail"):
        raise InstagramProviderError(f"HikerAPI: {data.get('detail')}")
    return data


async def _yepapi_get(path: str, *, params: dict | None = None) -> dict | list:
    base = settings.yepapi_base_url.rstrip("/")
    url = f"{base}{path}"
    timeout = settings.instagram_provider_timeout_seconds
    headers = {"Authorization": f"Bearer {settings.yepapi_api_key.strip()}", "accept": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers, params=params or {})
    if response.status_code >= 400:
        detail = response.text[:500]
        raise InstagramProviderError(f"YepAPI 请求失败 ({response.status_code}): {detail}")
    return response.json()


async def discover_post_authors_from_hashtags(
    hashtags: list[str],
    *,
    limit: int = 100,
) -> "DiscoveryResult":
    from app.services.apify_instagram import discover_post_authors_from_hashtags as apify_discover

    provider = ensure_instagram_provider_ready()
    if provider == PROVIDER_API_DIRECT:
        from app.services.api_direct_instagram import discover_post_authors_from_hashtags as ad_discover

        return await ad_discover(hashtags, limit=limit)
    if provider == PROVIDER_APIFY:
        return await apify_discover(hashtags, limit=limit)
    if provider == PROVIDER_HIKERAPI:
        return await _hikerapi_discover_hashtags(hashtags, limit=limit)
    return await _yepapi_discover_hashtags(hashtags, limit=limit)


async def discover_post_authors_from_post_urls(
    post_urls: list[str],
    *,
    limit: int = 100,
) -> "DiscoveryResult":
    from app.services.apify_instagram import discover_post_authors_from_post_urls as apify_discover

    provider = ensure_instagram_provider_ready()
    if provider == PROVIDER_API_DIRECT:
        from app.services.api_direct_instagram import discover_post_authors_from_post_urls as ad_discover

        return await ad_discover(post_urls, limit=limit)
    if provider == PROVIDER_APIFY:
        return await apify_discover(post_urls, limit=limit)
    if provider == PROVIDER_HIKERAPI:
        return await _hikerapi_discover_post_authors(post_urls, limit=limit)
    return await _yepapi_discover_post_authors(post_urls, limit=limit)


async def scrape_instagram_profiles(
    urls_or_usernames: list[str],
    *,
    candidate_meta: dict | None = None,
    on_item_complete=None,
    should_stop=None,
) -> "ProfileScrapeResult":
    from app.services.apify_instagram import scrape_instagram_profiles as apify_scrape

    provider = ensure_instagram_provider_ready()
    if provider == PROVIDER_API_DIRECT:
        from app.services.api_direct_instagram import scrape_instagram_profiles as ad_scrape

        return await ad_scrape(
            urls_or_usernames,
            candidate_meta=candidate_meta,
            on_item_complete=on_item_complete,
            should_stop=should_stop,
        )
    if provider == PROVIDER_APIFY:
        return await apify_scrape(
            urls_or_usernames,
            candidate_meta=candidate_meta,
            on_item_complete=on_item_complete,
            should_stop=should_stop,
        )
    if provider == PROVIDER_HIKERAPI:
        return await _hikerapi_scrape_profiles(urls_or_usernames, candidate_meta=candidate_meta)
    return await _yepapi_scrape_profiles(urls_or_usernames, candidate_meta=candidate_meta)


async def discover_comment_authors_from_post_urls(
    post_urls: list[str],
    *,
    limit: int = 100,
) -> "DiscoveryResult":
    from app.services.instagram_comment_discovery import discover_comment_authors_from_post_urls as apify_comments

    provider = ensure_instagram_provider_ready()
    if provider == PROVIDER_API_DIRECT:
        from app.services.api_direct_instagram import discover_comment_authors_from_post_urls as ad_comments

        return await ad_comments(post_urls, limit=limit)
    if provider == PROVIDER_APIFY:
        return await apify_comments(post_urls, limit=limit)
    if provider == PROVIDER_HIKERAPI:
        return await _hikerapi_discover_comments(post_urls, limit=limit)
    return await _yepapi_discover_comments(post_urls, limit=limit)


async def _hikerapi_discover_hashtags(hashtags: list[str], *, limit: int) -> "DiscoveryResult":
    from app.services.apify_instagram import (
        DiscoveryResult,
        PostAuthorCandidate,
        _caption_from_raw,
        _normalize_profile_url,
        _post_url_from_raw,
        _username_from_url,
    )

    candidates: list[PostAuthorCandidate] = []
    post_urls: list[str] = []
    errors: list[str] = []
    seen_authors: set[str] = set()
    seen_posts: set[str] = set()
    raw_total = 0

    per_tag = max(10, limit // max(len(hashtags), 1))
    for tag in hashtags:
        clean = tag.strip().lstrip("#")
        if not clean:
            continue
        try:
            payload = await _hikerapi_get(
                "/v1/hashtag/medias",
                params={"name": clean, "count": per_tag},
            )
        except InstagramProviderError as exc:
            errors.append(str(exc))
            continue

        items = payload if isinstance(payload, list) else payload.get("items") or payload.get("medias") or []
        if isinstance(items, dict):
            items = items.get("items") or []
        raw_total += len(items)

        for raw in items:
            if not isinstance(raw, dict):
                continue
            post_url = _post_url_from_raw(raw)
            if post_url:
                pk = post_url.lower()
                if pk not in seen_posts:
                    seen_posts.add(pk)
                    post_urls.append(post_url)
            owner = raw.get("user") or raw.get("owner") or {}
            username = raw.get("username") or (owner.get("username") if isinstance(owner, dict) else None)
            if not username and post_url:
                username = _username_from_url(post_url)
            if not username:
                continue
            profile_url = _normalize_profile_url(str(username))
            key = profile_url.lower()
            if key in seen_authors:
                continue
            seen_authors.add(key)
            candidates.append(
                PostAuthorCandidate(
                    username=str(username),
                    profile_url=profile_url,
                    source_hashtag=clean,
                    source_post_url=post_url,
                    source_caption=_caption_from_raw(raw),
                    source_discovery_type="post_author",
                )
            )
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    return DiscoveryResult(
        candidates=candidates,
        post_urls=post_urls,
        errors=errors,
        post_count=raw_total,
    )


async def _hikerapi_discover_post_authors(post_urls: list[str], *, limit: int) -> "DiscoveryResult":
    from app.services.apify_instagram import (
        DiscoveryResult,
        PostAuthorCandidate,
        _caption_from_raw,
        _normalize_profile_url,
        _post_url_from_raw,
        _username_from_url,
    )

    candidates: list[PostAuthorCandidate] = []
    errors: list[str] = []
    seen_authors: set[str] = set()
    scraped = 0

    for url in post_urls:
        text = (url or "").strip()
        if not text:
            continue
        try:
            payload = await _hikerapi_get("/v1/media/by/url", params={"url": text})
        except InstagramProviderError as exc:
            errors.append(f"帖子 {text}: {exc}")
            continue
        scraped += 1
        raw = payload.get("media") if isinstance(payload, dict) else payload
        if not isinstance(raw, dict):
            raw = payload if isinstance(payload, dict) else {}
        post_url = _post_url_from_raw(raw) or text
        owner = raw.get("user") or raw.get("owner") or {}
        username = raw.get("username") or (owner.get("username") if isinstance(owner, dict) else None)
        if not username:
            errors.append(f"帖子 {post_url} 无法提取作者用户名")
            continue
        profile_url = _normalize_profile_url(str(username))
        key = profile_url.lower()
        if key in seen_authors:
            continue
        seen_authors.add(key)
        candidates.append(
            PostAuthorCandidate(
                username=str(username),
                profile_url=profile_url,
                source_post_url=post_url,
                source_caption=_caption_from_raw(raw),
                source_discovery_type="post_author",
            )
        )
        if len(candidates) >= limit:
            break

    return DiscoveryResult(candidates=candidates, errors=errors, post_count=scraped or len(post_urls))


async def _hikerapi_scrape_profiles(
    urls_or_usernames: list[str],
    *,
    candidate_meta: dict | None = None,
) -> "ProfileScrapeResult":
    from app.models.enums import ProfileFailureReason
    from app.services.apify_instagram import (
        FailedProfile,
        ProfileScrapeResult,
        _normalize_profile_url,
        _source_fields_from_meta,
        _username_from_url,
        classify_profile_failure,
        map_apify_instagram_profile,
    )

    results: list[CollectedInfluencer] = []
    errors: list[str] = []
    failed_profiles: list[FailedProfile] = []
    failed_keys: set[str] = set()

    for item in urls_or_usernames:
        text = item.strip()
        if not text:
            continue
        username = _username_from_url(text) if "instagram.com" in text else text.lstrip("@")
        if not username:
            errors.append(f"无效用户名: {text}")
            continue
        key = username.lower()
        meta = candidate_meta.get(key) if candidate_meta else None
        profile_url = text if text.startswith("http") else _normalize_profile_url(username)
        try:
            payload = await _hikerapi_get("/v1/user/by/username", params={"username": username})
        except InstagramProviderError as exc:
            detail = str(exc)
            errors.append(detail)
            if key not in failed_keys:
                failed_keys.add(key)
                failed_profiles.append(
                    FailedProfile(
                        username=username,
                        profile_url=profile_url,
                        reason=classify_profile_failure(detail),
                        detail=detail,
                        **_source_fields_from_meta(meta),
                    )
                )
            continue
        user = payload.get("user") if isinstance(payload, dict) else payload
        if not isinstance(user, dict):
            user = payload if isinstance(payload, dict) else {}
        if not user:
            detail = f"未获取到主页数据: @{username}"
            errors.append(detail)
            if key not in failed_keys:
                failed_keys.add(key)
                failed_profiles.append(
                    FailedProfile(
                        username=username,
                        profile_url=profile_url,
                        reason=ProfileFailureReason.MISSING_PROFILE_DETAIL,
                        detail=detail,
                        **_source_fields_from_meta(meta),
                    )
                )
            continue
        raw = {
            "username": user.get("username") or username,
            "name": user.get("full_name") or user.get("name"),
            "biography": user.get("biography") or user.get("bio"),
            "followers": user.get("follower_count") or user.get("followers"),
            "businessEmail": user.get("public_email") or user.get("business_email"),
            "profilePicUrl": user.get("profile_pic_url") or user.get("profile_pic_url_hd"),
            "homepage": user.get("external_url") or user.get("website"),
            "isPrivate": user.get("is_private"),
        }
        if raw.get("isPrivate"):
            detail = f"@{username} 为私密账号"
            errors.append(detail)
            if key not in failed_keys:
                failed_keys.add(key)
                failed_profiles.append(
                    FailedProfile(
                        username=username,
                        profile_url=profile_url,
                        reason=ProfileFailureReason.PRIVATE_ACCOUNT,
                        detail=detail,
                        **_source_fields_from_meta(meta),
                    )
                )
            continue
        try:
            results.append(map_apify_instagram_profile(raw, fallback_url=profile_url))
        except ValueError as exc:
            detail = f"@{username} 映射失败: {exc}"
            errors.append(detail)
            if key not in failed_keys:
                failed_keys.add(key)
                failed_profiles.append(
                    FailedProfile(
                        username=username,
                        profile_url=profile_url,
                        reason=ProfileFailureReason.MISSING_PROFILE_DETAIL,
                        detail=detail,
                        **_source_fields_from_meta(meta),
                    )
                )

    return ProfileScrapeResult(profiles=results, errors=errors, failed_profiles=failed_profiles)


async def _hikerapi_discover_comments(post_urls: list[str], *, limit: int) -> "DiscoveryResult":
    from app.services.instagram_comment_discovery import discover_comment_authors_from_post_urls as apify_comments

    if not settings.is_apify_configured or not settings.apify_instagram_comment_actor_id:
        raise InstagramProviderError(
            "HikerAPI 模式下评论发现需额外配置 APIFY_TOKEN 与 APIFY_INSTAGRAM_COMMENT_ACTOR_ID，"
            "或将 INSTAGRAM_DATA_PROVIDER 设为 apify"
        )
    return await apify_comments(post_urls, limit=limit)


async def _yepapi_discover_post_authors(post_urls: list[str], *, limit: int) -> "DiscoveryResult":
    raise InstagramProviderError("YepAPI 帖子作者发现尚未接入，请使用 INSTAGRAM_DATA_PROVIDER=apify")


async def _yepapi_discover_hashtags(hashtags: list[str], *, limit: int) -> "DiscoveryResult":
    raise InstagramProviderError("YepAPI hashtag 发现尚未接入，请使用 INSTAGRAM_DATA_PROVIDER=apify")


async def _yepapi_scrape_profiles(urls_or_usernames: list[str], *, candidate_meta: dict | None = None) -> "ProfileScrapeResult":
    raise InstagramProviderError("YepAPI 主页补采尚未接入，请使用 INSTAGRAM_DATA_PROVIDER=apify")


async def _yepapi_discover_comments(post_urls: list[str], *, limit: int) -> "DiscoveryResult":
    raise InstagramProviderError("YepAPI 评论发现尚未接入，请使用 INSTAGRAM_DATA_PROVIDER=apify")
