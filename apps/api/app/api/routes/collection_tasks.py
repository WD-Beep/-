import logging

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory, get_db
from app.deps.tenant import TenantContext, get_tenant_context, require_write_product_id
from app.services.tenant_scope import ALL_PRODUCTS_ID, scoped_product_id
from app.services.task_access import ensure_task_access
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionTaskStatus, CandidateStatus
from app.schemas.email import EmailSendResult
from app.schemas.collection_task import (
    CollectionTaskBulkDelete,
    CollectionTaskBulkDeleteResult,
    CollectionTaskBulkManage,
    CollectionTaskBulkManageResult,
    CollectionTaskBulkRun,
    CollectionTaskBulkRunResult,
    CollectionTaskDeleteResult,
    CollectionTaskCandidateFilter,
    CollectionTaskCandidateBatchRecrawlRequest,
    CollectionTaskCandidateBatchRecrawlResult,
    CollectionTaskCandidateBatchEmailEnrichmentRequest,
    CollectionTaskCandidateBatchEmailEnrichmentResult,
    CollectionTaskCandidateEmailEnrichmentResult,
    CollectionTaskCandidateRead,
    CollectionTaskCandidateRecrawlRequest,
    CollectionTaskCandidateRecrawlResult,
    CollectionTaskCreate,
    CollectionTaskFilter,
    CollectionTaskRead,
    CollectionRunResult,
    CollectionTaskUpdate,
    collection_task_candidate_read,
)
from app.schemas.common import PaginatedResponse
from app.services.export import build_collection_task_candidates_excel
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.services.task_candidate import TaskCandidateService
from app.services.task_candidate_recrawl import TaskCandidateRecrawlService
from app.services.youtube_email_enrichment import YouTubeEmailEnrichmentService
from app.services.task_retention import task_has_retention_traces
from app.schemas.scheduler import SchedulerRefreshResponse
from app.scheduler import refresh_scheduler
from app.schemas.platform_capabilities import PlatformCapabilitiesResponse, PlatformCapabilityRead
from app.services.api_direct_provider import list_platform_capabilities
from app.services.collection_runner import CollectionRunnerService
from app.services.collection_task import CollectionTaskService
from app.services.email import EmailService
from app.services.task_run_progress import STAGE_DISCOVERY, reset_run_progress

router = APIRouter(prefix="/collection-tasks", tags=["collection-tasks"])
logger = logging.getLogger(__name__)


def _collection_start_message(task) -> str:
    platforms = [str(p).lower() for p in (getattr(task, "platforms", None) or []) if p]
    if not platforms and getattr(task, "platform", None):
        platforms = [str(task.platform).lower()]
    platform_names = ", ".join(dict.fromkeys(platforms)) or "配置的平台"
    return f"采集任务已开始，正在从 {platform_names} 发现候选作者并补采主页"


def _run_result_snapshot(task, *, message: str | None = None) -> CollectionRunResult:
    return CollectionRunResult(
        task_id=task.id,
        status=CollectionTaskStatus(task.status),
        new_count=0,
        updated_count=0,
        skipped_count=0,
        filtered_count=task.filtered_out_count or 0,
        total_count=task.result_count or 0,
        discovered_count=task.discovered_count or 0,
        deduped_count=task.deduped_count or 0,
        profile_fetched_count=task.profile_fetched_count or 0,
        profile_failed_count=task.profile_failed_count or 0,
        filtered_out_count=task.filtered_out_count or 0,
        inserted_count=task.inserted_count or 0,
        hashtag_count=task.hashtag_count or 0,
        post_count=task.post_count or 0,
        comment_author_count=task.comment_author_count or 0,
        filtered_below_min_followers_count=getattr(task, "filtered_below_min_followers_count", 0) or 0,
        filtered_excluded_keyword_count=getattr(task, "filtered_excluded_keyword_count", 0) or 0,
        email_count=task.email_count or 0,
        missing_contact_count=task.missing_contact_count or 0,
        status_summary=message or task.status_summary,
    )


