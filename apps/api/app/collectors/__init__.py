from app.collectors.apify import ApifyCollector

from app.collectors.base import BaseCollector

from app.core.config import settings

from app.core.exceptions import MOCK_COLLECTOR_DISABLED_MSG
from app.services.api_direct_provider import task_platforms
from app.services.instagram_provider import InstagramProviderError, ensure_instagram_provider_ready

from app.models.collection_task import CollectionTask


_COLLECTOR_REGISTRY: dict[str, type[BaseCollector]] = {
    "apify": ApifyCollector,
}


def get_collector(task: CollectionTask) -> BaseCollector:
    """Instagram 任务校验 provider；非 Instagram 平台在各自 provider 内单独处理 API Direct。"""
    platforms = task_platforms(task)
    has_instagram = "instagram" in platforms

    mode = settings.collector_mode.lower()

    if mode == "mock":
        raise RuntimeError(MOCK_COLLECTOR_DISABLED_MSG)

    if not has_instagram:
        return ApifyCollector()

    if mode in ("auto", "apify", "youtube"):
        try:
            ensure_instagram_provider_ready()
        except InstagramProviderError as exc:
            raise RuntimeError(str(exc)) from exc
        return ApifyCollector()

    collector_cls = _COLLECTOR_REGISTRY.get(mode)
    if collector_cls is None:
        raise RuntimeError(f"未知采集模式: {mode}，当前仅支持 apify / auto")
    return collector_cls()


__all__ = [
    "ApifyCollector",
    "BaseCollector",
    "CollectedInfluencer",
    "get_collector",
]
