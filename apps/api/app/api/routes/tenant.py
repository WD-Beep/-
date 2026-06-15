from fastapi import APIRouter, Depends, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import UserContext, get_user_context
from app.schemas.tenant import ProductCreate, ProductRead, ProductUpdate, UserRead
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/tenant", tags=["tenant"])


@router.get("/me", response_model=UserRead)
async def get_current_user(
    ctx: UserContext = Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await TenantService.get_user(db, ctx.user_id)
    return user  # type: ignore[return-value]


@router.get("/products", response_model=list[ProductRead])
async def list_products(
    include_test: bool = False,
    ctx: UserContext = Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[ProductRead]:
    if include_test and not ctx.is_admin:
        include_test = False
    return await TenantService.list_accessible_products(
        db,
        user_id=ctx.user_id,
        is_admin=ctx.is_admin,
        include_test=include_test,
    )


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    ctx: UserContext = Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
) -> ProductRead:
    return await TenantService.create_product(
        db, user_id=ctx.user_id, is_admin=ctx.is_admin, data=data
    )


@router.patch("/products/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    ctx: UserContext = Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
) -> ProductRead:
    return await TenantService.update_product(
        db,
        user_id=ctx.user_id,
        is_admin=ctx.is_admin,
        product_id=product_id,
        data=data,
    )
