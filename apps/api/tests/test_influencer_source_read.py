"""红人来源追溯 API 字段测试。"""

from datetime import UTC, datetime

from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.models.product_influencer_source import ProductInfluencerSource
from app.services.influencer_projection import to_influencer_read


def test_to_influencer_read_includes_source_records():
    global_row = GlobalInfluencerProfile(
        id=1,
        platform="tiktok",
        username="creator",
        normalized_username="creator",
        profile_url="https://www.tiktok.com/@creator",
        normalized_profile_url="https://www.tiktok.com/@creator",
    )
    now = datetime.now(UTC)
    product_row = ProductInfluencer(
        id=10,
        product_id=1,
        global_influencer_id=1,
        source_post_url="https://www.tiktok.com/@creator/video/1",
        created_at=now,
        updated_at=now,
    )
    sources = [
        ProductInfluencerSource(
            id=1,
            product_influencer_id=10,
            task_id=5,
            source_post_url="https://www.tiktok.com/@creator/video/1",
            source_input_url="https://vm.tiktok.com/1",
            source_platform="tiktok",
            task_name="导入任务A",
            source_key="k1",
            collected_at=datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC),
        ),
        ProductInfluencerSource(
            id=2,
            product_influencer_id=10,
            task_id=6,
            source_post_url="https://www.tiktok.com/@creator/video/2",
            source_input_url="https://vm.tiktok.com/2",
            source_platform="tiktok",
            task_name="导入任务B",
            source_key="k2",
            collected_at=datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC),
        ),
    ]

    read = to_influencer_read(product_row, global_row, sources=sources)
    assert len(read.source_records) == 2
    assert read.source_records[0].source_post_url.endswith("/video/1")
    assert read.source_records[0].source_input_url == "https://vm.tiktok.com/1"
    assert read.source_records[0].task_name == "导入任务A"
    assert read.source_records[1].source_post_url.endswith("/video/2")
    assert read.source_post_url == "https://www.tiktok.com/@creator/video/1"
