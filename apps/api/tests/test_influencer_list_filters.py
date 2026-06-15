"""红人列表筛选与排序相关测试。"""

import asyncio

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.session import async_session_factory
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


def test_platform_stats_omit_link_import_platforms_without_inserted_data():
    async def _run() -> None:
        from app.schemas.influencer import InfluencerFilter
        from app.services.product_influencer_service import ProductInfluencerService

        async with async_session_factory() as db_session:
            stats = await ProductInfluencerService.get_platform_stats(
                db_session,
                product_id=1,
                filters=InfluencerFilter(),
            )
            platforms = [item.platform for item in stats.items]
            assert platforms[:4] == ["tiktok", "youtube", "instagram", "facebook"]
            assert "pinterest" not in platforms
            assert "ltk" not in platforms
            assert "shopmy" not in platforms

    asyncio.run(_run())


def test_platform_stats_include_link_import_platform_with_inserted_data():
    async def _run() -> None:
        import uuid
        from datetime import UTC, datetime

        from app.collectors.base import CollectedInfluencer
        from app.schemas.influencer import InfluencerFilter
        from app.services.influencer_persistence import (
            create_global_profile_from_collected,
            create_product_influencer_from_collected,
        )
        from app.services.product_influencer_service import ProductInfluencerService

        suffix = uuid.uuid4().hex[:8]
        run_at = datetime.now(UTC)
        item = CollectedInfluencer(
            platform="pinterest",
            username=f"pinterest_creator_{suffix}",
            profile_url=f"https://www.pinterest.com/pinterest_creator_{suffix}/",
            platform_unique_id=f"pinterest_{suffix}",
            followers_count=12000,
            engagement_rate=1.2,
            bio="home decor creator",
            display_name="Pinterest Creator",
        )

        async with async_session_factory() as db_session:
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db_session.add(global_profile)
            await db_session.flush()
            db_session.add(
                create_product_influencer_from_collected(
                    product_id=1,
                    global_profile=global_profile,
                    data=item,
                    task=None,
                    run_at=run_at,
                )
            )
            await db_session.flush()

            stats = await ProductInfluencerService.get_platform_stats(
                db_session,
                product_id=1,
                filters=InfluencerFilter(),
            )
            platforms = [entry.platform for entry in stats.items]
            assert "pinterest" in platforms
            pinterest = next(entry for entry in stats.items if entry.platform == "pinterest")
            assert pinterest.total >= 1
            await db_session.rollback()

    asyncio.run(_run())


def test_influencer_filter_accepts_value_tier():
    filters = InfluencerFilter(value_tier="manual_research")
    assert filters.value_tier == "manual_research"
