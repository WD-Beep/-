from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.tenant import Product, Workspace
from app.services.email_log import EmailLogService


@pytest.mark.asyncio
async def test_bulk_delete_email_logs_is_product_scoped():
    async with async_session_factory() as db:
        own_log = EmailLog(
            product_id=1,
            user_id=1,
            recipients=["own-delete@example.com"],
            subject="Own delete",
            status=EmailLogStatus.FAILED.value,
            sent_at=datetime.now(UTC),
        )
        other_log = EmailLog(
            product_id=2,
            user_id=1,
            recipients=["other-delete@example.com"],
            subject="Other delete",
            status=EmailLogStatus.FAILED.value,
            sent_at=datetime.now(UTC),
        )
        db.add_all([own_log, other_log])
        await db.commit()
        await db.refresh(own_log)
        await db.refresh(other_log)

        deleted_ids, missing_ids = await EmailLogService.bulk_delete_logs(
            db,
            log_ids=[own_log.id, other_log.id, 99999999, own_log.id],
            product_id=1,
        )

        assert deleted_ids == [own_log.id]
        assert missing_ids == [other_log.id, 99999999]
        assert await db.scalar(select(EmailLog).where(EmailLog.id == own_log.id)) is None
        assert await db.scalar(select(EmailLog).where(EmailLog.id == other_log.id)) is not None

        await db.execute(delete(EmailLog).where(EmailLog.id == other_log.id))
        await db.commit()


@pytest.mark.asyncio
async def test_bulk_delete_email_logs_by_status_deletes_all_matching_product_rows():
    async with async_session_factory() as db:
        workspace = Workspace(name="Email log delete test", slug=f"email-log-delete-test-{datetime.now(UTC).timestamp()}")
        db.add(workspace)
        await db.flush()
        own_product = Product(workspace_id=workspace.id, name="Delete Test Product", slug="delete-test-product")
        other_product = Product(workspace_id=workspace.id, name="Other Delete Test Product", slug="other-delete-test-product")
        db.add_all([own_product, other_product])
        await db.flush()
        own_failed_1 = EmailLog(
            product_id=own_product.id,
            user_id=1,
            recipients=["failed-one@brandmail.co"],
            subject="Outreach failed one",
            status=EmailLogStatus.FAILED.value,
            sent_at=None,
        )
        own_failed_2 = EmailLog(
            product_id=own_product.id,
            user_id=1,
            recipients=["failed-two@brandmail.co"],
            subject="Outreach failed two",
            status=EmailLogStatus.FAILED.value,
            sent_at=None,
        )
        own_sent = EmailLog(
            product_id=own_product.id,
            user_id=1,
            recipients=["sent@brandmail.co"],
            subject="Outreach sent",
            status=EmailLogStatus.SENT.value,
            sent_at=datetime.now(UTC),
        )
        other_failed = EmailLog(
            product_id=other_product.id,
            user_id=1,
            recipients=["other-failed@brandmail.co"],
            subject="Other outreach failed",
            status=EmailLogStatus.FAILED.value,
            sent_at=None,
        )
        db.add_all([own_failed_1, own_failed_2, own_sent, other_failed])
        await db.commit()
        for row in [own_failed_1, own_failed_2, own_sent, other_failed]:
            await db.refresh(row)

        deleted_ids = await EmailLogService.bulk_delete_logs_by_status(
            db,
            status=EmailLogStatus.FAILED,
            product_id=own_product.id,
        )

        assert set(deleted_ids) == {own_failed_1.id, own_failed_2.id}
        assert await db.scalar(select(EmailLog).where(EmailLog.id == own_failed_1.id)) is None
        assert await db.scalar(select(EmailLog).where(EmailLog.id == own_failed_2.id)) is None
        assert await db.scalar(select(EmailLog).where(EmailLog.id == own_sent.id)) is not None
        assert await db.scalar(select(EmailLog).where(EmailLog.id == other_failed.id)) is not None

        await db.execute(delete(EmailLog).where(EmailLog.id.in_([own_sent.id, other_failed.id])))
        await db.execute(delete(Product).where(Product.id.in_([own_product.id, other_product.id])))
        await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
        await db.commit()