async def _run_collection_task_in_background(task_id: int, *, resume: bool = False) -> None:
    async with async_session_factory() as bg_db:
        task = await CollectionTaskService.get_task(bg_db, task_id)
        if not task:
            return
        try:
            await CollectionRunnerService.run_task(bg_db, task, allow_running=True, resume=resume)
        except Exception as exc:
            logger.exception("Background collection task %s failed: %s", task_id, exc)


@router.get("/platform-capabilities", response_model=PlatformCapabilitiesResponse)
async def get_platform_capabilities() -> PlatformCapabilitiesResponse:
    caps = list_platform_capabilities()
    return PlatformCapabilitiesResponse(
        items=[PlatformCapabilityRead.model_validate(cap.__dict__) for cap in caps],
        api_direct_configured=settings.is_api_direct_configured,
        apify_configured=settings.is_apify_configured,
        instagram_data_provider=settings.active_instagram_provider,
        youtube_data_provider=settings.active_youtube_provider,
        tiktok_data_provider=settings.active_tiktok_provider,
        facebook_data_provider=settings.active_facebook_provider,
        collection_max_running_tasks=max(1, settings.collection_max_running_tasks),
        collection_profile_enrich_concurrency=settings.effective_profile_enrich_concurrency,
        collection_profile_request_timeout_seconds=max(5, settings.collection_profile_request_timeout_seconds),
        collection_running_stale_seconds=max(30, settings.collection_running_stale_seconds),
    )


