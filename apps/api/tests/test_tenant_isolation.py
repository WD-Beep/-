"""多租户隔离与全局去重测试。"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product
from app.services import collection_filters as cf
from app.services.collection_task import CollectionTaskService
from app.schemas.collection_task import CollectionTaskFilter
from app.services.influencer_persistence import (
    InfluencerPersistenceService,
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
    identity_key_for_item,
)


def _item(**kwargs) -> CollectedInfluencer:
    suffix = uuid.uuid4().hex[:8]
    base = dict(
        platform="youtube",
        username=f"creator_shared_{suffix}",
        profile_url=f"https://www.youtube.com/@creator_shared_{suffix}",
        platform_unique_id=f"UCshared{suffix}123456789012",
        followers_count=50000,
        engagement_rate=1.5,
        bio="amazon finds creator",
        display_name="Shared Creator",
    )
    base.update(kwargs)
    return CollectedInfluencer(**base)


def _product_b() -> Product:
    suffix = uuid.uuid4().hex[:8]
    return Product(
        workspace_id=1,
        name=f"测试产品B-{suffix}",
        slug=f"test-product-b-{suffix}",
        is_default=False,
    )


def test_same_global_profile_two_products_can_insert():
    async def _run() -> None:
        from datetime import UTC, datetime

        async with async_session_factory() as db_session:
            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()

            run_at = datetime.now(UTC)
            item = _item()
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db_session.add(global_profile)
            await db_session.flush()

            for product_id in (1, product_b.id):
                record = create_product_influencer_from_collected(
                    product_id=product_id,
                    global_profile=global_profile,
                    data=item,
                    task=None,
                    run_at=run_at,
                )
                db_session.add(record)
            await db_session.flush()

            rows = (
                await db_session.execute(
                    select(ProductInfluencer).where(
                        ProductInfluencer.global_influencer_id == global_profile.id
                    )
                )
            ).scalars().all()
            assert len(rows) == 2
            assert len({row.product_id for row in rows}) == 2
            await db_session.rollback()

    asyncio.run(_run())


def test_global_profile_dedup_by_identity_key():
    async def _run() -> None:
        from datetime import UTC, datetime

        async with async_session_factory() as db_session:
            run_at = datetime.now(UTC)
            item = _item()
            db_session.add(create_global_profile_from_collected(item, run_at=run_at))
            await db_session.flush()

            found = await InfluencerPersistenceService.find_global_profiles_batch(db_session, [item])
            assert len(found) == 1
            await db_session.rollback()

    asyncio.run(_run())


def test_product_duplicate_within_same_product():
    async def _run() -> None:
        from datetime import UTC, datetime

        async with async_session_factory() as db_session:
            run_at = datetime.now(UTC)
            item = _item()
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db_session.add(global_profile)
            await db_session.flush()
            db_session.add(
                create_product_influencer_from_collected(
                    product_id=1,
                    global_profile=global_profile,
                    data=item,
                    task=None,
                    run_at=run_at,
                )
            )
            await db_session.flush()

            product_map = await InfluencerPersistenceService.find_product_influencers_batch(
                db_session, 1, [item]
            )
            assert identity_key_for_item(item) in product_map
            await db_session.rollback()

    asyncio.run(_run())


def test_collection_tasks_filtered_by_product():
    async def _run() -> None:
        suffix = uuid.uuid4().hex[:8]
        async with async_session_factory() as db_session:
            product_b = Product(
                workspace_id=1,
                name=f"任务隔离B-{suffix}",
                slug=f"task-isolation-b-{suffix}",
                is_default=False,
            )
            db_session.add(product_b)
            await db_session.flush()

            task_a = CollectionTask(
                name=f"A-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["a"],
                product_id=1,
            )
            task_b = CollectionTask(
                name=f"B-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["b"],
                product_id=product_b.id,
            )
            db_session.add_all([task_a, task_b])
            await db_session.flush()

            page = await CollectionTaskService.list_tasks(
                db_session, CollectionTaskFilter(product_id=1), page=1, page_size=200
            )
            assert all(item.product_id == 1 for item in page.items)
            assert any(item.name == f"A-{suffix}" for item in page.items)
            assert all(item.name != f"B-{suffix}" for item in page.items)
            await db_session.rollback()

    asyncio.run(_run())


def test_collection_tasks_default_to_current_owner_scope():
    async def _run() -> None:
        suffix = uuid.uuid4().hex[:8]
        async with async_session_factory() as db_session:
            mine = CollectionTask(
                name=f"mine-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["mine"],
                product_id=1,
                user_id=1,
            )
            teammate = CollectionTask(
                name=f"teammate-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["teammate"],
                product_id=1,
                user_id=2,
            )
            db_session.add_all([mine, teammate])
            await db_session.flush()

            page = await CollectionTaskService.list_tasks(
                db_session,
                CollectionTaskFilter(product_id=1, owner_user_id=1, owner_scope="mine"),
                page=1,
                page_size=200,
            )

            names = {item.name for item in page.items}
            assert f"mine-{suffix}" in names
            assert f"teammate-{suffix}" not in names
            await db_session.rollback()

    asyncio.run(_run())


def test_collection_tasks_admin_all_scope_can_see_team_tasks():
    async def _run() -> None:
        suffix = uuid.uuid4().hex[:8]
        async with async_session_factory() as db_session:
            mine = CollectionTask(
                name=f"admin-mine-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["mine"],
                product_id=1,
                user_id=1,
            )
            teammate = CollectionTask(
                name=f"admin-teammate-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["teammate"],
                product_id=1,
                user_id=2,
            )
            db_session.add_all([mine, teammate])
            await db_session.flush()

            page = await CollectionTaskService.list_tasks(
                db_session,
                CollectionTaskFilter(product_id=1, owner_user_id=1, owner_scope="all", owner_is_admin=True),
                page=1,
                page_size=200,
            )

            names = {item.name for item in page.items}
            assert f"admin-mine-{suffix}" in names
            assert f"admin-teammate-{suffix}" in names
            await db_session.rollback()

    asyncio.run(_run())


def test_collection_tasks_all_products_scope_shows_total_tasks():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        async with async_session_factory() as db_session:
            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()
            product_b_id = product_b.id

            db_session.add_all(
                [
                    CollectionTask(
                        name=f"total-a-{suffix}",
                        platform="youtube",
                        platforms=["youtube"],
                        keywords=["a"],
                        product_id=1,
                        user_id=1,
                    ),
                    CollectionTask(
                        name=f"total-b-{suffix}",
                        platform="youtube",
                        platforms=["youtube"],
                        keywords=["b"],
                        product_id=product_b_id,
                        user_id=2,
                    ),
                ]
            )
            await db_session.commit()

        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"/api/collection-tasks?search=total-&page_size=200",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                )
                assert response.status_code == 200, response.text
                names = {item["name"] for item in response.json()["items"]}
                assert f"total-a-{suffix}" in names
                assert f"total-b-{suffix}" in names
        finally:
            from sqlalchemy import delete

            async with async_session_factory() as db_session:
                await db_session.execute(delete(CollectionTask).where(CollectionTask.name.like(f"total-%-{suffix}")))
                await db_session.execute(delete(Product).where(Product.slug == f"test-product-b-{suffix}"))
                await db_session.commit()

    asyncio.run(_run())


def test_hard_filter_independent_per_product_recipe():
    task = SimpleNamespace(
        collection_mode="discovery",
        discovery_limit=5,
        min_followers_count=10000,
        min_engagement_rate=0.5,
        filter_exclude_keywords=[],
        filter_include_keywords=[],
        platform="youtube",
    )
    assert cf.evaluate_post_hydration_hard_filter(_item(followers_count=15000), task).passed is True
    assert cf.evaluate_post_hydration_hard_filter(_item(followers_count=8000), task).passed is False


def test_same_global_profile_product_business_fields_isolated():
    async def _run() -> None:
        from datetime import UTC, datetime

        async with async_session_factory() as db_session:
            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()

            run_at = datetime.now(UTC)
            item = _item()
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db_session.add(global_profile)
            await db_session.flush()

            record_a = create_product_influencer_from_collected(
                product_id=1,
                global_profile=global_profile,
                data=item,
                task=None,
                run_at=run_at,
            )
            record_a.product_fit = 88.0
            record_a.score = 90.0
            record_b = create_product_influencer_from_collected(
                product_id=product_b.id,
                global_profile=global_profile,
                data=item,
                task=None,
                run_at=run_at,
            )
            record_b.product_fit = 42.0
            record_b.score = 45.0
            db_session.add_all([record_a, record_b])
            await db_session.flush()

            assert record_a.product_fit != record_b.product_fit
            assert record_a.score != record_b.score
            await db_session.rollback()

    asyncio.run(_run())


def test_global_profile_dedup_by_normalized_username():
    async def _run() -> None:
        from datetime import UTC, datetime

        async with async_session_factory() as db_session:
            suffix = uuid.uuid4().hex[:8]
            run_at = datetime.now(UTC)
            item = _item(
                username=f"same_user_{suffix}",
                profile_url=f"https://www.youtube.com/@same_user_{suffix}",
                platform_unique_id=None,
            )
            db_session.add(create_global_profile_from_collected(item, run_at=run_at))
            await db_session.flush()

            lookup = _item(
                username=f"Same_User_{suffix}",
                profile_url=f"https://youtube.com/@same_user_{suffix}/videos",
                platform_unique_id=None,
            )
            found = await InfluencerPersistenceService.find_global_profiles_batch(db_session, [lookup])
            assert len(found) == 1
            await db_session.rollback()

    asyncio.run(_run())


def test_task_influencer_service_scoped_to_task_product_candidates():
    async def _run() -> None:
        from datetime import UTC, datetime

        from app.models.collection_task_candidate import CollectionTaskCandidate
        from app.models.enums import CandidateStatus
        from app.services.task_candidate import TaskCandidateService
        from app.services.task_influencer import TaskInfluencerService

        suffix = uuid.uuid4().hex[:8]
        async with async_session_factory() as db_session:
            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()

            run_at = datetime.now(UTC)
            item = _item(username=f"task_scope_{suffix}")
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db_session.add(global_profile)
            await db_session.flush()

            product_record = create_product_influencer_from_collected(
                product_id=1,
                global_profile=global_profile,
                data=item,
                task=None,
                run_at=run_at,
            )
            db_session.add(product_record)
            await db_session.flush()

            task = CollectionTask(
                name=f"scope-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["scope"],
                product_id=1,
                user_id=1,
            )
            other_task = CollectionTask(
                name=f"other-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["other"],
                product_id=product_b.id,
                user_id=1,
            )
            db_session.add_all([task, other_task])
            await db_session.flush()

            await TaskCandidateService.bulk_insert(
                db_session,
                task.id,
                [
                    TaskCandidateService.row_from_inserted(
                        meta=None,
                        username=item.username,
                        profile_url=item.profile_url,
                        platform="youtube",
                        collection_mode="discovery",
                        product_influencer_id=product_record.id,
                        global_influencer_id=global_profile.id,
                        product_id=1,
                        user_id=1,
                        followers_count=item.followers_count,
                        engagement_rate=item.engagement_rate,
                        profile_fetched_at=run_at,
                    )
                ],
                run_at=run_at,
                product_id=1,
                user_id=1,
            )
            await db_session.flush()

            scoped = await TaskInfluencerService.get_influencers_for_task(db_session, task)
            assert len(scoped) == 1
            assert scoped[0].id == product_record.id

            other_scoped = await TaskInfluencerService.get_influencers_for_task(db_session, other_task)
            assert other_scoped == []
            await db_session.rollback()

    asyncio.run(_run())


def test_candidate_export_joins_product_influencer():
    async def _run() -> None:
        from datetime import UTC, datetime

        from app.models.enums import CandidateStatus
        from app.services.task_candidate import TaskCandidateService

        suffix = uuid.uuid4().hex[:8]
        async with async_session_factory() as db_session:
            run_at = datetime.now(UTC)
            item = _item(username=f"export_join_{suffix}")
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db_session.add(global_profile)
            await db_session.flush()
            product_record = create_product_influencer_from_collected(
                product_id=1,
                global_profile=global_profile,
                data=item,
                task=None,
                run_at=run_at,
            )
            product_record.ai_summary = "product scoped ai"
            db_session.add(product_record)
            await db_session.flush()

            task = CollectionTask(
                name=f"export-{suffix}",
                platform="youtube",
                platforms=["youtube"],
                keywords=["export"],
                product_id=1,
                user_id=1,
            )
            db_session.add(task)
            await db_session.flush()

            await TaskCandidateService.bulk_insert(
                db_session,
                task.id,
                [
                    TaskCandidateService.row_from_inserted(
                        meta=None,
                        username=item.username,
                        profile_url=item.profile_url,
                        platform="youtube",
                        collection_mode="discovery",
                        product_influencer_id=product_record.id,
                        global_influencer_id=global_profile.id,
                        product_id=1,
                        user_id=1,
                        followers_count=item.followers_count,
                        engagement_rate=item.engagement_rate,
                        profile_fetched_at=run_at,
                    )
                ],
                run_at=run_at,
                product_id=1,
                user_id=1,
            )
            await db_session.flush()

            rows = await TaskCandidateService.list_for_export(
                db_session,
                task.id,
                product_id=1,
                status=CandidateStatus.INSERTED.value,
            )
            assert len(rows) == 1
            candidate, influencer = rows[0]
            assert candidate.product_influencer_id == product_record.id
            assert influencer is not None
            assert influencer.ai_summary == "product scoped ai"
            await db_session.rollback()

    asyncio.run(_run())


def test_get_tenant_context_requires_both_headers():
    async def _run() -> None:
        from app.deps.tenant import get_tenant_context

        async with async_session_factory() as db_session:
            with pytest.raises(Exception) as missing_user:
                await get_tenant_context(db=db_session, x_user_id=None, x_product_id=1)
            assert missing_user.value.status_code == 422

            with pytest.raises(Exception) as missing_product:
                await get_tenant_context(db=db_session, x_user_id=1, x_product_id=None)
            assert missing_product.value.status_code == 422

    asyncio.run(_run())


def test_get_user_context_rejects_unknown_user():
    async def _run() -> None:
        from app.deps.tenant import get_user_context

        async with async_session_factory() as db_session:
            with pytest.raises(Exception) as exc:
                await get_user_context(db=db_session, x_user_id=999_999)
            assert exc.value.status_code == 401

    asyncio.run(_run())


def test_ensure_task_access_rejects_task_without_product():
    from app.deps.tenant import TenantContext
    from app.services.task_access import ensure_task_access

    task = CollectionTask(
        name="orphan",
        platform="youtube",
        platforms=["youtube"],
        keywords=["x"],
        product_id=None,
    )
    ctx = TenantContext(user_id=1, product_id=1, workspace_id=1, is_admin=True)

    with pytest.raises(Exception) as exc:
        ensure_task_access(task, ctx)
    assert exc.value.status_code == 403


def test_ensure_task_access_rejects_all_products_context():
    from app.deps.tenant import TenantContext
    from app.services.task_access import ensure_task_access
    from app.services.tenant_scope import ALL_PRODUCTS_ID

    task = CollectionTask(
        name="bound",
        platform="instagram",
        platforms=["instagram"],
        keywords=["B00VOEZYHI"],
        product_id=1,
    )
    ctx = TenantContext(
        user_id=1,
        product_id=ALL_PRODUCTS_ID,
        workspace_id=1,
        is_admin=True,
    )

    with pytest.raises(Exception) as exc:
        ensure_task_access(task, ctx)
    assert exc.value.status_code == 403


def test_ensure_task_access_rejects_cross_product():
    from app.deps.tenant import TenantContext
    from app.services.task_access import ensure_task_access

    task = CollectionTask(
        name="product-a-task",
        platform="instagram",
        platforms=["instagram"],
        keywords=["B00VOEZYHI"],
        product_id=1,
    )
    ctx = TenantContext(user_id=1, product_id=99, workspace_id=1, is_admin=False)

    with pytest.raises(Exception) as exc:
        ensure_task_access(task, ctx)
    assert exc.value.status_code == 403


def test_ensure_task_access_rejects_cross_owner_for_non_admin():
    from app.deps.tenant import TenantContext
    from app.services.task_access import ensure_task_access

    task = CollectionTask(
        name="teammate-task",
        platform="instagram",
        platforms=["instagram"],
        keywords=["B00VOEZYHI"],
        product_id=1,
        user_id=2,
    )
    ctx = TenantContext(user_id=1, product_id=1, workspace_id=1, is_admin=False)

    with pytest.raises(Exception) as exc:
        ensure_task_access(task, ctx)
    assert exc.value.status_code == 403


def test_ensure_task_access_allows_cross_owner_for_admin():
    from app.deps.tenant import TenantContext
    from app.services.task_access import ensure_task_access

    task = CollectionTask(
        name="teammate-task",
        platform="instagram",
        platforms=["instagram"],
        keywords=["B00VOEZYHI"],
        product_id=1,
        user_id=2,
    )
    ctx = TenantContext(user_id=1, product_id=1, workspace_id=1, is_admin=True)

    assert ensure_task_access(task, ctx) is task


def test_protected_api_rejects_missing_tenant_headers():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for path in (
                "/api/dashboard/summary",
                "/api/email-logs",
                "/api/link-import/batches",
                "/api/influencers",
                "/api/collection-tasks",
                "/api/message-templates",
            ):
                response = await client.get(path)
                assert response.status_code == 422, path

            ok = await client.get(
                "/api/dashboard/summary",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
            )
            assert ok.status_code == 200

    asyncio.run(_run())


def test_email_logs_filtered_by_product():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy import delete

        from app.main import app
        from app.models.email_log import EmailLog
        from app.models.enums import EmailLogStatus

        suffix = uuid.uuid4().hex[:8]
        product_b_id: int
        async with async_session_factory() as db_session:
            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()
            product_b_id = product_b.id

            db_session.add_all(
                [
                    EmailLog(
                        task_id=None,
                        product_id=1,
                        user_id=1,
                        recipients=["a@example.com"],
                        subject=f"product-a-{suffix}",
                        status=EmailLogStatus.SENT.value,
                    ),
                    EmailLog(
                        task_id=None,
                        product_id=product_b_id,
                        user_id=1,
                        recipients=["b@example.com"],
                        subject=f"product-b-{suffix}",
                        status=EmailLogStatus.SENT.value,
                    ),
                ]
            )
            await db_session.commit()

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp_a = await client.get(
                    "/api/email-logs",
                    headers={"X-User-Id": "1", "X-Product-Id": "1"},
                )
                assert resp_a.status_code == 200
                subjects_a = {item["subject"] for item in resp_a.json()["items"]}
                assert f"product-a-{suffix}" in subjects_a
                assert f"product-b-{suffix}" not in subjects_a

                resp_b = await client.get(
                    "/api/email-logs",
                    headers={"X-User-Id": "1", "X-Product-Id": str(product_b_id)},
                )
                assert resp_b.status_code == 200
                subjects_b = {item["subject"] for item in resp_b.json()["items"]}
                assert f"product-b-{suffix}" in subjects_b
                assert f"product-a-{suffix}" not in subjects_b
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(delete(EmailLog).where(EmailLog.subject.like(f"%-{suffix}")))
                await db_session.commit()

    asyncio.run(_run())


def test_email_logs_all_products_scope_shows_total_logs():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy import delete

        from app.main import app
        from app.models.email_log import EmailLog
        from app.models.enums import EmailLogStatus

        suffix = uuid.uuid4().hex[:8]
        product_b_id: int
        async with async_session_factory() as db_session:
            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()
            product_b_id = product_b.id

            db_session.add_all(
                [
                    EmailLog(
                        task_id=None,
                        product_id=1,
                        user_id=1,
                        recipients=["a@example.com"],
                        subject=f"total-product-a-{suffix}",
                        status=EmailLogStatus.SENT.value,
                    ),
                    EmailLog(
                        task_id=None,
                        product_id=product_b_id,
                        user_id=2,
                        recipients=["b@example.com"],
                        subject=f"total-product-b-{suffix}",
                        status=EmailLogStatus.SENT.value,
                    ),
                ]
            )
            await db_session.commit()

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/email-logs?page_size=200",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                )
                assert response.status_code == 200, response.text
                subjects = {item["subject"] for item in response.json()["items"]}
                assert f"total-product-a-{suffix}" in subjects
                assert f"total-product-b-{suffix}" in subjects
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(delete(EmailLog).where(EmailLog.subject.like(f"total-product-%-{suffix}")))
                await db_session.execute(delete(Product).where(Product.slug == f"test-product-b-{suffix}"))
                await db_session.commit()

    asyncio.run(_run())


def test_link_import_batches_filtered_by_product():
    async def _run() -> None:
        from sqlalchemy import delete, text

        from app.services.link_import import LinkImportService

        suffix = uuid.uuid4().hex[:8]
        product_b_id: int
        async with async_session_factory() as db_session:
            column_exists = (
                await db_session.execute(
                    text(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'link_import_batches'
                          AND column_name = 'product_id'
                        LIMIT 1
                        """
                    )
                )
            ).scalar_one_or_none()
            if not column_exists:
                pytest.skip("link_import_batches.product_id 尚未迁移")

            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()
            product_b_id = product_b.id

            await db_session.execute(
                text(
                    """
                    INSERT INTO link_import_batches (
                        user_id, workspace_id, product_id, name, raw_urls,
                        valid_urls, invalid_urls, status, total_count
                    ) VALUES
                    (1, 1, 1, :name_a, 'https://instagram.com/a', '[]'::jsonb, '[]'::jsonb, 'pending', 1),
                    (1, 1, :product_b_id, :name_b, 'https://instagram.com/b', '[]'::jsonb, '[]'::jsonb, 'pending', 1)
                    """
                ),
                {
                    "name_a": f"A-{suffix}",
                    "name_b": f"B-{suffix}",
                    "product_b_id": product_b_id,
                },
            )
            await db_session.commit()

        try:
            async with async_session_factory() as db_session:
                page_a = await LinkImportService.list_batches(db_session, 1, 100, product_id=1)
                names_a = {item.name for item in page_a.items}
                assert f"A-{suffix}" in names_a
                assert f"B-{suffix}" not in names_a

                page_b = await LinkImportService.list_batches(
                    db_session, 1, 100, product_id=product_b_id
                )
                names_b = {item.name for item in page_b.items}
                assert f"B-{suffix}" in names_b
                assert f"A-{suffix}" not in names_b
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(
                    text("DELETE FROM link_import_batches WHERE name LIKE :pattern"),
                    {"pattern": f"%-{suffix}"},
                )
                await db_session.commit()

    asyncio.run(_run())


