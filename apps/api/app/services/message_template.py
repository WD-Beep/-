import math
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.tenant import TenantContext, require_write_product_id
from app.models.message_template import MessageTemplate
from app.services.default_message_templates import is_system_default_template
from app.schemas.common import PaginatedResponse
from app.schemas.message_template import (
    MessageTemplateCreate,
    MessageTemplateFilter,
    MessageTemplateRead,
    MessageTemplateUpdate,
)


class MessageTemplateService:
    @staticmethod
    def _to_read(row: MessageTemplate) -> MessageTemplateRead:
        data = MessageTemplateRead.model_validate(row)
        return data.model_copy(update={"is_system_default": is_system_default_template(row)})

    @staticmethod
    def _normalize_tags(tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for raw in tags:
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out

    @staticmethod
    def _normalize_rules(rules: object | None) -> dict:
        if rules is None:
            return {}
        if hasattr(rules, "model_dump"):
            return rules.model_dump(exclude_none=True)
        return {key: value for key, value in dict(rules).items() if value is not None} if isinstance(rules, dict) else {}

    @staticmethod
    async def _clear_default_for_product(
        db: AsyncSession,
        *,
        product_id: int,
        exclude_id: int | None = None,
    ) -> None:
        statement = update(MessageTemplate).where(
            MessageTemplate.product_id == product_id,
            MessageTemplate.is_default.is_(True),
        )
        if exclude_id is not None:
            statement = statement.where(MessageTemplate.id != exclude_id)
        await db.execute(statement.values(is_default=False))

    @staticmethod
    def _apply_filters(query, filters: MessageTemplateFilter):
        query = query.where(MessageTemplate.product_id == filters.product_id)
        if filters.scenario:
            query = query.where(MessageTemplate.scenario == filters.scenario)
        if filters.platform:
            query = query.where(MessageTemplate.platform == filters.platform)
        if filters.language:
            query = query.where(MessageTemplate.language == filters.language)
        if filters.tag:
            query = query.where(MessageTemplate.tags.contains([filters.tag]))
        if filters.search:
            term = f"%{filters.search.strip()}%"
            query = query.where(
                or_(
                    MessageTemplate.title.ilike(term),
                    MessageTemplate.content.ilike(term),
                    MessageTemplate.note.ilike(term),
                )
            )
        return query

    @staticmethod
    async def list_templates(
        db: AsyncSession,
        filters: MessageTemplateFilter,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[MessageTemplateRead]:
        base = select(MessageTemplate)
        base = MessageTemplateService._apply_filters(base, filters)
        total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
        result = await db.execute(
            base.order_by(MessageTemplate.is_default.desc(), MessageTemplate.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [MessageTemplateService._to_read(row) for row in result.scalars().all()]
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def get_template(
        db: AsyncSession,
        template_id: int,
        *,
        product_id: int,
    ) -> MessageTemplate | None:
        result = await db.execute(
            select(MessageTemplate).where(
                MessageTemplate.id == template_id,
                MessageTemplate.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_template(
        db: AsyncSession,
        data: MessageTemplateCreate,
        *,
        ctx: TenantContext,
    ) -> MessageTemplate:
        product_id = require_write_product_id(ctx)
        if data.is_default:
            await MessageTemplateService._clear_default_for_product(db, product_id=product_id)
        row = MessageTemplate(
            user_id=ctx.user_id,
            workspace_id=ctx.workspace_id,
            product_id=product_id,
            title=data.title.strip(),
            scenario=data.scenario.strip(),
            platform=(data.platform or "").strip() or None,
            language=(data.language or "").strip() or None,
            tags=MessageTemplateService._normalize_tags(data.tags),
            content=data.content.strip(),
            note=(data.note or "").strip() or None,
            generation_rules=MessageTemplateService._normalize_rules(data.generation_rules),
            is_default=data.is_default,
            source_filename=(data.source_filename or "").strip() or None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def update_template(
        db: AsyncSession,
        row: MessageTemplate,
        data: MessageTemplateUpdate,
    ) -> MessageTemplate:
        payload = data.model_dump(exclude_unset=True)
        if payload.get("is_default") is True:
            await MessageTemplateService._clear_default_for_product(
                db,
                product_id=row.product_id,
                exclude_id=row.id,
            )
        if "title" in payload and payload["title"] is not None:
            row.title = payload["title"].strip()
        if "scenario" in payload and payload["scenario"] is not None:
            row.scenario = payload["scenario"].strip()
        if "platform" in payload:
            row.platform = (payload["platform"] or "").strip() or None
        if "language" in payload:
            row.language = (payload["language"] or "").strip() or None
        if "tags" in payload and payload["tags"] is not None:
            row.tags = MessageTemplateService._normalize_tags(payload["tags"])
        if "content" in payload and payload["content"] is not None:
            row.content = payload["content"].strip()
        if "note" in payload:
            row.note = (payload["note"] or "").strip() or None
        if "generation_rules" in payload and payload["generation_rules"] is not None:
            row.generation_rules = MessageTemplateService._normalize_rules(payload["generation_rules"])
        if "is_default" in payload and payload["is_default"] is not None:
            row.is_default = bool(payload["is_default"])
        if "source_filename" in payload:
            row.source_filename = (payload["source_filename"] or "").strip() or None
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def delete_template(db: AsyncSession, row: MessageTemplate) -> None:
        await db.delete(row)
        await db.commit()

    @staticmethod
    async def record_use(db: AsyncSession, row: MessageTemplate) -> MessageTemplate:
        row.usage_count = int(row.usage_count or 0) + 1
        row.last_used_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def duplicate_template(
        db: AsyncSession,
        row: MessageTemplate,
        *,
        ctx: TenantContext,
    ) -> MessageTemplate:
        copy = MessageTemplate(
            user_id=ctx.user_id,
            workspace_id=ctx.workspace_id,
            product_id=row.product_id,
            title=f"{row.title}（副本）"[:255],
            scenario=row.scenario,
            platform=row.platform,
            language=row.language,
            tags=list(row.tags or []),
            content=row.content,
            note=row.note,
            generation_rules=dict(row.generation_rules or {}),
            is_default=False,
            source_filename=row.source_filename,
        )
        db.add(copy)
        await db.commit()
        await db.refresh(copy)
        return copy
