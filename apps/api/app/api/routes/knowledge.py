# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：knowledge
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context, require_write_product_id
from app.models.knowledge import KnowledgeDocument
from app.schemas.common import PaginatedResponse
from app.schemas.knowledge import (
    KnowledgeBaseCreate,
    KnowledgeBaseRead,
    KnowledgeChunkRead,
    KnowledgeDocumentImportRequest,
    KnowledgeDocumentRead,
    KnowledgeImportPreset,
    KnowledgeSearchResult,
    ScriptRecommendRequest,
    ScriptRecommendResponse,
)
from app.services.knowledge.knowledge_service import KnowledgeService
from app.services.knowledge.search_service import KnowledgeSearchService
from app.services.product_influencer_service import ProductInfluencerService
from app.services.speech_recommendation_service import SpeechRecommendationService
from app.services.tenant_scope import ALL_PRODUCTS_ID

router = APIRouter(tags=["knowledge"])


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择具体产品/品牌后再操作知识库",
        )
    return ctx.product_id


def _ensure_document_access(row: KnowledgeDocument, product_id: int) -> None:
    if row.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")


@router.get("/knowledge-bases", response_model=list[KnowledgeBaseRead])
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[KnowledgeBaseRead]:
    product_id = _require_product_scope(ctx)
    return await KnowledgeService.list_bases(db, product_id=product_id)


@router.post("/knowledge-bases", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> KnowledgeBaseRead:
    product_id = require_write_product_id(ctx)
    return await KnowledgeService.create_base(db, data, ctx=ctx, product_id=product_id)


@router.get("/knowledge-documents", response_model=PaginatedResponse[KnowledgeDocumentRead])
async def list_knowledge_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    knowledge_base_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[KnowledgeDocumentRead]:
    product_id = _require_product_scope(ctx)
    return await KnowledgeService.list_documents(
        db,
        product_id=product_id,
        knowledge_base_id=knowledge_base_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/knowledge-documents/{document_id}/chunks",
    response_model=PaginatedResponse[KnowledgeChunkRead],
)
async def list_knowledge_document_chunks(
    document_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[KnowledgeChunkRead]:
    product_id = _require_product_scope(ctx)
    row = await KnowledgeService.get_document(db, document_id=document_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return await KnowledgeService.list_chunks(
        db,
        document_id=document_id,
        product_id=product_id,
        page=page,
        page_size=page_size,
    )


@router.post("/knowledge-documents/upload", response_model=KnowledgeDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    knowledge_base_id: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> KnowledgeDocumentRead:
    product_id = require_write_product_id(ctx)
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少文件名")

    import tempfile
    from pathlib import Path

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".pptx"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 PDF 与 PPTX 文件")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        return await KnowledgeService.create_document_from_path(
            db,
            ctx=ctx,
            product_id=product_id,
            file_path=tmp_path,
            knowledge_base_id=knowledge_base_id,
            is_upload=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/knowledge-documents/import-presets", response_model=list[KnowledgeImportPreset])
async def list_knowledge_import_presets() -> list[KnowledgeImportPreset]:
    presets: list[KnowledgeImportPreset] = []
    for preset_id, label, path_value in (
        ("scandihome-pdf", "ScandiHome 视觉手册 (PDF)", settings.scandihome_pdf_path),
        ("scandihome-pptx", "ScandiHome 视觉升级 (PPTX)", settings.scandihome_pptx_path),
    ):
        normalized = path_value.strip()
        if not normalized:
            continue
        presets.append(
            KnowledgeImportPreset(
                id=preset_id,
                label=label,
                file_path=normalized,
                available=Path(normalized).expanduser().is_file(),
            )
        )
    return presets


@router.post("/knowledge-documents/import", response_model=KnowledgeDocumentRead, status_code=status.HTTP_201_CREATED)
async def import_knowledge_document(
    data: KnowledgeDocumentImportRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> KnowledgeDocumentRead:
    product_id = require_write_product_id(ctx)
    try:
        return await KnowledgeService.create_document_from_path(
            db,
            ctx=ctx,
            product_id=product_id,
            file_path=data.file_path,
            knowledge_base_id=data.knowledge_base_id,
            is_upload=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/knowledge-documents/{document_id}/reprocess", response_model=KnowledgeDocumentRead)
async def reprocess_knowledge_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> KnowledgeDocumentRead:
    product_id = require_write_product_id(ctx)
    row = await KnowledgeService.get_document(db, document_id=document_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    try:
        return await KnowledgeService.reprocess_document(db, row)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.delete("/knowledge-documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    product_id = require_write_product_id(ctx)
    row = await KnowledgeService.get_document(db, document_id=document_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    await KnowledgeService.delete_document(db, row)


@router.get("/knowledge-search", response_model=list[KnowledgeSearchResult])
async def search_knowledge(
    q: str = Query(min_length=1),
    knowledge_base_id: int | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[KnowledgeSearchResult]:
    product_id = _require_product_scope(ctx)
    return await KnowledgeSearchService.search(
        db,
        product_id=product_id,
        query=q,
        knowledge_base_id=knowledge_base_id,
        limit=limit,
    )


@router.post("/scripts/recommend", response_model=ScriptRecommendResponse)
async def recommend_script(
    payload: ScriptRecommendRequest,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> ScriptRecommendResponse:
    product_id = _require_product_scope(ctx)
    pair = await ProductInfluencerService.get_product_influencer(
        db, product_id=product_id, record_id=payload.influencer_id
    )
    if not pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="红人不存在")
    product_row, global_row = pair
    return await SpeechRecommendationService.recommend(
        db,
        product_id=product_id,
        global_row=global_row,
        product_row=product_row,
        payload=payload,
    )
