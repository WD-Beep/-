# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：collection tasks
import logging
from datetime import UTC, datetime, timedelta

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
from app.services.collection_runner import CollectionRunCapacityError, CollectionRunnerService
from app.services.collection_task import CollectionTaskService
from app.services.collection_queue import CollectionQueueService
from app.services.collection_queue import QUEUE_REASON_GLOBAL_FULL
from app.services.email import EmailService

router = APIRouter(prefix="/collection-tasks", tags=["collection-tasks"])
logger = logging.getLogger(__name__)


async def _start_next_batch_child(
    parent: CollectionTask,
    background_tasks: BackgroundTasks | None,
    db: AsyncSession,
    *,
    resume_paused: bool = False,
) -> CollectionTaskStatus | None:
    child = (
        await CollectionTaskService.paused_batch_child_to_resume(db, parent.id)
        if resume_paused
        else None
    )
    if child is None:
        child = await CollectionTaskService.next_batch_child_to_run(db, parent.id)
    if child is None:
        await CollectionTaskService.refresh_batch_parent_state(db, parent)
        return None
    parent_checkpoint = dict(parent.run_checkpoint or {})
    if parent_checkpoint.get("stopped") or parent_checkpoint.get("stop_requested"):
        return None
    deadline_text = parent_checkpoint.get("runtime_deadline_at")
    if not deadline_text:
        now = datetime.now(UTC)
        deadline_text = (now + timedelta(minutes=int(parent.max_runtime_minutes or 60))).isoformat()
        parent_checkpoint["runtime_started_at"] = now.isoformat()
        parent_checkpoint["runtime_deadline_at"] = deadline_text
        parent.run_checkpoint = parent_checkpoint
    child_checkpoint = dict(child.run_checkpoint or {})
    child_checkpoint["runtime_started_at"] = parent_checkpoint.get("runtime_started_at")
    child_checkpoint["runtime_deadline_at"] = deadline_text
    child.run_checkpoint = child_checkpoint
    await db.commit()
    stale_running = CollectionTaskService.is_running_stale(child)
    resume = child.status == CollectionTaskStatus.PAUSED.value or (
        child.status == CollectionTaskStatus.RUNNING.value and stale_running
    )
    active_resume = (
        child.status == CollectionTaskStatus.PAUSED.value
        and CollectionRunnerService.is_task_active_in_process(child.id)
    )
    if child.status == CollectionTaskStatus.PAUSED.value:
        CollectionTaskService.prepare_paused_task_for_resume(child)
    if active_resume:
        child.status = CollectionTaskStatus.RUNNING.value
        await db.commit()
        await db.refresh(child)
        result_status = CollectionTaskStatus.RUNNING
    else:
        result_status = await CollectionQueueService.queue_or_start(db, child, resume=resume)
    await CollectionTaskService.refresh_batch_parent_state(db, parent)
    if result_status == CollectionTaskStatus.RUNNING and not active_resume:
        if background_tasks is not None:
            background_tasks.add_task(_run_collection_task_in_background, child.id, resume=resume)
        else:
            await CollectionQueueService.start_background(child.id, resume=resume)
    return result_status


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
        if (task.run_checkpoint or {}).get("stopped"):
            return
        try:
            await CollectionRunnerService.run_task_with_timeout(bg_db, task, allow_running=True, resume=resume)
        except CollectionRunCapacityError as exc:
            logger.warning("Background collection task %s returned to queue: %s", task_id, exc)
            await CollectionQueueService.restore_task_to_queue(
                bg_db,
                task,
                reasons=[QUEUE_REASON_GLOBAL_FULL],
                resume=resume,
            )
        except Exception as exc:
            logger.exception("Background collection task %s failed: %s", task_id, exc)
        finally:
            if task.parent_task_id:
                parent = await CollectionTaskService.get_task(bg_db, task.parent_task_id)
                if parent:
                    try:
                        checkpoint = dict(parent.run_checkpoint or {})
                        if not checkpoint.get("stopped") and not checkpoint.get("stop_requested"):
                            await _start_next_batch_child(parent, None, bg_db)
                    except Exception as exc:
                        logger.exception("Failed to continue batch parent %s after child %s: %s", parent.id, task_id, exc)
            await CollectionQueueService.dispatch_queued_tasks()


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
        collection_max_concurrency_per_user=max(1, settings.collection_max_concurrency_per_user),
        collection_max_concurrency_per_platform=max(1, settings.collection_max_concurrency_per_platform),
        collection_worker_count=max(0, settings.collection_worker_count),
        collection_profile_enrich_concurrency=settings.effective_profile_enrich_concurrency,
        collection_profile_request_timeout_seconds=max(5, settings.collection_profile_request_timeout_seconds),
        collection_running_stale_seconds=max(30, settings.collection_running_stale_seconds),
    )


