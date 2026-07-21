# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：amazon url
"""Amazon 商品链接识别、ASIN 提取与归一化。"""



from __future__ import annotations



import re

from urllib.parse import unquote, urlparse



AMAZON_URL_ASIN_RE = re.compile(

    r"(?:amazon\.[a-z.]+/(?:[^/]+/)?(?:dp|gp/product|product)/|asin=)([A-Z0-9]{10})",

    re.I,

)

STANDALONE_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$", re.I)

AMAZON_HOST_RE = re.compile(r"amazon\.[a-z.]+", re.I)



AMAZON_PRODUCT_PATH_RE = re.compile(

    r"/(?:dp|gp/product|product)/([A-Z0-9]{10})(?:[/?]|$)",

    re.I,

)



AMAZON_SLUG_BEFORE_PRODUCT_RE = re.compile(

    r"/([^/]+)/(?:dp|gp/product|product)/[A-Z0-9]{10}",

    re.I,

)



AMAZON_PATH_STOPWORDS = frozenset(

    {

        "a",

        "an",

        "the",

        "and",

        "or",

        "for",

        "with",

        "of",

        "in",

        "on",

        "to",

        "new",

        "set",

        "pack",

        "pcs",

        "piece",

        "pieces",

        "size",

        "color",

        "style",

        "by",

        "from",

    }

)



# slug 单词级弱信号：不能单独作为商品相关性强匹配

AMAZON_WEAK_TOKENS = frozenset(

    {

        "washable",

        "organizer",

        "essentials",

        "large",

        "bag",

        "best",

        "products",

        "finds",

        "home",

        "musthaves",

        "favorites",

        "laundry",

    }

)



DEFAULT_NEGATIVE_KEYWORDS: tuple[str, ...] = (

    "air purifier",

    "air purifiers",

    "washable filters",

    "washable filter",

    "nut milk maker",

    "nut milk makers",

    "geothermal heating",

    "geothermal system",

    "lake-based geothermal",

    "coffee maker",

    "vacuum cleaner",

    "vacuum",

    "water filter",

    "kitchen appliance",

    "home appliance",

    "purifier",

    "filter machine",

    "replacement filter",

    "appliance deals",

    "appliance organizer",

    "laundry detergent organizer",

    "washing machine essentials",

    "laundry room organizer",

)



# 已知 ASIN 补充元数据（slug 不足以表达完整商品语义时）

AMAZON_ASIN_PROFILES: dict[str, dict[str, str | list[str]]] = {

    "B0CPF3W9B2": {

        "brand": "Aegero",

        "product_category": "laundry_bag",
        "product_videos": [
            {
                "creator_name": "Kuzzin Vinny Reviews",
                "video_title": "Aegero 2 Pack XL Travel Laundry Bag Review",
                "video_source": "customer_review_video",
                "review_url": "https://www.amazon.com/dp/B0CPF3W9B2",
                "video_url": "https://www.amazon.com/dp/B0CPF3W9B2#customer-review-video",
                "text": "Aegero travel laundry bag B0CPF3W9B2",
            }
        ],

        "strong_keywords": [

            "laundry bag",

            "travel laundry bag",

            "dirty clothes organizer",

            "drawstring laundry bag",

            "laundry hamper bag",

            "machine washable laundry bag",

            "2 pack xl laundry bag",

            "aegero laundry bag",

            "amazon laundry bag",

            "amazon travel laundry bag",

        ],

    },
    "B0D9W576KQ": {
        "brand": "HOMEHIVE",
        "product_title": "HOMEHIVE 20 Clear PVC Jewelry Storage Bags Anti Tarnish Zipper Bags",
        "product_category": "jewelry_storage_bag",
        "require_brand_match": "true",
        "strong_keywords": [
            "clear PVC jewelry bags",
            "PVC jewelry storage bags",
            "anti tarnish jewelry bags",
            "zipper jewelry bags",
            "HOMEHIVE jewelry storage bags",
            "HOMEHIVE clear PVC jewelry bags",
            "HOMEHIVE anti tarnish jewelry bags",
            "HOMEHIVE travel jewelry organizer",
        ],
        "exact_phrases": [
            "HOMEHIVE jewelry storage bags",
            "HOMEHIVE clear PVC jewelry bags",
            "HOMEHIVE anti tarnish jewelry bags",
            "HOMEHIVE 20 clear bags",
            "HOMEHIVE 20 PVC",
        ],
        "variant_attributes": [
            "20 clear bags",
            "20 PVC",
            "clear PVC",
            "clear zipper jewelry bags",
            "zipper jewelry bags",
        ],
        "broad_category_keywords": [
            "jewelry organizer",
            "jewelry storage",
            "storage bags",
            "travel jewelry pouch",
            "travel jewelry organizer",
            "necklace storage",
            "ring earring storage",
        ],
    },

}





