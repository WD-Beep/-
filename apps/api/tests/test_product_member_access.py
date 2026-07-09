"""Brand assignment access control tests."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.tenant import Product, ProductMember, User


def _headers(user_id: int, product_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id), "X-Product-Id": str(product_id)}


async def _create_products_with_assignment() -> tuple[int, int, str]:
    suffix = f"z{uuid.uuid4().hex[:8]}"
    async with async_session_factory() as db:
        assigned = Product(
            workspace_id=1,
            name=f"Brand Access Assigned {suffix}",
            slug=f"brand-access-assigned-{suffix}",
            brand="Assigned",
            is_default=False,
        )
        unassigned = Product(
            workspace_id=1,
            name=f"Brand Access Unassigned {suffix}",
            slug=f"brand-access-unassigned-{suffix}",
            brand="Unassigned",
            is_default=False,
        )
        db.add_all([assigned, unassigned])
        await db.flush()
        db.add(ProductMember(user_id=2, product_id=assigned.id))
        await db.commit()
        return assigned.id, unassigned.id, suffix


async def _cleanup_products(suffix: str) -> None:
    async with async_session_factory() as db:
        product_ids = (
            await db.execute(
                select(Product.id).where(Product.slug.like(f"brand-access-%-{suffix}"))
            )
        ).scalars().all()
        if product_ids:
            await db.execute(delete(ProductMember).where(ProductMember.product_id.in_(product_ids)))
        await db.execute(
            delete(Product).where(Product.slug.like(f"brand-access-%-{suffix}"))
        )
        await db.commit()


def test_admin_can_see_all_products_and_sales_only_assigned_products():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        assigned_id, unassigned_id, suffix = await _create_products_with_assignment()
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                admin_resp = await client.get("/api/tenant/products", headers=_headers(1, 0))
                assert admin_resp.status_code == 200, admin_resp.text
                admin_ids = {item["id"] for item in admin_resp.json()}
                assert assigned_id in admin_ids
                assert unassigned_id in admin_ids

                sales_resp = await client.get("/api/tenant/products", headers=_headers(2, assigned_id))
                assert sales_resp.status_code == 200, sales_resp.text
                sales_ids = {item["id"] for item in sales_resp.json()}
                assert assigned_id in sales_ids
                assert unassigned_id not in sales_ids
        finally:
            await _cleanup_products(suffix)

    asyncio.run(_run())


def test_sales_never_sees_or_accesses_system_default_brand_even_if_stale_member_exists():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with async_session_factory() as db:
            sales_id = (await db.execute(select(User.id).where(User.username == "sales1"))).scalar_one()
            stale_member = ProductMember(user_id=sales_id, product_id=1, role="member")
            db.add(stale_member)
            await db.commit()
            stale_member_id = stale_member.id

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                products = await client.get("/api/tenant/products", headers=_headers(sales_id, 0))
                assert products.status_code == 200, products.text
                assert all(item["slug"] != "default" for item in products.json())

                influencers = await client.get("/api/influencers", headers=_headers(sales_id, 1))
                assert influencers.status_code == 403, influencers.text

                tasks = await client.get("/api/collection-tasks", headers=_headers(sales_id, 1))
                assert tasks.status_code == 403, tasks.text
        finally:
            async with async_session_factory() as db:
                await db.execute(delete(ProductMember).where(ProductMember.id == stale_member_id))
                await db.commit()

    asyncio.run(_run())


@pytest.mark.parametrize(
    "path",
    [
        "/api/collection-tasks",
        "/api/influencers",
        "/api/email-logs",
        "/api/email-inbound/replies",
    ],
)
def test_sales_cannot_access_unassigned_brand_data(path: str):
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        _assigned_id, unassigned_id, suffix = await _create_products_with_assignment()
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(path, headers=_headers(2, unassigned_id))
                assert response.status_code == 403, response.text
        finally:
            await _cleanup_products(suffix)

    asyncio.run(_run())


def test_sales_cannot_use_all_products_scope_but_admin_can_query_it():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        assigned_id, _unassigned_id, suffix = await _create_products_with_assignment()
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                sales_resp = await client.get("/api/email-logs", headers=_headers(2, 0))
                assert sales_resp.status_code == 403, sales_resp.text

                admin_resp = await client.get("/api/email-logs", headers=_headers(1, 0))
                assert admin_resp.status_code == 200, admin_resp.text
        finally:
            await _cleanup_products(suffix)

    asyncio.run(_run())


def test_write_operation_rejects_all_products_scope():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/collection-tasks",
                headers=_headers(1, 0),
                json={
                    "name": f"all-scope-write-{uuid.uuid4().hex[:8]}",
                    "platform": "youtube",
                    "platforms": ["youtube"],
                    "keywords": ["interior"],
                },
            )
            assert response.status_code == 400, response.text

    asyncio.run(_run())


def test_production_does_not_trust_client_user_id_header(monkeypatch):
    async def _run() -> None:
        from app.deps.tenant import get_user_context

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("AUTH_PROXY_SHARED_SECRET", raising=False)

        async with async_session_factory() as db:
            with pytest.raises(Exception) as exc:
                await get_user_context(db=db, x_user_id=1)
            assert exc.value.status_code in {401, 403}

    asyncio.run(_run())


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/influencers",
            {
                "platform": "instagram",
                "username": "all_scope_creator",
                "profile_url": "https://instagram.com/all_scope_creator",
            },
        ),
        (
            "/api/email/outreach/send-batch",
            {"influencer_ids": [1], "dry_run": True},
        ),
        (
            "/api/ai/analyze-influencer/1",
            {},
        ),
    ],
)
def test_write_side_effect_routes_reject_all_products_scope(path: str, payload: dict):
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(path, headers=_headers(1, 0), json=payload)
            assert response.status_code in {400, 403}, response.text

    asyncio.run(_run())
