"""红人价值分层规则测试。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.influencer import Influencer
from app.schemas.influencer import InfluencerExportFilter, InfluencerFilter
from app.services.influencer import InfluencerService
from app.services.value_tier import classify_value_tier


def _row(**kwargs):
    defaults = {
        "platform": "pinterest",
        "final_email": None,
        "email": None,
        "public_email": None,
        "business_email": None,
        "website": None,
        "contact_page": None,
        "linktree_url": None,
        "whatsapp": None,
        "telegram": None,
        "other_social_links": [],
        "contact_score": None,
        "contactability_score": None,
        "final_priority": None,
        "score": None,
        "product_fit": None,
        "commercial_signal_score": None,
        "bio": None,
        "ai_summary": None,
        "score_reason": None,
        "ai_collaboration_suggestion": None,
        "tags": [],
        "content_topics": [],
        "profile_url": "https://pinterest.com/demo",
        "username": "demo",
        "display_name": "Demo",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_email_maps_to_direct_contact():
    tier, label, reason = classify_value_tier(_row(email="creator@example.com"))
    assert tier == "direct_contact"
    assert label == "可直接外联"
    assert "邮箱" in reason


def test_high_score_without_contact_maps_to_manual_research():
    tier, _, reason = classify_value_tier(_row(score=72.0))
    assert tier == "manual_research"
    assert "评分" in reason


def test_product_fit_maps_to_manual_research():
    tier, _, _ = classify_value_tier(_row(product_fit=65.0))
    assert tier == "manual_research"


def test_commercial_keyword_in_bio_maps_to_manual_research():
    tier, _, reason = classify_value_tier(_row(bio="Open for brand collab and sponsored posts"))
    assert tier == "manual_research"
    assert "sponsored" in reason or "collab" in reason


def test_facebook_people_url_maps_to_skip():
    tier, label, reason = classify_value_tier(
        _row(
            profile_url="https://facebook.com/people/Someone/123",
            email="shop@example.com",
        )
    )
    assert tier == "skip"
    assert label == "暂时跳过"
    assert "Facebook" in reason


def test_low_value_keyword_maps_to_skip():
    tier, _, reason = classify_value_tier(_row(bio="Official fan page for coupon deals"))
    assert tier == "skip"
    assert "低价值" in reason


def test_shopmy_profile_with_website_and_product_fit_not_skip():
    tier, _, _ = classify_value_tier(
        _row(
            platform="shopmy",
            profile_url="https://shopmy.us/creator/demo",
            website="https://shopmy.us/creator/demo",
            product_fit=72.0,
        )
    )
    assert tier != "skip"


def test_amazon_storefront_bio_not_skip():
    tier, _, _ = classify_value_tier(
        _row(bio="Amazon storefront and brand collab opportunities")
    )
    assert tier == "manual_research"


def test_youtube_bare_channel_not_direct_contact():
    tier, _, reason = classify_value_tier(
        _row(
            platform="youtube",
            profile_url="https://www.youtube.com/channel/UC123",
        )
    )
    assert tier != "direct_contact"
    assert "YouTube" not in reason


def test_youtube_bare_channel_with_score_is_manual_research():
    tier, _, reason = classify_value_tier(
        _row(
            platform="youtube",
            profile_url="https://www.youtube.com/channel/UC123",
            score=72.0,
        )
    )
    assert tier == "manual_research"
    assert "评分" in reason


def test_dm_for_collab_bio_direct_contact():
    tier, _, reason = classify_value_tier(
        _row(
            platform="tiktok",
            profile_url="https://www.tiktok.com/@creator",
            bio="Fashion · DM for collab · business inquiry only",
        )
    )
    assert tier == "direct_contact"
    assert "私信" in reason or "collab" in reason.lower()


def test_tiktok_linktree_direct_contact():
    tier, _, reason = classify_value_tier(
        _row(
            platform="tiktok",
            profile_url="https://www.tiktok.com/@creator",
            linktree_url="https://linktr.ee/creator",
        )
    )
    assert tier == "direct_contact"
    assert "Linktree" in reason


def test_facebook_groups_url_still_skip():
    tier, _, reason = classify_value_tier(
        _row(profile_url="https://facebook.com/groups/travel-deals/123")
    )
    assert tier == "skip"
    assert "Facebook" in reason


def test_facebook_meme_display_name_skips():
    tier, _, reason = classify_value_tier(
        _row(
            platform="facebook",
            profile_url="https://facebook.com/dailymemes",
            display_name="Daily Meme News",
            username="dailymemes",
        )
    )
    assert tier == "skip"
    assert "低价值" in reason


def test_facebook_official_name_with_email_still_direct_contact():
    tier, _, reason = classify_value_tier(
        _row(
            platform="facebook",
            profile_url="https://facebook.com/brand.official",
            display_name="Brand Official Fan Page",
            email="biz@example.com",
        )
    )
    assert tier == "direct_contact"
    assert "邮箱" in reason


def test_website_maps_to_direct_contact():
    tier, _, reason = classify_value_tier(_row(website="https://creator.example.com"))
    assert tier == "direct_contact"
    assert "官网" in reason


def test_high_value_filter_includes_a_and_b_not_c():
    query = InfluencerService._apply_filters(
        select(Influencer),
        InfluencerFilter(high_value=True),
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "influencers.final_email IS NOT NULL" in sql
    assert "influencers.commercial_signal_score >= 50.0" in sql
    assert "facebook.com/people/" in sql
    assert "NOT" in sql


def test_value_tier_direct_contact_filter():
    query = InfluencerService._apply_filters(
        select(Influencer),
        InfluencerFilter(value_tier="direct_contact"),
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "influencers.website IS NOT NULL" in sql
    assert "influencers.contact_score >= 50.0" in sql


def test_value_tier_skip_filter():
    query = InfluencerService._apply_filters(
        select(Influencer),
        InfluencerFilter(value_tier="skip"),
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "facebook.com/people/" in sql
    assert "official" in sql.lower() or "店铺" in sql


def test_export_filter_preserves_value_tier():
    export_filter = InfluencerExportFilter(
        platform="youtube",
        value_tier="manual_research",
        high_value=True,
    )
    query_filter = export_filter.to_query_filter()
    assert query_filter.value_tier == "manual_research"
    assert query_filter.high_value is True


def test_invalid_value_tier_raises():
    with pytest.raises(ValueError, match="Unsupported value_tier"):
        InfluencerService._value_tier_condition("invalid")


def test_influencer_read_includes_value_tier_in_schema_and_dump():
    row = {
        "id": 1,
        "platform": "instagram",
        "username": "demo",
        "profile_url": "https://www.instagram.com/demo/",
        "email": "creator@example.com",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    from app.schemas.influencer import InfluencerRead

    model = InfluencerRead.model_validate(row)
    dumped = model.model_dump()
    schema_props = InfluencerRead.model_json_schema().get("properties", {})

    assert dumped["value_tier"] == "direct_contact"
    assert dumped["value_tier_label"] == "可直接外联"
    assert dumped["value_tier_reason"]
    assert dumped["contact_summary"] == "creator@example.com"
    assert "value_tier" in schema_props
    assert "value_tier_label" in schema_props
    assert "value_tier_reason" in schema_props
    assert "contact_summary" in dumped
    assert "contact_summary" in InfluencerRead.model_computed_fields
