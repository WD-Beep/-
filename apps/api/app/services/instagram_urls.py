"""Instagram 链接清洗、规范化与校验（入库与 API 输出统一使用）。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._]{1,30}$")
RESERVED_USERNAMES = frozenset(
    {
        "p",
        "reel",
        "reels",
        "explore",
        "accounts",
        "stories",
        "tv",
        "about",
        "legal",
        "direct",
        "nametag",
    }
)

INSTAGRAM_HOST_MARKERS = ("instagram.com",)
RESERVED_PATH_SEGMENTS = frozenset(
    {"p", "reel", "reels", "tv", "explore", "stories", "accounts", "tags", "direct", "about"}
)
POST_PATH_RE = re.compile(r"instagram\.com/(p|reel|reels|tv)/([^/?#]+)", re.I)
PROFILE_PATH_RE = re.compile(r"instagram\.com/([^/?#]+)/?", re.I)

_FULLWIDTH_MAP = str.maketrans(
    {
        "：": ":",
        "／": "/",
        "．": ".",
        "　": " ",
    }
)


def is_valid_instagram_username(username: str | None) -> bool:
    if not username:
        return False
    value = username.strip().lstrip("@").lower()
    if not value or value in RESERVED_USERNAMES:
        return False
    return bool(USERNAME_RE.match(value))


def _clean_text(raw: str | None) -> str:
    if raw is None:
        return ""
    text = str(raw).strip().translate(_FULLWIDTH_MAP)
    if not text or text.lower() in {"undefined", "null", "none", "nan"}:
        return ""
    return text


def sanitize_url_text(raw: str | None) -> str:
    """去除空白与非法前缀，补全 https://。"""
    text = _clean_text(raw)
    if not text:
        return ""
    if not re.match(r"^https?://", text, re.I):
        text = f"https://{text.lstrip('/')}"
    return text


def _instagram_path_segments(url: str) -> list[str]:
    parsed = urlparse(sanitize_url_text(url))
    host = (parsed.netloc or "").lower()
    if not any(marker in host for marker in INSTAGRAM_HOST_MARKERS):
        return []
    return [part for part in parsed.path.strip("/").split("/") if part]


def extract_profile_username(url_or_username: str | None) -> str | None:
    text = _clean_text(url_or_username)
    if not text:
        return None
    if "instagram.com" not in text.lower():
        stripped = text.strip()
        if " " in stripped and not stripped.startswith("@"):
            return None
        candidate = stripped.lstrip("@").split()[0]
        return candidate if is_valid_instagram_username(candidate) else None
    segments = _instagram_path_segments(text)
    if not segments or segments[0].lower() in RESERVED_PATH_SEGMENTS:
        return None
    username = segments[0].lstrip("@")
    return username if is_valid_instagram_username(username) else None


def is_instagram_post_url(url: str | None) -> bool:
    text = sanitize_url_text(url)
    return bool(text and POST_PATH_RE.search(text))


def is_instagram_profile_url(url: str | None) -> bool:
    username = extract_profile_username(url)
    return username is not None


def normalize_instagram_profile_url(value: str | None, *, username: str | None = None) -> str | None:
    """规范为 https://www.instagram.com/{username}/"""
    uname = extract_profile_username(username) if username else None
    if not uname and value:
        uname = extract_profile_username(value)
    if not uname:
        return None
    return f"https://www.instagram.com/{uname}/"


def normalize_instagram_post_url(value: str | None, raw: dict | None = None) -> str | None:
    """规范为 https://www.instagram.com/p|reel/{shortcode}/"""
    if raw:
        shortcode = raw.get("shortCode") or raw.get("shortcode") or raw.get("code")
        if shortcode:
            code = str(shortcode).strip()
            post_type = str(raw.get("type") or raw.get("productType") or raw.get("mediaType") or "").lower()
            segment = "reel" if any(token in post_type for token in ("reel", "clips", "video")) else "p"
            return f"https://www.instagram.com/{segment}/{code}/"

    text = sanitize_url_text(value)
    if not text:
        return None

    match = POST_PATH_RE.search(text)
    if match:
        segment = "reel" if match.group(1).lower() in {"reel", "reels"} else match.group(1).lower()
        if segment == "reels":
            segment = "reel"
        return f"https://www.instagram.com/{segment}/{match.group(2)}/"

    # 拒绝把主页、hashtag、纯用户名当作帖子链接
    if is_instagram_profile_url(text):
        return None
    return None


