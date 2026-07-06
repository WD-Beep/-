"""collection_funnel 目标合格数摘要。"""

from types import SimpleNamespace

from app.models.enums import CollectionTaskStatus
from app.services.collection_funnel import (
    CollectionFunnelStats,
    append_target_qualified_summary,
    build_running_discovery_summary,
    build_status_summary,
)
from app.services.collection_targets import RATE_LIMIT_STOP_REASON, max_overfetch_rounds_for_task


def test_status_summary_explains_target_shortfall():
    stats = CollectionFunnelStats(
        discovered_count=120,
        deduped_count=90,
        profile_fetched_count=90,
        inserted_count=12,
        filtered_out_count=78,
        filtered_below_min_followers_count=70,
        filtered_excluded_keyword_count=2,
        target_qualified_count=30,
        overfetch_stop_reason="已达安全上限",
    )
    summary = build_status_summary(stats, status=CollectionTaskStatus.COMPLETED_WITH_RESULTS)
    assert "目标 30 条合格入库" in summary
    assert "实际 12 条" in summary
    assert "低粉/粉丝未知" in summary
    assert "已达安全上限" in summary


def test_append_target_qualified_summary_when_met():
    stats = CollectionFunnelStats(inserted_count=30, target_qualified_count=30)
    text = append_target_qualified_summary("采集完成", stats)
    assert "已达标" in text


def test_build_running_discovery_summary_rate_limited():
    text = build_running_discovery_summary(
        phase="discovery",
        target=28,
        discovered=224,
        deduped=194,
        profile_fetched=194,
        filtered_out=0,
        inserted=0,
        rate_limited=True,
    )
    assert "限流" in text
    assert "已发现 224" in text
    assert "合格入库 0 / 目标 28" in text


def test_build_running_discovery_summary_zero_discovered_explains_reason():
    text = build_running_discovery_summary(
        phase="discovery",
        target=10,
        discovered=0,
        deduped=0,
        profile_fetched=0,
        filtered_out=0,
        inserted=0,
        slow_api=True,
    )
    assert "已发现 0" in text
    assert "目标 10" in text
    assert "可能原因" in text
    assert "Apify" in text or "API" in text


def test_slow_apify_platforms_skip_extra_overfetch_rounds():
    for platform in ("tiktok", "youtube", "facebook"):
        task = SimpleNamespace(
            platform=platform,
            platforms=[platform],
            discovery_limit=20,
            collection_mode="discovery",
        )

        assert max_overfetch_rounds_for_task(task) == 1


def test_status_summary_zero_insert_explains_filters():
    stats = CollectionFunnelStats(
        discovered_count=194,
        deduped_count=194,
        profile_fetched_count=194,
        inserted_count=0,
        filtered_out_count=194,
        filtered_below_min_followers_count=120,
        filtered_excluded_keyword_count=4,
        target_qualified_count=28,
        overfetch_stop_reason=RATE_LIMIT_STOP_REASON,
    )
    summary = build_status_summary(stats, status=CollectionTaskStatus.COMPLETED_NO_RESULTS)
    assert "合格入库 0" in summary
    assert "粉丝低于门槛" in summary
    assert RATE_LIMIT_STOP_REASON in summary


def test_status_summary_zero_insert_explains_link_signals_and_missing_contact():
    stats = CollectionFunnelStats(
        discovered_count=32,
        deduped_count=24,
        profile_fetched_count=24,
        inserted_count=0,
        filtered_out_count=24,
        target_qualified_count=10,
    )
    stats.external_link_count = 24
    stats.commercial_link_count = 16
    stats.social_only_link_count = 8
    stats.missing_contact_or_landing_count = 18
    stats.external_link_types = ["amazon_storefront", "instagram", "tiktok", "linktree"]

    summary = build_status_summary(stats, status=CollectionTaskStatus.COMPLETED_NO_RESULTS)

    assert "外链" in summary
    assert "Amazon storefront" in summary or "amazon storefront" in summary.lower()
    assert "Instagram" in summary
    assert "TikTok" in summary
    assert "Linktree" in summary
    assert "商业" in summary
    assert "联系方式" in summary or "落地页" in summary
