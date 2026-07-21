# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：smtp accounts
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.models.user_smtp_account import UserSmtpAccount
from app.schemas.email import EmailTestResponse
from app.schemas.smtp_account import UserSmtpAccountRead, UserSmtpAccountStatus, UserSmtpAccountUpsertRequest
from app.services.email import EmailService, format_smtp_send_error
from app.services.outreach_recipient import normalize_email_address
from app.services.smtp_account import mark_smtp_account_test_result, resolve_smtp_account, upsert_user_smtp_account

router = APIRouter(prefix="/smtp-accounts", tags=["smtp-accounts"])


def _read(account: UserSmtpAccount) -> UserSmtpAccountRead:
    return UserSmtpAccountRead.model_validate(account).model_copy(
        update={
            "has_password": bool(account.smtp_password),
            "has_imap_password": bool(account.imap_password),
        }
    )


@router.get("/me", response_model=UserSmtpAccountStatus)
async def get_my_smtp_account(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> UserSmtpAccountStatus:
    account = await db.scalar(select(UserSmtpAccount).where(UserSmtpAccount.user_id == ctx.user_id))
    resolved = await resolve_smtp_account(db, user_id=ctx.user_id)
    return UserSmtpAccountStatus(
        configured=resolved.configured,
        source=resolved.source,
        sender_email=resolved.smtp_from or None,
        account=_read(account) if account else None,
    )


@router.put("/me", response_model=UserSmtpAccountRead)
async def save_my_smtp_account(
    payload: UserSmtpAccountUpsertRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> UserSmtpAccountRead:
    try:
        account = await upsert_user_smtp_account(
            db,
            user_id=ctx.user_id,
            smtp_user=str(payload.smtp_user),
            smtp_password=payload.smtp_password,
            imap_password=payload.imap_password,
            imap_same_as_smtp=payload.imap_same_as_smtp,
            provider=payload.provider,
            smtp_from_name=payload.smtp_from_name,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _read(account)


@router.post("/me/test", response_model=EmailTestResponse)
async def test_my_smtp_account(
    recipient: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailTestResponse:
    account = await db.scalar(select(UserSmtpAccount).where(UserSmtpAccount.user_id == ctx.user_id))
    if not account or not account.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="personal_smtp_not_configured")
    to_address = normalize_email_address(recipient or account.smtp_user)
    if not to_address:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_test_recipient")

    resolved = await resolve_smtp_account(db, user_id=ctx.user_id)
    message = MIMEMultipart()
    message["From"] = resolved.smtp_from
    message["To"] = to_address
    message["Subject"] = "Influencer Intel Gmail SMTP test"
    message.attach(MIMEText("This is a Gmail SMTP configuration test email. It is not influencer outreach.", "plain", "utf-8"))
    try:
        await EmailService._send_message(message, [to_address], smtp_account=resolved)
    except Exception as exc:
        error = format_smtp_send_error(exc)
        await mark_smtp_account_test_result(db, account, success=False, error=error)
        return EmailTestResponse(success=False, message=error, recipient=to_address)

    await mark_smtp_account_test_result(db, account, success=True)
    return EmailTestResponse(success=True, message=f"测试邮件已发送至 {to_address}", recipient=to_address)


@router.get("/users/{user_id}", response_model=UserSmtpAccountStatus)
async def get_user_smtp_account_for_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> UserSmtpAccountStatus:
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
    account = await db.scalar(select(UserSmtpAccount).where(UserSmtpAccount.user_id == user_id))
    resolved = await resolve_smtp_account(db, user_id=user_id)
    return UserSmtpAccountStatus(
        configured=resolved.configured,
        source=resolved.source,
        sender_email=resolved.smtp_from or None,
        account=_read(account) if account else None,
    )
