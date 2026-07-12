"""YouTube API Direct 平台 provider。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.api_direct_client import ApiDirectError, ad_get, get_request_count, is_rate_limit_error
from app.services.contact_discovery import (
    EMAIL_RE,
    EXCLUDED_EMAILS,
    EXCLUDED_EMAIL_SUFFIXES,
    _local_part_looks_like_filename,
    _pseudo_filename_adjacent_before,
    extract_emails_from_text,
    normalize_email,
)
from app.services.discovery_progress import report_discovery_progress
from app.services.platform_types import PlatformCapability, PlatformCandidateProfile, PlatformDiscoveryResult
from app.services.contact_signals import extract_urls_from_text
from app.services.concurrency import map_bounded
from app.services.collection_targets import (
    discovery_fetch_limit,
    overfetch_pages_for_limit,
    target_qualified_count,
)
from app.services.platform_utils import (
    dedupe_profiles,
    engagement_rate_from_metrics,
    parse_count_text,
    profile_to_collected,
)

from app.services.platform_providers.youtube_dedupe import normalize_keywords
from app.services.task_run_progress import STAGE_DISCOVERY, STAGE_HYDRATION

logger = logging.getLogger(__name__)

ENDPOINTS = [
    "/v1/youtube/posts",
    "/v1/youtube/channels",
    "/v1/youtube/video",
    "/v1/youtube/comments",
]
MAX_ABOUT_HYDRATIONS = 30
YOUTUBE_ABOUT_HYDRATION_CONCURRENCY = 2
_ABOUT_FETCH_TIMEOUT_SECONDS = 10
_HTTP_TIMEOUT = httpx.Timeout(connect=4.0, read=8.0, write=8.0, pool=4.0)
_INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlWIP9oR0QdBjAtpU1QU_Twe1eQ"
_INNERTUBE_CLIENT_VERSION = "2.20250328.01.00"
_INNERTUBE_BROWSE_URL = f"https://www.youtube.com/youtubei/v1/browse?key={_INNERTUBE_API_KEY}"
# 常见频道 About tab params（InnerTube protobuf 编码）
_ABOUT_TAB_PARAMS = (
    "EgVhYm91dCI6FAgKBg9",
    "EgVhYm91dA%3D%3D",
)
_CAPABILITY_MESSAGE = (
    "API Direct 已支持关键词搜索视频/频道（基础资料）；"
    "About/更多外链不在 /v1/youtube/channels 中，需公开页补采且受 YouTube 可达性影响"
)
_ABOUT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_YT_INITIAL_DATA_MARKERS = ("var ytInitialData = ", "ytInitialData = ")
_EXTERNAL_LINK_MODEL_RE = re.compile(
    r'"channelExternalLinkViewModel"\s*:\s*\{.*?"title"\s*:\s*\{[^}]*"content"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)".*?'
    r'"link"\s*:\s*\{[^}]*"content"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
    re.S,
)
_DIRECT_COMMERCE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:lnktr|linktr)\.ee/[A-Za-z0-9_-]+|"
    r"https?://(?:www\.)?(?:amzn\.to|amzlink\.to)/[A-Za-z0-9/_-]+|"
    r"https?://(?:www\.)?(?:beacons\.ai|stan\.store|solo\.to|msha\.ke|bio\.site)/[A-Za-z0-9/_-]+|"
    r"https?://(?:www\.)?urlgeni\.us/[A-Za-z0-9/_-]+",
    re.I,
)
_HTML_HREF_RE = re.compile(
    r"<a\b[^>]*\bhref=(?P<quote>[\"'])(?P<href>.*?)(?P=quote)[^>]*>(?P<label>.*?)</a>",
    re.I | re.S,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
CHANNEL_URL_RE = re.compile(r"youtube\.com/(?:channel/([^/?#]+)|@([^/?#]+))", re.I)
SOCIAL_HOST_LABELS = {
    "facebook.com": ("facebook", "Facebook"),
    "fb.com": ("facebook", "Facebook"),
    "twitter.com": ("twitter", "Twitter"),
    "x.com": ("twitter", "X"),
    "instagram.com": ("instagram", "Instagram"),
    "tiktok.com": ("tiktok", "TikTok"),
    "linkedin.com": ("linkedin", "LinkedIn"),
}
AGGREGATOR_HOST_LABELS = {
    "linktr.ee": ("linktree", "Linktree"),
    "linktree.com": ("linktree", "Linktree"),
    "lnktr.ee": ("linktree", "Linktree"),
    "lnkrtr.ee": ("linktree", "Linktree"),
    "beacons.ai": ("beacons", "Beacons"),
    "beacons.page": ("beacons", "Beacons"),
    "stan.store": ("stan_store", "Stan Store"),
    "carrd.co": ("carrd", "Carrd"),
    "carrd.site": ("carrd", "Carrd"),
    "solo.to": ("linktree", "Solo.to"),
    "msha.ke": ("linktree", "Msha.ke"),
    "bio.site": ("linktree", "Bio.site"),
}
STOREFRONT_HOST_LABELS = {
    "shopmy.us": ("shopmy", "ShopMy"),
    "shopltk.com": ("ltk", "LTK"),
}
COMMERCIAL_LINK_TYPES = frozenset(
    {
        "amazon_storefront",
        "shopmy",
        "ltk",
        "linktree",
        "beacons",
        "stan_store",
        "carrd",
        "website",
    }
)
SOCIAL_LINK_TYPES = frozenset(
    {
        "instagram",
        "tiktok",
        "facebook",
        "twitter",
        "linkedin",
    }
)
_EMAIL_BUTTON_TERMS = (
    "view email address",
    "view email",
    "show email",
    "查看电子邮件地址",
    "查看邮箱",
    "顯示電子郵件地址",
)
_PROFILE_COPY_UNSET = object()


@dataclass
class YouTubeAboutSignals:
    links: list[dict[str, str]]
    email: str | None = None
    contact_button_present: bool = False
    email_unexpanded: bool = False
    about_links_hydrated: bool = False
    fetch_status: str | None = None
    error: str | None = None


def _unique_strings(values: list[str | None], *, limit: int = 5) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _merge_recent_posts(*profiles: PlatformCandidateProfile) -> tuple[list[str], list[str]]:
    titles: list[str | None] = []
    urls: list[str | None] = []
    for profile in profiles:
        titles.extend(profile.recent_post_titles or [])
        urls.extend(profile.recent_post_urls or [])
        video_title = (profile.source_meta or {}).get("video_title")
        if video_title:
            titles.append(str(video_title))
        if profile.source_url:
            urls.append(profile.source_url)
    return _unique_strings(titles), _unique_strings(urls)


def _email_verification_required(channel: dict) -> bool:
    if channel.get("email_verification_required") is True:
        return True
    if channel.get("email_requires_verification") is True:
        return True
    status = str(channel.get("email_verification_status") or channel.get("email_status") or "").lower()
    return status in {"verification_required", "requires_verification", "manual_required", "pending_verification"}


def _channel_profile_url(channel_id: str | None, *, title: str | None = None) -> str | None:
    if channel_id:
        return f"https://www.youtube.com/channel/{channel_id}"
    if title:
        handle = title.strip().replace(" ", "")
        if handle:
            return f"https://www.youtube.com/@{handle}"
    return None


def _host_matches(host: str, known_host: str) -> bool:
    return host == known_host or host.endswith("." + known_host)


def _normalize_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    elif not re.match(r"^https?://", text, re.I):
        text = f"https://{text}"
    parsed = urlparse(text)
    if not parsed.netloc:
        return None
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if _host_matches(host, "youtube.com") and parsed.path.rstrip("/") == "/redirect":
        query = parse_qs(parsed.query)
        redirected = (query.get("q") or query.get("url") or [None])[0]
        if redirected:
            return _normalize_url(redirected)
    if _host_matches(host, "google.com") and parsed.path.rstrip("/") == "/url":
        query = parse_qs(parsed.query)
        redirected = (query.get("q") or query.get("url") or [None])[0]
        if redirected:
            return _normalize_url(redirected)
    return text.rstrip()


_YOUTUBE_LINK_LABELS = frozenset(
    {
        "shop",
        "store",
        "my links",
        "links",
        "link",
        "storefront",
        "amazon storefront",
        "website",
        "site",
        "contact",
    }
)


def _resolve_link_label(link_type: str, resolved_label: str, fallback_label: str | None) -> str:
    custom = (fallback_label or "").strip()
    if not custom:
        return resolved_label
    if custom.lower() == resolved_label.lower():
        return resolved_label
    if custom.lower() in _YOUTUBE_LINK_LABELS:
        return custom
    if link_type in {"linktree", "website", "amazon_storefront", "shopmy", "ltk"}:
        return custom
    if link_type == "website" and resolved_label == "Website":
        return custom
    return resolved_label


def _url_from_link_item(item: dict) -> object:
    for key in ("url", "href", "link", "target_url"):
        value = item.get(key)
        if value:
            return value
    endpoint = item.get("navigation_endpoint") or item.get("navigationEndpoint")
    if isinstance(endpoint, str):
        return endpoint
    if isinstance(endpoint, dict):
        command = endpoint.get("commandMetadata") or {}
        web_command = command.get("webCommandMetadata") or {}
        return (
            endpoint.get("url")
            or endpoint.get("href")
            or web_command.get("url")
            or web_command.get("webPageType")
        )
    return None


def _link_type_and_label(url: str, fallback_label: str | None = None) -> tuple[str, str]:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    lower_url = url.lower()
    for known_host, result in SOCIAL_HOST_LABELS.items():
        if _host_matches(host, known_host):
            return result
    for known_host, result in AGGREGATOR_HOST_LABELS.items():
        if _host_matches(host, known_host):
            return result
    for known_host, result in STOREFRONT_HOST_LABELS.items():
        if _host_matches(host, known_host):
            return result
    if "amazon.com/shop/" in lower_url or "amazon.com/stores/" in lower_url or "amzn.to/" in lower_url or "amzlink.to/" in lower_url or "urlgeni.us/amzn/" in lower_url:
        return ("amazon_storefront", "Amazon storefront")
    return ("website", (fallback_label or "Website").strip() or "Website")


def _append_link(links: list[dict[str, str]], seen: set[str], url: object, label: object = None) -> None:
    normalized = _normalize_url(url)
    if not normalized:
        return
    host = (urlparse(normalized).netloc or "").lower().removeprefix("www.")
    if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
        return
    if normalized in seen:
        return
    text_label = str(label).strip() if label is not None else None
    link_type, resolved_label = _link_type_and_label(normalized, text_label)
    final_label = _resolve_link_label(link_type, resolved_label, text_label)
    links.append({"type": link_type, "label": final_label, "url": normalized})
    seen.add(normalized)


def _iter_link_dicts(value: object):
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item
    elif isinstance(value, dict):
        for key in ("links", "external_links", "social_links", "channels", "items"):
            yield from _iter_link_dicts(value.get(key))


def _extract_channel_links(channel: dict) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    for key in ("website", "url_external"):
        _append_link(links, seen, channel.get(key), "Website")

    for container_key in ("links", "external_links", "social_links", "about", "details", "about_links", "channel_links"):
        for item in _iter_link_dicts(channel.get(container_key)):
            url = _url_from_link_item(item)
            label = item.get("title") or item.get("label") or item.get("name") or item.get("text")
            _append_link(links, seen, url, label)

    for key, label in (
        ("facebook", "Facebook"),
        ("facebook_url", "Facebook"),
        ("twitter", "Twitter"),
        ("twitter_url", "Twitter"),
        ("x", "X"),
        ("x_url", "X"),
        ("instagram", "Instagram"),
        ("instagram_url", "Instagram"),
        ("tiktok", "TikTok"),
        ("tiktok_url", "TikTok"),
        ("linktree", "Linktree"),
        ("linktree_url", "Linktree"),
    ):
        _append_link(links, seen, channel.get(key), label)

    return links


def _merge_link_dicts(*groups: list[dict[str, str]] | None) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for link in group or []:
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(
                {
                    "type": str(link.get("type") or "website"),
                    "label": str(link.get("label") or "Links"),
                    "url": url,
                }
            )
    return merged


def _normalize_youtube_description_email(raw: str | None) -> str | None:
    if not raw:
        return None
    email = raw.strip().lower().strip(".,;)'\"")
    if not email or "@" not in email:
        return None
    if email in EXCLUDED_EMAILS:
        return None
    if any(email.endswith(suffix) for suffix in EXCLUDED_EMAIL_SUFFIXES):
        return None
    local, _domain = email.split("@", 1)
    if _local_part_looks_like_filename(local):
        return None
    if not EMAIL_RE.fullmatch(email):
        return None
    return email


def _extract_first_email(*texts: object, source_type: str = "youtube_description") -> str | None:
    for value in texts:
        if not isinstance(value, str) or not value.strip():
            continue
        for candidate in extract_emails_from_text(value, source_type):
            if candidate.email:
                return candidate.email
        for match in EMAIL_RE.finditer(value):
            if _pseudo_filename_adjacent_before(value, match.start()):
                continue
            email = _normalize_youtube_description_email(match.group(0))
            if email:
                return email
    return None


def _append_links_from_text(links: list[dict[str, str]], seen: set[str], text: object) -> None:
    if not isinstance(text, str) or not text.strip():
        return
    for raw_url in extract_urls_from_text(text):
        normalized = _normalize_url(raw_url)
        if not normalized:
            continue
        host = (urlparse(normalized).netloc or "").lower().removeprefix("www.")
        link_type, _ = _link_type_and_label(normalized, None)
        if link_type == "website" and any(
            link.get("type") == "website"
            and (urlparse(str(link.get("url") or "")).netloc or "").lower().removeprefix("www.") == host
            for link in links
        ):
            continue
        _append_link(links, seen, normalized, _label_for_snippet_url(text, normalized))


def _extract_description_signals(text: object) -> YouTubeAboutSignals:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    _append_links_from_text(links, seen, text)
    email = _extract_first_email(text)
    return YouTubeAboutSignals(
        links=links,
        email=email,
        about_links_hydrated=False,
        fetch_status="description" if links or email else None,
    )


def _contains_email_button_text(text: object) -> bool:
    if not isinstance(text, str):
        return False
    lower = text.lower()
    return any(term.lower() in lower for term in _EMAIL_BUTTON_TERMS)


def _scan_yt_payload_for_about_signals(value: object, descriptions: list[str], button_flag: list[bool]) -> None:
    if isinstance(value, dict):
        text = _yt_text_content(value)
        if text:
            lower = text.lower()
            if "@" in text or "http://" in lower or "https://" in lower:
                descriptions.append(text)
            if _contains_email_button_text(text):
                button_flag[0] = True
        for key in ("description", "descriptionText", "aboutDescription", "channelDescription"):
            text = _yt_text_content(value.get(key))
            if text:
                descriptions.append(text)
        for nested in value.values():
            _scan_yt_payload_for_about_signals(nested, descriptions, button_flag)
    elif isinstance(value, list):
        for item in value:
            _scan_yt_payload_for_about_signals(item, descriptions, button_flag)


def _link_type_summary(links: list[dict[str, str]] | None) -> tuple[int, list[str], int, int]:
    total = 0
    commercial = 0
    social = 0
    types: list[str] = []
    seen_types: set[str] = set()
    for link in links or []:
        if not isinstance(link, dict):
            continue
        link_type = str(link.get("type") or "").strip().lower() or "website"
        total += 1
        if link_type in COMMERCIAL_LINK_TYPES:
            commercial += 1
        if link_type in SOCIAL_LINK_TYPES:
            social += 1
        if link_type not in seen_types:
            seen_types.add(link_type)
            types.append(link_type)
    return total, types, commercial, social


def _augment_source_meta_with_links(meta: dict | None, links: list[dict[str, str]] | None) -> dict:
    next_meta = dict(meta or {})
    total, types, commercial, social = _link_type_summary(links)
    next_meta["external_link_count"] = total
    next_meta["external_link_types"] = types
    next_meta["commercial_link_count"] = commercial
    next_meta["social_link_count"] = social
    next_meta["has_external_links"] = total > 0
    next_meta["has_commercial_links"] = commercial > 0
    return next_meta


def _label_for_snippet_url(snippet: str, url: str) -> str:
    lower = snippet.lower()
    if any(term in lower for term in ("shop my home", "shop my", "shop everything", "shop here")):
        return "Shop"
    if "amazon" in lower or "amzn" in url.lower():
        return "Amazon storefront"
    if "linktree" in lower or "lnktr" in url.lower() or "linktr" in url.lower():
        return "Links"
    return "Links"


def _collect_snippet_links_by_channel(posts: list[dict]) -> dict[str, list[dict[str, str]]]:
    by_channel: dict[str, list[dict[str, str]]] = {}
    for post in posts:
        if not isinstance(post, dict):
            continue
        channel_id = str(post.get("channel_id") or "").strip()
        snippet = str(post.get("snippet") or post.get("description") or "").strip()
        if not channel_id or not snippet:
            continue
        bucket = by_channel.setdefault(channel_id, [])
        seen = {link["url"] for link in bucket}
        for raw_url in extract_urls_from_text(snippet):
            normalized = _normalize_url(raw_url)
            if not normalized or normalized in seen:
                continue
            host = (urlparse(normalized).netloc or "").lower()
            if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
                continue
            label = _label_for_snippet_url(snippet, normalized)
            link_type, resolved_label = _link_type_and_label(normalized, label)
            final_label = _resolve_link_label(link_type, resolved_label, label)
            bucket.append({"type": link_type, "label": final_label, "url": normalized})
            seen.add(normalized)
    return by_channel


def _decode_yt_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.replace("\\/", "/")


def _decode_html_text(value: str) -> str:
    text = _HTML_TAG_RE.sub("", value or "")
    return (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .strip()
    )


def _yt_text_content(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in ("content", "simpleText", "text"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
            if isinstance(nested, dict):
                runs = nested.get("runs")
                if isinstance(runs, list):
                    parts = [
                        str(item.get("text") or "").strip()
                        for item in runs
                        if isinstance(item, dict) and item.get("text")
                    ]
                    joined = "".join(parts).strip()
                    if joined:
                        return joined
    return None


def _yt_url_from_endpoint(endpoint: object) -> str | None:
    if not isinstance(endpoint, dict):
        return None
    command = endpoint.get("commandMetadata") or {}
    web_command = command.get("webCommandMetadata") or {}
    for candidate in (
        endpoint.get("url"),
        endpoint.get("href"),
        web_command.get("url"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _append_links_from_yt_object(value: object, links: list[dict[str, str]], seen: set[str]) -> None:
    if isinstance(value, dict):
        model = value.get("channelExternalLinkViewModel")
        if isinstance(model, dict):
            label = _yt_text_content(model.get("title")) or "Links"
            url = _yt_text_content(model.get("link")) or _yt_url_from_endpoint(model.get("link"))
            if not url:
                endpoint = model.get("linkEndpoint") or model.get("navigationEndpoint")
                url = _yt_url_from_endpoint(endpoint)
            _append_link(links, seen, url, label)

        for key in ("title", "label", "name", "text"):
            label = _yt_text_content(value.get(key))
            if not label:
                continue
            for url_key in ("url", "href", "link", "target_url", "externalUrl"):
                _append_link(links, seen, value.get(url_key), label)
            endpoint = value.get("navigationEndpoint") or value.get("linkEndpoint")
            endpoint_url = _yt_url_from_endpoint(endpoint)
            if endpoint_url:
                _append_link(links, seen, endpoint_url, label)

        for nested in value.values():
            _append_links_from_yt_object(nested, links, seen)
    elif isinstance(value, list):
        for item in value:
            _append_links_from_yt_object(item, links, seen)


def _extract_links_from_yt_payload(payload: object) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    _append_links_from_yt_object(payload, links, seen)
    return links


def _extract_yt_initial_data(html: str) -> dict | None:
    for marker in _YT_INITIAL_DATA_MARKERS:
        idx = html.find(marker)
        if idx < 0:
            continue
        start = html.find("{", idx + len(marker))
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for pos in range(start, len(html)):
            ch = html[pos]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(html[start : pos + 1])
                    except json.JSONDecodeError:
                        return None
                    return parsed if isinstance(parsed, dict) else None
    return None


def _extract_about_signals_from_html(html: str) -> YouTubeAboutSignals:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    descriptions: list[str] = []
    button_flag = [False]

    initial_data = _extract_yt_initial_data(html)
    if initial_data:
        for link in _extract_links_from_yt_payload(initial_data):
            _append_link(links, seen, link.get("url"), link.get("label"))
        _scan_yt_payload_for_about_signals(initial_data, descriptions, button_flag)

    for match in _EXTERNAL_LINK_MODEL_RE.finditer(html):
        label = _decode_yt_json_string(match.group(1))
        url = _decode_yt_json_string(match.group(2))
        _append_link(links, seen, url, label)
    for match in _HTML_HREF_RE.finditer(html):
        url = _decode_html_text(match.group("href"))
        label = _decode_html_text(match.group("label")) or "Links"
        _append_link(links, seen, url, label)
    for match in _DIRECT_COMMERCE_URL_RE.finditer(html):
        _append_link(links, seen, match.group(0), "Shop")

    visible_text = _decode_html_text(html)
    descriptions.append(visible_text)
    _append_links_from_text(links, seen, visible_text)
    contact_button_present = button_flag[0] or _contains_email_button_text(visible_text)
    email = _extract_first_email(*descriptions)
    return YouTubeAboutSignals(
        links=links,
        email=email,
        contact_button_present=contact_button_present,
        email_unexpanded=contact_button_present,
        about_links_hydrated=bool(links),
        fetch_status="success" if links or email or contact_button_present else "empty_or_unreachable",
    )


def _extract_about_links_from_html(html: str) -> list[dict[str, str]]:
    return _extract_about_signals_from_html(html).links


def _extract_about_signals_from_payload(payload: object) -> YouTubeAboutSignals:
    links = _extract_links_from_yt_payload(payload)
    descriptions: list[str] = []
    button_flag = [False]
    _scan_yt_payload_for_about_signals(payload, descriptions, button_flag)
    seen = {link["url"] for link in links if isinstance(link, dict) and link.get("url")}
    for text in descriptions:
        _append_links_from_text(links, seen, text)
    email = _extract_first_email(*descriptions)
    return YouTubeAboutSignals(
        links=links,
        email=email,
        contact_button_present=button_flag[0],
        email_unexpanded=button_flag[0],
        about_links_hydrated=bool(links),
        fetch_status="success" if links or email or button_flag[0] else "empty_or_unreachable",
    )


def _public_page_urls(channel_id: str | None, profile_url: str | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def _add(url: str | None) -> None:
        if not url:
            return
        normalized = url.rstrip("/")
        if normalized in seen:
            return
        seen.add(normalized)
        urls.append(normalized)

    if channel_id:
        _add(f"https://www.youtube.com/channel/{channel_id}/about")
        _add(f"https://www.youtube.com/channel/{channel_id}")
    if profile_url:
        base = profile_url.rstrip("/")
        _add(f"{base}/about" if "/about" not in base else base)
        if "/about" in base:
            _add(base.replace("/about", ""))
        else:
            _add(base)
    return urls


def _about_http_headers() -> dict[str, str]:
    return {
        "User-Agent": _ABOUT_USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/json",
    }


async def _fetch_links_from_public_html(
    url: str,
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, str]]:
    return (await _fetch_signals_from_public_html(url, client=client)).links


async def _fetch_signals_from_public_html(
    url: str,
    *,
    client: httpx.AsyncClient,
) -> YouTubeAboutSignals:
    response = await client.get(url)
    response.raise_for_status()
    return _extract_about_signals_from_html(response.text)


async def _fetch_innertube_about_links(
    channel_id: str | None,
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, str]]:
    return (await _fetch_innertube_about_signals(channel_id, client=client)).links


def _merge_about_signals(*groups: YouTubeAboutSignals | None) -> YouTubeAboutSignals:
    links = _merge_link_dicts(*[group.links for group in groups if group])
    email = next((group.email for group in groups if group and group.email), None)
    contact_button_present = any(bool(group and group.contact_button_present) for group in groups)
    errors = [group.error for group in groups if group and group.error]
    fetch_status = "success" if links or email or contact_button_present else "empty_or_unreachable"
    return YouTubeAboutSignals(
        links=links,
        email=email,
        contact_button_present=contact_button_present,
        email_unexpanded=contact_button_present,
        about_links_hydrated=bool(links),
        fetch_status=fetch_status,
        error="; ".join(errors)[:500] if errors else None,
    )


async def _fetch_innertube_about_signals(
    channel_id: str | None,
    *,
    client: httpx.AsyncClient,
) -> YouTubeAboutSignals:
    if not channel_id:
        return YouTubeAboutSignals(links=[], fetch_status="empty_or_unreachable")
    merged = YouTubeAboutSignals(links=[], fetch_status="empty_or_unreachable")
    payload_base = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": _INNERTUBE_CLIENT_VERSION,
                "hl": "en",
                "gl": "US",
            }
        },
        "browseId": channel_id,
    }
    for params in _ABOUT_TAB_PARAMS:
        payload = {**payload_base, "params": params}
        try:
            response = await client.post(
                _INNERTUBE_BROWSE_URL,
                json=payload,
                headers={**_about_http_headers(), "Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.debug("YouTube InnerTube about failed for %s (%s): %s", channel_id, params, exc)
            continue
        merged = _merge_about_signals(merged, _extract_about_signals_from_payload(data))
        if merged.links or merged.email or merged.contact_button_present:
            break
    return merged


async def fetch_youtube_channel_about_links(
    channel_id: str | None,
    profile_url: str | None,
) -> list[dict[str, str]]:
    """从 YouTube 公开页/InnerTube 补采频道 About 外链（只读，不绕过验证码）。"""
    if not channel_id and not profile_url:
        return []
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers=_about_http_headers(),
            trust_env=True,
        ) as client:
            for link in await _fetch_innertube_about_links(channel_id, client=client):
                _append_link(merged, seen, link.get("url"), link.get("label"))
            if merged:
                return merged
            for page_url in _public_page_urls(channel_id, profile_url):
                try:
                    for link in await _fetch_links_from_public_html(page_url, client=client):
                        _append_link(merged, seen, link.get("url"), link.get("label"))
                except Exception as exc:
                    logger.debug("YouTube public page hydration failed for %s: %s", page_url, exc)
                if merged:
                    break
    except Exception as exc:
        logger.debug("YouTube about hydration failed for %s: %s", channel_id or profile_url, exc)
    return merged


async def _fetch_channel_about_links(
    channel_id: str | None,
    profile_url: str | None,
) -> list[dict[str, str]]:
    return await fetch_youtube_channel_about_links(channel_id, profile_url)


async def _fetch_channel_about_signals(
    channel_id: str | None,
    profile_url: str | None,
) -> YouTubeAboutSignals:
    if not channel_id and not profile_url:
        return YouTubeAboutSignals(links=[], fetch_status="empty_or_unreachable")
    merged = YouTubeAboutSignals(links=[], fetch_status="empty_or_unreachable")
    errors: list[str] = []
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers=_about_http_headers(),
            trust_env=True,
        ) as client:
            merged = _merge_about_signals(merged, await _fetch_innertube_about_signals(channel_id, client=client))
            if merged.links or merged.email or merged.contact_button_present:
                return merged
            for page_url in _public_page_urls(channel_id, profile_url):
                try:
                    merged = _merge_about_signals(
                        merged,
                        await _fetch_signals_from_public_html(page_url, client=client),
                    )
                except Exception as exc:
                    errors.append(f"{page_url}: {exc}")
                    logger.debug("YouTube public page hydration failed for %s: %s", page_url, exc)
                if merged.links or merged.email or merged.contact_button_present:
                    break
    except Exception as exc:
        errors.append(str(exc))
        logger.debug("YouTube about hydration failed for %s: %s", channel_id or profile_url, exc)
    if errors and not (merged.links or merged.email or merged.contact_button_present):
        merged.fetch_status = "failed"
        merged.error = "; ".join(errors)[:500]
    return merged


def _append_links_to_profile(
    profile: PlatformCandidateProfile,
    extra_links: list[dict[str, str]],
) -> PlatformCandidateProfile:
    if not extra_links:
        return profile
    merged_links = _merge_link_dicts(profile.other_social_links, extra_links)
    website = profile.website or _primary_website({}, merged_links)
    return PlatformCandidateProfile(
        platform=profile.platform,
        username=profile.username,
        profile_url=profile.profile_url,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        followers_count=profile.followers_count,
        avg_views=profile.avg_views,
        avg_likes=profile.avg_likes,
        avg_comments=profile.avg_comments,
        engagement_rate=profile.engagement_rate,
        website=website,
        email=profile.email,
        other_social_links=merged_links,
        recent_post_titles=list(profile.recent_post_titles or []),
        recent_post_urls=list(profile.recent_post_urls or []),
        source_url=profile.source_url,
        source_type=profile.source_type,
        source_discovery_type=profile.source_discovery_type,
        source_meta=_augment_source_meta_with_links(profile.source_meta, merged_links),
        channel_id=profile.channel_id,
    )


def _copy_profile(
    profile: PlatformCandidateProfile,
    *,
    bio: str | None | object = _PROFILE_COPY_UNSET,
    website: str | None | object = _PROFILE_COPY_UNSET,
    email: str | None | object = _PROFILE_COPY_UNSET,
    other_social_links: list[dict[str, str]] | None | object = _PROFILE_COPY_UNSET,
    source_meta: dict | None | object = _PROFILE_COPY_UNSET,
) -> PlatformCandidateProfile:
    return PlatformCandidateProfile(
        platform=profile.platform,
        username=profile.username,
        profile_url=profile.profile_url,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        bio=profile.bio if bio is _PROFILE_COPY_UNSET else bio,
        followers_count=profile.followers_count,
        avg_views=profile.avg_views,
        avg_likes=profile.avg_likes,
        avg_comments=profile.avg_comments,
        engagement_rate=profile.engagement_rate,
        website=profile.website if website is _PROFILE_COPY_UNSET else website,
        email=profile.email if email is _PROFILE_COPY_UNSET else email,
        other_social_links=list(profile.other_social_links or []) if other_social_links is _PROFILE_COPY_UNSET else list(other_social_links or []),
        recent_post_titles=list(profile.recent_post_titles or []),
        recent_post_urls=list(profile.recent_post_urls or []),
        source_url=profile.source_url,
        source_type=profile.source_type,
        source_discovery_type=profile.source_discovery_type,
        source_meta=dict(profile.source_meta or {}) if source_meta is _PROFILE_COPY_UNSET else dict(source_meta or {}),
        channel_id=profile.channel_id,
    )


def _rate_limit_message(keyword: str, endpoint: str) -> str:
    return f"YouTube {endpoint}「{keyword}」: API Direct 限流 (429)，正在降速重试"


def _youtube_keyword_search_concurrency() -> int:
    return max(
        1,
        min(
            settings.collection_search_concurrency,
            settings.youtube_api_direct_keyword_concurrency,
        ),
    )


def _discovery_deadline() -> float:
    return time.perf_counter() + max(30, settings.youtube_discovery_max_duration_seconds)


async def _ad_get_timed(
    path: str,
    *,
    params: dict | None,
    platform: str,
    timeout_seconds: float,
) -> dict:
    try:
        return await asyncio.wait_for(
            ad_get(path, params=params, platform=platform),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise ApiDirectError(
            f"API Direct 请求超时 (>{timeout_seconds:.0f}s): {path}",
        ) from exc


async def _hydrate_profiles_about(
    profiles: list[PlatformCandidateProfile],
) -> list[PlatformCandidateProfile]:
    candidates = [profile for profile in profiles if profile.channel_id or profile.profile_url]
    if not candidates:
        return profiles
    limited = candidates[:MAX_ABOUT_HYDRATIONS]
    hydrated_so_far = 0

    async def _hydrate(profile: PlatformCandidateProfile) -> PlatformCandidateProfile:
        nonlocal hydrated_so_far
        try:
            about_signals = await _fetch_channel_about_signals(profile.channel_id, profile.profile_url)
        except Exception as exc:
            about_signals = YouTubeAboutSignals(
                links=[],
                fetch_status="failed",
                error=str(exc),
            )
        hydrated_so_far += 1
        await report_discovery_progress(
            phase=STAGE_HYDRATION,
            profile_fetched_count=hydrated_so_far,
        )
        meta = dict(profile.source_meta or {})
        if about_signals.links:
            enriched = _append_links_to_profile(profile, about_signals.links)
            meta = _augment_source_meta_with_links(meta, enriched.other_social_links)
            meta["about_links_hydrated"] = True
            meta["about_links_source"] = "public_page"
            meta["contact_button_present"] = about_signals.contact_button_present
            meta["email_unexpanded"] = about_signals.email_unexpanded
            if about_signals.email:
                meta["email_source"] = "youtube_about"
            return _copy_profile(
                enriched,
                email=about_signals.email or enriched.email,
                source_meta=meta,
            )
        meta = _augment_source_meta_with_links(meta, profile.other_social_links)
        meta["about_links_hydrated"] = False
        meta["about_links_fetch"] = about_signals.fetch_status or "empty_or_unreachable"
        meta["contact_button_present"] = about_signals.contact_button_present
        meta["email_unexpanded"] = about_signals.email_unexpanded
        if about_signals.error:
            meta["about_links_error"] = about_signals.error
        if about_signals.email:
            meta["email_source"] = "youtube_about"
        return _copy_profile(
            profile,
            email=about_signals.email or profile.email,
            source_meta=meta,
        )

    outcomes = await map_bounded(
        limited,
        _hydrate,
        concurrency=min(YOUTUBE_ABOUT_HYDRATION_CONCURRENCY, settings.collection_search_concurrency),
    )
    enriched_map = {
        (profile.platform, profile.profile_url.lower().rstrip("/")): profile
        for profile in outcomes
        if isinstance(profile, PlatformCandidateProfile)
    }
    result: list[PlatformCandidateProfile] = []
    for profile in profiles:
        key = (profile.platform, profile.profile_url.lower().rstrip("/"))
        result.append(enriched_map.get(key, profile))
    return result


def _primary_website(channel: dict, links: list[dict[str, str]]) -> str | None:
    explicit = _normalize_url(channel.get("website") or channel.get("url_external"))
    if explicit:
        host = (urlparse(explicit).netloc or "").lower().removeprefix("www.")
        aggregator_hosts = set(AGGREGATOR_HOST_LABELS.keys())
        if not any(_host_matches(host, known) for known in aggregator_hosts):
            return explicit
    for link in links:
        if link.get("type") == "website":
            return link.get("url")
    return None


def _profile_from_channel(channel: dict, *, source_keyword: str | None, source_type: str) -> PlatformCandidateProfile | None:
    channel_id = channel.get("channel_id")
    title = (channel.get("title") or "").strip()
    if not channel_id and not title:
        return None
    username = channel_id or title.replace(" ", "_")
    profile_url = channel.get("url") or _channel_profile_url(channel_id, title=title)
    if not profile_url:
        return None
    external_links = _extract_channel_links(channel)
    description_signals = _extract_description_signals(channel.get("description"))
    external_links = _merge_link_dicts(external_links, description_signals.links)
    email_verification_required = _email_verification_required(channel)
    explicit_email = normalize_email(channel.get("email") or channel.get("business_email"))
    email = explicit_email or description_signals.email
    source_meta = _augment_source_meta_with_links(
        {
            "provider": "api_direct",
            "endpoint": "/v1/youtube/channels",
            "source_keyword": source_keyword,
            "subscriber_count_raw": channel.get("subscriber_count"),
            "email_verification_required": email_verification_required,
        },
        external_links,
    )
    if email and description_signals.email and not explicit_email:
        source_meta["email_source"] = "youtube_description"
    return PlatformCandidateProfile(
        platform="youtube",
        username=username,
        profile_url=profile_url,
        display_name=title or None,
        avatar_url=channel.get("thumbnail"),
        bio=channel.get("description"),
        followers_count=parse_count_text(channel.get("subscriber_count")),
        website=_primary_website(channel, external_links),
        email=email,
        other_social_links=external_links,
        source_type=source_type,
        source_discovery_type="channel_search",
        channel_id=channel_id,
        source_meta=source_meta,
    )


def _profile_from_post(post: dict, *, source_keyword: str | None) -> PlatformCandidateProfile | None:
    channel_id = post.get("channel_id")
    author = (post.get("author") or "").strip()
    if not channel_id and not author:
        return None
    username = channel_id or author.replace(" ", "_")
    profile_url = _channel_profile_url(channel_id, title=author)
    if not profile_url:
        return None
    views = post.get("views")
    title = (post.get("title") or "").strip()
    post_url = post.get("url")
    return PlatformCandidateProfile(
        platform="youtube",
        username=username,
        profile_url=profile_url,
        display_name=author or None,
        avatar_url=post.get("thumbnail"),
        bio=post.get("snippet"),
        avg_views=views if isinstance(views, int) else None,
        engagement_rate=engagement_rate_from_metrics(
            views=views if isinstance(views, int) else None,
            likes=None,
            comments=None,
        ),
        source_url=post_url,
        source_post_url=str(post_url) if post_url else None,
        recent_post_titles=[title] if title else [],
        recent_post_urls=[str(post_url)] if post_url else [],
        source_type="keyword_video_channel",
        source_discovery_type="video_channel",
        channel_id=channel_id,
        source_meta={
            "provider": "api_direct",
            "endpoint": "/v1/youtube/posts",
            "source_keyword": source_keyword,
            "video_title": title or None,
        },
    )


def _profile_from_input_url(url: str) -> PlatformCandidateProfile | None:
    text = url.strip()
    if not text:
        return None
    match = CHANNEL_URL_RE.search(text)
    if match:
        channel_id = match.group(1)
        handle = match.group(2)
        if channel_id:
            profile_url = f"https://www.youtube.com/channel/{channel_id}"
            username = channel_id
        else:
            profile_url = f"https://www.youtube.com/@{handle}"
            username = handle
        return PlatformCandidateProfile(
            platform="youtube",
            username=username,
            profile_url=profile_url,
            source_type="input_url",
            source_discovery_type="url_import",
            channel_id=channel_id,
            source_meta={
                "provider": "api_direct",
                "input_url": text,
                "link_type": "profile",
                "profile_hydration": "url_only_pending_channel_search",
            },
        )

    from app.services.platform_providers.youtube_dedupe import extract_video_id

    video_id = extract_video_id({"url": text})
    if not video_id:
        return None
    return PlatformCandidateProfile(
        platform="youtube",
        username=f"video_{video_id}",
        profile_url=f"https://www.youtube.com/watch?v={video_id}",
        source_url=text,
        source_post_url=text,
        source_type="input_url",
        source_discovery_type="url_import",
        source_meta={
            "provider": "api_direct",
            "input_url": text,
            "link_type": "post",
            "video_id": video_id,
            "profile_hydration": "url_only_pending_video_lookup",
        },
    )


async def _hydrate_url_import_video_profiles(
    profiles: list[PlatformCandidateProfile],
    *,
    errors: list[str],
    keyword_timeout: int,
) -> list[PlatformCandidateProfile]:
    hydrated: list[PlatformCandidateProfile] = []
    for profile in profiles:
        meta = profile.source_meta or {}
        if meta.get("profile_hydration") != "url_only_pending_video_lookup":
            hydrated.append(profile)
            continue
        video_id = meta.get("video_id")
        input_url = meta.get("input_url") or profile.source_post_url or profile.source_url
        if not video_id:
            hydrated.append(profile)
            continue
        try:
            post_data = await _ad_get_timed(
                "/v1/youtube/posts",
                params={"query": str(video_id), "pages": "1"},
                platform="youtube",
                timeout_seconds=keyword_timeout,
            )
            posts = post_data.get("posts") or []
            matched = posts[0] if posts else None
            if not isinstance(matched, dict):
                errors.append(f"YouTube 视频 {input_url}: 未返回频道信息")
                hydrated.append(profile)
                continue
            channel_profile = _profile_from_post(matched, source_keyword=None)
            if channel_profile is None:
                errors.append(f"YouTube 视频 {input_url}: 无法解析频道")
                hydrated.append(profile)
                continue
            source_post_url = profile.source_post_url or str(input_url or "")
            hydrated.append(
                PlatformCandidateProfile(
                    platform=channel_profile.platform,
                    username=channel_profile.username,
                    profile_url=channel_profile.profile_url,
                    display_name=channel_profile.display_name,
                    avatar_url=channel_profile.avatar_url,
                    bio=channel_profile.bio,
                    followers_count=channel_profile.followers_count,
                    avg_views=channel_profile.avg_views,
                    avg_likes=channel_profile.avg_likes,
                    avg_comments=channel_profile.avg_comments,
                    engagement_rate=channel_profile.engagement_rate,
                    website=channel_profile.website,
                    email=channel_profile.email,
                    other_social_links=channel_profile.other_social_links,
                    recent_post_titles=channel_profile.recent_post_titles,
                    recent_post_urls=channel_profile.recent_post_urls or ([source_post_url] if source_post_url else []),
                    source_url=source_post_url or channel_profile.source_url,
                    source_post_url=source_post_url or None,
                    source_type="input_url",
                    source_discovery_type="url_import",
                    channel_id=channel_profile.channel_id,
                    source_meta={
                        **(channel_profile.source_meta or {}),
                        **meta,
                        "link_type": "post",
                        "profile_hydration": "video_channel_resolved",
                    },
                )
            )
        except ApiDirectError as exc:
            errors.append(f"YouTube 视频 {input_url}: {exc}")
            hydrated.append(profile)
        except httpx.HTTPError as exc:
            errors.append(f"YouTube 视频 {input_url}: 网络请求失败 ({exc.__class__.__name__})")
            hydrated.append(profile)
        except Exception as exc:
            errors.append(f"YouTube 视频 {input_url}: {exc}")
            hydrated.append(profile)
    return hydrated


def _merge_channel_details(
    profiles: list[PlatformCandidateProfile],
    channels: list[PlatformCandidateProfile],
) -> list[PlatformCandidateProfile]:
    by_id = {p.channel_id: p for p in channels if p.channel_id}
    by_url = {p.profile_url.lower().rstrip("/"): p for p in channels}
    merged: list[PlatformCandidateProfile] = []
    for profile in profiles:
        enriched = profile
        if profile.channel_id and profile.channel_id in by_id:
            src = by_id[profile.channel_id]
            recent_titles, recent_urls = _merge_recent_posts(profile, src)
            enriched = PlatformCandidateProfile(
                platform=profile.platform,
                username=profile.username,
                profile_url=profile.profile_url,
                display_name=src.display_name or profile.display_name,
                avatar_url=src.avatar_url or profile.avatar_url,
                bio=src.bio or profile.bio,
                followers_count=src.followers_count or profile.followers_count,
                avg_views=profile.avg_views or src.avg_views,
                avg_likes=profile.avg_likes,
                avg_comments=profile.avg_comments,
                engagement_rate=profile.engagement_rate or src.engagement_rate,
                website=src.website or profile.website,
                email=src.email or profile.email,
                other_social_links=_merge_link_dicts(src.other_social_links, profile.other_social_links),
                recent_post_titles=recent_titles,
                recent_post_urls=recent_urls,
                source_url=profile.source_url,
                source_type=profile.source_type,
                source_discovery_type=profile.source_discovery_type,
                source_meta={**(profile.source_meta or {}), **(src.source_meta or {})},
                channel_id=profile.channel_id,
            )
        else:
            key = profile.profile_url.lower().rstrip("/")
            if key in by_url:
                src = by_url[key]
                recent_titles, recent_urls = _merge_recent_posts(profile, src)
                enriched = PlatformCandidateProfile(
                    platform=profile.platform,
                    username=profile.username,
                    profile_url=profile.profile_url,
                    display_name=src.display_name or profile.display_name,
                    avatar_url=src.avatar_url or profile.avatar_url,
                    bio=src.bio or profile.bio,
                    followers_count=src.followers_count or profile.followers_count,
                    avg_views=profile.avg_views or src.avg_views,
                    avg_likes=profile.avg_likes,
                    avg_comments=profile.avg_comments,
                    engagement_rate=profile.engagement_rate or src.engagement_rate,
                    website=src.website or profile.website,
                    email=src.email or profile.email,
                    other_social_links=_merge_link_dicts(src.other_social_links, profile.other_social_links),
                    recent_post_titles=recent_titles,
                    recent_post_urls=recent_urls,
                    source_url=profile.source_url,
                    source_type=profile.source_type,
                    source_discovery_type=profile.source_discovery_type,
                    source_meta={**(profile.source_meta or {}), **(src.source_meta or {})},
                    channel_id=profile.channel_id or src.channel_id,
                )
        merged.append(enriched)
    return merged


def _api_budget_remaining(platform: str = "youtube") -> int | None:
    limit = settings.api_direct_max_requests_per_platform
    if limit <= 0:
        return None
    return max(0, limit - get_request_count(platform))


def _needs_subscriber_hydration(task: CollectionTask) -> bool:
    return task.min_followers_count is not None and task.min_followers_count > 0


def _youtube_keyword_search_cap(task: CollectionTask, keyword_count: int) -> int:
    target = target_qualified_count(task)
    desired = max(1, min(keyword_count, 2 + target // 2))
    remaining = _api_budget_remaining()
    if remaining is None:
        return desired
    return max(1, min(desired, max(1, remaining // 3)))


def _prioritize_youtube_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in sorted(keywords, key=lambda item: (len(item), item.lower())):
        clean = raw.strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(clean)
    return ordered


def _profile_passes_follower_gate(profile: PlatformCandidateProfile, task: CollectionTask) -> bool:
    required = task.min_followers_count
    if required is None:
        return True
    followers = profile.followers_count
    return followers is not None and followers >= required


def _rank_profiles_for_persist(
    profiles: list[PlatformCandidateProfile],
    task: CollectionTask,
    *,
    limit: int,
) -> list[PlatformCandidateProfile]:
    if not profiles:
        return profiles

    def sort_key(profile: PlatformCandidateProfile) -> tuple[int, int, int]:
        qualified = 1 if _profile_passes_follower_gate(profile, task) else 0
        has_followers = 1 if profile.followers_count is not None else 0
        followers = profile.followers_count or 0
        views = profile.avg_views or 0
        return (qualified, has_followers, max(followers, views))

    ranked = sorted(profiles, key=sort_key, reverse=True)
    return ranked[:limit]


async def _hydrate_subscriber_counts(
    profiles: list[PlatformCandidateProfile],
    task: CollectionTask,
    *,
    keyword_timeout: float,
) -> list[PlatformCandidateProfile]:
    if not _needs_subscriber_hydration(task):
        return profiles

    target = target_qualified_count(task)
    qualified = sum(1 for profile in profiles if _profile_passes_follower_gate(profile, task))
    if qualified >= target:
        return profiles

    pending = [
        profile
        for profile in profiles
        if profile.followers_count is None and (profile.display_name or profile.username)
    ]
    if not pending:
        return profiles

    pending.sort(key=lambda profile: profile.avg_views or 0, reverse=True)
    hydrate_cap = min(len(pending), max(target * 2, target + 4))
    remaining = _api_budget_remaining()
    if remaining is not None:
        hydrate_cap = min(hydrate_cap, remaining)
    if hydrate_cap <= 0:
        return profiles

    channel_profiles: list[PlatformCandidateProfile] = []
    hydrated_qualified = qualified

    for profile in pending[:hydrate_cap]:
        if hydrated_qualified >= target:
            break
        if _api_budget_remaining() == 0:
            break
        query = (profile.display_name or profile.username or "").strip()
        if len(query) < 2:
            continue
        try:
            channel_data = await _ad_get_timed(
                "/v1/youtube/channels",
                params={"query": query, "pages": 1},
                platform="youtube",
                timeout_seconds=keyword_timeout,
            )
        except ApiDirectError:
            continue
        for channel in channel_data.get("channels") or []:
            if not isinstance(channel, dict):
                continue
            enriched = _profile_from_channel(
                channel,
                source_keyword=(profile.source_meta or {}).get("source_keyword"),
                source_type="subscriber_hydration",
            )
            if not enriched:
                continue
            if profile.channel_id and enriched.channel_id and profile.channel_id != enriched.channel_id:
                continue
            channel_profiles.append(enriched)
            if _profile_passes_follower_gate(enriched, task):
                hydrated_qualified += 1
            break

    if not channel_profiles:
        return profiles
    return _merge_channel_details(profiles, dedupe_profiles(channel_profiles))


class YouTubeApiDirectProvider:
    platform = "youtube"

    @staticmethod
    def capability() -> PlatformCapability:
        if not settings.is_api_direct_configured:
            return PlatformCapability(
                platform="youtube",
                label="YouTube",
                status="not_configured",
                message="API Direct 暂未配置（缺少 API_DIRECT_API_KEY）",
                endpoints=ENDPOINTS,
            )
        return PlatformCapability(
            platform="youtube",
            label="YouTube",
            status="supported",
            message=_CAPABILITY_MESSAGE,
            endpoints=ENDPOINTS,
        )

    @staticmethod
    async def discover(
        task: CollectionTask,
        *,
        checkpoint: RunCheckpoint | None = None,
    ) -> PlatformDiscoveryResult:
        _ = checkpoint
        cap = YouTubeApiDirectProvider.capability()
        if cap.status == "not_configured":
            return PlatformDiscoveryResult(
                platform="youtube",
                fatal=True,
                skipped=True,
                skip_reason=cap.message,
                errors=[cap.message],
            )

        errors: list[str] = []
        raw_keywords = normalize_keywords([str(k) for k in (task.keywords or [])])
        keywords = _prioritize_youtube_keywords(raw_keywords)
        keyword_cap = _youtube_keyword_search_cap(task, len(keywords))
        if keyword_cap < len(keywords):
            errors.append(
                f"YouTube 为节省 API 额度，仅搜索前 {keyword_cap} 个关键词（跳过 {len(keywords) - keyword_cap} 个）"
            )
            keywords = keywords[:keyword_cap]
        input_urls = [u.strip() for u in (task.input_urls or []) if u and str(u).strip()]
        url_profiles = [_profile_from_input_url(u) for u in input_urls]
        url_profiles = [p for p in url_profiles if p]

        if not keywords and not url_profiles:
            msg = "YouTube 采集需要关键词或 YouTube 频道/视频链接"
            return PlatformDiscoveryResult(platform="youtube", errors=[msg], skip_reason=msg)

        limit = discovery_fetch_limit(task)
        pages = overfetch_pages_for_limit(limit)
        keyword_timeout = max(1, settings.youtube_discovery_keyword_timeout_seconds)
        if url_profiles:
            url_profiles = await _hydrate_url_import_video_profiles(
                url_profiles,
                errors=errors,
                keyword_timeout=keyword_timeout,
            )
        profiles: list[PlatformCandidateProfile] = list(url_profiles)
        channel_profiles: list[PlatformCandidateProfile] = []
        collected_posts: list[dict] = []
        rate_limit_count = 0
        slow_api = False
        discovery_started = time.perf_counter()
        deadline = _discovery_deadline()
        concurrency = _youtube_keyword_search_concurrency()

        await report_discovery_progress(
            phase=STAGE_DISCOVERY,
            discovered_count=len(profiles),
            deduped_count=len(profiles),
            profile_fetched_count=0,
            inserted_count=0,
            provider="api_direct",
            keywords_completed=0,
            keywords_total=len(keywords),
        )

        async def _search_keyword(
            keyword: str,
        ) -> tuple[str, list[PlatformCandidateProfile], list[PlatformCandidateProfile], list[dict], list[str], int, bool]:
            local_profiles: list[PlatformCandidateProfile] = []
            local_channels: list[PlatformCandidateProfile] = []
            local_posts: list[dict] = []
            local_errors: list[str] = []
            local_rate_limits = 0
            local_slow = False
            started = time.perf_counter()

            await report_discovery_progress(
                phase=STAGE_DISCOVERY,
                discovered_count=len(profiles),
                deduped_count=len(dedupe_profiles(profiles)),
                profile_fetched_count=0,
                provider="api_direct",
                current_keyword=keyword,
                keywords_total=len(keywords),
            )

            async def _fetch_keyword_data() -> None:
                nonlocal local_rate_limits, local_slow
                try:
                    channel_data = await _ad_get_timed(
                        "/v1/youtube/channels",
                        params={"query": keyword, "pages": pages},
                        platform="youtube",
                        timeout_seconds=keyword_timeout,
                    )
                    for ch in channel_data.get("channels") or []:
                        if isinstance(ch, dict):
                            p = _profile_from_channel(ch, source_keyword=keyword, source_type="keyword_channel")
                            if p:
                                local_channels.append(p)
                                local_profiles.append(p)
                except ApiDirectError as exc:
                    if "超时" in str(exc):
                        local_slow = True
                    if is_rate_limit_error(exc):
                        local_rate_limits += 1
                        local_errors.append(_rate_limit_message(keyword, "频道搜索"))
                        await asyncio.sleep(min(8.0, 2.0 * local_rate_limits))
                    else:
                        local_errors.append(f"YouTube 频道搜索「{keyword}」: {exc}")

                if len(local_profiles) < limit and (_api_budget_remaining() or 1) > 0:
                    try:
                        post_data = await _ad_get_timed(
                            "/v1/youtube/posts",
                            params={"query": keyword, "pages": pages},
                            platform="youtube",
                            timeout_seconds=keyword_timeout,
                        )
                        for post in post_data.get("posts") or []:
                            if not isinstance(post, dict):
                                continue
                            local_posts.append(post)
                            p = _profile_from_post(post, source_keyword=keyword)
                            if p:
                                local_profiles.append(p)
                            if len(local_profiles) >= limit:
                                break
                    except ApiDirectError as exc:
                        if "超时" in str(exc):
                            local_slow = True
                        if is_rate_limit_error(exc):
                            local_rate_limits += 1
                            local_errors.append(_rate_limit_message(keyword, "视频搜索"))
                            await asyncio.sleep(min(8.0, 2.0 * local_rate_limits))
                        else:
                            local_errors.append(f"YouTube 视频搜索「{keyword}」: {exc}")

            try:
                await asyncio.wait_for(_fetch_keyword_data(), timeout=keyword_timeout * 2 + 2)
            except asyncio.TimeoutError:
                local_slow = True
                local_errors.append(
                    f"YouTube API Direct 搜索「{keyword}」超时（>{keyword_timeout * 2}s），已跳过该关键词并继续"
                )
                logger.warning(
                    "YouTube API Direct keyword timeout keyword=%s elapsed=%.2fs",
                    keyword,
                    time.perf_counter() - started,
                )

            elapsed = time.perf_counter() - started
            logger.info(
                "YouTube API Direct keyword search keyword=%s elapsed=%.2fs profiles=%d rate_limits=%d",
                keyword,
                elapsed,
                len(local_profiles),
                local_rate_limits,
            )
            if not local_profiles and elapsed >= settings.youtube_discovery_slow_threshold_seconds:
                local_slow = True
                local_errors.append(
                    f"YouTube API Direct 搜索「{keyword}」耗时 {elapsed:.0f}s 但未返回候选，可能关键词无结果或平台响应慢"
                )
            return keyword, local_profiles, local_channels, local_posts, local_errors, local_rate_limits, local_slow

        keywords_completed = 0
        for chunk_start in range(0, len(keywords), concurrency):
            if time.perf_counter() >= deadline:
                slow_api = True
                errors.append(
                    f"YouTube 发现阶段总耗时超过 {settings.youtube_discovery_max_duration_seconds}s，"
                    f"已停止剩余 {len(keywords) - keywords_completed} 个关键词"
                )
                break
            if len(profiles) >= limit:
                break

            chunk = keywords[chunk_start : chunk_start + concurrency]
            await report_discovery_progress(
                phase=STAGE_DISCOVERY,
                discovered_count=len(profiles),
                deduped_count=len(dedupe_profiles(profiles)),
                profile_fetched_count=0,
                provider="api_direct",
                current_keyword=chunk[0],
                keywords_completed=keywords_completed,
                keywords_total=len(keywords),
            )

            outcomes = await map_bounded(chunk, _search_keyword, concurrency=len(chunk))
            for outcome in outcomes:
                keywords_completed += 1
                if isinstance(outcome, BaseException):
                    errors.append(str(outcome))
                    continue
                keyword, local_profiles, local_channels, local_posts, local_errors, local_rate_limits, local_slow = outcome
                rate_limit_count += local_rate_limits
                slow_api = slow_api or local_slow
                errors.extend(local_errors)
                channel_profiles.extend(local_channels)
                collected_posts.extend(local_posts)
                for profile in local_profiles:
                    if len(profiles) >= limit:
                        break
                    profiles.append(profile)
                await report_discovery_progress(
                    phase=STAGE_DISCOVERY,
                    discovered_count=len(profiles),
                    deduped_count=len(dedupe_profiles(profiles)),
                    profile_fetched_count=0,
                    rate_limited=rate_limit_count > 0,
                    slow_api=slow_api,
                    rate_limit_note=local_errors[-1] if local_rate_limits and local_errors else None,
                    provider="api_direct",
                    current_keyword=keyword,
                    keywords_completed=keywords_completed,
                    keywords_total=len(keywords),
                    timing_note=local_errors[-1] if local_errors else None,
                )
                if len(profiles) >= limit:
                    break

        snippet_links = _collect_snippet_links_by_channel(collected_posts)
        if snippet_links:
            profiles = [
                _append_links_to_profile(profile, snippet_links.get(profile.channel_id or "", []))
                for profile in profiles
            ]
            channel_profiles = [
                _append_links_to_profile(profile, snippet_links.get(profile.channel_id or "", []))
                for profile in channel_profiles
            ]

        deduped = dedupe_profiles(profiles)[:limit]
        if channel_profiles:
            deduped = _merge_channel_details(deduped, dedupe_profiles(channel_profiles))
        deduped = await _hydrate_subscriber_counts(deduped, task, keyword_timeout=keyword_timeout)
        deduped = _rank_profiles_for_persist(deduped, task, limit=limit)

        await report_discovery_progress(
            phase=STAGE_HYDRATION,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=0,
            rate_limited=rate_limit_count > 0,
            slow_api=slow_api,
            provider="api_direct",
            keywords_completed=keywords_completed,
            keywords_total=len(keywords),
        )
        deduped = await _hydrate_profiles_about(deduped)

        api_errors = [message for message in errors if "YouTube" in message and "About/更多外链" not in message]
        rate_limited = rate_limit_count > 0
        if rate_limited:
            errors.append(
                f"YouTube API Direct 限流 {rate_limit_count} 次；系统已降速重试，"
                f"已发现 {len(profiles)} 个候选，去重 {len(deduped)} 个，About/主页补采 {len(deduped)} 个"
            )
        if not deduped and not profiles:
            if rate_limited:
                empty_reason = "平台接口限流，暂无候选结果"
            elif slow_api or (time.perf_counter() - discovery_started) >= settings.youtube_discovery_slow_threshold_seconds:
                empty_reason = "API Direct 响应较慢或关键词暂无匹配结果"
            else:
                empty_reason = "关键词/API 暂无候选结果"
            errors.append(
                f"YouTube 发现阶段结束：{empty_reason}（共搜索 {keywords_completed}/{len(keywords)} 个关键词）"
            )
        missing_about = [
            profile.display_name or profile.username
            for profile in deduped
            if (profile.channel_id or profile.profile_url)
            and not (profile.source_meta or {}).get("about_links_hydrated")
        ]
        if missing_about and not rate_limited:
            sample = "、".join(missing_about[:3])
            suffix = f" 等 {len(missing_about)} 个" if len(missing_about) > 3 else ""
            errors.append(
                "YouTube About/更多外链：/v1/youtube/channels 不含该字段；"
                f"公开页补采未成功（{sample}{suffix}）。"
                "请确认服务器可访问 youtube.com 后重跑采集。"
            )

        await report_discovery_progress(
            phase=STAGE_DISCOVERY,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=len(deduped),
            rate_limited=rate_limited,
            slow_api=slow_api,
            rate_limit_note=errors[-1] if rate_limited and errors else None,
            provider="api_direct",
            keywords_completed=keywords_completed,
            keywords_total=len(keywords),
        )

        items = [profile_to_collected(p) for p in deduped]
        logger.info(
            "YouTube API Direct discover finished elapsed=%.2fs discovered=%d deduped=%d errors=%d",
            time.perf_counter() - discovery_started,
            len(profiles),
            len(deduped),
            len(errors),
        )

        return PlatformDiscoveryResult(
            platform="youtube",
            items=items,
            profiles=deduped,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=len(deduped),
            api_requests=get_request_count("youtube"),
            errors=errors,
            rate_limited=rate_limited,
            rate_limit_count=rate_limit_count,
            fatal=bool(api_errors) and not deduped and not rate_limited and not slow_api,
        )
