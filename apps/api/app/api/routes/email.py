from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG
from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context, require_write_product_id
from app.schemas.email import EmailTestRequest, EmailTestResponse, SmtpStatus
from app.schemas.outreach_email import (
    OutreachBatchPreviewRequest,
    OutreachBatchPreviewResponse,
    OutreachBatchSendRequest,
    OutreachBatchSendResponse,
)
from app.services.email import EmailNotConfiguredError, EmailService
from app.services.outreach_email_service import OutreachEmailService

router = APIRouter(prefix="/email", tags=["email"])


@router.get("/status", response_model=SmtpStatus)
async def get_smtp_status() -> SmtpStatus:
    return EmailService.get_smtp_status()


@router.post("/test", response_model=EmailTestResponse)
async def send_test_email(payload: EmailTestRequest) -> EmailTestResponse:
    try:
        return await EmailService.send_test_email(recipient=str(payload.recipient))
    except EmailNotConfiguredError:
        return EmailTestResponse(success=False, message=SMTP_NOT_CONFIGURED_MSG)


@router.post("/outreach/preview-batch", response_model=OutreachBatchPreviewResponse)
async def preview_outreach_batch(
    payload: OutreachBatchPreviewRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachBatchPreviewResponse:
    return await OutreachEmailService.preview_batch(
        db,
        product_id=ctx.product_id,
        payload=payload,
    )


@router.post("/outreach/send-batch", response_model=OutreachBatchSendResponse)
async def send_outreach_batch(
    payload: OutreachBatchSendRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachBatchSendResponse:
    product_id = require_write_product_id(ctx)
    return await OutreachEmailService.send_batch(
        db,
        product_id=product_id,
        user_id=ctx.user_id,
        payload=payload,
    )
