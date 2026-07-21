# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：shopping seed discovery provider
"""通过导购平台关键词搜索与 bio/外链解析发现真实导购 seed profile URL。

Seed 发现只围绕 LTK / ShopMy / Pinterest 三个导购平台。
Instagram / TikTok / YouTube / Facebook 不再参与 seed 搜索阶段，
它们只在 seed 已发现后的 link_seed_enrichment 阶段用于补全社媒主页详情。
"""

from __future__ import annotations

import logging
import re
import base64
import asyncio
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx

from app.core.config import settings
from app.collectors.base import CollectedInfluencer
from app.services.apify_client import ApifyError, is_apify_network_unreachable, run_actor_sync
from app.services.platform_utils import profile_to_collected
from app.services.platform_providers.url_only import (
    PINTEREST_RESERVED,
    SHOPMY_RESERVED,
    _parse_ltk,
    _parse_pinterest,
    _parse_shopmy,
)

logger = logging.getLogger(__name__)

# Seed discovery 不再使用社交平台搜索。保留常量供搜索计划生成 query，
# 但实际 discover 调用不会发往这些平台。
_SEARCH_PLATFORMS_LEGACY = ("instagram", "tiktok", "youtube", "facebook")
# 实际用于 seed 搜索的平台集合——当前为空，表示不执行社交平台搜索
SEED_SOCIAL_SEARCH_PLATFORMS: tuple[str, ...] = ()
DEFAULT_MAX_SEED_SEARCH_QUERIES = 12
PUBLIC_WEB_SEARCH_PLATFORM = "public_web"
PINTEREST_APIFY_SEARCH_PLATFORM = "pinterest_apify"
PROVIDER_UNAVAILABLE_STATUS = "provider_unavailable"
NETWORK_UNREACHABLE_REASON = "network_unreachable"
QUERY_TIMEOUT_REASON = "query_timeout"
APIFY_MEMORY_LIMIT_REASON = "apify_memory_limit_exceeded"
_SUPPORTED_SOCIAL_SEED_SEARCH_PLATFORMS = {"instagram", "youtube", "tiktok", "facebook"}

_SEED_URL_PATTERNS: dict[str, re.Pattern[str]] = {
    "ltk": re.compile(
        r"https?://(?:www\.)?shopltk\.com/explore/([A-Za-z0-9_.-]{2,80})",
        re.I,
    ),
    "shopmy": re.compile(
        r"https?://(?:www\.)?shopmy\.us/(?:shop/)?([A-Za-z0-9_.-]{2,80})",
        re.I,
    ),
    "pinterest": re.compile(
        r"https?://(?:www\.)?pinterest\.com/([A-Za-z0-9_.-]{2,80})/?",
        re.I,
    ),
}

_SEED_PARSERS = {
    "ltk": _parse_ltk,
    "shopmy": _parse_shopmy,
    "pinterest": _parse_pinterest,
}
LTK_RESERVED = {"ltk", "shopltk", "liketoknowit", "search", "explore"}

_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
_LTK_DISPLAY_NAME_RE = re.compile(r"""displayName\s*:\s*["']([A-Za-z0-9_.-]{2,80})["']""")


def configured_seed_search_platforms() -> list[str]:
    providers = [
        part.strip().lower()
        for part in (settings.shopping_seed_search_provider or "").split(",")
        if part.strip()
    ]
    if "none" in providers or "disabled" in providers:
        return []
    platforms: list[str] = []
    if PUBLIC_WEB_SEARCH_PLATFORM in providers:
        platforms.append(PUBLIC_WEB_SEARCH_PLATFORM)
    if (
        PINTEREST_APIFY_SEARCH_PLATFORM in providers
        and settings.is_apify_configured
        and settings.apify_pinterest_search_actor_id.strip()
    ):
        platforms.append(PINTEREST_APIFY_SEARCH_PLATFORM)
    return platforms


def configured_public_search_engines() -> set[str]:
    engines = {
        part.strip().lower()
        for part in (settings.shopping_seed_public_search_engines or "").split(",")
        if part.strip()
    }
    if not engines:
        return {"duckduckgo", "bing", "ltk", "shopmy"}
    if "all" in engines:
        return {"duckduckgo", "bing", "ltk", "shopmy"}
    return engines & {"duckduckgo", "bing", "ltk", "shopmy", "pinterest"}


def configured_social_seed_search_platforms() -> list[str]:
    configured = getattr(settings, "shopping_seed_social_search_platforms", "")
    platforms = [
        part.strip().lower()
        for part in (configured or "").split(",")
        if part.strip()
    ]
    if not platforms:
        platforms = list(SEED_SOCIAL_SEARCH_PLATFORMS)
    if "none" in platforms or "disabled" in platforms:
        return []
    return [
        platform
        for platform in dict.fromkeys(platforms)
        if platform in _SUPPORTED_SOCIAL_SEED_SEARCH_PLATFORMS
    ]


