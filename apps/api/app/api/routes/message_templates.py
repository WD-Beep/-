from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context, require_write_product_id
from app.models.message_template import MessageTemplate
from app.schemas.common import PaginatedResponse
from app.schemas.message_template import (
    MessageTemplateCreate,
    MessageTemplateFilter,
    MessageTemplateRead,
    MessageTemplateUpdate,
)
from app.services.default_message_templates import ensure_default_templates_for_product
from app.services.message_template import MessageTemplateService
from app.services.tenant_scope import ALL_PRODUCTS_ID

router = APIRouter(prefix="/message-templates", tags=["message-templates"])


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择具体产品/品牌后再操作话术库",
        )
    return ctx.product_id


def _ensure_template_access(row: MessageTemplate, ctx: TenantContext) -> None:
    product_id = _require_product_scope(ctx)
    if row.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")


@router.get("", response_model=PaginatedResponse[MessageTemplateRead])
async def list_message_templates(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    scenario: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    language: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[MessageTemplateRead]:
    product_id = _require_product_scope(ctx)
    await ensure_default_templates_for_product(db, ctx=ctx, product_id=product_id)
    filters = MessageTemplateFilter(
        product_id=product_id,
        search=search,
        scenario=scenario,
        platform=platform,
        language=language,
        tag=tag,
    )
    return await MessageTemplateService.list_templates(db, filters, page, page_size)


@router.post("", response_model=MessageTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_message_template(
    data: MessageTemplateCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    _require_product_scope(ctx)
    row = await MessageTemplateService.create_template(db, data, ctx=ctx)
    return MessageTemplateService._to_read(row)


@router.get("/{template_id}", response_model=MessageTemplateRead)
async def get_message_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    product_id = _require_product_scope(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    return MessageTemplateService._to_read(row)


@router.patch("/{template_id}", response_model=MessageTemplateRead)
async def update_message_template(
    template_id: int,
    data: MessageTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    product_id = _require_product_scope(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    _ensure_template_access(row, ctx)
    updated = await MessageTemplateService.update_template(db, row, data)
    return MessageTemplateService._to_read(updated)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    product_id = _require_product_scope(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    _ensure_template_access(row, ctx)
    await MessageTemplateService.delete_template(db, row)


@router.post("/{template_id}/use", response_model=MessageTemplateRead)
async def use_message_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    product_id = _require_product_scope(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    _ensure_template_access(row, ctx)
    updated = await MessageTemplateService.record_use(db, row)
    return MessageTemplateService._to_read(updated)


@router.post("/{template_id}/duplicate", response_model=MessageTemplateRead, status_code=status.HTTP_201_CREATED)
async def duplicate_message_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    product_id = require_write_product_id(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    copy = await MessageTemplateService.duplicate_template(db, row, ctx=ctx)
    return MessageTemplateService._to_read(copy)
