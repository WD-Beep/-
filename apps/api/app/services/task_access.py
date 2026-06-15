from fastapi import HTTPException, status

from app.deps.tenant import TenantContext
from app.models.collection_task import CollectionTask
from app.services.tenant_scope import ALL_PRODUCTS_ID


def ensure_task_access(task: CollectionTask | None, ctx: TenantContext) -> CollectionTask:
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection task not found")
    if not task.product_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="任务未绑定产品，拒绝访问",
        )
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="请先选择具体产品后再访问采集任务",
        )
    if task.product_id != ctx.product_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该采集任务")
    return task
