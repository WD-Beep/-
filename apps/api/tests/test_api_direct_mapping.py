from app.services.api_direct_instagram import post_item_to_apify_raw, user_to_apify_raw


def test_user_to_apify_raw_maps_followers_and_email():
    raw = user_to_apify_raw(
        {
            "username": "natgeo",
            "full_name": "National Geographic",
            "biography": "Explore the world",
            "follower_count": 1000,
            "is_verified": True,
            "is_private": False,
            "public_email": "contact@example.com",
            "profile_pic_url_hd": "https://cdn.example/pic.jpg",
            "external_url": "https://link.example",
        }
    )
    assert raw["username"] == "natgeo"
    assert raw["followers"] == 1000
    assert raw["businessEmail"] == "contact@example.com"
    assert raw["isVerified"] is True


def test_post_item_to_apify_raw_extracts_author():
    raw = post_item_to_apify_raw(
        {
            "url": "https://instagram.com/p/ABC123/",
            "author": "creator_one",
            "snippet": "hello #travel",
            "media_type": "clips",
            "likes": 10,
            "comments": 2,
        }
    )
    assert raw["username"] == "creator_one"
    assert raw["shortcode"] == "ABC123"
    assert raw["type"] == "reel"
