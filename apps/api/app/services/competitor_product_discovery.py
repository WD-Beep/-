"""竞品商品红人发现：解析 Amazon 输入 → IG hashtag 搜索 → caption 匹配。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from app.models.collection_task import CollectionTask
from app.services.apify_instagram import PostAuthorCandidate
from app.services.keyword_discovery import (
    KeywordDiscoveryMeta,
    discover_candidates_from_keywords,
)

logger = logging.getLogger(__name__)

AMAZON_URL_ASIN_RE = re.compile(
    r"(?:amazon\.[a-z.]+/(?:[^/]+/)?(?:dp|gp/product|product)/|asin=)([A-Z0-9]{10})",
    re.I,
)
STANDALONE_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$", re.I)
AMAZON_HOST_RE = re.compile(r"amazon\.[a-z.]+", re.I)

DEFAULT_AMAZON_HASHTAGS = (
    "amazonfinds",
    "amazonmusthaves",
    "amazonhome",
    "founditonamazon",
    "amazonfavorites",
)

CATEGORY_HASHTAGS: dict[str, tuple[str, ...]] = {
    "beauty": ("beautyfinds", "makeupfinds"),
    "美妆": ("beautyfinds", "makeupfinds"),
    "home": ("homefinds", "homedecor"),
    "家居": ("homefinds", "homedecor"),
    "kitchen": ("kitchenfinds", "kitchengadgets"),
    "厨房": ("kitchenfinds", "kitchengadgets"),
    "tech": ("techfinds", "gadgetfinds"),
    "科技": ("techfinds", "gadgetfinds"),
    "travel": ("travelgear", "travelfinds"),
    "旅行": ("travelgear", "travelfinds"),
    "fitness": ("fitnessfinds", "workoutgear"),
    "健身": ("fitnessfinds", "workoutgear"),
    "baby": ("babyfinds", "momfinds"),
    "母婴": ("babyfinds", "momfinds"),
    "pet": ("petfinds", "dogfinds"),
    "宠物": ("petfinds", "dogfinds"),
}

COMMERCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Amazon 提及",
        re.compile(
            r"\bamazon\b|amazonfinds|amazonmusthaves|amazonhome|founditonamazon|amazonfavorites|amzn\.to|a\.co/|geni\.us",
            re.I,
        ),
    ),
    ("LTK / Shop", re.compile(r"\bltk\b|liketoknow|shop my|storefront|link in bio", re.I)),
)

COLLAB_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("广告合作词", re.compile(r"\b(ad|sponsored|gifted|collab|partnership)\b|#ad\b|paid partnership", re.I)),
)


@dataclass
class CompetitorProductInfo:
    asin: str | None = None
    brand: str | None = None
    product_title: str | None = None
    core_keywords: list[str] = field(default_factory=list)
    amazon_urls: list[str] = field(default_factory=list)
    search_keywords: list[str] = field(default_factory=list)
    search_hashtags: list[str] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)


@dataclass
class CaptionMatchResult:
    matched: bool = False
    matched_keywords: list[str] = field(default_factory=list)
    match_reasons: list[str] = field(default_factory=list)
    suspected_collab: bool = False
    low_confidence: bool = False


@dataclass
class CompetitorProductDiscoveryMeta:
    product_info: CompetitorProductInfo
    posts_scanned: int = 0
    authors_before_filter: int = 0
    authors_matched: int = 0


@dataclass
class CompetitorProductDiscoveryResult:
    candidates: list[PostAuthorCandidate] = field(default_factory=list)
    raw_candidates: list[PostAuthorCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    meta: KeywordDiscoveryMeta | None = None
    competitor_meta: CompetitorProductDiscoveryMeta | None = None
    hashtag_api_all_failed: bool = False
    all_discovery_apis_failed: bool = False


def extract_asin_from_text(text: str) -> str | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    match = AMAZON_URL_ASIN_RE.search(cleaned)
    if match:
        return match.group(1).upper()
    if STANDALONE_ASIN_RE.match(cleaned):
        return cleaned.upper()
    return None


def is_amazon_url(text: str) -> bool:
    return bool(AMAZON_HOST_RE.search(text or ""))


def _normalize_hashtag(value: str) -> str:
    text = (value or "").strip().lower().lstrip("#")
    return re.sub(r"[^a-z0-9_]+", "", text)


def _tokenize_keywords(text: str) -> list[str]:
    parts = re.split(r"[\s,，/|]+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def parse_competitor_product_inputs(task: CollectionTask) -> CompetitorProductInfo:
    """从任务 input_urls / keywords / category 解析竞品商品搜索上下文。"""
    info = CompetitorProductInfo()
    seen_keywords: set[str] = set()
    seen_hashtags: set[str] = set()
    keywords: list[str] = []
    hashtags: list[str] = []

    def add_keyword(raw: str) -> None:
        for token in _tokenize_keywords(raw):
            key = token.lower()
            asin = extract_asin_from_text(token)
            if asin:
                info.asin = info.asin or asin
                if asin not in seen_keywords:
                    seen_keywords.add(asin)
                    keywords.append(asin)
                continue
            if key in seen_keywords or len(token) < 2:
                return
            seen_keywords.add(key)
            keywords.append(token)

    def add_hashtag(raw: str) -> None:
        tag = _normalize_hashtag(raw)
        if not tag or len(tag) < 3 or tag in seen_hashtags:
            return
        seen_hashtags.add(tag)
        hashtags.append(tag)

    for url in task.input_urls or []:
        text = (url or "").strip()
        if not text:
            continue
        if is_amazon_url(text):
            info.amazon_urls.append(text)
            asin = extract_asin_from_text(text)
            if asin:
                info.asin = info.asin or asin
                add_keyword(asin)
            else:
                info.parse_notes.append(f"已从链接识别 Amazon 商品，ASIN={info.asin or '未解析'}")
        else:
            add_keyword(text)

    raw_keywords = [k.strip() for k in (task.keywords or []) if k and str(k).strip()]
    for raw in raw_keywords:
        if raw.lower().startswith("brand:"):
            info.brand = raw.split(":", 1)[1].strip()
            continue
        asin = extract_asin_from_text(raw)
        if asin:
            info.asin = info.asin or asin
        add_keyword(raw)

    if info.brand:
        add_keyword(info.brand)
        add_hashtag(info.brand)

    for kw in keywords:
        add_hashtag(kw)

    for tag in DEFAULT_AMAZON_HASHTAGS:
        add_hashtag(tag)

    category = (task.category or "").strip().lower()
    if category:
        for key, tags in CATEGORY_HASHTAGS.items():
            if key in category or category in key:
                for tag in tags:
                    add_hashtag(tag)
                break

    info.core_keywords = keywords[:12]
    info.search_keywords = keywords[:12]
    info.search_hashtags = hashtags[:16]

    if not info.search_keywords and not info.search_hashtags:
        info.parse_notes.append("未能解析有效关键词，请手填品牌或商品词")

    return info


def build_competitor_search_keywords(info: CompetitorProductInfo) -> list[str]:
    """生成传给 keyword discovery 的搜索词（hashtag 优先）。"""
    if info.search_hashtags:
        return info.search_hashtags[:12]
    return info.search_keywords[:12]


def _has_meaningful_product_keywords(info: CompetitorProductInfo) -> bool:
    asin_lower = (info.asin or "").lower()
    brand_lower = (info.brand or "").lower()
    for kw in info.core_keywords:
        if len(kw) < 3:
            continue
        kl = kw.lower()
        if kl == asin_lower or kl == brand_lower:
            continue
        return True
    return False


def match_competitor_caption(caption: str | None, info: CompetitorProductInfo) -> CaptionMatchResult:
    text = (caption or "").strip()
    if not text:
        return CaptionMatchResult()

    lowered = text.lower()
    result = CaptionMatchResult()
    product_hits: list[str] = []
    commerce_hits: list[str] = []
    collab_hits: list[str] = []

    if info.brand and info.brand.lower() in lowered:
        product_hits.append(info.brand)
        result.match_reasons.append("包含品牌名")

    if info.asin and info.asin.lower() in lowered:
        product_hits.append(info.asin)
        result.match_reasons.append("包含 ASIN")

    for kw in info.core_keywords:
        if len(kw) < 3:
            continue
        if kw.lower() in lowered:
            product_hits.append(kw)
            if "包含商品关键词" not in result.match_reasons:
                result.match_reasons.append("包含商品关键词")

    for label, pattern in COMMERCE_PATTERNS:
        if pattern.search(text):
            commerce_hits.append(label)

    for label, pattern in COLLAB_PATTERNS:
        if pattern.search(text):
            collab_hits.append(label)

    requires_strict_product_match = bool(info.brand or _has_meaningful_product_keywords(info))

    if product_hits:
        result.matched = True
        if not requires_strict_product_match:
            result.low_confidence = True
        for label in commerce_hits + collab_hits:
            if f"辅助：{label}" not in result.match_reasons:
                result.match_reasons.append(f"辅助：{label}")
        result.matched_keywords = list(dict.fromkeys(product_hits + commerce_hits + collab_hits))
        result.suspected_collab = bool(collab_hits or commerce_hits)
    elif requires_strict_product_match:
        result.matched = False
    elif info.asin or info.amazon_urls:
        asin_in_text = bool(info.asin and info.asin.lower() in lowered)
        url_asin = extract_asin_from_text(text)
        if asin_in_text or (url_asin and info.asin and url_asin.upper() == info.asin.upper()):
            result.matched = True
            result.low_confidence = True
            if info.asin:
                product_hits.append(info.asin)
            result.match_reasons.append("仅 ASIN/链接匹配（低置信）")
            for label in commerce_hits + collab_hits:
                result.match_reasons.append(f"辅助：{label}")
            result.matched_keywords = list(dict.fromkeys(product_hits + commerce_hits + collab_hits))
            result.suspected_collab = bool(collab_hits or commerce_hits)

    return result


def build_candidate_source_meta(
    info: CompetitorProductInfo,
    match: CaptionMatchResult,
    *,
    source_post_url: str | None,
    source_caption: str | None,
) -> dict:
    return {
        "competitor_product_title": info.product_title,
        "asin": info.asin,
        "brand": info.brand,
        "matched_keywords": match.matched_keywords,
        "match_reasons": match.match_reasons,
        "suspected_collab": match.suspected_collab,
        "low_confidence": match.low_confidence,
        "source_post_url": source_post_url,
        "source_caption": source_caption,
        "collection_mode": "competitor_product",
        "amazon_urls": info.amazon_urls,
        "search_hashtags": info.search_hashtags[:8],
    }


def filter_candidates_by_competitor_caption(
    candidates: list[PostAuthorCandidate],
    info: CompetitorProductInfo,
) -> tuple[list[PostAuthorCandidate], int]:
    matched: list[PostAuthorCandidate] = []
    for candidate in candidates:
        match = match_competitor_caption(candidate.source_caption, info)
        if not match.matched:
            continue
        candidate.source_discovery_type = "competitor_product"
        candidate.source_meta = build_candidate_source_meta(
            info,
            match,
            source_post_url=candidate.source_post_url,
            source_caption=candidate.source_caption,
        )
        matched.append(candidate)
    return matched, len(candidates)


async def discover_competitor_product_candidates(
    task: CollectionTask,
    *,
    limit: int = 100,
) -> CompetitorProductDiscoveryResult:
    info = parse_competitor_product_inputs(task)
    search_terms = build_competitor_search_keywords(info)
    if not search_terms:
        return CompetitorProductDiscoveryResult(
            errors=["竞品商品发现需要 Amazon 链接、ASIN、品牌名或商品关键词至少一项"],
            competitor_meta=CompetitorProductDiscoveryMeta(product_info=info),
        )

    search_task = SimpleNamespace(
        keywords=search_terms,
        platform=task.platform,
        country=task.country,
        category=task.category,
    )

    kw_result = await discover_candidates_from_keywords(
        search_task,
        limit=limit,
        max_hashtags=min(12, len(search_terms)),
        include_comments=False,
    )

    authors_before = len(kw_result.raw_candidates)
    filtered, _ = filter_candidates_by_competitor_caption(kw_result.raw_candidates, info)

    deduped: dict[str, PostAuthorCandidate] = {}
    for candidate in filtered:
        key = candidate.profile_url.lower()
        if key not in deduped:
            deduped[key] = candidate

    candidates = list(deduped.values())[: limit * 2]
    competitor_meta = CompetitorProductDiscoveryMeta(
        product_info=info,
        posts_scanned=kw_result.meta.post_count if kw_result.meta else 0,
        authors_before_filter=authors_before,
        authors_matched=len(filtered),
    )

    logger.info(
        "[CompetitorProduct] asin=%s brand=%s hashtags=%d posts=%d raw=%d matched=%d deduped=%d",
        info.asin,
        info.brand,
        len(info.search_hashtags),
        competitor_meta.posts_scanned,
        authors_before,
        len(filtered),
        len(candidates),
    )

    return CompetitorProductDiscoveryResult(
        candidates=candidates,
        raw_candidates=filtered,
        errors=kw_result.errors,
        meta=kw_result.meta,
        competitor_meta=competitor_meta,
        hashtag_api_all_failed=kw_result.hashtag_api_all_failed,
        all_discovery_apis_failed=kw_result.all_discovery_apis_failed and not candidates,
    )
