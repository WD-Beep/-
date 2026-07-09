"""Admin sales data bootstrap safety checks."""

from __future__ import annotations

from app.data.brand_products import BRAND_PRODUCT_SEEDS
from app.scripts.admin_sales_data_bootstrap import (
    SALES_BRAND_ASSIGNMENTS,
    is_obvious_test_product,
)


def test_sales_brand_assignments_cover_sales1_to_sales11_once() -> None:
    assert [item.username for item in SALES_BRAND_ASSIGNMENTS] == [
        f"sales{index}" for index in range(1, 12)
    ]
    assert [item.slug for item in SALES_BRAND_ASSIGNMENTS] == [
        "junlin-epedal24",
        "duolaiwei-aquorix",
        "duolairui-recoverjoy",
        "qianyu-scandihome",
        "duolaida-acestrike",
        "baibo-p-travel",
        "oce-oce-gear",
        "junyu-p-travel-design",
        "duolaiji-homehive",
        "jiuyu-bbcreat",
        "hongbolang",
    ]
    assert len({item.slug for item in SALES_BRAND_ASSIGNMENTS}) == 11


def test_seed_brand_products_match_required_sales_brands() -> None:
    seed_slugs = {item["slug"] for item in BRAND_PRODUCT_SEEDS}
    assignment_slugs = {item.slug for item in SALES_BRAND_ASSIGNMENTS}

    assert assignment_slugs <= seed_slugs
    assert "duolairui-jourcraf" not in seed_slugs
    assert "hongbolang" in seed_slugs


def test_obvious_test_product_detection_is_conservative() -> None:
    assert is_obvious_test_product(name="Test Product", slug="test-product")
    assert is_obvious_test_product(name="测试产品B-12345678", slug="test-product-b-12345678")
    assert is_obvious_test_product(name="Delete Test Product", slug="delete-test-product")
    assert is_obvious_test_product(name="Monthly Product abc123", slug="monthly-product-abc123")
    assert is_obvious_test_product(name="Amazon跨产品B-abcdef12", slug="amazon-cross-b-abcdef12")

    assert not is_obvious_test_product(name="珺临", slug="junlin-epedal24")
    assert not is_obvious_test_product(name="弘博朗", slug="hongbolang")
