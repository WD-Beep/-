# 文件说明：后端知识库服务，负责资料解析、保存和检索；当前文件：knowledge service
from __future__ import annotations

import math
import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.tenant import TenantContext
from app.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.schemas.common import PaginatedResponse
from app.schemas.knowledge import (
    KnowledgeBaseCreate,
    KnowledgeBaseRead,
    KnowledgeChunkRead,
    KnowledgeDocumentRead,
)
from app.services.knowledge.document_parser import parse_document

UPLOAD_ROOT = Path(__file__).resolve().parents[3] / "data" / "knowledge_uploads"


def _ensure_upload_root() -> Path:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    return UPLOAD_ROOT


def _detect_file_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix in {"pdf", "pptx"}:
        return suffix
    raise ValueError(f"不支持的文件类型: .{suffix or 'unknown'}")


class KnowledgeService:
    @staticmethod
    async def _count_documents(db: AsyncSession, knowledge_base_id: int) -> int:
        return (
            await db.scalar(
                select(func.count())
                .select_from(KnowledgeDocument)
                .where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
            )
            or 0
        )

    @staticmethod
    async def _count_chunks_for_base(db: AsyncSession, knowledge_base_id: int) -> int:
        return (
            await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.knowledge_base_id == knowledge_base_id)
            )
            or 0
        )

    @staticmethod
    async def _count_chunks_for_document(db: AsyncSession, document_id: int) -> int:
        return (
            await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document_id)
            )
            or 0
        )

    @staticmethod
    async def _to_base_read(db: AsyncSession, row: KnowledgeBase) -> KnowledgeBaseRead:
        doc_count = await KnowledgeService._count_documents(db, row.id)
        chunk_count = await KnowledgeService._count_chunks_for_base(db, row.id)
        data = KnowledgeBaseRead.model_validate(row)
        data.document_count = doc_count
        data.chunk_count = chunk_count
        return data

    @staticmethod
    async def _to_document_read(db: AsyncSession, row: KnowledgeDocument) -> KnowledgeDocumentRead:
        chunk_count = await KnowledgeService._count_chunks_for_document(db, row.id)
        data = KnowledgeDocumentRead.model_validate(row)
        data.chunk_count = chunk_count
        return data

    @staticmethod
    async def list_bases(db: AsyncSession, *, product_id: int) -> list[KnowledgeBaseRead]:
        result = await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.product_id == product_id)
            .order_by(KnowledgeBase.updated_at.desc())
        )
        rows = result.scalars().all()
        return [await KnowledgeService._to_base_read(db, row) for row in rows]

    @staticmethod
    async def get_base(
        db: AsyncSession,
        *,
        knowledge_base_id: int,
        product_id: int,
    ) -> KnowledgeBase | None:
        result = await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_base(
        db: AsyncSession,
        data: KnowledgeBaseCreate,
        *,
        ctx: TenantContext,
        product_id: int,
    ) -> KnowledgeBaseRead:
        row = KnowledgeBase(
            workspace_id=ctx.workspace_id,
            product_id=product_id,
            name=data.name.strip(),
            description=(data.description or "").strip() or None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return await KnowledgeService._to_base_read(db, row)

    @staticmethod
    async def get_or_create_default_base(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        product_id: int,
    ) -> KnowledgeBase:
        result = await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.product_id == product_id)
            .order_by(KnowledgeBase.created_at.asc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            return row
        row = KnowledgeBase(
            workspace_id=ctx.workspace_id,
            product_id=product_id,
            name="默认知识库",
            description="品牌资料与视觉手册",
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def list_documents(
        db: AsyncSession,
        *,
        product_id: int,
        knowledge_base_id: int | None,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[KnowledgeDocumentRead]:
        base = select(KnowledgeDocument).where(KnowledgeDocument.product_id == product_id)
        if knowledge_base_id:
            base = base.where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
        total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
        result = await db.execute(
            base.order_by(KnowledgeDocument.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [
            await KnowledgeService._to_document_read(db, row) for row in result.scalars().all()
        ]
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def get_document(
        db: AsyncSession,
        *,
        document_id: int,
        product_id: int,
    ) -> KnowledgeDocument | None:
        result = await db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_chunks(
        db: AsyncSession,
        *,
        document_id: int,
        product_id: int,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[KnowledgeChunkRead]:
        base = select(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document_id,
            KnowledgeChunk.product_id == product_id,
        )
        total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
        result = await db.execute(
            base.order_by(KnowledgeChunk.chunk_index.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = []
        for row in result.scalars().all():
            items.append(
                KnowledgeChunkRead(
                    id=row.id,
                    document_id=row.document_id,
                    knowledge_base_id=row.knowledge_base_id,
                    product_id=row.product_id,
                    chunk_index=row.chunk_index,
                    title=row.title,
                    content=row.content,
                    metadata=dict(row.chunk_metadata or {}),
                    created_at=row.created_at,
                )
            )
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def _store_upload_copy(source: Path, *, product_id: int, file_name: str) -> Path:
        upload_root = _ensure_upload_root() / str(product_id)
        upload_root.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}_{Path(file_name).name}"
        target = upload_root / safe_name
        shutil.copy2(source, target)
        return target

    @staticmethod
    async def create_document_from_path(
        db: AsyncSession,
        *,
        ctx: TenantContext,
        product_id: int,
        file_path: str,
        knowledge_base_id: int | None = None,
        is_upload: bool = False,
    ) -> KnowledgeDocumentRead:
        source = Path(file_path).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"文件不存在: {source}")

        base = await KnowledgeService.get_or_create_default_base(db, ctx=ctx, product_id=product_id)
        if knowledge_base_id:
            selected = await KnowledgeService.get_base(
                db, knowledge_base_id=knowledge_base_id, product_id=product_id
            )
            if not selected:
                raise ValueError("知识库不存在")
            base = selected

        file_type = _detect_file_type(source.name)
        stored_path = await KnowledgeService._store_upload_copy(
            source, product_id=product_id, file_name=source.name
        )

        row = KnowledgeDocument(
            knowledge_base_id=base.id,
            workspace_id=ctx.workspace_id,
            product_id=product_id,
            file_name=source.name,
            file_type=file_type,
            source_path=None if is_upload else str(source),
            uploaded_file_path=str(stored_path),
            status="processing",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        try:
            await KnowledgeService._process_document(db, row, stored_path)
        except Exception as exc:
            row.status = "failed"
            row.error_message = str(exc)[:2000]
            await db.commit()
            await db.refresh(row)
            raise

        return await KnowledgeService._to_document_read(db, row)

    @staticmethod
    async def _process_document(
        db: AsyncSession,
        row: KnowledgeDocument,
        file_path: Path,
    ) -> None:
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == row.id))
        row.status = "processing"
        row.error_message = None
        await db.commit()

        sections = parse_document(file_path)
        if not sections:
            raise ValueError("未能从文档中提取到有效文本")

        for index, section in enumerate(sections):
            db.add(
                KnowledgeChunk(
                    document_id=row.id,
                    knowledge_base_id=row.knowledge_base_id,
                    workspace_id=row.workspace_id,
                    product_id=row.product_id,
                    chunk_index=index,
                    title=section.title,
                    content=section.content,
                    chunk_metadata=section.metadata,
                )
            )

        row.status = "ready"
        row.error_message = None
        await db.commit()
        await db.refresh(row)

    @staticmethod
    async def reprocess_document(
        db: AsyncSession,
        row: KnowledgeDocument,
    ) -> KnowledgeDocumentRead:
        file_path = Path(row.uploaded_file_path or row.source_path or "")
        if not file_path.exists():
            raise FileNotFoundError("文档文件不存在，请重新上传")
        try:
            await KnowledgeService._process_document(db, row, file_path)
        except Exception as exc:
            row.status = "failed"
            row.error_message = str(exc)[:2000]
            await db.commit()
            await db.refresh(row)
            raise
        return await KnowledgeService._to_document_read(db, row)

    @staticmethod
    async def delete_document(db: AsyncSession, row: KnowledgeDocument) -> None:
        if row.uploaded_file_path:
            path = Path(row.uploaded_file_path)
            if path.exists():
                path.unlink(missing_ok=True)
        await db.delete(row)
        await db.commit()
