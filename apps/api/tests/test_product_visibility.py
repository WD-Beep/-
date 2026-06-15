"""产品可见性过滤测试。"""

from __future__ import annotations

from app.services.product_visibility import is_product_visible, looks_like_test_product


class _Product:
    def __init__(
        self,
        *,
        name: str,
        slug: str,
        brand: str | None = None,
        is_archived: bool = False,
        is_hidden: bool = False,
        is_test: bool = False,
    ) -> None:
        self.name = name
        self.slug = slug
        self.brand = brand
        self.is_archived = is_archived
        self.is_hidden = is_hidden
        self.is_test = is_test


def test_looks_like_test_product_patterns():
    assert looks_like_test_product(name="测试产品B-f0548c4c", slug="test-product-b-f0548c4c")
    assert looks_like_test_product(name="Amazon跨产品B-a04dbb73", slug="amazon-cross-b-a04dbb73")
    assert looks_like_test_product(name="Demo Brand", slug="demo-brand")
    assert looks_like_test_product(name="新品测试-abc12345", slug="new-product-abc12345")
    assert not looks_like_test_product(name="默认项目", slug="default", brand="默认品牌")
    assert not looks_like_test_product(name="珺临", slug="junlin-epedal24", brand="EPEDAL24")
    assert not looks_like_test_product(name="OCE", slug="oce-oce-gear", brand="OCE GEAR")


def test_is_product_visible_respects_flags_and_heuristics():
    hidden = _Product(name="真实产品", slug="real-product", is_hidden=True)
    assert not is_product_visible(hidden)

    flagged = _Product(name="任意名称", slug="any-slug", is_test=True)
    assert not is_product_visible(flagged)

    test_like = _Product(name="测试产品B-9b793a3a", slug="test-product-b-9b793a3a")
    assert not is_product_visible(test_like)

    real = _Product(name="珺临", slug="junlin-epedal24", brand="EPEDAL24")
    assert is_product_visible(real)

    include = _Product(name="测试产品B-9b793a3a", slug="test-product-b-9b793a3a")
    assert is_product_visible(include, include_test=True)
