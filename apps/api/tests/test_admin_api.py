"""Admin API tests for the first administrator backend skeleton."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_send_queue import OutreachSendQueueItem
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


def test_admin_can_create_single_character_sales_username():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with async_session_factory() as db_session:
            existing = set((await db_session.execute(select(User.username))).scalars().all())
        username = next(candidate for candidate in "123456789abcdefghijklmnopqrstuvwxyz" if candidate not in existing)
        created_id: int | None = None
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/admin/users",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                    json={
                        "username": username,
                        "password": "1",
                        "display_name": "Single Character Sales",
                        "email": None,
                        "role": "sales",
                        "is_active": True,
                        "product_ids": [],
                    },
                )
                assert response.status_code == 201, response.text
                payload = response.json()
                created_id = payload["id"]
                assert payload["username"] == username
                assert payload["role"] == "sales"
        finally:
            async with async_session_factory() as db_session:
                if created_id is not None:
                    await db_session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == created_id))
                    await db_session.execute(delete(ProductMember).where(ProductMember.user_id == created_id))
                    await db_session.execute(delete(User).where(User.id == created_id))
                else:
                    await db_session.execute(delete(User).where(User.username == username))
                await db_session.commit()

    asyncio.run(_run())


def test_admin_salesperson_contact_accepts_local_account_phone_wechat_and_text():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        username = f"contact-sales-{suffix}"
        created_id: int | None = None
        contacts = [
            "sales1@local",
            "13800138000",
            "微信号 wx_sales_01",
            "内部业务员账号",
        ]
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post(
                    "/api/admin/users",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                    json={
                        "username": username,
                        "password": "1",
                        "display_name": "Contact Sales",
                        "email": contacts[0],
                        "role": "sales",
                        "is_active": True,
                        "product_ids": [],
                    },
                )
                assert created.status_code == 201, created.text
                created_id = created.json()["id"]
                assert created.json()["email"] == contacts[0]

                for contact in contacts[1:]:
                    updated = await client.patch(
                        f"/api/admin/users/{created_id}",
                        headers={"X-User-Id": "1", "X-Product-Id": "0"},
                        json={"email": contact},
                    )
                    assert updated.status_code == 200, updated.text
                    assert updated.json()["email"] == contact

                non_admin_update = await client.patch(
                    f"/api/admin/users/{created_id}",
                    headers={"X-User-Id": str(created_id), "X-Product-Id": "0"},
                    json={"email": "unauthorized contact"},
                )
                assert non_admin_update.status_code == 403

                blank_username = await client.patch(
                    f"/api/admin/users/{created_id}",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                    json={"username": ""},
                )
                assert blank_username.status_code == 422
        finally:
            async with async_session_factory() as db_session:
                if created_id is not None:
                    await db_session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == created_id))
                    await db_session.execute(delete(ProductMember).where(ProductMember.user_id == created_id))
                    await db_session.execute(delete(User).where(User.id == created_id))
                else:
                    await db_session.execute(delete(User).where(User.username == username))
                await db_session.commit()

    asyncio.run(_run())


def test_admin_can_delete_salesperson_and_preserve_historical_business_data():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        username = f"delete-sales-{suffix}"
        created_ids: dict[str, int] = {}
        delete_succeeded = False
        try:
            async with async_session_factory() as db_session:
                user = User(username=username, display_name="Delete Sales", is_admin=False)
                db_session.add(user)
                await db_session.flush()
                db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="member"))
                product = Product(
                    workspace_id=1,
                    name=f"Delete Safe Brand {suffix}",
                    slug=f"delete-safe-brand-{suffix}",
                )
                db_session.add(product)
                await db_session.flush()
                db_session.add(ProductMember(user_id=user.id, product_id=product.id, role="owner"))
                task = CollectionTask(
                    user_id=user.id,
                    workspace_id=1,
                    product_id=product.id,
                    name=f"Delete Safe Task {suffix}",
                    platform="youtube",
                    platforms=["youtube"],
                    keywords=["delete-safe"],
                    status="completed_with_results",
                )
                db_session.add(task)
                profile = GlobalInfluencerProfile(
                    platform="youtube",
                    username=f"delete_safe_{suffix}",
                    normalized_username=f"delete_safe_{suffix}",
                    profile_url=f"https://example.com/delete-safe/{suffix}",
                    normalized_profile_url=f"https://example.com/delete-safe/{suffix}",
                )
                db_session.add(profile)
                await db_session.flush()
                influencer = ProductInfluencer(product_id=product.id, global_influencer_id=profile.id)
                db_session.add(influencer)
                await db_session.flush()
                email_log = EmailLog(
                    user_id=user.id,
                    product_id=product.id,
                    task_id=task.id,
                    product_influencer_id=influencer.id,
                    recipients=["creator@example.com"],
                    subject="Delete safe email",
                    status="sent",
                    sent_at=datetime.now(timezone.utc),
                )
                db_session.add(email_log)
                await db_session.flush()
                campaign = OutreachEmailCampaign(
                    product_id=product.id,
                    user_id=user.id,
                    name=f"Delete Safe Campaign {suffix}",
                    status="running",
                    auto_send_enabled=True,
                    auto_send_time="10:00",
                )
                db_session.add(campaign)
                await db_session.flush()
                reply = EmailReply(
                    user_id=user.id,
                    product_id=product.id,
                    email_log_id=email_log.id,
                    product_influencer_id=influencer.id,
                    campaign_id=campaign.id,
                    from_address="creator@example.com",
                    to_address="brand@example.com",
                    subject="Re: Delete safe email",
                    received_at=datetime.now(timezone.utc),
                )
                queue = OutreachSendQueueItem(
                    product_id=product.id,
                    user_id=user.id,
                    product_influencer_id=influencer.id,
                    recipient="creator@example.com",
                    subject="Queued email",
                    body="Queued body",
                    status="queued",
                    campaign_id=campaign.id,
                )
                db_session.add_all([reply, queue])
                await db_session.commit()
                created_ids.update(
                    user=user.id,
                    product=product.id,
                    task=task.id,
                    profile=profile.id,
                    influencer=influencer.id,
                    email=email_log.id,
                    campaign=campaign.id,
                    reply=reply.id,
                    queue=queue.id,
                )

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                blocked = await client.delete(
                    f"/api/admin/users/{created_ids['user']}",
                    headers={"X-User-Id": str(created_ids["user"]), "X-Product-Id": "0"},
                )
                assert blocked.status_code == 403

                deleted = await client.delete(
                    f"/api/admin/users/{created_ids['user']}",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                )
                assert deleted.status_code == 200, deleted.text
                payload = deleted.json()
                assert payload["success"] is True
                assert payload["deleted_user_id"] == created_ids["user"]
                assert payload["released_products"] == 1
                assert payload["released_tasks"] == 1
                assert payload["cancelled_campaigns"] == 1
                assert payload["cancelled_queue_items"] == 1
                assert payload["preserved_history_records"] is True
                delete_succeeded = True

            async with async_session_factory() as db_session:
                assert await db_session.get(User, created_ids["user"]) is None
                assert await db_session.scalar(
                    select(ProductMember.id).where(ProductMember.user_id == created_ids["user"])
                ) is None
                assert await db_session.scalar(
                    select(WorkspaceMember.id).where(WorkspaceMember.user_id == created_ids["user"])
                ) is None
                assert (await db_session.get(CollectionTask, created_ids["task"])).user_id is None
                assert (await db_session.get(EmailLog, created_ids["email"])).user_id is None
                assert (await db_session.get(EmailReply, created_ids["reply"])).user_id is None
                preserved_campaign = await db_session.get(OutreachEmailCampaign, created_ids["campaign"])
                assert preserved_campaign is not None
                assert preserved_campaign.user_id is None
                assert preserved_campaign.status == "cancelled"
                assert preserved_campaign.auto_send_enabled is False
                preserved_queue = await db_session.get(OutreachSendQueueItem, created_ids["queue"])
                assert preserved_queue is not None
                assert preserved_queue.user_id is None
                assert preserved_queue.status == "cancelled"
                assert await db_session.get(ProductInfluencer, created_ids["influencer"]) is not None
                audit = (
                    await db_session.execute(
                        text(
                            "SELECT action, actor_user_id, target_user_id, details "
                            "FROM admin_audit_logs WHERE target_user_id = :target_user_id "
                            "ORDER BY id DESC LIMIT 1"
                        ),
                        {"target_user_id": created_ids["user"]},
                    )
                ).mappings().first()
                assert audit is not None
                assert audit["action"] == "admin_user_deleted"
                assert audit["actor_user_id"] == 1
                assert audit["details"]["released_products"] == 1
        finally:
            async with async_session_factory() as db_session:
                if delete_succeeded:
                    await db_session.execute(
                        text("DELETE FROM admin_audit_logs WHERE target_user_id = :target_user_id"),
                        {"target_user_id": created_ids.get("user")},
                    )
                if "reply" in created_ids:
                    await db_session.execute(delete(EmailReply).where(EmailReply.id == created_ids["reply"]))
                if "queue" in created_ids:
                    await db_session.execute(delete(OutreachSendQueueItem).where(OutreachSendQueueItem.id == created_ids["queue"]))
                if "campaign" in created_ids:
                    await db_session.execute(delete(OutreachEmailCampaign).where(OutreachEmailCampaign.id == created_ids["campaign"]))
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


def test_admin_user_delete_rolls_back_when_commit_fails():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        username = f"delete-rollback-{suffix}"
        user_id: int | None = None
        product_id: int | None = None
        original_commit = AsyncSession.commit
        try:
            async with async_session_factory() as db_session:
                user = User(username=username, display_name="Rollback Sales", is_admin=False)
                db_session.add(user)
                await db_session.flush()
                db_session.add(WorkspaceMember(workspace_id=1, user_id=user.id, role="member"))
                product = Product(
                    workspace_id=1,
                    name=f"Rollback Brand {suffix}",
                    slug=f"rollback-brand-{suffix}",
                )
                db_session.add(product)
                await db_session.flush()
                db_session.add(ProductMember(user_id=user.id, product_id=product.id, role="owner"))
                await db_session.commit()
                user_id = user.id
                product_id = product.id

            async def failing_commit(_session: AsyncSession) -> None:
                raise RuntimeError("forced commit failure")

            AsyncSession.commit = failing_commit
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.delete(
                    f"/api/admin/users/{user_id}",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                )
                assert response.status_code == 500
                assert "删除业务员失败" in response.text
        finally:
            AsyncSession.commit = original_commit
            async with async_session_factory() as db_session:
                if user_id is not None:
                    assert await db_session.get(User, user_id) is not None
                    assert await db_session.scalar(
                        select(ProductMember.id).where(ProductMember.user_id == user_id)
                    ) is not None
                    await db_session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user_id))
                    await db_session.execute(delete(ProductMember).where(ProductMember.user_id == user_id))
                    await db_session.execute(delete(User).where(User.id == user_id))
                if product_id is not None:
                    await db_session.execute(delete(Product).where(Product.id == product_id))
                await db_session.commit()

    asyncio.run(_run())


def test_admin_cannot_delete_current_logged_in_admin():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                "/api/admin/users/1",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert response.status_code == 409
            assert "不能删除当前登录的管理员账号" in response.text

    asyncio.run(_run())


def test_admin_can_update_username_and_login_with_new_username():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        old_username = f"rename-sales-old-{suffix}"
        new_username = f"rename-sales-new-{suffix}"
        password = "rename-pass-1"
        created_id: int | None = None
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post(
                    "/api/admin/users",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                    json={
                        "username": old_username,
                        "password": password,
                        "display_name": "Rename Sales",
                        "email": None,
                        "role": "sales",
                        "is_active": True,
                        "product_ids": [],
                    },
                )
                assert created.status_code == 201, created.text
                created_id = created.json()["id"]

                updated = await client.patch(
                    f"/api/admin/users/{created_id}",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                    json={"username": new_username},
                )
                assert updated.status_code == 200, updated.text
                assert updated.json()["username"] == new_username

                detail = await client.get(
                    f"/api/admin/users/{created_id}",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                )
                assert detail.status_code == 200, detail.text
                assert detail.json()["username"] == new_username

                new_login = await client.post(
                    "/api/auth/login",
                    json={"username": new_username, "password": password},
                )
                assert new_login.status_code == 200, new_login.text

                old_login = await client.post(
                    "/api/auth/login",
                    json={"username": old_username, "password": password},
                )
                assert old_login.status_code == 401, old_login.text
        finally:
            async with async_session_factory() as db_session:
                if created_id is not None:
                    await db_session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == created_id))
                    await db_session.execute(delete(ProductMember).where(ProductMember.user_id == created_id))
                    await db_session.execute(delete(User).where(User.id == created_id))
                await db_session.execute(delete(User).where(User.username.in_([old_username, new_username])))
                await db_session.commit()

    asyncio.run(_run())


def test_admin_username_update_rejects_duplicate_but_allows_unchanged_value():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        first_username = f"dup-sales-a-{suffix}"
        second_username = f"dup-sales-b-{suffix}"
        first_id: int | None = None
        second_id: int | None = None
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                for username in [first_username, second_username]:
                    created = await client.post(
                        "/api/admin/users",
                        headers={"X-User-Id": "1", "X-Product-Id": "0"},
                        json={
                            "username": username,
                            "password": "1",
                            "display_name": username,
                            "email": None,
                            "role": "sales",
                            "is_active": True,
                            "product_ids": [],
                        },
                    )
                    assert created.status_code == 201, created.text
                    if username == first_username:
                        first_id = created.json()["id"]
                    else:
                        second_id = created.json()["id"]

                unchanged = await client.patch(
                    f"/api/admin/users/{first_id}",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                    json={"username": first_username},
                )
                assert unchanged.status_code == 200, unchanged.text

                duplicate = await client.patch(
                    f"/api/admin/users/{first_id}",
                    headers={"X-User-Id": "1", "X-Product-Id": "0"},
                    json={"username": second_username},
                )
                assert duplicate.status_code == 409, duplicate.text
        finally:
            async with async_session_factory() as db_session:
                for user_id in [first_id, second_id]:
                    if user_id is not None:
                        await db_session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user_id))
                        await db_session.execute(delete(ProductMember).where(ProductMember.user_id == user_id))
                        await db_session.execute(delete(User).where(User.id == user_id))
                await db_session.execute(delete(User).where(User.username.in_([first_username, second_username])))
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
