"""租户产品/品牌创建测试。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.tenant import Product


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
