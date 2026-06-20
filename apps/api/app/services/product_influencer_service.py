"""产品维度红人库查询（隔离 + 全局资料投影）。"""

from __future__ import annotations

import math
from dataclasses import fields
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, not_, or_, select, exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer

from app.collectors.base import CollectedInfluencer
from app.schemas.common import PaginatedResponse
from app.schemas.influencer import (
    InfluencerCreate,
    InfluencerFilter,
    InfluencerRead,
    InfluencerUpdate,
    PlatformStatItem,
    PlatformStatsResponse,
)
from app.services.influencer_lead import CONTACTED_STATUSES, EXCLUDED_FROM_TODAY, TODAY_RECOMMENDED_STATUSES
from app.services.influencer_persistence import (
    InfluencerPersistenceService,
    apply_global_profile_data,
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
    identity_key_for_item,
)
from app.services.influencer_projection import to_influencer_read
from app.services.influencer_source import InfluencerSourceService
from app.services.email_sent_status import load_email_sent_map, successful_email_sent_exists
from app.services.platform_utils import normalize_profile_url
from app.services.tenant_scope import ALL_PRODUCTS_ID

PRIMARY_PLATFORMS: tuple[str, ...] = ("tiktok", "youtube", "instagram", "facebook")
LINK_IMPORT_STAT_PLATFORMS: tuple[str, ...] = ("pinterest", "ltk", "shopmy")
ALL_STAT_PLATFORMS: tuple[str, ...] = PRIMARY_PLATFORMS + LINK_IMPORT_STAT_PLATFORMS

_COLLECTED_INFLUENCER_FIELDS = frozenset(field.name for field in fields(CollectedInfluencer))

_PRODUCT_UPDATE_FIELDS = frozenset(
    {
        "product_fit",
        "travel_fit_score",
        "purchasing_power_score",
        "sales_potential_score",
        "audience_match_score",
        "roi_forecast",
        "engagement_score",
        "content_match_score",
        "contactability_score",
        "commercial_signal_score",
        "activity_score",
        "risk_score",
        "final_priority",
        "score",
        "risk_level",
        "score_reason",
        "ai_summary",
        "ai_collaboration_suggestion",
        "ai_outreach_message",
        "tags",
        "follow_status",
        "owner",
        "note",
        "next_follow_up_at",
        "last_contacted_at",
        "last_reply_at",
        "invalid_reason",
        "blacklist_reason",
        "last_collected_at",
    }
)


