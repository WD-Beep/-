"""Instagram URL 规范化测试。"""

from app.services.instagram_urls import (
    is_instagram_post_url,
    is_instagram_profile_url,
    normalize_instagram_post_url,
    normalize_instagram_profile_url,
    post_url_from_apify_raw,
    profile_url_from_apify_raw,
)


def test_normalize_profile_url_from_username():
    assert normalize_instagram_profile_url("mamartiina") == "https://www.instagram.com/mamartiina/"
    assert (
        normalize_instagram_profile_url("https://www.instagram.com/mamartiina")
        == "https://www.instagram.com/mamartiina/"
    )


def test_normalize_post_url_from_shortcode():
    assert (
        normalize_instagram_post_url(None, {"shortCode": "DZHfLJgCLRt", "type": "GraphImage"})
        == "https://www.instagram.com/p/DZHfLJgCLRt/"
    )
    assert (
        normalize_instagram_post_url(None, {"shortcode": "ABC", "productType": "clips"})
        == "https://www.instagram.com/reel/ABC/"
    )


def test_reject_caption_or_hashtag_as_profile():
    assert normalize_instagram_profile_url("Dolce vita mode ON") is None
    assert normalize_instagram_profile_url("https://www.instagram.com/explore/tags/travel/") is None


def test_profile_url_from_apify_does_not_use_post_url_field():
    raw = {
        "ownerUsername": "creator_one",
        "url": "https://www.instagram.com/p/SHORT123/",
    }
    assert profile_url_from_apify_raw(raw) == "https://www.instagram.com/creator_one/"
    assert post_url_from_apify_raw(raw) == "https://www.instagram.com/p/SHORT123/"


def test_sanitize_missing_protocol():
    url = normalize_instagram_profile_url("www.instagram.com/demo_user/")
    assert url == "https://www.instagram.com/demo_user/"
    assert is_instagram_profile_url(url)
    post = normalize_instagram_post_url("instagram.com/p/AbCdEf/")
    assert post == "https://www.instagram.com/p/AbCdEf/"
    assert is_instagram_post_url(post)
