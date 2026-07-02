from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.schemas.outreach_campaign import (
    OutreachCampaignBulkApproveRequest,
    OutreachCampaignBulkApproveResponse,
    OutreachCampaignCreateRequest,
    OutreachCampaignDraftUpdateRequest,
    OutreachCampaignGenerateAndSendResponse,
    OutreachCampaignPreviewRequest,
    OutreachCampaignPreviewResponse,
    OutreachCampaignProcessResponse,
    OutreachCampaignQueueRequest,
    OutreachCampaignQueueResponse,
    OutreachCampaignRead,
    OutreachCampaignRecipientListResponse,
    OutreachCampaignReplyBoardResponse,
    OutreachCampaignPreviewItem,
    OutreachOneClickWorkbenchResponse,
    OutreachCampaignUpdateRequest,
)
from app.services.outreach_campaign_service import OutreachCampaignService
from app.services.tenant_scope import ALL_PRODUCTS_ID, scoped_product_id

router = APIRouter(prefix="/outreach-campaigns", tags=["outreach-campaigns"])


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择具体产品/品牌后再操作邮件活动",
        )
    return ctx.product_id


@router.get("", response_model=list[OutreachCampaignRead])
async def list_outreach_campaigns(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[OutreachCampaignRead]:
    return await OutreachCampaignService.list_campaigns(db, product_id=scoped_product_id(ctx.product_id))


@router.get("/workbench", response_model=OutreachOneClickWorkbenchResponse)
async def get_outreach_workbench(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachOneClickWorkbenchResponse:
    return await OutreachCampaignService.get_one_click_workbench(db, product_id=scoped_product_id(ctx.product_id))


@router.post("", response_model=OutreachCampaignRead, status_code=status.HTTP_201_CREATED)
async def create_outreach_campaign(
    payload: OutreachCampaignCreateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignRead:
    _require_product_scope(ctx)
    return await OutreachCampaignService.create_campaign(db, ctx=ctx, payload=payload)


@router.patch("/{campaign_id}", response_model=OutreachCampaignRead)
async def update_outreach_campaign(
    campaign_id: int,
    payload: OutreachCampaignUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignRead:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.update_campaign(
        db,
        product_id=product_id,
        campaign_id=campaign_id,
        payload=payload,
    )


@router.post("/{campaign_id}/preview", response_model=OutreachCampaignPreviewResponse)
async def preview_outreach_campaign(
    campaign_id: int,
    payload: OutreachCampaignPreviewRequest | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignPreviewResponse:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.preview_campaign(
        db, product_id=product_id, campaign_id=campaign_id, payload=payload
    )


@router.get("/{campaign_id}/recipients", response_model=OutreachCampaignRecipientListResponse)
async def list_outreach_campaign_recipients(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignRecipientListResponse:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.list_campaign_recipients(
        db, product_id=product_id, campaign_id=campaign_id
    )


@router.post("/{campaign_id}/recipients/bulk-approve", response_model=OutreachCampaignBulkApproveResponse)
async def bulk_approve_outreach_campaign_drafts(
    campaign_id: int,
    payload: OutreachCampaignBulkApproveRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignBulkApproveResponse:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.bulk_approve_campaign_drafts(
        db, product_id=product_id, campaign_id=campaign_id, payload=payload
    )


@router.post("/{campaign_id}/recipients/{influencer_id}/open", response_model=OutreachCampaignPreviewItem)
async def open_outreach_campaign_draft(
    campaign_id: int,
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignPreviewItem:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.open_campaign_draft(
        db, product_id=product_id, campaign_id=campaign_id, influencer_id=influencer_id
    )


@router.patch("/{campaign_id}/recipients/{influencer_id}", response_model=OutreachCampaignPreviewItem)
async def update_outreach_campaign_draft(
    campaign_id: int,
    influencer_id: int,
    payload: OutreachCampaignDraftUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignPreviewItem:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.update_campaign_draft(
        db,
        product_id=product_id,
        campaign_id=campaign_id,
        influencer_id=influencer_id,
        payload=payload,
    )


@router.post("/{campaign_id}/recipients/{influencer_id}/regenerate", response_model=OutreachCampaignPreviewItem)
async def regenerate_outreach_campaign_draft(
    campaign_id: int,
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignPreviewItem:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.regenerate_campaign_draft(
        db, product_id=product_id, campaign_id=campaign_id, influencer_id=influencer_id
    )


@router.post("/{campaign_id}/recipients/{influencer_id}/approve", response_model=OutreachCampaignPreviewItem)
async def approve_outreach_campaign_draft(
    campaign_id: int,
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignPreviewItem:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.approve_campaign_draft(
        db, product_id=product_id, campaign_id=campaign_id, influencer_id=influencer_id
    )


@router.post("/{campaign_id}/recipients/{influencer_id}/skip", response_model=OutreachCampaignPreviewItem)
async def skip_outreach_campaign_draft(
    campaign_id: int,
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignPreviewItem:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.skip_campaign_draft(
        db, product_id=product_id, campaign_id=campaign_id, influencer_id=influencer_id
    )


@router.post("/{campaign_id}/queue", response_model=OutreachCampaignQueueResponse)
async def queue_outreach_campaign(
    campaign_id: int,
    payload: OutreachCampaignQueueRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignQueueResponse:
    _require_product_scope(ctx)
    return await OutreachCampaignService.queue_campaign(
        db, ctx=ctx, campaign_id=campaign_id, payload=payload
    )


@router.get("/{campaign_id}/replies", response_model=OutreachCampaignReplyBoardResponse)
async def list_outreach_campaign_replies(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignReplyBoardResponse:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.list_campaign_replies(
        db, product_id=product_id, campaign_id=campaign_id
    )


@router.post("/{campaign_id}/process", response_model=OutreachCampaignProcessResponse)
async def process_outreach_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignProcessResponse:
    _require_product_scope(ctx)
    return await OutreachCampaignService.process_campaign(
        db, ctx=ctx, campaign_id=campaign_id
    )


@router.post("/{campaign_id}/generate-and-send", response_model=OutreachCampaignGenerateAndSendResponse)
async def generate_and_send_outreach_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignGenerateAndSendResponse:
    _require_product_scope(ctx)
    return await OutreachCampaignService.generate_and_send_campaign(
        db, ctx=ctx, campaign_id=campaign_id
    )


@router.post("/{campaign_id}/pause", response_model=OutreachCampaignRead)
async def pause_outreach_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignRead:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.pause_campaign(
        db, product_id=product_id, campaign_id=campaign_id
    )


@router.post("/{campaign_id}/resume", response_model=OutreachCampaignRead)
async def resume_outreach_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignRead:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.resume_campaign(
        db, product_id=product_id, campaign_id=campaign_id
    )


@router.post("/{campaign_id}/cancel", response_model=OutreachCampaignRead)
async def cancel_outreach_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> OutreachCampaignRead:
    product_id = _require_product_scope(ctx)
    return await OutreachCampaignService.cancel_campaign(
        db, product_id=product_id, campaign_id=campaign_id
    )
