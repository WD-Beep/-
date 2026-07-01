"""多平台采集主链路：任务创建、provider 路由、部分失败与入库路径。"""

from __future__ import annotations

from types import SimpleNamespace
import asyncio
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from pydantic import ValidationError

from app.models.collection_task import CollectionTask
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.schemas.collection_task import CollectionTaskCreate
from app.services.collection_runner import (
    CollectionRunnerService,
    _annotate_instagram_failure_in_aggregate,
    _split_keyword_seed_platforms,
    run_instagram_pipeline_with_provider_check,
)
from app.services.collection_task import CollectionTaskService
from app.services.link_import import LinkImportService
from app.services.link_import import LinkImportExecuteResult
from app.services.multi_platform_runner import (
    build_multi_platform_error_prefix,
    build_multi_platform_summary,
    determine_multi_platform_status,
    merge_platform_results,
)
from app.services.api_direct_provider import discover_non_instagram_platforms
from app.services.shopping_seed_runner import KeywordSeedDiscoveryResult
from app.services.collect_errors import summarize_errors
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


def test_stable_collection_mode_applies_conservative_task_defaults():
    payload = CollectionTaskCreate(
        **_discovery_payload(
            platform="multi",
            platforms=["youtube", "tiktok", "facebook"],
            discovery_limit=100,
            require_email=True,
            require_contact=True,
            strict_quality_filter=True,
            insert_qualified_only=True,
            stable_collection_mode=True,
        )
    )
    data = CollectionTaskService._serialize_task_data(payload.model_dump())
    data = CollectionTaskService._apply_high_value_first_defaults(data, set(payload.model_fields_set))
    data = CollectionTaskService._apply_stable_collection_defaults(data)

    assert data["discovery_limit"] == 20
    assert data["require_email"] is False
    assert data["require_contact"] is False
    assert data["strict_quality_filter"] is False
    assert data["insert_qualified_only"] is False
    assert data["platform"] == "youtube"
    assert data["platforms"] == ["youtube"]
    assert data["run_checkpoint"]["stable_collection_mode"] is True


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


def test_keyword_seed_platforms_split_from_provider_discovery():
    task = CollectionTask(
        name="keyword seed",
        collection_mode=CollectionMode.DISCOVERY.value,
        platform="multi",
        platforms=["instagram", "pinterest", "shopmy"],
        keywords=["travel bag"],
    )
    discovery_platforms, seed_platforms = _split_keyword_seed_platforms(
        task,
        ["instagram", "pinterest", "shopmy"],
    )
    assert discovery_platforms == ["instagram"]
    assert seed_platforms == ["pinterest", "shopmy"]


def test_keyword_seed_platforms_run_seed_discovery_from_main_runner(monkeypatch):
    task = CollectionTask(
        id=456,
        name="shopmy keyword seed",
        collection_mode=CollectionMode.DISCOVERY.value,
        platform="shopmy",
        platforms=["shopmy"],
        product_id=1,
        keywords=["travel bag"],
        discovery_limit=10,
        status=CollectionTaskStatus.PENDING.value,
        schedule_enabled=False,
        email_enabled=False,
    )
    calls = []
    inserted_rows = []

    exec_result = LinkImportExecuteResult(
        new_count=1,
        updated_count=0,
        not_inserted_count=0,
        filtered_out_count=0,
        hydrated_profile_count=1,
        candidate_rows=[{"platform": "shopmy", "username": "seed_creator"}],
    )

    async def fake_seed_discovery(db, task_arg, *, run_at=None):
        calls.append((db, task_arg, run_at))
        return KeywordSeedDiscoveryResult(
            exec_result=exec_result,
            discovered_count=1,
            seed_enriched_count=1,
            platform_failed_count=0,
            skipped_platform_count=0,
        )

    async def noop_async(*_args, **_kwargs):
        return None

    async def empty_existing(*_args, **_kwargs):
        return {}

    async def capture_bulk_insert(_db, _task_id, rows, **_kwargs):
        inserted_rows.extend(rows)

    monkeypatch.setattr(CollectionRunnerService, "_claim_collection_run", noop_async)
    monkeypatch.setattr(CollectionRunnerService, "_release_collection_run", noop_async)
    monkeypatch.setattr("app.services.collection_runner.InfluencerPersistenceService.find_global_profiles_batch", empty_existing)
    monkeypatch.setattr(
        "app.services.collection_runner.InfluencerPersistenceService.find_product_influencers_batch",
        empty_existing,
    )
    monkeypatch.setattr("app.services.collection_runner.TaskCandidateService.clear_for_task", noop_async)
    monkeypatch.setattr("app.services.collection_runner.TaskCandidateService.bulk_insert", capture_bulk_insert)
    monkeypatch.setattr("app.services.collection_runner.TaskCandidateService.sync_task_inserted_stats", noop_async)
    monkeypatch.setattr("app.services.collection_runner.TaskInfluencerService.refresh_task_stats", noop_async)
    monkeypatch.setattr(
        "app.services.shopping_seed_runner.ShoppingSeedDiscoveryService.run_keyword_seed_discovery",
        fake_seed_discovery,
    )

    class FakeDb:
        async def commit(self):
            return None

        async def refresh(self, *_args, **_kwargs):
            return None

        async def execute(self, *_args, **_kwargs):
            return None

        async def flush(self):
            return None

    result = anyio.run(CollectionRunnerService.run_task, FakeDb(), task)

    assert len(calls) == 1
    assert result["new_count"] == 1
    assert result["inserted_count"] == 1
    assert result["profile_fetched_count"] == 1
    assert task.status == CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
    assert task.result_count == 1
    assert task.run_checkpoint["keyword_seed_discovery"]["seed_platforms"] == ["shopmy"]
    assert inserted_rows == exec_result.candidate_rows


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


