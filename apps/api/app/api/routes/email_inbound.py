import math

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context
from app.schemas.common import PaginatedResponse
from app.schemas.email_reply import (
    EmailReplyBulkDeleteRequest,
    EmailReplyBulkDeleteResponse,
    EmailReplyCountSummary,
    EmailReplyIngestBatchResponse,
    EmailReplyIngestResult,
    EmailReplyRead,
    EmailReplySendResponseRequest,
    EmailReplySendResponseResult,
    EmailReplySummary,
    EmailReplyUpdateRequest,
    InboundEmailStatus,
    InboundEmailWebhookRequest,
)
from app.services.email_reply_service import EmailReplyService
from app.services.tenant_scope import ALL_PRODUCTS_ID, scoped_product_id

router = APIRouter(prefix="/email-inbound", tags=["email-inbound"])
email_replies_router = APIRouter(prefix="/email-replies", tags=["email-replies"])


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择具体产品/品牌后再查看回复",
        )
    return ctx.product_id


def _verify_webhook_secret(x_webhook_secret: str | None) -> None:
    expected = settings.email_inbound_webhook_secret.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inbound webhook 未配置",
        )
    if not x_webhook_secret or x_webhook_secret.strip() != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook secret 无效")


@router.get("/status", response_model=InboundEmailStatus)
async def get_inbound_email_status() -> InboundEmailStatus:
    return InboundEmailStatus(**settings.get_inbound_email_status())


@router.post("/webhook", response_model=EmailReplyIngestResult)
async def ingest_inbound_webhook(
    payload: InboundEmailWebhookRequest,
    db: AsyncSession = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> EmailReplyIngestResult:
    _verify_webhook_secret(x_webhook_secret)
    normalized = EmailReplyService.webhook_to_payload(payload)
    return await EmailReplyService.ingest(db, normalized, source="webhook")


@router.post("/poll-imap", response_model=EmailReplyIngestBatchResponse)
async def poll_imap_inbox(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
    mark_seen: bool = Query(default=False),
) -> EmailReplyIngestBatchResponse:
    product_id = _require_product_scope(ctx)
    try:
        return await EmailReplyService.poll_imap(
            db,
            mark_seen=mark_seen,
            product_id_hint=product_id,
            user_id=ctx.user_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/replies", response_model=PaginatedResponse[EmailReplyRead])
async def list_email_replies(
    product_influencer_id: int | None = None,
    email_log_id: int | None = None,
    campaign_id: int | None = None,
    processing_status: str | None = Query(default=None, pattern="^(unprocessed|processed)$"),
    intent_status: str | None = Query(
        default=None,
        pattern="^(unprocessed|interested|follow_up|not_interested|processed|unmatched)$",
    ),
    unmatched: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[EmailReplyRead]:
    items, total = await EmailReplyService.list_replies(
        db,
        product_id=scoped_product_id(ctx.product_id),
        product_influencer_id=product_influencer_id,
        email_log_id=email_log_id,
        campaign_id=campaign_id,
        processing_status=processing_status,
        intent_status=intent_status,
        unmatched=unmatched,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/replies/work-count", response_model=EmailReplyCountSummary)
async def get_email_reply_work_count(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailReplyCountSummary:
    unprocessed_count, unmatched_count, unviewed_count = await EmailReplyService.count_reply_work(
        db,
        product_id=scoped_product_id(ctx.product_id),
    )
    return EmailReplyCountSummary(
        unprocessed_count=unprocessed_count,
        unmatched_count=unmatched_count,
        unviewed_count=unviewed_count,
    )


@router.patch("/replies/{reply_id}", response_model=EmailReplyRead)
async def update_email_reply(
    reply_id: int,
    payload: EmailReplyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailReplyRead:
    product_id = _require_product_scope(ctx)
    try:
        return await EmailReplyService.update_reply(
            db,
            product_id=product_id,
            reply_id=reply_id,
            product_influencer_id=payload.product_influencer_id,
            campaign_id=payload.campaign_id,
            intent_status=payload.intent_status,
            processing_status=payload.processing_status,
            manual_note=payload.manual_note,
            mark_viewed=payload.mark_viewed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/replies/{reply_id}/rematch", response_model=EmailReplyRead)
async def rematch_email_reply(
    reply_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailReplyRead:
    product_id = _require_product_scope(ctx)
    try:
        return await EmailReplyService.rematch_reply(db, product_id=product_id, reply_id=reply_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _send_email_reply_response(
    reply_id: int,
    payload: EmailReplySendResponseRequest,
    db: AsyncSession,
    ctx: TenantContext,
) -> EmailReplySendResponseResult:
    product_id = _require_product_scope(ctx)
    try:
        return await EmailReplyService.send_response(
            db,
            product_id=product_id,
            user_id=ctx.user_id,
            reply_id=reply_id,
            body=payload.body,
            subject=payload.subject,
            use_ai_draft=payload.use_ai_draft,
            mark_processed=payload.mark_processed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/replies/{reply_id}/send-response", response_model=EmailReplySendResponseResult)
async def send_email_reply_response(
    reply_id: int,
    payload: EmailReplySendResponseRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailReplySendResponseResult:
    return await _send_email_reply_response(reply_id, payload, db, ctx)


@email_replies_router.post("/{reply_id}/send-response", response_model=EmailReplySendResponseResult)
async def send_email_reply_response_alias(
    reply_id: int,
    payload: EmailReplySendResponseRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailReplySendResponseResult:
    return await _send_email_reply_response(reply_id, payload, db, ctx)


@router.post("/replies/bulk-delete", response_model=EmailReplyBulkDeleteResponse)
async def bulk_delete_email_replies(
    payload: EmailReplyBulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailReplyBulkDeleteResponse:
    product_id = _require_product_scope(ctx)
    return await EmailReplyService.delete_replies(
        db,
        product_id=product_id,
        reply_ids=payload.ids,
    )


@router.get("/campaigns/{campaign_id}/reply-summary", response_model=EmailReplySummary)
async def get_campaign_reply_summary(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailReplySummary:
    product_id = _require_product_scope(ctx)
    return await EmailReplyService.reply_summary_for_campaign(
        db,
        product_id=product_id,
        campaign_id=campaign_id,
    )
