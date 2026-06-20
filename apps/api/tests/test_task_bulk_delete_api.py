"""采集任务 bulk-delete API 回归。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import async_session_factory
from app.main import app
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.services.task_effectiveness import classify_task_effectiveness


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


def test_partial_failed_large_funnel_is_high_value():
    row = _task(
        name="Amazon 商品发现",
        collection_mode=CollectionMode.COMPETITOR_PRODUCT.value,
        status=CollectionTaskStatus.PARTIAL_FAILED.value,
        inserted_count=21,
        result_count=21,
        discovered_count=574,
        deduped_count=481,
        profile_fetched_count=481,
        filtered_out_count=109,
        discovery_limit=50,
    )

    assert classify_task_effectiveness(row) == "high_value"


def test_single_link_import_is_low_value_not_high_value():
    row = _task(
        name="link-import-quality",
        status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
        inserted_count=1,
        result_count=1,
        discovered_count=1,
        deduped_count=1,
        profile_fetched_count=1,
        email_count=0,
    )

    assert classify_task_effectiveness(row) == "low_value_result"


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


@pytest.mark.anyio
async def test_collection_task_list_paginates_and_hides_archived_by_default():
    created_ids: list[int] = []
    async with async_session_factory() as db:
        for idx in range(3):
            row = _task(
                name=f"pagination-{idx}-{uuid.uuid4().hex[:6]}",
                created_at=datetime.now(UTC) - timedelta(minutes=idx),
            )
            db.add(row)
            await db.flush()
            created_ids.append(row.id)
        archived = _task(name=f"pagination-archived-{uuid.uuid4().hex[:6]}", is_archived=True)
        db.add(archived)
        await db.flush()
        created_ids.append(archived.id)
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/collection-tasks?page=1&page_size=2",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["page"] == 1
            assert payload["page_size"] == 2
            assert payload["total"] >= 3
            assert payload["total_pages"] >= 2
            assert len(payload["items"]) <= 2
            assert all(item["is_archived"] is False for item in payload["items"])

            archived_resp = await client.get(
                "/api/collection-tasks?page=1&page_size=20&task_view=archived",
                headers=headers,
            )
            assert archived_resp.status_code == 200, archived_resp.text
            archived_payload = archived_resp.json()
            assert any(item["id"] == archived.id for item in archived_payload["items"])
            assert all(item["is_archived"] is True for item in archived_payload["items"])
    finally:
        async with async_session_factory() as db:
            for task_id in created_ids:
                row = await db.get(CollectionTask, task_id)
                if row:
                    await db.delete(row)
            await db.commit()


@pytest.mark.anyio
async def test_collection_task_list_marks_test_history_and_duplicates():
    created_ids: list[int] = []
    duplicate_kwargs = {
        "name": f"seed-discovery-tiktok-{uuid.uuid4().hex[:6]}",
        "collection_mode": CollectionMode.DISCOVERY.value,
        "platform": "tiktok",
        "platforms": ["tiktok"],
        "keywords": ["dupe keyword"],
        "product_id": 1,
    }
    async with async_session_factory() as db:
        rows = [
            _task(**duplicate_kwargs),
            _task(**duplicate_kwargs, last_run_at=datetime.now(UTC) + timedelta(seconds=1)),
            _task(name=f"real-business-{uuid.uuid4().hex[:6]}", inserted_count=3, result_count=3),
        ]
        db.add_all(rows)
        await db.flush()
        created_ids = [row.id for row in rows]
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/collection-tasks?page=1&page_size=20&task_view=test_history",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            items = response.json()["items"]
            test_items = [item for item in items if item["id"] in created_ids[:2]]
            assert len(test_items) == 2
            assert all("test_task" in item["management_tags"] for item in test_items)
            assert all(item["is_possible_duplicate"] is True for item in test_items)
            assert not any(item["id"] == created_ids[2] for item in items)
    finally:
        async with async_session_factory() as db:
            for task_id in created_ids:
                row = await db.get(CollectionTask, task_id)
                if row:
                    await db.delete(row)
            await db.commit()


@pytest.mark.anyio
async def test_bulk_archive_test_history_is_limited_to_current_product():
    product_one_id: int
    product_two_id: int
    async with async_session_factory() as db:
        product_one = _task(name=f"验收-链接导入-{uuid.uuid4().hex[:6]}", product_id=1)
        product_two = _task(name=f"验收-链接导入-{uuid.uuid4().hex[:6]}", product_id=2)
        db.add_all([product_one, product_two])
        await db.flush()
        product_one_id = product_one.id
        product_two_id = product_two.id
        await db.commit()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/collection-tasks/bulk-manage",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
                json={"action": "archive_test_history"},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["matched_count"] >= 1
            assert product_one_id in payload["archived_ids"]
            assert product_two_id not in payload["archived_ids"]

        async with async_session_factory() as db:
            product_one = await db.get(CollectionTask, product_one_id)
            product_two = await db.get(CollectionTask, product_two_id)
            assert product_one is not None and product_one.is_archived is True
            assert product_two is not None and product_two.is_archived is False
    finally:
        async with async_session_factory() as db:
            for task_id in (product_one_id, product_two_id):
                row = await db.get(CollectionTask, task_id)
                if row:
                    await db.delete(row)
            await db.commit()


@pytest.mark.anyio
async def test_bulk_manage_skips_high_value_tasks_and_high_value_tab_lists_partial_success():
    high_id: int
    low_id: int
    async with async_session_factory() as db:
        high = _task(
            name=f"验收-Amazon 商品发现-{uuid.uuid4().hex[:6]}",
            product_id=1,
            collection_mode=CollectionMode.COMPETITOR_PRODUCT.value,
            status=CollectionTaskStatus.PARTIAL_FAILED.value,
            inserted_count=21,
            result_count=21,
            discovered_count=574,
            deduped_count=481,
            profile_fetched_count=481,
            filtered_out_count=109,
            discovery_limit=50,
        )
        low = _task(
            name=f"link-import-quality-{uuid.uuid4().hex[:6]}",
            product_id=1,
            status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
            inserted_count=1,
            result_count=1,
            discovered_count=1,
            deduped_count=1,
            profile_fetched_count=1,
        )
        db.add_all([high, low])
        await db.flush()
        high_id = high.id
        low_id = low.id
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            high_resp = await client.get(
                "/api/collection-tasks?page=1&page_size=20&task_view=high_value",
                headers=headers,
            )
            assert high_resp.status_code == 200, high_resp.text
            high_items = high_resp.json()["items"]
            assert any(item["id"] == high_id and item["effectiveness_category"] == "high_value" for item in high_items)

            low_resp = await client.get(
                "/api/collection-tasks?page=1&page_size=20&task_view=low_value_result",
                headers=headers,
            )
            assert low_resp.status_code == 200, low_resp.text
            low_items = low_resp.json()["items"]
            assert any(item["id"] == low_id and item["effectiveness_category"] == "low_value_result" for item in low_items)
            assert not any(item["id"] == high_id for item in low_items)

            archive_resp = await client.post(
                "/api/collection-tasks/bulk-manage",
                headers=headers,
                json={"action": "archive_test_history", "task_ids": [high_id, low_id]},
            )
            assert archive_resp.status_code == 200, archive_resp.text
            archive_payload = archive_resp.json()
            assert high_id not in archive_payload["archived_ids"]
            assert archive_payload["skipped_reasons"][str(high_id)] == "high_value_protected"

        async with async_session_factory() as db:
            high = await db.get(CollectionTask, high_id)
            assert high is not None and high.is_archived is False
    finally:
        async with async_session_factory() as db:
            for task_id in (high_id, low_id):
                row = await db.get(CollectionTask, task_id)
                if row:
                    await db.delete(row)
            await db.commit()


@pytest.mark.anyio
async def test_archive_duplicates_keeps_high_value_over_latest_low_value():
    high_id: int
    low_id: int
    duplicate_kwargs = {
        "name": f"duplicate-campaign-{uuid.uuid4().hex[:6]}",
        "collection_mode": CollectionMode.DISCOVERY.value,
        "platform": "instagram",
        "platforms": ["instagram"],
        "keywords": ["laundry bag"],
        "product_id": 1,
    }
    async with async_session_factory() as db:
        high = _task(
            **duplicate_kwargs,
            status=CollectionTaskStatus.PARTIAL_FAILED.value,
            inserted_count=21,
            result_count=21,
            discovered_count=574,
            profile_fetched_count=481,
            last_run_at=datetime.now(UTC) - timedelta(hours=1),
        )
        low = _task(
            **duplicate_kwargs,
            status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
            inserted_count=1,
            result_count=1,
            discovered_count=1,
            profile_fetched_count=1,
            last_run_at=datetime.now(UTC),
        )
        db.add_all([high, low])
        await db.flush()
        high_id = high.id
        low_id = low.id
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/collection-tasks/bulk-manage",
                headers=headers,
                json={"action": "archive_duplicates", "task_ids": [high_id, low_id]},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert high_id not in payload["archived_ids"]
            assert low_id in payload["archived_ids"]

        async with async_session_factory() as db:
            high = await db.get(CollectionTask, high_id)
            low = await db.get(CollectionTask, low_id)
            assert high is not None and high.is_archived is False
            assert low is not None and low.is_archived is True
    finally:
        async with async_session_factory() as db:
            for task_id in (high_id, low_id):
                row = await db.get(CollectionTask, task_id)
                if row:
                    await db.delete(row)
            await db.commit()
