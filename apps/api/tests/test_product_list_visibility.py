"""产品列表 API 可见性测试。"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.tenant import Product


def test_list_products_hides_test_entries_by_default():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        slug = f"test-product-b-{suffix}"
        headers = {"X-User-Id": "1", "X-Product-Id": "0"}

        try:
            async with async_session_factory() as db_session:
                row = Product(
                    workspace_id=1,
                    name=f"测试产品B-{suffix}",
                    slug=slug,
                    is_test=True,
                    is_hidden=True,
                    created_source="auto_test",
                )
                db_session.add(row)
                await db_session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                listed = await client.get("/api/tenant/products", headers=headers)
                assert listed.status_code == 200
                names = {item["name"] for item in listed.json()}
                assert f"测试产品B-{suffix}" not in names
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(delete(Product).where(Product.slug == slug))
                await db_session.commit()

    asyncio.run(_run())


def test_list_products_keeps_real_brand_seeds():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        headers = {"X-User-Id": "1", "X-Product-Id": "0"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get("/api/tenant/products", headers=headers)
            assert listed.status_code == 200
            slugs = {item["slug"] for item in listed.json()}
            assert "junlin-epedal24" in slugs
            assert "default" in slugs

    asyncio.run(_run())
