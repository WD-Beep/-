"""手点采集配方回归：对照任务 84 成功 vs 86/87 失败配置，零 API 调用。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import collection_filters as cf
from app.services.discovery_progress import DiscoveryProgressReporter, report_discovery_progress
from app.services.task_run_progress import RunCheckpoint


def _task(**kwargs):
    base = dict(
        collection_mode="discovery",
        discovery_limit=5,
        min_followers_count=10000,
        min_engagement_rate=0.5,
        filter_exclude_keywords=[],
        filter_include_keywords=[],
        platform="youtube",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _item(**kwargs):
    base = dict(
        platform="youtube",
        username="creator1",
        display_name="Creator One",
        profile_url="https://www.youtube.com/@creator1",
        platform_unique_id="UCtest123456789012345678",
        followers_count=8000,
        engagement_rate=1.2,
        bio="amazon finds creator",
        category=None,
        niche=None,
        country=None,
        language=None,
        content_topics=None,
        recent_post_titles=None,
        tags=None,
        collaboration_formats=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_quality_recipe_10k_passes_mid_tier_creator():
    """商用默认：1 万粉门槛，1.5 万粉中腰部应通过硬筛。"""
    result = cf.evaluate_post_hydration_hard_filter(
        _item(followers_count=15000),
        _task(min_followers_count=10000),
    )
    assert result.passed is True


def test_quality_recipe_10k_rejects_micro_creator():
    """1 万粉门槛应滤掉几千粉的微型号。"""
    result = cf.evaluate_post_hydration_hard_filter(
        _item(followers_count=8000),
        _task(min_followers_count=10000),
    )
    assert result.passed is False
    assert result.reason == "below_min_followers"


def test_task86_style_fails_hard_filter():
    """任务 86 配方：10000 粉门槛，8000 粉会被滤掉。"""
    result = cf.evaluate_post_hydration_hard_filter(
        _item(followers_count=8000),
        _task(min_followers_count=10000, min_engagement_rate=2.0),
    )
    assert result.passed is False
    assert result.reason == "below_min_followers"


def test_wide_keyword_amazonfinds_still_passes_if_metrics_ok():
    """宽词 amazonfinds 本身不挡入库，挡的是粉丝/互动门槛。"""
    result = cf.evaluate_post_hydration_hard_filter(
        _item(bio="amazonfinds deals", followers_count=15000, engagement_rate=2.5),
        _task(min_followers_count=10000, min_engagement_rate=2.0),
    )
    assert result.passed is True


@pytest.mark.anyio
async def test_report_discovery_progress_platform_kwarg_does_not_raise():
    """TikTok 旧报错：platform= 传入进度上报不得中断采集。"""
    task = SimpleNamespace(
        discovered_count=0,
        deduped_count=0,
        profile_fetched_count=0,
        filtered_out_count=0,
        inserted_count=0,
        success_count=0,
        result_count=0,
        processed_count=0,
        total_estimate=0,
        current_stage=None,
        status_summary=None,
        last_error=None,
        run_checkpoint={},
        platform="tiktok",
    )
    reporter = DiscoveryProgressReporter(
        db=AsyncMock(),
        task=task,  # type: ignore[arg-type]
        checkpoint=RunCheckpoint(),
        target_qualified=5,
    )
    reporter.db.commit = AsyncMock()

    with patch("app.services.discovery_progress.get_discovery_reporter", return_value=reporter):
        await report_discovery_progress(
            phase="discovery",
            discovered_count=3,
            platform="tiktok",
            provider="api_direct",
            current_keyword="amazon finds",
        )

    assert task.discovered_count == 3


@pytest.mark.anyio
async def test_tiktok_discover_mock_returns_candidates_without_api():
    from app.services.platform_providers.tiktok_api_direct import TikTokApiDirectProvider

    task = SimpleNamespace(
        id=999,
        keywords=["amazon finds"],
        min_followers_count=3000,
        discovery_limit=5,
        country="US",
        category=None,
    )

    fake_video = {
        "author": "testcreator",
        "author_name": "Test Creator",
        "play_count": 50000,
        "likes": 2000,
        "comments": 100,
        "url": "https://www.tiktok.com/@testcreator/video/1",
    }

    with (
        patch("app.services.platform_providers.tiktok_api_direct.settings") as mock_settings,
        patch(
            "app.services.platform_providers.tiktok_api_direct.ad_get",
            new_callable=AsyncMock,
            return_value={"videos": [fake_video]},
        ),
        patch("app.services.platform_providers.tiktok_api_direct.get_request_count", return_value=1),
        patch("app.services.platform_providers.tiktok_api_direct._api_budget_remaining", return_value=10),
        patch(
            "app.services.platform_providers.tiktok_api_direct._hydrate_tiktok_profile",
            new_callable=AsyncMock,
            side_effect=lambda p, errors: p,
        ),
    ):
        mock_settings.is_api_direct_configured = True
        mock_settings.api_direct_max_requests_per_platform = 20
        result = await TikTokApiDirectProvider.discover(task)  # type: ignore[arg-type]

    assert result.deduped_count >= 1
    assert len(result.items) >= 1
    assert result.platform == "tiktok"
