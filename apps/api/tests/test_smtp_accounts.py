from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.tenant import User
from app.models.user_smtp_account import UserSmtpAccount
from app.schemas.smtp_account import UserSmtpAccountRead
from app.services.smtp_account import resolve_smtp_account, upsert_user_smtp_account


def test_user_smtp_account_resolves_before_system_and_hides_password():
    async def _run() -> None:
        suffix = uuid.uuid4().hex[:10]
        async with async_session_factory() as db:
            user = User(username=f"smtp-user-{suffix}", email=f"smtp-user-{suffix}@local")
            db.add(user)
            await db.flush()
            account = await upsert_user_smtp_account(
                db,
                user_id=user.id,
                smtp_user=f"sales-{suffix}@gmail.com",
                smtp_password="abcdefghijklmnop",
                imap_password="replyabcdefghijklmnop",
                smtp_from_name="Sales Sender",
            )
            user_id = user.id
            account_id = account.id

        try:
            async with async_session_factory() as db:
                resolved = await resolve_smtp_account(db, user_id=user_id)
                assert resolved.source == "user"
                assert resolved.account_id == account_id
                assert resolved.smtp_host == "smtp.gmail.com"
                assert resolved.smtp_port == 587
                assert resolved.smtp_from == f"sales-{suffix}@gmail.com"

                account = await db.scalar(select(UserSmtpAccount).where(UserSmtpAccount.id == account_id))
                assert account.imap_host == "imap.gmail.com"
                assert account.imap_port == 993
                assert account.imap_user == f"sales-{suffix}@gmail.com"
                assert account.imap_password == "replyabcdefghijklmnop"
                payload = UserSmtpAccountRead.model_validate(account).model_dump()
                assert "smtp_password" not in payload
                assert "imap_password" not in payload
                assert payload["has_imap_password"] is True
        finally:
            async with async_session_factory() as db:
                await db.execute(delete(UserSmtpAccount).where(UserSmtpAccount.id == account_id))
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()

    asyncio.run(_run())
