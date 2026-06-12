"""将任务关键词扩展为 hashtag 列表（用于真实 API 发现）。"""

from __future__ import annotations

import re

# 常见 travel / lifestyle 等后缀，可按种子词组合
_HASHTAG_SUFFIXES = (
    "",
    "gram",
    "blogger",
    "blog",
    "life",
    "lover",
    "addict",
    "daily",
    "vibes",
    "photography",
    "photo",
    "pics",
    "reels",
    "tiktok",
    "influencer",
    "creator",
    "community",
    "guide",
    "tips",
    "hacks",
    "gear",
    "essentials",
    "musthaves",
    "finds",
    "deals",
)

# 领域修饰词（与种子词组合）
_DOMAIN_PREFIXES = (
    "luxury",
    "solo",
    "budget",
    "family",
    "adventure",
    "digital",
    "nomad",
    "backpack",
    "weekend",
    "amazon",
)


def _normalize_seed(keyword: str) -> str:
    text = keyword.strip().lower().lstrip("#")
    text = re.sub(r"[^a-z0-9_]+", "", text)
    return text


def expand_keywords_to_hashtags(
    keywords: list[str],
    *,
    max_hashtags: int = 12,
) -> list[str]:
    """关键词 → hashtag 列表，例如 travel → travel, travelgram, travelblogger…"""
    seeds: list[str] = []
    for raw in keywords:
        seed = _normalize_seed(raw)
        if seed and len(seed) >= 2 and seed not in seeds:
            seeds.append(seed)

    if not seeds:
        return []

    expanded: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        clean = _normalize_seed(tag)
        if not clean or len(clean) < 2 or clean in seen:
            return
        seen.add(clean)
        expanded.append(clean)

    for seed in seeds:
        add(seed)
        for suffix in _HASHTAG_SUFFIXES:
            if suffix:
                add(f"{seed}{suffix}")
        for prefix in _DOMAIN_PREFIXES:
            add(f"{prefix}{seed}")

    return expanded[:max_hashtags]
