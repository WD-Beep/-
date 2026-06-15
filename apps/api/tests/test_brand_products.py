"""真实品牌 seed 定义测试。"""

from app.data.brand_products import BRAND_PRODUCT_SEEDS, format_brand_product_label


def test_brand_product_seeds_count_and_unique_slugs():
    assert len(BRAND_PRODUCT_SEEDS) == 11
    slugs = [item["slug"] for item in BRAND_PRODUCT_SEEDS]
    assert len(slugs) == len(set(slugs))


def test_brand_product_labels():
    assert format_brand_product_label("珺临", "EPEDAL24") == "珺临 · EPEDAL24"
    assert format_brand_product_label("哆莱瑞", "RecoverJoy") == "哆莱瑞 · RecoverJoy"
    assert format_brand_product_label("哆莱瑞", "JourCraf") == "哆莱瑞 · JourCraf"


def test_duolairui_has_two_distinct_brands():
    duolairui = [item for item in BRAND_PRODUCT_SEEDS if item["name"] == "哆莱瑞"]
    assert len(duolairui) == 2
    brands = {item["brand"] for item in duolairui}
    assert brands == {"RecoverJoy", "JourCraf"}
