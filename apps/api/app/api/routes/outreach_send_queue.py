from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.schemas.common import PaginatedResponse
from app.schemas.outreach_email import (
    OutreachQueueBulkActionRequest,
    OutreachQueueRescheduleRequest,
    OutreachScheduleRequest,
    OutreachScheduleResponse,
    OutreachSendQueueClearFailedResponse,
    OutreachSendQueueProcessResponse,
    OutreachSendQueueRead,
)
from app.services.outreach_send_scheduler import (
    cancel_queue_items,
    get_queue_item,
    list_scheduled_queue,
    pause_queue_items,
    reschedule_queue_item,
    resume_queue_items,
    schedule_outreach_emails,
    send_queue_item,
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
    campaign_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    recipient_email: str | None = Query(default=None),
    scheduled_from: datetime | None = Query(default=None),
    scheduled_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[OutreachSendQueueRead]:
    product_id = _require_product_scope(ctx)
    return await list_scheduled_queue(
        db,
        product_id=product_id,
        campaign_id=campaign_id,
        status_filter=status,
        recipient_email=recipient_email,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
        page=page,
        page_size=page_size,
    )


@router.post("/schedule", response_model=OutreachScheduleResponse, status_code=status.HTTP_201_CREATED)
async def schedule_outreach_send_queue(
    payload: OutreachScheduleRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachScheduleResponse:
    product_id = _require_product_scope(ctx)
    return await schedule_outreach_emails(
        db,
        product_id=product_id,
        user_id=ctx.user_id,
        payload=payload,
    )


@router.post("/process-today", response_model=OutreachSendQueueProcessResponse)
async def process_today_outreach_queue(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueProcessResponse:
    _require_product_scope(ctx)
    return await OutreachSendQueueService.process_today(db, ctx=ctx)


@router.delete("/failed", response_model=OutreachSendQueueClearFailedResponse)
async def clear_failed_outreach_queue(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueClearFailedResponse:
    product_id = _require_product_scope(ctx)
    deleted_count = await OutreachSendQueueService.clear_failed(db, product_id=product_id)
    return OutreachSendQueueClearFailedResponse(
        deleted_count=deleted_count,
        message=f"已删除 {deleted_count} 条失败队列记录",
    )


@router.post("/bulk-pause")
async def bulk_pause_outreach_queue(
    payload: OutreachQueueBulkActionRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, int]:
    product_id = _require_product_scope(ctx)
    updated = await pause_queue_items(db, product_id=product_id, ids=payload.ids)
    return {"updated_count": updated}


@router.post("/bulk-cancel")
async def bulk_cancel_outreach_queue(
    payload: OutreachQueueBulkActionRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, int]:
    product_id = _require_product_scope(ctx)
    updated = await cancel_queue_items(db, product_id=product_id, ids=payload.ids)
    return {"updated_count": updated}


@router.get("/{item_id}", response_model=OutreachSendQueueRead)
async def get_outreach_queue_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueRead:
    product_id = _require_product_scope(ctx)
    return await get_queue_item(db, product_id=product_id, item_id=item_id)


@router.post("/{item_id}/pause", response_model=OutreachSendQueueRead)
async def pause_outreach_queue_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueRead:
    product_id = _require_product_scope(ctx)
    await pause_queue_items(db, product_id=product_id, ids=[item_id])
    return await get_queue_item(db, product_id=product_id, item_id=item_id)


@router.post("/{item_id}/resume", response_model=OutreachSendQueueRead)
async def resume_outreach_queue_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueRead:
    product_id = _require_product_scope(ctx)
    await resume_queue_items(db, product_id=product_id, ids=[item_id])
    return await get_queue_item(db, product_id=product_id, item_id=item_id)


@router.post("/{item_id}/cancel", response_model=OutreachSendQueueRead)
async def cancel_outreach_queue_item_post(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueRead:
    product_id = _require_product_scope(ctx)
    await cancel_queue_items(db, product_id=product_id, ids=[item_id])
    return await get_queue_item(db, product_id=product_id, item_id=item_id)


@router.post("/{item_id}/send-now", response_model=OutreachSendQueueRead)
async def send_outreach_queue_item_now(
    item_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueRead:
    product_id = _require_product_scope(ctx)
    return await send_queue_item(item_id, product_id=product_id, user_id=ctx.user_id)


@router.post("/{item_id}/reschedule", response_model=OutreachSendQueueRead)
async def reschedule_outreach_queue_item(
    item_id: int,
    payload: OutreachQueueRescheduleRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueRead:
    product_id = _require_product_scope(ctx)
    return await reschedule_queue_item(db, product_id=product_id, item_id=item_id, payload=payload)


@router.delete("/{item_id}", response_model=OutreachSendQueueRead)
async def cancel_outreach_queue_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachSendQueueRead:
    product_id = _require_product_scope(ctx)
    return await OutreachSendQueueService.cancel(db, product_id=product_id, item_id=item_id)
