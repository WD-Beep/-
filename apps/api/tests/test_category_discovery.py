"""类目采集关键词扩展与分层兼容测试。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.collection_task import CollectionTaskCreate
from app.services.category_discovery import (
    apply_category_discovery_expansion,
    expand_category_discovery_inputs,
    generate_category_keywords,
)
from app.services.value_tier import classify_value_tier


def test_category_discovery_generates_platform_keywords():
    keywords, generated = generate_category_keywords(
        category="Travel",
        country="US",
        platforms=["instagram", "youtube", "shopmy"],
    )
    assert generated
    assert any("travel" in k.lower() for k in generated)
    assert any("shopmy" in k.lower() for k in generated)
    assert any("US" in k for k in keywords)


def test_supplementary_keywords_merge_and_deduplicate():
    expansion = expand_category_discovery_inputs(
        category="Beauty",
        country=None,
        platforms=["instagram", "pinterest"],
        supplementary_keywords=["beauty influencer", "Beauty", "makeup"],
    )
    lowered = {k.lower() for k in expansion.keywords}
    assert "beauty influencer" in lowered
    assert "makeup" in lowered
    assert len(expansion.keywords) == len(lowered)
    assert "makeup" in expansion.supplementary_keywords


def test_category_discovery_create_requires_category():
    with pytest.raises(ValidationError, match="类目"):
        CollectionTaskCreate(
            name="category task",
            collection_mode="category_discovery",
            platforms=["instagram"],
            keywords=[],
        )


def test_keyword_collection_create_still_requires_keywords():
    with pytest.raises(ValidationError, match="关键词"):
        CollectionTaskCreate(
            name="keyword task",
            collection_mode="keyword",
            platforms=["instagram"],
            keywords=[],
        )


def test_apply_category_discovery_expansion_mutates_task_keywords():
    task = SimpleNamespace(
        collection_mode="category_discovery",
        platform="multi",
        platforms=["shopmy", "pinterest"],
        category="Skincare",
        country="US",
        keywords=["dermatologist"],
        input_urls=[],
    )
    expansion = apply_category_discovery_expansion(task)
    assert expansion is not None
    assert "dermatologist" in task.keywords
    assert any("skincare" in k.lower() for k in task.keywords)
    assert any("shopmy.us" in url for url in task.input_urls)
    assert any("pinterest.com" in url for url in task.input_urls)


def test_shopmy_ltk_pinterest_links_not_skipped_by_value_tier():
    cases = [
        SimpleNamespace(
            final_email=None,
            email=None,
            public_email=None,
            business_email=None,
            website="https://shopmy.us/creator/demo",
            contact_page=None,
            linktree_url=None,
            whatsapp=None,
            telegram=None,
            contact_score=None,
            contactability_score=None,
            final_priority=None,
            score=None,
            product_fit=72.0,
            commercial_signal_score=None,
            bio=None,
            ai_summary=None,
            score_reason=None,
            ai_collaboration_suggestion=None,
            tags=[],
            content_topics=[],
            profile_url="https://shopmy.us/creator/demo",
            username="demo",
            display_name="Demo Creator",
        ),
        SimpleNamespace(
            final_email=None,
            email=None,
            public_email=None,
            business_email=None,
            website=None,
            contact_page=None,
            linktree_url=None,
            whatsapp=None,
            telegram=None,
            contact_score=None,
            contactability_score=None,
            final_priority=None,
            score=None,
            product_fit=65.0,
            commercial_signal_score=None,
            bio=None,
            ai_summary=None,
            score_reason=None,
            ai_collaboration_suggestion=None,
            tags=[],
            content_topics=[],
            profile_url="https://www.shopltk.com/explore/travelstyle",
            username="travelstyle",
            display_name="Travel Style",
        ),
        SimpleNamespace(
            final_email=None,
            email=None,
            public_email=None,
            business_email=None,
            website="https://www.pinterest.com/homecurator/",
            contact_page=None,
            linktree_url=None,
            whatsapp=None,
            telegram=None,
            contact_score=None,
            contactability_score=None,
            final_priority=None,
            score=None,
            product_fit=68.0,
            commercial_signal_score=None,
            bio="Pinterest product curator for home decor",
            ai_summary=None,
            score_reason=None,
            ai_collaboration_suggestion=None,
            tags=[],
            content_topics=[],
            profile_url="https://www.pinterest.com/homecurator/",
            username="homecurator",
            display_name="Home Curator",
        ),
    ]
    for row in cases:
        tier, _, _ = classify_value_tier(row)
        assert tier != "skip"
