"""话术库租户隔离与 CRUD 测试。"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.message_template import MessageTemplate
from app.models.tenant import Product


def _product_b() -> Product:
    suffix = uuid.uuid4().hex[:8]
    return Product(
        workspace_id=1,
        name=f"话术测试产品B-{suffix}",
        slug=f"msg-tpl-b-{suffix}",
        is_default=False,
    )


def test_message_templates_reject_missing_headers():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ("/api/message-templates",):
                response = await client.get(path)
                assert response.status_code == 422

    asyncio.run(_run())


def test_message_templates_require_specific_product():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/message-templates",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert response.status_code == 400

    asyncio.run(_run())


def test_message_templates_filtered_by_product():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        product_b_id: int
        async with async_session_factory() as db_session:
            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()
            product_b_id = product_b.id
            db_session.add_all(
                [
                    MessageTemplate(
                        user_id=1,
                        workspace_id=1,
                        product_id=1,
                        title=f"产品A话术-{suffix}",
                        scenario="first_contact",
                        content="Hello A {name}",
                        tags=["intro"],
                    ),
                    MessageTemplate(
                        user_id=1,
                        workspace_id=1,
                        product_id=product_b_id,
                        title=f"产品B话术-{suffix}",
                        scenario="first_contact",
                        content="Hello B {name}",
                        tags=["intro"],
                    ),
                ]
            )
            await db_session.commit()

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers_a = {"X-User-Id": "1", "X-Product-Id": "1"}
                list_a = await client.get("/api/message-templates", headers=headers_a)
                assert list_a.status_code == 200
                titles_a = {item["title"] for item in list_a.json()["items"]}
                assert f"产品A话术-{suffix}" in titles_a
                assert f"产品B话术-{suffix}" not in titles_a

                create = await client.post(
                    "/api/message-templates",
                    headers=headers_a,
                    json={
                        "title": f"新建话术-{suffix}",
                        "scenario": "quote",
                        "content": "Quote for {product}",
                        "platform": "instagram",
                        "language": "en",
                        "tags": ["quote"],
                    },
                )
                assert create.status_code == 201
                created = create.json()
                assert created["product_id"] == 1
                assert created["user_id"] == 1

                cross = await client.get(
                    f"/api/message-templates/{created['id']}",
                    headers={"X-User-Id": "1", "X-Product-Id": str(product_b_id)},
                )
                assert cross.status_code == 404

                use_resp = await client.post(
                    f"/api/message-templates/{created['id']}/use",
                    headers=headers_a,
                )
                assert use_resp.status_code == 200
                assert use_resp.json()["usage_count"] == 1
                assert use_resp.json()["last_used_at"] is not None

                delete_resp = await client.delete(
                    f"/api/message-templates/{created['id']}",
                    headers=headers_a,
                )
                assert delete_resp.status_code == 204
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(
                    delete(MessageTemplate).where(MessageTemplate.title.like(f"%{suffix}%"))
                )
                await db_session.execute(delete(Product).where(Product.id == product_b_id))
                await db_session.commit()

    asyncio.run(_run())
