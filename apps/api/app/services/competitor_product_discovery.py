"""竞品商品红人发现：解析 Amazon 输入 → IG hashtag 搜索 → caption 匹配。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from app.models.collection_task import CollectionTask
from app.services.apify_instagram import PostAuthorCandidate
from app.services.amazon_url import (
    AMAZON_WEAK_TOKENS,
    extract_asin_from_text,
    is_amazon_url,
    looks_like_asin,
    normalize_amazon_product_url,
    parse_amazon_product_url,
)
from app.services.keyword_discovery import (
    KeywordDiscoveryMeta,
    discover_candidates_from_keywords,
)

logger = logging.getLogger(__name__)

DEFAULT_AMAZON_HASHTAGS = (
    "amazonfinds",
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

_LAUNDRY_BAG_CATEGORY_RE = re.compile(
    r"laundry\s+bag|travel\s+laundry|drawstring\s+laundry|laundry\s+hamper|dirty\s+clothes|hamper\s+bag",
    re.I,
)


@dataclass
class CompetitorProductInfo:
    asin: str | None = None
    brand: str | None = None
    product_title: str | None = None
    product_category: str | None = None
    core_keywords: list[str] = field(default_factory=list)
    strong_keywords: list[str] = field(default_factory=list)
    weak_keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
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
    relevance_level: str | None = None
    rejected_reason: str | None = None
    match_score: float | None = None


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


def _normalize_hashtag(value: str) -> str:
    text = (value or "").strip().lower().lstrip("#")
    return re.sub(r"[^a-z0-9_]+", "", text)


def _tokenize_keywords(text: str) -> list[str]:
    parts = re.split(r"[\s,，/|]+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _apply_seed_relevance(info: CompetitorProductInfo, seed: dict) -> None:
    if seed.get("brand") and not info.brand:
        info.brand = str(seed["brand"]).strip()
    if seed.get("product_category") and not info.product_category:
        info.product_category = str(seed["product_category"]).strip()
    for field in ("strong_keywords", "weak_keywords", "negative_keywords", "search_keywords"):
        for raw in seed.get(field) or []:
            token = str(raw).strip()
            if not token:
                continue
            bucket = getattr(info, field)
            key = token.lower()
            if key not in {x.lower() for x in bucket}:
                bucket.append(token)


def parse_competitor_product_inputs(task: CollectionTask) -> CompetitorProductInfo:
    """从任务 input_urls / keywords / category 解析竞品商品搜索上下文。"""
    info = CompetitorProductInfo()
    seen_keywords: set[str] = set()
    seen_hashtags: set[str] = set()
    keywords: list[str] = []
    hashtags: list[str] = []

    checkpoint = getattr(task, "run_checkpoint", None) or {}
    for seed in checkpoint.get("amazon_product_seeds") or []:
        if isinstance(seed, dict):
            _apply_seed_relevance(info, seed)

    def add_keyword(raw: str) -> None:
        for token in _tokenize_keywords(raw):
            key = token.strip().lower()
            if not key:
                continue
            asin = extract_asin_from_text(token)
            if asin and looks_like_asin(token):
                info.asin = info.asin or asin
                if asin not in seen_keywords:
                    seen_keywords.add(asin)
                    keywords.append(asin)
                continue
            if len(key) < 2 or key in seen_keywords:
                continue
            seen_keywords.add(key)
            keywords.append(key)

    def add_hashtag(raw: str) -> None:
        tag = _normalize_hashtag(raw)
        if not tag or len(tag) < 3 or tag in seen_hashtags:
            return
        if tag in AMAZON_WEAK_TOKENS:
            return
        seen_hashtags.add(tag)
        hashtags.append(tag)

    def add_phrase_hashtag(phrase: str) -> None:
        tag = _normalize_hashtag(phrase.replace(" ", ""))
        if tag:
            add_hashtag(tag)

    for url in task.input_urls or []:
        text = (url or "").strip()
        if not text:
            continue
        if is_amazon_url(text):
            seed = parse_amazon_product_url(text)
            normalized = (seed or {}).get("normalized_url") or normalize_amazon_product_url(text) or text.strip()
            if normalized not in info.amazon_urls:
                info.amazon_urls.append(normalized)
            if seed:
                _apply_seed_relevance(info, seed)
                asin = seed.get("asin")
                if asin:
                    info.asin = info.asin or str(asin)
                    add_keyword(str(asin))
                for kw in seed.get("search_keywords") or seed.get("strong_keywords") or []:
                    add_keyword(str(kw))
                title_slug = seed.get("title_slug")
                if title_slug and not info.product_title:
                    info.product_title = str(title_slug).replace("-", " ").replace("\uFF0C", " ")
            else:
                asin = extract_asin_from_text(text)
                if asin:
                    info.asin = info.asin or asin
                    add_keyword(asin)
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
        add_phrase_hashtag(f"{info.brand} laundry bag")

    for phrase in info.strong_keywords:
        add_keyword(phrase)
        add_phrase_hashtag(phrase)

    for kw in keywords:
        if kw.lower() not in AMAZON_WEAK_TOKENS and len(kw) >= 3:
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

    if info.strong_keywords:
        info.core_keywords = list(dict.fromkeys(info.strong_keywords))[:16]
    else:
        info.core_keywords = [
            k for k in keywords if k.lower() not in AMAZON_WEAK_TOKENS and " " in k
        ][:12]

    if info.search_keywords:
        info.search_keywords = list(dict.fromkeys(info.search_keywords))[:12]
    else:
        info.search_keywords = [k for k in info.core_keywords if k.lower() != (info.asin or "").lower()][:12]

    info.search_hashtags = hashtags[:16]

    if not info.search_keywords and not info.search_hashtags:
        info.parse_notes.append("未能解析有效关键词，请手填品牌或商品词")

    return info


def _is_phrase_search_term(token: str) -> bool:
    text = (token or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower in AMAZON_WEAK_TOKENS:
        return False
    if looks_like_asin(text):
        return True
    return " " in text


def build_competitor_search_keywords(info: CompetitorProductInfo) -> list[str]:
    """生成平台搜索词：仅使用多词短语（+ ASIN），禁止泛词单词搜索。"""
    from app.core.config import settings

    max_terms = max(1, settings.competitor_product_max_search_keywords)
    terms: list[str] = []
    seen: set[str] = set()
    for raw in info.search_keywords or info.strong_keywords:
        token = str(raw).strip()
        if not _is_phrase_search_term(token):
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(token)
    if info.asin and info.asin not in terms:
        terms.append(info.asin)
    return terms[:max_terms]


def is_competitor_product_task(task) -> bool:
    mode = getattr(task, "collection_mode", None) or ""
    return str(mode) == "competitor_product"


def competitor_product_max_search_keywords() -> int:
    from app.core.config import settings

    return max(1, settings.competitor_product_max_search_keywords)


def filter_competitor_phrase_keywords(tokens: list[str]) -> list[str]:
    """从任务 keywords 中筛出短语级搜索词（用于 link import / 多平台发现）。"""
    max_terms = competitor_product_max_search_keywords()
    terms: list[str] = []
    seen: set[str] = set()
    for raw in tokens:
        token = str(raw).strip()
        if not _is_phrase_search_term(token):
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(token)
    return terms[:max_terms]


def resolve_competitor_discovery_keywords(task: CollectionTask) -> list[str]:
    info = parse_competitor_product_inputs(task)
    return build_competitor_search_keywords(info)


def competitor_task_for_platform_discovery(task: CollectionTask):
    """竞品发现：用短语级关键词代理 task，不修改数据库中的 task。"""
    from types import SimpleNamespace

    keywords = resolve_competitor_discovery_keywords(task)
    return SimpleNamespace(
        keywords=keywords,
        collection_mode=task.collection_mode,
        input_urls=task.input_urls,
        platform=task.platform,
        platforms=task.platforms,
        discovery_limit=task.discovery_limit,
        country=task.country,
        category=task.category,
        run_checkpoint=getattr(task, "run_checkpoint", None),
    )


def competitor_discovery_keyword_timeout_seconds(default: int) -> int:
    from app.core.config import settings

    return max(10, min(default, settings.competitor_product_keyword_timeout_seconds))


def competitor_discovery_apify_timeout_seconds(default: int) -> int:
    from app.core.config import settings

    kw = settings.competitor_product_keyword_timeout_seconds
    return max(15, min(default, kw + 15))


COMPETITOR_PLATFORM_PRIORITY: tuple[str, ...] = ("tiktok", "facebook", "youtube")


def order_competitor_discovery_platforms(platforms: list[str]) -> list[str]:
    rank = {name: idx for idx, name in enumerate(COMPETITOR_PLATFORM_PRIORITY)}
    return sorted(platforms, key=lambda name: rank.get(name, 99))


def _normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _collect_post_text(
    *,
    caption: str | None = None,
    title: str | None = None,
    description: str | None = None,
    hashtags: list[str] | None = None,
    recent_post_titles: list[str] | None = None,
) -> str:
    parts: list[str] = []
    for value in (caption, title, description):
        if value and str(value).strip():
            parts.append(str(value).strip())
    for item in recent_post_titles or []:
        if item and str(item).strip():
            parts.append(str(item).strip())
    for tag in hashtags or []:
        text = str(tag).strip()
        if text:
            parts.append(text if text.startswith("#") else f"#{text}")
    return "\n".join(parts)


def _negative_match_reason(text: str, info: CompetitorProductInfo) -> str | None:
    lowered = _normalize_match_text(text)
    if not lowered:
        return None
    # 强相关商品词优先于泛负向词（如 laundry room organizer vs travel laundry bag）
    if _has_core_category_signal(text, info):
        return None
    for phrase in info.negative_keywords or []:
        needle = str(phrase).strip().lower()
        if needle and needle in lowered:
            return f"irrelevant_category:{needle}"
    if re.search(r"\bpurifier\b", lowered) and not _LAUNDRY_BAG_CATEGORY_RE.search(lowered):
        return "irrelevant_category:purifier"
    if "washable filter" in lowered and not _LAUNDRY_BAG_CATEGORY_RE.search(lowered):
        return "irrelevant_category:washable filter"
    if re.search(r"\bwashing\s+machine\b", lowered) and not _LAUNDRY_BAG_CATEGORY_RE.search(lowered):
        return "irrelevant_category:washing machine"
    if re.search(r"\blaundry\s+detergent\b", lowered) and not _LAUNDRY_BAG_CATEGORY_RE.search(lowered):
        return "irrelevant_category:laundry detergent"
    return None


def _has_core_category_signal(text: str, info: CompetitorProductInfo) -> bool:
    lowered = _normalize_match_text(text)
    if not lowered:
        return False
    for phrase in info.strong_keywords:
        if " " in phrase and phrase.lower() in lowered:
            return True
    if info.product_category == "laundry_bag":
        return bool(_LAUNDRY_BAG_CATEGORY_RE.search(lowered))
    for kw in info.core_keywords:
        kl = kw.lower()
        if kl in AMAZON_WEAK_TOKENS or kl == (info.asin or "").lower():
            continue
        if kl in lowered:
            return True
    return False


def _brand_only_without_category(text: str, info: CompetitorProductInfo) -> bool:
    if not info.brand:
        return False
    lowered = _normalize_match_text(text)
    if info.brand.lower() not in lowered:
        return False
    return not _has_core_category_signal(text, info)


def _is_weak_only_match(text: str, info: CompetitorProductInfo) -> bool:
    lowered = _normalize_match_text(text)
    if not lowered:
        return False
    weak_hits = [w for w in AMAZON_WEAK_TOKENS if re.search(rf"\b{re.escape(w)}\b", lowered)]
    if not weak_hits:
        return False
    commerce_only = bool(
        re.search(
            r"\bamazon\b|amazonfinds|amazonmusthaves|amazonhome|founditonamazon|amazonfavorites",
            lowered,
            re.I,
        )
    )
    strong_phrase_hit = any(p.lower() in lowered for p in info.strong_keywords)
    if strong_phrase_hit:
        return False
    non_weak_tokens = [
        kw
        for kw in info.core_keywords
        if kw.lower() not in AMAZON_WEAK_TOKENS
        and kw.lower() != (info.asin or "").lower()
        and kw.lower() != (info.brand or "").lower()
    ]
    if any(kw.lower() in lowered for kw in non_weak_tokens):
        return False
    if info.brand and info.brand.lower() in lowered:
        return False
    return bool(weak_hits or commerce_only)


def match_competitor_post_text(
    text: str | None,
    info: CompetitorProductInfo,
    *,
    caption: str | None = None,
) -> CaptionMatchResult:
    combined = _collect_post_text(
        caption=caption or text,
        title=text if caption is None else None,
    )
    return match_competitor_caption(combined, info)


def match_competitor_caption(caption: str | None, info: CompetitorProductInfo) -> CaptionMatchResult:
    text = (caption or "").strip()
    if not text:
        return CaptionMatchResult(relevance_level="rejected", rejected_reason="empty_content")

    lowered = _normalize_match_text(text)
    result = CaptionMatchResult()
    product_hits: list[str] = []
    commerce_hits: list[str] = []
    collab_hits: list[str] = []

    negative = _negative_match_reason(text, info)
    if negative:
        result.matched = False
        result.relevance_level = "rejected"
        result.rejected_reason = negative
        result.match_reasons.append(negative)
        return result

    for phrase in info.strong_keywords:
        if phrase.lower() in lowered:
            product_hits.append(phrase)
            if "包含强相关商品词组" not in result.match_reasons:
                result.match_reasons.append("包含强相关商品词组")

    if info.brand and info.brand.lower() in lowered:
        product_hits.append(info.brand)
        result.match_reasons.append("包含品牌名")

    if info.asin and info.asin.lower() in lowered:
        product_hits.append(info.asin)
        result.match_reasons.append("包含 ASIN")

    for kw in info.core_keywords:
        if len(kw) < 3:
            continue
        kl = kw.lower()
        if kl in AMAZON_WEAK_TOKENS:
            continue
        if kl == (info.asin or "").lower() or kl == (info.brand or "").lower():
            continue
        if kl in lowered:
            product_hits.append(kw)
            if "包含商品关键词" not in result.match_reasons:
                result.match_reasons.append("包含商品关键词")

    for label, pattern in COMMERCE_PATTERNS:
        if pattern.search(text):
            commerce_hits.append(label)

    for label, pattern in COLLAB_PATTERNS:
        if pattern.search(text):
            collab_hits.append(label)

    strong_phrase_hits = [h for h in product_hits if " " in h]

    if _brand_only_without_category(text, info):
        result.matched = False
        result.relevance_level = "rejected"
        result.rejected_reason = "brand_only_no_category"
        result.match_reasons.append("仅命中品牌名，缺少洗衣袋等商品类目词")
        return result

    has_core = _has_core_category_signal(text, info)

    if has_core and not _is_weak_only_match(text, info):
        result.matched = True
        result.relevance_level = "strong" if strong_phrase_hits else "medium"
        result.match_score = 90.0 if strong_phrase_hits else 75.0
        if not strong_phrase_hits and info.asin and info.asin in product_hits:
            result.low_confidence = True
            result.relevance_level = "low"
            result.match_score = 40.0
        for label in commerce_hits + collab_hits:
            if f"辅助：{label}" not in result.match_reasons:
                result.match_reasons.append(f"辅助：{label}")
        result.matched_keywords = list(dict.fromkeys(product_hits + commerce_hits + collab_hits))
        result.suspected_collab = bool(collab_hits or commerce_hits)
        return result

    if _is_weak_only_match(text, info):
        result.matched = False
        result.relevance_level = "rejected"
        result.rejected_reason = "weak_keyword_only"
        result.match_reasons.append("仅命中泛词或 Amazon 发现词，缺少洗衣袋等强相关商品词")
        return result

    if info.asin or info.amazon_urls:
        asin_in_text = bool(info.asin and info.asin.lower() in lowered)
        url_asin = extract_asin_from_text(text)
        if asin_in_text or (url_asin and info.asin and url_asin.upper() == info.asin.upper()):
            result.matched = True
            result.low_confidence = True
            result.relevance_level = "low"
            result.match_score = 35.0
            if info.asin:
                product_hits.append(info.asin)
            result.match_reasons.append("仅 ASIN/链接匹配（低置信）")
            for label in commerce_hits + collab_hits:
                result.match_reasons.append(f"辅助：{label}")
            result.matched_keywords = list(dict.fromkeys(product_hits + commerce_hits + collab_hits))
            result.suspected_collab = bool(collab_hits or commerce_hits)
            return result

    result.matched = False
    result.relevance_level = "rejected"
    result.rejected_reason = "no_product_match"
    return result


def build_candidate_source_meta(
    info: CompetitorProductInfo,
    match: CaptionMatchResult,
    *,
    source_post_url: str | None,
    source_caption: str | None,
    source_input_url: str | None = None,
    amazon_original_url: str | None = None,
) -> dict:
    meta = {
        "competitor_product_title": info.product_title,
        "asin": info.asin,
        "brand": info.brand,
        "product_category": info.product_category,
        "matched_keywords": match.matched_keywords,
        "match_reasons": match.match_reasons,
        "suspected_collab": match.suspected_collab,
        "low_confidence": match.low_confidence,
        "relevance_level": match.relevance_level,
        "rejected_reason": match.rejected_reason,
        "match_score": match.match_score,
        "source_post_url": source_post_url,
        "source_caption": source_caption,
        "collection_mode": "competitor_product",
        "amazon_urls": info.amazon_urls,
        "search_hashtags": info.search_hashtags[:8],
        "strong_keywords": info.strong_keywords[:12],
    }
    if source_input_url:
        meta["source_input_url"] = source_input_url
    if amazon_original_url and amazon_original_url != source_input_url:
        meta["amazon_original_url"] = amazon_original_url
    return meta


def resolve_amazon_source_input_urls(task: CollectionTask) -> tuple[str | None, str | None]:
    """从 checkpoint seeds 或 input_urls 解析 Amazon 来源输入链接（规范化 + 原始）。"""
    checkpoint = getattr(task, "run_checkpoint", None) or {}
    seeds = checkpoint.get("amazon_product_seeds") or []
    for seed in seeds:
        if not isinstance(seed, dict):
            continue
        normalized = (seed.get("normalized_url") or "").strip() or None
        original = (seed.get("url") or "").strip() or None
        if normalized:
            if original == normalized:
                original = None
            return normalized, original

    for raw in task.input_urls or []:
        text = str(raw or "").strip()
        if not text or not is_amazon_url(text):
            continue
        normalized = normalize_amazon_product_url(text) or text
        original = text if text != normalized else None
        return normalized, original

    info = parse_competitor_product_inputs(task)
    if info.amazon_urls:
        return info.amazon_urls[0], None
    return None, None


def apply_competitor_product_source_context(
    profile,
    task: CollectionTask,
):
    """为 competitor_product 平台候选写入 Amazon source_input_url 与作品链接。"""
    from app.models.enums import CollectionMode
    from app.services.platform_types import PlatformCandidateProfile

    if (task.collection_mode or "") != CollectionMode.COMPETITOR_PRODUCT.value:
        return profile

    normalized, original = resolve_amazon_source_input_urls(task)
    if not normalized:
        return profile

    meta = dict(getattr(profile, "source_meta", None) or {})
    meta.setdefault("source_input_url", normalized)
    meta.setdefault("collection_mode", "competitor_product")
    if original:
        meta.setdefault("amazon_original_url", original)

    if not getattr(profile, "source_post_url", None):
        video_url = getattr(profile, "source_url", None) or meta.get("source_post_url")
        if video_url and getattr(profile, "platform", None) in {"youtube", "tiktok", "facebook", "instagram"}:
            profile.source_post_url = str(video_url)

    profile.source_input_url = getattr(profile, "source_input_url", None) or normalized
    profile.source_meta = meta
    if not getattr(profile, "source_discovery_type", None):
        profile.source_discovery_type = "competitor_product"
    if isinstance(profile, PlatformCandidateProfile) and not profile.source_type:
        profile.source_type = "competitor_product_post_author"
    return profile


def apply_competitor_product_source_to_collected(item, task: CollectionTask):
    from app.collectors.base import CollectedInfluencer

    normalized, original = resolve_amazon_source_input_urls(task)
    if not normalized or (task.collection_mode or "") != "competitor_product":
        return item

    if not getattr(item, "source_input_url", None):
        item.source_input_url = normalized
    if not getattr(item, "source_post_url", None) and getattr(item, "source_url", None):
        item.source_post_url = item.source_url
    if isinstance(item, CollectedInfluencer):
        if not item.source_discovery_type:
            item.source_discovery_type = "competitor_product"
    return item


def apply_competitor_product_source_to_candidate(
    candidate: PostAuthorCandidate,
    task: CollectionTask,
) -> PostAuthorCandidate:
    from app.models.enums import CollectionMode

    if (task.collection_mode or "") != CollectionMode.COMPETITOR_PRODUCT.value:
        return candidate

    normalized, original = resolve_amazon_source_input_urls(task)
    if not normalized:
        return candidate

    candidate.source_input_url = normalized
    candidate.source_discovery_type = candidate.source_discovery_type or "competitor_product"
    existing_meta = dict(candidate.source_meta or {})
    if candidate.source_discovery_type == "competitor_product" and existing_meta:
        match = CaptionMatchResult(
            matched_keywords=list(existing_meta.get("matched_keywords") or []),
            match_reasons=list(existing_meta.get("match_reasons") or []),
            suspected_collab=bool(existing_meta.get("suspected_collab")),
            low_confidence=bool(existing_meta.get("low_confidence")),
        )
        info = parse_competitor_product_inputs(task)
        candidate.source_meta = build_candidate_source_meta(
            info,
            match,
            source_post_url=candidate.source_post_url,
            source_caption=candidate.source_caption,
            source_input_url=normalized,
            amazon_original_url=original,
        )
    else:
        existing_meta.setdefault("source_input_url", normalized)
        existing_meta.setdefault("collection_mode", "competitor_product")
        if original:
            existing_meta.setdefault("amazon_original_url", original)
        candidate.source_meta = existing_meta
    return candidate


def filter_candidates_by_competitor_caption(
    candidates: list[PostAuthorCandidate],
    info: CompetitorProductInfo,
    *,
    source_input_url: str | None = None,
    amazon_original_url: str | None = None,
) -> tuple[list[PostAuthorCandidate], int]:
    matched: list[PostAuthorCandidate] = []
    for candidate in candidates:
        match = match_competitor_caption(candidate.source_caption, info)
        if not match.matched:
            continue
        candidate.source_discovery_type = "competitor_product"
        if source_input_url:
            candidate.source_input_url = source_input_url
        candidate.source_meta = build_candidate_source_meta(
            info,
            match,
            source_post_url=candidate.source_post_url,
            source_caption=candidate.source_caption,
            source_input_url=source_input_url,
            amazon_original_url=amazon_original_url,
        )
        matched.append(candidate)
    return matched, len(candidates)


def _profile_post_text(profile) -> str:
    meta = getattr(profile, "source_meta", None) or {}
    title = meta.get("video_title") or meta.get("title") or meta.get("source_title")
    return _collect_post_text(
        caption=meta.get("source_caption") or meta.get("caption"),
        title=title,
        description=meta.get("description") or meta.get("video_description"),
        recent_post_titles=list(getattr(profile, "recent_post_titles", None) or []),
    )


def filter_platform_profiles_by_competitor_relevance(
    profiles: list,
    info: CompetitorProductInfo,
) -> tuple[list, list]:
    """按视频标题/简介/帖子文本过滤平台 profile，返回 (相关, 不相关)。"""
    kept: list = []
    rejected: list = []
    for profile in profiles:
        text = _profile_post_text(profile)
        if not text.strip():
            text = _collect_post_text(
                title=getattr(profile, "display_name", None),
                description=getattr(profile, "bio", None),
            )
        match = match_competitor_caption(text, info)
        if match.matched:
            kept.append(profile)
        else:
            rejected.append(profile)
    return kept, rejected


def apply_competitor_product_relevance_to_platform_results(
    results: list,
    task: CollectionTask,
) -> list:
    """非 Instagram 平台发现结果：过滤不相关视频作者并写入 Amazon 来源。"""
    from app.models.enums import CollectionMode
    from app.services.platform_types import PlatformDiscoveryResult

    if (task.collection_mode or "") != CollectionMode.COMPETITOR_PRODUCT.value:
        return results

    info = parse_competitor_product_inputs(task)
    normalized, original = resolve_amazon_source_input_urls(task)

    for result in results:
        if not isinstance(result, PlatformDiscoveryResult):
            continue
        profiles = list(result.profiles or [])
        kept, _rejected = filter_platform_profiles_by_competitor_relevance(profiles, info)
        enriched_profiles = []
        for profile in kept:
            text = _profile_post_text(profile)
            match = match_competitor_caption(text, info)
            profile = apply_competitor_product_source_context(profile, task)
            meta = dict(getattr(profile, "source_meta", None) or {})
            meta.update(
                build_candidate_source_meta(
                    info,
                    match,
                    source_post_url=getattr(profile, "source_post_url", None),
                    source_caption=text,
                    source_input_url=normalized,
                    amazon_original_url=original,
                )
            )
            profile.source_meta = meta
            enriched_profiles.append(profile)
        result.profiles = enriched_profiles
        from app.services.platform_utils import profile_to_collected

        enriched_items = []
        for profile in enriched_profiles:
            item = profile_to_collected(profile)
            enriched_items.append(apply_competitor_product_source_to_collected(item, task))
        result.items = enriched_items
    return results


async def discover_competitor_product_candidates(
    task: CollectionTask,
    *,
    limit: int = 100,
) -> CompetitorProductDiscoveryResult:
    info = parse_competitor_product_inputs(task)
    source_input_url, amazon_original_url = resolve_amazon_source_input_urls(task)
    search_terms = build_competitor_search_keywords(info)
    from app.core.config import settings

    max_hashtags = min(
        settings.competitor_product_max_hashtags,
        len(search_terms),
        len(info.search_hashtags or []),
    )
    if max_hashtags <= 0:
        max_hashtags = min(settings.competitor_product_max_hashtags, len(search_terms))
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
        max_hashtags=max_hashtags,
        include_comments=False,
    )

    authors_before = len(kw_result.raw_candidates)
    filtered, _ = filter_candidates_by_competitor_caption(
        kw_result.raw_candidates,
        info,
        source_input_url=source_input_url,
        amazon_original_url=amazon_original_url,
    )

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
