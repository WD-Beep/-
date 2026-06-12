import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, not_, or_, select, exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.influencer import Influencer
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
from app.services.value_tier import (
    direct_contact_tier_condition,
    high_value_tier_condition,
    manual_research_tier_condition,
    reachable_contact_condition,
    skip_tier_condition,
)

PRIMARY_PLATFORMS: tuple[str, ...] = ("tiktok", "youtube", "instagram", "facebook")


class InfluencerService:
    @staticmethod
    def _recency_ordering():
        recency = func.coalesce(Influencer.last_collected_at, Influencer.created_at)
        return (
            recency.desc().nullslast(),
            Influencer.id.desc(),
        )

    @staticmethod
    def _quality_ordering():
        priority_rank = case(
            (Influencer.final_priority == "P0", 0),
            (Influencer.final_priority == "P1", 1),
            (Influencer.final_priority == "P2", 2),
            (Influencer.final_priority == "P3", 3),
            else_=4,
        )
        return (
            priority_rank.asc(),
            Influencer.score.desc().nullslast(),
            Influencer.updated_at.desc(),
        )

    @staticmethod
    def _contactable_condition():
        return reachable_contact_condition()

    @staticmethod
    def _high_value_condition():
        return high_value_tier_condition()

    @staticmethod
    def _value_tier_condition(value_tier: str):
        if value_tier == "direct_contact":
            return direct_contact_tier_condition()
        if value_tier == "manual_research":
            return manual_research_tier_condition()
        if value_tier == "skip":
            return skip_tier_condition()
        raise ValueError(f"Unsupported value_tier: {value_tier}")

    @staticmethod
    def _apply_filters(query, filters: InfluencerFilter):
        min_score = filters.min_score
        min_product_fit = filters.min_product_fit
        if filters.high_match:
            query = query.where(
                or_(
                    Influencer.final_priority.in_(("P0", "P1")),
                    Influencer.score >= 75.0,
                )
            )
            min_score = max(min_score or 0, 62.0)

        if filters.platform == "other":
            query = query.where(~Influencer.platform.in_(PRIMARY_PLATFORMS))
        elif filters.platform:
            query = query.where(Influencer.platform == filters.platform)
        if filters.country:
            query = query.where(Influencer.country == filters.country)
        if filters.category:
            query = query.where(Influencer.category == filters.category)

        status = filters.lead_status or filters.follow_status
        if status:
            query = query.where(Influencer.follow_status == status)
        if filters.lead_priority:
            query = query.where(Influencer.final_priority == filters.lead_priority)
        if filters.owner_name:
            query = query.where(Influencer.owner == filters.owner_name)
        if filters.source_discovery_type:
            query = query.where(Influencer.source_discovery_type == filters.source_discovery_type)
        if filters.high_priority:
            query = query.where(Influencer.final_priority.in_(("P0", "P1")))
        if filters.unassigned:
            query = query.where(or_(Influencer.owner.is_(None), Influencer.owner == ""))
        if filters.pending_follow_up:
            today_end = datetime.now(UTC).replace(hour=23, minute=59, second=59, microsecond=999999)
            excluded = tuple(EXCLUDED_FROM_TODAY)
            query = query.where(
                Influencer.next_follow_up_at.isnot(None),
                Influencer.next_follow_up_at <= today_end,
                or_(
                    Influencer.follow_status.is_(None),
                    ~Influencer.follow_status.in_(excluded),
                ),
            )
        if filters.today_recommended:
            allowed = tuple(TODAY_RECOMMENDED_STATUSES)
            excluded = tuple(EXCLUDED_FROM_TODAY | CONTACTED_STATUSES)
            query = query.where(
                or_(
                    Influencer.follow_status.in_(allowed),
                    Influencer.follow_status.is_(None),
                )
            )
            query = query.where(
                or_(
                    Influencer.follow_status.is_(None),
                    ~Influencer.follow_status.in_(excluded),
                )
            )

        if min_score is not None:
            query = query.where(Influencer.score >= min_score)
        if min_product_fit is not None:
            query = query.where(Influencer.product_fit >= min_product_fit)
        if filters.has_email:
            query = query.where(
                or_(
                    Influencer.final_email.isnot(None),
                    Influencer.email.isnot(None),
                    Influencer.public_email.isnot(None),
                    Influencer.business_email.isnot(None),
                )
            )
        if filters.contactable:
            query = query.where(InfluencerService._contactable_condition())
        if filters.high_value:
            query = query.where(InfluencerService._high_value_condition())
        if filters.value_tier:
            query = query.where(InfluencerService._value_tier_condition(filters.value_tier))
        if filters.missing_contact:
            query = query.where(
                ~InfluencerService._contactable_condition()
            )
        if filters.high_credibility_contact:
            query = query.where(
                or_(
                    Influencer.contact_credibility_level == "high",
                    Influencer.contact_score >= 75.0,
                )
            )
        if filters.search:
            term = f"%{filters.search}%"
            query = query.where(
                or_(
                    Influencer.username.ilike(term),
                    Influencer.display_name.ilike(term),
                    Influencer.bio.ilike(term),
                    Influencer.email.ilike(term),
                    Influencer.final_email.ilike(term),
                )
            )
        if filters.collection_task_id:
            inserted_for_task = exists(
                select(1).where(
                    CollectionTaskCandidate.influencer_id == Influencer.id,
                    CollectionTaskCandidate.task_id == filters.collection_task_id,
                    CollectionTaskCandidate.status == "inserted",
                )
            )
            query = query.where(inserted_for_task)
        if filters.created_within_hours:
            cutoff = datetime.now(UTC) - timedelta(hours=filters.created_within_hours)
            query = query.where(Influencer.created_at >= cutoff)
        if filters.collected_within_days:
            cutoff = datetime.now(UTC) - timedelta(days=filters.collected_within_days)
            query = query.where(Influencer.last_collected_at >= cutoff)
        return query

    @staticmethod
    def _has_email_condition():
        return or_(
            Influencer.final_email.isnot(None),
            Influencer.email.isnot(None),
            Influencer.public_email.isnot(None),
            Influencer.business_email.isnot(None),
        )

    @staticmethod
    async def get_platform_stats(
        db: AsyncSession,
        filters: InfluencerFilter,
    ) -> PlatformStatsResponse:
        stats_filters = filters.model_copy(update={"platform": None})
        has_email = InfluencerService._has_email_condition()
        direct_contact = direct_contact_tier_condition()
        missing_contact = not_(reachable_contact_condition())
        high_value = high_value_tier_condition()

        query = select(
            Influencer.platform,
            func.count().label("total"),
            func.sum(case((has_email, 1), else_=0)).label("has_email"),
            func.sum(case((direct_contact, 1), else_=0)).label("direct_contact"),
            func.sum(case((missing_contact, 1), else_=0)).label("missing_contact"),
            func.sum(case((high_value, 1), else_=0)).label("high_value"),
        )
        query = InfluencerService._apply_filters(query, stats_filters)
        query = query.group_by(Influencer.platform).order_by(func.count().desc())

        result = await db.execute(query)
        raw_rows = result.all()

        buckets: dict[str, PlatformStatItem] = {}
        for row in raw_rows:
            platform_key = row.platform if row.platform in PRIMARY_PLATFORMS else "other"
            current = buckets.get(platform_key)
            if current is None:
                buckets[platform_key] = PlatformStatItem(
                    platform=platform_key,
                    total=int(row.total or 0),
                    has_email=int(row.has_email or 0),
                    direct_contact=int(row.direct_contact or 0),
                    missing_contact=int(row.missing_contact or 0),
                    high_value=int(row.high_value or 0),
                )
            else:
                buckets[platform_key] = PlatformStatItem(
                    platform=platform_key,
                    total=current.total + int(row.total or 0),
                    has_email=current.has_email + int(row.has_email or 0),
                    direct_contact=current.direct_contact + int(row.direct_contact or 0),
                    missing_contact=current.missing_contact + int(row.missing_contact or 0),
                    high_value=current.high_value + int(row.high_value or 0),
                )

        ordered_keys = [p for p in PRIMARY_PLATFORMS if p in buckets]
        if "other" in buckets:
            ordered_keys.append("other")

        return PlatformStatsResponse(items=[buckets[key] for key in ordered_keys])

    @staticmethod
    async def list_influencers(
        db: AsyncSession,
        filters: InfluencerFilter,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[InfluencerRead]:
        base_query = select(Influencer)
        base_query = InfluencerService._apply_filters(base_query, filters)

        total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
        total = total or 0

        if filters.pending_follow_up:
            ordering = (
                Influencer.next_follow_up_at.asc().nullslast(),
                *InfluencerService._recency_ordering(),
            )
        elif filters.today_recommended:
            ordering = (
                *InfluencerService._recency_ordering(),
                *InfluencerService._quality_ordering(),
            )
        else:
            ordering = InfluencerService._recency_ordering()

        query = (
            base_query.order_by(*ordering)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(query)
        items = [InfluencerRead.model_validate(row) for row in result.scalars().all()]

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def list_for_export(db: AsyncSession, filters: InfluencerFilter) -> list[Influencer]:
        query = select(Influencer)
        query = InfluencerService._apply_filters(query, filters)
        if filters.pending_follow_up:
            query = query.order_by(
                Influencer.next_follow_up_at.asc().nullslast(),
                *InfluencerService._recency_ordering(),
            )
        elif filters.today_recommended:
            query = query.order_by(
                *InfluencerService._recency_ordering(),
                *InfluencerService._quality_ordering(),
            )
        else:
            query = query.order_by(*InfluencerService._recency_ordering())
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_influencer(db: AsyncSession, influencer_id: int) -> Influencer | None:
        return await db.get(Influencer, influencer_id)

    @staticmethod
    async def create_influencer(db: AsyncSession, data: InfluencerCreate) -> Influencer:
        payload = data.model_dump(mode="json")
        for field in ("website", "contact_page", "linktree_url"):
            if payload.get(field) is not None:
                payload[field] = str(payload[field])
        for field in ("email", "final_email", "public_email", "business_email"):
            if payload.get(field) is not None:
                payload[field] = str(payload[field])

        influencer = Influencer(**payload)
        db.add(influencer)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError("Influencer with same platform and profile_url already exists") from exc
        await db.refresh(influencer)
        return influencer

    @staticmethod
    async def update_influencer(
        db: AsyncSession,
        influencer: Influencer,
        data: InfluencerUpdate,
    ) -> Influencer:
        update_data = data.model_dump(exclude_unset=True, mode="json")
        for field in ("website", "contact_page", "linktree_url"):
            if field in update_data and update_data[field] is not None:
                update_data[field] = str(update_data[field])
        for field in ("email", "final_email", "public_email", "business_email"):
            if field in update_data and update_data[field] is not None:
                update_data[field] = str(update_data[field])

        for field, value in update_data.items():
            setattr(influencer, field, value)

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError("Influencer with same platform and profile_url already exists") from exc
        await db.refresh(influencer)
        return influencer

    @staticmethod
    async def delete_influencer(db: AsyncSession, influencer: Influencer) -> None:
        await db.delete(influencer)
        await db.commit()
