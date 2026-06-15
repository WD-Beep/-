"""采集发现阶段进度上报（YouTube 等非 Instagram 平台）。"""



from __future__ import annotations



import asyncio
import inspect
import logging
import time
from contextvars import ContextVar

from dataclasses import dataclass, field

from typing import Any



from sqlalchemy.ext.asyncio import AsyncSession



from app.core.config import settings

from app.models.collection_task import CollectionTask

from app.services.collection_funnel import build_running_discovery_summary

from app.services.task_run_progress import RunCheckpoint



logger = logging.getLogger(__name__)

_reporter: ContextVar[DiscoveryProgressReporter | None] = ContextVar("discovery_progress_reporter", default=None)





@dataclass

class DiscoveryProgressReporter:

    db: AsyncSession

    task: CollectionTask

    checkpoint: RunCheckpoint

    target_qualified: int

    discovery_started_at: float = field(default_factory=time.perf_counter)
    _commit_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)


    def _discovery_elapsed_seconds(self) -> float:

        return max(0.0, time.perf_counter() - self.discovery_started_at)



    def _should_mark_slow_api(

        self,

        *,

        phase: str,

        discovered_count: int | None,

        rate_limited: bool,

    ) -> bool:

        if rate_limited:

            return False

        discovered = discovered_count if discovered_count is not None else (self.task.discovered_count or 0)

        if discovered > 0:

            return False

        if phase not in {"discovery", "hydration"}:

            return False

        threshold = max(0, settings.youtube_discovery_slow_threshold_seconds)

        return self._discovery_elapsed_seconds() >= threshold



    async def update(

        self,

        *,

        phase: str,

        discovered_count: int | None = None,

        deduped_count: int | None = None,

        profile_fetched_count: int | None = None,

        filtered_out_count: int | None = None,

        inserted_count: int | None = None,

        rate_limited: bool = False,

        rate_limit_note: str | None = None,

        slow_api: bool | None = None,

        current_keyword: str | None = None,

        provider: str | None = None,

        keywords_completed: int | None = None,

        keywords_total: int | None = None,

        timing_note: str | None = None,

        profiles_hydrating_total: int | None = None,

        profiles_hydrating_completed: int | None = None,

        current_profile_url: str | None = None,

        partial_skip_note: str | None = None,

        platform: str | None = None,

        current_platform: str | None = None,

        platforms_completed: int | None = None,

        platforms_total: int | None = None,

        platform_discovery_status: dict[str, str] | None = None,

        commit: bool = True,

    ) -> None:

        self.task.current_stage = phase

        if discovered_count is not None:

            self.task.discovered_count = discovered_count

        if deduped_count is not None:

            self.task.deduped_count = deduped_count

        if profile_fetched_count is not None:

            self.task.profile_fetched_count = profile_fetched_count

        if filtered_out_count is not None:

            self.task.filtered_out_count = filtered_out_count

        if inserted_count is not None:

            self.task.inserted_count = inserted_count

            self.task.success_count = inserted_count

            self.task.result_count = inserted_count



        processed = inserted_count if inserted_count is not None else (profile_fetched_count or deduped_count or discovered_count or 0)

        self.task.processed_count = max(0, processed)

        total = self.target_qualified if phase == "persist" else max(self.task.discovered_count or 0, self.target_qualified)

        self.task.total_estimate = max(total, self.target_qualified)



        self.checkpoint.last_stage = phase

        extra: dict[str, Any] = dict(self.task.run_checkpoint or {})

        extra.update(self.checkpoint.to_dict())

        extra["discovery_phase"] = phase

        extra["rate_limited"] = bool(extra.get("rate_limited")) or rate_limited

        if rate_limit_note:

            extra["rate_limit_note"] = rate_limit_note

        if current_keyword:

            extra["current_keyword"] = current_keyword

        if provider:

            extra["discovery_provider"] = provider

        if keywords_completed is not None:

            extra["keywords_completed"] = keywords_completed

        if keywords_total is not None:

            extra["keywords_total"] = keywords_total

        if timing_note:

            extra["timing_note"] = timing_note

        if profiles_hydrating_total is not None:

            extra["profiles_hydrating_total"] = profiles_hydrating_total

        if profiles_hydrating_completed is not None:

            extra["profiles_hydrating_completed"] = profiles_hydrating_completed

        if current_profile_url:

            extra["current_profile_url"] = current_profile_url

        if partial_skip_note:

            extra["partial_skip_note"] = partial_skip_note

        if current_platform:

            extra["current_platform"] = current_platform

        if platforms_completed is not None:

            extra["platforms_completed"] = platforms_completed

        if platforms_total is not None:

            extra["platforms_total"] = platforms_total

        if platform_discovery_status is not None:

            merged_status = dict(extra.get("platform_discovery_status") or {})

            merged_status.update(platform_discovery_status)

            extra["platform_discovery_status"] = merged_status

        extra["discovery_elapsed_seconds"] = round(self._discovery_elapsed_seconds(), 1)



        mark_slow = slow_api if slow_api is not None else self._should_mark_slow_api(

            phase=phase,

            discovered_count=discovered_count,

            rate_limited=bool(extra.get("rate_limited")),

        )

        extra["slow_api"] = bool(mark_slow)

        self.task.run_checkpoint = extra



        if rate_limit_note:

            self.task.last_error = rate_limit_note[:2000]

        elif mark_slow and timing_note:

            self.task.last_error = timing_note[:2000]



        resolved_partial_skip = partial_skip_note or extra.get("partial_skip_note")
        if not resolved_partial_skip and timing_note and "跳过" in timing_note:
            resolved_partial_skip = timing_note

        self.task.status_summary = build_running_discovery_summary(

            phase=phase,

            target=self.target_qualified,

            discovered=self.task.discovered_count or 0,

            deduped=self.task.deduped_count or 0,

            profile_fetched=self.task.profile_fetched_count or 0,

            filtered_out=self.task.filtered_out_count or 0,

            inserted=self.task.inserted_count or 0,

            rate_limited=bool(extra.get("rate_limited")),

            slow_api=bool(extra.get("slow_api")),

            current_keyword=extra.get("current_keyword"),

            provider=extra.get("discovery_provider"),

            keywords_completed=extra.get("keywords_completed"),

            keywords_total=extra.get("keywords_total"),

            profiles_hydrating_total=extra.get("profiles_hydrating_total"),

            profiles_hydrating_completed=extra.get("profiles_hydrating_completed"),

            partial_skip_note=resolved_partial_skip,

            platform=platform or getattr(self.task, "platform", None),

            current_platform=extra.get("current_platform"),

            platforms_completed=extra.get("platforms_completed"),

            platforms_total=extra.get("platforms_total"),

            platform_discovery_status=extra.get("platform_discovery_status"),

        )



        if commit:

            async with self._commit_lock:
                await self.db.commit()




def get_discovery_reporter() -> DiscoveryProgressReporter | None:

    return _reporter.get()





def set_discovery_reporter(reporter: DiscoveryProgressReporter | None):

    return _reporter.set(reporter)





def reset_discovery_reporter(token) -> None:

    _reporter.reset(token)





async def report_discovery_progress(**kwargs) -> None:
    reporter = get_discovery_reporter()
    if not reporter:
        return
    try:
        allowed = inspect.signature(DiscoveryProgressReporter.update).parameters
        filtered = {key: value for key, value in kwargs.items() if key in allowed}
        await reporter.update(**filtered)
    except Exception:
        logger.warning("discovery progress update failed", exc_info=True)

