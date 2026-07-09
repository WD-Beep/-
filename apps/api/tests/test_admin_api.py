"""Admin API tests for the first administrator backend skeleton."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid

from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product, ProductMember, User, WorkspaceMember


def test_admin_can_read_summary_users_and_products():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-User-Id": "1", "X-Product-Id": "0"}

            summary = await client.get("/api/admin/summary", headers=headers)
            assert summary.status_code == 200, summary.text
            summary_payload = summary.json()
            assert "total_users" in summary_payload
            assert "total_products" in summary_payload
            assert "total_replies" in summary_payload

            users = await client.get("/api/admin/users", headers=headers)
            assert users.status_code == 200, users.text
            users_payload = users.json()
            assert isinstance(users_payload, list)
            assert any(item["is_admin"] for item in users_payload)
            assert {
                "id",
                "username",
                "role",
                "is_active",
                "product_count",
                "bound_products",
                "collection_task_count",
                "collection_success_count",
                "collection_failed_count",
                "influencer_count",
                "email_count",
                "email_failed_count",
                "reply_count",
                "pending_reply_count",
                "last_active_at",
                "created_at",
                "status",
            } <= set(users_payload[0])

            products = await client.get("/api/admin/products", headers=headers)
            assert products.status_code == 200, products.text
            assert isinstance(products.json(), list)

    asyncio.run(_run())


def test_admin_can_read_user_detail_and_related_admin_lists():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        username = f"admin-detail-sales-{suffix}"
        product_slug = f"admin-detail-brand-{suffix}"
        created_ids: dict[str, int] = {}

        try:
            async with async_session_factory() as db_session:
                user = User(username=username, display_name="Admin Detail Sales", is_admin=False)
                db_session.add(user)
                await db_session.flush()
                db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="member"))
                product = Product(
                    workspace_id=1,
                    name=f"Admin Detail Brand {suffix}",
                    slug=product_slug,
                    brand="Detail Brand",
                    description="Detail product",
                )
                db_session.add(product)
                await db_session.flush()
                db_session.add(ProductMember(user_id=user.id, product_id=product.id, role="owner"))
                task = CollectionTask(
                    user_id=user.id,
                    workspace_id=1,
                    product_id=product.id,
                    name=f"Admin Detail Task {suffix}",
                    platform="youtube",
                    platforms=["youtube"],
                    keywords=["detail"],
                    status="completed_with_results",
                    success_count=3,
                    failed_count=1,
                    inserted_count=2,
                )
                db_session.add(task)
                profile = GlobalInfluencerProfile(
                    platform="youtube",
                    username=f"detail_influencer_{suffix}",
                    normalized_username=f"detail_influencer_{suffix}",
                    profile_url=f"https://example.com/{suffix}",
                    normalized_profile_url=f"https://example.com/{suffix}",
                    display_name="Detail Influencer",
                )
                db_session.add(profile)
                await db_session.flush()
                influencer = ProductInfluencer(product_id=product.id, global_influencer_id=profile.id)
                db_session.add(influencer)
                email_log = EmailLog(
                    user_id=user.id,
                    product_id=product.id,
                    task_id=task.id,
                    product_influencer_id=influencer.id,
                    recipients=["creator@example.com"],
                    subject="Hello",
                    status="failed",
                    sent_at=datetime.now(timezone.utc),
                )
                db_session.add(email_log)
                await db_session.flush()
                reply = EmailReply(
                    user_id=user.id,
                    product_id=product.id,
                    email_log_id=email_log.id,
                    product_influencer_id=influencer.id,
                    from_address="creator@example.com",
                    to_address="brand@example.com",
                    subject="Re: Hello",
                    snippet="Interested",
                    processing_status="unprocessed",
                    intent_status="positive",
                    received_at=datetime.now(timezone.utc),
                )
                db_session.add(reply)
                await db_session.commit()
                created_ids.update(
                    user=user.id,
                    product=product.id,
                    task=task.id,
                    profile=profile.id,
                    influencer=influencer.id,
                    email=email_log.id,
                    reply=reply.id,
                )

            headers = {"X-User-Id": "1", "X-Product-Id": "0"}
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                detail = await client.get(f"/api/admin/users/{created_ids['user']}", headers=headers)
                assert detail.status_code == 200, detail.text
                detail_payload = detail.json()
                assert detail_payload["username"] == username
                assert detail_payload["collection_success_count"] == 1
                assert detail_payload["collection_failed_count"] == 0
                assert detail_payload["email_failed_count"] == 1
                assert detail_payload["pending_reply_count"] == 1
                assert detail_payload["bound_products"][0]["id"] == created_ids["product"]

                for path, expected_id in [
                    ("products", created_ids["product"]),
                    ("collection-tasks", created_ids["task"]),
                    ("influencers", created_ids["influencer"]),
                    ("emails", created_ids["email"]),
                    ("replies", created_ids["reply"]),
                ]:
                    response = await client.get(f"/api/admin/users/{created_ids['user']}/{path}", headers=headers)
                    assert response.status_code == 200, response.text
                    assert any(item["id"] == expected_id for item in response.json())

                product_detail = await client.get(f"/api/admin/products/{created_ids['product']}", headers=headers)
                assert product_detail.status_code == 200, product_detail.text
                product_payload = product_detail.json()
                assert product_payload["name"].startswith("Admin Detail Brand")
                assert product_payload["collection_task_count"] == 1
                assert product_payload["influencer_count"] == 1
                assert product_payload["email_count"] == 1
                assert product_payload["reply_count"] == 1

                for path in ["collection-tasks", "influencers", "emails"]:
                    response = await client.get(f"/api/admin/{path}", headers=headers)
                    assert response.status_code == 200, response.text
                    assert isinstance(response.json(), list)

                sales_headers = {"X-User-Id": str(created_ids["user"]), "X-Product-Id": "0"}
                blocked = await client.get(f"/api/admin/users/{created_ids['user']}", headers=sales_headers)
                assert blocked.status_code == 403
        finally:
            async with async_session_factory() as db_session:
                if "reply" in created_ids:
                    await db_session.execute(delete(EmailReply).where(EmailReply.id == created_ids["reply"]))
                if "email" in created_ids:
                    await db_session.execute(delete(EmailLog).where(EmailLog.id == created_ids["email"]))
                if "influencer" in created_ids:
                    await db_session.execute(delete(ProductInfluencer).where(ProductInfluencer.id == created_ids["influencer"]))
                if "profile" in created_ids:
                    await db_session.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == created_ids["profile"]))
                if "task" in created_ids:
                    await db_session.execute(delete(CollectionTask).where(CollectionTask.id == created_ids["task"]))
                if "product" in created_ids:
                    await db_session.execute(delete(ProductMember).where(ProductMember.product_id == created_ids["product"]))
                    await db_session.execute(delete(Product).where(Product.id == created_ids["product"]))
                if "user" in created_ids:
                    await db_session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == created_ids["user"]))
                    await db_session.execute(delete(User).where(User.id == created_ids["user"]))
                await db_session.commit()

    asyncio.run(_run())


def test_sales_cannot_read_admin_summary():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        username = f"admin-api-sales-{suffix}"
        try:
            async with async_session_factory() as db_session:
                user = User(username=username, display_name="Admin API Sales", is_admin=False)
                db_session.add(user)
                await db_session.flush()
                db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="member"))
                await db_session.commit()
                user_id = user.id

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/admin/summary",
                    headers={"X-User-Id": str(user_id), "X-Product-Id": "0"},
                )
                assert response.status_code == 403
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(delete(User).where(User.username == username))
                await db_session.commit()

    asyncio.run(_run())


def test_admin_products_include_brand_created_by_sales_member():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        username = f"admin-products-sales-{suffix}"
        payload = {
            "name": f"Admin Visible Brand {suffix}",
            "slug": f"admin-visible-brand-{suffix}",
            "description": "Created by sales and visible to admin",
            "is_default": False,
        }
        created_id: int | None = None

        try:
            async with async_session_factory() as db_session:
                user = User(username=username, display_name="Admin Products Sales", is_admin=False)
                db_session.add(user)
                await db_session.flush()
                db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="member"))
                await db_session.commit()
                user_id = user.id

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create = await client.post(
                    "/api/tenant/products",
                    headers={"X-User-Id": str(user_id), "X-Product-Id": "0"},
                    json=payload,
                )
                assert create.status_code == 201, create.text
                created = create.json()
                created_id = created["id"]

                products = await client.get(
                    "/api/admin/products",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                )
                assert products.status_code == 200, products.text
                row = next(item for item in products.json() if item["id"] == created_id)
                assert row["name"] == payload["name"]
                assert username in row["owner_names"]
                assert row["members"][0]["user_id"] == user_id
        finally:
            async with async_session_factory() as db_session:
                if created_id is not None:
                    await db_session.execute(delete(ProductMember).where(ProductMember.product_id == created_id))
                    await db_session.execute(delete(Product).where(Product.id == created_id))
                await db_session.execute(delete(User).where(User.username == username))
                await db_session.commit()

    asyncio.run(_run())
