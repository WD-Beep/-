"""采集任务 bulk-delete API 回归。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import async_session_factory
from app.main import app
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus


def _task(**kwargs) -> CollectionTask:
    defaults = {
        "name": f"bulk-del-{uuid.uuid4().hex[:8]}",
        "product_id": 1,
        "collection_mode": CollectionMode.LINK_IMPORT.value,
        "platform": "tiktok",
        "platforms": ["tiktok"],
        "keywords": [],
        "input_urls": ["https://www.tiktok.com/@u/video/1"],
        "status": CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
        "last_run_at": datetime.now(UTC),
        "inserted_count": 0,
        "result_count": 0,
        "discovered_count": 0,
        "profile_fetched_count": 0,
        "is_archived": False,
    }
    defaults.update(kwargs)
    return CollectionTask(**defaults)


@pytest.mark.anyio
async def test_bulk_delete_route_is_not_shadowed_by_task_id_path():
    """POST /bulk-delete 不能被 /{task_id} 路由抢先匹配导致 405。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/collection-tasks/bulk-delete",
            headers={"X-User-Id": "1", "X-Product-Id": "1"},
            json={"task_ids": [999999999]},
        )
    assert response.status_code != 405, response.text
    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted_count"] == 0
    assert payload["archived_count"] == 0


@pytest.mark.anyio
async def test_bulk_delete_api_archives_retained_and_deletes_clean():
    clean_id: int
    archived_id: int
    skipped_id: int

    async with async_session_factory() as db:
        clean = _task(name="clean-bulk")
        archived = _task(name="archived-bulk")
        skipped = _task(
            name="effective-bulk",
            inserted_count=2,
            status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
        )
        db.add_all([clean, archived, skipped])
        await db.flush()
        clean_id = clean.id
        archived_id = archived.id
        skipped_id = skipped.id
        db.add(
            CollectionTaskCandidate(
                task_id=skipped.id,
                product_id=1,
                username="effective_creator",
                profile_url="https://www.tiktok.com/@effective_creator",
                platform="tiktok",
                status=CandidateStatus.INSERTED.value,
                is_high_value=True,
                has_email=True,
                followers_count=5000,
            )
        )
        db.add(
            CollectionTaskCandidate(
                task_id=archived.id,
                product_id=1,
                username="creator",
                profile_url="https://www.tiktok.com/@creator",
                platform="tiktok",
                status=CandidateStatus.PROFILE_FAILED.value,
                source_post_url="https://www.tiktok.com/@creator/video/1",
                source_input_url="https://www.amazon.com/dp/B0CPF3W9B2",
            )
        )
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.post(
                "/api/collection-tasks/bulk-delete",
                headers={"X-User-Id": "1", "X-Product-Id": "2"},
                json={"task_ids": [skipped_id]},
            )
            assert denied.status_code == 403

            response = await client.post(
                "/api/collection-tasks/bulk-delete",
                headers=headers,
                json={"task_ids": [clean_id, archived_id, skipped_id]},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert clean_id in payload["deleted_ids"]
            assert archived_id in payload["archived_ids"]
            assert skipped_id in payload["skipped_ids"]
            assert payload["deleted_count"] == 1
            assert payload["archived_count"] == 1
            assert payload["skipped_count"] == 1

            candidate_resp = await client.get(
                f"/api/collection-tasks/{archived_id}/candidates",
                headers=headers,
            )
            assert candidate_resp.status_code == 200
            assert candidate_resp.json()["total"] == 1
            assert candidate_resp.json()["items"][0]["source_input_url"] == "https://www.amazon.com/dp/B0CPF3W9B2"
    finally:
        async with async_session_factory() as db:
            for task_id in (archived_id, skipped_id):
                row = await db.get(CollectionTask, task_id)
                if row:
                    await db.delete(row)
            await db.commit()