def should_use_ltk_site_search(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[A-Z0-9]{10}", text, re.I):
        return False
    lowered = text.lower()
    if "shopmy" in lowered or "pinterest" in lowered:
        return False
    return True


def build_social_search_queries(keyword: str, seed_platforms: list[str]) -> list[str]:
    text = (keyword or "").strip()
    if not text:
        return []
    queries: list[str] = []
    for plat in seed_platforms:
        if plat == "ltk":
            queries.extend([f"{text} shopltk", f"{text} LTK influencer"])
        elif plat == "shopmy":
            queries.extend([f"{text} shopmy", f"{text} shopmy.us"])
        elif plat == "pinterest":
            queries.extend([f"{text} pinterest creator", f"{text} pinterest.com"])
    return list(dict.fromkeys(queries))


def _seed_query_score(query: str) -> tuple[int, int]:
    text = (query or "").lower()
    score = 0
    if re.fullmatch(r"[a-z0-9]{10}", text.strip()):
        score += 220
    elif re.search(r"\b[a-z0-9]{10}\b", text):
        score += 100
    if "shopltk" in text or " ltk" in text:
        score += 80
    if "shopmy" in text:
        score += 80
    if "pinterest" in text:
        score += 70
    if "amazon finds" in text:
        score += 60
    if "influencer" in text or "blogger" in text:
        score += 40
    return (-score, len(text))


def build_seed_search_plan(
    *,
    keywords: list[str],
    seed_platforms: list[str],
    max_queries: int = DEFAULT_MAX_SEED_SEARCH_QUERIES,
) -> list[dict[str, str]]:
    """Build a capped, high-signal provider search plan.

    Older code expanded every product phrase by every seed platform and every
    social platform, which could turn one Amazon product into hundreds of API
    searches. Keep the most likely seed-bearing queries first.
    """
    allowed = [p.strip().lower() for p in seed_platforms if p and p.strip()]
    raw_queries: list[str] = []
    source_by_query: dict[str, str] = {}
    must_keep: list[str] = []
    for index, keyword in enumerate(keywords or []):
        text = (keyword or "").strip()
        if not text:
            continue
        raw_queries.append(text)
        source_by_query.setdefault(text, text)
        lowered = text.lower()
        if (
            re.fullmatch(r"[a-z0-9]{10}", lowered)
            or " ltk" in lowered
            or "shopmy" in lowered
            or "pinterest" in lowered
            or "amazon finds" in lowered
        ):
            must_keep.append(text)
        if index < 6:
            for expanded in build_social_search_queries(text, allowed):
                raw_queries.append(expanded)
                source_by_query.setdefault(expanded, text)

    deduped = list(dict.fromkeys(q for q in raw_queries if q.strip()))
    cap = max(1, max_queries or DEFAULT_MAX_SEED_SEARCH_QUERIES)
    required_by_platform: list[str] = []
    platform_markers = {
        "ltk": ("ltk", "shopltk"),
        "shopmy": ("shopmy",),
        "pinterest": ("pinterest",),
    }
    for platform in allowed:
        markers = platform_markers.get(platform, ())
        match = next(
            (
                query
                for query in deduped
                if any(marker in query.lower() for marker in markers)
            ),
            None,
        )
        if match:
            required_by_platform.append(match)
    required_fallbacks: list[str] = []
    fallback_patterns = (
        "site:shopltk.com/explore",
        "site:shopmy.us",
        '"shopltk"',
        '"shopmy"',
    )
    for pattern in fallback_patterns:
        match = next((query for query in deduped if pattern in query.lower()), None)
        if match:
            required_fallbacks.append(match)
    pinned = list(dict.fromkeys(required_by_platform + required_fallbacks + must_keep))[:cap]
    pinned_keys = {q.lower() for q in pinned}
    ranked = [q for q in sorted(deduped, key=_seed_query_score) if q.lower() not in pinned_keys]
    capped = (pinned + ranked)[:cap]
    plan: list[dict[str, str]] = []
    for query in capped:
        plan.append({"query": query, "source_keyword": source_by_query.get(query, query)})
    return plan


def should_use_pinterest_apify_for_query(query: str) -> bool:
    text = (query or "").strip().lower()
    if not text:
        return False
    if "pinterest" in text:
        return True
    if any(marker in text for marker in ("ltk", "shopltk", "shopmy", "shopmy.us")):
        return False
    return True


def _is_apify_memory_limit_error(exc: Exception) -> bool:
    detail = str(exc).strip().lower()
    return (
        "actor-memory-limit-exceeded" in detail
        or "memory limit exceeded" in detail
        or "memory_limit_exceeded" in detail
    )


def build_seed_search_diagnostics(
    *,
    keywords: list[str],
    seed_platforms: list[str],
    category: str | None = None,
    profiles_returned_count: int = 0,
    seed_extracted_count: int = 0,
) -> dict:
    allowed = sorted(
        {
            p.strip().lower()
            for p in seed_platforms
            if p and p.strip() and p.strip().lower() in _SEED_PARSERS
        }
    )
    keyword_pool: list[str] = []
    for keyword in keywords or []:
        text = (keyword or "").strip()
        if text:
            keyword_pool.append(text)
    if category and str(category).strip():
        keyword_pool.append(str(category).strip())
    plan = build_seed_search_plan(
        keywords=keyword_pool,
        seed_platforms=allowed,
        max_queries=getattr(settings, "shopping_seed_search_max_queries", DEFAULT_MAX_SEED_SEARCH_QUERIES),
    )
    configured_platforms = configured_seed_search_platforms()
    search_platforms: list[str] = []
    if PUBLIC_WEB_SEARCH_PLATFORM in configured_platforms:
        search_platforms.append(PUBLIC_WEB_SEARCH_PLATFORM)
    if "pinterest" in allowed and PINTEREST_APIFY_SEARCH_PLATFORM in configured_platforms:
        search_platforms.append(PINTEREST_APIFY_SEARCH_PLATFORM)
    social_search_platforms = configured_social_seed_search_platforms()
    search_platforms.extend(social_search_platforms)
    provider_call_count = 0
    public_web_query_count = 0
    for item in plan:
        query = item["query"]
        if PUBLIC_WEB_SEARCH_PLATFORM in search_platforms:
            provider_call_count += 1
            public_web_query_count += 1
        if PINTEREST_APIFY_SEARCH_PLATFORM in search_platforms and should_use_pinterest_apify_for_query(query):
            provider_call_count += 1
        provider_call_count += len(social_search_platforms)
    disabled = provider_call_count == 0
    zero_reason = None
    if disabled:
        zero_reason = "seed_search_provider_not_configured"
    elif allowed == ["shopmy"] and profiles_returned_count == 0:
        zero_reason = "shopmy_keyword_search_requires_authenticated_provider"
    elif profiles_returned_count == 0:
        zero_reason = "seed_search_no_profiles_returned"
    elif seed_extracted_count == 0:
        zero_reason = "seed_search_no_seed_urls_extracted"
    platform_provider_notes: dict[str, str] = {}
    if "shopmy" in allowed:
        platform_provider_notes["shopmy"] = (
            "ShopMy keyword discovery has no authenticated provider configured; "
            "public web search may not return creator profiles."
        )
    return {
        "seed_platforms": allowed,
        "search_platforms": search_platforms,
        "queries": [item["query"] for item in plan],
        "query_count": len(plan),
        "provider_call_count": provider_call_count,
        "public_web_query_count": public_web_query_count,
        "profiles_returned_count": profiles_returned_count,
        "seed_extracted_count": seed_extracted_count,
        "seed_search_disabled": disabled,
        "zero_seed_reason": zero_reason,
        "platform_provider_notes": platform_provider_notes,
    }


def _is_valid_seed_handle(platform: str, handle: str) -> bool:
    lowered = handle.lower()
    if platform == "ltk" and lowered in LTK_RESERVED:
        return False
    if platform == "pinterest" and lowered in PINTEREST_RESERVED:
        return False
    if platform == "shopmy" and lowered in SHOPMY_RESERVED:
        return False
    if platform == "pinterest" and lowered == "pin":
        return False
    return bool(re.match(r"^[A-Za-z0-9_.-]{2,80}$", handle))


def _seed_url_from_match(platform: str, handle: str) -> str | None:
    if not _is_valid_seed_handle(platform, handle):
        return None
    if platform == "ltk":
        return f"https://www.shopltk.com/explore/{handle}"
    if platform == "shopmy":
        return f"https://shopmy.us/{handle}"
    if platform == "pinterest":
        return f"https://www.pinterest.com/{handle}/"
    return None


def extract_seed_urls_from_text(text: str, allowed_platforms: set[str]) -> list[tuple[str, str]]:
    if not text or not allowed_platforms:
        return []
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_url in _URL_IN_TEXT_RE.findall(text):
        cleaned = raw_url.rstrip(".,);]")
        for platform in allowed_platforms:
            pattern = _SEED_URL_PATTERNS.get(platform)
            if pattern is None:
                continue
            match = pattern.search(cleaned)
            if not match:
                continue
            handle = match.group(1)
            url = _seed_url_from_match(platform, handle)
            if not url:
                continue
            key = (platform, url.lower().rstrip("/"))
            if key in seen:
                continue
            seen.add(key)
            found.append((platform, url))
    return found


def _iter_text_values(value: Any) -> list[str]:
    texts: list[str] = []
    if value is None:
        return texts
    if isinstance(value, str):
        if value.strip():
            texts.append(value)
        return texts
    if isinstance(value, dict):
        for child in value.values():
            texts.extend(_iter_text_values(child))
        return texts
    if isinstance(value, (list, tuple, set)):
        for child in value:
            texts.extend(_iter_text_values(child))
        return texts
    return texts


def _source_label(item: CollectedInfluencer, field: str) -> str:
    platform = (item.platform or "provider").strip().lower()
    if field == "bio":
        return f"{platform}_bio"
    if field in {"caption", "source_comment_text", "recent_post_titles"}:
        return f"{platform}_caption"
    if field in {"youtube_about", "about_links"}:
        return "youtube_about"
    if field in {"video_description", "description"}:
        return "youtube_video_description" if platform == "youtube" else f"{platform}_caption"
    if field in {"external_links", "other_social_links", "website", "linktree_url", "contact_page"}:
        return f"{platform}_external_links"
    if field in {"recent_post_urls", "source_post_url"}:
        return "search_result"
    return "provider_source_meta"


def extract_seed_refs_from_collected(
    item: CollectedInfluencer,
    allowed_platforms: set[str],
    *,
    discovery_query: str | None = None,
) -> list[dict[str, str]]:
    source_profile_url = item.profile_url
    source_post_url = item.source_post_url
    source_input_url = getattr(item, "source_input_url", None)
    source_meta = getattr(item, "source_meta", None)
    if isinstance(source_meta, dict):
        source_post_url = source_post_url or source_meta.get("source_post_url")
        source_input_url = source_input_url or source_meta.get("source_input_url") or source_meta.get("input_url")

    text_sources: list[tuple[str, str]] = []
    direct_fields = {
        "bio": item.bio,
        "website": item.website,
        "linktree_url": getattr(item, "linktree_url", None),
        "contact_page": getattr(item, "contact_page", None),
        "source_post_url": source_post_url,
        "source_comment_text": getattr(item, "source_comment_text", None),
    }
    for name, value in direct_fields.items():
        for text in _iter_text_values(value):
            text_sources.append((name, text))
    for link in item.other_social_links or []:
        for text in _iter_text_values(link):
            text_sources.append(("other_social_links", text))
    for text in _iter_text_values(item.recent_post_urls or []):
        text_sources.append(("recent_post_urls", text))
    for text in _iter_text_values(item.recent_post_titles or []):
        text_sources.append(("recent_post_titles", text))
    if isinstance(source_meta, dict):
        for key, value in source_meta.items():
            for text in _iter_text_values(value):
                text_sources.append((str(key), text))

    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for field, text in text_sources:
        for platform, url in extract_seed_urls_from_text(text, allowed_platforms):
            key = (platform, url.lower().rstrip("/"))
            if key in seen:
                continue
            seen.add(key)
            parsed = _parse_seed_profile(platform, url)
            username = parsed.username if parsed else ""
            refs.append(
                {
                    "link_seed_platform": platform,
                    "link_seed_profile_url": url,
                    "link_seed_username": username,
                    "discovery_source": _source_label(item, field),
                    "discovery_query": discovery_query or "",
                    "source_platform": item.platform or "",
                    "provider": item.platform or "",
                    "source_profile_url": source_profile_url or "",
                    "source_post_url": source_post_url or "",
                    "source_input_url": source_input_url or source_profile_url or "",
                    "raw_url": url,
                    "normalized_seed_url": url,
                    "extraction_reason": f"{_source_label(item, field)}_seed_link",
                }
            )
    return refs


def extract_seed_urls_from_collected(
    item: CollectedInfluencer,
    allowed_platforms: set[str],
) -> list[tuple[str, str]]:
    return [
        (ref["link_seed_platform"], ref["link_seed_profile_url"])
        for ref in extract_seed_refs_from_collected(item, allowed_platforms)
    ]


def _parse_seed_profile(platform: str, url: str):
    parser = _SEED_PARSERS.get(platform)
    if parser is None:
        return None
    return parser(url)


def _seed_site_filter(allowed_platforms: set[str]) -> str:
    sites: list[str] = []
    if "ltk" in allowed_platforms:
        sites.append("site:shopltk.com/explore")
    if "shopmy" in allowed_platforms:
        sites.append("site:shopmy.us")
    if "pinterest" in allowed_platforms:
        sites.append("site:pinterest.com")
    return " OR ".join(sites)


def _unwrap_search_url(raw_url: str, *, base_url: str = "https://duckduckgo.com") -> str | None:
    if not raw_url:
        return None
    url = raw_url.strip()
    if url.startswith("//"):
        url = f"https:{url}"
    if url.startswith("/"):
        url = urljoin(base_url, url)
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            return unquote(target)
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/"):
        encoded = parse_qs(parsed.query).get("u", [None])[0]
        if encoded:
            for candidate in (encoded, encoded[1:] if encoded.startswith("a") else ""):
                if not candidate:
                    continue
                try:
                    padded = candidate + "=" * (-len(candidate) % 4)
                    decoded = base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="ignore")
                except Exception:
                    continue
                if decoded.startswith("http"):
                    return decoded
    if parsed.netloc:
        return url
    return None


