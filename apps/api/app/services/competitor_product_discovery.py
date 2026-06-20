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
    exact_phrases: list[str] = field(default_factory=list)
    variant_attributes: list[str] = field(default_factory=list)
    broad_category_keywords: list[str] = field(default_factory=list)
    weak_keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    amazon_urls: list[str] = field(default_factory=list)
    search_keywords: list[str] = field(default_factory=list)
    search_hashtags: list[str] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)
    require_brand_match: bool = False


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
    match_type: str | None = None
    matched_phrases: list[str] = field(default_factory=list)
    missing_required_phrases: list[str] = field(default_factory=list)
    product_match_confidence: str | None = None
    selected_reason: str | None = None


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
    if seed.get("product_title") and not info.product_title:
        info.product_title = str(seed["product_title"]).strip()
    if seed.get("title_slug") and not info.product_title:
        info.product_title = str(seed["title_slug"]).replace("-", " ").replace("\uFF0C", " ")
    if str(seed.get("require_brand_match") or "").lower() in {"1", "true", "yes"}:
        info.require_brand_match = True
    for field in (
        "strong_keywords",
        "exact_phrases",
        "variant_attributes",
        "broad_category_keywords",
        "weak_keywords",
        "negative_keywords",
        "search_keywords",
    ):
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

    if info.brand and info.product_category == "laundry_bag":
        add_phrase_hashtag(f"{info.brand} laundry bag")

    for phrase in list(info.exact_phrases) + list(info.search_keywords) + list(info.strong_keywords):
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
    if info.asin:
        seen.add(info.asin.lower())
        terms.append(info.asin)
    for raw in info.search_keywords or info.strong_keywords:
        token = str(raw).strip()
        if not _is_phrase_search_term(token):
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(token)
    return terms[:max_terms]


def _add_unique_text(values: list[str], value: str | None) -> None:
    text = re.sub(r"\s+", " ", (value or "").strip())
    if text and text.lower() not in {item.lower() for item in values}:
        values.append(text)


def build_instagram_product_search_queries(info: CompetitorProductInfo) -> list[str]:
    """Build Instagram-oriented Amazon product discovery queries."""
    queries: list[str] = []
    brand = (info.brand or "").strip()
    strong_phrases = list(dict.fromkeys(info.exact_phrases + info.strong_keywords + info.search_keywords))
    category_phrases = list(dict.fromkeys(info.broad_category_keywords + ([info.product_category] if info.product_category else [])))

    for phrase in strong_phrases[:8]:
        if brand and not phrase.lower().startswith(brand.lower()):
            _add_unique_text(queries, f"{brand} {phrase} Instagram")
        _add_unique_text(queries, f"{phrase} Amazon finds Instagram")
        _add_unique_text(queries, f"{phrase} Amazon must haves Instagram")
        if phrase.lower().startswith("amazon "):
            _add_unique_text(queries, f"{phrase} Instagram")
        else:
            _add_unique_text(queries, f"{phrase} Instagram")

    combined = " ".join(str(part or "") for part in strong_phrases + category_phrases).lower()
    if any(term in combined for term in ("home", "organization", "organizer", "storage")):
        _add_unique_text(queries, "Amazon home organization finds Instagram")
        _add_unique_text(queries, "homeorganization")
        _add_unique_text(queries, "amazonhomefinds organization")
    if any(term in combined for term in ("jewelry", "accessories")):
        _add_unique_text(queries, "Amazon accessories organizer Instagram")
        _add_unique_text(queries, "jewelrystorage")
    if any(term in combined for term in ("travel", "portable")):
        _add_unique_text(queries, "travelorganizer amazonfinds")
        _add_unique_text(queries, "amazontravelessentials")

    for phrase in category_phrases[:8]:
        _add_unique_text(queries, f"{phrase} Amazon finds Instagram")
        _add_unique_text(queries, f"{phrase} influencer Instagram")
        _add_unique_text(queries, f"{phrase} blogger Instagram")
        _add_unique_text(queries, f"amazonfinds {phrase}")
        _add_unique_text(queries, f"amazonmusthaves {phrase}")

    return queries[:60]


