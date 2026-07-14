from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.tenant import User
from app.services.auth_service import create_access_token, hash_password, verify_password
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    username = data.username.strip()
    user = await db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确")

    valid = verify_password(data.password, user.password_hash)
    # Existing installations used fixed demo credentials. Upgrade them on first successful login.
    legacy_password = "admin" if user.is_admin else "baibo"
    if not valid and not user.password_hash and data.password == legacy_password:
        user.password_hash = hash_password(data.password)
        await db.commit()
        valid = True
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确")

    products = await TenantService.list_accessible_products(
        db, user_id=user.id, is_admin=user.is_admin, include_test=False
    )
    return {
        "token": create_access_token(user.id),
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "is_admin": user.is_admin,
        },
        "products": products,
    }
