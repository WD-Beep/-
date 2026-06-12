import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Product, User, WorkspaceMember
from app.schemas.tenant import ProductCreate, ProductRead, ProductUpdate, UserRead

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_product_name(name: str) -> str:
    text = (name or "").strip().lower()
    slug = _SLUG_RE.sub("-", text).strip("-")
    if not slug:
        slug = f"product-{uuid.uuid4().hex[:8]}"
    return slug[:100]


def normalize_product_slug(slug: str) -> str:
    text = (slug or "").strip().lower()
    normalized = _SLUG_RE.sub("-", text).strip("-")
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="slug 无效")
    return normalized[:100]


class TenantService:
    @staticmethod
    async def list_accessible_products(db: AsyncSession, *, user_id: int, is_admin: bool) -> list[ProductRead]:
        if is_admin:
            rows = await db.execute(select(Product).order_by(Product.is_default.desc(), Product.id.asc()))
        else:
            rows = await db.execute(
                select(Product)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Product.workspace_id)
                .where(WorkspaceMember.user_id == user_id)
                .order_by(Product.is_default.desc(), Product.id.asc())
            )
        return [ProductRead.model_validate(row) for row in rows.scalars().all()]

    @staticmethod
    async def get_user(db: AsyncSession, user_id: int) -> UserRead | None:
        user = await db.get(User, user_id)
        return UserRead.model_validate(user) if user else None

    @staticmethod
    async def resolve_user_workspace_id(db: AsyncSession, *, user_id: int, is_admin: bool) -> int:
        result = await db.execute(
            select(WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(WorkspaceMember.id.asc())
            .limit(1)
        )
        workspace_id = result.scalar_one_or_none()
        if workspace_id is not None:
            return workspace_id
        if is_admin:
            return 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前用户未加入任何工作区，无法创建产品/品牌",
        )

    @staticmethod
    async def _ensure_unique_slug(db: AsyncSession, workspace_id: int, slug: str) -> str:
        candidate = slug
        suffix = 2
        while True:
            existing = await db.execute(
                select(Product.id).where(
                    Product.workspace_id == workspace_id,
                    Product.slug == candidate,
                )
            )
            if existing.scalar_one_or_none() is None:
                return candidate
            stem = slug[: max(1, 100 - len(str(suffix)) - 1)].rstrip("-")
            candidate = f"{stem}-{suffix}"[:100]
            suffix += 1

    @staticmethod
    async def _clear_default_products(db: AsyncSession, workspace_id: int) -> None:
        await db.execute(
            update(Product)
            .where(Product.workspace_id == workspace_id, Product.is_default.is_(True))
            .values(is_default=False)
        )

    @staticmethod
    async def create_product(
        db: AsyncSession,
        *,
        user_id: int,
        is_admin: bool,
        data: ProductCreate,
    ) -> ProductRead:
        workspace_id = await TenantService.resolve_user_workspace_id(
            db, user_id=user_id, is_admin=is_admin
        )
        base_slug = normalize_product_slug(data.slug or slugify_product_name(data.name))
        slug = await TenantService._ensure_unique_slug(db, workspace_id, base_slug)

        if data.is_default:
            await TenantService._clear_default_products(db, workspace_id)

        row = Product(
            workspace_id=workspace_id,
            name=data.name.strip(),
            slug=slug,
            brand=(data.brand or "").strip() or None,
            description=(data.description or "").strip() or None,
            is_default=data.is_default,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return ProductRead.model_validate(row)

    @staticmethod
    async def update_product(
        db: AsyncSession,
        *,
        user_id: int,
        is_admin: bool,
        product_id: int,
        data: ProductUpdate,
    ) -> ProductRead:
        product = await db.get(Product, product_id)
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产品不存在")

        workspace_id = await TenantService.resolve_user_workspace_id(
            db, user_id=user_id, is_admin=is_admin
        )
        if product.workspace_id != workspace_id and not is_admin:
            membership = await db.execute(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == product.workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
            )
            if membership.scalar_one_or_none() is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改该产品")

        payload = data.model_dump(exclude_unset=True)
        if "name" in payload and payload["name"] is not None:
            product.name = payload["name"].strip()
        if "brand" in payload:
            product.brand = (payload["brand"] or "").strip() or None
        if "description" in payload:
            product.description = (payload["description"] or "").strip() or None
        if "slug" in payload and payload["slug"] is not None:
            base_slug = normalize_product_slug(payload["slug"])
            if base_slug != product.slug:
                product.slug = await TenantService._ensure_unique_slug(db, product.workspace_id, base_slug)
        if payload.get("is_default") is True:
            await TenantService._clear_default_products(db, product.workspace_id)
            product.is_default = True
        elif payload.get("is_default") is False:
            product.is_default = False

        await db.commit()
        await db.refresh(product)
        return ProductRead.model_validate(product)
