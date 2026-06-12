from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.services.tenant_scope import scoped_product_id
from app.models.enums import EmailLogStatus
from app.schemas.common import PaginatedResponse
from app.schemas.email_log import EmailLogFilter, EmailLogRead
from app.services.email_log import EmailLogService

router = APIRouter(prefix="/email-logs", tags=["email-logs"])


@router.get("", response_model=PaginatedResponse[EmailLogRead])
async def list_email_logs(
    task_id: int | None = None,
    status: EmailLogStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[EmailLogRead]:
    filters = EmailLogFilter(product_id=scoped_product_id(ctx.product_id), task_id=task_id, status=status)
    return await EmailLogService.list_logs(db, filters, page, page_size)
