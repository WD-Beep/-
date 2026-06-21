from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.schemas.common import PaginatedResponse
from app.schemas.outreach_email import (
    OutreachSendQueueProcessResponse,
    OutreachSendQueueRead,
)
from app.services.outreach_send_queue_service import OutreachSendQueueService
from app.services.tenant_scope import ALL_PRODUCTS_ID

router = APIRouter(prefix="/outreach-send-queue", tags=["outreach-send-queue"])


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择具体产品/品牌后再操作发送队列",
        )
    return ctx.product_id


@router.get("", response_model=PaginatedResponse[OutreachSendQueueRead])
async def list_outreach_send_queue(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[OutreachSendQueueRead]:
    product_id = _require_product_scope(ctx)
    return await OutreachSendQueueService.list_queue(
        db,
        product_id=product_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.post("/process-today", response_model=OutreachSendQueueProcessResponse)
async def process_today_outreach_queue(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueProcessResponse:
    _require_product_scope(ctx)
    return await OutreachSendQueueService.process_today(db, ctx=ctx)


@router.delete("/{item_id}", response_model=OutreachSendQueueRead)
async def cancel_outreach_queue_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueRead:
    product_id = _require_product_scope(ctx)
    return await OutreachSendQueueService.cancel(db, product_id=product_id, item_id=item_id)
