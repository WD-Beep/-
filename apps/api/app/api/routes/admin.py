# 文件说明：后端接口路由，负责接收前端请求并调用对应业务逻辑；当前文件：admin
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps.tenant import UserContext, get_user_context
from app.models.admin_audit_log import AdminAuditLog
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.link_import_batch import LinkImportBatch
from app.models.link_knowledge_base import LinkKnowledgeBase
from app.models.manual_outreach_email import ManualOutreachEmail
from app.models.message_template import MessageTemplate
from app.models.outreach_email_campaign import OutreachEmailCampaign
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product, ProductMember, User, WorkspaceMember
from app.scheduler import refresh_scheduler
from app.schemas.collection_task import CollectionTaskBulkDelete, CollectionTaskBulkDeleteResult
from app.services.collection_task import CollectionTaskService
from app.services.auth_service import hash_password
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

SUCCESS_TASK_STATUSES = {"completed", "completed_with_results", "completed_no_results"}
FAILED_TASK_STATUSES = {"failed", "partial_failed"}


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    role: str = Field(default="sales", pattern=r"^(admin|sales)$")
    is_active: bool = True
    product_ids: list[int] = Field(default_factory=list)


class AdminUserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, pattern=r"^(admin|sales)$")
    is_active: bool | None = None


