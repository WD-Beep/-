"""Tenant context dependencies: user and product access checks."""

from __future__ import annotations

from dataclasses import dataclass
import os

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.tenant import Product, ProductMember, User, WorkspaceMember
from app.services.tenant_scope import ALL_PRODUCTS_ID
from app.services.auth_service import read_access_token


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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")
    return user


async def _ensure_product_access(db: AsyncSession, *, user: User, product_id: int) -> Product:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if user.is_admin:
        return product
    if product.is_default or product.slug == "default":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this product")
    assignment = await db.execute(
        select(ProductMember.id).where(
            ProductMember.product_id == product.id,
            ProductMember.user_id == user.id,
        )
    )
    if assignment.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this product")
    return product


def _parse_required_header(value: int | None, header_name: str) -> int:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing {header_name} header",
        )
    if value < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {header_name}",
        )
    return value


def _is_production_env() -> bool:
    value = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return value in {"prod", "production"}


def _resolve_authenticated_user_id(
    *,
    x_user_id: int | None,
    x_authenticated_user_id: int | None,
    x_auth_proxy_secret: str | None,
    authorization: str | None,
) -> int:
    if authorization and authorization.lower().startswith("bearer "):
        token_user_id = read_access_token(authorization[7:].strip())
        if token_user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效")
        return token_user_id
    if _is_production_env():
        expected_secret = (os.getenv("AUTH_PROXY_SHARED_SECRET") or "").strip()
        if not expected_secret:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is not configured")
        if not x_auth_proxy_secret or x_auth_proxy_secret.strip() != expected_secret:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication proxy secret")
        return _parse_required_header(x_authenticated_user_id, "X-Authenticated-User-Id")

    return _parse_required_header(x_user_id, "X-User-Id")


async def get_user_context(
    db: AsyncSession = Depends(get_db),
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    x_authenticated_user_id: int | None = Header(default=None, alias="X-Authenticated-User-Id"),
    x_auth_proxy_secret: str | None = Header(default=None, alias="X-Auth-Proxy-Secret"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UserContext:
    user_id = _resolve_authenticated_user_id(
        x_user_id=x_user_id,
        x_authenticated_user_id=x_authenticated_user_id,
        x_auth_proxy_secret=x_auth_proxy_secret,
        authorization=authorization,
    )
    user = await _load_user(db, user_id)
    return UserContext(user_id=user.id, is_admin=user.is_admin)


async def get_tenant_context(
    db: AsyncSession = Depends(get_db),
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    x_product_id: int | None = Header(default=None, alias="X-Product-Id"),
    x_authenticated_user_id: int | None = Header(default=None, alias="X-Authenticated-User-Id"),
    x_auth_proxy_secret: str | None = Header(default=None, alias="X-Auth-Proxy-Secret"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> TenantContext:
    user_id = _resolve_authenticated_user_id(
        x_user_id=x_user_id,
        x_authenticated_user_id=x_authenticated_user_id,
        x_auth_proxy_secret=x_auth_proxy_secret,
        authorization=authorization,
    )
    product_id = _parse_required_header(x_product_id, "X-Product-Id")
    user = await _load_user(db, user_id)
    if product_id == ALL_PRODUCTS_ID:
        if not user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to all products")
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
            detail="Please select a concrete product before writing data.",
        )
    return ctx.product_id


async def resolve_write_product_id(db: AsyncSession, ctx: TenantContext) -> int:
    if ctx.product_id != ALL_PRODUCTS_ID:
        return ctx.product_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Please select a concrete product before writing data.",
    )


async def require_product_access(
    product_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    if product_id != ctx.product_id and not ctx.is_admin:
        user = await _load_user(db, ctx.user_id)
        await _ensure_product_access(db, user=user, product_id=product_id)
    return ctx
