from __future__ import annotations

import math
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context, require_write_product_id
from app.models.link_knowledge_base import (
    LinkKnowledgeBase,
    LinkKnowledgeChunk,
    LinkScriptJob,
    LinkScriptResult,
)
from app.schemas.common import PaginatedResponse
from app.schemas.link_knowledge_base import (
    LinkKnowledgeBaseCreate,
    LinkKnowledgeBaseRead,
    LinkKnowledgeBaseUpdate,
    LinkScriptGenerateRequest,
    LinkScriptJobRead,
    LinkScriptRegenerateRequest,
    LinkScriptResultRead,
    LinkScriptResultUpdate,
)
from app.services.link_fetcher import fetch_url_content
from app.services.link_knowledge_extractor import build_chunks_from_extracted_knowledge, extract_link_knowledge
from app.services import link_script_generator
from app.services.product_influencer_service import ProductInfluencerService
from app.services.tenant_scope import ALL_PRODUCTS_ID

router = APIRouter(tags=["link-knowledge-bases"])


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please select a product first")
    return ctx.product_id


def _name_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or "Link knowledge"
    path = parsed.path.strip("/").split("/")[-1]
    return (path or host)[:255]


async def _load_base(db: AsyncSession, base_id: int, product_id: int) -> LinkKnowledgeBase:
    row = await db.get(LinkKnowledgeBase, base_id)
    if not row or row.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link knowledge base not found")
    return row


async def _read_base(db: AsyncSession, row: LinkKnowledgeBase) -> LinkKnowledgeBaseRead:
    chunks = (
        await db.scalars(
            select(LinkKnowledgeChunk)
            .where(LinkKnowledgeChunk.link_knowledge_base_id == row.id)
            .order_by(LinkKnowledgeChunk.chunk_index.asc())
        )
    ).all()
    return LinkKnowledgeBaseRead.model_validate(row).model_copy(update={"chunks": chunks})


async def _replace_chunks(db: AsyncSession, row: LinkKnowledgeBase) -> None:
    await db.execute(delete(LinkKnowledgeChunk).where(LinkKnowledgeChunk.link_knowledge_base_id == row.id))
    chunks = build_chunks_from_extracted_knowledge(row.extracted_knowledge, row.clean_text)
    for idx, chunk in enumerate(chunks):
        db.add(
            LinkKnowledgeChunk(
                link_knowledge_base_id=row.id,
                workspace_id=row.workspace_id,
                chunk_index=idx,
                chunk_type=chunk["chunk_type"],
                title=chunk.get("title"),
                content=chunk["content"],
                chunk_metadata=chunk.get("metadata") or {},
            )
        )


async def _fetch_and_parse(db: AsyncSession, row: LinkKnowledgeBase) -> None:
    row.status = "fetching"
    row.fetch_status = "running"
    row.parse_status = "pending"
    row.error_message = None
    await db.flush()
    try:
        fetched = await fetch_url_content(row.url)
        row.url = fetched["url"]
        row.domain = fetched["domain"]
        row.source_type = fetched["source_type"]
        row.raw_html = fetched["raw_html"]
        row.clean_text = fetched["clean_text"]
        row.fetch_status = "success"
        row.last_fetched_at = datetime.now(UTC)
        extracted = await extract_link_knowledge(row.clean_text or "", row.url, fetched.get("title"))
        row.extracted_knowledge = extracted
        row.summary = extracted.get("brand_summary") or extracted.get("product_summary") or row.summary
        row.parse_status = "success"
        row.status = "parsed"
        await _replace_chunks(db, row)
    except Exception as exc:
        row.status = "failed"
        row.fetch_status = "failed" if row.fetch_status == "running" else row.fetch_status
        row.parse_status = "failed"
        row.error_message = str(exc)


