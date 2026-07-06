from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.schemas.manual_outreach_email import ManualOutreachEmailRequest, ManualOutreachEmailResponse
from app.services.manual_outreach_email_service import ManualOutreachEmailService

router = APIRouter(prefix="/manual-outreach-email", tags=["manual-outreach-email"])


@router.post("/send", response_model=ManualOutreachEmailResponse)
async def send_manual_outreach_email(
    payload: ManualOutreachEmailRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> ManualOutreachEmailResponse:
    return await ManualOutreachEmailService.submit(db, ctx=ctx, payload=payload)
