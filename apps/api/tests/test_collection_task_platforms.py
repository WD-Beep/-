"""采集任务多平台 schema 校验。"""

import pytest
from pydantic import ValidationError

from app.models.enums import CollectionMode
from app.schemas.collection_task import CollectionTaskCreate, CollectionTaskUpdate
from app.services.collection_task import CollectionTaskService


def _base_payload(**overrides):
    payload = {
        "name": "test task",
        "collection_mode": "discovery",
        "keywords": ["amazon"],
        "schedule_enabled": False,
        "email_enabled": False,
        "email_recipients": [],
    }
    payload.update(overrides)
    return payload


def test_create_youtube_single_platform():
    task = CollectionTaskCreate(**_base_payload(platform="youtube", platforms=["youtube"]))
    assert task.platform == "youtube"
    assert task.platforms == ["youtube"]


def test_create_tiktok_single_platform():
    task = CollectionTaskCreate(**_base_payload(platform="tiktok", platforms=["tiktok"]))
    assert task.platform == "tiktok"
    assert task.platforms == ["tiktok"]


def test_create_facebook_single_platform():
    task = CollectionTaskCreate(**_base_payload(platform="facebook", platforms=["facebook"]))
    assert task.platform == "facebook"
    assert task.platforms == ["facebook"]


def test_create_rejects_seed_only_platforms_in_discovery_mode():
    for platform in ("pinterest", "shopmy"):
        with pytest.raises(ValidationError, match="seed"):
            CollectionTaskCreate(**_base_payload(platform=platform, platforms=[platform]))


def test_link_import_accepts_pinterest_ltk_shopmy_urls():
    cases = [
        ("pinterest", "https://www.pinterest.com/example_user/"),
        ("pinterest", "https://www.pinterest.com/pin/123/"),
        ("ltk", "https://www.shopltk.com/explore/example_user"),
        ("shopmy", "https://shopmy.us/example_user"),
    ]
    for _platform, url in cases:
        task = CollectionTaskCreate(
            name="url import",
            collection_mode=CollectionMode.LINK_IMPORT,
            platform="instagram",
            input_urls=[url],
        )
        assert task.collection_mode == CollectionMode.LINK_IMPORT
        assert task.input_urls
        assert task.input_urls[0].startswith(url.rstrip("/"))


def test_create_multi_platform_instagram_youtube():
    task = CollectionTaskCreate(
        **_base_payload(platform="multi", platforms=["instagram", "youtube"])
    )
    assert task.platform == "multi"
    assert task.platforms == ["instagram", "youtube"]


def test_create_allows_mixed_keyword_platforms_with_seed_platforms():
    task = CollectionTaskCreate(
        **_base_payload(platform="multi", platforms=["instagram", "pinterest", "shopmy"])
    )
    assert task.platform == "multi"
    assert task.platforms == ["instagram", "pinterest", "shopmy"]


def test_create_legacy_instagram_only_platform():
    task = CollectionTaskCreate(**_base_payload(platform="instagram"))
    assert task.platform == "instagram"
    assert task.platforms == ["instagram"]


def test_create_rejects_twitter_platform():
    with pytest.raises(ValidationError):
        CollectionTaskCreate(**_base_payload(platform="twitter", platforms=["twitter"]))


def test_create_rejects_twitter_in_platforms():
    with pytest.raises(ValidationError):
        CollectionTaskCreate(**_base_payload(platform="multi", platforms=["instagram", "twitter"]))


def test_update_rejects_seed_only_platform_in_discovery_mode():
    with pytest.raises(ValidationError, match="seed"):
        CollectionTaskUpdate(
            collection_mode=CollectionMode.DISCOVERY,
            platform="pinterest",
            platforms=["pinterest"],
        )


def test_link_seed_discovery_accepts_seed_only_platforms():
    task = CollectionTaskCreate(
        name="seed discovery",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY,
        platform="multi",
        platforms=["pinterest", "shopmy"],
        keywords=["amazon finds"],
    )
    assert task.collection_mode == CollectionMode.LINK_SEED_DISCOVERY
    assert task.platforms == ["pinterest", "shopmy"]


def test_link_seed_discovery_accepts_asin_only_input():
    task = CollectionTaskCreate(
        name="seed asin",
        collection_mode=CollectionMode.LINK_SEED_DISCOVERY,
        platform="pinterest",
        platforms=["pinterest"],
        input_urls=["B0D9W576KQ"],
    )
    assert task.collection_mode == CollectionMode.LINK_SEED_DISCOVERY
    assert task.input_urls == ["https://www.amazon.com/dp/B0D9W576KQ"]
    seeds = task.run_checkpoint.get("amazon_product_seeds") or []
    assert seeds and seeds[0]["asin"] == "B0D9W576KQ"


def test_update_platforms_only():
    task = CollectionTaskUpdate(platforms=["youtube", "tiktok"])
    assert task.platform == "multi"
    assert task.platforms == ["youtube", "tiktok"]


def test_update_keyword_task_allows_empty_input_urls():
    task = CollectionTaskUpdate(
        collection_mode=CollectionMode.DISCOVERY,
        platform="tiktok",
        platforms=["tiktok"],
        keywords=["makeup bag"],
        input_urls=[],
        filter_include_keywords=["brand deal", "collab"],
        filter_exclude_keywords=["giveaway", "fan page"],
    )
    assert task.input_urls == []
    assert task.filter_include_keywords == ["brand deal", "collab"]
    assert task.filter_exclude_keywords == ["giveaway", "fan page"]


