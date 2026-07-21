# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：outreach records
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.models.email_log import EmailLog
from app.schemas.email_log import (
    BulkFollowUpRequest,
    BulkFollowUpResponse,
    EmailLogRead,
    ScheduleFollowUpRequest,
    StopFollowUpRequest,
)
from app.services.follow_up_scheduler import (
    bulk_create_second_follow_ups,
    mark_record_replied,
    mark_record_unreplied,
    schedule_follow_up_check,
    stop_follow_up,
)
from app.services.tenant_scope import ALL_PRODUCTS_ID

router = APIRouter(prefix="/outreach-records", tags=["outreach-records"])


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please select a specific product before operating outreach records",
        )
    return ctx.product_id


async def _safe_call(func, *args, **kwargs) -> EmailLog:
    try:
        return await func(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{record_id}/schedule-follow-up", response_model=EmailLogRead)
async def schedule_record_follow_up(
    record_id: int,
    payload: ScheduleFollowUpRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailLogRead:
    product_id = _require_product_scope(ctx)
    record = await _safe_call(
        schedule_follow_up_check,
        db,
        outreach_record_id=record_id,
        product_id=product_id,
        after_days=payload.after_days,
        max_followups=payload.max_followups,
    )
    return EmailLogRead.model_validate(record)


@router.post("/{record_id}/stop-follow-up", response_model=EmailLogRead)
async def stop_record_follow_up(
    record_id: int,
    payload: StopFollowUpRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailLogRead:
    product_id = _require_product_scope(ctx)
    record = await _safe_call(
        stop_follow_up,
        db,
        outreach_record_id=record_id,
        product_id=product_id,
        reason=payload.reason,
    )
    return EmailLogRead.model_validate(record)


@router.post("/{record_id}/mark-replied", response_model=EmailLogRead)
async def mark_outreach_record_replied(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailLogRead:
    product_id = _require_product_scope(ctx)
    record = await _safe_call(
        mark_record_replied,
        db,
        outreach_record_id=record_id,
        product_id=product_id,
        reply_summary="Manually marked as replied",
    )
    return EmailLogRead.model_validate(record)


@router.post("/{record_id}/mark-unreplied", response_model=EmailLogRead)
async def mark_outreach_record_unreplied(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailLogRead:
    product_id = _require_product_scope(ctx)
    record = await _safe_call(mark_record_unreplied, db, outreach_record_id=record_id, product_id=product_id)
    return EmailLogRead.model_validate(record)


@router.get("/follow-up-due", response_model=list[EmailLogRead])
async def list_due_follow_up_records(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[EmailLogRead]:
    product_id = _require_product_scope(ctx)
    rows = (
        await db.scalars(
            select(EmailLog)
            .where(
                EmailLog.product_id == product_id,
                EmailLog.follow_up_status == "pending_check",
                EmailLog.stop_follow_up.is_(False),
            )
            .order_by(EmailLog.next_follow_up_at.asc().nullslast())
            .limit(limit)
        )
    ).all()
    return [EmailLogRead.model_validate(row) for row in rows]


@router.post("/bulk-second-follow-up", response_model=BulkFollowUpResponse)
async def bulk_second_follow_up(
    payload: BulkFollowUpRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> BulkFollowUpResponse:
    product_id = _require_product_scope(ctx)
    result = await bulk_create_second_follow_ups(
        db,
        product_id=product_id,
        user_id=ctx.user_id,
        record_ids=payload.record_ids,
    )
    return BulkFollowUpResponse(
        requested_count=result.requested_count,
        created_count=result.created_count,
        skipped_count=result.skipped_count,
        created_record_ids=result.created_record_ids,
        queue_item_ids=result.queue_item_ids,
        skip_reasons=result.skip_reasons,
    )
