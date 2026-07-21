# 文件说明：后端内部脚本入口，用于初始化、验收或数据处理；当前文件：admin sales data bootstrap
"""Bootstrap admin verification data for sales brand isolation.

The script is intentionally idempotent and only uses the existing application
tables. It does not send email; it writes outreach verification rows to
email_logs so the admin backend can read real database records.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.enums import CollectionTaskStatus, EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.outreach_send_queue import OutreachSendQueueItem
from app.models.product_influencer import ProductInfluencer
from app.models.product_influencer_source import ProductInfluencerSource
from app.models.tenant import Product, ProductMember, User, WorkspaceMember

WORKSPACE_ID = 1
SYSTEM_ADMIN_ID = 1
DEFAULT_PRODUCT_SLUG = "default"
VERIFY_COUNT_PER_BRAND = 20


@dataclass(frozen=True)
class SalesBrandAssignment:
    username: str
    name: str
    brand: str
    slug: str
    category: str
    keywords: tuple[str, ...]


SALES_BRAND_ASSIGNMENTS: tuple[SalesBrandAssignment, ...] = (
    SalesBrandAssignment("sales1", "\u73fa\u4e34", "EPEDAL24", "junlin-epedal24", "e-bike accessories", ("e-bike", "cycling", "commuter gear")),
    SalesBrandAssignment("sales2", "\u54c6\u83b1\u5a01", "Aquorix", "duolaiwei-aquorix", "water filtration", ("water filter", "hydration", "home wellness")),
    SalesBrandAssignment("sales3", "\u54c6\u83b1\u745e", "RecoverJoy", "duolairui-recoverjoy", "recovery wellness", ("recovery", "wellness", "self care")),
    SalesBrandAssignment("sales4", "\u94b1\u94b0", "Scandihome", "qianyu-scandihome", "home decor", ("scandinavian home", "home decor", "organization")),
    SalesBrandAssignment("sales5", "\u591a\u83b1\u8fbe", "ACESTRIKE", "duolaida-acestrike", "sports gear", ("pickleball", "training gear", "fitness")),
    SalesBrandAssignment("sales6", "\u6822\u535a", "P.travel", "baibo-p-travel", "travel accessories", ("travel packing", "carry on", "digital nomad")),
    SalesBrandAssignment("sales7", "OCE", "OCE GEAR", "oce-oce-gear", "outdoor gear", ("outdoor gear", "camping", "adventure")),
    SalesBrandAssignment("sales8", "\u73fa\u94b0", "P.TRAVEL DESIGN", "junyu-p-travel-design", "travel design", ("travel design", "packing cubes", "weekend trip")),
    SalesBrandAssignment("sales9", "\u591a\u83b1\u5409", "HOMEHIVE", "duolaiji-homehive", "home storage", ("home storage", "kitchen organization", "small space")),
    SalesBrandAssignment("sales10", "\u7396\u94b0", "BBCREAT", "jiuyu-bbcreat", "creative lifestyle", ("creator tools", "lifestyle desk", "craft storage")),
    SalesBrandAssignment("sales11", "\u5f18\u535a\u6717", "Hongbolang", "hongbolang", "brand placeholder", ("home lifestyle", "travel lifestyle", "daily essentials")),
)

REQUIRED_SALES_USERNAMES = tuple(item.username for item in SALES_BRAND_ASSIGNMENTS)
REQUIRED_BRAND_SLUGS = tuple(item.slug for item in SALES_BRAND_ASSIGNMENTS)

_HASH_SUFFIX_RE = re.compile(r"-[0-9a-f]{8}$", re.IGNORECASE)
_OBVIOUS_FAKE_SLUG_PREFIXES = (
    "test-product",
    "delete-test-product",
    "other-delete-test-product",
    "monthly-product",
    "monthlyprodect",
    "codex-",
    "qa-",
    "amazon-cross-b-",
)
_OBVIOUS_FAKE_USER_PREFIXES = (
    "codex-acceptance-",
    "qa-run-",
    "monthly_user_",
)


def is_obvious_test_product(*, name: str, slug: str, brand: str | None = None) -> bool:
    lowered = f"{name or ''} {slug or ''} {brand or ''}".lower()
    slug_text = (slug or "").strip().lower()

    if slug_text in {DEFAULT_PRODUCT_SLUG, *REQUIRED_BRAND_SLUGS}:
        return False
    if slug_text.startswith(_OBVIOUS_FAKE_SLUG_PREFIXES):
        return True
    if any(marker in lowered for marker in ("test product", "delete test product", "monthly product", "demo", "mock", "temp")):
        return True
    if "\u6d4b\u8bd5\u4ea7\u54c1" in lowered or "amazon\u8de8\u4ea7\u54c1b" in lowered:
        return True
    return bool(_HASH_SUFFIX_RE.search(slug_text) and ("test" in lowered or "amazon" in lowered))


def is_obvious_test_user(username: str) -> bool:
    return (username or "").lower().startswith(_OBVIOUS_FAKE_USER_PREFIXES)


async def _ensure_user(db: AsyncSession, assignment: SalesBrandAssignment) -> User:
    user = (
        await db.execute(select(User).where(User.username == assignment.username))
    ).scalar_one_or_none()
    if user is None:
        number = assignment.username.removeprefix("sales")
        user = User(
            username=assignment.username,
            display_name=f"\u4e1a\u52a1\u5458{number}",
            email=f"{assignment.username}@local",
            is_active=True,
            is_admin=False,
        )
        db.add(user)
        await db.flush()
    else:
        user.is_active = True
        user.is_admin = False
        if not user.email:
            user.email = f"{assignment.username}@local"

    membership_exists = await db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == WORKSPACE_ID,
            WorkspaceMember.user_id == user.id,
        )
    )
    if membership_exists is None:
        db.add(WorkspaceMember(workspace_id=WORKSPACE_ID, user_id=user.id, role="member"))
    return user


async def _ensure_product(db: AsyncSession, assignment: SalesBrandAssignment) -> Product:
    product = (
        await db.execute(
            select(Product).where(
                Product.workspace_id == WORKSPACE_ID,
                Product.slug == assignment.slug,
            )
        )
    ).scalar_one_or_none()
    if product is None:
        product = Product(
            workspace_id=WORKSPACE_ID,
            name=assignment.name,
            brand=assignment.brand,
            slug=assignment.slug,
            description=_product_description(assignment),
            is_default=False,
            is_archived=False,
            is_hidden=False,
            is_test=False,
            created_source="seed",
        )
        db.add(product)
        await db.flush()
    else:
        product.name = assignment.name
        product.brand = assignment.brand
        product.description = _product_description(assignment)
        product.is_default = False
        product.is_archived = False
        product.is_hidden = False
        product.is_test = False
        product.created_source = product.created_source or "seed"
    return product


def _product_description(assignment: SalesBrandAssignment) -> str:
    if assignment.slug == "hongbolang":
        return "Admin verification brand. Hongbolang is a temporary slug/English placeholder."
    return f"Admin verification brand for {assignment.brand}."


async def _set_exact_sales_membership(
    db: AsyncSession,
    *,
    user: User,
    product: Product,
) -> None:
    default_product_ids = (
        await db.execute(
            select(Product.id).where(or_(Product.is_default.is_(True), Product.slug == DEFAULT_PRODUCT_SLUG))
        )
    ).scalars().all()
    if default_product_ids:
        await db.execute(
            delete(ProductMember).where(
                ProductMember.user_id == user.id,
                ProductMember.product_id.in_(default_product_ids),
            )
        )

    other_brand_ids = (
        await db.execute(
            select(Product.id).where(
                Product.slug.in_(REQUIRED_BRAND_SLUGS),
                Product.id != product.id,
            )
        )
    ).scalars().all()
    if other_brand_ids:
        await db.execute(
            delete(ProductMember).where(
                ProductMember.user_id == user.id,
                ProductMember.product_id.in_(other_brand_ids),
            )
        )

    member = await db.scalar(
        select(ProductMember).where(
            ProductMember.user_id == user.id,
            ProductMember.product_id == product.id,
        )
    )
    if member is None:
        db.add(ProductMember(user_id=user.id, product_id=product.id, role="owner"))
    else:
        member.role = "owner"


async def _remove_non_admin_default_memberships(db: AsyncSession) -> int:
    default_product_ids = (
        await db.execute(
            select(Product.id).where(or_(Product.is_default.is_(True), Product.slug == DEFAULT_PRODUCT_SLUG))
        )
    ).scalars().all()
    if not default_product_ids:
        return 0
    result = await db.execute(
        delete(ProductMember)
        .where(ProductMember.product_id.in_(default_product_ids))
        .where(
            ProductMember.user_id.in_(
                select(User.id).where(User.is_admin.is_(False))
            )
        )
    )
    return int(result.rowcount or 0)


async def _fake_product_ids(db: AsyncSession) -> list[int]:
    rows = (await db.execute(select(Product))).scalars().all()
    fake_ids = []
    for product in rows:
        if product.slug in REQUIRED_BRAND_SLUGS or product.slug == DEFAULT_PRODUCT_SLUG:
            continue
        if product.created_source == "seed":
            fake_ids.append(product.id)
            continue
        if is_obvious_test_product(name=product.name, slug=product.slug, brand=product.brand):
            fake_ids.append(product.id)
    return fake_ids


async def _delete_fake_products(db: AsyncSession) -> dict[str, int]:
    product_ids = await _fake_product_ids(db)
    if not product_ids:
        return {"products": 0}

    product_influencer_ids = (
        await db.execute(
            select(ProductInfluencer.id).where(ProductInfluencer.product_id.in_(product_ids))
        )
    ).scalars().all()
    profile_ids = (
        await db.execute(
            select(ProductInfluencer.global_influencer_id).where(ProductInfluencer.product_id.in_(product_ids))
        )
    ).scalars().all()
    task_ids = (
        await db.execute(select(CollectionTask.id).where(CollectionTask.product_id.in_(product_ids)))
    ).scalars().all()
    email_ids = (
        await db.execute(
            select(EmailLog.id).where(
                or_(
                    EmailLog.product_id.in_(product_ids),
                    EmailLog.task_id.in_(task_ids or [-1]),
                    EmailLog.product_influencer_id.in_(product_influencer_ids or [-1]),
                )
            )
        )
    ).scalars().all()
    queue_ids = (
        await db.execute(
            select(OutreachSendQueueItem.id).where(
                or_(
                    OutreachSendQueueItem.product_id.in_(product_ids),
                    OutreachSendQueueItem.product_influencer_id.in_(product_influencer_ids or [-1]),
                    OutreachSendQueueItem.email_log_id.in_(email_ids or [-1]),
                    OutreachSendQueueItem.outreach_record_id.in_(email_ids or [-1]),
                )
            )
        )
    ).scalars().all()

    counts: dict[str, int] = {}
    counts["outreach_send_queue_children"] = await _bulk_delete_count(
        db,
        delete(OutreachSendQueueItem).where(
            OutreachSendQueueItem.parent_queue_id.in_(queue_ids or [-1])
        ),
    )
    counts["outreach_send_queue"] = await _bulk_delete_count(
        db,
        delete(OutreachSendQueueItem).where(OutreachSendQueueItem.id.in_(queue_ids or [-1])),
    )
    counts["email_replies"] = await _bulk_delete_count(
        db,
        delete(EmailReply).where(
            or_(
                EmailReply.product_id.in_(product_ids),
                EmailReply.email_log_id.in_(email_ids or [-1]),
                EmailReply.product_influencer_id.in_(product_influencer_ids or [-1]),
            )
        ),
    )
    counts["email_logs"] = await _bulk_delete_count(db, delete(EmailLog).where(EmailLog.id.in_(email_ids or [-1])))
    counts["product_influencer_sources"] = await _bulk_delete_count(
        db,
        delete(ProductInfluencerSource).where(
            or_(
                ProductInfluencerSource.product_influencer_id.in_(product_influencer_ids or [-1]),
                ProductInfluencerSource.task_id.in_(task_ids or [-1]),
            )
        ),
    )
    counts["collection_task_candidates"] = await _bulk_delete_count(
        db,
        delete(CollectionTaskCandidate).where(
            or_(
                CollectionTaskCandidate.product_id.in_(product_ids),
                CollectionTaskCandidate.task_id.in_(task_ids or [-1]),
                CollectionTaskCandidate.product_influencer_id.in_(product_influencer_ids or [-1]),
                CollectionTaskCandidate.global_influencer_id.in_(profile_ids or [-1]),
            )
        ),
    )
    counts["product_influencers"] = await _bulk_delete_count(
        db, delete(ProductInfluencer).where(ProductInfluencer.id.in_(product_influencer_ids or [-1]))
    )
    counts["collection_tasks"] = await _bulk_delete_count(db, delete(CollectionTask).where(CollectionTask.id.in_(task_ids or [-1])))
    counts["product_members"] = await _bulk_delete_count(db, delete(ProductMember).where(ProductMember.product_id.in_(product_ids)))
    counts["products"] = await _bulk_delete_count(db, delete(Product).where(Product.id.in_(product_ids)))
    if profile_ids:
        counts["global_influencer_profiles"] = await _bulk_delete_count(
            db,
            delete(GlobalInfluencerProfile).where(
                GlobalInfluencerProfile.id.in_(profile_ids),
                ~exists().where(ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id),
            ),
        )
    else:
        counts["global_influencer_profiles"] = 0
    return counts


async def _delete_fake_users(db: AsyncSession) -> int:
    user_ids = (
        await db.execute(
            select(User.id).where(
                or_(*[User.username.like(f"{prefix}%") for prefix in _OBVIOUS_FAKE_USER_PREFIXES])
            )
        )
    ).scalars().all()
    if not user_ids:
        return 0
    await db.execute(delete(ProductMember).where(ProductMember.user_id.in_(user_ids)))
    await db.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id.in_(user_ids)))
    await db.execute(delete(OutreachSendQueueItem).where(OutreachSendQueueItem.user_id.in_(user_ids)))
    await db.execute(delete(EmailReply).where(EmailReply.user_id.in_(user_ids)))
    await db.execute(delete(EmailLog).where(EmailLog.user_id.in_(user_ids)))
    await db.execute(delete(CollectionTask).where(CollectionTask.user_id.in_(user_ids)))
    result = await db.execute(delete(User).where(User.id.in_(user_ids)))
    return int(result.rowcount or 0)


async def _bulk_delete_count(db: AsyncSession, statement: Any) -> int:
    result = await db.execute(statement)
    return int(result.rowcount or 0)


async def _ensure_verification_data(
    db: AsyncSession,
    *,
    user: User,
    product: Product,
    assignment: SalesBrandAssignment,
) -> dict[str, int]:
    now = datetime.now(UTC)
    task_name = f"Admin verification seed - {assignment.slug}"
    task = (
        await db.execute(
            select(CollectionTask).where(
                CollectionTask.user_id == user.id,
                CollectionTask.product_id == product.id,
                CollectionTask.name == task_name,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        task = CollectionTask(
            user_id=user.id,
            workspace_id=WORKSPACE_ID,
            product_id=product.id,
            name=task_name,
            collection_mode="keyword",
            platform="instagram",
            platforms=["instagram"],
            keywords=list(assignment.keywords),
            category=assignment.category,
            discovery_limit=VERIFY_COUNT_PER_BRAND,
            status=CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
            last_run_at=now,
            result_count=VERIFY_COUNT_PER_BRAND,
            email_count=VERIFY_COUNT_PER_BRAND,
            discovered_count=VERIFY_COUNT_PER_BRAND,
            inserted_count=VERIFY_COUNT_PER_BRAND,
            success_count=VERIFY_COUNT_PER_BRAND,
            processed_count=VERIFY_COUNT_PER_BRAND,
            total_estimate=VERIFY_COUNT_PER_BRAND,
            status_summary="Admin verification data only; no live email was sent.",
        )
        db.add(task)
        await db.flush()
    else:
        task.status = CollectionTaskStatus.COMPLETED_WITH_RESULTS.value
        task.platform = "instagram"
        task.platforms = ["instagram"]
        task.keywords = list(assignment.keywords)
        task.category = assignment.category
        task.result_count = VERIFY_COUNT_PER_BRAND
        task.email_count = VERIFY_COUNT_PER_BRAND
        task.discovered_count = VERIFY_COUNT_PER_BRAND
        task.inserted_count = VERIFY_COUNT_PER_BRAND
        task.success_count = VERIFY_COUNT_PER_BRAND
        task.processed_count = VERIFY_COUNT_PER_BRAND
        task.total_estimate = VERIFY_COUNT_PER_BRAND
        task.last_run_at = task.last_run_at or now

    created = {"profiles": 0, "product_influencers": 0, "email_logs": 0, "email_replies": 0}
    slug_token = assignment.slug.replace("-", "_")
    for index in range(1, VERIFY_COUNT_PER_BRAND + 1):
        username = f"{slug_token}_creator_{index:02d}"
        profile_url = f"https://www.instagram.com/{username}"
        profile = (
            await db.execute(
                select(GlobalInfluencerProfile).where(
                    GlobalInfluencerProfile.platform == "instagram",
                    GlobalInfluencerProfile.normalized_profile_url == profile_url,
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            profile = GlobalInfluencerProfile(
                platform="instagram",
                platform_unique_id=f"admin-verify-{assignment.slug}-{index:02d}",
                username=username,
                normalized_username=username,
                display_name=f"{assignment.brand} Creator {index:02d}",
                profile_url=profile_url,
                normalized_profile_url=profile_url,
                category=assignment.category,
                niche=assignment.keywords[0],
                bio=f"Creator focused on {assignment.category} for admin verification.",
                followers_count=8_000 + index * 750,
                avg_views=2_000 + index * 90,
                engagement_rate=0.035 + index / 10_000,
                email=f"{username}@example.test",
                final_email=f"{username}@example.test",
                email_source="admin_verification_seed",
                contact_fetch_status="success",
                content_topics=list(assignment.keywords),
                data_completeness=0.9,
            )
            db.add(profile)
            await db.flush()
            created["profiles"] += 1

        product_influencer = (
            await db.execute(
                select(ProductInfluencer).where(
                    ProductInfluencer.product_id == product.id,
                    ProductInfluencer.global_influencer_id == profile.id,
                )
            )
        ).scalar_one_or_none()
        if product_influencer is None:
            product_influencer = ProductInfluencer(
                product_id=product.id,
                global_influencer_id=profile.id,
                score=82 + (index % 12),
                product_fit=0.8,
                engagement_score=0.75,
                contactability_score=0.95,
                final_priority="high" if index <= 8 else "medium",
                follow_status="contacted",
                owner=user.username,
                source_discovery_type="admin_verification_seed",
                first_inserted_at=now - timedelta(days=1),
                last_collected_at=now,
            )
            db.add(product_influencer)
            await db.flush()
            created["product_influencers"] += 1

        message_id = f"admin-verify-{assignment.slug}-{index:02d}@local"
        email_log = (
            await db.execute(
                select(EmailLog).where(
                    EmailLog.product_id == product.id,
                    EmailLog.message_id == message_id,
                )
            )
        ).scalar_one_or_none()
        if email_log is None:
            email_log = EmailLog(
                user_id=user.id,
                product_id=product.id,
                task_id=task.id,
                product_influencer_id=product_influencer.id,
                sender_email=f"{assignment.username}@brand.local",
                influencer_username=username,
                recipients=[f"{username}@example.test"],
                subject=f"{assignment.brand} collaboration idea",
                body="Admin verification outreach record. No live email was sent.",
                status=EmailLogStatus.SENT.value,
                generated_by_ai=True,
                ai_provider="verification_seed",
                sent_at=now - timedelta(hours=index),
                message_id=message_id,
                last_outbound_at=now - timedelta(hours=index),
            )
            db.add(email_log)
            await db.flush()
            created["email_logs"] += 1

        if index in {3, 8, 13, 18}:
            reply_message_id = f"admin-verify-reply-{assignment.slug}-{index:02d}@local"
            reply = (
                await db.execute(
                    select(EmailReply).where(EmailReply.message_id == reply_message_id)
                )
            ).scalar_one_or_none()
            if reply is None:
                reply = EmailReply(
                    product_id=product.id,
                    user_id=user.id,
                    email_log_id=email_log.id,
                    product_influencer_id=product_influencer.id,
                    message_id=reply_message_id,
                    in_reply_to=message_id,
                    match_method="admin_verification_seed",
                    processing_status="unprocessed",
                    intent_status="positive",
                    source="seed",
                    from_address=f"{username}@example.test",
                    to_address=f"{assignment.username}@brand.local",
                    subject=f"Re: {assignment.brand} collaboration idea",
                    body="Interested in learning more.",
                    snippet="Interested in learning more.",
                    raw_headers={"seed": "admin_verification"},
                    received_at=now - timedelta(minutes=index),
                )
                db.add(reply)
                await db.flush()
                email_log.has_replied = True
                email_log.replied_at = reply.received_at
                email_log.reply_email_log_id = reply.id
                created["email_replies"] += 1

    return created


async def bootstrap_sales_admin_data() -> dict[str, Any]:
    async with async_session_factory() as db:
        removed_default_memberships = await _remove_non_admin_default_memberships(db)
        deleted_products = await _delete_fake_products(db)
        deleted_users = await _delete_fake_users(db)

        seeded: dict[str, dict[str, int]] = {}
        for assignment in SALES_BRAND_ASSIGNMENTS:
            user = await _ensure_user(db, assignment)
            product = await _ensure_product(db, assignment)
            await _set_exact_sales_membership(db, user=user, product=product)
            seeded[assignment.slug] = await _ensure_verification_data(
                db,
                user=user,
                product=product,
                assignment=assignment,
            )

        await db.commit()
        return {
            "removed_default_memberships": removed_default_memberships,
            "deleted_products": deleted_products,
            "deleted_users": deleted_users,
            "seeded": seeded,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap admin sales verification data.")
    parser.parse_args()
    result = asyncio.run(bootstrap_sales_admin_data())
    print(result)


if __name__ == "__main__":
    main()
