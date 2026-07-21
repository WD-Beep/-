# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：task candidate
"""采集任务候选账号持久化与查询。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateFailureReason, CandidateSourceType, CandidateStatus, CollectionMode
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
from app.collectors.base import CollectedInfluencer
from app.services.high_value_filter import assessment_row_fields, evaluate_high_value_assessment
from app.services.influencer_persistence import identity_key_for_item
from app.services.url_parser import validate_link_import_url_lines


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
            source_input_url = payload.get("source_input_url")
            if not source_input_url:
                meta = payload.get("source_meta")
                if isinstance(meta, dict):
                    source_input_url = meta.get("source_input_url") or meta.get("input_url")
            if source_input_url and not payload.get("source_input_url"):
                payload["source_input_url"] = str(source_input_url).strip()
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
        source_input_url: str | None = None,
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
            "source_input_url": source_input_url,
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
        source_input_url: str | None = None,
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
            "source_input_url": source_input_url,
            "followers_count": followers_count,
            "engagement_rate": engagement_rate,
            "profile_fetched_at": profile_fetched_at,
            "status": CandidateStatus.FILTERED_OUT.value,
            "failure_reason": normalize_hard_filter_reason(failure_reason),
            "failure_detail": sanitize_failure_detail(failure_detail),
        }

    @staticmethod
    def row_from_not_inserted(
        *,
        username: str,
        profile_url: str,
        failure_reason: str | None = None,
        failure_detail: str | None = None,
        insert_blocked_reason: str | None = None,
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
        source_input_url: str | None = None,
        followers_count: int | None = None,
        engagement_rate: float | None = None,
        profile_fetched_at: datetime | None = None,
        is_high_value: bool | None = None,
        has_email: bool | None = None,
        has_contact: bool | None = None,
        contact_status: str | None = None,
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
            "source_input_url": source_input_url,
            "followers_count": followers_count,
            "engagement_rate": engagement_rate,
            "profile_fetched_at": profile_fetched_at,
            "status": CandidateStatus.NOT_INSERTED.value,
            "failure_reason": normalize_hard_filter_reason(failure_reason),
            "failure_detail": sanitize_failure_detail(failure_detail),
            "insert_blocked_reason": sanitize_failure_detail(insert_blocked_reason or failure_detail),
            "is_high_value": is_high_value,
            "has_email": has_email,
            "has_contact": has_contact,
            "contact_status": contact_status,
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
        source_input_url: str | None = None,
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
                "source_input_url": source_input_url,
                "status": CandidateStatus.DUPLICATE.value,
                "failure_reason": CandidateFailureReason.DUPLICATE.value,
                "failure_detail": detail,
            }
        )
        return row

    @staticmethod
    async def count_by_status(
        db: AsyncSession,
        task_id: int,
        *,
        status: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(CollectionTaskCandidate).where(
            CollectionTaskCandidate.task_id == task_id
        )
        if status:
            query = query.where(CollectionTaskCandidate.status == status)
        return int((await db.execute(query)).scalar_one())

    @staticmethod
    def _apply_product_scope(query, product_id: int | None):
        if product_id is None or product_id <= 0:
            return query
        return query.where(
            or_(
                CollectionTaskCandidate.product_id == product_id,
                CollectionTaskCandidate.product_id.is_(None),
            )
        )

    @staticmethod
    async def sync_task_inserted_stats(
        db: AsyncSession,
        task: CollectionTask,
        *,
        force: bool = False,
    ) -> None:
        total_candidates = await TaskCandidateService.count_by_status(db, task.id)
        inserted = await TaskCandidateService.count_by_status(
            db, task.id, status=CandidateStatus.INSERTED.value
        )
        if total_candidates <= 0:
            if not force:
                return
            # 候选明细为空时，避免把「已解析主页数」误当成已入库数长期挂在任务上
            checkpoint = task.run_checkpoint if isinstance(task.run_checkpoint, dict) else {}
            persisted = len(checkpoint.get("persisted_profiles") or [])
            task.inserted_count = persisted
            task.result_count = persisted
            return
        task.inserted_count = inserted
        task.result_count = inserted

    @staticmethod
    async def ensure_candidates_for_task(db: AsyncSession, task: CollectionTask) -> int:
        """Backfill missing inserted candidate rows for legacy/resume tasks."""
        expected = max(task.inserted_count or 0, task.result_count or 0)
        if expected <= 0 or not task.product_id:
            return 0

        existing_inserted = await TaskCandidateService.count_by_status(
            db, task.id, status=CandidateStatus.INSERTED.value
        )
        if existing_inserted >= expected:
            return 0

        run_at = task.last_run_at or datetime.now(UTC)
        missing = expected - existing_inserted
        backfill_rows: list[dict] = []

        linked_ids = select(CollectionTaskCandidate.product_influencer_id).where(
            CollectionTaskCandidate.task_id == task.id,
            CollectionTaskCandidate.product_influencer_id.isnot(None),
        )

        if task.collection_mode == CollectionMode.LINK_IMPORT.value and task.input_urls:
            valid_entries = validate_link_import_url_lines(list(task.input_urls))
            url_set = {
                (entry.get("url") or "").lower().rstrip("/")
                for entry in valid_entries
                if entry.get("url")
            }
            if url_set:
                result = await db.execute(
                    select(ProductInfluencer, GlobalInfluencerProfile)
                    .join(
                        GlobalInfluencerProfile,
                        ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id,
                    )
                    .where(
                        ProductInfluencer.product_id == task.product_id,
                        ProductInfluencer.id.notin_(linked_ids),
                    )
                )
                for product_row, global_row in result.all():
                    profile_url = (global_row.profile_url or "").lower().rstrip("/")
                    if profile_url not in url_set:
                        continue
                    source_url = next(
                        (entry.get("url") or profile_url for entry in valid_entries if (entry.get("url") or "").lower().rstrip("/") == profile_url),
                        profile_url,
                    )
                    assessment = evaluate_high_value_assessment(
                        CollectedInfluencer(
                            platform=global_row.platform,
                            username=global_row.username,
                            profile_url=global_row.profile_url,
                            followers_count=global_row.followers_count,
                            engagement_rate=global_row.engagement_rate,
                            final_email=global_row.final_email,
                            email=global_row.final_email,
                        ),
                        task,
                    )
                    row = TaskCandidateService.row_from_inserted(
                        meta=None,
                        username=global_row.username,
                        profile_url=global_row.profile_url,
                        platform=global_row.platform,
                        collection_mode=task.collection_mode,
                        product_influencer_id=product_row.id,
                        global_influencer_id=global_row.id,
                        product_id=task.product_id,
                        user_id=task.user_id,
                        followers_count=global_row.followers_count,
                        engagement_rate=global_row.engagement_rate,
                        profile_fetched_at=run_at,
                        source_type=CandidateSourceType.INPUT_PROFILE.value,
                        source_discovery_type="url_profile",
                        source_post_url=source_url,
                    )
                    row.update(assessment_row_fields(assessment))
                    backfill_rows.append(row)
                    if len(backfill_rows) >= missing:
                        break

        if len(backfill_rows) < missing:
            # 手动停止/暂停时，候选池明细可能未写入，但 inserted_count 已累计。
            # last_collected_at 也可能未刷新，因此按入库红人兜底回填，并放宽时间匹配。
            time_clauses = []
            if task.last_run_at:
                window_start = task.last_run_at - timedelta(hours=48)
                window_end = task.last_run_at + timedelta(hours=6)
                time_clauses = [
                    or_(
                        and_(
                            ProductInfluencer.last_collected_at.is_not(None),
                            ProductInfluencer.last_collected_at >= window_start,
                            ProductInfluencer.last_collected_at <= window_end,
                        ),
                        and_(
                            ProductInfluencer.updated_at >= window_start,
                            ProductInfluencer.updated_at <= window_end,
                        ),
                        and_(
                            ProductInfluencer.created_at >= window_start,
                            ProductInfluencer.created_at <= window_end,
                        ),
                    )
                ]
            result = await db.execute(
                select(ProductInfluencer, GlobalInfluencerProfile)
                .join(
                    GlobalInfluencerProfile,
                    ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id,
                )
                .where(
                    ProductInfluencer.product_id == task.product_id,
                    ProductInfluencer.is_inserted.is_(True),
                    ProductInfluencer.id.notin_(linked_ids),
                    *time_clauses,
                )
                .order_by(
                    ProductInfluencer.last_collected_at.desc().nullslast(),
                    ProductInfluencer.updated_at.desc(),
                )
                .limit(missing - len(backfill_rows))
            )
            for product_row, global_row in result.all():
                if any(row.get("product_influencer_id") == product_row.id for row in backfill_rows):
                    continue
                assessment = evaluate_high_value_assessment(
                    CollectedInfluencer(
                        platform=global_row.platform,
                        username=global_row.username,
                        profile_url=global_row.profile_url,
                        followers_count=global_row.followers_count,
                        engagement_rate=global_row.engagement_rate,
                        final_email=global_row.final_email,
                        email=global_row.final_email,
                    ),
                    task,
                )
                row = TaskCandidateService.row_from_inserted(
                    meta=None,
                    username=global_row.username,
                    profile_url=global_row.profile_url,
                    platform=global_row.platform,
                    collection_mode=task.collection_mode,
                    product_influencer_id=product_row.id,
                    global_influencer_id=global_row.id,
                    product_id=task.product_id,
                    user_id=task.user_id,
                    followers_count=global_row.followers_count,
                    engagement_rate=global_row.engagement_rate,
                    profile_fetched_at=run_at,
                    source_type=product_row.source_discovery_type,
                    source_discovery_type=product_row.source_discovery_type,
                    source_post_url=product_row.source_post_url,
                )
                row.update(assessment_row_fields(assessment))
                backfill_rows.append(row)

        if not backfill_rows:
            return 0

        await TaskCandidateService.bulk_insert(
            db,
            task.id,
            backfill_rows,
            run_at=run_at,
            product_id=task.product_id,
            user_id=task.user_id,
        )
        await TaskCandidateService.sync_task_inserted_stats(db, task)
        return len(backfill_rows)

    @staticmethod
    def _apply_candidate_filters(
        query,
        *,
        task_id: int,
        status: str | None = None,
        failure_reason: str | None = None,
        source_type: str | None = None,
        source_discovery_type: str | None = None,
        platform: str | None = None,
        high_value: bool | None = None,
        has_email: bool | None = None,
        has_contact: bool | None = None,
        min_followers_count: int | None = None,
        max_followers_count: int | None = None,
        min_engagement_rate: float | None = None,
        max_engagement_rate: float | None = None,
        insert_blocked_reason: str | None = None,
        contact_status: str | None = None,
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
        if platform:
            query = query.where(CollectionTaskCandidate.platform == platform)
        if high_value is not None:
            query = query.where(CollectionTaskCandidate.is_high_value.is_(high_value))
        if has_email is not None:
            query = query.where(CollectionTaskCandidate.has_email.is_(has_email))
        if has_contact is not None:
            query = query.where(CollectionTaskCandidate.has_contact.is_(has_contact))
        if min_followers_count is not None:
            query = query.where(CollectionTaskCandidate.followers_count >= min_followers_count)
        if max_followers_count is not None:
            query = query.where(CollectionTaskCandidate.followers_count <= max_followers_count)
        if min_engagement_rate is not None:
            query = query.where(CollectionTaskCandidate.engagement_rate >= min_engagement_rate)
        if max_engagement_rate is not None:
            query = query.where(CollectionTaskCandidate.engagement_rate <= max_engagement_rate)
        if insert_blocked_reason:
            term = f"%{insert_blocked_reason.strip()}%"
            query = query.where(CollectionTaskCandidate.insert_blocked_reason.ilike(term))
        if contact_status:
            query = query.where(CollectionTaskCandidate.contact_status == contact_status)
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
        platform: str | None = None,
        high_value: bool | None = None,
        has_email: bool | None = None,
        has_contact: bool | None = None,
        min_followers_count: int | None = None,
        max_followers_count: int | None = None,
        min_engagement_rate: float | None = None,
        max_engagement_rate: float | None = None,
        insert_blocked_reason: str | None = None,
        contact_status: str | None = None,
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
            platform=platform,
            high_value=high_value,
            has_email=has_email,
            has_contact=has_contact,
            min_followers_count=min_followers_count,
            max_followers_count=max_followers_count,
            min_engagement_rate=min_engagement_rate,
            max_engagement_rate=max_engagement_rate,
            insert_blocked_reason=insert_blocked_reason,
            contact_status=contact_status,
            search=search,
        )
        if product_id is not None:
            query = TaskCandidateService._apply_product_scope(query, product_id)
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
        platform: str | None = None,
        high_value: bool | None = None,
        has_email: bool | None = None,
        has_contact: bool | None = None,
        min_followers_count: int | None = None,
        max_followers_count: int | None = None,
        min_engagement_rate: float | None = None,
        max_engagement_rate: float | None = None,
        insert_blocked_reason: str | None = None,
        contact_status: str | None = None,
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
            platform=platform,
            high_value=high_value,
            has_email=has_email,
            has_contact=has_contact,
            min_followers_count=min_followers_count,
            max_followers_count=max_followers_count,
            min_engagement_rate=min_engagement_rate,
            max_engagement_rate=max_engagement_rate,
            insert_blocked_reason=insert_blocked_reason,
            contact_status=contact_status,
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
            platform=platform,
            high_value=high_value,
            has_email=has_email,
            has_contact=has_contact,
            min_followers_count=min_followers_count,
            max_followers_count=max_followers_count,
            min_engagement_rate=min_engagement_rate,
            max_engagement_rate=max_engagement_rate,
            insert_blocked_reason=insert_blocked_reason,
            contact_status=contact_status,
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
