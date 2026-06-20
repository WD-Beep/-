"""候选池导出 API 回归。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import async_session_factory
from app.main import app
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus


@pytest.mark.anyio
async def test_candidate_export_empty_returns_404_not_500():
    task_id: int

    async with async_session_factory() as db:
        task = CollectionTask(
            name="export-empty",
            product_id=1,
            collection_mode=CollectionMode.LINK_IMPORT.value,
            platform="ltk",
            platforms=["ltk"],
            input_urls=["https://www.shopltk.com/explore/none"],
            status=CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
            export_qualified_only=True,
            inserted_count=0,
        )
        db.add(task)
        await db.flush()
        task_id = task.id
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/collection-tasks/{task_id}/candidates/export",
                headers=headers,
                params={"high_value": "true"},
            )
            assert resp.status_code == 404, resp.text
            assert "没有符合筛选条件" in resp.json()["detail"]
    finally:
        async with async_session_factory() as db:
            row = await db.get(CollectionTask, task_id)
            if row:
                await db.delete(row)
                await db.commit()


@pytest.mark.anyio
async def test_candidate_export_filtered_row_with_export_qualified_only_task():
    ltk_url = "https://www.shopltk.com/explore/apieceofmyhaven?utm_source=ig"
    task_id: int

    async with async_session_factory() as db:
        task = CollectionTask(
            name="export-filtered-ltk",
            product_id=1,
            collection_mode=CollectionMode.LINK_IMPORT.value,
            platform="ltk",
            platforms=["ltk"],
            input_urls=[ltk_url],
            status=CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
            export_qualified_only=True,
            insert_qualified_only=True,
            strict_quality_filter=True,
            require_email=True,
            inserted_count=0,
            last_run_at=datetime.now(UTC),
        )
        db.add(task)
        await db.flush()
        task_id = task.id
        db.add(
            CollectionTaskCandidate(
                task_id=task.id,
                product_id=1,
                username="apieceofmyhaven",
                profile_url="https://www.instagram.com/apieceofmyhaven/",
                platform="instagram",
                status=CandidateStatus.FILTERED_OUT.value,
                failure_reason="missing_email",
                failure_detail="未发现邮箱",
                source_input_url=ltk_url,
                source_meta={
                    "source_input_url": ltk_url,
                    "link_seed_enrichment": {
                        "link_seed_platform": "ltk",
                        "primary_platform": "instagram",
                        "enrichment_attempted": True,
                    },
                },
                followers_count=2_444_689,
                engagement_rate=1.03,
                is_high_value=False,
            )
        )
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/collection-tasks/{task_id}/candidates/export",
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            assert len(resp.content) > 500
            assert "attachment" in resp.headers.get("content-disposition", "").lower()
    finally:
        async with async_session_factory() as db:
            row = await db.get(CollectionTask, task_id)
            if row:
                await db.delete(row)
                await db.commit()