def test_link_import_batch_access_rejects_all_products_context():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/api/link-import/batches",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
                json={
                    "name": f"tenant-batch-{suffix}",
                    "raw_urls": "https://www.pinterest.com/example_user/",
                },
            )
            assert create_resp.status_code == 201, create_resp.text
            batch_id = create_resp.json()["id"]

            denied_get = await client.get(
                f"/api/link-import/batches/{batch_id}",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert denied_get.status_code == 403

            denied_run = await client.post(
                f"/api/link-import/batches/{batch_id}/run",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert denied_run.status_code == 403

            denied_delete = await client.delete(
                f"/api/link-import/batches/{batch_id}",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert denied_delete.status_code == 403

    asyncio.run(_run())


def test_migration_dedup_sql_accepts_duplicate_platform_unique_id_urls():
    async def _run() -> None:
        from sqlalchemy import text

        async with async_session_factory() as db_session:
            result = await db_session.execute(
                text(
                    """
                    WITH source AS (
                        SELECT *
                        FROM (
                            VALUES
                                (1, 'youtube', 'UCmigrate001', 'https://www.youtube.com/channel/UCmigrate001'),
                                (2, 'youtube', 'UCmigrate001', 'https://www.youtube.com/@migrate001')
                        ) AS t(id, platform, platform_unique_id, profile_url)
                    ),
                    ranked AS (
                        SELECT
                            id,
                            platform,
                            platform_unique_id,
                            LOWER(RTRIM(profile_url, '/')) AS normalized_profile_url,
                            ROW_NUMBER() OVER (
                                PARTITION BY platform,
                                    COALESCE(
                                        NULLIF(TRIM(platform_unique_id), ''),
                                        LOWER(RTRIM(profile_url, '/'))
                                    )
                                ORDER BY id ASC
                            ) AS rn
                        FROM source
                    )
                    SELECT COUNT(*) FILTER (WHERE rn = 1) AS canonical_count,
                           COUNT(*) AS total_count
                    FROM ranked
                    """
                )
            )
            row = result.one()
            assert row.total_count == 2
            assert row.canonical_count == 1

    asyncio.run(_run())

