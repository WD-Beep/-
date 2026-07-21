# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：link import
import logging
import math

from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import CollectedInfluencer
from app.deps.tenant import TenantContext, require_write_product_id
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateSourceType, CandidateStatus, CollectionMode, CollectionTaskStatus, LinkImportBatchStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.link_import_batch import LinkImportBatch
from app.models.product_influencer import ProductInfluencer
from app.schemas.common import PaginatedResponse
from app.schemas.link_import import LinkImportBatchCreate, LinkImportBatchRead
from app.services.apify_instagram import _username_from_url
from app.services.candidate_pool import hard_filter_failure_detail
from app.services.collect_errors import summarize_errors
from app.services.ai_service import analyze_influencer
from app.services.collection_filters import evaluate_post_hydration_hard_filter, PostHydrationHardFilterResult
from app.services.contact_discovery import ContactDiscoveryService
from app.services.high_value_filter import (
    assessment_row_fields,
    evaluate_high_value_assessment,
    is_url_only_metrics_pending,
    should_skip_insert,
    should_strict_filter_out,
)
from app.services.influencer_persistence import (
    InfluencerPersistenceService,
    apply_global_profile_data,
    apply_product_influencer_data,
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
    global_profile_has_changes,
    identity_key_for_item,
    product_record_has_changes,
    should_refresh_global_profile,
)
from app.services.influencer_projection import apply_ai_to_product_record, merged_influencer_for_ai
from app.services.influencer_source import InfluencerSourceService
from app.services.instagram_provider import discover_post_authors_from_post_urls, scrape_instagram_profiles
from app.services.api_direct_provider import discover_platform
from app.services.platform_types import URL_ONLY_PLATFORMS, PlatformCandidateProfile
from app.services.platform_providers.url_only import PARSERS
from app.services.platform_providers.youtube_dedupe import extract_video_id
from app.services.platform_utils import profile_to_collected
from app.services.link_import_url import parsed_to_valid_entry, resolve_import_link
from app.services.task_candidate import TaskCandidateService
from app.services.task_influencer import TaskInfluencerService
from app.services.task_run_progress import STAGE_COMPLETED, STAGE_FAILED
from app.services.url_parser import (
    parse_raw_urls,
    split_link_import_entries,
    tiktok_profile_from_url,
    validate_link_import_url_lines,
)
from app.services.link_seed_enrichment import (
    LINK_SEED_PLATFORMS,
    collected_profile_snapshot,
    enrich_link_seed_item,
    enrichment_meta_dict,
    link_seed_low_value_detail,
)
from app.services.influencer_profile_value import is_influencer_profile_valuable


@dataclass
class LinkImportExecuteResult:
    new_count: int = 0
    updated_count: int = 0
    import_failed: int = 0
    import_errors: list[str] = field(default_factory=list)
    filtered_out_count: int = 0
    filtered_below_min: int = 0
    filtered_excluded: int = 0
    not_inserted_count: int = 0
    pending_profile_count: int = 0
    hydrated_profile_count: int = 0
    low_value_seed_count: int = 0
    seed_enrichment_attempted: int = 0
    seed_social_profiles_found: int = 0
    candidate_rows: list[dict] = field(default_factory=list)


URL_ONLY_PENDING_DETAIL = "资料不足，建议补采社媒主页；已尝试通过 Instagram/TikTok/YouTube 自动补全。"


def _entry_post_url(entry: dict[str, str | None]) -> str | None:
    link_type = entry.get("link_type") or ""
    if link_type in {"post", "pin", "product", "short"}:
        return entry.get("source_post_url") or entry.get("url")
    return entry.get("source_post_url")


def _count_link_import_posts(entries: list[dict[str, str | None]]) -> int:
    return sum(1 for entry in entries if _entry_post_url(entry))


def _normalize_lookup_url(url: str | None) -> str:
    if not url:
        return ""
    return url.strip().lower().split("#")[0].split("?")[0].rstrip("/")


def _entry_lookup_keys(entry: dict[str, str | None]) -> set[str]:
    keys: set[str] = set()
    for field in ("url", "source_post_url", "profile_url"):
        value = entry.get(field)
        if value:
            keys.add(_normalize_lookup_url(str(value)))
    video_id = extract_video_id({"url": str(entry.get("url") or "")})
    if video_id:
        keys.add(f"video:{video_id.lower()}")
    return keys


def _item_lookup_keys(item: CollectedInfluencer) -> set[str]:
    keys: set[str] = set()
    for value in (
        getattr(item, "source_post_url", None),
        getattr(item, "profile_url", None),
    ):
        if value:
            keys.add(_normalize_lookup_url(str(value)))
    for value in getattr(item, "recent_post_urls", None) or []:
        if value:
            keys.add(_normalize_lookup_url(str(value)))
            video_id = extract_video_id({"url": str(value)})
            if video_id:
                keys.add(f"video:{video_id.lower()}")
    if item.source_post_url:
        video_id = extract_video_id({"url": str(item.source_post_url)})
        if video_id:
            keys.add(f"video:{video_id.lower()}")
    return keys


def _is_instagram_post_entry(entry: dict[str, str | None]) -> bool:
    if entry.get("link_type") == "post":
        return True
    return bool(_entry_post_url(entry))