@router.post("/link-knowledge-bases", response_model=LinkKnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_link_knowledge_base(
    data: LinkKnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkKnowledgeBaseRead:
    product_id = data.product_id or require_write_product_id(ctx)
    if product_id != ctx.product_id and not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to product")
    url = str(data.url)
    row = LinkKnowledgeBase(
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        product_id=product_id,
        name=(data.name or _name_from_url(url)).strip(),
        url=url,
        domain=urlparse(url).netloc.lower(),
        source_type="unknown",
        status="pending",
        fetch_status="pending",
        parse_status="pending",
        tags=data.tags or [],
        is_active=True,
    )
    db.add(row)
    await db.flush()
    if data.parse_immediately:
        await _fetch_and_parse(db, row)
    await db.commit()
    await db.refresh(row)
    return await _read_base(db, row)


@router.get("/link-knowledge-bases", response_model=PaginatedResponse[LinkKnowledgeBaseRead])
async def list_link_knowledge_bases(
    product_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    domain: str | None = None,
    keyword: str | None = None,
    tag: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[LinkKnowledgeBaseRead]:
    scoped_product_id = product_id or _require_product_scope(ctx)
    query = select(LinkKnowledgeBase).where(LinkKnowledgeBase.product_id == scoped_product_id)
    if status_filter:
        query = query.where(LinkKnowledgeBase.status == status_filter)
    else:
        # 默认不展示已删除/归档项，保持列表为可维护的 CRUD 视图
        query = query.where(LinkKnowledgeBase.is_active.is_(True), LinkKnowledgeBase.status != "archived")
    if domain:
        query = query.where(LinkKnowledgeBase.domain == domain)
    if keyword:
        term = f"%{keyword}%"
        query = query.where(or_(LinkKnowledgeBase.name.ilike(term), LinkKnowledgeBase.url.ilike(term), LinkKnowledgeBase.summary.ilike(term)))
    if tag:
        query = query.where(LinkKnowledgeBase.tags.contains([tag]))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.scalars(
            query.order_by(LinkKnowledgeBase.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    items = [await _read_base(db, row) for row in rows]
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/link-knowledge-bases/{base_id}", response_model=LinkKnowledgeBaseRead)
async def get_link_knowledge_base(
    base_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkKnowledgeBaseRead:
    product_id = _require_product_scope(ctx)
    row = await _load_base(db, base_id, product_id)
    return await _read_base(db, row)


@router.patch("/link-knowledge-bases/{base_id}", response_model=LinkKnowledgeBaseRead)
async def update_link_knowledge_base(
    base_id: int,
    data: LinkKnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkKnowledgeBaseRead:
    product_id = require_write_product_id(ctx)
    row = await _load_base(db, base_id, product_id)
    payload = data.model_dump(exclude_unset=True)
    reparse = bool(payload.pop("reparse", False))
    knowledge_changed = "extracted_knowledge" in payload
    url_changed = False
    if "url" in payload and payload["url"] is not None:
        next_url = str(payload["url"])
        url_changed = next_url != row.url
        payload["url"] = next_url
        payload["domain"] = urlparse(next_url).netloc.lower()
    for field, value in payload.items():
        setattr(row, field, value)
    if knowledge_changed and not (reparse or url_changed):
        await _replace_chunks(db, row)
    if reparse or url_changed:
        await _fetch_and_parse(db, row)
    elif row.status == "failed" and (row.summary or row.extracted_knowledge):
        # 抓取失败后允许人工补齐知识，再继续生成话术
        row.status = "parsed"
        row.parse_status = "manual"
        row.error_message = None
    await db.commit()
    await db.refresh(row)
    return await _read_base(db, row)


@router.post("/link-knowledge-bases/{base_id}/refresh", response_model=LinkKnowledgeBaseRead)
async def refresh_link_knowledge_base(
    base_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkKnowledgeBaseRead:
    product_id = require_write_product_id(ctx)
    row = await _load_base(db, base_id, product_id)
    await _fetch_and_parse(db, row)
    await db.commit()
    await db.refresh(row)
    return await _read_base(db, row)


@router.delete("/link-knowledge-bases/{base_id}", response_model=LinkKnowledgeBaseRead)
async def archive_link_knowledge_base(
    base_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkKnowledgeBaseRead:
    product_id = require_write_product_id(ctx)
    row = await _load_base(db, base_id, product_id)
    row.is_active = False
    row.status = "archived"
    await db.commit()
    await db.refresh(row)
    return await _read_base(db, row)


def _job_config(payload: LinkScriptGenerateRequest | LinkScriptRegenerateRequest, base: LinkScriptJob | None = None) -> dict[str, Any]:
    return {
        "language": payload.language or (base.language if base else "en"),
        "tone": payload.tone or (base.tone if base else "friendly"),
        "collaboration_type": payload.collaboration_type or (base.collaboration_type if base else "gifted_collab"),
        "script_types": getattr(payload, "script_types", None) or (base.script_types if base else []),
        "extra_instruction": payload.extra_instruction if payload.extra_instruction is not None else (base.extra_instruction if base else None),
    }


@router.post("/link-knowledge-bases/{base_id}/generate-scripts", response_model=LinkScriptJobRead, status_code=status.HTTP_201_CREATED)
async def generate_link_scripts(
    base_id: int,
    payload: LinkScriptGenerateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkScriptJobRead:
    product_id = require_write_product_id(ctx)
    base = await _load_base(db, base_id, product_id)
    job = LinkScriptJob(
        workspace_id=ctx.workspace_id,
        link_knowledge_base_id=base.id,
        product_id=product_id,
        name=payload.name or f"{base.name} script job",
        status="running",
        total_count=len(payload.influencer_ids),
        language=payload.language,
        tone=payload.tone,
        collaboration_type=payload.collaboration_type,
        script_types=payload.script_types,
        ai_model=settings.openai_model if settings.is_openai_configured else None,
        extra_instruction=payload.extra_instruction,
    )
    db.add(job)
    await db.flush()
    config = _job_config(payload)
    for influencer_id in payload.influencer_ids:
        pair = await ProductInfluencerService.get_product_influencer(db, product_id=product_id, record_id=influencer_id)
        if not pair:
            job.failed_count += 1
            db.add(
                LinkScriptResult(
                    workspace_id=ctx.workspace_id,
                    job_id=job.id,
                    link_knowledge_base_id=base.id,
                    influencer_id=influencer_id,
                    status="failed",
                    error_message="Influencer not found",
                )
            )
            continue
        product_row, global_row = pair
        result = LinkScriptResult(
            workspace_id=ctx.workspace_id,
            job_id=job.id,
            link_knowledge_base_id=base.id,
            influencer_id=product_row.id,
            platform=global_row.platform,
            profile_url=global_row.profile_url,
            influencer_name=global_row.display_name,
            influencer_handle=global_row.username,
            status="generating",
        )
        db.add(result)
        await db.flush()
        try:
            generated, snapshot = await link_script_generator.generate_scripts_for_influencer(
                db, base, product_row, global_row, config
            )
            result.generated_content = generated
            result.input_snapshot = snapshot
            result.status = "completed"
            job.success_count += 1
        except Exception as exc:
            result.status = "failed"
            result.error_message = str(exc)
            job.failed_count += 1
    job.status = "completed" if job.failed_count == 0 else ("failed" if job.success_count == 0 else "partial_failed")
    job.completed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    return LinkScriptJobRead.model_validate(job)


@router.get("/link-script-jobs", response_model=PaginatedResponse[LinkScriptJobRead])
async def list_link_script_jobs(
    link_knowledge_base_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[LinkScriptJobRead]:
    product_id = _require_product_scope(ctx)
    query = select(LinkScriptJob).where(LinkScriptJob.product_id == product_id)
    if link_knowledge_base_id:
        query = query.where(LinkScriptJob.link_knowledge_base_id == link_knowledge_base_id)
    if status_filter:
        query = query.where(LinkScriptJob.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.scalars(query.order_by(LinkScriptJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).all()
    return PaginatedResponse(
        items=[LinkScriptJobRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/link-script-jobs/{job_id}", response_model=LinkScriptJobRead)
async def get_link_script_job(job_id: int, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)) -> LinkScriptJobRead:
    product_id = _require_product_scope(ctx)
    job = await db.get(LinkScriptJob, job_id)
    if not job or job.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return LinkScriptJobRead.model_validate(job)


@router.get("/link-script-jobs/{job_id}/results", response_model=PaginatedResponse[LinkScriptResultRead])
async def list_link_script_results(
    job_id: int,
    status_filter: str | None = Query(default=None, alias="status"),
    platform: str | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[LinkScriptResultRead]:
    product_id = _require_product_scope(ctx)
    job = await db.get(LinkScriptJob, job_id)
    if not job or job.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    query = select(LinkScriptResult).where(LinkScriptResult.job_id == job_id)
    if status_filter:
        query = query.where(LinkScriptResult.status == status_filter)
    if platform:
        query = query.where(LinkScriptResult.platform == platform)
    if keyword:
        term = f"%{keyword}%"
        query = query.where(or_(LinkScriptResult.influencer_name.ilike(term), LinkScriptResult.influencer_handle.ilike(term)))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.scalars(query.order_by(LinkScriptResult.id.asc()).offset((page - 1) * page_size).limit(page_size))
    ).all()
    return PaginatedResponse(
        items=[LinkScriptResultRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


async def _load_result(db: AsyncSession, result_id: int, product_id: int) -> tuple[LinkScriptResult, LinkScriptJob, LinkKnowledgeBase]:
    result = await db.get(LinkScriptResult, result_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    job = await db.get(LinkScriptJob, result.job_id)
    base = await db.get(LinkKnowledgeBase, result.link_knowledge_base_id)
    if not job or not base or job.product_id != product_id or base.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    return result, job, base


@router.get("/link-script-results/{result_id}", response_model=LinkScriptResultRead)
async def get_link_script_result(result_id: int, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)) -> LinkScriptResultRead:
    result, _job, _base = await _load_result(db, result_id, _require_product_scope(ctx))
    return LinkScriptResultRead.model_validate(result)


@router.patch("/link-script-results/{result_id}", response_model=LinkScriptResultRead)
async def update_link_script_result(
    result_id: int,
    payload: LinkScriptResultUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkScriptResultRead:
    result, _job, _base = await _load_result(db, result_id, require_write_product_id(ctx))
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(result, field, value)
    await db.commit()
    await db.refresh(result)
    return LinkScriptResultRead.model_validate(result)


@router.post("/link-script-results/{result_id}/regenerate", response_model=LinkScriptResultRead)
async def regenerate_link_script_result(
    result_id: int,
    payload: LinkScriptRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> LinkScriptResultRead:
    result, job, base = await _load_result(db, result_id, require_write_product_id(ctx))
    pair = await ProductInfluencerService.get_product_influencer(db, product_id=job.product_id or ctx.product_id, record_id=result.influencer_id)
    if not pair:
        result.status = "failed"
        result.error_message = "Influencer not found"
    else:
        product_row, global_row = pair
        config = _job_config(payload, job)
        try:
            generated, snapshot = await link_script_generator.generate_scripts_for_influencer(
                db, base, product_row, global_row, config
            )
            result.generated_content = generated
            result.input_snapshot = snapshot
            result.status = "completed"
            result.error_message = None
        except Exception as exc:
            result.status = "failed"
            result.error_message = str(exc)
    await db.commit()
    await db.refresh(result)
    return LinkScriptResultRead.model_validate(result)


@router.get("/link-script-jobs/{job_id}/export")
async def export_link_script_job(job_id: int, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)) -> StreamingResponse:
    product_id = _require_product_scope(ctx)
    job = await db.get(LinkScriptJob, job_id)
    if not job or job.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    rows = (
        await db.scalars(select(LinkScriptResult).where(LinkScriptResult.job_id == job_id).order_by(LinkScriptResult.id.asc()))
    ).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "link scripts"
    headers = [
        "influencer_name",
        "influencer_handle",
        "platform",
        "profile_url",
        "match_reason",
        "email_subjects",
        "email_first_touch",
        "instagram_dm",
        "follow_up_1",
        "follow_up_2",
        "status",
        "error_message",
    ]
    ws.append(headers)
    for row in rows:
        content = row.used_content or row.edited_content or row.generated_content or {}
        ws.append(
            [
                row.influencer_name,
                row.influencer_handle,
                row.platform,
                row.profile_url,
                content.get("match_reason"),
                "\n".join(str(item) for item in content.get("email_subjects", []) if item),
                content.get("email_first_touch"),
                content.get("instagram_dm"),
                content.get("follow_up_1"),
                content.get("follow_up_2"),
                row.status,
                row.error_message,
            ]
        )
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f"link-script-job-{job_id}.xlsx"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