def _extract_candidate_search_urls(html: str, *, base_url: str = "https://duckduckgo.com") -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for href in _HREF_RE.findall(html or ""):
        url = _unwrap_search_url(href, base_url=base_url)
        if not url:
            continue
        key = url.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(url)
    for raw_url in _URL_IN_TEXT_RE.findall(html or ""):
        url = _unwrap_search_url(raw_url.rstrip(".,);]"), base_url=base_url)
        if not url:
            continue
        key = url.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(url)
    return candidates


def _direct_site_search_query(platform: str, query: str) -> str:
    text = (query or "").strip()
    if platform == "shopmy":
        text = re.sub(r"\bshopmy(?:\.us)?\b", " ", text, flags=re.I)
    elif platform == "pinterest":
        text = re.sub(r"\bpinterest(?:\.com)?\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip() or (query or "").strip()


def _extract_ltk_search_refs(html: str, query: str, limit: int) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _LTK_DISPLAY_NAME_RE.finditer(html or ""):
        username = match.group(1).strip()
        url = _seed_url_from_match("ltk", username)
        if not url:
            continue
        key = username.lower()
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "link_seed_platform": "ltk",
                "link_seed_profile_url": url,
                "link_seed_username": username,
                "discovery_source": "ltk_search_result",
                "discovery_query": query,
                "source_platform": PUBLIC_WEB_SEARCH_PLATFORM,
                "provider": PUBLIC_WEB_SEARCH_PLATFORM,
                "source_profile_url": "",
                "source_post_url": "",
                "source_input_url": url,
                "search_result_url": f"https://www.shopltk.com/search?keyword={quote_plus(query)}",
                "raw_url": url,
                "normalized_seed_url": url,
                "extraction_reason": "ltk_site_search_display_name",
            }
        )
        if len(refs) >= limit:
            return refs
    return refs


