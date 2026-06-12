"""hashtag 扩展测试。"""

from app.services.hashtag_expansion import expand_keywords_to_hashtags


def test_expand_travel_keyword():
    tags = expand_keywords_to_hashtags(["travel"], max_hashtags=20)
    assert "travel" in tags
    assert any("travel" in t and t != "travel" for t in tags)
    assert "luxurytravel" in tags or "travelgram" in tags or "travelblogger" in tags


if __name__ == "__main__":
    test_expand_travel_keyword()
    print("ok")