def looks_like_asin(value: str) -> bool:

    text = (value or "").strip().upper()

    if not STANDALONE_ASIN_RE.match(text):

        return False

    return any(ch.isdigit() for ch in text)





def extract_asin_from_text(text: str) -> str | None:

    cleaned = (text or "").strip()

    if not cleaned:

        return None

    match = AMAZON_URL_ASIN_RE.search(cleaned)

    if match:

        return match.group(1).upper()

    if looks_like_asin(cleaned):

        return cleaned.upper()

    return None





def is_amazon_url(text: str) -> bool:

    return bool(AMAZON_HOST_RE.search(text or ""))





def is_amazon_product_url(text: str) -> bool:

    cleaned = (text or "").strip()

    if not cleaned or not AMAZON_HOST_RE.search(cleaned):

        return False

    return extract_asin_from_text(cleaned) is not None





def amazon_marketplace_from_host(host: str) -> str:

    return (host or "").lower().removeprefix("www.")





def normalize_amazon_product_url(raw: str) -> str | None:

    """归一化为 https://{marketplace}/dp/{ASIN}，去掉 ref/tag/psc/utm 等追踪参数。"""

    text = (raw or "").strip()

    if not text:

        return None

    if not re.match(r"^https?://", text, re.I):

        text = f"https://{text}"

    asin = extract_asin_from_text(text)

    if not asin:

        return None

    parsed = urlparse(text)

    host = (parsed.netloc or "").lower()

    if not host or not AMAZON_HOST_RE.search(host):

        return None

    return f"https://{host}/dp/{asin.upper()}"





def extract_amazon_product_slug(raw: str) -> str | None:

    text = (raw or "").strip()

    if not text:

        return None

    if not re.match(r"^https?://", text, re.I):

        text = f"https://{text}"

    path = unquote(urlparse(text).path or "")

    match = AMAZON_SLUG_BEFORE_PRODUCT_RE.search(path)

    if match:

        return match.group(1)

    parts = [part for part in path.split("/") if part]

    for index, part in enumerate(parts):

        if part.lower() in {"dp", "gp", "product"}:

            if index > 0 and parts[index - 1].lower() not in {"dp", "gp", "product"}:

                return parts[index - 1]

        if STANDALONE_ASIN_RE.match(part) and index > 0:

            return parts[index - 1]

    return None





def extract_amazon_product_keywords(raw: str) -> list[str]:

    """从 slug 提取全部可用 token（兼容旧字段 product_keywords）。"""

    slug = extract_amazon_product_slug(raw)

    if not slug:

        return []

    normalized = slug.replace("\uFF0C", "-").replace("\u3001", "-").replace(",", "-")

    tokens = re.split(r"[-_\s]+", normalized)

    keywords: list[str] = []

    seen: set[str] = set()

    for token in tokens:

        word = token.strip().lower()

        if len(word) < 3 or word in AMAZON_PATH_STOPWORDS or word in seen:

            continue

        if not re.fullmatch(r"[a-z0-9]+", word):

            continue

        seen.add(word)

        keywords.append(word)

    return keywords[:12]





def _infer_strong_phrases_from_tokens(tokens: set[str], slug: str | None) -> list[str]:

    phrases: list[str] = []

    slug_lower = (slug or "").lower()



    def add(phrase: str) -> None:

        key = phrase.strip().lower()

        if key and key not in phrases:

            phrases.append(key)



    if "laundry" in tokens:

        add("laundry bag")

        add("travel laundry bag")

        add("drawstring laundry bag")

        add("machine washable laundry bag")

        add("laundry hamper bag")

        add("dirty clothes organizer")

        add("amazon laundry bag")

        add("amazon travel laundry bag")

    if "drawstring" in tokens and "laundry" in tokens:

        add("drawstring laundry bag")

    if "organizer" in tokens and "laundry" in tokens:

        add("dirty clothes organizer")

    if "xl" in slug_lower or "large" in tokens:

        add("2 pack xl laundry bag")



    return phrases





