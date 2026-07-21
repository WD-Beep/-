# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：message templates
from io import BytesIO
from pathlib import Path
import zipfile
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import TenantContext, get_tenant_context, require_write_product_id
from app.models.message_template import MessageTemplate
from app.schemas.common import PaginatedResponse
from app.schemas.message_template import (
    MessageTemplateCreate,
    MessageTemplateFilter,
    MessageTemplateRead,
    MessageTemplateUploadRead,
    MessageTemplateUpdate,
)
from app.services.default_message_templates import ensure_default_templates_for_product
from app.services.message_template import MessageTemplateService
from app.services.tenant_scope import ALL_PRODUCTS_ID

router = APIRouter(prefix="/message-templates", tags=["message-templates"])
MAX_TEMPLATE_UPLOAD_BYTES = 2 * 1024 * 1024
SUPPORTED_TEMPLATE_UPLOAD_SUFFIXES = {".txt", ".md", ".docx"}


def _require_product_scope(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择具体产品/品牌后再操作话术库",
        )
    return ctx.product_id


def _ensure_template_access(row: MessageTemplate, ctx: TenantContext) -> None:
    product_id = _require_product_scope(ctx)
    if row.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")


def _decode_template_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="模板文本编码无法识别，请使用 UTF-8")


def _parse_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="DOCX 文件损坏或格式不正确") from exc
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


@router.get("", response_model=PaginatedResponse[MessageTemplateRead])
async def list_message_templates(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    scenario: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    language: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> PaginatedResponse[MessageTemplateRead]:
    product_id = _require_product_scope(ctx)
    await ensure_default_templates_for_product(db, ctx=ctx, product_id=product_id)
    filters = MessageTemplateFilter(
        product_id=product_id,
        search=search,
        scenario=scenario,
        platform=platform,
        language=language,
        tag=tag,
    )
    return await MessageTemplateService.list_templates(db, filters, page, page_size)


@router.post("", response_model=MessageTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_message_template(
    data: MessageTemplateCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    _require_product_scope(ctx)
    row = await MessageTemplateService.create_template(db, data, ctx=ctx)
    return MessageTemplateService._to_read(row)


@router.post("/parse-upload", response_model=MessageTemplateUploadRead)
async def parse_message_template_upload(
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateUploadRead:
    _require_product_scope(ctx)
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_TEMPLATE_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 .txt、.md、.docx 模板文件")
    content = await file.read(MAX_TEMPLATE_UPLOAD_BYTES + 1)
    if len(content) > MAX_TEMPLATE_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="模板文件不能超过 2MB")
    parsed = _parse_docx_text(content) if suffix == ".docx" else _decode_template_text(content)
    parsed = parsed.strip()
    if not parsed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="模板文件内容为空")
    return MessageTemplateUploadRead(filename=filename, content=parsed)


@router.get("/{template_id}", response_model=MessageTemplateRead)
async def get_message_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    product_id = _require_product_scope(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    return MessageTemplateService._to_read(row)


@router.patch("/{template_id}", response_model=MessageTemplateRead)
async def update_message_template(
    template_id: int,
    data: MessageTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    product_id = _require_product_scope(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    _ensure_template_access(row, ctx)
    updated = await MessageTemplateService.update_template(db, row, data)
    return MessageTemplateService._to_read(updated)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> None:
    product_id = _require_product_scope(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    _ensure_template_access(row, ctx)
    await MessageTemplateService.delete_template(db, row)


@router.post("/{template_id}/use", response_model=MessageTemplateRead)
async def use_message_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    product_id = _require_product_scope(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    _ensure_template_access(row, ctx)
    updated = await MessageTemplateService.record_use(db, row)
    return MessageTemplateService._to_read(updated)


@router.post("/{template_id}/duplicate", response_model=MessageTemplateRead, status_code=status.HTTP_201_CREATED)
async def duplicate_message_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
) -> MessageTemplateRead:
    product_id = require_write_product_id(ctx)
    row = await MessageTemplateService.get_template(db, template_id, product_id=product_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="话术不存在")
    copy = await MessageTemplateService.duplicate_template(db, row, ctx=ctx)
    return MessageTemplateService._to_read(copy)