class AdminPasswordReset(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class AdminProductAssignments(BaseModel):
    product_ids: list[int] = Field(default_factory=list)


class AdminUserDeleteResult(BaseModel):
    success: bool
    deleted_user_id: int
    released_products: int
    released_tasks: int
    cancelled_campaigns: int
    cancelled_queue_items: int
    preserved_history_records: bool
    preserved_history_count: int


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


async def _replace_product_assignments(db: AsyncSession, user: User, product_ids: list[int]) -> None:
    unique_ids = list(dict.fromkeys(product_ids))
    if unique_ids:
        valid_ids = set(
            (await db.execute(select(Product.id).where(Product.id.in_(unique_ids)))).scalars().all()
        )
        missing = [product_id for product_id in unique_ids if product_id not in valid_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"品牌不存在：{', '.join(map(str, missing))}")
    existing = {
        membership.product_id: membership
        for membership in (
            await db.execute(select(ProductMember).where(ProductMember.user_id == user.id))
        ).scalars().all()
    }
    for product_id, membership in existing.items():
        if product_id not in unique_ids:
            await db.delete(membership)
    for product_id in unique_ids:
        if product_id not in existing:
            db.add(ProductMember(user_id=user.id, product_id=product_id, role="owner"))


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


async def _user_summaries(db: AsyncSession, users: list[User]) -> list[dict[str, Any]]:
    if not users:
        return []
    today = _today_start()
    user_ids = [user.id for user in users]

    bound_by_user: dict[int, list[dict[str, Any]]] = {user_id: [] for user_id in user_ids}
    product_ids_by_user: dict[int, list[int]] = {user_id: [] for user_id in user_ids}
    membership_rows = await db.execute(
        select(ProductMember, Product)
        .join(Product, Product.id == ProductMember.product_id)
        .where(ProductMember.user_id.in_(user_ids))
        .order_by(Product.created_at.desc(), Product.id.desc())
    )
    for member, product in membership_rows:
        product_ids_by_user.setdefault(member.user_id, []).append(product.id)
        bound_by_user.setdefault(member.user_id, []).append(
            {
                "id": product.id,
                "name": product.name,
                "slug": product.slug,
                "role": member.role,
                "status": _status_for_product(product),
                "created_at": product.created_at,
            }
        )

    task_rows = await db.execute(
        select(
            CollectionTask.user_id,
            func.count(CollectionTask.id).label("total"),
            func.count(CollectionTask.id).filter(CollectionTask.created_at >= today).label("today"),
            func.count(CollectionTask.id).filter(CollectionTask.status.in_(SUCCESS_TASK_STATUSES)).label("success"),
            func.count(CollectionTask.id).filter(CollectionTask.status.in_(FAILED_TASK_STATUSES)).label("failed"),
            func.max(CollectionTask.updated_at).label("last_at"),
        )
        .where(CollectionTask.user_id.in_(user_ids))
        .group_by(CollectionTask.user_id)
    )
    task_stats = {row.user_id: row for row in task_rows if row.user_id is not None}

    influencer_rows = await db.execute(
        select(
            ProductMember.user_id,
            func.count(ProductInfluencer.id).label("total"),
            func.count(ProductInfluencer.id).filter(ProductInfluencer.created_at >= today).label("today"),
        )
        .join(ProductInfluencer, ProductInfluencer.product_id == ProductMember.product_id)
        .where(ProductMember.user_id.in_(user_ids))
        .group_by(ProductMember.user_id)
    )
    influencer_stats = {row.user_id: row for row in influencer_rows}

    email_rows = await db.execute(
        select(
            EmailLog.user_id,
            func.count(EmailLog.id).label("total"),
            func.count(EmailLog.id).filter(EmailLog.status == "failed").label("failed"),
            func.max(EmailLog.sent_at).label("last_at"),
        )
        .where(EmailLog.user_id.in_(user_ids))
        .group_by(EmailLog.user_id)
    )
    email_stats = {row.user_id: row for row in email_rows if row.user_id is not None}

    reply_rows = await db.execute(
        select(
            EmailReply.user_id,
            func.count(EmailReply.id).label("total"),
            func.count(EmailReply.id).filter(EmailReply.processing_status == "unprocessed").label("pending"),
            func.max(EmailReply.received_at).label("last_at"),
        )
        .where(EmailReply.user_id.in_(user_ids))
        .group_by(EmailReply.user_id)
    )
    reply_stats = {row.user_id: row for row in reply_rows if row.user_id is not None}

    membership_last_rows = await db.execute(
        select(ProductMember.user_id, func.max(ProductMember.updated_at).label("last_at"))
        .where(ProductMember.user_id.in_(user_ids))
        .group_by(ProductMember.user_id)
    )
    membership_last = {row.user_id: row.last_at for row in membership_last_rows}

    summaries: list[dict[str, Any]] = []
    for user in users:
        user_task = task_stats.get(user.id)
        user_influencer = influencer_stats.get(user.id)
        user_email = email_stats.get(user.id)
        user_reply = reply_stats.get(user.id)
        product_ids = product_ids_by_user.get(user.id, [])
        summaries.append(
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "role": "admin" if user.is_admin else "sales",
                "is_admin": user.is_admin,
                "is_active": user.is_active,
                "product_count": len(product_ids),
                "bound_products": bound_by_user.get(user.id, []),
                "collection_task_count": int(user_task.total or 0) if user_task else 0,
                "today_collection_task_count": int(user_task.today or 0) if user_task else 0,
                "collection_success_count": int(user_task.success or 0) if user_task else 0,
                "collection_failed_count": int(user_task.failed or 0) if user_task else 0,
                "influencer_count": int(user_influencer.total or 0) if user_influencer else 0,
                "today_influencer_count": int(user_influencer.today or 0) if user_influencer else 0,
                "email_count": int(user_email.total or 0) if user_email else 0,
                "email_failed_count": int(user_email.failed or 0) if user_email else 0,
                "reply_count": int(user_reply.total or 0) if user_reply else 0,
                "pending_reply_count": int(user_reply.pending or 0) if user_reply else 0,
                "last_active_at": _latest(
                    [
                        user.updated_at,
                        user_task.last_at if user_task else None,
                        user_email.last_at if user_email else None,
                        user_reply.last_at if user_reply else None,
                        membership_last.get(user.id),
                    ]
                ),
                "created_at": user.created_at,
                "updated_at": user.updated_at,
                "status": "active" if user.is_active else "disabled",
            }
        )
    return summaries


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


