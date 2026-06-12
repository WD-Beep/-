"""collection_filters 单元测试（避免加载 collectors 包循环依赖）。"""



from types import SimpleNamespace



from app.models.collection_task import CollectionTask

from app.services import collection_filters as cf





def _task(**kwargs) -> CollectionTask:
    defaults = {"name": "test", "platform": "instagram", "keywords": ["travel"]}
    defaults.update(kwargs)
    return CollectionTask(**defaults)





def _item(**kwargs):

    defaults = {

        "platform": "instagram",

        "username": "travel_creator",

        "profile_url": "https://www.instagram.com/travel_creator/",

        "followers_count": 50_000,

        "engagement_rate": 2.5,

        "bio": "Lifestyle creator",

        "display_name": None,

        "category": None,

        "niche": None,

        "country": None,

        "language": None,

        "content_topics": None,

        "recent_post_titles": None,

        "tags": None,

        "collaboration_formats": None,

    }

    defaults.update(kwargs)

    return SimpleNamespace(**defaults)





def test_soft_preferences_do_not_block_insertion_filter():

    task = _task(

        min_followers_count=10_000,

        max_followers_count=20_000,

        min_engagement_rate=1.0,

        filter_include_keywords=["travel"],

    )

    item = _item(
        username="shop_creator",
        profile_url="https://www.instagram.com/shop_creator/",
        followers_count=50_000,
        bio="Lifestyle and shopping only",
    )

    assert cf.passes_post_hydration_filters(item, task)

    assert not cf.matches_quality_preferences(item, task)

    reasons = cf.get_quality_preference_mismatch_reasons(item, task)

    assert "above_max_followers" in reasons

    assert "missing_include_keyword" in reasons





def test_exclude_keyword_hard_filter():

    task = _task(filter_exclude_keywords=["giveaway"])

    item = _item(bio="Weekly giveaway for fans")

    result = cf.evaluate_post_hydration_hard_filter(item, task)

    assert not result.passed

    assert result.reason == "excluded_keyword:giveaway"





def test_followers_in_range_matches_preferences():

    task = _task(

        min_followers_count=10_000,

        max_followers_count=20_000,

        filter_include_keywords=["travel"],

    )

    item = _item(followers_count=50_000, bio="travel tips daily")

    assert cf.passes_post_hydration_filters(item, task)

    assert not cf.matches_quality_preferences(item, task)

    assert "above_max_followers" in cf.get_quality_preference_mismatch_reasons(item, task)





def test_discovery_hard_min_followers_floor_and_ceiling():
    task_10k = _task(collection_mode="keyword", min_followers_count=10_000)
    assert cf.discovery_hard_min_followers(task_10k) == 30_000
    task_50k = _task(collection_mode="discovery", min_followers_count=50_000)
    assert cf.discovery_hard_min_followers(task_50k) == 50_000

    task = _task(collection_mode="keyword", min_followers_count=10_000)

    none_followers = _item(followers_count=None, bio="travel")
    r_none = cf.evaluate_post_hydration_hard_filter(none_followers, task)
    assert not r_none.passed
    assert r_none.reason == "below_min_followers"

    r_29999 = cf.evaluate_post_hydration_hard_filter(_item(followers_count=29_999, bio="travel"), task)
    assert not r_29999.passed
    assert r_29999.reason == "below_min_followers"

    assert cf.evaluate_post_hydration_hard_filter(_item(followers_count=30_000, bio="travel"), task).passed
    assert cf.evaluate_post_hydration_hard_filter(_item(followers_count=50_000, bio="travel"), task).passed

    task_50k_req = _task(collection_mode="keyword", min_followers_count=50_000)
    assert not cf.evaluate_post_hydration_hard_filter(_item(followers_count=40_000, bio="travel"), task_50k_req).passed
    assert cf.evaluate_post_hydration_hard_filter(_item(followers_count=50_000, bio="travel"), task_50k_req).passed


def test_urls_mode_hard_min_followers():
    task = _task(collection_mode="urls", min_followers_count=10_000)
    assert cf.discovery_hard_min_followers(task) == 30_000
    low = _item(followers_count=25_000, bio="travel")
    assert not cf.evaluate_post_hydration_hard_filter(low, task).passed
    assert cf.evaluate_post_hydration_hard_filter(_item(followers_count=35_000, bio="travel"), task).passed


def test_mixed_mode_hard_min_followers():
    task = _task(collection_mode="mixed", min_followers_count=50_000)
    assert cf.discovery_hard_min_followers(task) == 50_000
    assert not cf.evaluate_post_hydration_hard_filter(_item(followers_count=40_000, bio="x"), task).passed


def test_comment_mode_min_followers_hard_filter():
    task = _task(collection_mode="comment_authors", min_followers_count=30000)
    low = _item(followers_count=25000, bio="travel tips")
    result = cf.evaluate_post_hydration_hard_filter(low, task)
    assert not result.passed
    assert result.reason == "below_min_followers"
    high = _item(followers_count=35000, bio="travel tips")
    assert cf.evaluate_post_hydration_hard_filter(high, task).passed


def test_invalid_profile_hard_filter():

    task = _task()

    item = _item(username="explore", profile_url="https://www.instagram.com/explore/")

    result = cf.evaluate_post_hydration_hard_filter(item, task)

    assert not result.passed

    assert result.reason == "invalid_profile"