class ProductInfluencerService:
    @staticmethod
    def _inserted_scope(product_id: int, *, PI=ProductInfluencer):
        if product_id == ALL_PRODUCTS_ID:
            return PI.is_inserted.is_(True)
        return (PI.product_id == product_id) & PI.is_inserted.is_(True)

    @staticmethod
    def _base_join(product_id: int):
        return (
            select(ProductInfluencer, GlobalInfluencerProfile)
            .join(GlobalInfluencerProfile, ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id)
            .where(ProductInfluencerService._inserted_scope(product_id))
        )

    @staticmethod
    def _apply_filters(
        query,
        filters: InfluencerFilter,
        *,
        product_id: int | None = None,
        PI=ProductInfluencer,
        GP=GlobalInfluencerProfile,
    ):
        min_score = filters.min_score
        if filters.high_match:
            query = query.where(
                or_(PI.final_priority.in_(("P0", "P1")), PI.score >= 75.0)
            )
            min_score = max(min_score or 0, 62.0)

        if filters.platform == "other":
            query = query.where(~GP.platform.in_(("tiktok", "youtube", "instagram", "facebook")))
        elif filters.platform:
            query = query.where(GP.platform == filters.platform)
        if filters.country:
            query = query.where(GP.country == filters.country)
        if filters.category:
            query = query.where(GP.category == filters.category)

        status = filters.lead_status or filters.follow_status
        if status:
            query = query.where(PI.follow_status == status)
        if filters.lead_priority:
            query = query.where(PI.final_priority == filters.lead_priority)
        if filters.owner_name:
            query = query.where(PI.owner == filters.owner_name)
        if filters.source_discovery_type:
            query = query.where(PI.source_discovery_type == filters.source_discovery_type)
        if filters.high_priority:
            query = query.where(PI.final_priority.in_(("P0", "P1")))
        if filters.unassigned:
            query = query.where(or_(PI.owner.is_(None), PI.owner == ""))
        if filters.pending_follow_up:
            today_end = datetime.now(UTC).replace(hour=23, minute=59, second=59, microsecond=999999)
            excluded = tuple(EXCLUDED_FROM_TODAY)
            query = query.where(
                PI.next_follow_up_at.isnot(None),
                PI.next_follow_up_at <= today_end,
                or_(PI.follow_status.is_(None), ~PI.follow_status.in_(excluded)),
            )
        if filters.today_recommended:
            allowed = tuple(TODAY_RECOMMENDED_STATUSES)
            excluded = tuple(EXCLUDED_FROM_TODAY | CONTACTED_STATUSES)
            query = query.where(or_(PI.follow_status.in_(allowed), PI.follow_status.is_(None)))
            query = query.where(or_(PI.follow_status.is_(None), ~PI.follow_status.in_(excluded)))
        if min_score is not None:
            query = query.where(PI.score >= min_score)
        if filters.min_product_fit is not None:
            query = query.where(PI.product_fit >= filters.min_product_fit)
        if filters.has_email:
            query = query.where(
                or_(
                    GP.final_email.isnot(None),
                    GP.email.isnot(None),
                    GP.public_email.isnot(None),
                    GP.business_email.isnot(None),
                )
            )
        has_contact = or_(
            GP.final_email.isnot(None),
            GP.email.isnot(None),
            GP.public_email.isnot(None),
            GP.business_email.isnot(None),
            GP.website.isnot(None),
            GP.contact_page.isnot(None),
            GP.linktree_url.isnot(None),
            GP.whatsapp.isnot(None),
            GP.telegram.isnot(None),
        )
        if filters.contactable:
            query = query.where(has_contact)
        if filters.high_value:
            query = query.where(or_(PI.final_priority.in_(("P0", "P1")), PI.score >= 62.0))
        if filters.value_tier == "direct_contact":
            query = query.where(has_contact)
        elif filters.value_tier == "manual_research":
            query = query.where(or_(PI.product_fit >= 60.0, PI.commercial_signal_score >= 50.0))
        elif filters.value_tier == "skip":
            query = query.where(and_(~has_contact, or_(PI.score.is_(None), PI.score < 50.0)))
        if filters.missing_contact:
            query = query.where(not_(has_contact))
        if filters.high_credibility_contact:
            query = query.where(or_(GP.contact_credibility_level == "high", GP.contact_score >= 75.0))
        if filters.search:
            term = f"%{filters.search}%"
            query = query.where(
                or_(
                    GP.username.ilike(term),
                    GP.display_name.ilike(term),
                    GP.bio.ilike(term),
                    GP.email.ilike(term),
                    GP.final_email.ilike(term),
                )
            )
        if filters.collection_task_id:
            inserted_for_task = exists(
                select(1).where(
                    CollectionTaskCandidate.product_influencer_id == PI.id,
                    CollectionTaskCandidate.task_id == filters.collection_task_id,
                    CollectionTaskCandidate.status == "inserted",
                )
            )
            query = query.where(inserted_for_task)
        if filters.created_within_hours:
            cutoff = datetime.now(UTC) - timedelta(hours=filters.created_within_hours)
            query = query.where(PI.created_at >= cutoff)
        if filters.collected_within_days:
            cutoff = datetime.now(UTC) - timedelta(days=filters.collected_within_days)
            query = query.where(PI.last_collected_at >= cutoff)
        if filters.email_status in ("sent", "unsent") and product_id is not None:
            sent_exists = successful_email_sent_exists(product_id, PI=PI, GP=GP)
            if filters.email_status == "sent":
                query = query.where(sent_exists)
            else:
                query = query.where(not_(sent_exists))
        return query

    @staticmethod
    async def list_influencers(
        db: AsyncSession,
        *,
        product_id: int,
        filters: InfluencerFilter,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[InfluencerRead]:
        base_query = ProductInfluencerService._apply_filters(
            ProductInfluencerService._base_join(product_id), filters, product_id=product_id
        )
        total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
        total = total or 0
        PI, GP = ProductInfluencer, GlobalInfluencerProfile
        if filters.pending_follow_up:
            ordering = (PI.next_follow_up_at.asc().nullslast(), PI.last_collected_at.desc().nullslast(), PI.id.desc())
        else:
            ordering = (PI.last_collected_at.desc().nullslast(), PI.id.desc())
        query = base_query.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
        rows = (await db.execute(query)).all()
        influencer_ids = [pi.id for pi, _gp in rows]
        sources_by_id = await InfluencerSourceService.list_for_product_influencers(db, influencer_ids)
        email_sent_map = await load_email_sent_map(
            db,
            product_id=product_id,
            product_influencer_ids=influencer_ids,
        )
        items = []
        for pi, gp in rows:
            read = to_influencer_read(pi, gp, sources=sources_by_id.get(pi.id, []))
            sent_info = email_sent_map.get(pi.id)
            if sent_info:
                read = read.model_copy(
                    update={
                        "email_sent": sent_info.email_sent,
                        "last_email_sent_at": sent_info.last_email_sent_at,
                        "last_email_subject": sent_info.last_email_subject,
                    }
                )
            items.append(read)
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def influencer_read_with_sources(
        db: AsyncSession,
        product_row: ProductInfluencer,
        global_row: GlobalInfluencerProfile,
    ) -> InfluencerRead:
        sources_map = await InfluencerSourceService.list_for_product_influencers(
            db, [product_row.id]
        )
        read = to_influencer_read(
            product_row,
            global_row,
            sources=sources_map.get(product_row.id, []),
        )
        email_sent_map = await load_email_sent_map(
            db,
            product_id=product_row.product_id,
            product_influencer_ids=[product_row.id],
        )
        sent_info = email_sent_map.get(product_row.id)
        if sent_info:
            read = read.model_copy(
                update={
                    "email_sent": sent_info.email_sent,
                    "last_email_sent_at": sent_info.last_email_sent_at,
                    "last_email_subject": sent_info.last_email_subject,
                }
            )
        return read

    @staticmethod
    async def get_product_influencer(
        db: AsyncSession,
        *,
        product_id: int,
        record_id: int,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile] | None:
        row = await db.execute(
            ProductInfluencerService._base_join(product_id).where(ProductInfluencer.id == record_id)
        )
        pair = row.first()
        return pair if pair else None

    @staticmethod
    def _create_collected_from_schema(data: InfluencerCreate) -> CollectedInfluencer:
        payload = data.model_dump(mode="json")
        for field in ("website", "contact_page", "linktree_url", "profile_url"):
            if payload.get(field) is not None:
                payload[field] = str(payload[field])
        for field in ("email", "final_email", "public_email", "business_email"):
            if payload.get(field) is not None:
                payload[field] = str(payload[field])
        filtered = {key: value for key, value in payload.items() if key in _COLLECTED_INFLUENCER_FIELDS}
        return CollectedInfluencer(**filtered)

    @staticmethod
    async def create_influencer(
        db: AsyncSession,
        *,
        product_id: int,
        data: InfluencerCreate,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile]:
        from datetime import UTC, datetime

        run_at = datetime.now(UTC)
        item = ProductInfluencerService._create_collected_from_schema(data)
        global_map = await InfluencerPersistenceService.find_global_profiles_batch(db, [item])
        global_profile = global_map.get(identity_key_for_item(item))
        if not global_profile:
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db.add(global_profile)
            await db.flush()
        else:
            apply_global_profile_data(global_profile, item, run_at=run_at)

        product_map = await InfluencerPersistenceService.find_product_influencers_batch(
            db, product_id, [item], global_map={identity_key_for_item(item): global_profile}
        )
        if identity_key_for_item(item) in product_map:
            raise ValueError("当前产品下该红人已存在")

        record = create_product_influencer_from_collected(
            product_id=product_id,
            global_profile=global_profile,
            data=item,
            task=None,
            run_at=run_at,
        )
        db.add(record)
        await db.flush()
        await InfluencerSourceService.record_from_collected(db, record, item, run_at=run_at)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError("当前产品下该红人已存在") from exc
        await db.refresh(record)
        await db.refresh(global_profile)
        return record, global_profile

    @staticmethod
    async def update_influencer(
        db: AsyncSession,
        *,
        product_row: ProductInfluencer,
        global_row: GlobalInfluencerProfile,
        data: InfluencerUpdate,
    ) -> tuple[ProductInfluencer, GlobalInfluencerProfile]:
        update_data = data.model_dump(exclude_unset=True, mode="json")
        for field in ("website", "contact_page", "linktree_url", "profile_url"):
            if field in update_data and update_data[field] is not None:
                update_data[field] = str(update_data[field])
        for field in ("email", "final_email", "public_email", "business_email"):
            if field in update_data and update_data[field] is not None:
                update_data[field] = str(update_data[field])

        for field, value in update_data.items():
            if field in _PRODUCT_UPDATE_FIELDS:
                setattr(product_row, field, value)
            else:
                setattr(global_row, field, value)
                if field == "profile_url" and value:
                    global_row.normalized_profile_url = normalize_profile_url(value)
                if field == "username" and value:
                    global_row.normalized_username = (value or "").strip().lower().lstrip("@")

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError("红人资料与现有记录冲突") from exc
        await db.refresh(product_row)
        await db.refresh(global_row)
        return product_row, global_row

    @staticmethod
    async def delete_influencer(
        db: AsyncSession,
        *,
        product_row: ProductInfluencer,
    ) -> None:
        await db.delete(product_row)
        await db.commit()

    @staticmethod
    async def list_for_export(
        db: AsyncSession,
        *,
        product_id: int,
        filters: InfluencerFilter,
    ) -> list[InfluencerRead]:
        PI, GP = ProductInfluencer, GlobalInfluencerProfile
        base_query = ProductInfluencerService._apply_filters(
            ProductInfluencerService._base_join(product_id), filters, product_id=product_id
        )
        if filters.pending_follow_up:
            ordering = (PI.next_follow_up_at.asc().nullslast(), PI.last_collected_at.desc().nullslast(), PI.id.desc())
        else:
            ordering = (PI.last_collected_at.desc().nullslast(), PI.id.desc())
        rows = (await db.execute(base_query.order_by(*ordering))).all()
        influencer_ids = [pi.id for pi, _gp in rows]
        sources_by_id = await InfluencerSourceService.list_for_product_influencers(db, influencer_ids)
        email_sent_map = await load_email_sent_map(
            db,
            product_id=product_id,
            product_influencer_ids=influencer_ids,
        )
        items = []
        for pi, gp in rows:
            read = to_influencer_read(pi, gp, sources=sources_by_id.get(pi.id, []))
            sent_info = email_sent_map.get(pi.id)
            if sent_info:
                read = read.model_copy(
                    update={
                        "email_sent": sent_info.email_sent,
                        "last_email_sent_at": sent_info.last_email_sent_at,
                        "last_email_subject": sent_info.last_email_subject,
                    }
                )
            items.append(read)
        return items

    @staticmethod
    async def get_platform_stats(
        db: AsyncSession,
        *,
        product_id: int,
        filters: InfluencerFilter,
    ) -> PlatformStatsResponse:
        PI, GP = ProductInfluencer, GlobalInfluencerProfile
        stats_filters = filters.model_copy(update={"platform": None})
        rows = (
            await db.execute(
                ProductInfluencerService._apply_filters(
                    select(GP.platform, PI, GP).select_from(PI).join(
                        GP, PI.global_influencer_id == GP.id
                    ).where(ProductInfluencerService._inserted_scope(product_id, PI=PI)),
                    stats_filters,
                    product_id=product_id,
                )
            )
        ).all()

        row_pairs = [(platform, pi, gp) for platform, pi, gp in rows]
        email_sent_map = await load_email_sent_map(
            db,
            product_id=product_id,
            product_influencer_ids=[pi.id for _platform, pi, _gp in row_pairs],
        )

        buckets: dict[str, PlatformStatItem] = {}
        for platform, pi, gp in row_pairs:
            platform_key = platform if platform in ALL_STAT_PLATFORMS else "other"
            has_mail = bool(gp.final_email or gp.email or gp.public_email or gp.business_email)
            has_reach = bool(
                gp.final_email or gp.email or gp.public_email or gp.business_email
                or gp.website or gp.contact_page or gp.linktree_url or gp.whatsapp or gp.telegram
            )
            is_high = pi.final_priority in ("P0", "P1") or (pi.score or 0) >= 62.0
            is_direct = has_reach and bool(gp.final_email or gp.email or gp.public_email or gp.business_email)
            sent_info = email_sent_map.get(pi.id)
            is_sent = bool(sent_info and sent_info.email_sent)
            current = buckets.get(platform_key)
            if current is None:
                buckets[platform_key] = PlatformStatItem(
                    platform=platform_key,
                    total=1,
                    has_email=1 if has_mail else 0,
                    direct_contact=1 if is_direct else 0,
                    missing_contact=0 if has_reach else 1,
                    high_value=1 if is_high else 0,
                    sent_email_count=1 if is_sent else 0,
                    unsent_email_count=0 if is_sent else 1,
                )
            else:
                buckets[platform_key] = PlatformStatItem(
                    platform=platform_key,
                    total=current.total + 1,
                    has_email=current.has_email + (1 if has_mail else 0),
                    direct_contact=current.direct_contact + (1 if is_direct else 0),
                    missing_contact=current.missing_contact + (0 if has_reach else 1),
                    high_value=current.high_value + (1 if is_high else 0),
                    sent_email_count=current.sent_email_count + (1 if is_sent else 0),
                    unsent_email_count=current.unsent_email_count + (0 if is_sent else 1),
                )

        empty = PlatformStatItem(
            platform="",
            total=0,
            has_email=0,
            direct_contact=0,
            missing_contact=0,
            high_value=0,
            sent_email_count=0,
            unsent_email_count=0,
        )
        ordered_keys = list(PRIMARY_PLATFORMS)
        for platform_key in LINK_IMPORT_STAT_PLATFORMS:
            bucket = buckets.get(platform_key)
            if bucket is not None and bucket.total > 0:
                ordered_keys.append(platform_key)
        if "other" in buckets and buckets["other"].total > 0:
            ordered_keys.append("other")
        return PlatformStatsResponse(
            items=[
                buckets.get(
                    key,
                    empty.model_copy(update={"platform": key}),
                )
                for key in ordered_keys
            ]
        )