def _match_item_to_entry(
    item: CollectedInfluencer,
    entries: list[dict[str, str | None]],
    *,
    matched_entry_urls: set[str],
) -> dict[str, str | None] | None:
    item_keys = _item_lookup_keys(item)
    for entry in entries:
        entry_url = str(entry.get("url") or "")
        if not entry_url or entry_url in matched_entry_urls:
            continue
        if item_keys & _entry_lookup_keys(entry):
            return entry
    profile_key = _normalize_lookup_url(item.profile_url)
    if profile_key:
        for entry in entries:
            entry_url = str(entry.get("url") or "")
            if not entry_url or entry_url in matched_entry_urls:
                continue
            if entry.get("link_type") == "profile" and _normalize_lookup_url(
                str(entry.get("profile_url") or entry_url)
            ) == profile_key:
                return entry
    return None


async def _process_provider_import_items(
    db: AsyncSession,
    *,
    platform: str,
    entries: list[dict[str, str | None]],
    items: list[CollectedInfluencer],
    product_id: int,
    task: CollectionTask | None,
    run_at: datetime,
    exec_result: LinkImportExecuteResult,
) -> None:
    matched_entry_urls: set[str] = set()
    for item in items:
        try:
            await ContactDiscoveryService.enrich_collected(item)
            entry = _match_item_to_entry(item, entries, matched_entry_urls=matched_entry_urls)
            source_post_url = _entry_post_url(entry) if entry else item.source_post_url
            source_input_url = str(entry.get("url") or "") if entry else getattr(item, "source_input_url", None)
            if entry and source_post_url and not item.source_post_url:
                item.source_post_url = source_post_url
            if entry and source_input_url and not getattr(item, "source_input_url", None):
                item.source_input_url = source_input_url
            if task is not None:
                await LinkImportService._process_import_item(
                    db,
                    item,
                    source_post_url=source_post_url,
                    source_input_url=source_input_url,
                    run_at=run_at,
                    product_id=product_id,
                    task=task,
                    exec_result=exec_result,
                )
            else:
                outcome, _ = await LinkImportService._upsert_product_influencer(
                    db, item, run_at, product_id=product_id, task=task
                )
                if outcome == "new":
                    exec_result.new_count += 1
                elif outcome == "updated":
                    exec_result.updated_count += 1
            if entry:
                entry_url = str(entry.get("url") or "")
                if entry_url:
                    matched_entry_urls.add(entry_url)
        except Exception as exc:
            exec_result.import_failed += 1
            exec_result.import_errors.append(f"入库失败 {platform}: {exc}")

    for entry in entries:
        entry_url = str(entry.get("url") or "")
        if not entry_url or entry_url in matched_entry_urls:
            continue
        exec_result.import_failed += 1
        exec_result.import_errors.append(f"链接导入失败，未匹配到采集结果: {entry_url}")
        if task is not None:
            LinkImportService._record_profile_failed(
                exec_result,
                source_post_url=_entry_post_url(entry) or entry_url,
                platform=platform,
                failure_detail="未匹配到采集结果",
                run_at=run_at,
            )


