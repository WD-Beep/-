"""采集目标：discovery_limit 作为合格入库目标数，发现阶段 over-fetch。"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from app.models.collection_task import CollectionTask

DEFAULT_TARGET = 100
MAX_DISCOVERY_LIMIT = 500
OVERFETCH_RATIO = 8
MAX_OVERFETCH_ROUNDS = 3


@dataclass
class CollectionRunContext:
    target_qualified_count: int
    max_candidates: int
    round_index: int = 0
    fetch_limit: int = 0
    total_discovered: int = 0
    stop_reason: str | None = None
    exclude_profile_keys: set[tuple[str, str]] = field(default_factory=set)


_run_context: ContextVar[CollectionRunContext | None] = ContextVar("collection_run_context", default=None)


def get_run_context() -> CollectionRunContext | None:
    return _run_context.get()


def set_run_context(ctx: CollectionRunContext):
    return _run_context.set(ctx)


def reset_run_context(token) -> None:
    _run_context.reset(token)


def target_qualified_count(task: CollectionTask) -> int:
    """用户填写的 discovery_limit = 目标合格入库数。"""
    raw = task.discovery_limit or DEFAULT_TARGET
    return max(1, min(MAX_DISCOVERY_LIMIT, int(raw)))


def max_candidates_to_process(task: CollectionTask) -> int:
    """安全上限：最多处理的候选数（约为目标的 8 倍）。"""
    target = target_qualified_count(task)
    return min(MAX_DISCOVERY_LIMIT, max(target, target * OVERFETCH_RATIO))


def max_overfetch_rounds() -> int:
    return MAX_OVERFETCH_ROUNDS


def discovery_fetch_limit(task: CollectionTask, *, round_index: int | None = None) -> int:
    """发现阶段拉取上限；随 over-fetch 轮次递增。"""
    ctx = get_run_context()
    if ctx and ctx.fetch_limit > 0 and round_index is None:
        return ctx.fetch_limit
    target = target_qualified_count(task)
    round_idx = round_index if round_index is not None else (ctx.round_index if ctx else 0)
    multiplier = OVERFETCH_RATIO + round_idx * 2
    return min(MAX_DISCOVERY_LIMIT, max(target, target * multiplier))


def overfetch_pages_for_limit(limit: int) -> int:
    """API Direct 分页：按发现上限估算页数。"""
    return max(1, min(5, (limit + 29) // 30))


def qualified_inserted_count(new_count: int, updated_count: int) -> int:
    return new_count + updated_count


def should_stop_overfetch(*, qualified: int, target: int, total_processed: int, max_candidates: int) -> str | None:
    if qualified >= target:
        return "已达标"
    if total_processed >= max_candidates:
        return "已达安全上限"
    return None


def should_stop_overfetch_round(*, new_unique_count: int) -> str | None:
    """单轮补采无新增唯一候选时停止，避免无效反复拉取。"""
    if new_unique_count <= 0:
        return "平台无更多结果"
    return None


def max_overfetch_rounds_for_task(task: CollectionTask) -> int:
    """小目标减少补采轮次，降低无效等待。"""
    from app.services.competitor_product_discovery import is_competitor_product_task

    if is_competitor_product_task(task):
        return 1
    platforms = [
        str(platform).strip().lower()
        for platform in (getattr(task, "platforms", None) or [])
        if platform
    ]
    if not platforms and getattr(task, "platform", None):
        platforms = [str(task.platform).strip().lower()]
    keywords = [
        str(keyword).strip()
        for keyword in (getattr(task, "keywords", None) or [])
        if str(keyword).strip()
    ]
    if set(platforms) & {"tiktok", "youtube", "facebook"} and not keywords:
        return 1
    target = target_qualified_count(task)
    if target <= 14:
        return 2
    return MAX_OVERFETCH_ROUNDS


RATE_LIMIT_STOP_REASON = "API 限流过多，稍后重试"
