# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：dashboard
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.schemas.dashboard import DashboardMonthlyReport, DashboardSummary
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> DashboardSummary:
    return await DashboardService.get_summary(db, product_id=ctx.product_id)


@router.get("/monthly-report", response_model=DashboardMonthlyReport)
async def get_dashboard_monthly_report(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> DashboardMonthlyReport:
    return await DashboardService.get_monthly_report(db, product_id=ctx.product_id, month=month)