def test_tiktok_profile_passes_platform_validation():
    task = _task(platform="multi", platforms=["tiktok"])
    item = _item(
        platform="tiktok",
        username="chefmike",
        profile_url="https://www.tiktok.com/@chefmike",
        followers_count=None,
    )
    result = cf.evaluate_post_hydration_hard_filter(item, task)
    assert result.passed


def test_youtube_profile_passes_platform_validation():
    task = _task(platform="multi", platforms=["youtube"])
    item = _item(
        platform="youtube",
        username="UC123",
        profile_url="https://www.youtube.com/channel/UC123",
        followers_count=1000,
    )
    result = cf.evaluate_post_hydration_hard_filter(item, task)
    assert result.passed


def test_facebook_profile_passes_platform_validation():
    task = _task(platform="multi", platforms=["facebook"])
    item = _item(
        platform="facebook",
        username="Meta",
        profile_url="https://www.facebook.com/Meta",
        followers_count=1000,
    )
    result = cf.evaluate_post_hydration_hard_filter(item, task)
    assert result.passed


def test_url_only_platform_profiles_pass_validation():
    cases = [
        ("pinterest", "targetcreator", "https://www.pinterest.com/targetcreator/"),
        ("ltk", "targetcreator", "https://www.shopltk.com/explore/targetcreator"),
        ("shopmy", "targetcreator", "https://shopmy.us/targetcreator"),
    ]
    for platform, username, profile_url in cases:
        task = _task(platform=platform, platforms=[platform])
        item = _item(
            platform=platform,
            username=username,
            profile_url=profile_url,
            followers_count=None,
        )
        result = cf.evaluate_post_hydration_hard_filter(item, task)
        assert result.passed


def test_url_only_platform_reserved_urls_fail_validation():
    cases = [
        ("pinterest", "pin", "https://www.pinterest.com/pin/123/"),
        ("ltk", "explore", "https://www.shopltk.com/post/abc"),
        ("shopmy", "shop", "https://shopmy.us/shop"),
    ]
    for platform, username, profile_url in cases:
        task = _task(platform=platform, platforms=[platform])
        item = _item(
            platform=platform,
            username=username,
            profile_url=profile_url,
            followers_count=None,
        )
        result = cf.evaluate_post_hydration_hard_filter(item, task)
        assert not result.passed
        assert result.reason == "invalid_profile"


def test_multi_task_instagram_item_still_hard_filters_30k():
    task = _task(platform="multi", platforms=["instagram", "tiktok"], min_followers_count=10_000)
    low = _item(platform="instagram", followers_count=25_000, bio="travel")
    high = _item(platform="instagram", followers_count=35_000, bio="travel")
    assert not cf.evaluate_post_hydration_hard_filter(low, task).passed
    assert cf.evaluate_post_hydration_hard_filter(high, task).passed


def test_multi_task_tiktok_unknown_followers_filtered_when_min_set():
    task = _task(platform="multi", platforms=["instagram", "tiktok"], min_followers_count=10_000)
    item = _item(
        platform="tiktok",
        username="creator",
        profile_url="https://www.tiktok.com/@creator",
        followers_count=None,
        bio="travel",
    )
    result = cf.evaluate_post_hydration_hard_filter(item, task)
    assert not result.passed
    assert result.reason == "below_min_followers"


def test_youtube_low_followers_filtered_when_min_set():
    task = _task(platform="multi", platforms=["youtube"], min_followers_count=10_000)
    low = _item(
        platform="youtube",
        username="UC123",
        profile_url="https://www.youtube.com/channel/UC123",
        followers_count=500,
    )
    assert not cf.evaluate_post_hydration_hard_filter(low, task).passed
    high = _item(
        platform="youtube",
        username="UC456",
        profile_url="https://www.youtube.com/channel/UC456",
        followers_count=15_000,
    )
    assert cf.evaluate_post_hydration_hard_filter(high, task).passed


def test_facebook_unknown_followers_filtered_when_min_set():
    task = _task(platform="multi", platforms=["facebook"], min_followers_count=10_000)
    item = _item(
        platform="facebook",
        username="Meta",
        profile_url="https://www.facebook.com/Meta",
        followers_count=None,
    )
    result = cf.evaluate_post_hydration_hard_filter(item, task)
    assert not result.passed
    assert result.reason == "below_min_followers"


def test_guess_category_amazon_commerce_before_tech():
    from app.services.apify_instagram import _guess_category, map_apify_instagram_profile

    bio = "Tech reviewer | Amazon storefront & gadget deals"
    assert _guess_category(bio) == "amazon_commerce"

    raw = {
        "username": "shopper",
        "bio": "Gadget reviews and tech tips",
        "bioLinks": [{"url": "https://amzn.to/abc123", "title": "Amazon finds"}],
        "followers": 50_000,
    }
    profile = map_apify_instagram_profile(raw)
    assert profile.category in {"amazon_commerce", "shopping"}
    assert profile.category != "tech"





if __name__ == "__main__":

    test_soft_preferences_do_not_block_insertion_filter()

    test_exclude_keyword_hard_filter()

    test_followers_in_range_matches_preferences()

    test_discovery_hard_min_followers_floor_and_ceiling()

    test_comment_mode_min_followers_hard_filter()

    test_invalid_profile_hard_filter()

    print("all tests passed")


