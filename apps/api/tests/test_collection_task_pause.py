from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from app.models.enums import CandidateStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.services import task_candidate
from app.services.collection_runner import CollectionRunnerService
from app.services.task_candidate import TaskCandidateService


@pytest.mark.asyncio
async def test_persist_inserted_candidate_snapshot_filters_non_inserted_rows(monkeypatch):
    cleared: list[int] = []
    inserted: list[dict] = []

    async def clear_for_task(_db, task_id: int) -> None:
        cleared.append(task_id)

    async def bulk_insert(_db, task_id: int, rows: list[dict], **_kwargs) -> None:
        assert task_id == 42
        inserted.extend(rows)

    monkeypatch.setattr(TaskCandidateService, "clear_for_task", clear_for_task)
    monkeypatch.setattr(TaskCandidateService, "bulk_insert", bulk_insert)
    monkeypatch.setattr(TaskCandidateService, "sync_task_inserted_stats", AsyncMock())

    db = SimpleNamespace(flush=AsyncMock())
    task = SimpleNamespace(id=42, product_id=7, user_id=13)
    rows = [
        {"username": "saved", "status": CandidateStatus.INSERTED.value},
        {"username": "filtered", "status": CandidateStatus.FILTERED_OUT.value},
        {"username": "failed", "status": CandidateStatus.PROFILE_FAILED.value},
    ]

    count = await CollectionRunnerService._persist_inserted_candidate_snapshot(
        db,
        task,
        rows,
        run_at=datetime.now(UTC),
    )

    assert count == 1
    assert cleared == [42]
    assert [row["username"] for row in inserted] == ["saved"]
    db.flush.assert_awaited_once()
    TaskCandidateService.sync_task_inserted_stats.assert_awaited_once_with(db, task)


@pytest.mark.asyncio
async def test_empty_inserted_snapshot_does_not_clear_previous_paused_results(monkeypatch):
    clear_for_task = AsyncMock()
    monkeypatch.setattr(TaskCandidateService, "clear_for_task", clear_for_task)
    monkeypatch.setattr(TaskCandidateService, "bulk_insert", AsyncMock())
    monkeypatch.setattr(TaskCandidateService, "sync_task_inserted_stats", AsyncMock())

    count = await CollectionRunnerService._persist_inserted_candidate_snapshot(
        SimpleNamespace(flush=AsyncMock()),
        SimpleNamespace(id=42, product_id=7, user_id=13),
        [{"username": "filtered", "status": CandidateStatus.FILTERED_OUT.value}],
        run_at=datetime.now(UTC),
    )

    assert count == 0
    clear_for_task.assert_not_awaited()


def test_candidate_backfill_has_sql_and_operator_available():
    assert callable(task_candidate.and_)


def test_global_profile_whatsapp_column_accepts_full_contact_urls():
    assert GlobalInfluencerProfile.__table__.c.whatsapp.type.length == 1024


def test_resume_reprocesses_checkpointed_item_when_database_record_is_missing():
    missing_record = None
    inserted_record = SimpleNamespace(is_inserted=True)

    assert CollectionRunnerService._should_skip_checkpointed_item(
        resume=False,
        product_record=missing_record,
    ) is True
    assert CollectionRunnerService._should_skip_checkpointed_item(
        resume=True,
        product_record=missing_record,
    ) is False
    assert CollectionRunnerService._should_skip_checkpointed_item(
        resume=True,
        product_record=inserted_record,
    ) is True


@pytest.mark.asyncio
async def test_resume_uses_real_inserted_candidate_count_instead_of_stale_task_stats(monkeypatch):
    count_by_status = AsyncMock(return_value=0)
    monkeypatch.setattr(TaskCandidateService, "count_by_status", count_by_status)
    task = SimpleNamespace(id=42, inserted_count=7, success_count=7)

    inserted = await CollectionRunnerService._resume_inserted_count(SimpleNamespace(), task)

    assert inserted == 0
    count_by_status.assert_awaited_once_with(
        ANY,
        42,
        status=CandidateStatus.INSERTED.value,
    )