def test_single_platform_timeout_does_not_block_other_platform(monkeypatch):
    task = CollectionTask(
        id=1,
        name="competitor timeout isolation",
        platform="multi",
        platforms=["youtube", "facebook"],
        keywords=["amazon finds"],
        collection_mode=CollectionMode.COMPETITOR_PRODUCT.value,
        discovery_limit=10,
    )

    async def fake_discover_platform(_task, platform, *, checkpoint=None):
        if platform == "youtube":
            raise TimeoutError("youtube timeout")
        return PlatformDiscoveryResult(
            platform=platform,
            items=[object()],
            discovered_count=1,
            deduped_count=1,
            profile_fetched_count=1,
            api_requests=1,
        )

    monkeypatch.setattr(
        "app.services.api_direct_provider.discover_platform",
        fake_discover_platform,
    )
    monkeypatch.setattr(
        "app.services.competitor_product_discovery.competitor_task_for_platform_discovery",
        lambda task_arg: task_arg,
    )
    monkeypatch.setattr(
        "app.services.competitor_product_discovery.order_competitor_discovery_platforms",
        lambda platforms: platforms,
    )
    monkeypatch.setattr(
        "app.services.competitor_product_discovery.apply_competitor_product_relevance_to_platform_results",
        lambda results, task_arg: None,
    )

    results = anyio.run(
        discover_non_instagram_platforms,
        task,
        ["youtube", "facebook"],
    )

    by_platform = {result.platform: result for result in results}
    assert by_platform["youtube"].skipped is True
    assert by_platform["youtube"].provider_availability_state["youtube"]["reason"] == "timeout"
    assert by_platform["facebook"].items
    aggregate = merge_platform_results(
        instagram_result=None,
        instagram_funnel=None,
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=results,
    )
    assert aggregate.platform_api_counts["facebook"] == 1
    assert aggregate.provider_availability_state["youtube"]["reason"] == "timeout"


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


def test_multi_platform_summary_preserves_platform_error_detail_and_skip_reason():
    aggregate = merge_platform_results(
        instagram_result=None,
        instagram_funnel=None,
        instagram_errors=["[instagram] Apify actor timed out after 90s"],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[
            PlatformDiscoveryResult(
                platform="tiktok",
                api_requests=8,
                fatal=True,
                errors=[
                    "query HOMEHIVE clear PVC jewelry bags: API Direct 429 rate limit",
                    "query HOMEHIVE 20 clear bags: actor timeout",
                ],
            ),
            PlatformDiscoveryResult(platform="facebook", api_requests=9, errors=[]),
            PlatformDiscoveryResult(
                platform="youtube",
                api_requests=0,
                skipped=True,
                skip_reason="YouTube 未执行：API Direct Token 未配置",
            ),
        ],
    )
    status = determine_multi_platform_status(
        aggregate,
        inserted_count=0,
        instagram_only=False,
        instagram_fatal=True,
    )
    summary = build_multi_platform_summary(
        aggregate,
        status=status,
        inserted_count=0,
        target_qualified_count=50,
        overfetch_stop_reason="平台无更多结果",
    )

    assert status == CollectionTaskStatus.PARTIAL_FAILED
    assert "instagram: Apify actor timed out after 90s" in summary
    assert "tiktok: failed (API 8 calls): query HOMEHIVE clear PVC jewelry bags: API Direct 429 rate limit" in summary
    assert "facebook: no same-product results (API 9 calls)" in summary
    assert "youtube: skipped (API 0 calls): YouTube 未执行：API Direct Token 未配置" in summary
    assert "queries 2" in summary


