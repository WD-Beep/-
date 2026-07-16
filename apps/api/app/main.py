from contextlib import asynccontextmanager
from datetime import UTC, datetime
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import api_router
from app.core.config import settings
from app.db.session import async_session_factory
from app.scheduler import scheduler_manager
from app.services.collection_queue import CollectionQueueService
from app.services.collection_task import CollectionTaskService
from app.workers.collection_worker_pool import start_embedded_worker_pool, stop_embedded_worker_pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_manager.start()
    worker_count = 0
    try:
        async with async_session_factory() as db:
            reconciled = await CollectionTaskService.reconcile_stale_running_tasks(db)
            if reconciled:
                logger.info("Reconciled %s stale running collection task(s) on startup", reconciled)
            started = await CollectionQueueService.dispatch_queued_tasks(db=db)
            if started:
                logger.info("Dispatched %s queued collection task(s) on startup", started)
        refresh_result = await scheduler_manager.refresh()
        logger.info(
            "Scheduler initialized: registered=%s skipped=%s",
            refresh_result.registered,
            refresh_result.skipped,
        )
        worker_count = start_embedded_worker_pool()
        logger.info(
            "Collection concurrency: global=%s per_user=%s per_platform=%s workers=%s",
            settings.collection_max_running_tasks,
            settings.collection_max_concurrency_per_user,
            settings.collection_max_concurrency_per_platform,
            worker_count,
        )
    except Exception as exc:
        logger.exception("Scheduler refresh on startup failed: %s", exc)

    yield

    await stop_embedded_worker_pool()
    scheduler_manager.shutdown()


app = FastAPI(
    title="Influencer Intel API",
    description="海外红人数据采集与管理系统 API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = " → ".join(str(part) for part in err.get("loc", []))
        errors.append(f"{loc}: {err.get('msg', 'invalid')}")
    return JSONResponse(
        status_code=422,
        content={"detail": "；".join(errors) or "请求参数无效"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试或查看 API 日志"},
    )


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "influencer-intel-api",
        "timestamp": datetime.now(UTC).isoformat(),
    }