def profile_url_from_apify_raw(raw: dict) -> str | None:
    """从 Apify 字段提取主页 URL，避免把帖子 url/inputUrl 误当主页。"""
    if not isinstance(raw, dict):
        return None

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
            url = normalize_instagram_profile_url(value)
            if url:
                return url

    for key in ("owner", "author", "user", "profile", "commenter"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            url = profile_url_from_apify_raw(nested)
            if url:
                return url

    for key in (
        "ownerUrl",
        "ownerProfileUrl",
        "owner_profile_url",
        "profileUrl",
        "profile_url",
        "authorUrl",
        "authorProfileUrl",
        "userUrl",
        "userProfileUrl",
    ):
        value = raw.get(key)
        if isinstance(value, str):
            url = normalize_instagram_profile_url(value)
            if url:
                return url

    for key in ("url", "inputUrl"):
        generic = raw.get(key)
        if isinstance(generic, str) and is_instagram_profile_url(generic):
            return normalize_instagram_profile_url(generic)

    deep = _deep_profile_url_from_apify_raw(raw)
    if deep:
        return deep

    return None


def _deep_profile_url_from_apify_raw(raw: dict) -> str | None:
    """Best-effort fallback for provider payloads with author data nested under raw nodes."""
    author_keys = {"owner", "author", "user", "profile"}
    url_keys = {
        "ownerUrl",
        "ownerProfileUrl",
        "owner_profile_url",
        "profileUrl",
        "profile_url",
        "authorUrl",
        "authorProfileUrl",
        "userUrl",
        "userProfileUrl",
    }
    username_keys = {
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
    }
    skip_keys = {
        "comments",
        "latestComments",
        "edge_media_to_comment",
        "edge_threaded_comments",
        "commenter",
    }

    def scan_author_dict(value: dict, depth: int) -> str | None:
        if depth > 6:
            return None
        for key in url_keys:
            candidate = value.get(key)
            if isinstance(candidate, str):
                url = normalize_instagram_profile_url(candidate)
                if url:
                    return url
        for key in username_keys:
            candidate = value.get(key)
            if isinstance(candidate, str):
                url = normalize_instagram_profile_url(candidate)
                if url:
                    return url
        generic = value.get("url")
        if isinstance(generic, str) and is_instagram_profile_url(generic):
            return normalize_instagram_profile_url(generic)
        for key in author_keys:
            nested = value.get(key)
            if isinstance(nested, dict):
                url = scan_author_dict(nested, depth + 1)
                if url:
                    return url
            elif isinstance(nested, str):
                url = normalize_instagram_profile_url(nested)
                if url:
                    return url
        return None

    def walk(value, depth: int = 0) -> str | None:
        if depth > 6:
            return None
        if isinstance(value, dict):
            url = scan_author_dict(value, depth)
            if url:
                return url
            for key, nested in value.items():
                if key in skip_keys:
                    continue
                url = walk(nested, depth + 1)
                if url:
                    return url
        elif isinstance(value, list):
            for nested in value[:12]:
                url = walk(nested, depth + 1)
                if url:
                    return url
        return None

    return walk(raw)


def post_url_from_apify_raw(raw: dict) -> str | None:
    for key in ("postUrl", "post_url"):
        value = raw.get(key)
        if isinstance(value, str):
            url = normalize_instagram_post_url(value, raw)
            if url:
                return url

    url = normalize_instagram_post_url(raw.get("url") if isinstance(raw.get("url"), str) else None, raw)
    if url:
        return url

    input_url = raw.get("inputUrl")
    if isinstance(input_url, str) and is_instagram_post_url(input_url):
        return normalize_instagram_post_url(input_url, raw)

    return None