@router.get("", response_model=PaginatedResponse[CollectionTaskRead])
async def list_collection_tasks(
    platform: str | None = None,
    status: CollectionTaskStatus | None = None,
    search: str | None = None,
    effectiveness: Literal["high_value", "effective", "ineffective", "low_value_result", "no_result", "failed"] | None = None,
    owner_scope: Literal["mine", "all"] = "mine",
    task_view: Literal[
        "all",
        "high_value",
        "effective",
        "ineffective",
        "low_value_result",
        "no_result",
        "test_history",
        "archived",
    ] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[CollectionTaskRead]:
    product_id = scoped_product_id(ctx.product_id)
    if ctx.product_id == ALL_PRODUCTS_ID:
        owner_scope = "all"
    filters = CollectionTaskFilter(
        product_id=product_id,
        platform=platform,
        status=status,
        search=search,
        effectiveness=effectiveness,
        owner_user_id=ctx.user_id,
        owner_scope=owner_scope,
        owner_is_admin=ctx.is_admin or ctx.product_id == ALL_PRODUCTS_ID,
        task_view=task_view,
    )
    return await CollectionTaskService.list_tasks(db, filters, page, page_size)


@router.post("", response_model=CollectionTaskRead, status_code=status.HTTP_201_CREATED)
async def create_collection_task(
    data: CollectionTaskCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskRead:
    task = await CollectionTaskService.create_task(
        db,
        data,
        user_id=ctx.user_id,
        workspace_id=ctx.workspace_id,
        product_id=require_write_product_id(ctx),
    )
    await refresh_scheduler()
    return CollectionTaskService.task_read(task)


@router.post("/scheduler/refresh", response_model=SchedulerRefreshResponse)
async def refresh_collection_scheduler() -> SchedulerRefreshResponse:
    result = await refresh_scheduler()
    return SchedulerRefreshResponse(
        registered=result.registered,
        skipped=result.skipped,
        errors=result.errors,
        message=f"已注册 {result.registered} 个定时任务，跳过 {result.skipped} 个",
    )


@router.post("/bulk-delete", response_model=CollectionTaskBulkDeleteResult)
async def bulk_delete_collection_tasks(
    data: CollectionTaskBulkDelete,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskBulkDeleteResult:
    product_id = require_write_product_id(ctx)
    tasks: list = []
    for task_id in data.task_ids:
        task = await db.get(CollectionTask, task_id)
        if not task or task.is_archived:
            continue
        ensure_task_access(task, ctx)
        if task.product_id != product_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除该任务")
        tasks.append(task)
    result = await CollectionTaskService.delete_tasks_bulk(
        db, tasks, require_ineffective=True
    )
    await refresh_scheduler()
    return CollectionTaskBulkDeleteResult(
        deleted_count=len(result["deleted_ids"]),
        archived_count=len(result["archived_ids"]),
        skipped_count=len(result["skipped_ids"]),
        deleted_ids=result["deleted_ids"],
        archived_ids=result["archived_ids"],
        skipped_ids=result["skipped_ids"],
    )


@router.post("/bulk-manage", response_model=CollectionTaskBulkManageResult)
async def bulk_manage_collection_tasks(
    data: CollectionTaskBulkManage,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskBulkManageResult:
    product_id = require_write_product_id(ctx)
    result = await CollectionTaskService.bulk_manage_tasks(
        db,
        action=data.action,
        product_id=product_id,
        task_ids=data.task_ids,
        owner_user_id=ctx.user_id,
        owner_scope="mine",
        owner_is_admin=ctx.is_admin,
    )
    await refresh_scheduler()
    return result


@router.get("/{task_id}", response_model=CollectionTaskRead)
async def get_collection_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskRead:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    retention = await task_has_retention_traces(db, task.id, task=task)
    return CollectionTaskService.task_read(task, has_retention_traces=retention)


@router.patch("/{task_id}", response_model=CollectionTaskRead)
async def update_collection_task(
    task_id: int,
    data: CollectionTaskUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskRead:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    updated = await CollectionTaskService.update_task(db, task, data)
    await refresh_scheduler()
    return CollectionTaskService.task_read(updated)


@router.delete("/{task_id}", response_model=CollectionTaskDeleteResult)
async def delete_collection_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskDeleteResult:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    try:
        action = await CollectionTaskService.delete_task(db, task)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await refresh_scheduler()
    return CollectionTaskDeleteResult(action=action, task_id=task_id)


@router.get("/{task_id}/candidates", response_model=PaginatedResponse[CollectionTaskCandidateRead])
async def list_collection_task_candidates(
    task_id: int,
    candidate_status: str | None = Query(default=None, alias="status"),
    failure_reason: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source_discovery_type: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    high_value: bool | None = Query(default=None),
    has_email: bool | None = Query(default=None),
    has_contact: bool | None = Query(default=None),
    min_followers_count: int | None = Query(default=None, ge=0),
    max_followers_count: int | None = Query(default=None, ge=0),
    min_engagement_rate: float | None = Query(default=None, ge=0, le=100),
    max_engagement_rate: float | None = Query(default=None, ge=0, le=100),
    insert_blocked_reason: str | None = Query(default=None),
    contact_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[CollectionTaskCandidateRead]:
    task = ensure_task_access(await CollectionTaskService.get_task_including_archived(db, task_id), ctx)
    await TaskCandidateService.ensure_candidates_for_task(db, task)
    await db.flush()
    result = await TaskCandidateService.list_for_task(
        db,
        task_id,
        page=page,
        page_size=page_size,
        status=candidate_status,
        failure_reason=failure_reason,
        source_type=source_type,
        source_discovery_type=source_discovery_type,
        platform=platform,
        high_value=high_value,
        has_email=has_email,
        has_contact=has_contact,
        min_followers_count=min_followers_count,
        max_followers_count=max_followers_count,
        min_engagement_rate=min_engagement_rate,
        max_engagement_rate=max_engagement_rate,
        insert_blocked_reason=insert_blocked_reason,
        contact_status=contact_status,
        search=search,
    )
    return PaginatedResponse(
        items=[collection_task_candidate_read(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.post(
    "/{task_id}/candidates/recrawl",
    response_model=CollectionTaskCandidateRecrawlResult,
)
async def recrawl_collection_task_candidate_by_profile(
    task_id: int,
    data: CollectionTaskCandidateRecrawlRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskCandidateRecrawlResult:
    task = ensure_task_access(await CollectionTaskService.get_task_including_archived(db, task_id), ctx)
    candidate_id = data.candidate_id
    if candidate_id is None:
        if not data.profile_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="candidate_id or profile_url is required")
        result = await db.execute(
            select(CollectionTaskCandidate.id).where(
                CollectionTaskCandidate.task_id == task.id,
                CollectionTaskCandidate.profile_url == data.profile_url,
            )
        )
        candidate_id = result.scalar_one_or_none()
        if candidate_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="candidate_not_found")
    try:
        result = await TaskCandidateRecrawlService.recrawl_candidate(
            db,
            candidate_id,
            task_id=task.id,
            profile_url=data.profile_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CollectionTaskCandidateRecrawlResult(**result.__dict__)


@router.post(
    "/{task_id}/candidates/{candidate_id}/recrawl",
    response_model=CollectionTaskCandidateRecrawlResult,
)
async def recrawl_collection_task_candidate(
    task_id: int,
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskCandidateRecrawlResult:
    task = ensure_task_access(await CollectionTaskService.get_task_including_archived(db, task_id), ctx)
    try:
        result = await TaskCandidateRecrawlService.recrawl_candidate(db, candidate_id, task_id=task.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CollectionTaskCandidateRecrawlResult(**result.__dict__)


@router.post(
    "/{task_id}/candidates/recrawl-failed",
    response_model=CollectionTaskCandidateBatchRecrawlResult,
)
async def recrawl_collection_task_failed_candidates(
    task_id: int,
    data: CollectionTaskCandidateBatchRecrawlRequest | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskCandidateBatchRecrawlResult:
    task = ensure_task_access(await CollectionTaskService.get_task_including_archived(db, task_id), ctx)
    payload = data or CollectionTaskCandidateBatchRecrawlRequest()
    try:
        result = await TaskCandidateRecrawlService.recrawl_failed_candidates_for_task(
            db,
            task.id,
            concurrency=payload.concurrency,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CollectionTaskCandidateBatchRecrawlResult(
        task_id=result.task_id,
        attempted=result.attempted,
        succeeded=result.succeeded,
        failed=result.failed,
        skipped=result.skipped,
        items=[CollectionTaskCandidateRecrawlResult(**item.__dict__) for item in result.items],
    )


@router.post(
    "/{task_id}/candidates/{candidate_id}/enrich-youtube-email",
    response_model=CollectionTaskCandidateEmailEnrichmentResult,
)
async def enrich_collection_task_candidate_youtube_email(
    task_id: int,
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskCandidateEmailEnrichmentResult:
    task = ensure_task_access(await CollectionTaskService.get_task_including_archived(db, task_id), ctx)
    try:
        result = await YouTubeEmailEnrichmentService.enrich_candidate(db, candidate_id, task_id=task.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CollectionTaskCandidateEmailEnrichmentResult(**result.__dict__)


@router.post(
    "/{task_id}/candidates/enrich-youtube-emails",
    response_model=CollectionTaskCandidateBatchEmailEnrichmentResult,
)
async def enrich_collection_task_candidates_youtube_emails(
    task_id: int,
    data: CollectionTaskCandidateBatchEmailEnrichmentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskCandidateBatchEmailEnrichmentResult:
    task = ensure_task_access(await CollectionTaskService.get_task_including_archived(db, task_id), ctx)
    payload = data or CollectionTaskCandidateBatchEmailEnrichmentRequest()
    try:
        result = await YouTubeEmailEnrichmentService.enrich_missing_for_task(
            db,
            task.id,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CollectionTaskCandidateBatchEmailEnrichmentResult(
        task_id=result.task_id,
        attempted=result.attempted,
        succeeded=result.succeeded,
        failed=result.failed,
        skipped=result.skipped,
        items=[CollectionTaskCandidateEmailEnrichmentResult(**item.__dict__) for item in result.items],
    )


@router.get("/{task_id}/candidates/export")
async def export_collection_task_candidates(
    task_id: int,
    candidate_status: str | None = Query(default=None, alias="status"),
    failure_reason: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source_discovery_type: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    high_value: bool | None = Query(default=None),
    has_email: bool | None = Query(default=None),
    has_contact: bool | None = Query(default=None),
    min_followers_count: int | None = Query(default=None, ge=0),
    max_followers_count: int | None = Query(default=None, ge=0),
    min_engagement_rate: float | None = Query(default=None, ge=0, le=100),
    max_engagement_rate: float | None = Query(default=None, ge=0, le=100),
    insert_blocked_reason: str | None = Query(default=None),
    contact_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> StreamingResponse:
    task = ensure_task_access(await CollectionTaskService.get_task_including_archived(db, task_id), ctx)
    await TaskCandidateService.ensure_candidates_for_task(db, task)
    await db.flush()

    rows = await TaskCandidateService.list_for_export(
        db,
        task_id,
        product_id=task.product_id,
        status=candidate_status,
        failure_reason=failure_reason,
        source_type=source_type,
        source_discovery_type=source_discovery_type,
        platform=platform,
        high_value=high_value,
        has_email=has_email,
        has_contact=has_contact,
        min_followers_count=min_followers_count,
        max_followers_count=max_followers_count,
        min_engagement_rate=min_engagement_rate,
        max_engagement_rate=max_engagement_rate,
        insert_blocked_reason=insert_blocked_reason,
        contact_status=contact_status,
        search=search,
    )
    if not rows and (task.inserted_count or 0) > 0 and candidate_status == CandidateStatus.INSERTED.value:
        rows = await TaskCandidateService.list_for_export(
            db,
            task_id,
            product_id=task.product_id,
            status=CandidateStatus.INSERTED.value,
        )
    if not rows:
        inserted = task.inserted_count or 0
        if inserted > 0:
            detail = (
                "当前筛选无数据，但任务显示有入库记录。请清空筛选或切换到「全部状态」后再导出；"
                "若仍无数据，可能是历史任务缺少候选池明细，请重新运行任务或从红人库导出。"
            )
        else:
            detail = "没有符合筛选条件的候选数据，无法导出。请调整筛选条件后重试。"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )

    content, filename = build_collection_task_candidates_excel(
        rows,
        task_id=task_id,
        task_name=task.name,
    )
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/{task_id}/enrich-link-seeds", response_model=CollectionRunResult)
async def enrich_link_seed_profiles(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionRunResult:
    """继续补采 LTK/ShopMy/Pinterest seed 的社媒资料（重新执行链接导入补全）。"""
    from app.models.enums import CollectionMode

    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    if task.collection_mode != CollectionMode.LINK_IMPORT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅链接导入任务支持继续补采社媒资料",
        )
    platforms = [str(p).lower() for p in (task.platforms or []) if p]
    if not any(p in {"ltk", "shopmy", "pinterest"} for p in platforms):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前任务不包含 LTK/ShopMy/Pinterest 链接，无需 seed 补全",
        )
    blocking_task = await CollectionTaskService.get_blocking_running_task(db, exclude_id=task_id)
    if blocking_task is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"已有采集任务运行中（{blocking_task.name}），请稍后再试",
        )
    task.status = CollectionTaskStatus.RUNNING.value
    task.current_stage = STAGE_DISCOVERY
    task.status_summary = "正在补采社媒资料（Instagram/TikTok/YouTube 反查）"
    reset_run_progress(task)
    await db.commit()
    background_tasks.add_task(_run_collection_task_in_background, task_id, resume=True)
    return _run_result_snapshot(task, message=task.status_summary)


@router.post("/bulk-run", response_model=CollectionTaskBulkRunResult)
async def bulk_run_collection_tasks(
    data: CollectionTaskBulkRun,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskBulkRunResult:
    """在并发上限内批量启动未完成任务（其余需等待空位后再运行）。"""
    product_id = require_write_product_id(ctx)
    capacity = CollectionRunnerService.collection_run_capacity()
    await CollectionRunnerService.reconcile_in_process_runs(db)
    in_process = CollectionRunnerService.active_collection_run_count()
    db_active = await CollectionTaskService.count_active_running_tasks(db)
    active_count = max(in_process, db_active)
    slots = max(0, capacity - active_count)

    started_ids: list[int] = []
    skipped_ids: list[int] = []
    skipped_reasons: dict[str, str] = {}

    for task_id in data.task_ids:
        task = await CollectionTaskService.get_task(db, task_id)
        if not task or task.product_id != product_id:
            skipped_ids.append(task_id)
            skipped_reasons[str(task_id)] = "not_found"
            continue
        ensure_task_access(task, ctx)
        stale_running = CollectionTaskService.is_running_stale(task)
        if task.status == CollectionTaskStatus.RUNNING.value and not stale_running:
            skipped_ids.append(task_id)
            skipped_reasons[str(task_id)] = "already_running"
            continue
        if slots <= 0 and not CollectionRunnerService.is_task_active_in_process(task_id):
            skipped_ids.append(task_id)
            skipped_reasons[str(task_id)] = "capacity_full"
            continue
        blocking = await CollectionTaskService.get_blocking_running_task(db, exclude_id=task_id)
        if blocking is not None and not CollectionRunnerService.is_task_active_in_process(task_id):
            skipped_ids.append(task_id)
            skipped_reasons[str(task_id)] = "capacity_full"
            continue
        if (
            CollectionRunnerService.has_active_collection_run()
            and not CollectionRunnerService.is_task_active_in_process(task_id)
        ):
            skipped_ids.append(task_id)
            skipped_reasons[str(task_id)] = "capacity_full"
            continue

        resume = task.status == CollectionTaskStatus.RUNNING.value and stale_running
        task.status = CollectionTaskStatus.RUNNING.value
        task.error_message = None
        task.last_error = None
        if resume:
            task.current_stage = task.current_stage or STAGE_DISCOVERY
        else:
            reset_run_progress(task)
        task.status_summary = (
            "检测到上次运行中断，将从 checkpoint 继续采集（跳过已完成项）"
            if resume
            else _collection_start_message(task)
        )
        await db.commit()
        background_tasks.add_task(_run_collection_task_in_background, task.id, resume=resume)
        started_ids.append(task_id)
        slots -= 1

    if started_ids and len(started_ids) == len(data.task_ids):
        message = f"已启动 {len(started_ids)} 个采集任务"
    elif started_ids:
        message = (
            f"已启动 {len(started_ids)} 个任务；"
            f"其余 {len(skipped_ids)} 个因并发上限（{capacity}）或已在运行而跳过，可稍后再试"
        )
    else:
        message = f"未启动任何任务（并发上限 {capacity}，当前活跃 {active_count}）"

    return CollectionTaskBulkRunResult(
        started_ids=started_ids,
        skipped_ids=skipped_ids,
        skipped_reasons=skipped_reasons,
        capacity=capacity,
        active_count=active_count + len(started_ids),
        message=message,
    )


@router.post("/{task_id}/run", response_model=CollectionRunResult)
async def run_collection_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionRunResult:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)

    stale_running = CollectionTaskService.is_running_stale(task)
    if task.status == CollectionTaskStatus.RUNNING.value and not stale_running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task is already running")

    blocking_task = await CollectionTaskService.get_blocking_running_task(db, exclude_id=task_id)
    if blocking_task is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务「{blocking_task.name}」正在采集中，请等待完成后再运行其他任务",
        )

    await CollectionRunnerService.reconcile_in_process_runs(db)
    if CollectionRunnerService.has_active_collection_run():
        active_ids = CollectionRunnerService.get_active_collection_task_ids()
        if task_id not in active_ids:
            active_id = CollectionRunnerService.get_active_collection_task_id()
            active_task = await CollectionTaskService.get_task(db, active_id) if active_id else None
            active_name = active_task.name if active_task else f"#{active_id}"
            capacity = CollectionRunnerService.collection_run_capacity()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"当前已有 {len(active_ids)}/{capacity} 个任务在采集中"
                    f"（例如「{active_name}」），请等待完成后再运行"
                ),
            )

    resume = task.status == CollectionTaskStatus.RUNNING.value and stale_running
    message = _collection_start_message(task)
    if resume:
        message = "检测到上次运行中断，将从 checkpoint 继续采集（跳过已完成项）"

    task.status = CollectionTaskStatus.RUNNING.value
    task.error_message = None
    task.last_error = None
    if resume:
        task.current_stage = task.current_stage or STAGE_DISCOVERY
    else:
        reset_run_progress(task)
    task.status_summary = message
    await db.commit()
    await db.refresh(task)
    background_tasks.add_task(_run_collection_task_in_background, task.id, resume=resume)
    return _run_result_snapshot(task, message=message)


@router.post("/{task_id}/send-email", response_model=EmailSendResult)
async def send_collection_task_email(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailSendResult:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)

    email_result = await EmailService.send_task_email(db, task)
    return email_result