@router.get("/concurrency-status")
async def get_collection_concurrency_status(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    await CollectionTaskService.reconcile_stale_running_tasks(db)
    overview = await CollectionQueueService.concurrency_overview(db, current_user_id=ctx.user_id)
    return overview


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
        if task.parent_task_id is not None:
            continue
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
    try:
        updated = await CollectionTaskService.update_task(db, task, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
    result_status = await CollectionQueueService.queue_or_start(db, task, resume=True)
    if result_status == CollectionTaskStatus.RUNNING:
        task.status_summary = "正在补采社媒资料（Instagram/TikTok/YouTube 反查）"
        await db.commit()
        await db.refresh(task)
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
    started_ids: list[int] = []
    queued_ids: list[int] = []
    skipped_ids: list[int] = []
    skipped_reasons: dict[str, str] = {}

    for task_id in data.task_ids:
        task = await CollectionTaskService.get_task(db, task_id)
        if not task or task.product_id != product_id:
            skipped_ids.append(task_id)
            skipped_reasons[str(task_id)] = "not_found"
            continue
        ensure_task_access(task, ctx)
        if CollectionTaskService._is_batch_parent(task):
            result_status = await _start_next_batch_child(task, background_tasks, db)
            if result_status == CollectionTaskStatus.RUNNING:
                started_ids.append(task_id)
            elif result_status == CollectionTaskStatus.QUEUED:
                queued_ids.append(task_id)
            else:
                skipped_ids.append(task_id)
                skipped_reasons[str(task_id)] = "batch_completed"
            continue
        stale_running = CollectionTaskService.is_running_stale(task)
        if task.status == CollectionTaskStatus.RUNNING.value and not stale_running:
            skipped_ids.append(task_id)
            skipped_reasons[str(task_id)] = "already_running"
            continue
        if task.status == CollectionTaskStatus.QUEUED.value:
            queued_ids.append(task_id)
            skipped_reasons[str(task_id)] = "already_queued"
            continue
        resume = task.status == CollectionTaskStatus.RUNNING.value and stale_running
        result_status = await CollectionQueueService.queue_or_start(db, task, resume=resume)
        if result_status == CollectionTaskStatus.RUNNING:
            background_tasks.add_task(_run_collection_task_in_background, task.id, resume=resume)
            started_ids.append(task_id)
        else:
            queued_ids.append(task_id)

    active_count = CollectionRunnerService.active_collection_run_count()
    parts: list[str] = []
    if started_ids:
        parts.append(f"已启动 {len(started_ids)} 个采集任务")
    if queued_ids:
        parts.append(f"已排队 {len(queued_ids)} 个任务，等待空位")
    if skipped_ids:
        parts.append(f"跳过 {len(skipped_ids)} 个任务")
    message = "；".join(parts) if parts else f"未启动任何任务（并发上限 {capacity}）"
    return CollectionTaskBulkRunResult(
        started_ids=started_ids,
        queued_ids=queued_ids,
        skipped_ids=skipped_ids,
        skipped_reasons=skipped_reasons,
        capacity=capacity,
        active_count=active_count,
        message=message,
    )


@router.post("/{task_id}/run-batch", response_model=CollectionTaskBulkRunResult)
async def run_collection_task_batch(
    task_id: int,
    background_tasks: BackgroundTasks,
    failed_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskBulkRunResult:
    parent = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    if not CollectionTaskService._is_batch_parent(parent):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="not_batch_parent_task")
    children = await CollectionTaskService.get_batch_children(db, parent.id)
    if failed_only:
        failed_statuses = {
            CollectionTaskStatus.FAILED.value,
            CollectionTaskStatus.PARTIAL_FAILED.value,
        }
        children = [child for child in children if child.status in failed_statuses]
    if not children:
        return CollectionTaskBulkRunResult(
            capacity=CollectionRunnerService.collection_run_capacity(),
            active_count=CollectionRunnerService.active_collection_run_count(),
            message="没有可运行的批次轮次",
        )
    payload = CollectionTaskBulkRun(task_ids=[child.id for child in children])
    return await bulk_run_collection_tasks(payload, background_tasks, db, ctx)


@router.post("/{task_id}/run", response_model=CollectionRunResult)
async def run_collection_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionRunResult:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    if CollectionTaskService._is_batch_parent(task):
        result_status = await _start_next_batch_child(task, background_tasks, db)
        await db.refresh(task)
        message = task.status_summary or "多轮采集已启动"
        if result_status is None:
            message = task.status_summary or "多轮采集已完成"
        return _run_result_snapshot(task, message=message)

    stale_running = CollectionTaskService.is_running_stale(task)
    if task.status == CollectionTaskStatus.RUNNING.value and not stale_running:
        return _run_result_snapshot(task, message=task.status_summary or "Task is already running")
    if task.status == CollectionTaskStatus.QUEUED.value:
        await CollectionQueueService.dispatch_queued_tasks()
        await db.refresh(task)
        return _run_result_snapshot(task, message=task.status_summary or "Task is already queued")

    resume = task.status == CollectionTaskStatus.RUNNING.value and stale_running
    result_status = await CollectionQueueService.queue_or_start(db, task, resume=resume)
    if result_status == CollectionTaskStatus.RUNNING:
        background_tasks.add_task(_run_collection_task_in_background, task.id, resume=resume)
    elif result_status == CollectionTaskStatus.QUEUED:
        await CollectionQueueService.dispatch_queued_tasks()
    return _run_result_snapshot(task, message=task.status_summary)


@router.post("/{task_id}/pause", response_model=CollectionTaskRead)
async def pause_collection_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskRead:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    try:
        paused = await CollectionTaskService.pause_task(db, task)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    parent_task_id = getattr(paused, "parent_task_id", None)
    if parent_task_id:
        parent = await CollectionTaskService.get_task(db, parent_task_id)
        if parent:
            await CollectionTaskService.refresh_batch_parent_state(db, parent)
    await CollectionQueueService.dispatch_queued_tasks()
    return CollectionTaskService.task_read(paused)


@router.post("/{task_id}/stop", response_model=CollectionTaskRead)
async def stop_collection_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskRead:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    active_statuses = {
        CollectionTaskStatus.RUNNING.value,
        CollectionTaskStatus.QUEUED.value,
        CollectionTaskStatus.PAUSED.value,
    }
    children = (
        await CollectionTaskService.get_batch_children(db, task.id)
        if CollectionTaskService._is_batch_parent(task)
        else []
    )
    if task.status not in active_statuses and not any(child.status in active_statuses for child in children):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="任务当前不在采集中")
    active_ids = await CollectionTaskService.request_stop(db, task)
    for active_id in active_ids:
        await CollectionRunnerService.cancel_active_task(active_id)
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    stopped = await CollectionTaskService.stop_task_and_preserve(
        db,
        task,
        reason="用户手动停止采集",
    )
    await CollectionQueueService.dispatch_queued_tasks()
    return CollectionTaskService.task_read(stopped)


@router.post("/{task_id}/resume", response_model=CollectionRunResult)
async def resume_collection_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionRunResult:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    if CollectionTaskService._is_batch_parent(task):
        result_status = await _start_next_batch_child(
            task,
            background_tasks,
            db,
            resume_paused=True,
        )
        await db.refresh(task)
        message = task.status_summary or "Batch collection resumed from the paused round."
        if result_status is None:
            message = task.status_summary or "No paused batch round to resume."
        return _run_result_snapshot(task, message=message)

    try:
        CollectionTaskService.prepare_paused_task_for_resume(task)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if CollectionRunnerService.is_task_active_in_process(task.id):
        task.status = CollectionTaskStatus.RUNNING.value
        await db.commit()
        await db.refresh(task)
        return _run_result_snapshot(task, message=task.status_summary)
    result_status = await CollectionQueueService.queue_or_start(db, task, resume=True)
    if result_status == CollectionTaskStatus.RUNNING:
        background_tasks.add_task(_run_collection_task_in_background, task.id, resume=True)
    return _run_result_snapshot(task, message=task.status_summary)


@router.post("/{task_id}/send-email", response_model=EmailSendResult)
async def send_collection_task_email(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> EmailSendResult:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)

    email_result = await EmailService.send_task_email(db, task)
    return email_result