def test_update_legacy_platform_only():
    task = CollectionTaskUpdate(platform="youtube")
    assert task.platform == "youtube"
    assert task.platforms == ["youtube"]


def test_competitor_product_rejects_url_only_platforms():
    for platform in ("pinterest", "ltk", "shopmy"):
        with pytest.raises(ValidationError, match="链接导入"):
            CollectionTaskCreate(
                name="竞品",
                collection_mode=CollectionMode.COMPETITOR_PRODUCT,
                platform=platform,
                platforms=[platform],
                keywords=["portable fan"],
            )


def test_competitor_product_accepts_core_discovery_platforms():
    for platform in ("instagram", "youtube", "tiktok", "facebook"):
        task = CollectionTaskCreate(
            name="竞品",
            collection_mode=CollectionMode.COMPETITOR_PRODUCT,
            platform=platform,
            platforms=[platform],
            keywords=["portable fan"],
        )
        assert task.platform == platform
        assert task.platforms == [platform]


def test_competitor_product_legacy_platform_field_cannot_bypass_platforms_validation():
    with pytest.raises(ValidationError, match="链接导入"):
        CollectionTaskCreate(
            name="竞品",
            collection_mode=CollectionMode.COMPETITOR_PRODUCT,
            platform="pinterest",
            platforms=[],
            keywords=["portable fan"],
        )


def test_competitor_product_update_rejects_url_only_platform():
    with pytest.raises(ValidationError, match="链接导入"):
        CollectionTaskUpdate(
            collection_mode=CollectionMode.COMPETITOR_PRODUCT,
            platform="shopmy",
            platforms=["shopmy"],
        )


def test_link_import_multi_platform_sets_platforms_and_checkpoint():
    task = CollectionTaskCreate(
        name="multi import",
        collection_mode=CollectionMode.LINK_IMPORT,
        platform="instagram",
        input_urls=[
            "https://www.instagram.com/example_a/",
            "https://www.pinterest.com/example_user/",
        ],
    )
    assert task.platform == "multi"
    assert task.platforms == ["instagram", "pinterest"]
    assert task.run_checkpoint.get("link_import_platforms") == ["instagram", "pinterest"]


def test_link_import_rejects_valid_and_invalid_mixed():
    with pytest.raises(ValidationError, match="第 2 行"):
        CollectionTaskCreate(
            name="invalid mixed",
            collection_mode=CollectionMode.LINK_IMPORT,
            input_urls=[
                "https://www.pinterest.com/example_user/",
                "https://unknown.example/x",
            ],
        )


def test_link_import_pinterest_pin_sets_platform_fields_and_checkpoint():
    pin_url = "https://www.pinterest.com/pin/123/"
    task = CollectionTaskCreate(
        name="pinterest pin import",
        collection_mode=CollectionMode.LINK_IMPORT,
        platform="instagram",
        input_urls=[pin_url],
    )
    assert task.collection_mode == CollectionMode.LINK_IMPORT
    assert task.platform == "pinterest"
    assert task.platforms == ["pinterest"]
    assert task.input_urls == ["https://www.pinterest.com/pin/123"]
    assert task.run_checkpoint.get("link_import_platforms") == ["pinterest"]
    assert task.run_checkpoint.get("link_import_source") is True


def test_create_task_persists_quality_filter_fields():
    task = CollectionTaskCreate(
        **_base_payload(
            platform="youtube",
            platforms=["youtube"],
            min_followers_count=10000,
            min_engagement_rate=1.5,
            require_email=True,
            require_contact=True,
            insert_qualified_only=True,
            strict_quality_filter=False,
            export_qualified_only=True,
        )
    )
    assert task.min_followers_count == 10000
    assert task.min_engagement_rate == 1.5
    assert task.require_email is True
    assert task.require_contact is True
    assert task.insert_qualified_only is True
    assert task.strict_quality_filter is False
    assert task.export_qualified_only is True


def test_create_service_applies_high_value_first_defaults_for_keyword_collection():
    task = CollectionTaskCreate(**_base_payload(platform="youtube", platforms=["youtube"]))
    payload = CollectionTaskService._serialize_task_data(task.model_dump())
    payload = CollectionTaskService._apply_high_value_first_defaults(payload, set(task.model_fields_set))

    assert payload["min_followers_count"] == 10000
    assert payload["min_engagement_rate"] is None
    assert payload["require_email"] is False
    assert payload["require_contact"] is False
    assert payload["strict_quality_filter"] is False
    assert payload["insert_qualified_only"] is True
    assert payload["export_qualified_only"] is True
    assert payload["run_checkpoint"]["quality_strategy"] == "high_value_first"


def test_create_service_respects_explicit_quality_settings():
    task = CollectionTaskCreate(
        **_base_payload(
            platform="youtube",
            platforms=["youtube"],
            min_followers_count=None,
            min_engagement_rate=1.5,
            insert_qualified_only=False,
            export_qualified_only=False,
        )
    )
    payload = CollectionTaskService._serialize_task_data(task.model_dump())
    payload = CollectionTaskService._apply_high_value_first_defaults(payload, set(task.model_fields_set))

    assert payload["min_followers_count"] is None
    assert payload["min_engagement_rate"] == 1.5
    assert payload["insert_qualified_only"] is False
    assert payload["export_qualified_only"] is False
