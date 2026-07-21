# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：ai
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context, require_write_product_id
from app.schemas.ai import (
    AiStatusResponse,
    AnalyzeInfluencerResponse,
    BatchAnalyzeRequest,
    BatchAnalyzeResponse,
)
from app.services.ai_analysis import AiAnalysisService
from app.services.product_influencer_service import ProductInfluencerService

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AiStatusResponse)
async def get_ai_status() -> AiStatusResponse:
    provider = settings.active_ai_provider
    return AiStatusResponse(
        provider=provider,
        model=settings.active_ai_model,
        configured=settings.is_openai_configured,
        mode=settings.ai_mode,
    )


@router.post("/analyze-influencer/{influencer_id}", response_model=AnalyzeInfluencerResponse)
async def analyze_influencer_by_id(
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AnalyzeInfluencerResponse:
    product_id = require_write_product_id(ctx)
    pair = await ProductInfluencerService.get_product_influencer(
        db, product_id=product_id, record_id=influencer_id
    )
    if not pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Influencer not found")

    product_row, global_row = pair
    return await AiAnalysisService.analyze_and_save(db, product_row, global_row)


@router.post("/batch-analyze", response_model=BatchAnalyzeResponse)
async def batch_analyze_influencers(
    payload: BatchAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> BatchAnalyzeResponse:
    product_id = require_write_product_id(ctx)
    return await AiAnalysisService.batch_analyze_and_save(
        db, payload.influencer_ids, product_id=product_id
    )
