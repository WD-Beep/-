"""Runtime keyword expansion for Instagram discovery."""

from __future__ import annotations

import re

# Common travel / lifestyle suffixes kept for one-word seeds.
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

_PRODUCT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "makeup bag": ("cosmetic bag", "toiletry bag", "makeup pouch", "cosmetic pouch"),
    "cosmetic bag": ("makeup bag", "toiletry bag", "cosmetic pouch"),
    "toiletry bag": ("travel toiletry bag", "toiletry pouch"),
    "makeup organizer": ("cosmetic organizer", "makeup storage"),
    "travel essentials": ("packing tips", "carry on essentials"),
}


def _normalize_phrase(keyword: str) -> str:
    text = str(keyword or "").strip().lower().lstrip("#")
    text = re.sub(r"[^a-z0-9_#\s-]+", " ", text)
    text = re.sub(r"[\s_-]+", " ", text)
    return text.strip()


def _normalize_hashtag(keyword: str) -> str:
    text = str(keyword or "").strip().lower().lstrip("#")
    text = re.sub(r"[^a-z0-9_]+", "", text)
    return text


def _words(phrase: str) -> list[str]:
    return [word for word in phrase.split() if word]


def _adjacent_phrases(words: list[str]) -> list[str]:
    if len(words) < 2 or len(words) > 4:
        return []
    phrases: list[str] = []
    for size in range(2, len(words)):
        for start in range(0, len(words) - size + 1):
            phrases.append(" ".join(words[start : start + size]))
    if len(words) == 2:
        phrases.append(" ".join(words))
    return phrases


def expand_keywords_to_hashtags(
    keywords: list[str],
    *,
    max_hashtags: int = 12,
) -> list[str]:
    """Expand task keywords into ordered Instagram discovery terms.

    The function is intentionally runtime-only: callers should use the returned
    list for discovery without mutating CollectionTask.keywords.
    """
    expanded: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        clean = _normalize_phrase(term)
        if not clean or len(clean.replace(" ", "")) < 2:
            return
        key = clean.lower()
        if key in seen:
            return
        seen.add(key)
        expanded.append(clean)

    def add_hashtag(term: str) -> None:
        clean = _normalize_hashtag(term)
        if not clean or len(clean) < 2:
            return
        if clean in seen:
            return
        seen.add(clean)
        expanded.append(clean)

    def add_synonyms_for(term: str) -> None:
        clean = _normalize_phrase(term)
        for synonym in _PRODUCT_SYNONYMS.get(clean, ()):
            add(synonym)

    for raw in keywords:
        phrase = _normalize_phrase(raw)
        if not phrase:
            continue
        words = _words(phrase)

        add(phrase)
        if len(words) > 1:
            add_hashtag(phrase)
            adjacent = _adjacent_phrases(words)
            for item in adjacent:
                add(item)
            for item in adjacent:
                add_hashtag(item)
            add_synonyms_for(phrase)
            for item in adjacent:
                add_synonyms_for(item)
        else:
            seed = _normalize_hashtag(phrase)
            for suffix in _HASHTAG_SUFFIXES:
                add_hashtag(f"{seed}{suffix}")
            for prefix in _DOMAIN_PREFIXES:
                add_hashtag(f"{prefix}{seed}")

    return expanded[: max(0, max_hashtags)]
