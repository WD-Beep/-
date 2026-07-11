"""Tests for runtime Instagram discovery keyword expansion."""

from app.services.hashtag_expansion import expand_keywords_to_hashtags


def test_expand_travel_keyword():
    tags = expand_keywords_to_hashtags(["travel"], max_hashtags=20)
    assert "travel" in tags
    assert any("travel" in t and t != "travel" for t in tags)
    assert "luxurytravel" in tags or "travelgram" in tags or "travelblogger" in tags


def test_expand_product_phrase_keeps_original_hashtag_and_adjacent_terms():
    tags = expand_keywords_to_hashtags(["travel makeup bag", "makeup bag"], max_hashtags=15)

    expected = [
        "travel makeup bag",
        "travelmakeupbag",
        "travel makeup",
        "makeup bag",
        "travelmakeup",
        "makeupbag",
        "cosmetic bag",
        "toiletry bag",
        "makeup pouch",
    ]
    for tag in expected:
        assert tag in tags
    assert len(tags) <= 15


def test_expand_product_phrase_strips_hash_and_deduplicates_in_order():
    tags = expand_keywords_to_hashtags(["#Makeup Bag", "makeup bag"], max_hashtags=15)

    assert tags[0] == "makeup bag"
    assert tags.count("makeup bag") == 1
    assert tags.count("makeupbag") == 1
    assert len(tags) <= 15


def test_expand_product_phrase_respects_limit():
    tags = expand_keywords_to_hashtags(
        ["travel makeup bag", "makeup organizer", "travel essentials"],
        max_hashtags=8,
    )

    assert len(tags) == 8


if __name__ == "__main__":
    test_expand_travel_keyword()
    test_expand_product_phrase_keeps_original_hashtag_and_adjacent_terms()
    test_expand_product_phrase_strips_hash_and_deduplicates_in_order()
    test_expand_product_phrase_respects_limit()
    print("ok")
