# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：email logs
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.services.tenant_scope import ALL_PRODUCTS_ID, scoped_product_id
from app.models.enums import EmailLogStatus
from app.schemas.common import PaginatedResponse
from app.schemas.email_log import (
    EmailLogBulkDeleteByStatusRequest,
    EmailLogBulkDeleteRequest,
    EmailLogBulkDeleteResponse,
    EmailLogFilter,
    EmailLogRead,
    SaveEmailLogAsTemplateRequest,
    SaveEmailLogAsTemplateResponse,
)
from app.services.email_log import EmailLogService

router = APIRouter(prefix="/email-logs", tags=["email-logs"])


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择具体产品/品牌后再操作邮件日志",
        )
    return ctx.product_id


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


@router.post("/bulk-delete", response_model=EmailLogBulkDeleteResponse)
async def bulk_delete_email_logs(
    payload: EmailLogBulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailLogBulkDeleteResponse:
    product_id = _require_product_scope(ctx)
    deleted_ids, missing_ids = await EmailLogService.bulk_delete_logs(
        db,
        log_ids=payload.ids,
        product_id=product_id,
    )
    return EmailLogBulkDeleteResponse(
        deleted_count=len(deleted_ids),
        deleted_ids=deleted_ids,
        missing_ids=missing_ids,
    )


@router.post("/bulk-delete-by-status", response_model=EmailLogBulkDeleteResponse)
async def bulk_delete_email_logs_by_status(
    payload: EmailLogBulkDeleteByStatusRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailLogBulkDeleteResponse:
    product_id = _require_product_scope(ctx)
    deleted_ids = await EmailLogService.bulk_delete_logs_by_status(
        db,
        status=payload.status,
        product_id=product_id,
    )
    return EmailLogBulkDeleteResponse(
        deleted_count=len(deleted_ids),
        deleted_ids=deleted_ids,
        missing_ids=[],
    )


@router.post(
    "/{log_id}/save-as-message-template",
    response_model=SaveEmailLogAsTemplateResponse,
)
async def save_email_log_as_message_template(
    log_id: int,
    payload: SaveEmailLogAsTemplateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> SaveEmailLogAsTemplateResponse:
    product_id = _require_product_scope(ctx)
    log = await EmailLogService.get_log(db, log_id=log_id, product_id=product_id)
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邮件日志不存在")
    return await EmailLogService.save_as_message_template(db, log=log, ctx=ctx, payload=payload)
