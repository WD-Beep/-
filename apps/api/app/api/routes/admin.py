from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import UserContext, get_user_context
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product, ProductMember, User
from app.scheduler import refresh_scheduler
from app.schemas.collection_task import CollectionTaskBulkDelete, CollectionTaskBulkDeleteResult
from app.services.collection_task import CollectionTaskService

router = APIRouter(prefix="/admin", tags=["admin"])

SUCCESS_TASK_STATUSES = {"completed", "completed_with_results", "completed_no_results"}
FAILED_TASK_STATUSES = {"failed", "partial_failed"}


async def require_admin(ctx: UserContext = Depends(get_user_context)) -> UserContext:
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return ctx


async def _count(db: AsyncSession, statement: Select[tuple[Any]]) -> int:
    value = await db.scalar(statement)
    return int(value or 0)


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _status_for_product(product: Product) -> str:
    if product.is_archived:
        return "archived"
    if product.is_hidden:
        return "hidden"
    return "active"


def _latest(values: Iterable[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


async def _product_ids_for_user(db: AsyncSession, user_id: int) -> list[int]:
    rows = await db.execute(
        select(ProductMember.product_id).where(ProductMember.user_id == user_id)
    )
    return [int(row[0]) for row in rows]


async def _product_members(db: AsyncSession, product_id: int) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(ProductMember, User)
        .join(User, User.id == ProductMember.user_id)
        .where(ProductMember.product_id == product_id)
        .order_by(ProductMember.role.desc(), User.id.asc())
    )
    return [
        {
            "id": member.id,
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": member.role,
            "created_at": member.created_at,
        }
        for member, user in rows
    ]


async def _bound_products(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(ProductMember, Product)
        .join(Product, Product.id == ProductMember.product_id)
        .where(ProductMember.user_id == user_id)
        .order_by(Product.created_at.desc(), Product.id.desc())
    )
    return [
        {
            "id": product.id,
            "name": product.name,
            "slug": product.slug,
            "role": member.role,
            "status": _status_for_product(product),
            "created_at": product.created_at,
        }
        for member, product in rows
    ]


async def _last_active_at(db: AsyncSession, user: User, product_ids: list[int]) -> datetime | None:
    task_last = await db.scalar(
        select(func.max(CollectionTask.updated_at)).where(CollectionTask.user_id == user.id)
    )
    email_last = await db.scalar(select(func.max(EmailLog.sent_at)).where(EmailLog.user_id == user.id))
    reply_last = await db.scalar(
        select(func.max(EmailReply.received_at)).where(EmailReply.user_id == user.id)
    )
    product_last = None
    if product_ids:
        product_last = await db.scalar(
            select(func.max(ProductMember.updated_at)).where(ProductMember.user_id == user.id)
        )
    return _latest([user.updated_at, task_last, email_last, reply_last, product_last])


async def _user_summary(db: AsyncSession, user: User) -> dict[str, Any]:
    today = _today_start()
    product_ids = await _product_ids_for_user(db, user.id)
    bound_products = await _bound_products(db, user.id)
    collection_task_count = await _count(
        db, select(func.count(CollectionTask.id)).where(CollectionTask.user_id == user.id)
    )
    today_collection_task_count = await _count(
        db,
        select(func.count(CollectionTask.id)).where(
            CollectionTask.user_id == user.id,
            CollectionTask.created_at >= today,
        ),
    )
    collection_success_count = await _count(
        db,
        select(func.count(CollectionTask.id)).where(
            CollectionTask.user_id == user.id,
            CollectionTask.status.in_(SUCCESS_TASK_STATUSES),
        ),
    )
    collection_failed_count = await _count(
        db,
        select(func.count(CollectionTask.id)).where(
            CollectionTask.user_id == user.id,
            CollectionTask.status.in_(FAILED_TASK_STATUSES),
        ),
    )
    influencer_count = 0
    today_influencer_count = 0
    if product_ids:
        influencer_count = await _count(
            db,
            select(func.count(ProductInfluencer.id)).where(
                ProductInfluencer.product_id.in_(product_ids)
            ),
        )
        today_influencer_count = await _count(
            db,
            select(func.count(ProductInfluencer.id)).where(
                ProductInfluencer.product_id.in_(product_ids),
                ProductInfluencer.created_at >= today,
            ),
        )
    email_count = await _count(db, select(func.count(EmailLog.id)).where(EmailLog.user_id == user.id))
    email_failed_count = await _count(
        db,
        select(func.count(EmailLog.id)).where(EmailLog.user_id == user.id, EmailLog.status == "failed"),
    )
    reply_count = await _count(db, select(func.count(EmailReply.id)).where(EmailReply.user_id == user.id))
    pending_reply_count = await _count(
        db,
        select(func.count(EmailReply.id)).where(
            EmailReply.user_id == user.id,
            EmailReply.processing_status == "unprocessed",
        ),
    )

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "role": "admin" if user.is_admin else "sales",
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "product_count": len(product_ids),
        "bound_products": bound_products,
        "collection_task_count": collection_task_count,
        "today_collection_task_count": today_collection_task_count,
        "collection_success_count": collection_success_count,
        "collection_failed_count": collection_failed_count,
        "influencer_count": influencer_count,
        "today_influencer_count": today_influencer_count,
        "email_count": email_count,
        "email_failed_count": email_failed_count,
        "reply_count": reply_count,
        "pending_reply_count": pending_reply_count,
        "last_active_at": await _last_active_at(db, user, product_ids),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "status": "active" if user.is_active else "disabled",
    }


