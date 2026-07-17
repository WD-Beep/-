"""联系方式信号与分层联动测试。"""

from types import SimpleNamespace

from app.services.contact_discovery import extract_emails_from_text, extract_whatsapp, normalize_email
from app.services.contact_signals import (
    apply_bio_contact_hints,
    build_contact_summary,
    direct_contact_reason,
    extract_bio_contact_hints,
)
from app.services.value_tier import classify_value_tier


def _row(**kwargs):
    defaults = {
        "platform": "instagram",
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
        "profile_url": "https://instagram.com/demo",
        "username": "demo",
        "display_name": "Demo",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_youtube_bare_channel_is_not_direct_contact():
    tier, _, reason = classify_value_tier(
        _row(
            platform="youtube",
            profile_url="https://www.youtube.com/channel/UCAPrhJwVweWZASGEPoC1Sdw",
        )
    )
    assert tier != "direct_contact"
    assert "YouTube" not in reason


def test_youtube_with_linktree_is_direct_contact():
    tier, _, reason = classify_value_tier(
        _row(
            platform="youtube",
            profile_url="https://www.youtube.com/channel/UC123",
            linktree_url="https://linktr.ee/demo",
        )
    )
    assert tier == "direct_contact"
    assert "Linktree" in reason


def test_tiktok_dm_collab_bio_is_direct_contact_not_skip():
    tier, _, reason = classify_value_tier(
        _row(
            platform="tiktok",
            profile_url="https://www.tiktok.com/@creator",
            bio="Travel creator · DM for collab and brand partnerships",
        )
    )
    assert tier == "direct_contact"
    assert "私信" in reason or "collab" in reason.lower()


def test_tiktok_bare_profile_is_not_direct_contact():
    tier, _, _ = classify_value_tier(
        _row(
            platform="tiktok",
            profile_url="https://www.tiktok.com/@creator",
        )
    )
    assert tier != "direct_contact"


def test_shopmy_storefront_without_email_not_skip():
    tier, _, reason = classify_value_tier(
        _row(
            platform="shopmy",
            profile_url="https://shopmy.us/creator/demo",
            website="https://shopmy.us/creator/demo",
        )
    )
    assert tier != "skip"
    assert "ShopMy" in reason or "官网" in reason


def test_ltk_profile_url_manual_or_direct_not_skip():
    tier, _, _ = classify_value_tier(
        _row(
            platform="ltk",
            profile_url="https://www.shopltk.com/explore/travelstyle",
            product_fit=65.0,
        )
    )
    assert tier != "skip"


def test_facebook_bare_page_is_not_direct_contact():
    tier, _, reason = classify_value_tier(
        _row(
            platform="facebook",
            profile_url="https://facebook.com/pleasantgreen",
        )
    )
    assert tier != "direct_contact"
    assert "Facebook Page" not in reason


def test_facebook_page_with_website_is_direct_contact():
    tier, _, reason = classify_value_tier(
        _row(
            platform="facebook",
            profile_url="https://facebook.com/pleasantgreen",
            website="https://pleasantgreen.com",
        )
    )
    assert tier == "direct_contact"
    assert "官网" in reason


def test_facebook_fan_page_display_name_skips_even_with_page_url():
    tier, _, reason = classify_value_tier(
        _row(
            platform="facebook",
            profile_url="https://facebook.com/travel.fan.page.official",
            display_name="Travel Fan Page Official",
            username="travel.fan.page.official",
        )
    )
    assert tier == "skip"
    assert "低价值" in reason


def test_facebook_coupon_username_skips():
    tier, _, reason = classify_value_tier(
        _row(
            platform="facebook",
            profile_url="https://facebook.com/coupondealsdaily",
            display_name="Coupon Deals Daily",
            username="coupondealsdaily",
        )
    )
    assert tier == "skip"
    assert "coupon" in reason.lower() or "低价值" in reason


def test_facebook_groups_still_skip():
    tier, _, reason = classify_value_tier(
        _row(
            platform="facebook",
            profile_url="https://facebook.com/groups/travel-deals/123",
        )
    )
    assert tier == "skip"
    assert "Facebook" in reason


def test_extract_bio_contact_hints_linktree_and_whatsapp():
    hints = extract_bio_contact_hints(
        "Collabs: hello@example.com · https://linktr.ee/demo · https://wa.me/1234567890"
    )
    assert hints.linktree_url == "https://linktr.ee/demo"
    assert hints.whatsapp == "https://wa.me/1234567890"


def test_contact_discovery_rejects_sentry_ingest_email_from_page_logs():
    sentry_email = "37df41a9eafc429585b01c3771b4af54@o468184.ingest.sentry.io"
    html = f"""
    <script>
      window.SENTRY_DSN = "https://{sentry_email}/123";
    </script>
    <p>For collaborations email hello@byaivhe.com</p>
    """

    assert normalize_email(sentry_email) is None
    assert [candidate.email for candidate in extract_emails_from_text(html, "website")] == ["hello@byaivhe.com"]


def test_extract_whatsapp_rejects_view_count_and_dates():
    assert extract_whatsapp("1.5M views · posted 2024-06-04") is None
    assert extract_whatsapp("followers: 1580455") is None
    assert extract_whatsapp("WhatsApp: +1 415 555 0100") == "+1 415 555 0100"


def test_apply_bio_contact_hints_mutates_collected_like_object():
    item = SimpleNamespace(
        platform="youtube",
        bio="Bookings: https://creator.example.com/contact · https://linktr.ee/demo",
        website=None,
        contact_page=None,
        linktree_url=None,
        whatsapp=None,
        telegram=None,
        other_social_links=[],
    )
    apply_bio_contact_hints(item)
    assert item.contact_page == "https://creator.example.com/contact"
    assert item.linktree_url == "https://linktr.ee/demo"


def test_build_contact_summary_only_explicit_channels():
    summary = build_contact_summary(
        _row(
            platform="youtube",
            profile_url="https://www.youtube.com/channel/UC123",
            linktree_url="https://linktr.ee/demo",
        )
    )
    assert summary == "Linktree"
    assert "YouTube" not in summary


def test_direct_contact_reason_whatsapp():
    reason = direct_contact_reason(_row(whatsapp="+1234567890"))
    assert reason == "有 WhatsApp"


def test_instagram_external_link_direct_contact_reason():
    reason = direct_contact_reason(
        _row(
            other_social_links=[{"type": "instagram", "label": "Instagram", "url": "https://instagram.com/demo"}],
        )
    )
    assert reason == "有 Instagram 外链"
