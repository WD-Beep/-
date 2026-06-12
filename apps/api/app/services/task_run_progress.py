"""采集任务结构化进度与 checkpoint。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task import CollectionTask

from app.services.platform_utils import platform_identity_key

STAGE_DISCOVERY = "discovery"
STAGE_HYDRATION = "hydration"
STAGE_PERSIST = "persist"
STAGE_AI_PROCESSING = "ai_processing"
STAGE_AI_COMPLETED = "ai_completed"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"
_UNSET = object()


def profile_checkpoint_key(
    platform: str,
    profile_url: str,
    *,
    platform_unique_id: str | None = None,
) -> str:
    key = platform_identity_key(
        platform,
        profile_url,
        platform_unique_id=platform_unique_id,
    )
    return f"{key[0]}:{key[1]}"


def search_checkpoint_key(platform: str, token: str) -> str:
    return f"{platform.strip().lower()}:{token.strip().lower()}"


@dataclass
class RunCheckpoint:
    completed_hashtags: list[str] = field(default_factory=list)
    completed_post_urls: list[str] = field(default_factory=list)
    completed_search_keys: list[str] = field(default_factory=list)
    hydrated_profiles: list[str] = field(default_factory=list)
    persisted_profiles: list[str] = field(default_factory=list)
    last_stage: str | None = None

    @classmethod
    def from_task(cls, task: CollectionTask) -> RunCheckpoint:
        raw = getattr(task, "run_checkpoint", None) or {}
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            completed_hashtags=list(raw.get("completed_hashtags") or []),
            completed_post_urls=list(raw.get("completed_post_urls") or []),
            completed_search_keys=list(raw.get("completed_search_keys") or []),
            hydrated_profiles=list(raw.get("hydrated_profiles") or []),
            persisted_profiles=list(raw.get("persisted_profiles") or []),
            last_stage=raw.get("last_stage"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed_hashtags": self.completed_hashtags,
            "completed_post_urls": self.completed_post_urls,
            "completed_search_keys": self.completed_search_keys,
            "hydrated_profiles": self.hydrated_profiles,
            "persisted_profiles": self.persisted_profiles,
            "last_stage": self.last_stage,
        }

    def hashtag_done(self, tag: str) -> bool:
        return tag.strip().lstrip("#").lower() in {t.lower() for t in self.completed_hashtags}

    def mark_hashtag(self, tag: str) -> None:
        clean = tag.strip().lstrip("#")
        if clean and not self.hashtag_done(clean):
            self.completed_hashtags.append(clean)

    def post_url_done(self, url: str) -> bool:
        key = url.strip().lower().rstrip("/")
        return key in {u.lower().rstrip("/") for u in self.completed_post_urls}

    def mark_post_url(self, url: str) -> None:
        clean = url.strip()
        if clean and not self.post_url_done(clean):
            self.completed_post_urls.append(clean)

    def search_done(self, platform: str, token: str) -> bool:
        key = search_checkpoint_key(platform, token)
        return key in set(self.completed_search_keys)

    def mark_search(self, platform: str, token: str) -> None:
        key = search_checkpoint_key(platform, token)
        if key not in self.completed_search_keys:
            self.completed_search_keys.append(key)

    def hydrated_done(self, platform: str, profile_url: str) -> bool:
        key = profile_checkpoint_key(platform, profile_url)
        return key in set(self.hydrated_profiles)

    def mark_hydrated(self, platform: str, profile_url: str) -> None:
        key = profile_checkpoint_key(platform, profile_url)
        if key not in self.hydrated_profiles:
            self.hydrated_profiles.append(key)

    def persisted_done(
        self,
        platform: str,
        profile_url: str,
        *,
        platform_unique_id: str | None = None,
    ) -> bool:
        key = profile_checkpoint_key(platform, profile_url, platform_unique_id=platform_unique_id)
        return key in set(self.persisted_profiles)

    def mark_persisted(
        self,
        platform: str,
        profile_url: str,
        *,
        platform_unique_id: str | None = None,
    ) -> None:
        key = profile_checkpoint_key(platform, profile_url, platform_unique_id=platform_unique_id)
        if key not in self.persisted_profiles:
            self.persisted_profiles.append(key)


def progress_summary(
    *,
    stage: str,
    processed: int,
    total: int,
    success: int,
    skipped: int,
    failed: int,
    target_qualified: int | None = None,
) -> str:
    stage_label = {
        STAGE_DISCOVERY: "发现",
        STAGE_HYDRATION: "补采",
        STAGE_PERSIST: "入库",
        STAGE_AI_PROCESSING: "AI 评分",
        STAGE_AI_COMPLETED: "AI 完成",
    }.get(stage, stage)
    if stage == STAGE_PERSIST and target_qualified and target_qualified > 0:
        return (
            f"{stage_label}中… 已入库 {success}/{target_qualified}，"
            f"已处理 {processed}/{total or '?'}，跳过 {skipped}，过滤 {failed}"
        )
    return f"{stage_label}中… 已处理 {processed}/{total}，成功 {success}，跳过 {skipped}，失败 {failed}"


async def update_task_progress(
    db: AsyncSession,
    task: CollectionTask,
    *,
    stage: str | None = None,
    processed: int | None = None,
    total: int | None = None,
    success: int | None = None,
    skipped: int | None = None,
    failed: int | None = None,
    last_error: str | None | object = _UNSET,
    checkpoint: RunCheckpoint | None = None,
    target_qualified: int | None = None,
    commit: bool = True,
) -> None:
    if stage is not None:
        task.current_stage = stage
    if processed is not None:
        task.processed_count = processed
    if total is not None:
        task.total_estimate = total
    if success is not None:
        task.success_count = success
        task.inserted_count = success
        task.result_count = success
    if skipped is not None:
        task.skipped_count = skipped
    if failed is not None:
        task.failed_count = failed
    if last_error is not _UNSET:
        task.last_error = last_error[:2000] if last_error else None
    if checkpoint is not None:
        checkpoint.last_stage = stage or checkpoint.last_stage
        task.run_checkpoint = checkpoint.to_dict()

    proc = task.processed_count or 0
    total_val = task.total_estimate or 0
    succ = task.success_count or 0
    skip = task.skipped_count or 0
    fail = task.failed_count or 0
    current_stage = task.current_stage or STAGE_DISCOVERY
    task.status_summary = progress_summary(
        stage=current_stage,
        processed=proc,
        total=total_val,
        success=succ,
        skipped=skip,
        failed=fail,
        target_qualified=target_qualified,
    )
    if commit:
        await db.commit()


def reset_run_progress(task: CollectionTask) -> None:
    task.processed_count = 0
    task.success_count = 0
    task.failed_count = 0
    task.skipped_count = 0
    task.total_estimate = 0
    task.current_stage = STAGE_DISCOVERY
    task.last_error = None
    task.run_checkpoint = {}
