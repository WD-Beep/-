"""产品/品牌可见性：过滤测试、临时、自动生成数据。"""

from __future__ import annotations

import re
from typing import Protocol

from app.data.brand_products import BRAND_PRODUCT_SEEDS

_HASH_SUFFIX_RE = re.compile(r"-[0-9a-f]{8}$", re.IGNORECASE)
_TEST_KEYWORDS = (
    "测试产品",
    "新品测试",
    "话术测试",
    "amazon跨产品",
    "test",
    "demo",
    "mock",
    "temp",
    "临时",
    "示例",
)

_SEED_SLUGS = {item["slug"] for item in BRAND_PRODUCT_SEEDS}
_SYSTEM_SLUGS = {"default"}
_TEST_PREFIXES = ("codex-", "qa-", "monthlyprodect", "monthly-product")


class ProductLike(Protocol):
    name: str
    slug: str
    brand: str | None
    is_archived: bool
    is_hidden: bool
    is_test: bool


def _combined_text(name: str, slug: str, brand: str | None) -> str:
    return f"{name} {slug} {brand or ''}".lower()


def looks_like_test_product(*, name: str, slug: str, brand: str | None = None) -> bool:
    name = (name or "").strip()
    slug = (slug or "").strip().lower()

    if slug in _SYSTEM_SLUGS or slug in _SEED_SLUGS:
        return False

    combined = _combined_text(name, slug, brand)

    for keyword in _TEST_KEYWORDS:
        if keyword.lower() in combined:
            return True

    if _HASH_SUFFIX_RE.search(name) or _HASH_SUFFIX_RE.search(slug):
        return True

    if slug.startswith(("test-product", "dup-slug-")) or slug.startswith(_TEST_PREFIXES):
        return True

    return False


def is_product_visible(product: ProductLike, *, include_test: bool = False) -> bool:
    if include_test:
        return True
    if product.is_archived or product.is_hidden or product.is_test:
        return False
    return not looks_like_test_product(
        name=product.name,
        slug=product.slug,
        brand=product.brand,
    )


def infer_test_flags(*, name: str, slug: str, brand: str | None = None) -> tuple[bool, bool, str | None]:
    """Return (is_test, is_hidden, created_source) for new rows."""
    if looks_like_test_product(name=name, slug=slug, brand=brand):
        return True, True, "auto_test"
    return False, False, None