def test_multi_platform_all_apis_normal_empty_is_completed_no_results():
    aggregate = merge_platform_results(
        instagram_result=object(),
        instagram_funnel=PipelineRunStats(discovered_count=0),
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[
            PlatformDiscoveryResult(platform="tiktok", api_requests=2),
            PlatformDiscoveryResult(platform="facebook", api_requests=3),
            PlatformDiscoveryResult(platform="youtube", api_requests=4),
        ],
    )
    status = determine_multi_platform_status(
        aggregate,
        inserted_count=0,
        instagram_only=False,
        instagram_fatal=False,
    )
    summary = build_multi_platform_summary(
        aggregate,
        status=status,
        inserted_count=0,
        target_qualified_count=50,
    )

    assert status == CollectionTaskStatus.COMPLETED_NO_RESULTS
    assert "多平台任务完成，未发现同款产品合作红人" in summary
    assert "平台无更多结果" not in summary
    assert "未发现同款产品合作红人" in summary


def test_multi_platform_error_message_uses_platform_api_prefix_not_instagram_only():
    aggregate = merge_platform_results(
        instagram_result=None,
        instagram_funnel=None,
        instagram_errors=["[instagram] Apify actor timed out after 90s"],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[
            PlatformDiscoveryResult(
                platform="tiktok",
                api_requests=8,
                fatal=True,
                errors=["query HOMEHIVE clear PVC jewelry bags: API Direct 429 rate limit"],
            ),
            PlatformDiscoveryResult(
                platform="youtube",
                api_requests=0,
                skipped=True,
                skip_reason="YouTube 未执行：API Direct Token 未配置",
            ),
        ],
    )

    message = summarize_errors(
        aggregate.collection_errors,
        prefix=build_multi_platform_error_prefix(
            aggregate,
            discovery_api_failed=True,
            instagram_only=False,
        ),
    )

    assert message is not None
    assert message.startswith("多平台采集部分平台异常：")
    assert "Instagram 采集 API 失败" not in message
    assert "Apify actor timed out after 90s" in message
    assert "API Direct 429 rate limit" in message
    assert "YouTube 未执行：API Direct Token 未配置" in message


def test_facebook_slow_empty_discovery_is_completed_no_results():
    aggregate = merge_platform_results(
        instagram_result=None,
        instagram_funnel=None,
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[
            PlatformDiscoveryResult(
                platform="facebook",
                api_requests=2,
                errors=[
                    "Facebook Apify 搜索「amazon home decor」耗时 45s 但未返回候选，可能关键词无结果或平台响应慢",
                    "Facebook 发现阶段结束：Apify/API 响应较慢或关键词暂无匹配结果（共搜索 2/2 个关键词）",
                ],
                fatal=False,
            ),
        ],
    )
    status = determine_multi_platform_status(
        aggregate,
        inserted_count=0,
        instagram_only=False,
        instagram_fatal=False,
    )

    assert status == CollectionTaskStatus.COMPLETED_NO_RESULTS
    assert "facebook" in aggregate.platform_completed
    assert not aggregate.platform_failures


def test_multi_platform_api_zero_with_error_is_skipped_not_no_result():
    aggregate = merge_platform_results(
        instagram_result=object(),
        instagram_funnel=PipelineRunStats(discovered_count=0),
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[
            PlatformDiscoveryResult(
                platform="youtube",
                api_requests=0,
                errors=["youtube 平台发现超时（90s），已跳过该平台继续其他平台"],
                skip_reason="youtube 平台发现超时（90s），已跳过该平台继续其他平台",
            ),
            PlatformDiscoveryResult(platform="facebook", api_requests=3),
        ],
    )
    status = determine_multi_platform_status(
        aggregate,
        inserted_count=0,
        instagram_only=False,
        instagram_fatal=False,
    )
    summary = build_multi_platform_summary(
        aggregate,
        status=status,
        inserted_count=0,
        target_qualified_count=50,
    )

    assert status == CollectionTaskStatus.PARTIAL_FAILED
    assert "youtube: skipped (API 0 calls): youtube 平台发现超时" in summary
    assert "youtube: no same-product results" not in summary