async def _product_summary(db: AsyncSession, product: Product) -> dict[str, Any]:
    members = await _product_members(db, product.id)
    return {
        "id": product.id,
        "name": product.name,
        "subject": product.brand or product.description,
        "brand": product.brand,
        "description": product.description,
        "slug": product.slug,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
        "members": members,
        "owner_names": [item["username"] for item in members if item["role"] == "owner"]
        or [item["username"] for item in members],
        "collection_task_count": await _count(
            db, select(func.count(CollectionTask.id)).where(CollectionTask.product_id == product.id)
        ),
        "influencer_count": await _count(
            db, select(func.count(ProductInfluencer.id)).where(ProductInfluencer.product_id == product.id)
        ),
        "email_count": await _count(
            db, select(func.count(EmailLog.id)).where(EmailLog.product_id == product.id)
        ),
        "reply_count": await _count(
            db, select(func.count(EmailReply.id)).where(EmailReply.product_id == product.id)
        ),
        "status": _status_for_product(product),
    }


def _task_row(task: CollectionTask, product: Product | None = None, user: User | None = None) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "platform": task.platform,
        "platforms": task.platforms or [],
        "keywords": task.keywords or [],
        "product_id": task.product_id,
        "product_name": product.name if product else None,
        "user_id": task.user_id,
        "username": user.username if user else None,
        "success_count": task.success_count,
        "failed_count": task.failed_count,
        "inserted_count": task.inserted_count,
        "result_count": task.result_count,
        "last_run_at": task.last_run_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _influencer_row(
    influencer: ProductInfluencer,
    profile: GlobalInfluencerProfile,
    product: Product | None = None,
) -> dict[str, Any]:
    return {
        "id": influencer.id,
        "product_id": influencer.product_id,
        "product_name": product.name if product else None,
        "platform": profile.platform,
        "username": profile.username,
        "display_name": profile.display_name,
        "profile_url": profile.profile_url,
        "followers_count": profile.followers_count,
        "email": profile.final_email or profile.email or profile.public_email or profile.business_email,
        "follow_status": influencer.follow_status,
        "score": influencer.score,
        "created_at": influencer.created_at,
        "updated_at": influencer.updated_at,
    }


def _email_row(email: EmailLog, product: Product | None = None, user: User | None = None) -> dict[str, Any]:
    return {
        "id": email.id,
        "user_id": email.user_id,
        "username": user.username if user else None,
        "product_id": email.product_id,
        "product_name": product.name if product else None,
        "task_id": email.task_id,
        "product_influencer_id": email.product_influencer_id,
        "sender_email": email.sender_email,
        "influencer_username": email.influencer_username,
        "recipients": email.recipients or [],
        "subject": email.subject,
        "status": email.status,
        "error_message": email.error_message,
        "sent_at": email.sent_at,
        "has_replied": email.has_replied,
        "replied_at": email.replied_at,
    }