def _profile_text(profile) -> str:
    meta = getattr(profile, "source_meta", None) or {}
    parts = [
        getattr(profile, "username", None),
        getattr(profile, "display_name", None),
        getattr(profile, "bio", None),
        meta.get("source_caption") if isinstance(meta, dict) else None,
        meta.get("caption") if isinstance(meta, dict) else None,
        meta.get("video_description") if isinstance(meta, dict) else None,
        meta.get("description") if isinstance(meta, dict) else None,
    ]
    return "\n".join(str(part).strip() for part in parts if str(part or "").strip())


def _slug_variants(value: str | None) -> list[str]:
    text = (value or "").strip().lstrip("@")
    if not text:
        return []
    variants: list[str] = []
    _add_unique_text(variants, text)
    compact = re.sub(r"[^A-Za-z0-9]+", "", text)
    if compact:
        _add_unique_text(variants, compact)
    no_digits = re.sub(r"\d+", "", compact)
    if no_digits and len(no_digits) >= 3:
        _add_unique_text(variants, no_digits)
    slug = re.sub(r"[^A-Za-z0-9]+", "", text.lower())
    if slug:
        _add_unique_text(variants, slug)
    return variants


def build_cross_platform_instagram_probe_queries(profiles: list) -> list[str]:
    queries: list[str] = []
    signal_re = re.compile(r"amazon\s*finds|amazon associate|shopmy|ltk|linktree|link in bio|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
    for profile in profiles or []:
        username = (getattr(profile, "username", None) or "").strip().lstrip("@")
        display_name = (getattr(profile, "display_name", None) or "").strip()
        for name in (username, display_name):
            if not name:
                continue
            _add_unique_text(queries, f"{name} Instagram")
            _add_unique_text(queries, f"{name} Amazon finds Instagram")
            _add_unique_text(queries, f"{name} link in bio Instagram")
            _add_unique_text(queries, f"{name} influencer Instagram")
        text = _profile_text(profile)
        if signal_re.search(text):
            for match in signal_re.findall(text):
                token = str(match).strip()
                if "@" in token:
                    token = token.split("@", 1)[0]
                if token:
                    _add_unique_text(queries, f"{token} Instagram")
    return queries[:60]


def build_instagram_profile_probe_urls(profiles: list) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for profile in profiles or []:
        for value in (getattr(profile, "username", None), getattr(profile, "display_name", None)):
            for variant in _slug_variants(value):
                handle = re.sub(r"[^A-Za-z0-9_.]", "", variant).strip("._").lower()
                if len(handle) < 3 or handle.lower().startswith("uc"):
                    continue
                url = f"https://www.instagram.com/{handle}/"
                key = url.lower()
                if key in seen:
                    continue
                seen.add(key)
                urls.append(url)
    return urls[:50]


def cross_platform_probe_candidates_from_results(results: list) -> list:
    candidates: list = []
    seen: set[tuple[str, str]] = set()
    for result in results or []:
        for profile in getattr(result, "profiles", None) or []:
            platform = (getattr(profile, "platform", None) or getattr(result, "platform", "") or "").lower()
            if platform not in {"tiktok", "youtube"}:
                continue
            meta = getattr(profile, "source_meta", None) or {}
            if not isinstance(meta, dict) or not meta.get("amazon_asin"):
                continue
            key = (platform, (getattr(profile, "username", None) or getattr(profile, "profile_url", "")).lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(profile)
    return candidates


def apply_cross_platform_evidence_to_instagram_item(item, source_profile):
    source_meta = dict(getattr(source_profile, "source_meta", None) or {})
    inherited = dict(getattr(item, "source_meta", None) or {})
    for key in (
        "competitor_product_title",
        "asin",
        "brand",
        "amazon_asin",
        "amazon_brand",
        "amazon_product_title",
        "product_category",
        "matched_keywords",
        "matched_phrases",
        "match_reasons",
        "match_type",
        "product_match_confidence",
        "selected_reason",
        "source_input_url",
        "amazon_original_url",
    ):
        if key in source_meta and key not in inherited:
            inherited[key] = source_meta.get(key)
    evidence_text = (
        source_meta.get("source_caption")
        or source_meta.get("caption")
        or source_meta.get("video_description")
        or source_meta.get("description")
        or getattr(source_profile, "bio", None)
        or ""
    )
    inherited.update(
        {
            "evidence_inherited_from_platform": getattr(source_profile, "platform", None),
            "evidence_source_profile_url": getattr(source_profile, "profile_url", None),
            "evidence_source_post_url": getattr(source_profile, "source_post_url", None) or source_meta.get("source_post_url"),
            "evidence_source_text": evidence_text,
            "primary_evidence_platform": getattr(source_profile, "platform", None),
            "collection_mode": "competitor_product",
        }
    )
    item.source_discovery_type = "competitor_product_cross_platform_instagram_probe"
    if not getattr(item, "source_post_url", None):
        item.source_post_url = inherited.get("evidence_source_post_url")
    if not getattr(item, "source_input_url", None):
        item.source_input_url = inherited.get("source_input_url")
    setattr(item, "source_meta", inherited)
    tags = list(getattr(item, "tags", None) or [])
    for tag in ("competitor_product", "cross_platform_instagram_probe"):
        if tag not in tags:
            tags.append(tag)
    item.tags = tags
    return item


async def discover_instagram_from_cross_platform_evidence(
    task: CollectionTask,
    platform_results: list,
    *,
    existing_usernames: set[str] | None = None,
) -> object | None:
    """Probe Instagram profiles that likely belong to matched TikTok/YouTube creators."""
    from app.services.contact_discovery import ContactDiscoveryService
    from app.services.instagram_provider import scrape_instagram_profiles
    from app.services.platform_types import PlatformCandidateProfile, PlatformDiscoveryResult

    if (task.collection_mode or "") != "competitor_product":
        return None
    source_profiles = cross_platform_probe_candidates_from_results(platform_results)
    probe_queries = build_cross_platform_instagram_probe_queries(source_profiles)
    probe_urls = build_instagram_profile_probe_urls(source_profiles)

    checkpoint = dict(getattr(task, "run_checkpoint", None) or {})
    fallback = dict(checkpoint.get("competitor_product_instagram_fallback") or {})
    fallback.update(
        {
            "cross_platform_probe_candidates": [
                {
                    "platform": getattr(profile, "platform", None),
                    "username": getattr(profile, "username", None),
                    "display_name": getattr(profile, "display_name", None),
                    "profile_url": getattr(profile, "profile_url", None),
                }
                for profile in source_profiles
            ],
            "probe_queries": probe_queries,
            "probe_query_count": len(probe_queries),
            "probe_profile_urls": probe_urls,
            "probe_profile_url_count": len(probe_urls),
        }
    )
    checkpoint["competitor_product_instagram_fallback"] = fallback
    task.run_checkpoint = checkpoint

    if not source_profiles or not probe_urls:
        fallback.setdefault("matched_instagram_count", 0)
        fallback.setdefault("inherited_evidence_count", 0)
        return None

    existing = {name.strip().lower().lstrip("@") for name in existing_usernames or set() if name}
    profile_urls = [
        url for url in probe_urls
        if url.rstrip("/").rsplit("/", 1)[-1].lower() not in existing
    ]
    if not profile_urls:
        fallback["matched_instagram_count"] = 0
        fallback["inherited_evidence_count"] = 0
        return None

    candidate_meta = {
        url.rstrip("/").rsplit("/", 1)[-1].lower(): PostAuthorCandidate(
            username=url.rstrip("/").rsplit("/", 1)[-1],
            profile_url=url,
            source_discovery_type="competitor_product_cross_platform_instagram_probe",
            source_meta={"probe_queries": probe_queries, "collection_mode": "competitor_product"},
        )
        for url in profile_urls
    }
    scrape_result = await scrape_instagram_profiles(profile_urls, candidate_meta=candidate_meta)
    items = []
    profiles = []
    source_by_name = {}
    for source in source_profiles:
        for variant in _slug_variants(getattr(source, "username", None)) + _slug_variants(getattr(source, "display_name", None)):
            source_by_name.setdefault(variant.lower(), source)
    for item in scrape_result.profiles:
        source = source_by_name.get((item.username or "").strip().lower())
        if source is None and len(source_profiles) == 1:
            source = source_profiles[0]
        if source is None:
            continue
        apply_cross_platform_evidence_to_instagram_item(item, source)
        await ContactDiscoveryService.enrich_collected(item)
        items.append(item)
        profiles.append(
            PlatformCandidateProfile(
                platform="instagram",
                username=item.username,
                display_name=item.display_name,
                profile_url=item.profile_url,
                bio=item.bio,
                followers_count=item.followers_count,
                engagement_rate=item.engagement_rate,
                website=item.website,
                email=item.email or item.final_email or item.public_email or item.business_email,
                other_social_links=item.other_social_links or [],
                source_post_url=item.source_post_url,
                source_input_url=item.source_input_url,
                source_discovery_type=item.source_discovery_type,
                source_meta=dict(getattr(item, "source_meta", {}) or {}),
            )
        )

    fallback["matched_instagram_count"] = len(items)
    fallback["inherited_evidence_count"] = len(items)
    fallback["profile_failed_count"] = len(getattr(scrape_result, "failed_profiles", []) or [])
    task.run_checkpoint = checkpoint
    if not items and not getattr(scrape_result, "failed_profiles", None):
        return None
    return PlatformDiscoveryResult(
        platform="instagram",
        items=items,
        profiles=profiles,
        discovered_count=len(profile_urls),
        deduped_count=len(profile_urls),
        profile_fetched_count=len(items),
        profile_failed_count=len(getattr(scrape_result, "failed_profiles", []) or []),
        errors=list(getattr(scrape_result, "errors", []) or []),
        api_requests=1 if profile_urls else 0,
    )


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


def _semantic_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def _phrase_in_text(phrase: str, text: str) -> bool:
    needle = _semantic_text(phrase)
    haystack = _semantic_text(text)
    return bool(needle and needle in haystack)


def _matched_phrase_list(phrases: list[str], text: str) -> list[str]:
    matched: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        value = str(phrase).strip()
        key = value.lower()
        if not value or key in seen:
            continue
        if _phrase_in_text(value, text):
            seen.add(key)
            matched.append(value)
    return matched


def _brand_hit(text: str, brand: str | None) -> bool:
    return bool(brand and _phrase_in_text(brand, text))


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

    asin_in_text = bool(info.asin and info.asin.lower() in lowered)
    url_asin = extract_asin_from_text(text)
    if asin_in_text or (url_asin and info.asin and url_asin.upper() == info.asin.upper()):
        result.matched = True
        result.low_confidence = False
        result.relevance_level = "exact"
        result.match_score = 100.0
        result.match_type = "exact_link_match"
        result.product_match_confidence = "exact"
        result.matched_keywords = [info.asin] if info.asin else []
        result.matched_phrases = list(result.matched_keywords)
        result.match_reasons.append("命中 Amazon ASIN 或原始商品链接")
        result.selected_reason = "命中 exact Amazon URL / ASIN，判断为同一商品"
        return result

    if info.require_brand_match:
        brand_matched = _brand_hit(text, info.brand)
        exact_hits = _matched_phrase_list(info.exact_phrases, text)
        variant_hits = _matched_phrase_list(info.variant_attributes, text)
        strong_hits = _matched_phrase_list(
            [
                phrase
                for phrase in info.strong_keywords
                if (not info.brand or info.brand.lower() not in phrase.lower())
            ],
            text,
        )
        broad_hits = _matched_phrase_list(info.broad_category_keywords, text)
        all_hits = list(dict.fromkeys(([info.brand] if brand_matched and info.brand else []) + exact_hits + variant_hits + strong_hits))

        missing: list[str] = []
        if info.brand and not brand_matched:
            missing.append(info.brand)
        if not (exact_hits or strong_hits or variant_hits):
            missing.append("同款标题/材质/变体短语")

        quantity_variant_hits = [hit for hit in variant_hits if re.search(r"\d", hit)]
        if brand_matched and quantity_variant_hits and (exact_hits or strong_hits or len(variant_hits) >= 2):
            result.matched = True
            result.relevance_level = "strong"
            result.match_score = 95.0
            result.match_type = "same_variant_match"
            result.product_match_confidence = "very_high"
            result.matched_keywords = all_hits
            result.matched_phrases = all_hits
            result.missing_required_phrases = []
            result.match_reasons.append("命中品牌和同页面变体属性")
            result.selected_reason = f"未发现原始 Amazon 链接，但命中 {info.brand} 和 {', '.join(quantity_variant_hits[:2])} 变体"
            return result

        if brand_matched and (exact_hits or strong_hits):
            result.matched = True
            result.relevance_level = "strong"
            result.match_score = 88.0
            result.match_type = "same_product_match"
            result.product_match_confidence = "high"
            result.matched_keywords = all_hits
            result.matched_phrases = all_hits
            result.missing_required_phrases = []
            result.match_reasons.append("命中品牌和同款核心标题短语")
            phrase = (exact_hits or strong_hits)[0]
            result.selected_reason = f"命中 {info.brand} + {phrase}，判断为同款产品"
            return result

        result.matched = False
        result.relevance_level = "rejected"
        result.match_score = 20.0 if broad_hits else None
        result.matched_keywords = list(dict.fromkeys(broad_hits + strong_hits + variant_hits))
        result.matched_phrases = result.matched_keywords
        result.missing_required_phrases = missing
        if broad_hits:
            result.match_type = "weak_category_match"
            result.rejected_reason = "weak_category_match"
            result.product_match_confidence = "low"
            result.match_reasons.append("仅命中泛类目，未命中品牌 + 同款产品指纹")
            result.selected_reason = f"仅命中 {', '.join(broad_hits[:2])} 泛类目，未达到同款产品要求"
        elif not brand_matched and (strong_hits or variant_hits):
            result.match_type = "weak_category_match"
            result.rejected_reason = "missing_brand_for_same_product"
            result.product_match_confidence = "low"
            result.match_reasons.append("命中商品类目/变体词，但缺少目标品牌")
            result.selected_reason = "命中同类/相似短语但未命中目标品牌，不能判定为同款产品"
        else:
            result.match_type = "weak_category_match"
            result.rejected_reason = "no_same_product_fingerprint"
            result.product_match_confidence = "none"
            result.selected_reason = "未命中目标品牌和同款产品指纹"
        return result

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
        "amazon_asin": info.asin,
        "amazon_brand": info.brand,
        "amazon_product_title": info.product_title,
        "product_category": info.product_category,
        "matched_keywords": match.matched_keywords,
        "matched_phrases": match.matched_phrases or match.matched_keywords,
        "match_reasons": match.match_reasons,
        "missing_required_phrases": match.missing_required_phrases,
        "match_type": match.match_type,
        "product_match_confidence": match.product_match_confidence,
        "selected_reason": match.selected_reason,
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


def _amazon_product_video_entries(task: CollectionTask) -> list[dict]:
    checkpoint = getattr(task, "run_checkpoint", None) or {}
    entries: list[dict] = []
    seen: set[str] = set()

    def entry_key(value: dict, creator: str, title: str, url: str) -> str:
        asin = str(value.get("asin") or "").strip().upper()
        if not asin:
            asin = (
                extract_asin_from_text(
                    "\n".join(
                        str(value.get(key) or "")
                        for key in ("text", "video_url", "review_url", "url")
                    )
                )
                or ""
            ).upper()
        review_url = str(value.get("review_url") or "").strip().lower()
        video_url = str(value.get("video_url") or value.get("url") or "").strip().lower()
        canonical_url = video_url or review_url or url.lower()
        if asin:
            return "|".join([asin, creator.lower(), title.lower()])
        return "|".join([creator.lower(), title.lower(), canonical_url])

    def add_many(values) -> None:
        for value in values or []:
            if not isinstance(value, dict):
                continue
            creator = str(
                value.get("creator_name")
                or value.get("creator")
                or value.get("author")
                or value.get("reviewer")
                or ""
            ).strip()
            title = str(value.get("video_title") or value.get("title") or "").strip()
            url = str(value.get("video_url") or value.get("review_url") or value.get("url") or "").strip()
            key = entry_key(value, creator, title, url)
            if not creator or key in seen:
                continue
            seen.add(key)
            entries.append(value)

    add_many(checkpoint.get("amazon_product_page_videos"))
    add_many(checkpoint.get("amazon_product_videos"))
    for seed in checkpoint.get("amazon_product_seeds") or []:
        if isinstance(seed, dict):
            add_many(seed.get("product_videos"))
            add_many(seed.get("amazon_product_page_videos"))
    return entries


def amazon_product_video_candidate_rows(task: CollectionTask) -> list[dict]:
    """Build visible candidate rows from Amazon Product Videos / customer review videos."""
    from app.models.enums import CandidateStatus, CollectionMode

    if (task.collection_mode or "") != CollectionMode.COMPETITOR_PRODUCT.value:
        return []

    info = parse_competitor_product_inputs(task)
    normalized, original = resolve_amazon_source_input_urls(task)
    rows: list[dict] = []
    for entry in _amazon_product_video_entries(task):
        creator = str(
            entry.get("creator_name")
            or entry.get("creator")
            or entry.get("author")
            or entry.get("reviewer")
            or ""
        ).strip()
        if not creator:
            continue
        title = str(entry.get("video_title") or entry.get("title") or "").strip()
        source = str(entry.get("video_source") or entry.get("source") or "amazon_product_video").strip()
        review_url = str(entry.get("review_url") or "").strip() or None
        video_url = str(entry.get("video_url") or entry.get("url") or "").strip() or None
        text = "\n".join(
            part
            for part in (
                title,
                str(entry.get("text") or "").strip(),
                str(entry.get("description") or "").strip(),
                str(entry.get("caption") or "").strip(),
                video_url or "",
                review_url or "",
                normalized or "",
            )
            if part
        )
        match = match_competitor_caption(text, info)
        if not match.matched:
            continue
        source_post_url = video_url or review_url or normalized
        source_meta = build_candidate_source_meta(
            info,
            match,
            source_post_url=source_post_url,
            source_caption=text,
            source_input_url=normalized,
            amazon_original_url=original,
        )
        source_meta.update(
            {
                "amazon_creator_name": creator,
                "video_title": title or None,
                "video_source": source,
                "review_url": review_url,
                "video_url": video_url,
                "source_kind": "amazon_product_page_strong_lead",
                "needs_social_profile_completion": True,
            }
        )
        rows.append(
            {
                "username": creator,
                "profile_url": review_url or video_url or normalized or f"https://www.amazon.com/dp/{info.asin}",
                "platform": "amazon",
                "status": CandidateStatus.PENDING_PROFILE.value,
                "failure_reason": "amazon_product_page_strong_lead",
                "failure_detail": "Amazon 商品页强线索：商品页视频/Customer Review 视频作者，待补全社媒主页",
                "source_keyword": info.asin or info.brand,
                "source_post_url": source_post_url,
                "source_caption": text,
                "source_input_url": normalized,
                "source_discovery_type": "amazon_product_page_strong_lead",
                "source_type": "amazon_product_page_video",
                "source_meta": source_meta,
            }
        )
    return rows


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
            matched_phrases=list(existing_meta.get("matched_phrases") or []),
            missing_required_phrases=list(existing_meta.get("missing_required_phrases") or []),
            match_reasons=list(existing_meta.get("match_reasons") or []),
            suspected_collab=bool(existing_meta.get("suspected_collab")),
            low_confidence=bool(existing_meta.get("low_confidence")),
            match_type=existing_meta.get("match_type"),
            product_match_confidence=existing_meta.get("product_match_confidence"),
            selected_reason=existing_meta.get("selected_reason"),
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
    """非 Instagram 平台发现结果：过滤不相关视频作者并写入 Amazon 来源。

    同款过滤后被拒绝的 profile 不进入 items/profiles（避免入库），
    但写入 candidate_rows（status=filtered_out, failure_reason=no_same_product_match），
    保留诊断信息供候选池和导出使用。
    """
    from app.models.enums import CandidateStatus, CollectionMode
    from app.services.platform_types import PlatformDiscoveryResult

    if (task.collection_mode or "") != CollectionMode.COMPETITOR_PRODUCT.value:
        return results

    info = parse_competitor_product_inputs(task)
    normalized, original = resolve_amazon_source_input_urls(task)

    for result in results:
        if not isinstance(result, PlatformDiscoveryResult):
            continue
        profiles = list(result.profiles or [])
        pre_filter_count = len(profiles)

        enriched_profiles = []
        enriched_items = []
        filtered_out_rows: list[dict] = []
        rejected_reason_counts: dict[str, int] = {}

        for profile in profiles:
            text = _profile_post_text(profile)
            if not text.strip():
                text = _collect_post_text(
                    title=getattr(profile, "display_name", None),
                    description=getattr(profile, "bio", None),
                )
            match = match_competitor_caption(text, info)

            if match.matched:
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
                from app.services.platform_utils import profile_to_collected

                item = profile_to_collected(profile)
                enriched_items.append(apply_competitor_product_source_to_collected(item, task))
            else:
                # Rejected by same-product filter — build diagnostic candidate_row
                source_keyword = (getattr(profile, "source_meta", None) or {}).get(
                    "source_keyword"
                )
                if not source_keyword:
                    for kw in info.search_keywords[:3]:
                        source_keyword = kw
                        break
                source_post_url = getattr(profile, "source_post_url", None) or (
                    getattr(profile, "source_meta", None) or {}
                ).get("source_post_url")
                source_caption = text
                source_input_url = normalized or getattr(profile, "source_input_url", None)
                source_meta = build_candidate_source_meta(
                    info,
                    match,
                    source_post_url=source_post_url,
                    source_caption=source_caption,
                    source_input_url=source_input_url,
                    amazon_original_url=original,
                )
                failure_detail = (
                    match.selected_reason
                    or match.rejected_reason
                    or "未命中同款商品指纹"
                )
                row = {
                    "username": getattr(profile, "username", None),
                    "profile_url": getattr(profile, "profile_url", None),
                    "platform": getattr(profile, "platform", None),
                    "status": CandidateStatus.FILTERED_OUT.value,
                    "failure_reason": "no_same_product_match",
                    "failure_detail": failure_detail,
                    "source_keyword": source_keyword,
                    "source_post_url": source_post_url,
                    "source_caption": source_caption,
                    "source_input_url": source_input_url,
                    "source_discovery_type": getattr(profile, "source_discovery_type", None)
                    or "competitor_product",
                    "source_meta": source_meta,
                    "followers_count": getattr(profile, "followers_count", None),
                    "engagement_rate": getattr(profile, "engagement_rate", None),
                }
                filtered_out_rows.append(row)

                reason_key = match.rejected_reason or "unknown"
                rejected_reason_counts[reason_key] = rejected_reason_counts.get(reason_key, 0) + 1

        result.profiles = enriched_profiles
        result.items = enriched_items
        # Preserve pre-filter counts — do NOT zero discovered/deduped/profile_fetched
        result.candidate_rows = filtered_out_rows

        # Add summary error when same-product filter rejected all candidates
        if filtered_out_rows and not enriched_profiles:
            reason_parts = [
                f"{reason} {count} 个"
                for reason, count in sorted(rejected_reason_counts.items())
            ]
            reason_summary = "、".join(reason_parts) if reason_parts else "全部被拒"
            platform_label = (result.platform or "unknown").capitalize()
            result.errors.append(
                f"{platform_label} 同款过滤后 0/{pre_filter_count}：{reason_summary}"
            )

    return results


async def discover_competitor_product_candidates(
    task: CollectionTask,
    *,
    limit: int = 100,
    checkpoint=None,
    db=None,
) -> CompetitorProductDiscoveryResult:
    info = parse_competitor_product_inputs(task)
    source_input_url, amazon_original_url = resolve_amazon_source_input_urls(task)
    product_instagram_queries = build_instagram_product_search_queries(info)
    search_terms = list(dict.fromkeys(build_competitor_search_keywords(info) + product_instagram_queries))
    if checkpoint is not None or getattr(task, "run_checkpoint", None) is not None:
        checkpoint_extra = dict(getattr(task, "run_checkpoint", None) or {})
        fallback = dict(checkpoint_extra.get("competitor_product_instagram_fallback") or {})
        fallback["product_instagram_queries"] = product_instagram_queries
        checkpoint_extra["competitor_product_instagram_fallback"] = fallback
        task.run_checkpoint = checkpoint_extra
        if checkpoint is not None and hasattr(checkpoint, "extra"):
            checkpoint_fallback = dict(checkpoint.extra.get("competitor_product_instagram_fallback") or {})
            checkpoint_fallback["product_instagram_queries"] = product_instagram_queries
            checkpoint.extra["competitor_product_instagram_fallback"] = checkpoint_fallback
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
        processed_count=getattr(task, "processed_count", 0) or 0,
        success_count=getattr(task, "success_count", 0) or 0,
        skipped_count=getattr(task, "skipped_count", 0) or 0,
        failed_count=getattr(task, "failed_count", 0) or 0,
        total_estimate=getattr(task, "total_estimate", 0) or 0,
        current_stage=getattr(task, "current_stage", None),
        status_summary=getattr(task, "status_summary", None),
        last_error=getattr(task, "last_error", None),
        run_checkpoint=getattr(task, "run_checkpoint", None),
    )

    kw_result = await discover_candidates_from_keywords(
        search_task,
        limit=limit,
        max_hashtags=max_hashtags,
        include_comments=False,
        checkpoint=checkpoint,
        db=None,
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