def build_amazon_product_relevance_profile(

    *,

    asin: str,

    slug: str | None,

    slug_tokens: list[str],

) -> dict[str, str | list[str]]:

    """构建强/弱关键词、搜索词与负向词。"""

    token_set = {t.lower() for t in slug_tokens}

    asin_upper = asin.upper()

    profile = AMAZON_ASIN_PROFILES.get(asin_upper, {})



    strong: list[str] = []

    seen_strong: set[str] = set()



    def add_strong(value: str) -> None:

        text = value.strip()
        key = text.lower()

        if not key or key in seen_strong:

            return

        seen_strong.add(key)

        strong.append(text)



    for phrase in profile.get("strong_keywords") or []:

        add_strong(str(phrase))

    for phrase in _infer_strong_phrases_from_tokens(token_set, slug):

        add_strong(phrase)



    brand = str(profile.get("brand") or "").strip()

    if brand:
        category = str(profile.get("product_category") or "").strip()
        if category == "laundry_bag":
            add_strong(f"{brand} laundry bag")



    weak = [t for t in slug_tokens if t.lower() in AMAZON_WEAK_TOKENS]

    strong_tokens = [t for t in slug_tokens if t.lower() not in AMAZON_WEAK_TOKENS and t.lower() not in seen_strong]



    search_keywords: list[str] = []

    seen_search: set[str] = set()

    for phrase in profile.get("exact_phrases") or []:
        text = str(phrase).strip()
        key = text.lower()
        if text and " " in text and key not in seen_search:
            seen_search.add(key)
            search_keywords.append(text)

    for phrase in strong:

        if " " not in phrase:

            continue

        key = phrase.lower()

        if key not in seen_search:

            seen_search.add(key)

            search_keywords.append(phrase)



    negative = list(DEFAULT_NEGATIVE_KEYWORDS)



    return {

        "brand": brand or None,

        "product_category": str(profile.get("product_category") or "") or None,
        "product_title": str(profile.get("product_title") or "") or None,
        "exact_phrases": list(profile.get("exact_phrases") or []),
        "variant_attributes": list(profile.get("variant_attributes") or []),
        "broad_category_keywords": list(profile.get("broad_category_keywords") or []),
        "require_brand_match": str(profile.get("require_brand_match") or "").lower(),

        "strong_keywords": strong,

        "weak_keywords": weak,

        "negative_keywords": negative,

        "search_keywords": search_keywords[:12],

        "strong_tokens": strong_tokens,
        "product_videos": list(profile.get("product_videos") or []),

    }





def parse_amazon_product_url(raw: str) -> dict[str, str | list[str]] | None:

    """解析 Amazon 商品链接，返回 seed 元数据。"""

    normalized = normalize_amazon_product_url(raw)

    if not normalized:

        return None

    asin = extract_asin_from_text(normalized)

    if not asin:

        return None

    parsed = urlparse(normalized)

    marketplace = amazon_marketplace_from_host(parsed.netloc)

    slug = extract_amazon_product_slug(raw)

    product_keywords = extract_amazon_product_keywords(raw)

    relevance = build_amazon_product_relevance_profile(

        asin=asin,

        slug=slug,

        slug_tokens=product_keywords,

    )

    payload: dict[str, str | list[str]] = {

        "url": (raw or "").strip(),

        "normalized_url": normalized,

        "platform": "amazon",

        "asin": asin.upper(),

        "marketplace": marketplace,

        "source_type": "amazon_product",

        "product_keywords": product_keywords,

        "strong_keywords": list(relevance.get("strong_keywords") or []),

        "weak_keywords": list(relevance.get("weak_keywords") or []),

        "negative_keywords": list(relevance.get("negative_keywords") or []),

        "search_keywords": list(relevance.get("search_keywords") or []),
        "exact_phrases": list(relevance.get("exact_phrases") or []),
        "variant_attributes": list(relevance.get("variant_attributes") or []),
        "broad_category_keywords": list(relevance.get("broad_category_keywords") or []),

    }
    if relevance.get("product_videos"):
        payload["product_videos"] = list(relevance.get("product_videos") or [])

    if slug:

        payload["title_slug"] = slug

    if relevance.get("brand"):

        payload["brand"] = relevance["brand"]

    if relevance.get("product_category"):

        payload["product_category"] = relevance["product_category"]
    if relevance.get("product_title"):
        payload["product_title"] = relevance["product_title"]
    if relevance.get("require_brand_match"):
        payload["require_brand_match"] = relevance["require_brand_match"]

    return payload





def parse_amazon_product_input(raw: str) -> dict[str, str | list[str]] | None:

    """Parse an Amazon product URL or bare ASIN into the same product seed payload."""

    text = (raw or "").strip()

    if not text:

        return None

    seed = parse_amazon_product_url(text)

    if seed:

        return seed

    asin = extract_asin_from_text(text)

    if not asin:

        return None

    return parse_amazon_product_url(f"https://www.amazon.com/dp/{asin}")



def build_amazon_seeds_from_urls(urls: list[str]) -> list[dict[str, str]]:

    seeds: list[dict[str, str]] = []

    seen: set[str] = set()

    for raw in urls or []:

        seed = parse_amazon_product_input(raw)

        if not seed:

            continue

        key = seed["normalized_url"]

        if key in seen:

            continue

        seen.add(key)

        seeds.append(seed)

    return seeds


