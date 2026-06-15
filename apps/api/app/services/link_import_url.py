"""链接导入 URL 解析：区分主页 / 作品 / 短链，保留 source_post_url。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx

from app.services.instagram_comment_discovery import classify_instagram_input_url
from app.services.instagram_urls import normalize_instagram_post_url, normalize_instagram_profile_url, sanitize_url_text


def normalize_url(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if not re.match(r"^https?://", text, re.I):
        text = f"https://{text}"
    parsed = urlparse(text)
    if not parsed.netloc:
        return text
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}{query}"

LinkType = Literal["profile", "post", "pin", "product", "short"]

TIKTOK_VIDEO_RE = re.compile(
    r"tiktok\.com/@(?P<handle>[A-Za-z0-9_.-]{2,80})/video/(?P<vid>\d+)",
    re.I,
)
TIKTOK_PROFILE_RE = re.compile(
    r"tiktok\.com/@(?P<handle>[A-Za-z0-9_.-]{2,80})(?:/|$|\?)",
    re.I,
)
TIKTOK_RESERVED_PATHS = frozenset(
    {"discover", "explore", "foryou", "following", "live", "upload", "search", "about", "legal"}
)
YOUTUBE_VIDEO_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?.*v=|shorts/|embed/)|youtu\.be/)(?P<id>[\w-]{6,})",
    re.I,
)
YOUTUBE_CHANNEL_RE = re.compile(
    r"youtube\.com/(?:channel/(?P<channel_id>UC[\w-]{10,})|@(?P<handle>[\w.-]+))",
    re.I,
)
FACEBOOK_POST_RE = re.compile(
    r"facebook\.com/(?:[^/]+/)?(?:posts|videos|reel|watch|photo\.php|story\.php|permalink\.php)",
    re.I,
)
LTK_PROFILE_RE = re.compile(r"shopltk\.com/explore/(?P<handle>[A-Za-z0-9_.-]{2,80})", re.I)


@dataclass(frozen=True)
class ParsedImportLink:
    url: str
    platform: str
    link_type: LinkType
    profile_url: str | None
    source_post_url: str | None
    username: str | None


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def _is_tiktok_short(url: str) -> bool:
    host = _host(url)
    return any(host == marker or host.endswith(f".{marker}") for marker in ("vm.tiktok.com", "vt.tiktok.com"))


def _parse_tiktok(url: str) -> ParsedImportLink | None:
    text = normalize_url(url)
    lower = text.lower()
    if "tiktok.com" not in lower and not _is_tiktok_short(text):
        return None
    if _is_tiktok_short(text):
        return ParsedImportLink(
            url=text,
            platform="tiktok",
            link_type="short",
            profile_url=None,
            source_post_url=text,
            username=None,
        )
    segments = [part for part in urlparse(text).path.split("/") if part]
    if segments and segments[0].lower() in TIKTOK_RESERVED_PATHS:
        return None
    video = TIKTOK_VIDEO_RE.search(text)
    if video:
        handle = video.group("handle")
        profile = f"https://www.tiktok.com/@{handle}"
        return ParsedImportLink(
            url=text,
            platform="tiktok",
            link_type="post",
            profile_url=profile,
            source_post_url=text,
            username=handle,
        )
    profile_match = TIKTOK_PROFILE_RE.search(text)
    if profile_match:
        handle = profile_match.group("handle")
        profile = f"https://www.tiktok.com/@{handle}"
        return ParsedImportLink(
            url=text,
            platform="tiktok",
            link_type="profile",
            profile_url=profile,
            source_post_url=None,
            username=handle,
        )
    return None


def _parse_youtube(url: str) -> ParsedImportLink | None:
    text = normalize_url(url)
    lower = text.lower()
    if "youtube.com" not in lower and "youtu.be" not in lower:
        return None
    if YOUTUBE_VIDEO_RE.search(text):
        channel = YOUTUBE_CHANNEL_RE.search(text)
        profile_url = None
        username = None
        if channel:
            if channel.group("channel_id"):
                profile_url = f"https://www.youtube.com/channel/{channel.group('channel_id')}"
                username = channel.group("channel_id")
            elif channel.group("handle"):
                profile_url = f"https://www.youtube.com/@{channel.group('handle')}"
                username = channel.group("handle")
        return ParsedImportLink(
            url=text,
            platform="youtube",
            link_type="post",
            profile_url=profile_url,
            source_post_url=text,
            username=username,
        )
    channel = YOUTUBE_CHANNEL_RE.search(text)
    if channel:
        if channel.group("channel_id"):
            cid = channel.group("channel_id")
            return ParsedImportLink(
                url=text,
                platform="youtube",
                link_type="profile",
                profile_url=f"https://www.youtube.com/channel/{cid}",
                source_post_url=None,
                username=cid,
            )
        handle = channel.group("handle")
        return ParsedImportLink(
            url=text,
            platform="youtube",
            link_type="profile",
            profile_url=f"https://www.youtube.com/@{handle}",
            source_post_url=None,
            username=handle,
        )
    return None


def _parse_instagram(url: str) -> ParsedImportLink | None:
    text = sanitize_url_text(url)
    if "instagram.com" not in text.lower():
        return None
    kind = classify_instagram_input_url(text)
    if kind == "post":
        post = normalize_instagram_post_url(text) or text
        return ParsedImportLink(
            url=normalize_url(text),
            platform="instagram",
            link_type="post",
            profile_url=None,
            source_post_url=post,
            username=None,
        )
    if kind == "profile":
        profile = normalize_instagram_profile_url(text)
        if not profile:
            return None
        username = profile.rstrip("/").split("/")[-1]
        return ParsedImportLink(
            url=normalize_url(text),
            platform="instagram",
            link_type="profile",
            profile_url=profile,
            source_post_url=None,
            username=username,
        )
    return None


def _parse_facebook(url: str) -> ParsedImportLink | None:
    text = normalize_url(url)
    lower = text.lower()
    if not any(token in lower for token in ("facebook.com", "fb.com", "fb.me")):
        return None
    if FACEBOOK_POST_RE.search(lower) or "/share/" in lower or "story.php" in lower:
        return ParsedImportLink(
            url=text,
            platform="facebook",
            link_type="post",
            profile_url=None,
            source_post_url=text,
            username=None,
        )
    return ParsedImportLink(
        url=text,
        platform="facebook",
        link_type="profile",
        profile_url=text,
        source_post_url=None,
        username=None,
    )


def parse_import_link(raw: str) -> ParsedImportLink | None:
    text = (raw or "").strip()
    if not text:
        return None
    for parser in (_parse_tiktok, _parse_youtube, _parse_instagram, _parse_facebook):
        parsed = parser(text)
        if parsed is not None:
            return parsed
    return None


def parsed_to_valid_entry(parsed: ParsedImportLink) -> dict[str, str | None]:
    return {
        "url": parsed.url,
        "platform": parsed.platform,
        "link_type": parsed.link_type,
        "profile_url": parsed.profile_url,
        "source_post_url": parsed.source_post_url,
        "username": parsed.username,
    }


async def resolve_redirect_url(raw: str, *, timeout: float = 8.0) -> str:
    text = normalize_url(raw)
    if not text:
        return raw.strip()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; InfluencerIntel/1.0)"},
        ) as client:
            response = await client.head(text)
            if response.status_code >= 400:
                response = await client.get(text)
            final = str(response.url)
            return normalize_url(final) if final else text
    except Exception:
        return text


async def resolve_import_link(raw: str) -> ParsedImportLink | None:
    resolved = await resolve_redirect_url(raw)
    parsed = parse_import_link(resolved)
    if parsed is not None:
        if parsed.url != normalize_url(raw) and parsed.link_type == "short":
            reparsed = parse_import_link(resolved)
            if reparsed is not None:
                return ParsedImportLink(
                    url=normalize_url(raw),
                    platform=reparsed.platform,
                    link_type=reparsed.link_type,
                    profile_url=reparsed.profile_url,
                    source_post_url=reparsed.source_post_url or normalize_url(resolved),
                    username=reparsed.username,
                )
        return parsed
    return None
