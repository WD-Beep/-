"""归档任务：候选池 API 仍可查询/导出，普通任务详情不可见。"""

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
        "name": f"archived-api-{uuid.uuid4().hex[:8]}",
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
        "discovered_count": 1,
        "profile_fetched_count": 0,
        "is_archived": False,
    }
    defaults.update(kwargs)
    return CollectionTask(**defaults)


@pytest.mark.anyio
async def test_archived_task_candidates_list_export_and_access_control():
    post_url = "https://www.tiktok.com/@creator/video/1234567890"
    input_url = "https://vm.tiktok.com/abc123/"
    task_id: int
    task_name: str

    async with async_session_factory() as db:
        task = _task()
        task_name = task.name
        db.add(task)
        await db.flush()
        task_id = task.id
        db.add(
            CollectionTaskCandidate(
                task_id=task.id,
                product_id=1,
                username="creator",
                profile_url="https://www.tiktok.com/@creator",
                platform="tiktok",
                status=CandidateStatus.PROFILE_FAILED.value,
                source_post_url=post_url,
                source_meta={"source_input_url": input_url, "input_url": input_url},
            )
        )
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            delete_resp = await client.delete(
                f"/api/collection-tasks/{task_id}",
                headers=headers,
            )
            assert delete_resp.status_code == 200, delete_resp.text
            assert delete_resp.json()["action"] == "archived"

            detail_resp = await client.get(
                f"/api/collection-tasks/{task_id}",
                headers=headers,
            )
            assert detail_resp.status_code == 404

            list_resp = await client.get(
                f"/api/collection-tasks",
                headers=headers,
                params={"search": task_name},
            )
            assert list_resp.status_code == 200
            listed_ids = [item["id"] for item in list_resp.json()["items"]]
            assert task_id not in listed_ids

            denied = await client.get(
                f"/api/collection-tasks/{task_id}/candidates",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert denied.status_code == 403

            candidates_resp = await client.get(
                f"/api/collection-tasks/{task_id}/candidates",
                headers=headers,
            )
            assert candidates_resp.status_code == 200, candidates_resp.text
            payload = candidates_resp.json()
            assert payload["total"] == 1
            item = payload["items"][0]
            assert item["source_post_url"] == post_url
            assert item["source_input_url"] == input_url

            export_resp = await client.get(
                f"/api/collection-tasks/{task_id}/candidates/export",
                headers=headers,
            )
            assert export_resp.status_code == 200, export_resp.text
            assert len(export_resp.content) > 100
            assert "attachment" in export_resp.headers.get("content-disposition", "").lower()
    finally:
        async with async_session_factory() as db:
            row = await db.get(CollectionTask, task_id)
            if row:
                await db.delete(row)
                await db.commit()