def _reply_row(reply: EmailReply, product: Product | None = None, user: User | None = None) -> dict[str, Any]:
    return {
        "id": reply.id,
        "user_id": reply.user_id,
        "username": user.username if user else None,
        "product_id": reply.product_id,
        "product_name": product.name if product else None,
        "email_log_id": reply.email_log_id,
        "product_influencer_id": reply.product_influencer_id,
        "from_address": reply.from_address,
        "to_address": reply.to_address,
        "subject": reply.subject,
        "snippet": reply.snippet,
        "processing_status": reply.processing_status,
        "intent_status": reply.intent_status,
        "received_at": reply.received_at,
        "handled_at": reply.handled_at,
    }


@router.get("/summary")
async def get_admin_summary(
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int | list[dict[str, Any]]]:
    today = _today_start()

    total_users = await _count(db, select(func.count(User.id)))
    total_sales = await _count(db, select(func.count(User.id)).where(User.is_admin.is_(False)))
    total_products = await _count(db, select(func.count(Product.id)))
    total_collection_tasks = await _count(db, select(func.count(CollectionTask.id)))
    total_influencers = await _count(db, select(func.count(ProductInfluencer.id)))
    total_email_logs = await _count(db, select(func.count(EmailLog.id)))
    total_replies = await _count(db, select(func.count(EmailReply.id)))

    sales_rank_rows = await db.execute(
        select(User.id, User.username, func.count(ProductMember.product_id).label("product_count"))
        .outerjoin(ProductMember, ProductMember.user_id == User.id)
        .where(User.is_admin.is_(False))
        .group_by(User.id, User.username)
        .order_by(func.count(ProductMember.product_id).desc(), User.id.asc())
        .limit(5)
    )
    product_rank_rows = await db.execute(
        select(Product.id, Product.name, func.count(ProductInfluencer.id).label("influencer_count"))
        .outerjoin(ProductInfluencer, ProductInfluencer.product_id == Product.id)
        .group_by(Product.id, Product.name)
        .order_by(func.count(ProductInfluencer.id).desc(), Product.id.asc())
        .limit(5)
    )

    return {
        "total_users": total_users,
        "total_sales": total_sales,
        "total_products": total_products,
        "total_collection_tasks": total_collection_tasks,
        "total_influencers": total_influencers,
        "total_email_logs": total_email_logs,
        "total_replies": total_replies,
        "today_collection_tasks": await _count(db, select(func.count(CollectionTask.id)).where(CollectionTask.created_at >= today)),
        "today_influencers": await _count(db, select(func.count(ProductInfluencer.id)).where(ProductInfluencer.created_at >= today)),
        "today_email_logs": await _count(db, select(func.count(EmailLog.id)).where(EmailLog.sent_at >= today)),
        "today_replies": await _count(db, select(func.count(EmailReply.id)).where(EmailReply.received_at >= today)),
        "failed_collection_tasks": await _count(db, select(func.count(CollectionTask.id)).where(CollectionTask.status.in_(FAILED_TASK_STATUSES))),
        "failed_email_logs": await _count(db, select(func.count(EmailLog.id)).where(EmailLog.status == "failed")),
        "pending_replies": await _count(db, select(func.count(EmailReply.id)).where(EmailReply.processing_status == "unprocessed")),
        "sales_rank": [{"id": row.id, "username": row.username, "product_count": row.product_count} for row in sales_rank_rows],
        "product_rank": [{"id": row.id, "name": row.name, "influencer_count": row.influencer_count} for row in product_rank_rows],
    }


