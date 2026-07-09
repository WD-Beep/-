"""租户产品/品牌创建测试。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.tenant import Product, ProductMember, User, WorkspaceMember


def test_create_product_requires_user_header():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/tenant/products",
                json={"name": "测试产品", "slug": "test-product"},
            )
            assert response.status_code == 422

    asyncio.run(_run())


def test_create_product_writes_to_user_workspace():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        headers = {"X-User-Id": "1", "X-Product-Id": "0"}
        payload = {
            "name": f"新品测试-{suffix}",
            "slug": f"new-product-{suffix}",
            "description": "自动化测试",
            "is_default": False,
        }

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create = await client.post("/api/tenant/products", headers=headers, json=payload)
                assert create.status_code == 201
                created = create.json()
                assert created["name"] == payload["name"]
                assert created["workspace_id"] == 1
                assert created["slug"] == payload["slug"]

                listed = await client.get("/api/tenant/products", headers=headers)
                assert listed.status_code == 200
                names = {item["name"] for item in listed.json()}
                assert payload["name"] not in names
                assert create.json()["is_test"] is True
                assert create.json()["is_hidden"] is True
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(
                    delete(Product).where(Product.slug == payload["slug"])
                )
                await db_session.commit()

    asyncio.run(_run())


def test_create_product_auto_slug_and_unique():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        slug = f"dup-slug-{suffix}"
        headers = {"X-User-Id": "1", "X-Product-Id": "1"}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                first = await client.post(
                    "/api/tenant/products",
                    headers=headers,
                    json={"name": f"产品A-{suffix}", "slug": slug},
                )
                assert first.status_code == 201

                second = await client.post(
                    "/api/tenant/products",
                    headers=headers,
                    json={"name": f"产品B-{suffix}", "slug": slug},
                )
                assert second.status_code == 201
                assert second.json()["slug"] != slug
                assert second.json()["slug"].startswith(slug)
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(delete(Product).where(Product.slug.like(f"%{suffix}%")))
                await db_session.commit()

    asyncio.run(_run())


def test_sales_create_product_assigns_product_to_self():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        username = f"sales-empty-{suffix}"
        payload = {
            "name": f"Sales Brand {suffix}",
            "slug": f"sales-brand-{suffix}",
            "description": "Created by sales",
            "is_default": False,
        }

        try:
            async with async_session_factory() as db_session:
                user = User(username=username, display_name="Empty Sales", is_admin=False)
                db_session.add(user)
                await db_session.flush()
                db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="member"))
                await db_session.commit()
                user_id = user.id

            headers = {"X-User-Id": str(user_id), "X-Product-Id": "0"}

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                before = await client.get("/api/tenant/products", headers=headers)
                assert before.status_code == 200
                assert before.json() == []

                create = await client.post("/api/tenant/products", headers=headers, json=payload)
                assert create.status_code == 201
                created = create.json()
                assert created["slug"] == payload["slug"]

                listed = await client.get("/api/tenant/products", headers=headers)
                assert listed.status_code == 200
                assert payload["slug"] in {item["slug"] for item in listed.json()}

            async with async_session_factory() as db_session:
                rows = await db_session.execute(
                    delete(ProductMember).where(ProductMember.product_id == created["id"])
                )
                assert rows.rowcount == 1
                await db_session.commit()
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(delete(Product).where(Product.slug == payload["slug"]))
                await db_session.execute(delete(User).where(User.username == username))
                await db_session.commit()

    asyncio.run(_run())


def test_sales_can_delete_own_product():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        username = f"sales-delete-{suffix}"

        async with async_session_factory() as db_session:
            user = User(username=username, display_name="Delete Sales", is_admin=False)
            db_session.add(user)
            await db_session.flush()
            db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="member"))
            product = Product(
                workspace_id=1,
                name=f"Delete Brand {suffix}",
                slug=f"delete-brand-{suffix}",
                brand="Delete",
                is_default=False,
            )
            db_session.add(product)
            await db_session.flush()
            db_session.add(ProductMember(user_id=user.id, product_id=product.id, role="owner"))
            await db_session.commit()
            user_id = user.id
            product_id = product.id

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.delete(
                    f"/api/tenant/products/{product_id}",
                    headers={"X-User-Id": str(user_id), "X-Product-Id": str(product_id)},
                )
                assert response.status_code == 204, response.text

                listed = await client.get(
                    "/api/tenant/products",
                    headers={"X-User-Id": str(user_id), "X-Product-Id": "0"},
                )
                assert listed.status_code == 200
                assert product_id not in {item["id"] for item in listed.json()}

            async with async_session_factory() as db_session:
                assert await db_session.get(Product, product_id) is None
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(delete(ProductMember).where(ProductMember.product_id == product_id))
                await db_session.execute(delete(Product).where(Product.id == product_id))
                await db_session.execute(delete(User).where(User.username == username))
                await db_session.commit()

    asyncio.run(_run())