async def _product_summaries(db: AsyncSession, products: list[Product]) -> list[dict[str, Any]]:
    if not products:
        return []
    product_ids = [product.id for product in products]
    members_by_product: dict[int, list[dict[str, Any]]] = {product_id: [] for product_id in product_ids}
    member_rows = await db.execute(
        select(ProductMember, User)
        .join(User, User.id == ProductMember.user_id)
        .where(ProductMember.product_id.in_(product_ids))
        .order_by(ProductMember.role.desc(), User.id.asc())
    )
    for member, user in member_rows:
        members_by_product.setdefault(member.product_id, []).append(
            {
                "id": member.id,
                "user_id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": member.role,
                "created_at": member.created_at,
            }
        )

    async def grouped_counts(model: Any, column: Any) -> dict[int, int]:
        rows = await db.execute(
            select(column, func.count(model.id).label("total"))
            .where(column.in_(product_ids))
            .group_by(column)
        )
        return {int(row[0]): int(row.total or 0) for row in rows}

    task_counts = await grouped_counts(CollectionTask, CollectionTask.product_id)
    influencer_counts = await grouped_counts(ProductInfluencer, ProductInfluencer.product_id)
    email_counts = await grouped_counts(EmailLog, EmailLog.product_id)
    reply_counts = await grouped_counts(EmailReply, EmailReply.product_id)

    summaries: list[dict[str, Any]] = []
    for product in products:
        members = members_by_product.get(product.id, [])
        summaries.append(
            {
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
                "collection_task_count": task_counts.get(product.id, 0),
                "influencer_count": influencer_counts.get(product.id, 0),
                "email_count": email_counts.get(product.id, 0),
                "reply_count": reply_counts.get(product.id, 0),
                "status": _status_for_product(product),
            }
        )
    return summaries


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
    return await _user_summaries(db, users)


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    data: AdminUserCreate,
    ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    username = data.username.strip()
    user = User(
        username=username,
        display_name=data.display_name.strip() if data.display_name else None,
        email=data.email.strip() if data.email else None,
        is_admin=data.role == "admin",
        is_active=data.is_active,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    try:
        await db.flush()
        admin_workspace_id = await db.scalar(
            select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == ctx.user_id).limit(1)
        )
        workspace_id = admin_workspace_id or await db.scalar(select(Product.workspace_id).limit(1)) or 1
        db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="admin" if user.is_admin else "member"))
        await _replace_product_assignments(db, user, data.product_ids if not user.is_admin else [])
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    await db.refresh(user)
    return await _user_summary(db, user)


