"""红人资料价值判定测试。"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.influencer_profile_value import is_candidate_row_valuable, is_influencer_profile_valuable


def test_empty_ltk_profile_is_not_valuable():
    profile = SimpleNamespace(
        platform="ltk",
        username="creator",
        profile_url="https://www.shopltk.com/explore/creator",
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        website=None,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is False


def test_display_name_only_profile_is_not_valuable():
    profile = SimpleNamespace(
        platform="shopmy",
        username="creator",
        profile_url="https://shopmy.us/creator",
        display_name="Creator Name",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        website=None,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is False


def test_self_storefront_link_in_other_social_links_is_not_valuable():
    profile_url = "https://www.shopltk.com/explore/creator"
    profile = SimpleNamespace(
        platform="ltk",
        username="creator",
        profile_url=profile_url,
        normalized_profile_url=profile_url,
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        website=None,
        other_social_links=[{"type": "ltk", "label": "LTK", "url": profile_url}],
    )
    assert is_influencer_profile_valuable(profile) is False


def test_profile_with_bio_is_valuable():
    profile = SimpleNamespace(
        platform="pinterest",
        username="creator",
        profile_url="https://www.pinterest.com/creator/",
        display_name="creator",
        bio="Travel and lifestyle",
        followers_count=None,
        engagement_rate=None,
        email=None,
        website=None,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is True


def test_profile_with_engagement_rate_is_valuable():
    profile = SimpleNamespace(
        platform="ltk",
        username="creator",
        profile_url="https://www.shopltk.com/explore/creator",
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=2.5,
        email=None,
        website=None,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is True


def test_profile_with_contact_page_is_valuable():
    profile = SimpleNamespace(
        platform="shopmy",
        username="creator",
        profile_url="https://shopmy.us/creator",
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        contact_page="https://creator.com/contact",
        website=None,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is True


def test_profile_with_meaningful_other_social_link_is_valuable():
    profile = SimpleNamespace(
        platform="pinterest",
        username="creator",
        profile_url="https://www.pinterest.com/creator/",
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        website=None,
        other_social_links=[{"type": "instagram", "label": "Instagram", "url": "https://www.instagram.com/creator/"}],
    )
    assert is_influencer_profile_valuable(profile) is True


def test_profile_with_content_topics_is_valuable():
    profile = SimpleNamespace(
        platform="ltk",
        username="creator",
        profile_url="https://www.shopltk.com/explore/creator",
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        website=None,
        other_social_links=[],
        content_topics=["fashion", "travel"],
    )
    assert is_influencer_profile_valuable(profile) is True


def test_self_profile_website_is_not_valuable():
    profile_url = "https://www.pinterest.com/creator/"
    profile = SimpleNamespace(
        platform="pinterest",
        username="creator",
        profile_url=profile_url,
        normalized_profile_url=profile_url,
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        website=profile_url,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is False


def test_third_party_storefront_website_without_context_is_not_valuable():
    profile = SimpleNamespace(
        platform="pinterest",
        username="creator",
        profile_url="https://www.pinterest.com/creator/",
        normalized_profile_url="https://www.pinterest.com/creator/",
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        website="https://shopmy.us/other_creator",
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is False


def test_storefront_self_website_without_context_is_not_valuable():
    profile_url = "https://shopmy.us/creator"
    profile = SimpleNamespace(
        platform="shopmy",
        username="creator",
        profile_url=profile_url,
        normalized_profile_url=profile_url,
        display_name="creator",
        bio=None,
        followers_count=None,
        engagement_rate=None,
        email=None,
        website=profile_url,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is False


def test_profile_with_followers_is_valuable():
    profile = SimpleNamespace(
        platform="shopmy",
        username="creator",
        profile_url="https://shopmy.us/creator",
        followers_count=1200,
        engagement_rate=None,
        bio=None,
        email=None,
        website=None,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is True


def test_profile_with_email_is_valuable():
    profile = SimpleNamespace(
        platform="pinterest",
        username="creator",
        profile_url="https://www.pinterest.com/creator/",
        followers_count=None,
        engagement_rate=None,
        bio=None,
        email="creator@example.com",
        website=None,
        other_social_links=[],
    )
    assert is_influencer_profile_valuable(profile) is True


def test_candidate_with_only_username_is_not_valuable():
    candidate = SimpleNamespace(
        username="creator",
        profile_url="https://www.shopltk.com/explore/creator",
        platform="ltk",
        is_high_value=False,
        has_email=False,
        has_contact=False,
        followers_count=None,
        engagement_rate=None,
        bio=None,
    )
    assert is_candidate_row_valuable(candidate) is False


def test_candidate_with_contact_is_valuable():
    candidate = SimpleNamespace(
        username="creator",
        profile_url="https://www.shopltk.com/explore/creator",
        platform="ltk",
        is_high_value=False,
        has_email=True,
        has_contact=True,
        followers_count=None,
        engagement_rate=None,
        bio=None,
    )
    assert is_candidate_row_valuable(candidate) is True
