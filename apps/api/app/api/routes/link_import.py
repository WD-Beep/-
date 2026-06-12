# link-import routes (v2)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context, require_write_product_id
from app.services.tenant_scope import ALL_PRODUCTS_ID, scoped_product_id
from app.models.enums import LinkImportBatchStatus
from app.models.link_import_batch import LinkImportBatch
from app.schemas.common import PaginatedResponse
from app.schemas.link_import import (
    LinkImportBatchCreate,
    LinkImportBatchRead,
    LinkImportRunResult,
)
from app.services.link_import import LinkImportService

router = APIRouter(prefix="/link-import", tags=["link-import"])


def _ensure_batch_access(batch: LinkImportBatch, ctx: TenantContext) -> None:
    if (
        batch.product_id is not None
        and batch.product_id != ctx.product_id
        and ctx.product_id != ALL_PRODUCTS_ID
        and not ctx.is_admin
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该导入批次")


@router.get("/batches", response_model=PaginatedResponse[LinkImportBatchRead])
async def list_link_import_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[LinkImportBatchRead]:
    return await LinkImportService.list_batches(
        db, page, page_size, product_id=scoped_product_id(ctx.product_id)
    )


@router.post("/batches", response_model=LinkImportBatchRead, status_code=status.HTTP_201_CREATED)
async def create_link_import_batch(
    data: LinkImportBatchCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkImportBatchRead:
    if not data.name.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请填写批次名称")
    if not data.raw_urls.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请粘贴至少一行链接")

    batch = await LinkImportService.create_batch(db, data, ctx=ctx)
    return LinkImportBatchRead.model_validate(batch)


@router.get("/batches/{batch_id}", response_model=LinkImportBatchRead)
async def get_link_import_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkImportBatchRead:
    batch = await LinkImportService.get_batch(
        db, batch_id, product_id=scoped_product_id(ctx.product_id)
    )
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导入批次不存在")
    _ensure_batch_access(batch, ctx)
    return LinkImportBatchRead.model_validate(batch)


@router.post("/batches/{batch_id}/run", response_model=LinkImportRunResult)
async def run_link_import_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkImportRunResult:
    batch = await LinkImportService.get_batch(
        db, batch_id, product_id=scoped_product_id(ctx.product_id)
    )
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导入批次不存在")
    _ensure_batch_access(batch, ctx)

    if batch.status == LinkImportBatchStatus.COMPLETED.value:
        return LinkImportRunResult(
            batch_id=batch.id,
            status=LinkImportBatchStatus(batch.status),
            total_count=batch.total_count,
            success_count=batch.success_count,
            failed_count=batch.failed_count,
            new_count=batch.new_count,
            updated_count=batch.updated_count,
            invalid_urls=batch.invalid_urls or [],
        )

    try:
        batch = await LinkImportService.run_batch(db, batch)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Link import failed: {exc}",
        ) from exc

    return LinkImportRunResult(
        batch_id=batch.id,
        status=LinkImportBatchStatus(batch.status),
        total_count=batch.total_count,
        success_count=batch.success_count,
        failed_count=batch.failed_count,
        new_count=batch.new_count,
        updated_count=batch.updated_count,
        invalid_urls=batch.invalid_urls or [],
    )


@router.delete("/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link_import_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    batch = await LinkImportService.get_batch(
        db, batch_id, product_id=scoped_product_id(ctx.product_id)
    )
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导入批次不存在")
    _ensure_batch_access(batch, ctx)
    if batch.status == LinkImportBatchStatus.RUNNING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="正在运行的批次无法删除")
    await db.delete(batch)
    await db.commit()
