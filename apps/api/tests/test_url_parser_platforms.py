"""链接解析：社媒与导购平台识别。"""

from app.services.url_parser import (
    detect_platform,
    parse_raw_urls,
    summarize_link_import_urls,
    tiktok_profile_from_url,
)


def test_detect_platform_for_social_and_guide_platforms():
    cases = [
        ("https://www.instagram.com/example/", "instagram"),
        ("https://www.youtube.com/@example", "youtube"),
        ("https://www.tiktok.com/@example", "tiktok"),
        ("https://www.facebook.com/example", "facebook"),
        ("https://www.pinterest.com/example_user/", "pinterest"),
        ("https://www.pinterest.com/pin/123/", "pinterest"),
        ("https://www.shopltk.com/explore/example_user", "ltk"),
        ("https://shopmy.us/example_user", "shopmy"),
        ("https://www.amazon.com/dp/B00VOEZYHI", "amazon"),
    ]
    for url, expected in cases:
        assert detect_platform(url) == expected


def test_detect_platform_rejects_non_profile_tiktok_video():
    assert detect_platform("https://www.tiktok.com/@creator/video/123") == "tiktok"
    assert detect_platform("https://www.tiktok.com/discover") is None


def test_summarize_link_import_urls_groups_and_detects_mixed():
    raw = "\n".join(
        [
            "https://www.instagram.com/a/",
            "https://www.instagram.com/b/",
            "https://www.pinterest.com/example_user/",
            "https://www.amazon.com/dp/B00VOEZYHI",
            "https://unknown.example/x",
        ]
    )
    summary = summarize_link_import_urls(raw)
    assert summary["counts"]["instagram"] == 2
    assert summary["counts"]["pinterest"] == 1
    assert summary["invalid_count"] == 1
    assert summary["mixed_amazon_and_profiles"] is True
    assert str(summary["invalid_lines"][0]).startswith("第 5 行")


def test_tiktok_profile_from_url():
    profile = tiktok_profile_from_url("https://www.tiktok.com/@creator")
    assert profile is not None
    assert profile.username == "creator"
    assert profile.platform == "tiktok"


def test_parse_raw_urls_accepts_youtube_channel():
    valid, invalid = parse_raw_urls("https://www.youtube.com/@creator")
    assert len(valid) == 1
    assert valid[0]["platform"] == "youtube"
    assert invalid == []


def test_parse_raw_urls_accepts_pinterest_pin_url():
    pin_url = "https://www.pinterest.com/pin/123/"
    valid, invalid = parse_raw_urls(pin_url)
    assert invalid == []
    assert len(valid) == 1
    assert valid[0]["platform"] == "pinterest"
    assert valid[0]["url"] == "https://www.pinterest.com/pin/123"
