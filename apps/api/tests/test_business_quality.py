from types import SimpleNamespace

from app.services.business_quality import apply_creator_quality, assess_creator_quality


def _row(**kwargs):
    defaults = {
        "platform": "youtube",
        "username": "creator",
        "display_name": "Creator",
        "profile_url": "https://www.youtube.com/channel/UC123",
        "bio": None,
        "category": None,
        "niche": None,
        "source_post_url": None,
        "source_comment_text": None,
        "ai_summary": None,
        "score_reason": None,
        "ai_collaboration_suggestion": None,
        "tags": [],
        "content_topics": [],
        "recent_post_titles": [],
        "collaboration_formats": [],
        "followers_count": None,
        "avg_views": None,
        "avg_likes": None,
        "avg_comments": None,
        "engagement_rate": None,
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
        "commercial_signal_score": None,
        "contactability_score": None,
        "content_match_score": None,
        "engagement_score": None,
        "risk_score": None,
        "product_fit": None,
        "sales_potential_score": None,
        "audience_match_score": None,
        "roi_forecast": None,
        "final_priority": None,
        "score": None,
        "has_brand_collaboration": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_commercial_review_storefront_scores_higher_than_bare_creator():
    bare = _row(avg_views=500_000, bio="I make videos about life.")
    commercial = _row(
        avg_views=120_000,
        bio="Amazon storefront, product review, links below. Business inquiries welcome.",
        linktree_url="https://linktr.ee/creator",
    )

    bare_quality = assess_creator_quality(bare)
    commercial_quality = assess_creator_quality(commercial)

    assert commercial_quality.commercial_score > bare_quality.commercial_score
    assert commercial_quality.contactability_score > bare_quality.contactability_score
    assert commercial_quality.score > bare_quality.score
    assert "Amazon" in commercial_quality.reason_text


def test_youtube_recent_post_titles_boost_commercial_score():
    row = _row(
        platform="youtube",
        avg_views=120_000,
        recent_post_titles=["Amazon product review", "Shopping deals tutorial"],
        bio="Product reviews and shopping finds",
    )
    quality = assess_creator_quality(row)
    assert quality.commercial_score >= 30
    assert any("YouTube" in reason for reason in quality.positive_reasons)


def test_low_value_coupon_meme_account_gets_risk_penalty():
    row = _row(
        platform="facebook",
        profile_url="https://facebook.com/couponmemenews",
        display_name="Coupon Meme News",
        bio="Daily coupon meme news and freebies",
        avg_views=900_000,
    )
    quality = assess_creator_quality(row)

    assert quality.risk_score >= 60
    assert quality.score < 50
    assert any("Meme" in reason or "Coupon" in reason for reason in quality.negative_reasons)


def test_apply_creator_quality_populates_export_and_sorting_fields():
    row = _row(
        platform="tiktok",
        profile_url="https://www.tiktok.com/@creator",
        bio="TikTok shop product review · DM for collab · use code CREATOR",
        avg_views=80_000,
        avg_likes=8_000,
        avg_comments=300,
    )
    assessment = apply_creator_quality(row)

    assert row.commercial_signal_score == assessment.commercial_score
    assert row.contactability_score >= 50
    assert row.product_fit >= 50
    assert row.final_priority in {"P0", "P1", "P2", "P3"}
    assert row.score_reason
    assert row.score is not None