class LinkImportService:
    @staticmethod
    async def list_batches(
        db: AsyncSession,
        page: int,
        page_size: int,
        *,
        product_id: int,
    ) -> PaginatedResponse[LinkImportBatchRead]:
        base = select(LinkImportBatch)
        if product_id is not None:
            base = base.where(LinkImportBatch.product_id == product_id)
        total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
        result = await db.execute(
            base.order_by(LinkImportBatch.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [LinkImportBatchRead.model_validate(row) for row in result.scalars().all()]
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def get_batch(
        db: AsyncSession,
        batch_id: int,
        *,
        product_id: int | None = None,
    ) -> LinkImportBatch | None:
        query = select(LinkImportBatch).where(LinkImportBatch.id == batch_id)
        if product_id is not None:
            query = query.where(LinkImportBatch.product_id == product_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_batch(
        db: AsyncSession,
        data: LinkImportBatchCreate,
        *,
        ctx: TenantContext,
    ) -> LinkImportBatch:
        lines = [line.strip() for line in data.raw_urls.splitlines() if line.strip()]
        if not lines:
            raise ValueError("请粘贴至少一行链接")
        valid_urls = validate_link_import_url_lines(lines)
        invalid_urls: list[str] = []
        total_count = len(lines)

        batch = LinkImportBatch(
            name=data.name.strip(),
            raw_urls=data.raw_urls,
            valid_urls=valid_urls,
            invalid_urls=invalid_urls,
            status=LinkImportBatchStatus.PENDING.value,
            total_count=total_count,
            failed_count=len(invalid_urls),
            user_id=ctx.user_id,
            workspace_id=ctx.workspace_id,
            product_id=require_write_product_id(ctx),
        )
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
        return batch

    @staticmethod
    async def run_batch(db: AsyncSession, batch: LinkImportBatch) -> LinkImportBatch:
        if batch.status == LinkImportBatchStatus.RUNNING.value:
            raise ValueError("Import batch is already running")
        if not batch.product_id:
            raise ValueError("导入批次未绑定产品，无法执行")

        batch.status = LinkImportBatchStatus.RUNNING.value
        batch.error_message = None
        await db.commit()
        await db.refresh(batch)

        run_at = datetime.now(UTC)
        valid_urls = batch.valid_urls or []
        product_id = batch.product_id

        try:
            exec_result = await LinkImportService._execute_url_import(
                db,
                valid_urls=valid_urls,
                invalid_urls=batch.invalid_urls or [],
                product_id=product_id,
                run_at=run_at,
            )

            success_count = len(valid_urls) - exec_result.import_failed
            invalid_count = len(batch.invalid_urls or [])
            batch.new_count = exec_result.new_count
            batch.updated_count = exec_result.updated_count
            batch.success_count = success_count
            batch.failed_count = invalid_count + exec_result.import_failed
            batch.status = LinkImportBatchStatus.COMPLETED.value
            batch.completed_at = run_at
            batch.error_message = summarize_errors(
                exec_result.import_errors,
                prefix="导入已完成，部分链接存在问题：" if exec_result.import_errors else "",
            )
            await db.commit()
            await db.refresh(batch)
            return batch

        except Exception as exc:
            batch.status = LinkImportBatchStatus.FAILED.value
            batch.error_message = str(exc)[:2000]
            batch.completed_at = run_at
            await db.commit()
            await db.refresh(batch)
            raise

    @staticmethod
    async def run_collection_task(db: AsyncSession, task: CollectionTask) -> dict[str, int]:
        if not task.product_id:
            raise ValueError("任务未绑定产品，无法执行")

        if task.collection_mode != CollectionMode.LINK_IMPORT.value:
            raise ValueError("仅链接导入任务可通过链接导入执行")

        run_at = datetime.now(UTC)
        valid_urls = validate_link_import_url_lines(list(task.input_urls or []))
        invalid_urls: list[str] = []

        try:
            exec_result = await LinkImportService._execute_url_import(
                db,
                valid_urls=valid_urls,
                invalid_urls=invalid_urls,
                product_id=task.product_id,
                task=task,
                run_at=run_at,
            )

            success_count = max(len(valid_urls) - exec_result.import_failed, 0)
            inserted_total = exec_result.new_count + exec_result.updated_count
            resolved_count = (
                inserted_total
                + exec_result.pending_profile_count
                + exec_result.not_inserted_count
                + exec_result.filtered_out_count
            )

            if success_count > 0 and exec_result.import_failed > 0:
                final_status = CollectionTaskStatus.PARTIAL_FAILED
            elif inserted_total > 0:
                final_status = CollectionTaskStatus.COMPLETED_WITH_RESULTS
            elif resolved_count > 0 or exec_result.pending_profile_count > 0:
                final_status = CollectionTaskStatus.COMPLETED_NO_RESULTS
            elif exec_result.filtered_out_count > 0:
                final_status = CollectionTaskStatus.COMPLETED_NO_RESULTS
            else:
                final_status = CollectionTaskStatus.FAILED

            task.status = final_status.value
            task.last_run_at = run_at
            task.last_error = None
            task.discovered_count = len(valid_urls)
            task.deduped_count = len(valid_urls)
            task.post_count = _count_link_import_posts(valid_urls)
            task.profile_fetched_count = exec_result.hydrated_profile_count
            task.profile_failed_count = exec_result.import_failed
            task.inserted_count = inserted_total
            task.result_count = inserted_total
            task.filtered_out_count = exec_result.filtered_out_count
            task.filtered_below_min_followers_count = exec_result.filtered_below_min
            task.filtered_excluded_keyword_count = exec_result.filtered_excluded
            task.current_stage = STAGE_COMPLETED
            filtered_note = (
                f"，过滤 {exec_result.filtered_out_count}" if exec_result.filtered_out_count else ""
            )
            not_inserted_note = (
                f"，未入库 {exec_result.not_inserted_count}" if exec_result.not_inserted_count else ""
            )
            pending_note = (
                f"，待补采 {exec_result.pending_profile_count}" if exec_result.pending_profile_count else ""
            )
            low_value_note = (
                f"，低价值 seed {exec_result.low_value_seed_count}" if exec_result.low_value_seed_count else ""
            )
            enrich_note = ""
            if exec_result.seed_enrichment_attempted:
                enrich_note = (
                    f"；已尝试社媒补全 {exec_result.seed_enrichment_attempted} 条"
                    f"（找到社媒主页 {exec_result.seed_social_profiles_found} 个）"
                )
            task.status_summary = (
                f"链接导入完成：成功 {success_count} 条，新增 {exec_result.new_count}，"
                f"更新 {exec_result.updated_count}{filtered_note}{not_inserted_note}{pending_note}"
                f"{low_value_note}{enrich_note}"
            )
            checkpoint = dict(task.run_checkpoint or {})
            checkpoint["link_seed_enrichment"] = {
                "attempted": exec_result.seed_enrichment_attempted,
                "social_profiles_found": exec_result.seed_social_profiles_found,
                "low_value_seed_count": exec_result.low_value_seed_count,
            }
            task.run_checkpoint = checkpoint
            task.error_message = summarize_errors(
                exec_result.import_errors,
                prefix="导入已完成，部分链接存在问题：" if exec_result.import_errors else "",
            )

            await TaskCandidateService.clear_for_task(db, task.id)
            if exec_result.candidate_rows:
                await TaskCandidateService.bulk_insert(
                    db,
                    task.id,
                    exec_result.candidate_rows,
                    run_at=run_at,
                    product_id=task.product_id,
                    user_id=task.user_id,
                )
            await TaskCandidateService.sync_task_inserted_stats(db, task)

            await TaskInfluencerService.refresh_task_stats(db, task)
            await db.commit()
            await db.refresh(task)

            return {
                "new_count": exec_result.new_count,
                "updated_count": exec_result.updated_count,
                "skipped_count": exec_result.not_inserted_count,
                "filtered_count": exec_result.filtered_out_count,
                "total_count": inserted_total,
                "discovered_count": len(valid_urls),
                "deduped_count": len(valid_urls),
                "profile_fetched_count": exec_result.hydrated_profile_count,
                "profile_failed_count": exec_result.import_failed,
                "filtered_out_count": exec_result.filtered_out_count,
                "inserted_count": inserted_total,
                "hashtag_count": 0,
                "post_count": task.post_count,
                "comment_author_count": 0,
                "email_count": task.email_count,
                "missing_contact_count": task.missing_contact_count,
                "status_summary": task.status_summary,
            }
        except Exception as exc:
            task.status = CollectionTaskStatus.FAILED.value
            task.error_message = str(exc)[:2000]
            task.current_stage = STAGE_FAILED
            task.last_error = task.error_message
            task.last_run_at = run_at
            await db.commit()
            raise

    @staticmethod
    def _link_import_candidate_context(
        item: CollectedInfluencer,
        *,
        source_post_url: str | None,
        source_input_url: str | None = None,
        run_at: datetime,
        enrichment_meta: dict | None = None,
        source_type: str | None = None,
        source_discovery_type: str | None = None,
    ) -> dict:
        meta = {
            "source_input_url": source_input_url or getattr(item, "source_input_url", None),
        }
        if enrichment_meta:
            meta["link_seed_enrichment"] = enrichment_meta
            meta["link_seed_platform"] = enrichment_meta.get("link_seed_platform")
            meta["link_seed_profile_url"] = enrichment_meta.get("link_seed_profile_url")
            meta["link_seed_username"] = enrichment_meta.get("link_seed_username")
            enriched = enrichment_meta.get("enriched_platform") or enrichment_meta.get("primary_platform")
            if enriched:
                meta["enriched_platform"] = enriched
            if enrichment_meta.get("enriched_profile_url"):
                meta["enriched_profile_url"] = enrichment_meta.get("enriched_profile_url")
            if enrichment_meta.get("enrichment_candidates"):
                meta["enrichment_candidates"] = enrichment_meta.get("enrichment_candidates")
            if enrichment_meta.get("selected_reason"):
                meta["selected_reason"] = enrichment_meta.get("selected_reason")
            for key in (
                "discovery_source",
                "discovery_query",
                "source_platform",
                "source_profile_url",
                "source_post_url",
                "source_input_url",
            ):
                if enrichment_meta.get(key):
                    meta[key] = enrichment_meta.get(key)
            detail_fetched = enrichment_meta.get("platform_detail_fetched") or enrichment_meta.get("instagram_detail_fetched")
            if detail_fetched:
                meta["instagram_detail_fetched"] = enrichment_meta.get("instagram_detail_fetched")
                meta["platform_detail_fetched"] = enrichment_meta.get("platform_detail_fetched")
                meta["profile_snapshot"] = collected_profile_snapshot(item)
        return {
            "username": item.username or "",
            "profile_url": item.profile_url,
            "platform": item.platform or "instagram",
            "source_type": source_type or CandidateSourceType.LINK_IMPORT.value,
            "source_discovery_type": source_discovery_type or item.source_discovery_type or "url_profile",
            "source_post_url": source_post_url or item.source_post_url,
            "source_meta": meta,
            "source_input_url": source_input_url or getattr(item, "source_input_url", None),
            "followers_count": item.followers_count,
            "engagement_rate": item.engagement_rate,
            "profile_fetched_at": run_at,
        }

    @staticmethod
    def _record_profile_failed(
        exec_result: LinkImportExecuteResult,
        *,
        source_post_url: str | None,
        platform: str,
        username: str = "",
        profile_url: str | None = None,
        failure_detail: str | None = None,
        run_at: datetime,
    ) -> None:
        exec_result.candidate_rows.append(
            TaskCandidateService.row_from_failed(
                username=username,
                profile_url=profile_url or source_post_url,
                failure_reason="profile_fetch_failed",
                failure_detail=failure_detail,
                platform=platform,
                source_discovery_type="url_profile",
                source_type=CandidateSourceType.INPUT_PROFILE.value,
                source_post_url=source_post_url,
                profile_fetched_at=run_at,
            )
        )

    @staticmethod
    def _seed_enriched_detail_pending(enrichment_meta: dict | None) -> bool:
        if not enrichment_meta:
            return False
        seed = str(enrichment_meta.get("link_seed_platform") or "").strip().lower()
        if seed not in LINK_SEED_PLATFORMS:
            return False
        enriched = str(
            enrichment_meta.get("enriched_platform") or enrichment_meta.get("primary_platform") or ""
        ).strip().lower()
        if not enriched or enriched in LINK_SEED_PLATFORMS:
            return False
        fetched = enrichment_meta.get("platform_detail_fetched") or enrichment_meta.get("instagram_detail_fetched")
        return not bool(fetched)

    @staticmethod
    def _seed_enriched_instagram_detail_pending(enrichment_meta: dict | None) -> bool:
        return LinkImportService._seed_enriched_detail_pending(enrichment_meta)

    @staticmethod
    async def _process_import_item(
        db: AsyncSession,
        item: CollectedInfluencer,
        *,
        source_post_url: str | None,
        source_input_url: str | None = None,
        run_at: datetime,
        product_id: int,
        task: CollectionTask | None,
        exec_result: LinkImportExecuteResult,
        enrichment_meta: dict | None = None,
        source_type: str | None = None,
        source_discovery_type: str | None = None,
    ) -> None:
        if source_post_url and not item.source_post_url:
            item.source_post_url = source_post_url
        if source_input_url and not getattr(item, "source_input_url", None):
            item.source_input_url = source_input_url
        if task is None:
            outcome, _ = await LinkImportService._upsert_product_influencer(
                db, item, run_at, product_id=product_id, task=task
            )
            if outcome == "new":
                exec_result.new_count += 1
            elif outcome == "updated":
                exec_result.updated_count += 1
            return

        platform = item.platform or "instagram"
        base = LinkImportService._link_import_candidate_context(
            item,
            source_post_url=source_post_url,
            source_input_url=source_input_url or getattr(item, "source_input_url", None),
            run_at=run_at,
            enrichment_meta=enrichment_meta,
            source_type=source_type,
            source_discovery_type=source_discovery_type,
        )

        hard = evaluate_post_hydration_hard_filter(item, task)
        if (
            not hard.passed
            and hard.reason == "below_min_followers"
            and item.followers_count is None
            and LinkImportService._seed_enriched_detail_pending(enrichment_meta)
        ):
            hard = PostHydrationHardFilterResult(True)
        if not hard.passed:
            follower_deferred = (
                hard.reason == "below_min_followers"
                and (
                    getattr(task, "strict_quality_filter", False)
                    or getattr(task, "insert_qualified_only", False)
                )
            )
            if not follower_deferred:
                exec_result.filtered_out_count += 1
                if hard.reason == "below_min_followers":
                    exec_result.filtered_below_min += 1
                elif hard.reason and hard.reason.startswith("excluded_keyword:"):
                    exec_result.filtered_excluded += 1
                row = TaskCandidateService.row_from_filtered(
                    failure_reason=hard.reason,
                    failure_detail=hard_filter_failure_detail(
                        hard.reason,
                        task=task,
                        followers_count=item.followers_count,
                        platform=platform,
                    ),
                    **base,
                )
                exec_result.candidate_rows.append(row)
                return

        assessment = evaluate_high_value_assessment(item, task)
        if should_strict_filter_out(task, assessment):
            exec_result.filtered_out_count += 1
            if assessment.filter_reason == "below_min_followers":
                exec_result.filtered_below_min += 1
            row = TaskCandidateService.row_from_filtered(
                failure_reason=assessment.filter_reason,
                failure_detail=assessment.filter_detail,
                **base,
            )
            row.update(assessment_row_fields(assessment))
            exec_result.candidate_rows.append(row)
            return

        if should_skip_insert(task, assessment):
            exec_result.not_inserted_count += 1
            row = TaskCandidateService.row_from_not_inserted(
                failure_reason=assessment.filter_reason,
                failure_detail=assessment.insert_blocked_reason,
                insert_blocked_reason=assessment.insert_blocked_reason,
                is_high_value=assessment.is_high_value,
                has_email=assessment.has_email,
                has_contact=assessment.has_contact,
                contact_status=assessment.contact_status,
                **base,
            )
            row.update(assessment_row_fields(assessment))
            exec_result.candidate_rows.append(row)
            return

        seed_platform = None
        if enrichment_meta:
            seed_platform = str(enrichment_meta.get("link_seed_platform") or "").strip().lower() or None
        elif platform in LINK_SEED_PLATFORMS:
            seed_platform = platform

        if seed_platform and LinkImportService._seed_enriched_detail_pending(enrichment_meta):
            low_value_detail = link_seed_low_value_detail(seed_platform)
            exec_result.low_value_seed_count += 1
            exec_result.not_inserted_count += 1
            row = TaskCandidateService.row_from_not_inserted(
                failure_reason="low_value_seed",
                failure_detail=low_value_detail,
                insert_blocked_reason=low_value_detail,
                is_high_value=False,
                has_email=assessment.has_email,
                has_contact=assessment.has_contact,
                contact_status=assessment.contact_status,
                **base,
            )
            row.update(assessment_row_fields(assessment))
            row["is_high_value"] = False
            row["status"] = CandidateStatus.NOT_INSERTED.value
            exec_result.candidate_rows.append(row)
            return

        if seed_platform and not is_influencer_profile_valuable(item):
            low_value_detail = link_seed_low_value_detail(seed_platform)
            exec_result.low_value_seed_count += 1
            exec_result.not_inserted_count += 1
            row = TaskCandidateService.row_from_not_inserted(
                failure_reason="low_value_seed",
                failure_detail=low_value_detail,
                insert_blocked_reason=low_value_detail,
                is_high_value=False,
                has_email=assessment.has_email,
                has_contact=assessment.has_contact,
                contact_status=assessment.contact_status,
                **base,
            )
            row.update(assessment_row_fields(assessment))
            row["is_high_value"] = False
            row["status"] = CandidateStatus.NOT_INSERTED.value
            exec_result.candidate_rows.append(row)
            return

        if is_url_only_metrics_pending(item):
            exec_result.pending_profile_count += 1
            row = {
                **base,
                "status": CandidateStatus.PENDING_PROFILE.value,
                "failure_reason": "missing_profile_detail",
                "failure_detail": URL_ONLY_PENDING_DETAIL,
                "is_high_value": False,
                "has_email": assessment.has_email,
                "has_contact": assessment.has_contact,
                "contact_status": assessment.contact_status,
                "insert_blocked_reason": URL_ONLY_PENDING_DETAIL,
            }
            row.update(assessment_row_fields(assessment))
            row["is_high_value"] = False
            exec_result.candidate_rows.append(row)
            return

        outcome, product_record = await LinkImportService._upsert_product_influencer(
            db, item, run_at, product_id=product_id, task=task
        )
        global_profile = None
        if product_record and product_record.global_influencer_id:
            global_profile = await db.get(GlobalInfluencerProfile, product_record.global_influencer_id)
        if outcome == "new":
            exec_result.new_count += 1
        elif outcome == "updated":
            exec_result.updated_count += 1
        elif outcome == "unchanged":
            row = TaskCandidateService.row_from_duplicate(
                meta=None,
                username=item.username,
                profile_url=item.profile_url,
                platform=platform,
                collection_mode=task.collection_mode,
                followers_count=item.followers_count,
                engagement_rate=item.engagement_rate,
                profile_fetched_at=run_at,
                detail="红人库中已存在相同主页，本次已刷新采集时间",
            )
            row.update(
                {
                    **base,
                    "product_influencer_id": product_record.id if product_record else None,
                    "global_influencer_id": global_profile.id if global_profile else None,
                    "product_id": task.product_id,
                    "user_id": task.user_id,
                }
            )
            row.update(assessment_row_fields(assessment))
            exec_result.candidate_rows.append(row)
            exec_result.hydrated_profile_count += 1
            return
        exec_result.hydrated_profile_count += 1

        row = TaskCandidateService.row_from_inserted(
            meta=None,
            username=item.username,
            profile_url=item.profile_url,
            platform=platform,
            collection_mode=task.collection_mode,
            product_influencer_id=product_record.id if product_record else None,
            global_influencer_id=global_profile.id if global_profile else None,
            product_id=task.product_id,
            user_id=task.user_id,
            followers_count=item.followers_count,
            engagement_rate=item.engagement_rate,
            profile_fetched_at=run_at,
            source_type=base["source_type"],
            source_discovery_type=base["source_discovery_type"],
            source_post_url=base["source_post_url"],
            source_input_url=base.get("source_input_url"),
        )
        row.update(base)
        row.update(assessment_row_fields(assessment))
        exec_result.candidate_rows.append(row)

    @staticmethod
    async def _execute_url_import(
        db: AsyncSession,
        *,
        valid_urls: list[dict[str, str]],
        invalid_urls: list[str],
        product_id: int,
        task: CollectionTask | None = None,
        run_at: datetime | None = None,
    ) -> LinkImportExecuteResult:
        run_at = run_at or datetime.now(UTC)
        exec_result = LinkImportExecuteResult(import_failed=len(invalid_urls))

        resolved_urls: list[dict[str, str | None]] = []
        for entry in valid_urls:
            url = entry.get("url", "")
            if not url:
                continue
            merged = dict(entry)
            parsed = await resolve_import_link(url)
            if parsed is not None:
                merged.update(parsed_to_valid_entry(parsed))
                merged["url"] = url
            resolved_urls.append(merged)
        valid_urls = resolved_urls

        instagram_entries: list[dict[str, str | None]] = []
        url_only_items: list[tuple[dict[str, str | None], CollectedInfluencer]] = []
        provider_import_urls: dict[str, list[dict[str, str | None]]] = {}

        for entry in valid_urls:
            url = entry.get("url", "") or ""
            platform = entry.get("platform", "") or ""
            source_post_url = _entry_post_url(entry)
            if not url or not platform:
                exec_result.import_failed += 1
                continue
            if platform == "instagram":
                instagram_entries.append(entry)
            elif platform == "tiktok":
                profile = tiktok_profile_from_url(url)
                if profile is None:
                    exec_result.import_failed += 1
                    exec_result.import_errors.append(f"无法解析 TikTok 链接: {url}")
                    if task is not None:
                        LinkImportService._record_profile_failed(
                            exec_result,
                            source_post_url=source_post_url or url,
                            platform="tiktok",
                            failure_detail="无法解析 TikTok 链接",
                            run_at=run_at,
                        )
                    continue
                if source_post_url and not profile.source_post_url:
                    profile = PlatformCandidateProfile(
                        platform=profile.platform,
                        username=profile.username,
                        profile_url=entry.get("profile_url") or profile.profile_url,
                        display_name=profile.display_name,
                        source_url=profile.source_url,
                        source_post_url=source_post_url,
                        source_type=profile.source_type,
                        source_discovery_type=profile.source_discovery_type,
                        source_meta=profile.source_meta,
                        followers_count=profile.followers_count,
                        engagement_rate=profile.engagement_rate,
                    )
                url_only_items.append((entry, profile_to_collected(profile)))
            elif platform in PARSERS:
                profile = PARSERS[platform](url)
                if profile is None:
                    exec_result.import_failed += 1
                    exec_result.import_errors.append(f"无法解析链接: {url}")
                    if task is not None:
                        LinkImportService._record_profile_failed(
                            exec_result,
                            source_post_url=source_post_url or url,
                            platform=platform,
                            failure_detail="无法解析链接",
                            run_at=run_at,
                        )
                    continue
                if source_post_url and not profile.source_post_url:
                    profile = PlatformCandidateProfile(
                        platform=profile.platform,
                        username=profile.username,
                        profile_url=profile.profile_url,
                        display_name=profile.display_name,
                        source_url=profile.source_url,
                        source_post_url=source_post_url,
                        source_type=profile.source_type,
                        source_discovery_type=profile.source_discovery_type,
                        source_meta=profile.source_meta,
                        followers_count=profile.followers_count,
                        engagement_rate=profile.engagement_rate,
                    )
                url_only_items.append((entry, profile_to_collected(profile)))
            elif platform in ("youtube", "facebook"):
                provider_import_urls.setdefault(platform, []).append(entry)
            else:
                exec_result.import_failed += 1
                exec_result.import_errors.append(f"不支持的平台链接: {url}")

        instagram_post_entries: list[dict[str, str | None]] = []
        instagram_profile_entries: list[dict[str, str | None]] = []
        for entry in instagram_entries:
            if _is_instagram_post_entry(entry):
                instagram_post_entries.append(entry)
            else:
                instagram_profile_entries.append(entry)

        if instagram_post_entries:
            post_urls = [str(entry.get("url") or "") for entry in instagram_post_entries if entry.get("url")]
            post_discovery = await discover_post_authors_from_post_urls(post_urls)
            exec_result.import_errors.extend(post_discovery.errors)
            post_to_candidate = {
                _normalize_lookup_url(candidate.source_post_url): candidate
                for candidate in post_discovery.candidates
                if candidate.source_post_url
            }
            profile_urls = list({candidate.profile_url for candidate in post_discovery.candidates if candidate.profile_url})
            apify_by_username: dict[str, CollectedInfluencer] = {}
            if profile_urls:
                scrape_result = await scrape_instagram_profiles(profile_urls)
                apify_by_username = {item.username.lower(): item for item in scrape_result.profiles}
                for item in scrape_result.profiles:
                    await ContactDiscoveryService.enrich_collected(item)
                exec_result.import_errors.extend(scrape_result.errors)

            for entry in instagram_post_entries:
                url = str(entry.get("url") or "")
                platform = str(entry.get("platform") or "instagram")
                source_post_url = _entry_post_url(entry) or url
                candidate = post_to_candidate.get(_normalize_lookup_url(url))
                if candidate:
                    source_post_url = source_post_url or candidate.source_post_url or url
                try:
                    username = (
                        (entry.get("username") or (candidate.username if candidate else "") or _username_from_url(url) or "")
                        .lower()
                    )
                    item = apify_by_username.get(username) if username else None
                    if not item and candidate and len(apify_by_username) == 1:
                        item = next(iter(apify_by_username.values()))
                    if not item:
                        exec_result.import_failed += 1
                        exec_result.import_errors.append(f"链接导入失败，未匹配到采集结果: {url}")
                        if task is not None:
                            LinkImportService._record_profile_failed(
                                exec_result,
                                source_post_url=source_post_url,
                                platform=platform,
                                username=username,
                                profile_url=candidate.profile_url if candidate else None,
                                failure_detail="未匹配到采集结果",
                                run_at=run_at,
                            )
                        continue
                    await LinkImportService._process_import_item(
                        db,
                        item,
                        source_post_url=source_post_url,
                        source_input_url=url,
                        run_at=run_at,
                        product_id=product_id,
                        task=task,
                        exec_result=exec_result,
                    )
                except Exception as exc:
                    exec_result.import_failed += 1
                    exec_result.import_errors.append(f"入库失败 {url}: {exc}")

        if instagram_profile_entries:
            profile_urls = [
                str(entry.get("url") or "")
                for entry in instagram_profile_entries
                if entry.get("url")
            ]
            apify_by_username = {}
            if profile_urls:
                scrape_result = await scrape_instagram_profiles(profile_urls)
                apify_by_username = {item.username.lower(): item for item in scrape_result.profiles}
                for item in scrape_result.profiles:
                    await ContactDiscoveryService.enrich_collected(item)
                exec_result.import_errors.extend(scrape_result.errors)
                if not scrape_result.profiles and profile_urls:
                    exec_result.import_errors.append(
                        f"未返回任何主页数据（请求 {len(profile_urls)} 条 Instagram 主页链接）"
                    )

            for entry in instagram_profile_entries:
                url = str(entry.get("url") or "")
                platform = str(entry.get("platform") or "instagram")
                source_post_url = _entry_post_url(entry)
                try:
                    username = (entry.get("username") or _username_from_url(url) or "").lower()
                    item = apify_by_username.get(username) if username else None
                    if not item and len(apify_by_username) == 1 and len(instagram_profile_entries) == 1:
                        item = next(iter(apify_by_username.values()))
                    if not item:
                        exec_result.import_failed += 1
                        exec_result.import_errors.append(f"链接导入失败，未匹配到采集结果: {url}")
                        if task is not None:
                            LinkImportService._record_profile_failed(
                                exec_result,
                                source_post_url=source_post_url or url,
                                platform=platform,
                                username=username,
                                profile_url=f"https://www.instagram.com/{username}/" if username else None,
                                failure_detail="未匹配到采集结果",
                                run_at=run_at,
                            )
                        continue
                    await LinkImportService._process_import_item(
                        db,
                        item,
                        source_post_url=source_post_url,
                        source_input_url=url,
                        run_at=run_at,
                        product_id=product_id,
                        task=task,
                        exec_result=exec_result,
                    )
                except Exception as exc:
                    exec_result.import_failed += 1
                    exec_result.import_errors.append(f"入库失败 {url}: {exc}")

        for entry, item in url_only_items:
            source_post_url = _entry_post_url(entry)
            entry_url = str(entry.get("url") or "")
            enrichment_meta: dict | None = None
            try:
                if (item.platform or "").lower() in LINK_SEED_PLATFORMS:
                    exec_result.seed_enrichment_attempted += 1
                    enrichment = await enrich_link_seed_item(item)
                    enrichment_meta = enrichment_meta_dict(enrichment)
                    exec_result.seed_social_profiles_found += enrichment.social_profiles_found
                    item = enrichment.item
                    if enrichment.enrichment_attempted:
                        exec_result.hydrated_profile_count += 1
                await LinkImportService._process_import_item(
                    db,
                    item,
                    source_post_url=source_post_url,
                    source_input_url=entry_url,
                    run_at=run_at,
                    product_id=product_id,
                    task=task,
                    exec_result=exec_result,
                    enrichment_meta=enrichment_meta,
                )
            except Exception as exc:
                exec_result.import_failed += 1
                exec_result.import_errors.append(f"入库失败 {entry.get('url', '')}: {exc}")

        if provider_import_urls and task is not None:
            for platform, entries in provider_import_urls.items():
                urls = [entry.get("url", "") or "" for entry in entries]
                mini_task = CollectionTask(
                    name=task.name,
                    platform=platform,
                    platforms=[platform],
                    input_urls=urls,
                    keywords=[],
                    collection_mode=CollectionMode.URLS.value,
                    discovery_limit=task.discovery_limit or max(len(urls), 10),
                    min_engagement_rate=task.min_engagement_rate or 0,
                    min_followers_count=task.min_followers_count,
                    max_followers_count=task.max_followers_count,
                    filter_include_keywords=task.filter_include_keywords or [],
                    filter_exclude_keywords=task.filter_exclude_keywords or [],
                    country=task.country,
                    category=task.category,
                    product_id=task.product_id,
                )
                try:
                    result = await discover_platform(mini_task, platform)
                    exec_result.import_errors.extend(result.errors)
                    if not result.items:
                        exec_result.import_failed += len(urls)
                        if result.skip_reason:
                            exec_result.import_errors.append(result.skip_reason)
                        for entry in entries:
                            entry_url = str(entry.get("url") or "")
                            LinkImportService._record_profile_failed(
                                exec_result,
                                source_post_url=_entry_post_url(entry) or entry_url,
                                platform=platform,
                                failure_detail=result.skip_reason or "未返回主页数据",
                                run_at=run_at,
                            )
                        continue
                    await _process_provider_import_items(
                        db,
                        platform=platform,
                        entries=entries,
                        items=result.items,
                        product_id=product_id,
                        task=task,
                        run_at=run_at,
                        exec_result=exec_result,
                    )
                except Exception as exc:
                    exec_result.import_failed += len(urls)
                    exec_result.import_errors.append(f"{platform} 链接导入失败: {exc}")
                    for entry in entries:
                        entry_url = str(entry.get("url") or "")
                        LinkImportService._record_profile_failed(
                            exec_result,
                            source_post_url=_entry_post_url(entry) or entry_url,
                            platform=platform,
                            failure_detail=str(exc)[:500],
                            run_at=run_at,
                        )
        elif provider_import_urls:
            for platform, entries in provider_import_urls.items():
                urls = [entry.get("url", "") or "" for entry in entries]
                mini_task = CollectionTask(
                    name=task.name if task else "batch",
                    platform=platform,
                    platforms=[platform],
                    input_urls=urls,
                    keywords=[],
                    collection_mode=CollectionMode.URLS.value,
                    discovery_limit=max(len(urls), 10),
                    product_id=product_id,
                )
                try:
                    result = await discover_platform(mini_task, platform)
                    exec_result.import_errors.extend(result.errors)
                    if not result.items:
                        exec_result.import_failed += len(urls)
                        if result.skip_reason:
                            exec_result.import_errors.append(result.skip_reason)
                        continue
                    await _process_provider_import_items(
                        db,
                        platform=platform,
                        entries=entries,
                        items=result.items,
                        product_id=product_id,
                        task=task,
                        run_at=run_at,
                        exec_result=exec_result,
                    )
                except Exception as exc:
                    exec_result.import_failed += len(urls)
                    exec_result.import_errors.append(f"{platform} 链接导入失败: {exc}")

        return exec_result

    @staticmethod
    async def _upsert_product_influencer(
        db: AsyncSession,
        item: CollectedInfluencer,
        run_at: datetime,
        *,
        product_id: int,
        task: CollectionTask | None = None,
    ) -> tuple[str, ProductInfluencer | None]:
        global_map = await InfluencerPersistenceService.find_global_profiles_batch(db, [item])
        product_map = await InfluencerPersistenceService.find_product_influencers_batch(
            db, product_id, [item], global_map=global_map
        )
        identity_key = identity_key_for_item(item)
        global_profile = global_map.get(identity_key)
        product_record = product_map.get(identity_key)

        if product_record:
            if not product_record_has_changes(product_record, item, task):
                product_record.last_collected_at = run_at
                await InfluencerSourceService.record_from_collected(
                    db,
                    product_record,
                    item,
                    task=task,
                    run_at=run_at,
                    source_input_url=getattr(item, "source_input_url", None),
                    source_post_url=item.source_post_url,
                )
                await db.flush()
                return "unchanged", product_record
            if global_profile and (
                should_refresh_global_profile(global_profile, now=run_at)
                or global_profile_has_changes(global_profile, item)
            ):
                apply_global_profile_data(global_profile, item, run_at=run_at)
            apply_product_influencer_data(product_record, item, task, run_at=run_at)
            await InfluencerSourceService.record_from_collected(
                db,
                product_record,
                item,
                task=task,
                run_at=run_at,
                source_input_url=getattr(item, "source_input_url", None),
                source_post_url=item.source_post_url,
            )
            await LinkImportService._analyze_product_influencer(db, product_record, global_profile)
            return "updated", product_record

        if not global_profile:
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db.add(global_profile)
            await db.flush()
        elif should_refresh_global_profile(global_profile, now=run_at) or global_profile_has_changes(
            global_profile, item
        ):
            apply_global_profile_data(global_profile, item, run_at=run_at)

        product_record = create_product_influencer_from_collected(
            product_id=product_id,
            global_profile=global_profile,
            data=item,
            task=task,
            run_at=run_at,
        )
        db.add(product_record)
        await db.flush()
        await InfluencerSourceService.record_from_collected(
            db, product_record, item, task=task, run_at=run_at,
            source_input_url=getattr(item, "source_input_url", None),
            source_post_url=item.source_post_url,
        )
        await LinkImportService._analyze_product_influencer(db, product_record, global_profile)
        return "new", product_record

    @staticmethod
    async def _analyze_product_influencer(
        db: AsyncSession,
        product_row: ProductInfluencer,
        global_row: GlobalInfluencerProfile | None,
    ) -> None:
        if not global_row:
            return
        try:
            merged = merged_influencer_for_ai(product_row, global_row)
            analysis = await analyze_influencer(merged)
            apply_ai_to_product_record(product_row, analysis, global_row=global_row)
        except Exception as exc:
            logger.warning("Link import AI failed for %s: %s", global_row.username, exc)
