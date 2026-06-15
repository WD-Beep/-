"""高价值筛选评估逻辑。"""

from types import SimpleNamespace

from app.models.collection_task import CollectionTask
from app.services.high_value_filter import (
    CONTACT_PENDING,
    evaluate_high_value_assessment,
    has_collection_contact_channel,
    has_collection_email,
    is_url_only_metrics_pending,
    should_skip_insert,
    should_strict_filter_out,
)


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
        "bio": "Lifestyle creator | collab email@test.com",
        "display_name": None,
        "category": None,
        "niche": None,
        "country": None,
        "language": None,
        "content_topics": None,
        "recent_post_titles": None,
        "tags": None,
        "collaboration_formats": None,
        "website": None,
        "contact_page": None,
        "linktree_url": None,
        "other_social_links": None,
        "email": None,
        "final_email": None,
        "public_email": None,
        "business_email": None,
        "contact_fetch_status": "success",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_has_collection_email_and_contact_from_multiple_fields():
    item = _item(final_email="hello@brand.com", website="https://example.com")
    assert has_collection_email(item)
    assert has_collection_contact_channel(item)


def test_contact_channel_from_linktree_and_storefront():
    item = _item(linktree_url="https://linktr.ee/creator")
    assert has_collection_contact_channel(item)
    assert not has_collection_email(item)

    shopmy = _item(other_social_links=[{"url": "https://shopmy.us/creator", "label": "ShopMy"}])
    assert has_collection_contact_channel(shopmy)


def test_missing_followers_not_high_value_when_min_set():
    task = _task(min_followers_count=10_000, platform="youtube", platforms=["youtube"])
    item = _item(platform="youtube", followers_count=None, profile_url="https://www.youtube.com/@creator")
    assessment = evaluate_high_value_assessment(item, task)
    assert not assessment.is_high_value
    assert assessment.followers_status == "missing"


def test_low_engagement_blocks_when_insert_qualified_only():
    task = _task(min_engagement_rate=2.0, insert_qualified_only=True)
    item = _item(engagement_rate=0.5)
    assessment = evaluate_high_value_assessment(item, task)
    assert assessment.insert_blocked
    assert should_skip_insert(task, assessment)
    assert not should_strict_filter_out(task, assessment)


def test_strict_filter_out_engagement_and_followers():
    task = _task(min_engagement_rate=2.0, strict_quality_filter=True)
    low_engagement = _item(engagement_rate=0.5)
    assessment = evaluate_high_value_assessment(low_engagement, task)
    assert should_strict_filter_out(task, assessment)
    assert assessment.filter_reason == "below_min_engagement_rate"


def test_require_email_does_not_block_when_contact_pending():
    task = _task(require_email=True, insert_qualified_only=True)
    item = _item(contact_fetch_status="not_started", final_email=None)
    assessment = evaluate_high_value_assessment(item, task)
    assert assessment.contact_status == CONTACT_PENDING
    assert not assessment.insert_blocked
    assert not should_skip_insert(task, assessment)


def test_require_email_blocks_when_resolved_without_email():
    task = _task(require_email=True, insert_qualified_only=True)
    item = _item(contact_fetch_status="failed", final_email=None, website=None)
    assessment = evaluate_high_value_assessment(item, task)
    assert assessment.contact_status == "missing"
    assert assessment.insert_blocked
    assert "missing_email" in assessment.mismatch_codes


def test_require_email_detects_bio_only_email():
    task = _task(require_email=True, insert_qualified_only=True)
    item = _item(
        contact_fetch_status="success",
        final_email=None,
        email=None,
        public_email=None,
        business_email=None,
        bio="Collab inquiries: hello@creator.com",
    )
    assert has_collection_email(item)
    assessment = evaluate_high_value_assessment(item, task)
    assert assessment.has_email
    assert assessment.is_high_value
    assert not should_skip_insert(task, assessment)


def test_require_contact_detects_bio_only_email():
    task = _task(require_contact=True, insert_qualified_only=True)
    item = _item(
        contact_fetch_status="success",
        final_email=None,
        email=None,
        public_email=None,
        business_email=None,
        bio="合作联系 hello@brand.com",
    )
    assert has_collection_email(item)
    assert has_collection_contact_channel(item)
    assessment = evaluate_high_value_assessment(item, task)
    assert assessment.has_email
    assert assessment.has_contact
    assert assessment.is_high_value
    assert "missing_contact" not in assessment.mismatch_codes
    assert not should_skip_insert(task, assessment)


def test_missing_engagement_not_high_value():
    task = _task(min_engagement_rate=2.0)
    item = _item(engagement_rate=None)
    assessment = evaluate_high_value_assessment(item, task)
    assert not assessment.is_high_value
    assert assessment.engagement_status == "missing"
    assert "missing_engagement_rate" in assessment.mismatch_codes


def test_require_contact_passes_with_website_only():
    task = _task(require_contact=True, insert_qualified_only=True)
    item = _item(contact_fetch_status="success", website="https://creator.com", final_email=None)
    assessment = evaluate_high_value_assessment(item, task)
    assert assessment.has_contact
    assert assessment.is_high_value


def test_amazon_competitor_candidate_uses_same_quality_rules():
    task = _task(
        collection_mode="competitor_product",
        platform="multi",
        platforms=["instagram", "youtube"],
        min_followers_count=20_000,
        require_contact=True,
        insert_qualified_only=True,
    )
    item = _item(
        source_discovery_type="competitor_product",
        followers_count=5_000,
        website="https://shop.example.com",
        contact_fetch_status="success",
    )
    assessment = evaluate_high_value_assessment(item, task)
    assert not assessment.is_high_value
    assert should_skip_insert(task, assessment)


def test_url_only_platform_without_metrics_not_high_value():
    item = _item(
        platform="pinterest",
        profile_url="https://www.pinterest.com/example_user/",
        followers_count=None,
        engagement_rate=None,
        contact_fetch_status="pending",
        bio=None,
        website=None,
    )
    assert is_url_only_metrics_pending(item)
    assessment = evaluate_high_value_assessment(item, _task())
    assert not assessment.is_high_value
    assert assessment.contact_status == CONTACT_PENDING


def test_url_only_platform_strict_filter_blocks_missing_followers():
    task = _task(
        platform="pinterest",
        platforms=["pinterest"],
        min_followers_count=1_000,
        strict_quality_filter=True,
    )
    item = _item(
        platform="pinterest",
        profile_url="https://www.pinterest.com/example_user/",
        followers_count=None,
        engagement_rate=None,
        contact_fetch_status="pending",
    )
    assessment = evaluate_high_value_assessment(item, task)
    assert should_strict_filter_out(task, assessment)
    assert not assessment.is_high_value
