"""采集任务候选账号持久化与查询。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateFailureReason, CandidateStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.influencer import Influencer
from app.models.product_influencer import ProductInfluencer
from app.services.influencer_projection import merged_influencer_for_ai
from app.schemas.common import PaginatedResponse
from app.services.apify_instagram import PostAuthorCandidate
from app.services.candidate_pool import (
    meta_source_fields,
    normalize_hard_filter_reason,
    normalize_profile_failure_reason,
    sanitize_failure_detail,
)


class TaskCandidateService:
    @staticmethod
    async def clear_for_task(db: AsyncSession, task_id: int) -> None:
        await db.execute(delete(CollectionTaskCandidate).where(CollectionTaskCandidate.task_id == task_id))

    @staticmethod
    async def bulk_insert(
        db: AsyncSession,
        task_id: int,
        rows: list[dict],
        *,
        run_at: datetime,
        product_id: int | None = None,
        user_id: int | None = None,
    ) -> None:
        for row in rows:
            payload = dict(row)
            if product_id is not None:
                payload.setdefault("product_id", product_id)
            if user_id is not None:
                payload.setdefault("user_id", user_id)
            db.add(
                CollectionTaskCandidate(
                    task_id=task_id,
                    run_at=run_at,
                    **payload,
                )
            )

    @staticmethod
    def _base_row(
        *,
        meta: PostAuthorCandidate,
        platform: str,
        collection_mode: str | None,
        source_keyword: str | None = None,
    ) -> dict:
        fields = meta_source_fields(meta, collection_mode=collection_mode)
        if source_keyword:
            fields["source_keyword"] = source_keyword
        elif not fields.get("source_keyword") and meta.source_hashtag:
            fields["source_keyword"] = meta.source_hashtag
        return {
            "username": meta.username,
            "profile_url": meta.profile_url,
            "platform": platform,
            **fields,
        }

    @staticmethod
    def row_from_discovered(
        *,
        meta: PostAuthorCandidate,
        platform: str,
        collection_mode: str | None = None,
        source_keyword: str | None = None,
    ) -> dict:
        return {
            **TaskCandidateService._base_row(
                meta=meta,
                platform=platform,
                collection_mode=collection_mode,
                source_keyword=source_keyword,
            ),
            "status": CandidateStatus.PENDING_PROFILE.value,
        }

    @staticmethod
    def row_from_failed(
        *,
        username: str,
        profile_url: str,
        failure_reason: str,
        failure_detail: str | None = None,
        platform: str = "instagram",
        source_hashtag: str | None = None,
        source_keyword: str | None = None,
        source_post_url: str | None = None,
        source_caption: str | None = None,
        source_comment_url: str | None = None,
        source_comment_text: str | None = None,
        source_discovery_type: str | None = None,
        source_type: str | None = None,
        source_meta: dict | None = None,
        followers_count: int | None = None,
        engagement_rate: float | None = None,
        profile_fetched_at: datetime | None = None,
    ) -> dict:
        return {
            "username": username,
            "profile_url": profile_url,
            "platform": platform,
            "source_hashtag": source_hashtag,
            "source_keyword": source_keyword or source_hashtag,
            "source_post_url": source_post_url,
            "source_caption": source_caption,
            "source_comment_url": source_comment_url,
            "source_comment_text": source_comment_text,
            "source_discovery_type": source_discovery_type,
            "source_type": source_type,
            "source_meta": source_meta,
            "followers_count": followers_count,
            "engagement_rate": engagement_rate,
            "profile_fetched_at": profile_fetched_at,
            "status": CandidateStatus.PROFILE_FAILED.value,
            "failure_reason": normalize_profile_failure_reason(failure_reason),
            "failure_detail": sanitize_failure_detail(failure_detail),
        }

    @staticmethod
    def row_from_filtered(
        *,
        username: str,
        profile_url: str,
        failure_reason: str | None = None,
        failure_detail: str | None = None,
        platform: str = "instagram",
        source_hashtag: str | None = None,
        source_keyword: str | None = None,
        source_post_url: str | None = None,
        source_caption: str | None = None,
        source_comment_url: str | None = None,
        source_comment_text: str | None = None,
        source_discovery_type: str | None = None,
        source_type: str | None = None,
        source_meta: dict | None = None,
        followers_count: int | None = None,
        engagement_rate: float | None = None,
        profile_fetched_at: datetime | None = None,
    ) -> dict:
        return {
            "username": username,
            "profile_url": profile_url,
            "platform": platform,
            "source_hashtag": source_hashtag,
            "source_keyword": source_keyword or source_hashtag,
            "source_post_url": source_post_url,
            "source_caption": source_caption,
            "source_comment_url": source_comment_url,
            "source_comment_text": source_comment_text,
            "source_discovery_type": source_discovery_type,
            "source_type": source_type,
            "source_meta": source_meta,
            "followers_count": followers_count,
            "engagement_rate": engagement_rate,
            "profile_fetched_at": profile_fetched_at,
            "status": CandidateStatus.FILTERED_OUT.value,
            "failure_reason": normalize_hard_filter_reason(failure_reason),
            "failure_detail": sanitize_failure_detail(failure_detail),
        }

    @staticmethod
    def row_from_inserted(
        *,
        meta: PostAuthorCandidate | None,
        username: str,
        profile_url: str,
        platform: str,
        collection_mode: str | None,
        product_influencer_id: int | None,
        global_influencer_id: int | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
        followers_count: int | None,
        engagement_rate: float | None,
        profile_fetched_at: datetime,
        source_keyword: str | None = None,
        **extra,
    ) -> dict:
        if meta:
            row = TaskCandidateService._base_row(
                meta=meta,
                platform=platform,
                collection_mode=collection_mode,
                source_keyword=source_keyword,
            )
        else:
            row = {
                "username": username,
                "profile_url": profile_url,
                "platform": platform,
                **extra,
            }
        row.update(
            {
                "followers_count": followers_count,
                "engagement_rate": engagement_rate,
                "profile_fetched_at": profile_fetched_at,
                "product_influencer_id": product_influencer_id,
                "global_influencer_id": global_influencer_id,
                "product_id": product_id,
                "user_id": user_id,
                "status": CandidateStatus.INSERTED.value,
                "failure_reason": None,
                "failure_detail": None,
            }
        )
        return row

    @staticmethod
    def row_from_duplicate(
        *,
        meta: PostAuthorCandidate | None,
        username: str,
        profile_url: str,
        platform: str,
        collection_mode: str | None,
        followers_count: int | None = None,
        engagement_rate: float | None = None,
        profile_fetched_at: datetime | None = None,
        source_keyword: str | None = None,
        detail: str = "红人库中已存在相同主页，本次未重复写入",
    ) -> dict:
        if meta:
            row = TaskCandidateService._base_row(
                meta=meta,
                platform=platform,
                collection_mode=collection_mode,
                source_keyword=source_keyword,
            )
        else:
            row = {"username": username, "profile_url": profile_url, "platform": platform}
        row.update(
            {
                "followers_count": followers_count,
                "engagement_rate": engagement_rate,
                "profile_fetched_at": profile_fetched_at,
                "status": CandidateStatus.DUPLICATE.value,
                "failure_reason": CandidateFailureReason.DUPLICATE.value,
                "failure_detail": detail,
            }
        )
        return row

    @staticmethod
    def _apply_candidate_filters(
        query,
        *,
        task_id: int,
        status: str | None = None,
        failure_reason: str | None = None,
        source_type: str | None = None,
        source_discovery_type: str | None = None,
        search: str | None = None,
    ):
        query = query.where(CollectionTaskCandidate.task_id == task_id)
        if status:
            query = query.where(CollectionTaskCandidate.status == status)
        if failure_reason:
            query = query.where(CollectionTaskCandidate.failure_reason == failure_reason)
        if source_type:
            query = query.where(CollectionTaskCandidate.source_type == source_type)
        if source_discovery_type:
            query = query.where(CollectionTaskCandidate.source_discovery_type == source_discovery_type)
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    CollectionTaskCandidate.username.ilike(term),
                    CollectionTaskCandidate.profile_url.ilike(term),
                )
            )
        return query

    @staticmethod
    async def list_for_export(
        db: AsyncSession,
        task_id: int,
        *,
        product_id: int | None = None,
        status: str | None = None,
        failure_reason: str | None = None,
        source_type: str | None = None,
        source_discovery_type: str | None = None,
        search: str | None = None,
    ) -> list[tuple[CollectionTaskCandidate, Influencer | None]]:
        query = select(CollectionTaskCandidate, ProductInfluencer, GlobalInfluencerProfile).outerjoin(
            ProductInfluencer, CollectionTaskCandidate.product_influencer_id == ProductInfluencer.id
        ).outerjoin(
            GlobalInfluencerProfile, ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id
        )
        query = TaskCandidateService._apply_candidate_filters(
            query,
            task_id=task_id,
            status=status,
            failure_reason=failure_reason,
            source_type=source_type,
            source_discovery_type=source_discovery_type,
            search=search,
        )
        if product_id is not None:
            query = query.where(CollectionTaskCandidate.product_id == product_id)
        result = await db.execute(query.order_by(CollectionTaskCandidate.id.desc()))
        rows: list[tuple[CollectionTaskCandidate, Influencer | None]] = []
        for candidate, product_row, global_row in result.all():
            influencer = (
                merged_influencer_for_ai(product_row, global_row)
                if product_row is not None and global_row is not None
                else None
            )
            rows.append((candidate, influencer))
        return rows

    @staticmethod
    async def list_for_task(
        db: AsyncSession,
        task_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        failure_reason: str | None = None,
        source_type: str | None = None,
        source_discovery_type: str | None = None,
        search: str | None = None,
    ) -> PaginatedResponse[CollectionTaskCandidate]:
        page_size = min(max(page_size, 1), 100)
        query = select(CollectionTaskCandidate)
        query = TaskCandidateService._apply_candidate_filters(
            query,
            task_id=task_id,
            status=status,
            failure_reason=failure_reason,
            source_type=source_type,
            source_discovery_type=source_discovery_type,
            search=search,
        )

        count_query = select(func.count()).select_from(CollectionTaskCandidate)
        count_query = TaskCandidateService._apply_candidate_filters(
            count_query,
            task_id=task_id,
            status=status,
            failure_reason=failure_reason,
            source_type=source_type,
            source_discovery_type=source_discovery_type,
            search=search,
        )
        total = int((await db.execute(count_query)).scalar_one())

        result = await db.execute(
            query.order_by(CollectionTaskCandidate.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(result.scalars().all())
        pages = max(1, (total + page_size - 1) // page_size)
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )
