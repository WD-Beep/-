# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：url parser
"""红人主页 / 商品链接解析与平台识别。"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from app.services.amazon_url import is_amazon_product_url, parse_amazon_product_url
from app.services.link_import_url import parse_import_link
from app.services.platform_providers.url_only import CONFIGS, PARSERS
from app.services.platform_types import PlatformCandidateProfile

SUPPORTED_PLATFORMS = (
    "instagram",
    "youtube",
    "tiktok",
    "facebook",
    "pinterest",
    "ltk",
    "shopmy",
    "amazon",
)

PLATFORM_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("instagram", re.compile(r"instagram\.com", re.I)),
    ("youtube", re.compile(r"(youtube\.com|youtu\.be)", re.I)),
    ("tiktok", re.compile(r"tiktok\.com", re.I)),
    ("facebook", re.compile(r"(facebook\.com|fb\.com|fb\.me)", re.I)),
]

TIKTOK_PROFILE_RE = re.compile(
    r"tiktok\.com/@(?P<handle>[A-Za-z0-9_.-]{2,80})(?:/|$|\?)",
    re.I,
)
YOUTUBE_CHANNEL_RE = re.compile(
    r"(?:youtube\.com/(?:channel/(?P<channel_id>UC[\w-]{10,})|@(?P<handle>[\w.-]+))|youtu\.be/)",
    re.I,
)

PLATFORM_INVALID_HINTS: dict[str, str] = {
    "instagram": "Instagram 主页/帖子/Reel 链接",
    "youtube": "YouTube 频道/视频链接",
    "tiktok": "TikTok 主页/视频链接",
    "facebook": "Facebook 主页/帖子链接",
    "pinterest": "Pinterest 主页/Pin 链接",
    "ltk": "LTK 创作者/商品链接",
    "shopmy": "ShopMy 创作者/商品链接",
    "amazon": "Amazon 商品链接（/dp、/gp/product、/product）",
}


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


def _is_tiktok_profile_url(url: str) -> bool:
    return bool(TIKTOK_PROFILE_RE.search(url.lower()))


def _is_youtube_channel_url(url: str) -> bool:
    return bool(YOUTUBE_CHANNEL_RE.search(url.lower()))


def detect_platform(url: str) -> str | None:
    normalized = normalize_url(url)
    if not normalized:
        return None
    if is_amazon_product_url(normalized):
        return "amazon"
    parsed = parse_import_link(normalized)
    if parsed is not None:
        return parsed.platform
    host_path = normalized.lower()
    for platform, parser in PARSERS.items():
        if parser(normalized):
            return platform
    return None


def supported_platform_hint() -> str:
    parts = [PLATFORM_INVALID_HINTS[name] for name in SUPPORTED_PLATFORMS if name in PLATFORM_INVALID_HINTS]
    return "；".join(parts)


def split_link_import_entries(valid: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    amazon_entries = [entry for entry in valid if entry.get("platform") == "amazon"]
    profile_entries = [entry for entry in valid if entry.get("platform") != "amazon"]
    return amazon_entries, profile_entries


def validate_link_import_url_lines(urls: list[str]) -> list[dict[str, str]]:
    """Parse link-import URLs and reject invalid lines or Amazon/profile mixes."""
    cleaned = [u.strip() for u in urls if u and str(u).strip()]
    if not cleaned:
        raise ValueError("链接导入至少需要一个链接")
    valid, invalid = parse_raw_urls("\n".join(cleaned))
    if invalid:
        raise ValueError(
            invalid[0]
            if len(invalid) == 1
            else f"有 {len(invalid)} 条链接无效：{invalid[0]}"
        )
    if not valid:
        raise ValueError("未识别到任何有效链接")
    amazon_entries, profile_entries = split_link_import_entries(valid)
    if amazon_entries and profile_entries:
        raise ValueError("Amazon 商品链接与红人主页链接请分任务提交")
    return valid


def parse_raw_urls(raw: str) -> tuple[list[dict[str, str]], list[str]]:
    """解析多行链接，返回 ([{url, platform, ...}, ...], [invalid_line, ...])。"""
    valid: list[dict[str, str]] = []
    invalid: list[str] = []
    seen: set[tuple[str, str]] = set()

    for line_no, line in enumerate(raw.splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        line_prefix = f"第 {line_no} 行"

        if is_amazon_product_url(text):
            seed = parse_amazon_product_url(text)
            if not seed:
                invalid.append(f"{line_prefix}: {text}（无法解析 Amazon 商品 ASIN）")
                continue
            key = ("amazon", seed["normalized_url"])
            if key in seen:
                continue
            seen.add(key)
            valid.append(seed)
            continue

        platform = detect_platform(text)
        if not platform:
            invalid.append(
                f"{line_prefix}: {text}（无法识别平台，当前支持：{supported_platform_hint()}）"
            )
            continue

        url = normalize_url(text)
        parsed = parse_import_link(url)
        entry: dict[str, str | None] = {"url": url, "platform": platform}
        if parsed is not None:
            entry.update(
                {
                    "link_type": parsed.link_type,
                    "profile_url": parsed.profile_url,
                    "source_post_url": parsed.source_post_url,
                    "username": parsed.username,
                }
            )
        elif platform in PARSERS and PARSERS[platform](url) is None:
            if platform in PLATFORM_INVALID_HINTS:
                hint = PLATFORM_INVALID_HINTS[platform]
            elif platform in CONFIGS:
                hint = CONFIGS[platform].message
            else:
                hint = platform
            invalid.append(f"{line_prefix}: {text}（不符合 {hint} 格式）")
            continue
        elif platform in PARSERS:
            profile = PARSERS[platform](url)
            if profile is not None:
                entry["link_type"] = profile.source_meta.get("link_type", "profile")
                entry["profile_url"] = profile.profile_url
                entry["source_post_url"] = profile.source_post_url or profile.source_meta.get("source_post_url")
                entry["username"] = profile.username

        key = (platform, url)
        if key in seen:
            continue
        seen.add(key)
        valid.append(entry)

    return valid, invalid


def tiktok_profile_from_url(url: str) -> PlatformCandidateProfile | None:
    parsed = parse_import_link(normalize_url(url))
    if parsed is None or parsed.platform != "tiktok":
        return None
    if not parsed.profile_url and not parsed.username:
        if parsed.link_type in {"post", "short"}:
            post_url = parsed.source_post_url or parsed.url
            return PlatformCandidateProfile(
                platform="tiktok",
                username="pending",
                profile_url=post_url,
                source_url=parsed.url,
                source_post_url=post_url,
                source_type="input_url",
                source_discovery_type="url_import",
                source_meta={
                    "input_url": url,
                    "link_type": parsed.link_type,
                    "profile_hydration": "url_only_pending",
                },
            )
        return None
    handle = parsed.username or "unknown"
    profile_url = parsed.profile_url or f"https://www.tiktok.com/@{handle}"
    post_url = parsed.source_post_url if parsed.link_type in {"post", "short"} else None
    return PlatformCandidateProfile(
        platform="tiktok",
        username=handle,
        profile_url=profile_url,
        source_url=parsed.url,
        source_post_url=post_url,
        source_type="input_url",
        source_discovery_type="url_import",
        source_meta={
            "input_url": url,
            "link_type": parsed.link_type,
            "profile_hydration": "url_only_pending",
        },
    )


def summarize_link_import_urls(raw: str) -> dict[str, int | list[str] | bool]:
    """统计链接导入预览：各平台数量、无效行、是否混合 Amazon 与红人链接。"""
    valid, invalid = parse_raw_urls(raw)
    amazon_entries, profile_entries = split_link_import_entries(valid)
    counts = Counter(entry.get("platform", "unknown") for entry in valid)
    return {
        "counts": dict(counts),
        "invalid_count": len(invalid),
        "invalid_lines": invalid,
        "valid_count": len(valid),
        "has_amazon": bool(amazon_entries),
        "has_profiles": bool(profile_entries),
        "mixed_amazon_and_profiles": bool(amazon_entries and profile_entries),
    }
