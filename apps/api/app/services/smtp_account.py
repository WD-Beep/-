from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user_smtp_account import UserSmtpAccount


@dataclass(frozen=True)
class ResolvedSmtpAccount:
    source: str
    account_id: int | None
    sender_user_id: int | None
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_from_name: str | None
    use_tls: bool

    @property
    def configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.smtp_from)


@dataclass(frozen=True)
class ResolvedImapAccount:
    source: str
    account_id: int | None
    user_id: int | None
    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_use_ssl: bool
    inbound_email_address: str | None = None
    folder: str = "INBOX"

    @property
    def configured(self) -> bool:
        return bool(self.imap_host and self.imap_user and self.imap_password)


def system_smtp_account() -> ResolvedSmtpAccount:
    return ResolvedSmtpAccount(
        source="system",
        account_id=None,
        sender_user_id=None,
        smtp_host=settings.smtp_host,
        smtp_port=int(settings.smtp_port),
        smtp_user=settings.smtp_user,
        smtp_password=settings.smtp_password,
        smtp_from=settings.smtp_from,
        smtp_from_name=settings.smtp_from_name or None,
        use_tls=bool(settings.smtp_use_tls),
    )


def system_imap_account() -> ResolvedImapAccount:
    return ResolvedImapAccount(
        source="system",
        account_id=None,
        user_id=None,
        imap_host=settings.imap_host,
        imap_port=int(settings.imap_port),
        imap_user=settings.imap_user,
        imap_password=settings.imap_password,
        imap_use_ssl=bool(settings.imap_use_ssl),
        inbound_email_address=settings.inbound_email_address or settings.imap_user,
        folder=settings.imap_folder or "INBOX",
    )


async def resolve_smtp_account(db: AsyncSession | None, *, user_id: int | None) -> ResolvedSmtpAccount:
    if db is not None and user_id:
        account = await db.scalar(
            select(UserSmtpAccount).where(
                UserSmtpAccount.user_id == user_id,
                UserSmtpAccount.enabled.is_(True),
            )
        )
        if account:
            return ResolvedSmtpAccount(
                source="user",
                account_id=account.id,
                sender_user_id=account.user_id,
                smtp_host=account.smtp_host,
                smtp_port=int(account.smtp_port),
                smtp_user=account.smtp_user,
                smtp_password=account.smtp_password,
                smtp_from=account.smtp_from,
                smtp_from_name=account.smtp_from_name,
                use_tls=bool(account.use_tls),
            )
    return system_smtp_account()


async def resolve_imap_account(db: AsyncSession | None, *, user_id: int | None) -> ResolvedImapAccount:
    if db is not None and user_id:
        account = await db.scalar(
            select(UserSmtpAccount).where(
                UserSmtpAccount.user_id == user_id,
                UserSmtpAccount.enabled.is_(True),
            )
        )
        if account and account.imap_password:
            return ResolvedImapAccount(
                source="user",
                account_id=account.id,
                user_id=account.user_id,
                imap_host=account.imap_host or "imap.gmail.com",
                imap_port=int(account.imap_port or 993),
                imap_user=account.imap_user or account.smtp_user,
                imap_password=account.imap_password,
                imap_use_ssl=bool(account.imap_use_ssl),
                inbound_email_address=account.smtp_from or account.smtp_user,
                folder="INBOX",
            )
    return system_imap_account()


async def upsert_user_smtp_account(
    db: AsyncSession,
    *,
    user_id: int,
    smtp_user: str,
    smtp_password: str | None,
    imap_password: str | None = None,
    imap_same_as_smtp: bool = True,
    provider: str | None = "gmail",
    smtp_from_name: str | None = None,
    enabled: bool = True,
) -> UserSmtpAccount:
    account = await db.scalar(select(UserSmtpAccount).where(UserSmtpAccount.user_id == user_id))
    if account is None:
        if not smtp_password:
            raise ValueError("smtp_password_required")
        account = UserSmtpAccount(
            user_id=user_id,
            smtp_user=smtp_user.strip(),
            smtp_password=smtp_password.strip(),
            smtp_from=smtp_user.strip(),
            smtp_from_name=(smtp_from_name or "").strip() or None,
            enabled=enabled,
        )
        db.add(account)
    else:
        account.smtp_user = smtp_user.strip()
        account.smtp_from = smtp_user.strip()
        if smtp_password:
            account.smtp_password = smtp_password.strip()
        account.smtp_from_name = (smtp_from_name or "").strip() or None
        account.enabled = enabled
    account.provider = (provider or "gmail").strip().lower() or "gmail"
    account.smtp_host = "smtp.gmail.com"
    account.smtp_port = 587
    account.use_tls = True
    account.imap_host = "imap.gmail.com"
    account.imap_port = 993
    account.imap_user = account.smtp_user
    if imap_same_as_smtp and smtp_password:
        account.imap_password = smtp_password.strip()
    elif imap_password:
        account.imap_password = imap_password.strip()
    elif account.imap_password is None and account.smtp_password:
        account.imap_password = account.smtp_password
    account.imap_use_ssl = True
    account.last_error = None
    await db.commit()
    await db.refresh(account)
    return account


async def mark_smtp_account_test_result(
    db: AsyncSession,
    account: UserSmtpAccount,
    *,
    success: bool,
    error: str | None = None,
) -> UserSmtpAccount:
    account.last_tested_at = datetime.now(UTC)
    account.verified_at = account.last_tested_at if success else account.verified_at
    account.last_error = None if success else (error or "smtp_test_failed")[:2000]
    await db.commit()
    await db.refresh(account)
    return account
