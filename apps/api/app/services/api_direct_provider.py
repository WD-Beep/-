"""API Direct 多平台统一 provider 注册与调度。"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.services.api_direct_client import reset_request_budget
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
from app.services.platform_types import SUPPORTED_PLATFORMS, PlatformCapability, PlatformDiscoveryResult
from app.services.task_run_progress import RunCheckpoint

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
        return PlatformCapability(
            platform=platform,
            label=platform,
            status="not_available",
            message=f"暂未接入该平台（{platform}）",
            endpoints=[],
        )
    return enrich_platform_capability(provider_cls.capability())


def list_platform_capabilities() -> list[PlatformCapability]:
    return [get_platform_capability(name) for name in SUPPORTED_PLATFORMS]


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

    async def _safe_discover(platform: str) -> PlatformDiscoveryResult:
        try:
            return await discover_platform(task, platform, checkpoint=checkpoint)
        except Exception as exc:
            return PlatformDiscoveryResult(
                platform=platform,
                fatal=True,
                errors=[str(exc)],
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
    return results
