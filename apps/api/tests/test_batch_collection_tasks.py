from __future__ import annotations

import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.api.routes.collection_tasks import run_collection_task
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionMode, CollectionTaskStatus
from app.schemas.collection_task import CollectionTaskCreate
from app.services.collection_task import CollectionTaskService


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _batch_payload(**overrides) -> CollectionTaskCreate:
    payload = {
        "name": f"batch-{uuid.uuid4().hex[:8]}",
        "collection_mode": CollectionMode.DISCOVERY,
        "platform": "youtube",
        "platforms": ["youtube"],
        "keywords": ["makeup bag", "cosmetic bag", "toiletry bag", "travel essentials"],
        "country": "US",
        "category": "beauty",
        "discovery_limit": 200,
        "min_followers_count": 5000,
        "min_engagement_rate": 1.2,
        "require_email": True,
        "require_contact": True,
        "outreach_enabled": True,
        "outreach_provider": "smtp",
        "outreach_dry_run": False,
        "outreach_templates": {"micro_subject": "Hi"},
        "batch_round_enabled": True,
        "batch_total_limit": 200,
        "batch_round_size": 50,
        "batch_round_count": 4,
    }
    payload.update(overrides)
    return CollectionTaskCreate(**payload)


@pytest.mark.anyio
async def test_batch_create_generates_parent_and_round_children():
    data = _batch_payload()
    created_ids: list[int] = []
    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(
            db,
            data,
            user_id=11,
            workspace_id=1,
            product_id=1,
        )
        created_ids.append(parent.id)
        rows = (
            await db.execute(
                select(CollectionTask)
                .where(CollectionTask.batch_group_id == parent.batch_group_id)
                .order_by(CollectionTask.batch_round_index.asc().nullsfirst(), CollectionTask.id.asc())
            )
        ).scalars().all()
        created_ids.extend(row.id for row in rows if row.id != parent.id)

        children = [row for row in rows if row.parent_task_id == parent.id]
        assert parent.parent_task_id is None
        assert parent.batch_round_index is None
        assert parent.batch_round_count == 4
        assert parent.discovery_limit == 200
        assert parent.status == CollectionTaskStatus.DRAFT.value
        assert len(children) == 4
        assert [child.name for child in children] == [f"{data.name} - 第{i}轮" for i in range(1, 5)]
        assert [child.discovery_limit for child in children] == [50, 50, 50, 50]
        assert [child.batch_round_index for child in children] == [1, 2, 3, 4]
        assert all(child.batch_round_count == 4 for child in children)
        assert all(child.user_id == 11 for child in children)
        assert all(child.workspace_id == 1 for child in children)
        assert all(child.product_id == 1 for child in children)
        assert all(child.platform == "youtube" and child.platforms == ["youtube"] for child in children)
        assert all(child.country == "US" and child.category == "beauty" for child in children)
        assert all(child.min_followers_count == 5000 for child in children)
        assert all(child.min_engagement_rate == 1.2 for child in children)
        assert all(child.require_email is True and child.require_contact is True for child in children)
        assert all(child.outreach_enabled is True and child.outreach_dry_run is False for child in children)
        assert all(child.outreach_templates == {"micro_subject": "Hi"} for child in children)
        assert children[0].keywords != children[1].keywords
        assert children[0].keywords[:2] == ["makeup bag", "makeupbag"]
    async with async_session_factory() as db:
        for task_id in created_ids:
            row = await db.get(CollectionTask, task_id)
            if row:
                await db.delete(row)
        await db.commit()


@pytest.mark.anyio
async def test_parent_batch_task_does_not_run_directly():
    data = _batch_payload(batch_round_count=2, batch_total_limit=20, batch_round_size=10)
    created_ids: list[int] = []
    async with async_session_factory() as db:
        parent = await CollectionTaskService.create_task(db, data, user_id=11, workspace_id=1, product_id=1)
        created_ids.append(parent.id)
        children = (
            await db.execute(select(CollectionTask).where(CollectionTask.parent_task_id == parent.id))
        ).scalars().all()
        created_ids.extend(child.id for child in children)
        with pytest.raises(HTTPException) as exc:
            await run_collection_task(parent.id, BackgroundTasks(), db, ctx=_tenant_ctx())
        assert exc.value.status_code == 400
        assert "parent_batch_task" in str(exc.value.detail)
    async with async_session_factory() as db:
        for task_id in created_ids:
            row = await db.get(CollectionTask, task_id)
            if row:
                await db.delete(row)
        await db.commit()


def _tenant_ctx():
    from app.deps.tenant import TenantContext

    return TenantContext(
        user_id=11,
        workspace_id=1,
        product_id=1,
        is_admin=False,
    )