def test_multi_platform_summary_compacts_many_instagram_errors():
    aggregate = merge_platform_results(
        instagram_result=object(),
        instagram_funnel=PipelineRunStats(discovered_count=0),
        instagram_errors=[
            "[instagram] Hashtag 帖子 post#1 post_author_missing: 无法提取作者主页",
            "[instagram] Hashtag ['b0d9w576kq'] 共 1 条帖子，但未解析到任何作者主页",
            "[instagram] Hashtag ['homehivejewelrybags'] 共 1 条帖子，但未解析到任何作者主页",
        ],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[],
    )

    summary = build_multi_platform_summary(
        aggregate,
        status=CollectionTaskStatus.COMPLETED_NO_RESULTS,
        inserted_count=0,
        target_qualified_count=50,
    )

    assert "post#1" in summary
    assert "b0d9w576kq" in summary
    assert "homehivejewelrybags" not in summary
    assert "另有 1 条详情见错误详情" in summary
    assert len(aggregate.collection_errors) == 3


def test_merge_platform_results_preserves_same_product_filtered_counts_and_rows():
    aggregate = merge_platform_results(
        instagram_result=object(),
        instagram_funnel=PipelineRunStats(discovered_count=0),
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[
            PlatformDiscoveryResult(
                platform="youtube",
                items=[],
                profiles=[],
                candidate_rows=[
                    {
                        "username": "other_brand",
                        "profile_url": "https://www.youtube.com/@other-brand",
                        "platform": "youtube",
                        "status": CandidateStatus.FILTERED_OUT.value,
                        "failure_reason": "no_same_product_match",
                    }
                ],
                discovered_count=3,
                deduped_count=2,
                profile_fetched_count=2,
                api_requests=8,
                errors=["YouTube same-product filter kept 0/2: missing_brand_for_same_product 2"],
            )
        ],
    )

    assert aggregate.funnel.discovered_count == 3
    assert aggregate.funnel.deduped_count == 2
    assert aggregate.funnel.profile_fetched_count == 2
    assert aggregate.funnel.filtered_out_count == 1
    assert aggregate.candidate_rows[0]["failure_reason"] == "no_same_product_match"
    assert "youtube" in aggregate.platform_completed
    assert "youtube" not in aggregate.platform_failures


def test_multi_platform_filtered_candidates_are_not_failed():
    aggregate = merge_platform_results(
        instagram_result=object(),
        instagram_funnel=PipelineRunStats(discovered_count=3, deduped_count=3, profile_fetched_count=3),
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[],
    )
    aggregate.funnel.discovered_count = 3
    aggregate.funnel.filtered_out_count = 3
    status = determine_multi_platform_status(
        aggregate,
        inserted_count=0,
        instagram_only=False,
        instagram_fatal=False,
    )
    summary = build_multi_platform_summary(
        aggregate,
        status=status,
        inserted_count=0,
        target_qualified_count=50,
        filtered_out=3,
    )

    assert status == CollectionTaskStatus.COMPLETED_NO_RESULTS
    assert "发现候选但未达入库条件" in summary


def test_facebook_only_empty_discovery_is_completed_no_results():
    aggregate = merge_platform_results(
        instagram_result=None,
        instagram_funnel=None,
        instagram_errors=[],
        instagram_candidate_rows=[],
        instagram_collected=[],
        platform_results=[
            PlatformDiscoveryResult(
                platform="facebook",
                api_requests=2,
                errors=[
                    "Facebook 发现阶段结束：关键词/API 暂无候选结果（共搜索 2/2 个关键词）"
                ],
                fatal=False,
            ),
        ],
    )
    status = determine_multi_platform_status(
        aggregate,
        inserted_count=0,
        instagram_only=False,
        instagram_fatal=False,
    )
    summary = build_multi_platform_summary(
        aggregate,
        status=status,
        inserted_count=0,
        target_qualified_count=3,
    )

    assert status == CollectionTaskStatus.COMPLETED_NO_RESULTS
    assert "facebook" in aggregate.platform_completed
    assert "facebook" not in [failure.split(":")[0] for failure in aggregate.platform_failures]
    assert "暂无候选结果" in summary
    assert aggregate.discovery_api_failed is False


