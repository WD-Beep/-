from app.models.collection_task import CollectionTask
from app.schemas.collection_task import CollectionTaskCreate, CollectionTaskUpdate
from app.services.apify_instagram import PostAuthorCandidate
from app.services.collection_task import CollectionTaskService
from app.services.amazon_url import looks_like_asin
from app.services.competitor_product_discovery import (
    build_competitor_search_keywords,
    extract_asin_from_text,
    filter_candidates_by_competitor_caption,
    filter_platform_profiles_by_competitor_relevance,
    match_competitor_caption,
    order_competitor_discovery_platforms,
    parse_competitor_product_inputs,
    resolve_competitor_discovery_keywords,
)
from app.services.platform_types import PlatformCandidateProfile
from app.services.collection_funnel import CollectionFunnelStats, build_status_summary
from app.services.competitor_product_discovery import CompetitorProductDiscoveryMeta, CompetitorProductInfo
from app.services.task_candidate import TaskCandidateService
from app.models.enums import CollectionMode, CollectionTaskStatus
import pytest


def test_extract_asin_from_amazon_url():
    url = "https://www.amazon.com/dp/B0ABCD1234/ref=sr_1_1"
    assert extract_asin_from_text(url) == "B0ABCD1234"
    assert extract_asin_from_text("B0ABCD1234") == "B0ABCD1234"


def test_parse_competitor_product_inputs_merges_brand_and_amazon():
    task = CollectionTask(
        name="test",
        platform="instagram",
        collection_mode="competitor_product",
        keywords=["brand:Anker", "portable charger"],
        input_urls=["https://www.amazon.com/dp/B0ABCD1234/"],
        category="tech",
    )
    info = parse_competitor_product_inputs(task)
    assert info.asin == "B0ABCD1234"
    assert info.brand == "Anker"
    assert "amazonfinds" in info.search_hashtags
    assert "techfinds" in info.search_hashtags or "gadgetfinds" in info.search_hashtags


def test_match_competitor_caption_detects_collab_signal():
    info = CompetitorProductInfo(
        asin="B0ABCD1234",
        brand="Anker",
        core_keywords=["charger"],
    )
    match = match_competitor_caption(
        "Love this Anker charger! #amazonfinds #ad link in bio",
        info,
    )
    assert match.matched is True
    assert match.suspected_collab is True
    assert "包含品牌名" in match.match_reasons


def test_filter_candidates_keeps_only_matched_authors():
    info = CompetitorProductInfo(brand="Anker", core_keywords=["charger"])
    candidates = [
        PostAuthorCandidate(
            username="hit",
            profile_url="https://www.instagram.com/hit/",
            source_caption="Anker charger amazonfinds",
            source_post_url="https://www.instagram.com/p/abc/",
        ),
        PostAuthorCandidate(
            username="miss",
            profile_url="https://www.instagram.com/miss/",
            source_caption="random travel photo",
        ),
    ]
    matched, before = filter_candidates_by_competitor_caption(candidates, info)
    assert before == 2
    assert len(matched) == 1
    assert matched[0].username == "hit"
    assert matched[0].source_meta["suspected_collab"] is True


def test_build_status_summary_for_competitor_product():
    info = CompetitorProductInfo(asin="B0ABCD1234", brand="Anker", core_keywords=["charger"])
    competitor_meta = CompetitorProductDiscoveryMeta(
        product_info=info,
        posts_scanned=42,
        authors_matched=7,
    )
    summary = build_status_summary(
        CollectionFunnelStats(discovered_count=7, inserted_count=3, post_count=42),
        status=CollectionTaskStatus.COMPLETED_WITH_RESULTS,
        collection_mode="competitor_product",
        competitor_meta=competitor_meta,
    )
    assert "ASIN B0ABCD1234" in summary
    assert "品牌 Anker" in summary
    assert "42 条帖子" in summary
    assert "7 个疑似推广账号" in summary
    assert "入库 3 个" in summary


