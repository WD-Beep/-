"""红人来源作品链接记录与去重。"""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.influencer_source import (
    InfluencerSourceService,
    normalize_source_key,
    resolve_source_fields,
)


def test_resolve_source_fields_keeps_post_separate_from_profile():
    profile = "https://www.tiktok.com/@waka4103"
    post = "https://www.tiktok.com/@waka4103/video/7467090233212345678"
    resolved_post, resolved_input, key = resolve_source_fields(
        source_post_url=post,
        source_input_url="https://vm.tiktok.com/abc123/",
        profile_url=profile,
    )
    assert resolved_post == post
    assert resolved_input == "https://vm.tiktok.com/abc123/"
    assert key == normalize_source_key(post)


def test_resolve_source_fields_rejects_profile_as_post_url():
    profile = "https://www.tiktok.com/@waka4103"
    resolved_post, resolved_input, key = resolve_source_fields(
        source_post_url=profile,
        source_input_url=profile,
        profile_url=profile,
    )
    assert resolved_post is None
    assert resolved_input == profile
    assert key == normalize_source_key(profile)


def test_aggregate_for_export_joins_multiple_sources():
    sources = [
        SimpleNamespace(
            source_post_url="https://www.tiktok.com/@a/video/1",
            source_input_url="https://vm.tiktok.com/1",
            task_name="任务A",
            task_id=10,
            source_platform="tiktok",
            collected_at=datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC),
        ),
        SimpleNamespace(
            source_post_url="https://www.tiktok.com/@a/video/2",
            source_input_url="https://vm.tiktok.com/2",
            task_name="任务B",
            task_id=11,
            source_platform="tiktok",
            collected_at=datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC),
        ),
    ]
    aggregated = InfluencerSourceService.aggregate_for_export(sources)
    assert "video/1" in aggregated["source_post_url"]
    assert "video/2" in aggregated["source_post_url"]
    assert "vm.tiktok.com/1" in aggregated["source_input_url"]
    assert "任务A" in aggregated["source_task_name"]
    assert "2026-06-04" in aggregated["collected_at"]