def _first_text_value(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _pinterest_ref_from_apify_item(item: dict, query: str) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    pinner = item.get("pinner") if isinstance(item.get("pinner"), dict) else {}
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    profile_url = _first_text_value(
        item,
        (
            "profileUrl",
            "profileURL",
            "userUrl",
            "userURL",
            "pinnerUrl",
            "pinnerURL",
            "ownerUrl",
            "creatorUrl",
            "authorUrl",
        ),
    )
    if not profile_url and pinner:
        profile_url = _first_text_value(
            pinner,
            (
                "profileUrl",
                "profileURL",
                "userUrl",
                "url",
            ),
        )
    if not profile_url and owner:
        profile_url = _first_text_value(
            owner,
            (
                "profileUrl",
                "profileURL",
                "userUrl",
                "url",
            ),
        )
    username = _first_text_value(
        item,
        (
            "username",
            "userName",
            "pinnerUsername",
            "pinnerName",
            "ownerUsername",
            "creatorUsername",
            "authorUsername",
        ),
    ).lstrip("@")
    if not username and pinner:
        username = _first_text_value(
            pinner,
            (
                "username",
                "userName",
                "name",
            ),
        ).lstrip("@")
    if not username and owner:
        username = _first_text_value(
            owner,
            (
                "username",
                "userName",
                "name",
            ),
        ).lstrip("@")
    if not profile_url and username:
        profile_url = _seed_url_from_match("pinterest", username) or ""
    if profile_url:
        found = extract_seed_urls_from_text(profile_url, {"pinterest"})
        if found:
            profile_url = found[0][1]
            username = username or profile_url.rstrip("/").split("/")[-1]
    if not profile_url:
        for text in _iter_text_values(item):
            for platform, url in extract_seed_urls_from_text(text, {"pinterest"}):
                if platform != "pinterest":
                    continue
                profile_url = url
                username = username or url.rstrip("/").split("/")[-1]
                break
            if profile_url:
                break
    if not profile_url or not username:
        return None
    profile_url = _seed_url_from_match("pinterest", username) or profile_url
    if not profile_url:
        return None
    source_post_url = _first_text_value(
        item,
        ("pinUrl", "pinURL", "slashURL", "url", "link", "sourceUrl", "sourceURL"),
    )
    return {
        "link_seed_platform": "pinterest",
        "link_seed_profile_url": profile_url,
        "link_seed_username": username,
        "discovery_source": "pinterest_apify_search_result",
        "discovery_query": query,
        "source_platform": PINTEREST_APIFY_SEARCH_PLATFORM,
        "provider": PINTEREST_APIFY_SEARCH_PLATFORM,
        "source_profile_url": profile_url,
        "source_post_url": source_post_url,
        "source_input_url": profile_url,
        "search_result_url": source_post_url or profile_url,
        "raw_url": source_post_url or profile_url,
        "normalized_seed_url": profile_url,
        "extraction_reason": "pinterest_apify_profile_owner",
    }


async def search_pinterest_apify_for_seed_refs(
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, str]]:
    text = (query or "").strip()
    if not text or not settings.is_apify_configured or not settings.apify_pinterest_search_actor_id.strip():
        return []
    requested_limit = max(1, min(limit or settings.shopping_seed_search_max_results, settings.shopping_seed_search_max_results))
    actor_limit = max(20, requested_limit)
    run_input = {
        "query": text,
        "filter": "all",
        "limit": actor_limit,
    }
    try:
        rows = await run_actor_sync(
            settings.apify_pinterest_search_actor_id,
            run_input,
            timeout=settings.apify_pinterest_search_timeout_seconds,
            max_retries=settings.apify_pinterest_search_max_retries,
            memory_mbytes=settings.apify_pinterest_search_memory_mbytes,
        )
    except ApifyError as exc:
        logger.warning("Pinterest Apify seed search failed query=%s error=%s", query, exc)
        raise

    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        ref = _pinterest_ref_from_apify_item(row, text)
        if not ref:
            continue
        key = ref["link_seed_profile_url"].lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
        if len(refs) >= requested_limit:
            return refs
    return refs