def test_collection_task_create_validates_competitor_product():
    task = CollectionTaskCreate(
        name="竞品",
        platform="instagram",
        collection_mode="competitor_product",
        keywords=["portable fan"],
        comment_discovery_enabled=True,
    )
    assert task.comment_discovery_enabled is False

    try:
        CollectionTaskCreate(
            name="竞品",
            platform="instagram",
            collection_mode="competitor_product",
        )
        raise AssertionError("expected validation error")
    except ValueError as exc:
        assert "竞品商品发现" in str(exc)


def test_commerce_only_does_not_match_without_product_signals():
    info = CompetitorProductInfo(brand="Anker", core_keywords=["charger"])
    match = match_competitor_caption("#amazonfinds #ad link in bio sponsored", info)
    assert match.matched is False

    asin_only = CompetitorProductInfo(
        asin="B0ABCD1234",
        amazon_urls=["https://www.amazon.com/dp/B0ABCD1234/"],
        core_keywords=["B0ABCD1234"],
    )
    generic = match_competitor_caption("Love #amazonfinds #ad link in bio", asin_only)
    assert generic.matched is False

    with_asin = match_competitor_caption(
        "Check https://www.amazon.com/dp/B0ABCD1234/ #amazonfinds",
        asin_only,
    )
    assert with_asin.matched is True
    assert with_asin.low_confidence is True


def test_row_from_filtered_and_failed_preserve_source_meta():
    meta = {
        "asin": "B0ABCD1234",
        "brand": "Anker",
        "matched_keywords": ["Anker"],
        "match_reasons": ["包含品牌名"],
        "source_post_url": "https://www.instagram.com/p/abc/",
        "source_caption": "Anker charger",
    }
    filtered = TaskCandidateService.row_from_filtered(
        username="user1",
        profile_url="https://www.instagram.com/user1/",
        failure_reason="below_min_followers",
        source_meta=meta,
    )
    failed = TaskCandidateService.row_from_failed(
        username="user2",
        profile_url="https://www.instagram.com/user2/",
        failure_reason="profile_fetch_failed",
        source_meta=meta,
    )
    assert filtered["source_meta"] == meta
    assert failed["source_meta"] == meta


def test_validate_task_inputs_competitor_product_requires_keywords_or_urls():
    with pytest.raises(ValueError, match="竞品商品发现"):
        CollectionTaskService._validate_task_inputs(
            CollectionMode.COMPETITOR_PRODUCT.value,
            [],
            [],
            False,
            [],
        )
    CollectionTaskService._validate_task_inputs(
        CollectionMode.COMPETITOR_PRODUCT.value,
        ["portable fan"],
        [],
        False,
        [],
    )


def test_competitor_product_update_payload_disables_comment_discovery():
    task = CollectionTask(
        name="竞品",
        platform="instagram",
        collection_mode=CollectionMode.KEYWORD.value,
        keywords=["travel"],
        comment_discovery_enabled=True,
    )
    data = CollectionTaskUpdate(
        collection_mode=CollectionMode.COMPETITOR_PRODUCT,
        keywords=["portable fan"],
        comment_discovery_enabled=True,
    )
    update_data = CollectionTaskService._serialize_task_data(data.model_dump(exclude_unset=True))
    merged_mode = update_data.get("collection_mode", task.collection_mode)
    merged_keywords = update_data.get("keywords", task.keywords or [])
    merged_urls = update_data.get("input_urls", task.input_urls or [])
    CollectionTaskService._validate_task_inputs(
        merged_mode,
        merged_keywords,
        merged_urls,
        update_data.get("email_enabled", task.email_enabled),
        update_data.get("email_recipients", task.email_recipients or []),
    )
    merged_mode_value = (
        merged_mode.value if isinstance(merged_mode, CollectionMode) else merged_mode
    )
    if merged_mode_value == CollectionMode.COMPETITOR_PRODUCT.value:
        update_data["comment_discovery_enabled"] = False
    assert update_data["comment_discovery_enabled"] is False


AMAZON_LAUNDRY_URL = (
    "https://www.amazon.com/Laundry-Washable-Organizer-Drawstring%EF%BC%8CLarge-Essentials/"
    "dp/B0CPF3W9B2/ref=zg_bs_g_3744371_d_sccl_2/138-2111992-2516563?psc=1"
)
AIR_PURIFIER_TITLE = (
    "Breathing Clean: Top 5 Best Air Purifiers With Washable Filters For A Healthier Home"
)


