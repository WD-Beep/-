"""红人主页链接解析与平台识别。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

SUPPORTED_PLATFORMS = ("instagram",)

PLATFORM_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("instagram", re.compile(r"instagram\.com", re.I)),
]


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


def detect_platform(url: str) -> str | None:
    normalized = normalize_url(url)
    if not normalized:
        return None
    host_path = normalized.lower()
    for platform, pattern in PLATFORM_RULES:
        if pattern.search(host_path):
            return platform
    return None


def parse_raw_urls(raw: str) -> tuple[list[dict[str, str]], list[str]]:
    """解析多行链接，返回 ([{url, platform}, ...], [invalid_line, ...])。"""
    valid: list[dict[str, str]] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue

        platform = detect_platform(text)
        if not platform:
            invalid.append(f"{text}（当前仅支持 Instagram 主页链接）")
            continue

        url = normalize_url(text)
        key = (platform, url)
        if key in seen:
            continue
        seen.add(key)
        valid.append({"url": url, "platform": platform})

    return valid, invalid
