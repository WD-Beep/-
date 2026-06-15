"""API Direct 多平台统一 provider 注册与调度。"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionMode
from app.services.api_direct_client import reset_request_budget
from app.services.discovery_progress import report_discovery_progress
from app.services.platform_providers.facebook_api_direct import FacebookApiDirectProvider
from app.services.platform_providers.facebook_apify import FacebookApifyProvider
from app.services.platform_providers.instagram_api_direct import InstagramApiDirectProvider
from app.services.platform_providers.tiktok_api_direct import TikTokApiDirectProvider
from app.services.platform_providers.tiktok_apify import TikTokApifyProvider
from app.services.platform_providers.url_only import (
    LtkUrlOnlyProvider,
    PinterestUrlOnlyProvider,
    ShopMyUrlOnlyProvider,
)
from app.services.platform_providers.youtube_api_direct import YouTubeApiDirectProvider
from app.services.platform_providers.youtube_apify import YouTubeApifyProvider
from app.services.collection_sources import enrich_platform_capability
from app.services.platform_types import (
    LINK_IMPORT_HINTS,
    SUPPORTED_PLATFORMS,
    PlatformCapability,
    PlatformDiscoveryResult,
    apply_platform_feature_flags,
    platform_feature_flags,
)
from app.services.task_run_progress import RunCheckpoint, STAGE_DISCOVERY

logger = logging.getLogger(__name__)

_PROVIDER_REGISTRY = {
    "instagram": InstagramApiDirectProvider,
    "tiktok": TikTokApiDirectProvider,
    "youtube": YouTubeApiDirectProvider,
    "facebook": FacebookApiDirectProvider,
    "pinterest": PinterestUrlOnlyProvider,
    "ltk": LtkUrlOnlyProvider,
    "shopmy": ShopMyUrlOnlyProvider,
}


def normalize_platforms(platform: str | None, platforms: list[str] | None) -> list[str]:
    if platforms:
        normalized = []
        for item in platforms:
            name = (item or "").strip().lower()
            if name in SUPPORTED_PLATFORMS and name not in normalized:
                normalized.append(name)
        if normalized:
            return normalized
    legacy = (platform or "instagram").strip().lower()
    if legacy == "multi" and platforms:
        return normalize_platforms(None, platforms)
    if legacy in SUPPORTED_PLATFORMS:
        return [legacy]
    return ["instagram"]


def task_platforms(task: CollectionTask) -> list[str]:
    raw = getattr(task, "platforms", None) or []
    return normalize_platforms(task.platform, raw if isinstance(raw, list) else [])


def _provider_cls(platform: str):
    if platform == "youtube" and settings.active_youtube_provider == "apify":
        return YouTubeApifyProvider
    if platform == "tiktok" and settings.active_tiktok_provider == "apify":
        return TikTokApifyProvider
    if platform == "facebook" and settings.active_facebook_provider == "apify":
        return FacebookApifyProvider
    return _PROVIDER_REGISTRY.get(platform)


def get_platform_capability(platform: str) -> PlatformCapability:
    provider_cls = _provider_cls(platform)
    if not provider_cls:
        return _finalize_platform_capability(
            PlatformCapability(
                platform=platform,
                label=platform,
                status="not_available",
                message=f"暂未接入该平台（{platform}）",
                endpoints=[],
            )
        )
    return _finalize_platform_capability(enrich_platform_capability(provider_cls.capability()))


def _finalize_platform_capability(cap: PlatformCapability) -> PlatformCapability:
    cap = apply_platform_feature_flags(cap)
    cap.link_import_hint = LINK_IMPORT_HINTS.get(cap.platform)
    return cap


def _amazon_platform_capability() -> PlatformCapability:
    return PlatformCapability(
        platform="amazon",
        label="Amazon",
        status="supported",
        message="Amazon 商品链接用于竞品商品发现线索；主要通过链接导入，不是红人主页平台。",
        endpoints=[],
        keyword_discovery=False,
        link_import=True,
        product_seed=True,
        link_import_hint=LINK_IMPORT_HINTS["amazon"],
    )


def list_platform_capabilities() -> list[PlatformCapability]:
    caps = [_finalize_platform_capability(get_platform_capability(name)) for name in SUPPORTED_PLATFORMS]
    caps.append(_amazon_platform_capability())
    return caps


def ensure_api_direct_ready() -> None:
    if not settings.is_api_direct_configured:
        raise RuntimeError("未配置 API_DIRECT_API_KEY，API Direct 采集不可用")


async def discover_platform(
    task: CollectionTask,
    platform: str,
    *,
    checkpoint: RunCheckpoint | None = None,
) -> PlatformDiscoveryResult:
    provider_cls = _provider_cls(platform)
    if not provider_cls:
        msg = f"API Direct 暂未接入该平台（{platform}）"
        return PlatformDiscoveryResult(
            platform=platform,
            fatal=True,
            skipped=True,
            skip_reason=msg,
            errors=[msg],
        )
    if platform == "instagram":
        msg = "Instagram 应走 InstagramCollectionPipeline"
        return PlatformDiscoveryResult(platform=platform, errors=[msg], skip_reason=msg)
    if hasattr(provider_cls, "discover"):
        import inspect

        sig = inspect.signature(provider_cls.discover)
        if "checkpoint" in sig.parameters:
            return await provider_cls.discover(task, checkpoint=checkpoint)
    return await provider_cls.discover(task)


async def discover_non_instagram_platforms(
    task: CollectionTask,
    platforms: list[str],
    *,
    checkpoint: RunCheckpoint | None = None,
) -> list[PlatformDiscoveryResult]:
    reset_request_budget()
    targets = [p for p in platforms if p != "instagram"]
    if not targets:
        return []

    competitor_mode = (task.collection_mode or "") == CollectionMode.COMPETITOR_PRODUCT.value
    discovery_task = task
    platform_timeout: int | None = None
    if competitor_mode:
        from app.services.competitor_product_discovery import (
            competitor_task_for_platform_discovery,
            order_competitor_discovery_platforms,
        )

        discovery_task = competitor_task_for_platform_discovery(task)
        targets = order_competitor_discovery_platforms(targets)
        platform_timeout = max(30, settings.competitor_product_platform_timeout_seconds)

    status_lock = asyncio.Lock()
    platform_status: dict[str, str] = {p: "queued" for p in targets}

    async def _set_platform_status(platform: str, status: str, note: str | None = None) -> None:
        if not competitor_mode:
            return
        async with status_lock:
            platform_status[platform] = status
            completed = sum(1 for s in platform_status.values() if s in {"done", "partial", "timeout_skipped", "failed"})
            await report_discovery_progress(
                phase=STAGE_DISCOVERY,
                platform=platform,
                current_platform=platform if status == "searching" else None,
                platforms_completed=completed,
                platforms_total=len(targets),
                platform_discovery_status=dict(platform_status),
                partial_skip_note=note,
            )

    async def _safe_discover(platform: str) -> PlatformDiscoveryResult:
        await _set_platform_status(platform, "searching")
        try:
            if platform_timeout:
                result = await asyncio.wait_for(
                    discover_platform(discovery_task, platform, checkpoint=checkpoint),
                    timeout=platform_timeout,
                )
            else:
                result = await discover_platform(discovery_task, platform, checkpoint=checkpoint)
            if result.errors and not (result.profiles or result.items):
                await _set_platform_status(platform, "failed")
            elif result.errors:
                await _set_platform_status(platform, "partial")
            else:
                await _set_platform_status(platform, "done")
            return result
        except asyncio.TimeoutError:
            msg = f"{platform} 平台发现超时（{platform_timeout}s），已跳过该平台继续其他平台"
            logger.warning("[CompetitorProduct] platform timeout platform=%s", platform)
            await _set_platform_status(platform, "timeout_skipped", note=msg)
            return PlatformDiscoveryResult(
                platform=platform,
                fatal=False,
                errors=[msg],
                skip_reason=msg,
            )
        except Exception as exc:
            await _set_platform_status(platform, "failed")
            return PlatformDiscoveryResult(
                platform=platform,
                fatal=True,
                errors=[str(exc)],
            )

    if competitor_mode:
        await report_discovery_progress(
            phase=STAGE_DISCOVERY,
            platforms_total=len(targets),
            platforms_completed=0,
            platform_discovery_status=dict(platform_status),
            partial_skip_note=f"多平台并发搜索（{len(targets)} 个平台，每平台最多 {platform_timeout}s）",
        )

    outcomes = await asyncio.gather(*(_safe_discover(p) for p in targets), return_exceptions=True)
    results: list[PlatformDiscoveryResult] = []
    for platform, outcome in zip(targets, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            results.append(
                PlatformDiscoveryResult(platform=platform, fatal=True, errors=[str(outcome)])
            )
        else:
            results.append(outcome)

    if competitor_mode:
        from app.services.competitor_product_discovery import apply_competitor_product_relevance_to_platform_results

        apply_competitor_product_relevance_to_platform_results(results, task)
        await report_discovery_progress(
            phase=STAGE_DISCOVERY,
            platforms_completed=len(targets),
            platforms_total=len(targets),
            platform_discovery_status=dict(platform_status),
        )

    return results