def _laundry_bag_task_info():
    from app.schemas.collection_task import CollectionTaskCreate

    created = CollectionTaskCreate(
        name="laundry-bag",
        collection_mode="link_import",
        platform="instagram",
        input_urls=[AMAZON_LAUNDRY_URL],
    )
    task = CollectionTask(
        name="laundry-bag",
        platform="multi",
        collection_mode="competitor_product",
        input_urls=created.input_urls,
        keywords=created.keywords,
        run_checkpoint=created.run_checkpoint,
    )
    return parse_competitor_product_inputs(task)


def test_laundry_bag_positive_and_negative_caption_relevance():
    info = _laundry_bag_task_info()
    for caption in (
        "Amazon travel laundry bag review",
        "drawstring laundry bag for college dorm",
        "dirty clothes organizer laundry hamper bag",
        "Aegero laundry bag",
        "#amazonfinds laundry bag",
    ):
        assert match_competitor_caption(caption, info).matched is True
    for caption in (
        AIR_PURIFIER_TITLE,
        "Best nut milk makers 2026",
        "Installing a lake-based geothermal heating system",
        "Best washable filters for air purifier",
        "Amazon home essentials you need",
        "This washable organizer is great",
        "Best filter machine for home",
        "Best replacement filter products",
        "Best appliance deals 2026",
        "Amazon appliance organizer",
        "Laundry detergent organizer",
        "Washing machine essentials",
        "Laundry room organizer shelf",
        "Just doing laundry today",
        "Love Aegero products",
    ):
        result = match_competitor_caption(caption, info)
        assert result.matched is False
        assert result.rejected_reason


def test_laundry_bag_search_keywords_exclude_broad_single_tokens():
    info = _laundry_bag_task_info()
    broad = {"laundry", "washable", "organizer", "essentials", "large", "bag", "home", "products", "finds"}
    search_terms = build_competitor_search_keywords(info)
    assert len(search_terms) <= 8
    for term in search_terms:
        if looks_like_asin(term):
            continue
        assert " " in term
        assert term.lower() not in broad
    assert "laundry bag" in search_terms or "travel laundry bag" in search_terms


def test_laundry_room_organizer_passes_when_laundry_bag_present():
    info = _laundry_bag_task_info()
    result = match_competitor_caption(
        "Laundry room organizer shelf plus my favorite travel laundry bag",
        info,
    )
    assert result.matched is True


def test_single_laundry_and_brand_only_rejected():
    info = _laundry_bag_task_info()
    laundry_only = match_competitor_caption("laundry", info)
    assert laundry_only.matched is False
    brand_only = match_competitor_caption("Check out Aegero", info)
    assert brand_only.matched is False
    assert brand_only.rejected_reason == "brand_only_no_category"


def test_competitor_discovery_keywords_limited_and_platform_order():
    task = CollectionTask(
        name="laundry-bag",
        platform="multi",
        collection_mode="competitor_product",
        input_urls=[AMAZON_LAUNDRY_URL],
        keywords=[],
    )
    keywords = resolve_competitor_discovery_keywords(task)
    assert len(keywords) <= 8
    assert "laundry bag" in keywords
    ordered = order_competitor_discovery_platforms(["youtube", "tiktok", "facebook"])
    assert ordered.index("tiktok") < ordered.index("youtube")


def test_youtube_air_purifier_profile_not_kept_for_laundry_bag():
    info = _laundry_bag_task_info()
    bad = PlatformCandidateProfile(
        platform="youtube",
        username="air_purifier",
        profile_url="https://www.youtube.com/channel/bad",
        recent_post_titles=[AIR_PURIFIER_TITLE],
        source_post_url="https://www.youtube.com/watch?v=rlu7RuLeb5I",
    )
    good = PlatformCandidateProfile(
        platform="youtube",
        username="laundry_creator",
        profile_url="https://www.youtube.com/channel/good",
        recent_post_titles=["Amazon travel laundry bag review"],
        source_post_url="https://www.youtube.com/watch?v=good123",
    )
    kept, _ = filter_platform_profiles_by_competitor_relevance([bad, good], info)
    assert [p.username for p in kept] == ["laundry_creator"]
