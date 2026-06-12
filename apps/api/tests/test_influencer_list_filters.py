"""红人列表筛选与排序相关测试。"""

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.influencer import Influencer
from app.schemas.influencer import InfluencerExportFilter, InfluencerFilter, PlatformStatItem
from app.services.influencer import InfluencerService


def test_influencer_filter_accepts_collection_task_and_recency_fields():
    filters = InfluencerFilter(
        platform="instagram",
        collection_task_id=48,
        created_within_hours=24,
        collected_within_days=7,
    )
    assert filters.collection_task_id == 48
    assert filters.created_within_hours == 24
    assert filters.collected_within_days == 7
    assert filters.high_value is None


def test_influencer_export_filter_preserves_collection_task_id():
    export_filter = InfluencerExportFilter(
        platform="instagram",
        collection_task_id=12,
        created_within_hours=24,
        high_value=True,
    )
    query_filter = export_filter.to_query_filter()
    assert query_filter.collection_task_id == 12
    assert query_filter.created_within_hours == 24
    assert query_filter.high_value is True


def test_high_value_filter_adds_contact_and_quality_rules():
    query = InfluencerService._apply_filters(
        select(Influencer),
        InfluencerFilter(high_value=True),
    )

    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "influencers.final_email IS NOT NULL" in sql
    assert "influencers.website IS NOT NULL" in sql
    assert "influencers.commercial_signal_score >= 50.0" in sql
    assert "influencers.product_fit >= 60.0" in sql
    assert "facebook.com/people/" in sql
    assert "NOT" in sql


def test_influencer_filter_accepts_platform_other():
    query = InfluencerService._apply_filters(
        select(Influencer),
        InfluencerFilter(platform="other"),
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "NOT" in sql
    assert "facebook" in sql.lower()


def test_platform_stats_response_shape():
    item = PlatformStatItem(
        platform="tiktok",
        total=10,
        has_email=4,
        direct_contact=3,
        missing_contact=2,
        high_value=1,
    )
    assert item.total == 10
    assert item.has_email == 4


def test_influencer_filter_accepts_value_tier():
    filters = InfluencerFilter(value_tier="manual_research")
    assert filters.value_tier == "manual_research"
