"""多平台采集主链路：任务创建、provider 路由、部分失败与入库路径。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from pydantic import ValidationError

from app.models.collection_task import CollectionTask
from app.models.enums import CollectionMode, CollectionTaskStatus
from app.schemas.collection_task import CollectionTaskCreate
from app.services.collection_runner import (
    CollectionRunnerService,
    _annotate_instagram_failure_in_aggregate,
    run_instagram_pipeline_with_provider_check,
)
from app.services.link_import import LinkImportService
from app.services.multi_platform_runner import (
    build_multi_platform_summary,
    determine_multi_platform_status,
    merge_platform_results,
)
from app.services.instagram_pipeline import PipelineRunStats
from app.services.platform_types import PlatformDiscoveryResult
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
    identity_key_for_item,
)
from app.collectors.base import CollectedInfluencer


def _discovery_payload(**overrides):
    payload = {
        "name": "multi-platform task",
        "collection_mode": "discovery",
        "keywords": ["amazon finds"],
        "schedule_enabled": False,
        "email_enabled": False,
        "email_recipients": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "platform",
    ["instagram", "youtube", "tiktok", "facebook"],
)
def test_keyword_discovery_task_create_for_core_platforms(platform: str):
    task = CollectionTaskCreate(**_discovery_payload(platform=platform, platforms=[platform]))
    assert task.platform == platform
    assert task.platforms == [platform]
    assert task.keywords == ["amazon finds"]


def test_link_import_profile_platforms_still_supported():
    cases = [
        ("https://www.instagram.com/example_user/", "instagram"),
        ("https://www.pinterest.com/example_user/", "pinterest"),
        ("https://www.shopltk.com/explore/example_user", "ltk"),
        ("https://shopmy.us/example_user", "shopmy"),
    ]
    for url, platform in cases:
        task = CollectionTaskCreate(
            name=f"import-{platform}",
            collection_mode=CollectionMode.LINK_IMPORT,
            platform="instagram",
            input_urls=[url],
        )
        assert task.collection_mode == CollectionMode.LINK_IMPORT
        assert task.platform == platform


def test_collection_runner_routes_link_import_tasks_to_link_import_service(monkeypatch):
    from app.services import collection_runner

    assert collection_runner.LinkImportService is LinkImportService

    task = CollectionTask(
        id=123,
        name="link import runner",
        status=CollectionTaskStatus.PENDING.value,
        collection_mode=CollectionMode.LINK_IMPORT.value,
        platform="ltk",
        input_urls=["https://www.shopltk.com/explore/example_user"],
    )
    calls = []

    class FakeDb:
        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    async def fake_run_collection_task(db, task_arg):
        calls.append((db, task_arg))
        return {"new_count": 1, "updated_count": 0, "skipped_count": 0}

    async def noop_claim(task_id):
        assert task_id == task.id

    async def noop_release(task_id):
        assert task_id == task.id

    monkeypatch.setattr(LinkImportService, "run_collection_task", fake_run_collection_task)
    monkeypatch.setattr(CollectionRunnerService, "_claim_collection_run", noop_claim)
    monkeypatch.setattr(CollectionRunnerService, "_release_collection_run", noop_release)

    db = FakeDb()
    result = anyio.run(CollectionRunnerService.run_task, db, task)

    assert result == {"new_count": 1, "updated_count": 0, "skipped_count": 0}
    assert calls == [(db, task)]


def test_youtube_provider_not_configured_returns_clear_error():
    from app.core.config import settings
    from app.services.platform_providers.youtube_api_direct import YouTubeApiDirectProvider

    task = CollectionTask(
        name="yt",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazon seller"],
        collection_mode="discovery",
    )

    async def _run():
        with patch.object(settings, "api_direct_api_key", ""):
            return await YouTubeApiDirectProvider.discover(task)

    result = anyio.run(_run)
    assert result.skipped is True
    assert "未配置" in (result.skip_reason or "")


def test_tiktok_provider_routes_to_apify_when_configured():
    from app.services.api_direct_provider import _provider_cls
    from app.core.config import settings

    with patch.object(settings, "tiktok_data_provider", "apify"):
        assert _provider_cls("tiktok").__name__ == "TikTokApifyProvider"


def test_facebook_provider_routes_to_apify_when_configured():
    from app.services.api_direct_provider import _provider_cls
    from app.core.config import settings

    with patch.object(settings, "facebook_data_provider", "apify"):
        assert _provider_cls("facebook").__name__ == "FacebookApifyProvider"


def test_instagram_provider_failure_returns_pipeline_error_without_raising():
    task = CollectionTask(
        name="ig",
        platform="multi",
        platforms=["instagram", "tiktok"],
        keywords=["travel"],
        collection_mode="discovery",
    )

    async def _run():
        with patch(
            "app.services.collection_runner.get_collector",
            side_effect=RuntimeError("Instagram 未配置 Apify Token，请在系统设置中配置 APIFY_TOKEN"),
        ):
            return await run_instagram_pipeline_with_provider_check(
                task,
                db=None,
                checkpoint=SimpleNamespace(),
            )

    result = anyio.run(_run)
    assert result.stats.discovery_api_failed is True
    assert result.errors
    assert "Instagram" in result.errors[0]


def test_multi_platform_instagram_failure_other_platform_continues():
    ok = PlatformDiscoveryResult(
        platform="tiktok",
        items=[object()],
        discovered_count=1,
        deduped_count=1,
        profile_fetched_count=1,
        api_requests=1,
    )
    aggregate = merge_platform_results(
        instagram_result=None,
        instagram_funnel=None,
        instagram_errors=["[instagram] Instagram 未配置 Apify Token"],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[ok],
    )
    from app.services.instagram_pipeline import InstagramPipelineResult, PipelineRunStats

    pipeline_result = InstagramPipelineResult(
        errors=["[instagram] Instagram 未配置 Apify Token"],
        stats=PipelineRunStats(discovery_api_failed=True),
    )
    _annotate_instagram_failure_in_aggregate(aggregate, pipeline_result)

    status = determine_multi_platform_status(
        aggregate,
        inserted_count=1,
        instagram_only=False,
        instagram_fatal=True,
    )
    assert status == CollectionTaskStatus.PARTIAL_FAILED
    assert "tiktok" in aggregate.platform_successes
    assert any("instagram" in failure.lower() for failure in aggregate.platform_failures)


def test_merge_platform_results_accepts_pipeline_run_stats_without_external_link_fields():
    pipeline_stats = PipelineRunStats(
        discovered_count=12,
        deduped_count=10,
        profile_fetched_count=8,
        profile_failed_count=1,
    )
    aggregate = merge_platform_results(
        instagram_result=object(),
        instagram_funnel=pipeline_stats,
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[],
    )
    assert aggregate.funnel.discovered_count == 12
    assert getattr(aggregate.funnel, "external_link_count", 0) == 0


def test_build_multi_platform_summary_tolerates_pipeline_run_stats_funnel():
    pipeline_stats = PipelineRunStats(discovered_count=5, deduped_count=5)
    aggregate = merge_platform_results(
        instagram_result=object(),
        instagram_funnel=pipeline_stats,
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[],
    )
    summary = build_multi_platform_summary(
        aggregate,
        status=CollectionTaskStatus.COMPLETED_NO_RESULTS,
        inserted_count=0,
        target_qualified_count=10,
        filtered_out=5,
    )
    assert "external_link_count" not in summary
    assert "目标 10 条合格入库" in summary


def test_collection_persistence_writes_product_and_global_records():
    from datetime import UTC, datetime

    run_at = datetime.now(UTC)
    item = CollectedInfluencer(
        platform="youtube",
        username="creator_yt_001",
        profile_url="https://www.youtube.com/@creator_yt_001",
        platform_unique_id="UCcreator_yt_001234567890",
        followers_count=120000,
        engagement_rate=2.5,
        bio="amazon finds",
    )
    global_profile = create_global_profile_from_collected(item, run_at=run_at)
    product_record = create_product_influencer_from_collected(
        product_id=1,
        global_profile=global_profile,
        data=item,
        task=None,
        run_at=run_at,
    )
    assert global_profile.platform == "youtube"
    assert product_record.product_id == 1
    assert product_record.global_influencer_id == global_profile.id
    assert identity_key_for_item(item)


def test_create_rejects_unknown_platform():
    with pytest.raises(ValidationError):
        CollectionTaskCreate(**_discovery_payload(platform="twitter", platforms=["twitter"]))
