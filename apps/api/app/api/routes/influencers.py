from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.services.influencer_projection import merged_influencer_for_ai, to_influencer_read
from app.services.product_influencer_service import ProductInfluencerService
from app.schemas.common import PaginatedResponse
from app.schemas.contact import ContactRefreshResult
from app.schemas.influencer import (
    InfluencerCreate,
    InfluencerExportFilter,
    InfluencerFilter,
    InfluencerRead,
    InfluencerUpdate,
    PlatformStatsResponse,
)
from app.schemas.influencer_lead import FollowupCreate, FollowupRead, InfluencerLeadUpdate
from app.services.contact_discovery import ContactDiscoveryService
from app.services.export import build_influencer_library_excel
from app.services.influencer_lead import InfluencerLeadService

router = APIRouter(prefix="/influencers", tags=["influencers"])


async def _require_product_influencer(db: AsyncSession, ctx: TenantContext, influencer_id: int):
    pair = await ProductInfluencerService.get_product_influencer(
        db, product_id=ctx.product_id, record_id=influencer_id
    )
    if not pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Influencer not found")
    return pair


@router.get("", response_model=PaginatedResponse[InfluencerRead])
async def list_influencers(
    platform: str | None = None,
    country: str | None = None,
    category: str | None = None,
    follow_status: str | None = None,
    lead_status: str | None = None,
    lead_priority: str | None = None,
    owner_name: str | None = None,
    source_discovery_type: str | None = None,
    search: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    min_product_fit: float | None = Query(default=None, ge=0, le=100),
    has_email: bool | None = None,
    contactable: bool | None = None,
    high_value: bool | None = None,
    value_tier: str | None = None,
    high_match: bool | None = None,
    today_recommended: bool | None = None,
    pending_follow_up: bool | None = None,
    unassigned: bool | None = None,
    high_priority: bool | None = None,
    missing_contact: bool | None = None,
    high_credibility_contact: bool | None = None,
    collection_task_id: int | None = Query(default=None, ge=1),
    created_within_hours: int | None = Query(default=None, ge=1, le=720),
    collected_within_days: int | None = Query(default=None, ge=1, le=365),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[InfluencerRead]:
    filters = InfluencerFilter(
        platform=platform,
        country=country,
        category=category,
        follow_status=follow_status,
        lead_status=lead_status,
        lead_priority=lead_priority,
        owner_name=owner_name,
        source_discovery_type=source_discovery_type,
        search=search,
        min_score=min_score,
        min_product_fit=min_product_fit,
        has_email=has_email,
        contactable=contactable,
        high_value=high_value,
        value_tier=value_tier,
        high_match=high_match,
        today_recommended=today_recommended,
        pending_follow_up=pending_follow_up,
        unassigned=unassigned,
        high_priority=high_priority,
        missing_contact=missing_contact,
        high_credibility_contact=high_credibility_contact,
        collection_task_id=collection_task_id,
        created_within_hours=created_within_hours,
        collected_within_days=collected_within_days,
    )
    return await ProductInfluencerService.list_influencers(
        db, product_id=ctx.product_id, filters=filters, page=page, page_size=page_size
    )


@router.get("/platform-stats", response_model=PlatformStatsResponse)
async def get_influencer_platform_stats(
    platform: str | None = None,
    country: str | None = None,
    category: str | None = None,
    follow_status: str | None = None,
    lead_status: str | None = None,
    lead_priority: str | None = None,
    owner_name: str | None = None,
    source_discovery_type: str | None = None,
    search: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    min_product_fit: float | None = Query(default=None, ge=0, le=100),
    has_email: bool | None = None,
    contactable: bool | None = None,
    high_value: bool | None = None,
    value_tier: str | None = None,
    high_match: bool | None = None,
    today_recommended: bool | None = None,
    pending_follow_up: bool | None = None,
    unassigned: bool | None = None,
    high_priority: bool | None = None,
    missing_contact: bool | None = None,
    high_credibility_contact: bool | None = None,
    collection_task_id: int | None = Query(default=None, ge=1),
    created_within_hours: int | None = Query(default=None, ge=1, le=720),
    collected_within_days: int | None = Query(default=None, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PlatformStatsResponse:
    filters = InfluencerFilter(
        platform=platform,
        country=country,
        category=category,
        follow_status=follow_status,
        lead_status=lead_status,
        lead_priority=lead_priority,
        owner_name=owner_name,
        source_discovery_type=source_discovery_type,
        search=search,
        min_score=min_score,
        min_product_fit=min_product_fit,
        has_email=has_email,
        contactable=contactable,
        high_value=high_value,
        value_tier=value_tier,
        high_match=high_match,
        today_recommended=today_recommended,
        pending_follow_up=pending_follow_up,
        unassigned=unassigned,
        high_priority=high_priority,
        missing_contact=missing_contact,
        high_credibility_contact=high_credibility_contact,
        collection_task_id=collection_task_id,
        created_within_hours=created_within_hours,
        collected_within_days=collected_within_days,
    )
    return await ProductInfluencerService.get_platform_stats(
        db, product_id=ctx.product_id, filters=filters
    )


@router.get("/export/excel")
async def export_influencers_excel(
    platform: str | None = None,
    country: str | None = None,
    category: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    min_product_fit: float | None = Query(default=None, ge=0, le=100),
    follow_status: str | None = None,
    lead_status: str | None = None,
    keyword: str | None = None,
    has_email: bool | None = None,
    contactable: bool | None = None,
    high_value: bool | None = None,
    value_tier: str | None = None,
    high_match: bool | None = None,
    today_recommended: bool | None = None,
    collection_task_id: int | None = Query(default=None, ge=1),
    created_within_hours: int | None = Query(default=None, ge=1, le=720),
    collected_within_days: int | None = Query(default=None, ge=1, le=365),
    missing_contact: bool | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> StreamingResponse:
    export_filter = InfluencerExportFilter(
        platform=platform,
        country=country,
        category=category,
        min_score=min_score,
        min_product_fit=min_product_fit,
        follow_status=follow_status,
        lead_status=lead_status,
        keyword=keyword,
        has_email=has_email,
        contactable=contactable,
        high_value=high_value,
        value_tier=value_tier,
        high_match=high_match,
        today_recommended=today_recommended,
        collection_task_id=collection_task_id,
        created_within_hours=created_within_hours,
        collected_within_days=collected_within_days,
        missing_contact=missing_contact,
    )
    influencers = await ProductInfluencerService.list_for_export(
        db, product_id=ctx.product_id, filters=export_filter.to_query_filter()
    )

    if not influencers:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="没有符合筛选条件的红人数据，无法导出。请调整筛选条件后重试。",
        )

    content, filename = build_influencer_library_excel(influencers)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("", response_model=InfluencerRead, status_code=status.HTTP_201_CREATED)
async def create_influencer(
    data: InfluencerCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> InfluencerRead:
    try:
        product_row, global_row = await ProductInfluencerService.create_influencer(
            db, product_id=ctx.product_id, data=data
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return to_influencer_read(product_row, global_row)


@router.get("/{influencer_id}", response_model=InfluencerRead)
async def get_influencer(
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> InfluencerRead:
    pair = await ProductInfluencerService.get_product_influencer(
        db, product_id=ctx.product_id, record_id=influencer_id
    )
    if not pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Influencer not found")
    product_row, global_row = pair
    return to_influencer_read(product_row, global_row)


@router.patch("/{influencer_id}", response_model=InfluencerRead)
async def update_influencer(
    influencer_id: int,
    data: InfluencerUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> InfluencerRead:
    product_row, global_row = await _require_product_influencer(db, ctx, influencer_id)
    try:
        product_row, global_row = await ProductInfluencerService.update_influencer(
            db, product_row=product_row, global_row=global_row, data=data
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return to_influencer_read(product_row, global_row)


@router.patch("/{influencer_id}/lead", response_model=InfluencerRead)
async def update_influencer_lead(
    influencer_id: int,
    data: InfluencerLeadUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> InfluencerRead:
    product_row, global_row = await _require_product_influencer(db, ctx, influencer_id)
    try:
        product_row = await InfluencerLeadService.update_product_lead(db, product_row, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return to_influencer_read(product_row, global_row)


@router.get("/{influencer_id}/followups", response_model=list[FollowupRead])
async def list_influencer_followups(
    influencer_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[FollowupRead]:
    product_row, _ = await _require_product_influencer(db, ctx, influencer_id)
    followups = await InfluencerLeadService.list_product_followups(
        db, product_row.id, limit=limit
    )
    return [FollowupRead.model_validate(item) for item in followups]


@router.post("/{influencer_id}/followups", response_model=FollowupRead, status_code=status.HTTP_201_CREATED)
async def create_influencer_followup(
    influencer_id: int,
    data: FollowupCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> FollowupRead:
    product_row, _ = await _require_product_influencer(db, ctx, influencer_id)
    try:
        followup = await InfluencerLeadService.add_product_followup(db, product_row, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return FollowupRead.model_validate(followup)


@router.post("/{influencer_id}/refresh-contact", response_model=ContactRefreshResult)
async def refresh_influencer_contact(
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> ContactRefreshResult:
    product_row, global_row = await _require_product_influencer(db, ctx, influencer_id)
    temp = merged_influencer_for_ai(product_row, global_row)
    result = await ContactDiscoveryService.refresh_influencer(temp)
    ContactDiscoveryService.apply_to_influencer(global_row, result)
    await db.commit()
    await db.refresh(global_row)
    await db.refresh(product_row)
    return ContactRefreshResult(
        influencer=to_influencer_read(product_row, global_row),
        contact_fetch_status=result.contact_fetch_status,
        contact_fetch_error=result.contact_fetch_error,
        contact_discovered_at=result.contact_discovered_at,
        contact_sources=result.contact_sources,
        final_email=result.final_email,
        email_source=result.email_source,
        contact_score=result.contact_score,
        contact_credibility_level=result.contact_credibility_level,
        contact_page=result.contact_page,
        linktree_url=result.linktree_url,
        whatsapp=result.whatsapp,
        telegram=result.telegram,
    )


@router.delete("/{influencer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_influencer(
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    product_row, _ = await _require_product_influencer(db, ctx, influencer_id)
    await ProductInfluencerService.delete_influencer(db, product_row=product_row)
