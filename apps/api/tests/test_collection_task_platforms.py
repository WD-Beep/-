"""采集任务多平台 schema 校验。"""

import pytest
from pydantic import ValidationError

from app.schemas.collection_task import CollectionTaskCreate, CollectionTaskUpdate


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


def test_create_pinterest_ltk_shopmy_platforms():
    for platform in ("pinterest", "ltk", "shopmy"):
        task = CollectionTaskCreate(**_base_payload(platform=platform, platforms=[platform]))
        assert task.platform == platform
        assert task.platforms == [platform]


def test_create_multi_platform_instagram_youtube():
    task = CollectionTaskCreate(
        **_base_payload(platform="multi", platforms=["instagram", "youtube", "pinterest"])
    )
    assert task.platform == "multi"
    assert task.platforms == ["instagram", "youtube", "pinterest"]


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


def test_update_platforms_only():
    task = CollectionTaskUpdate(platforms=["youtube", "tiktok"])
    assert task.platform == "multi"
    assert task.platforms == ["youtube", "tiktok"]


def test_update_legacy_platform_only():
    task = CollectionTaskUpdate(platform="youtube")
    assert task.platform == "youtube"
    assert task.platforms == ["youtube"]