@router.patch("/users/{user_id}")
async def update_admin_user(
    user_id: int,
    data: AdminUserUpdate,
    ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == ctx.user_id and data.is_active is False:
        raise HTTPException(status_code=409, detail="不能禁用当前登录的管理员账号")
    if user.id == ctx.user_id and data.role == "sales":
        raise HTTPException(status_code=409, detail="不能移除当前登录账号的管理员权限")
    if data.username is not None:
        next_username = data.username.strip()
        if next_username != user.username:
            if user.id == ctx.user_id:
                raise HTTPException(status_code=409, detail="不能修改当前登录账号的用户名")
            user.username = next_username
    if data.display_name is not None:
        user.display_name = data.display_name.strip() or None
    if "email" in data.model_fields_set:
        user.email = data.email.strip() if data.email else None
    if data.role is not None:
        user.is_admin = data.role == "admin"
    if data.is_active is not None:
        user.is_active = data.is_active
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    await db.refresh(user)
    return await _user_summary(db, user)


@router.delete("/users/{user_id}", response_model=AdminUserDeleteResult)
async def delete_admin_user(
    user_id: int,
    ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserDeleteResult:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == ctx.user_id:
        raise HTTPException(status_code=409, detail="不能删除当前登录的管理员账号")

    product_ids = await _product_ids_for_user(db, user.id)
    collection_task_count = await _count(
        db, select(func.count(CollectionTask.id)).where(CollectionTask.user_id == user.id)
    )
    candidate_count = await _count(
        db,
        select(func.count(CollectionTaskCandidate.id)).where(
            CollectionTaskCandidate.user_id == user.id
        ),
    )
    email_count = await _count(db, select(func.count(EmailLog.id)).where(EmailLog.user_id == user.id))
    reply_count = await _count(db, select(func.count(EmailReply.id)).where(EmailReply.user_id == user.id))
    manual_email_count = await _count(
        db,
        select(func.count(ManualOutreachEmail.id)).where(ManualOutreachEmail.user_id == user.id),
    )
    link_base_count = await _count(
        db,
        select(func.count(LinkKnowledgeBase.id)).where(LinkKnowledgeBase.user_id == user.id),
    )
    link_import_count = await _count(
        db,
        select(func.count(LinkImportBatch.id)).where(LinkImportBatch.user_id == user.id),
    )
    campaign_count = await _count(
        db,
        select(func.count(OutreachEmailCampaign.id)).where(
            OutreachEmailCampaign.user_id == user.id
        ),
    )
    queue_count = await _count(
        db,
        select(func.count(OutreachSendQueueItem.id)).where(
            OutreachSendQueueItem.user_id == user.id
        ),
    )
    active_campaign_count = await _count(
        db,
        select(func.count(OutreachEmailCampaign.id)).where(
            OutreachEmailCampaign.user_id == user.id,
            OutreachEmailCampaign.status.not_in(("cancelled", "completed")),
        ),
    )
    active_queue_count = await _count(
        db,
        select(func.count(OutreachSendQueueItem.id)).where(
            OutreachSendQueueItem.user_id == user.id,
            OutreachSendQueueItem.status.in_(("queued", "scheduled", "sending")),
        ),
    )
    template_count = await _count(
        db,
        select(func.count(MessageTemplate.id)).where(MessageTemplate.user_id == user.id),
    )
    influencer_count = 0
    if product_ids:
        influencer_count = await _count(
            db,
            select(func.count(ProductInfluencer.id)).where(ProductInfluencer.product_id.in_(product_ids)),
        )

    preserved_history_count = sum(
        (
            collection_task_count,
            candidate_count,
            influencer_count,
            email_count,
            reply_count,
            manual_email_count,
            link_base_count,
            link_import_count,
            campaign_count,
            queue_count,
        )
    )
    actor = await db.get(User, ctx.user_id)
    details = {
        "released_products": len(product_ids),
        "released_tasks": collection_task_count,
        "cancelled_campaigns": active_campaign_count,
        "cancelled_queue_items": active_queue_count,
        "preserved_influencers": influencer_count,
        "preserved_emails": email_count,
        "preserved_replies": reply_count,
        "preserved_manual_emails": manual_email_count,
        "preserved_link_bases": link_base_count,
        "preserved_link_imports": link_import_count,
        "preserved_campaigns": campaign_count,
        "preserved_queue_items": queue_count,
        "deleted_private_templates": template_count,
    }

    try:
        await db.execute(
            update(OutreachEmailCampaign)
            .where(
                OutreachEmailCampaign.user_id == user.id,
                OutreachEmailCampaign.status.not_in(("cancelled", "completed")),
            )
            .values(
                status="cancelled",
                auto_send_enabled=False,
                next_auto_process_at=None,
            )
        )
        await db.execute(
            update(OutreachEmailCampaign)
            .where(OutreachEmailCampaign.user_id == user.id)
            .values(user_id=None, auto_send_enabled=False, next_auto_process_at=None)
        )
        await db.execute(
            update(OutreachSendQueueItem)
            .where(
                OutreachSendQueueItem.user_id == user.id,
                OutreachSendQueueItem.status.in_(("queued", "scheduled", "sending")),
            )
            .values(
                status="cancelled",
                locked_at=None,
                next_retry_at=None,
            )
        )
        await db.execute(
            update(OutreachSendQueueItem)
            .where(OutreachSendQueueItem.user_id == user.id)
            .values(user_id=None)
        )
        for model in (
            CollectionTask,
            CollectionTaskCandidate,
            EmailLog,
            EmailReply,
            ManualOutreachEmail,
            LinkKnowledgeBase,
            LinkImportBatch,
        ):
            await db.execute(update(model).where(model.user_id == user.id).values(user_id=None))

        await db.execute(delete(ProductMember).where(ProductMember.user_id == user.id))
        await db.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
        await db.execute(delete(MessageTemplate).where(MessageTemplate.user_id == user.id))
        db.add(
            AdminAuditLog(
                action="admin_user_deleted",
                actor_user_id=ctx.user_id,
                actor_username=actor.username if actor else f"user:{ctx.user_id}",
                target_user_id=user.id,
                target_username=user.username,
                target_display_name=user.display_name,
                details=details,
            )
        )
        await db.delete(user)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.exception("Admin user deletion blocked by database association", extra={"user_id": user_id})
        raise HTTPException(
            status_code=409,
            detail="删除业务员失败：仍存在无法安全解除的数据库关联，所有更改已回滚。",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Admin user deletion failed", extra={"user_id": user_id})
        raise HTTPException(
            status_code=500,
            detail="删除业务员失败，所有更改已回滚，请查看服务器日志。",
        ) from exc

    return AdminUserDeleteResult(
        success=True,
        deleted_user_id=user_id,
        released_products=len(product_ids),
        released_tasks=collection_task_count,
        cancelled_campaigns=active_campaign_count,
        cancelled_queue_items=active_queue_count,
        preserved_history_records=True,
        preserved_history_count=preserved_history_count,
    )


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_admin_user_password(
    user_id: int,
    data: AdminPasswordReset,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(data.password)
    await db.commit()


@router.put("/users/{user_id}/products")
async def set_admin_user_products(
    user_id: int,
    data: AdminProductAssignments,
    _ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await _replace_product_assignments(db, user, data.product_ids)
    await db.commit()
    return await _user_summary(db, user)


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
    return await _product_summaries(db, products)


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


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_product(
    product_id: int,
    ctx: UserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await TenantService.delete_product(
        db,
        user_id=ctx.user_id,
        is_admin=True,
        product_id=product_id,
    )


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