async def search_public_web_for_seed_refs(
    query: str,
    allowed_platforms: set[str],
    *,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Search public web results for real LTK / ShopMy / Pinterest profile URLs."""
    text = (query or "").strip()
    if not text or not allowed_platforms:
        return []
    site_filter = _seed_site_filter(allowed_platforms)
    if site_filter:
        text = f"{text} ({site_filter})"
    engines = configured_public_search_engines()
    search_urls: list[tuple[str, str]] = []
    if "duckduckgo" in engines:
        search_urls.append((f"https://duckduckgo.com/html/?q={quote_plus(text)}", "https://duckduckgo.com"))
    if "bing" in engines:
        search_urls.append((f"https://www.bing.com/search?q={quote_plus(text)}", "https://www.bing.com"))
    if "ltk" in engines and "ltk" in allowed_platforms and should_use_ltk_site_search(query):
        search_urls.append((f"https://www.shopltk.com/search?keyword={quote_plus(query)}", "https://www.shopltk.com"))
    if "shopmy" in engines and "shopmy" in allowed_platforms:
        shopmy_query = _direct_site_search_query("shopmy", query)
        encoded_query = quote_plus(shopmy_query)
        search_urls.append((f"https://shopmy.us/search?q={encoded_query}", "https://shopmy.us"))
        search_urls.append((f"https://shopmy.us/search?query={encoded_query}", "https://shopmy.us"))
    timeout = max(3, settings.shopping_seed_search_timeout_seconds)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; InfluencerIntel/1.0; +https://example.com/bot)",
        "Accept": "text/html,application/xhtml+xml",
    }
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    max_results = max(1, min(limit or settings.shopping_seed_search_max_results, settings.shopping_seed_search_max_results))
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for search_url, search_base_url in search_urls:
            try:
                response = await client.get(search_url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("Shopping seed public web search failed query=%s url=%s error=%s", query, search_url, exc)
                continue

            if "shopltk.com/search" in search_url:
                for ref in _extract_ltk_search_refs(response.text, query, max_results - len(refs)):
                    username = ref["link_seed_username"]
                    key = ("ltk", username.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    refs.append(ref)
                    if len(refs) >= max_results:
                        return refs

            for candidate_url in _extract_candidate_search_urls(response.text, base_url=search_base_url):
                for platform, seed_url in extract_seed_urls_from_text(candidate_url, allowed_platforms):
                    parsed = _parse_seed_profile(platform, seed_url)
                    if parsed is None:
                        continue
                    username = (parsed.username or "").strip()
                    if not username:
                        continue
                    key = (platform, username.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    refs.append(
                        {
                            "link_seed_platform": platform,
                            "link_seed_profile_url": seed_url,
                            "link_seed_username": username,
                            "discovery_source": "search_result",
                            "discovery_query": query,
                            "source_platform": PUBLIC_WEB_SEARCH_PLATFORM,
                            "provider": PUBLIC_WEB_SEARCH_PLATFORM,
                            "source_profile_url": "",
                            "source_post_url": "",
                            "source_input_url": seed_url,
                            "search_result_url": candidate_url,
                            "raw_url": candidate_url,
                            "normalized_seed_url": seed_url,
                            "extraction_reason": "public_web_search_result_url",
                        }
                    )
                    if len(refs) >= max_results:
                        return refs
    return refs


async def discover_shopping_seeds_via_social_search(
    *,
    keywords: list[str],
    seed_platforms: list[str],
    category: str | None = None,
    limit: int = 100,
    completed_queries: set[str] | None = None,
    on_query_complete: Callable[[str, int], Awaitable[None]] | None = None,
    on_query_error: Callable[[str, list[str]], Awaitable[None]] | None = None,
    on_query_skip: Callable[[str, str], Awaitable[None]] | None = None,
    on_provider_unavailable: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> list[CollectedInfluencer]:
    """Search LTK / ShopMy / Pinterest seed URLs with checkpoint-aware bounded concurrency."""
    from app.services.api_direct_provider import discover_platform

    allowed = {p.strip().lower() for p in seed_platforms if p and p.strip()}
    allowed &= set(_SEED_PARSERS.keys())
    if not allowed:
        allowed = set(_SEED_PARSERS.keys())

    keyword_pool: list[str] = []
    for kw in keywords or []:
        text = (kw or "").strip()
        if text:
            keyword_pool.append(text)
    if category and str(category).strip():
        keyword_pool.append(str(category).strip())
    if not keyword_pool:
        return []

    cap = max(1, min(limit or 100, 500))
    seen_keys: set[tuple[str, str]] = set()
    seeds: list[CollectedInfluencer] = []
    plan = build_seed_search_plan(
        keywords=keyword_pool,
        seed_platforms=sorted(allowed),
        max_queries=getattr(settings, "shopping_seed_search_max_queries", DEFAULT_MAX_SEED_SEARCH_QUERIES),
    )
    completed_query_keys = {(query or "").strip().lower() for query in completed_queries or set()}
    provider_availability_state: dict[str, dict[str, Any]] = {}
    pending_plan: list[dict[str, str]] = []
    for search in plan:
        query = search["query"]
        source_keyword = search.get("source_keyword") or query
        if query.strip().lower() in completed_query_keys or source_keyword.strip().lower() in completed_query_keys:
            if on_query_skip:
                await on_query_skip(query, "checkpoint")
            continue
        pending_plan.append(search)

    def _collect_from_ref(ref: dict[str, str], *, query: str, source_keyword: str) -> CollectedInfluencer | None:
        platform = ref["link_seed_platform"]
        url = ref["link_seed_profile_url"]
        parsed = _parse_seed_profile(platform, url)
        if parsed is None:
            return None
        username_key = (parsed.username or "").strip().lower()
        if not username_key:
            return None
        dedupe = (platform, username_key)
        if dedupe in seen_keys:
            return None
        seen_keys.add(dedupe)
        source_meta = dict(parsed.source_meta or {})
        source_meta.update(ref)
        if "search_platform" not in source_meta and source_meta.get("source_platform"):
            source_meta["search_platform"] = source_meta["source_platform"]
        provider = (
            source_meta.get("source_platform")
            or source_meta.get("search_platform")
            or source_meta.get("provider")
            or "search"
        )
        source_meta["provider"] = provider
        source_meta.update({"search_query": query, "source_keyword": source_keyword})
        parsed.source_meta = source_meta
        collected = profile_to_collected(parsed)
        setattr(collected, "source_meta", source_meta)
        collected.source_input_url = source_meta.get("source_input_url") or url
        collected.source_post_url = source_meta.get("source_post_url") or collected.source_post_url
        collected.source_discovery_type = "link_seed_discovered"
        source_platform = str(provider)
        collected.tags = list(
            dict.fromkeys((collected.tags or []) + [f"shopping_seed:{platform}", f"shopping_seed:{source_platform}"])
        )
        return collected

    async def _search_one(search: dict[str, str]) -> tuple[dict[str, str], list[dict[str, str]], list[str]]:
        query = search["query"]
        refs: list[dict[str, str]] = []
        errors: list[str] = []
        platforms = configured_seed_search_platforms()
        public_web_timeout = max(3, getattr(settings, "shopping_seed_search_timeout_seconds", 12))
        pinterest_timeout = max(
            public_web_timeout,
            getattr(settings, "apify_pinterest_search_timeout_seconds", public_web_timeout),
        )
        if PUBLIC_WEB_SEARCH_PLATFORM in platforms:
            try:
                refs.extend(
                    await asyncio.wait_for(
                        search_public_web_for_seed_refs(
                            query,
                            allowed,
                            limit=max(1, min(cap, settings.shopping_seed_search_max_results)),
                        ),
                        timeout=public_web_timeout,
                    )
                )
            except TimeoutError:
                errors.append("public_web:query_timeout")
            except Exception as exc:
                errors.append(f"public_web:{exc}")
        if (
            "pinterest" in allowed
            and PINTEREST_APIFY_SEARCH_PLATFORM in platforms
            and should_use_pinterest_apify_for_query(query)
        ):
            unavailable = provider_availability_state.get(PINTEREST_APIFY_SEARCH_PLATFORM)
            if unavailable and unavailable.get("reason") in {
                NETWORK_UNREACHABLE_REASON,
                QUERY_TIMEOUT_REASON,
                APIFY_MEMORY_LIMIT_REASON,
            }:
                errors.append(
                    f"{PINTEREST_APIFY_SEARCH_PLATFORM}:{PROVIDER_UNAVAILABLE_STATUS}:{unavailable.get('reason')}"
                )
            else:
                try:
                    refs.extend(
                        await asyncio.wait_for(
                            search_pinterest_apify_for_seed_refs(
                                query,
                                limit=max(1, min(cap, settings.shopping_seed_search_max_results)),
                            ),
                            timeout=pinterest_timeout,
                        )
                    )
                except TimeoutError:
                    state = {
                        "status": PROVIDER_UNAVAILABLE_STATUS,
                        "reason": QUERY_TIMEOUT_REASON,
                        "message": "Pinterest Apify 搜索请求超时，已跳过后续 Pinterest Apify 查询",
                        "provider": PINTEREST_APIFY_SEARCH_PLATFORM,
                    }
                    provider_availability_state[PINTEREST_APIFY_SEARCH_PLATFORM] = state
                    if on_provider_unavailable:
                        await on_provider_unavailable(PINTEREST_APIFY_SEARCH_PLATFORM, state)
                    errors.append("pinterest_apify:query_timeout")
                except Exception as exc:
                    detail = str(exc).strip() or type(exc).__name__
                    if _is_apify_memory_limit_error(exc):
                        state = {
                            "status": PROVIDER_UNAVAILABLE_STATUS,
                            "reason": APIFY_MEMORY_LIMIT_REASON,
                            "message": "Apify 内存额度已满/并发 actor 过多，已跳过后续 Pinterest Apify 查询",
                            "provider": PINTEREST_APIFY_SEARCH_PLATFORM,
                        }
                        provider_availability_state[PINTEREST_APIFY_SEARCH_PLATFORM] = state
                        if on_provider_unavailable:
                            await on_provider_unavailable(PINTEREST_APIFY_SEARCH_PLATFORM, state)
                        errors.append(f"pinterest_apify:{APIFY_MEMORY_LIMIT_REASON}:{detail}")
                    elif is_apify_network_unreachable(exc):
                        state = {
                            "status": PROVIDER_UNAVAILABLE_STATUS,
                            "reason": NETWORK_UNREACHABLE_REASON,
                            "message": "当前环境无法连接 Apify（api.apify.com:443）",
                            "provider": PINTEREST_APIFY_SEARCH_PLATFORM,
                        }
                        provider_availability_state[PINTEREST_APIFY_SEARCH_PLATFORM] = state
                        if on_provider_unavailable:
                            await on_provider_unavailable(PINTEREST_APIFY_SEARCH_PLATFORM, state)
                        errors.append(f"pinterest_apify:{NETWORK_UNREACHABLE_REASON}:{detail}")
                    else:
                        errors.append(f"pinterest_apify:{exc}")
        for search_platform in configured_social_seed_search_platforms():
            mini_task = SimpleNamespace(
                keywords=[query],
                platform=search_platform,
                platforms=[search_platform],
                discovery_limit=8,
                collection_mode="keyword",
                input_urls=[],
                country=None,
                category=None,
                min_followers_count=None,
            )
            try:
                result = await discover_platform(mini_task, search_platform)
            except Exception as exc:
                logger.warning("Shopping seed search failed (%s, %s): %s", search_platform, query, exc)
                errors.append(f"{search_platform}:{exc}")
                continue
            for profile in result.profiles or []:
                item = profile_to_collected(profile)
                setattr(item, "source_meta", dict(profile.source_meta or {}))
                for ref in extract_seed_refs_from_collected(item, allowed, discovery_query=query):
                    ref.setdefault("source_platform", search_platform)
                    ref.setdefault("provider", search_platform)
                    refs.append(ref)
        return search, refs, errors

    async def _bounded_search(search: dict[str, str], sem: asyncio.Semaphore):
        async with sem:
            return await _search_one(search)

    concurrency = max(1, getattr(settings, "shopping_seed_search_concurrency", 3))
    empty_stop = max(0, getattr(settings, "shopping_seed_empty_query_stop_count", 4))
    sem = asyncio.Semaphore(concurrency)
    empty_streak = 0
    for start in range(0, len(pending_plan), concurrency):
        if len(seeds) >= cap:
            break
        if empty_stop and empty_streak >= empty_stop:
            for skipped in pending_plan[start:]:
                if on_query_skip:
                    await on_query_skip(skipped["query"], "empty_query_stop")
            break
        batch = pending_plan[start : start + concurrency]
        results = await asyncio.gather(*[_bounded_search(search, sem) for search in batch])
        for search, refs, errors in results:
            query = search["query"]
            source_keyword = search["source_keyword"]
            added_for_query = 0
            for ref in refs:
                collected = _collect_from_ref(ref, query=query, source_keyword=source_keyword)
                if collected is None:
                    continue
                seeds.append(collected)
                added_for_query += 1
                if len(seeds) >= cap:
                    break
            if errors:
                if on_query_error:
                    await on_query_error(query, errors)
            if added_for_query > 0 and not errors and on_query_complete:
                await on_query_complete(query, added_for_query)
            elif not errors and on_query_complete:
                await on_query_complete(query, added_for_query)
            empty_streak = empty_streak + 1 if added_for_query == 0 and not errors else 0
            if len(seeds) >= cap:
                break
    return seeds
