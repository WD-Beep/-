"""多租户上下文：用户 + 产品权限校验。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.tenant import Product, User, WorkspaceMember
from app.services.tenant_scope import ALL_PRODUCTS_ID
from app.services.tenant_service import TenantService


@dataclass(frozen=True)
class TenantContext:
    user_id: int
    product_id: int
    workspace_id: int
    is_admin: bool


@dataclass(frozen=True)
class UserContext:
    user_id: int
    is_admin: bool


async def _load_user(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
    return user


async def _ensure_product_access(db: AsyncSession, *, user: User, product_id: int) -> Product:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产品不存在")
    if user.is_admin:
        return product
    membership = await db.execute(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == product.workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该产品")
    return product


def _parse_required_header(value: int | None, header_name: str) -> int:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"缺少 {header_name} 请求头",
        )
    if value < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{header_name} 无效",
        )
    return value


async def get_user_context(
    db: AsyncSession = Depends(get_db),
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
) -> UserContext:
    user_id = _parse_required_header(x_user_id, "X-User-Id")
    user = await _load_user(db, user_id)
    return UserContext(user_id=user.id, is_admin=user.is_admin)


async def get_tenant_context(
    db: AsyncSession = Depends(get_db),
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    x_product_id: int | None = Header(default=None, alias="X-Product-Id"),
) -> TenantContext:
    user_id = _parse_required_header(x_user_id, "X-User-Id")
    product_id = _parse_required_header(x_product_id, "X-Product-Id")
    user = await _load_user(db, user_id)
    if product_id == ALL_PRODUCTS_ID:
        membership = await db.execute(
            select(WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user.id)
            .limit(1)
        )
        workspace_id = membership.scalar_one_or_none() or 1
        return TenantContext(
            user_id=user.id,
            product_id=ALL_PRODUCTS_ID,
            workspace_id=workspace_id,
            is_admin=user.is_admin,
        )
    product = await _ensure_product_access(db, user=user, product_id=product_id)
    return TenantContext(
        user_id=user.id,
        product_id=product.id,
        workspace_id=product.workspace_id,
        is_admin=user.is_admin,
    )


def require_write_product_id(ctx: TenantContext) -> int:
    if ctx.product_id == ALL_PRODUCTS_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择具体产品后再创建或修改数据",
        )
    return ctx.product_id


async def resolve_write_product_id(db: AsyncSession, ctx: TenantContext) -> int:
    if ctx.product_id != ALL_PRODUCTS_ID:
        return ctx.product_id
    products = await TenantService.list_accessible_products(
        db,
        user_id=ctx.user_id,
        is_admin=ctx.is_admin,
    )
    if not products:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="暂无可用产品，请先创建产品",
        )
    return products[0].id


async def require_product_access(
    product_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    if product_id != ctx.product_id and not ctx.is_admin:
        user = await _load_user(db, ctx.user_id)
        await _ensure_product_access(db, user=user, product_id=product_id)
    return ctx