@router.get("/users")
async def list_admin_users(
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    users = (await db.execute(select(User).order_by(User.is_admin.desc(), User.id.asc()))).scalars().all()
    return [await _user_summary(db, user) for user in users]


@router.get("/users/{user_id}")
async def get_admin_user(
    user_id: int,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    detail = await _user_summary(db, user)
    detail["recent_activity"] = {
        "collection_tasks": (await list_admin_user_collection_tasks(user_id, _ctx, db))[:5],
        "emails": (await list_admin_user_emails(user_id, _ctx, db))[:5],
        "replies": (await list_admin_user_replies(user_id, _ctx, db))[:5],
    }
    return detail


@router.get("/users/{user_id}/products")
async def list_admin_user_products(
    user_id: int,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await _ensure_user_exists(db, user_id)
    products = (
        await db.execute(
            select(Product)
            .join(ProductMember, ProductMember.product_id == Product.id)
            .where(ProductMember.user_id == user_id)
            .order_by(Product.created_at.desc(), Product.id.desc())
        )
    ).scalars().all()
    return [await _product_summary(db, product) for product in products]


@router.get("/users/{user_id}/collection-tasks")
async def list_admin_user_collection_tasks(
    user_id: int,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await _ensure_user_exists(db, user_id)
    rows = await db.execute(
        select(CollectionTask, Product, User)
        .outerjoin(Product, Product.id == CollectionTask.product_id)
        .outerjoin(User, User.id == CollectionTask.user_id)
        .where(CollectionTask.user_id == user_id)
        .order_by(CollectionTask.created_at.desc(), CollectionTask.id.desc())
        .limit(100)
    )
    return [_task_row(task, product, user) for task, product, user in rows]


@router.get("/users/{user_id}/influencers")
async def list_admin_user_influencers(
    user_id: int,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await _ensure_user_exists(db, user_id)
    product_ids = await _product_ids_for_user(db, user_id)
    if not product_ids:
        return []
    rows = await db.execute(
        select(ProductInfluencer, GlobalInfluencerProfile, Product)
        .join(GlobalInfluencerProfile, GlobalInfluencerProfile.id == ProductInfluencer.global_influencer_id)
        .join(Product, Product.id == ProductInfluencer.product_id)
        .where(ProductInfluencer.product_id.in_(product_ids))
        .order_by(ProductInfluencer.created_at.desc(), ProductInfluencer.id.desc())
        .limit(100)
    )
    return [_influencer_row(influencer, profile, product) for influencer, profile, product in rows]


@router.get("/users/{user_id}/emails")
async def list_admin_user_emails(
    user_id: int,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await _ensure_user_exists(db, user_id)
    rows = await db.execute(
        select(EmailLog, Product, User)
        .outerjoin(Product, Product.id == EmailLog.product_id)
        .outerjoin(User, User.id == EmailLog.user_id)
        .where(EmailLog.user_id == user_id)
        .order_by(EmailLog.sent_at.desc().nullslast(), EmailLog.id.desc())
        .limit(100)
    )
    return [_email_row(email, product, user) for email, product, user in rows]


@router.get("/users/{user_id}/replies")
async def list_admin_user_replies(
    user_id: int,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await _ensure_user_exists(db, user_id)
    rows = await db.execute(
        select(EmailReply, Product, User)
        .outerjoin(Product, Product.id == EmailReply.product_id)
        .outerjoin(User, User.id == EmailReply.user_id)
        .where(EmailReply.user_id == user_id)
        .order_by(EmailReply.received_at.desc(), EmailReply.id.desc())
        .limit(100)
    )
    return [_reply_row(reply, product, user) for reply, product, user in rows]


@router.get("/products")
async def list_admin_products(
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    products = (await db.execute(select(Product).order_by(Product.created_at.desc(), Product.id.desc()))).scalars().all()
    return [await _product_summary(db, product) for product in products]


@router.get("/products/{product_id}")
async def get_admin_product(
    product_id: int,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    detail = await _product_summary(db, product)
    detail["collection_tasks"] = await _collection_tasks_for_product(db, product_id)
    detail["influencers"] = await _influencers_for_product(db, product_id)
    detail["emails"] = await _emails_for_product(db, product_id)
    detail["replies"] = await _replies_for_product(db, product_id)
    return detail


@router.get("/collection-tasks")
async def list_admin_collection_tasks(
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(CollectionTask, Product, User)
        .outerjoin(Product, Product.id == CollectionTask.product_id)
        .outerjoin(User, User.id == CollectionTask.user_id)
        .where(CollectionTask.is_archived.is_(False))
        .order_by(CollectionTask.created_at.desc(), CollectionTask.id.desc())
        .limit(200)
    )
    return [_task_row(task, product, user) for task, product, user in rows]


@router.post("/collection-tasks/bulk-delete", response_model=CollectionTaskBulkDeleteResult)
async def bulk_delete_admin_collection_tasks(
    data: CollectionTaskBulkDelete,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CollectionTaskBulkDeleteResult:
    tasks: list[CollectionTask] = []
    for task_id in data.task_ids:
        task = await db.get(CollectionTask, task_id)
        if task and not task.is_archived and task.parent_task_id is None:
            tasks.append(task)
    result = await CollectionTaskService.delete_tasks_bulk(
        db,
        tasks,
        require_ineffective=False,
    )
    await refresh_scheduler()
    return CollectionTaskBulkDeleteResult(
        deleted_count=len(result["deleted_ids"]),
        archived_count=len(result["archived_ids"]),
        skipped_count=len(result["skipped_ids"]),
        deleted_ids=result["deleted_ids"],
        archived_ids=result["archived_ids"],
        skipped_ids=result["skipped_ids"],
    )


@router.delete("/collection-tasks/{task_id}")
async def delete_admin_collection_task(
    task_id: int,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await db.get(CollectionTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Collection task not found")
    try:
        action = await CollectionTaskService.dispose_task(db, task, require_ineffective=False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await refresh_scheduler()
    return {"action": action, "task_id": task_id}


@router.get("/influencers")
async def list_admin_influencers(
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(ProductInfluencer, GlobalInfluencerProfile, Product)
        .join(GlobalInfluencerProfile, GlobalInfluencerProfile.id == ProductInfluencer.global_influencer_id)
        .join(Product, Product.id == ProductInfluencer.product_id)
        .order_by(ProductInfluencer.created_at.desc(), ProductInfluencer.id.desc())
        .limit(200)
    )
    return [_influencer_row(influencer, profile, product) for influencer, profile, product in rows]


@router.get("/emails")
async def list_admin_emails(
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(EmailLog, Product, User)
        .outerjoin(Product, Product.id == EmailLog.product_id)
        .outerjoin(User, User.id == EmailLog.user_id)
        .order_by(EmailLog.sent_at.desc().nullslast(), EmailLog.id.desc())
        .limit(200)
    )
    return [_email_row(email, product, user) for email, product, user in rows]


@router.get("/replies")
async def list_admin_replies(
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(EmailReply, Product, User)
        .outerjoin(Product, Product.id == EmailReply.product_id)
        .outerjoin(User, User.id == EmailReply.user_id)
        .order_by(EmailReply.received_at.desc(), EmailReply.id.desc())
        .limit(200)
    )
    return [_reply_row(reply, product, user) for reply, product, user in rows]


async def _ensure_user_exists(db: AsyncSession, user_id: int) -> None:
    if not await db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")


async def _collection_tasks_for_product(db: AsyncSession, product_id: int) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(CollectionTask, Product, User)
        .outerjoin(Product, Product.id == CollectionTask.product_id)
        .outerjoin(User, User.id == CollectionTask.user_id)
        .where(CollectionTask.product_id == product_id)
        .where(CollectionTask.is_archived.is_(False))
        .order_by(CollectionTask.created_at.desc(), CollectionTask.id.desc())
        .limit(100)
    )
    return [_task_row(task, product, user) for task, product, user in rows]


async def _influencers_for_product(db: AsyncSession, product_id: int) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(ProductInfluencer, GlobalInfluencerProfile, Product)
        .join(GlobalInfluencerProfile, GlobalInfluencerProfile.id == ProductInfluencer.global_influencer_id)
        .join(Product, Product.id == ProductInfluencer.product_id)
        .where(ProductInfluencer.product_id == product_id)
        .order_by(ProductInfluencer.created_at.desc(), ProductInfluencer.id.desc())
        .limit(100)
    )
    return [_influencer_row(influencer, profile, product) for influencer, profile, product in rows]


async def _emails_for_product(db: AsyncSession, product_id: int) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(EmailLog, Product, User)
        .outerjoin(Product, Product.id == EmailLog.product_id)
        .outerjoin(User, User.id == EmailLog.user_id)
        .where(EmailLog.product_id == product_id)
        .order_by(EmailLog.sent_at.desc().nullslast(), EmailLog.id.desc())
        .limit(100)
    )
    return [_email_row(email, product, user) for email, product, user in rows]


async def _replies_for_product(db: AsyncSession, product_id: int) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(EmailReply, Product, User)
        .outerjoin(Product, Product.id == EmailReply.product_id)
        .outerjoin(User, User.id == EmailReply.user_id)
        .where(EmailReply.product_id == product_id)
        .order_by(EmailReply.received_at.desc(), EmailReply.id.desc())
        .limit(100)
    )
    return [_reply_row(reply, product, user) for reply, product, user in rows]