def test_apply_terminal_task_state_clears_stale_interrupt_on_success():
    from app.services.task_run_progress import apply_terminal_task_state

    task = CollectionTask(
        id=1,
        name="youtube",
        platform="youtube",
        platforms=["youtube"],
        keywords=["amazon"],
        collection_mode="discovery",
        status=CollectionTaskStatus.PARTIAL_FAILED.value,
        error_message="任务已超时中断（阶段：discovery），可重新运行从 checkpoint 继续",
        last_error="任务已超时中断（阶段：discovery），可重新运行从 checkpoint 继续",
        status_summary="任务已超时中断（阶段：discovery），可重新运行从 checkpoint 继续",
        run_checkpoint={
            "interrupted": True,
            "interrupted_stage": "discovery",
            "interrupted_at": "2026-06-19T00:00:00+00:00",
        },
    )
    # Simulate in-memory clears while DB still holds stale interrupt text.
    task.error_message = None
    task.last_error = None
    apply_terminal_task_state(
        task,
        status=CollectionTaskStatus.COMPLETED_WITH_RESULTS,
        errors=["任务已超时中断（阶段：discovery），可重新运行从 checkpoint 继续"],
        prefix="多平台采集 API 失败：",
    )

    assert task.status == CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
    assert task.error_message is None
    assert task.last_error is None
    assert task.status_summary is None
    assert task.run_checkpoint.get("interrupted") is None


def test_progress_updates_serialize_shared_session_commits():
    from app.services.discovery_progress import DiscoveryProgressReporter
    from app.services.task_run_progress import RunCheckpoint, STAGE_DISCOVERY, STAGE_HYDRATION, update_task_progress

    class ContendedDb:
        def __init__(self):
            self.in_commit = False
            self.commits = 0

        async def commit(self):
            if self.in_commit:
                raise RuntimeError("IllegalStateChangeError: commit already in progress")
            self.in_commit = True
            await asyncio.sleep(0.01)
            self.commits += 1
            self.in_commit = False

    async def _run():
        db = ContendedDb()
        task = CollectionTask(
            id=99,
            name="shared session progress",
            platform="multi",
            platforms=["instagram", "tiktok"],
            collection_mode=CollectionMode.DISCOVERY.value,
            discovery_limit=20,
        )
        checkpoint = RunCheckpoint()
        reporter = DiscoveryProgressReporter(db, task, checkpoint, target_qualified=20)

        await asyncio.gather(
            update_task_progress(
                db,
                task,
                stage=STAGE_HYDRATION,
                processed=1,
                total=2,
                success=1,
                skipped=0,
                failed=0,
                checkpoint=checkpoint,
                commit=True,
            ),
            reporter.update(
                phase=STAGE_DISCOVERY,
                discovered_count=1,
                deduped_count=1,
                platform="tiktok",
                commit=True,
            ),
        )
        assert db.commits == 2

    anyio.run(_run)


def test_multi_platform_progress_updates_do_not_decrease_aggregate_counts():
    from app.services.discovery_progress import DiscoveryProgressReporter
    from app.services.task_run_progress import RunCheckpoint, STAGE_DISCOVERY

    class FakeDb:
        async def commit(self):
            return None

    async def _run():
        task = CollectionTask(
            id=100,
            name="shared aggregate progress",
            platform="multi",
            platforms=["instagram", "tiktok", "youtube"],
            collection_mode=CollectionMode.DISCOVERY.value,
            discovery_limit=20,
            discovered_count=157,
            deduped_count=146,
            profile_fetched_count=44,
        )
        reporter = DiscoveryProgressReporter(FakeDb(), task, RunCheckpoint(), target_qualified=20)

        await reporter.update(
            phase=STAGE_DISCOVERY,
            discovered_count=0,
            deduped_count=0,
            profile_fetched_count=0,
            platform="youtube",
            current_platform="youtube",
            commit=False,
        )

        assert task.discovered_count == 157
        assert task.deduped_count == 146
        assert task.profile_fetched_count == 44

    anyio.run(_run)
