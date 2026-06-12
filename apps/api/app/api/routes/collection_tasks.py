import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory, get_db
from app.deps.tenant import TenantContext, get_tenant_context, resolve_write_product_id
from app.services.tenant_scope import scoped_product_id
from app.services.task_access import ensure_task_access
from app.models.enums import CollectionTaskStatus
from app.schemas.email import EmailSendResult
from app.schemas.collection_task import (
    CollectionTaskCandidateFilter,
    CollectionTaskCandidateRead,
    CollectionTaskCreate,
    CollectionTaskFilter,
    CollectionTaskRead,
    CollectionRunResult,
    CollectionTaskUpdate,
)
from app.schemas.common import PaginatedResponse
from app.services.export import build_collection_task_candidates_excel
from app.services.task_candidate import TaskCandidateService
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
    )


@router.get("", response_model=PaginatedResponse[CollectionTaskRead])
async def list_collection_tasks(
    platform: str | None = None,
    status: CollectionTaskStatus | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[CollectionTaskRead]:
    filters = CollectionTaskFilter(
        product_id=scoped_product_id(ctx.product_id), platform=platform, status=status, search=search
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
        product_id=await resolve_write_product_id(db, ctx),
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


@router.get("/{task_id}", response_model=CollectionTaskRead)
async def get_collection_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> CollectionTaskRead:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    return CollectionTaskService.task_read(task)


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


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    task = ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    try:
        await CollectionTaskService.delete_task(db, task)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await refresh_scheduler()


@router.get("/{task_id}/candidates", response_model=PaginatedResponse[CollectionTaskCandidateRead])
async def list_collection_task_candidates(
    task_id: int,
    status: str | None = Query(default=None),
    failure_reason: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source_discovery_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[CollectionTaskCandidateRead]:
    ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)
    result = await TaskCandidateService.list_for_task(
        db,
        task_id,
        page=page,
        page_size=page_size,
        status=status,
        failure_reason=failure_reason,
        source_type=source_type,
        source_discovery_type=source_discovery_type,
        search=search,
    )
    return PaginatedResponse(
        items=[CollectionTaskCandidateRead.model_validate(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.get("/{task_id}/candidates/export")
async def export_collection_task_candidates(
    task_id: int,
    status: str | None = Query(default=None),
    failure_reason: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source_discovery_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> StreamingResponse:
    ensure_task_access(await CollectionTaskService.get_task(db, task_id), ctx)

    rows = await TaskCandidateService.list_for_export(
        db,
        task_id,
        product_id=ctx.product_id,
        status=status,
        failure_reason=failure_reason,
        source_type=source_type,
        source_discovery_type=source_discovery_type,
        search=search,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="没有符合筛选条件的候选数据，无法导出。请调整筛选条件后重试。",
        )

    content, filename = build_collection_task_candidates_excel(rows, task_id=task_id)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
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

    if CollectionRunnerService.has_active_collection_run():
        active_id = CollectionRunnerService.get_active_collection_task_id()
        if active_id is not None and active_id != task_id:
            active_task = await CollectionTaskService.get_task(db, active_id)
            active_name = active_task.name if active_task else f"#{active_id}"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"任务「{active_name}」正在采集中，请等待完成后再运行其他任务",
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
