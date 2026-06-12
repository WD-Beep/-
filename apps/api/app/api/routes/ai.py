from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
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
    return AiStatusResponse(
        provider="kimi",
        model=settings.kimi_model if settings.is_kimi_configured else None,
        configured=settings.is_kimi_configured,
        mode=settings.ai_mode,
    )


@router.post("/analyze-influencer/{influencer_id}", response_model=AnalyzeInfluencerResponse)
async def analyze_influencer_by_id(
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> AnalyzeInfluencerResponse:
    pair = await ProductInfluencerService.get_product_influencer(
        db, product_id=ctx.product_id, record_id=influencer_id
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
    return await AiAnalysisService.batch_analyze_and_save(
        db, payload.influencer_ids, product_id=ctx.product_id
    )
