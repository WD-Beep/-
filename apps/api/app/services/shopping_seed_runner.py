# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：shopping seed runner
"""导购型 seed 自动发现 + 多平台详情补全任务执行。"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.enums import CandidateSourceType, CollectionMode, CollectionTaskStatus
from app.services.collect_errors import summarize_errors
from app.services.collection_targets import target_qualified_count
from app.services.link_import import LinkImportExecuteResult, LinkImportService
from app.services.link_seed_enrichment import enrich_link_seed_item, enrichment_meta_dict
from app.services.shopping_seed_checkpoint import (
    append_checkpoint_value,
    append_nested_checkpoint_value,
    checkpoint_nested_set,
    checkpoint_set,
    increment_checkpoint_count,
    normalize_checkpoint_key,
)
from app.services.shopping_seed_discovery import (
    build_shopping_seed_search_keywords_for_task,
    discover_shopping_seeds_from_task,
)
from app.services.shopping_seed_discovery_provider import build_seed_search_diagnostics
from app.services.task_candidate import TaskCandidateService
from app.services.task_influencer import TaskInfluencerService
from app.services.task_run_progress import STAGE_COMPLETED


@dataclass
class KeywordSeedDiscoveryResult:
    exec_result: LinkImportExecuteResult
    discovered_count: int
    seed_enriched_count: int
    platform_failed_count: int
    skipped_platform_count: int


def _provider_failed_but_fallback_ran(diag: dict, checkpoint: dict) -> bool:
    provider_state = checkpoint.get("provider_availability_state")
    if not isinstance(provider_state, dict) or not provider_state:
        provider_state = diag.get("provider_availability_state")
    if not isinstance(provider_state, dict) or not provider_state:
        return False
    search_platforms = diag.get("search_platforms")
    if not isinstance(search_platforms, list) or "public_web" not in search_platforms:
        return False
    public_web_query_count = diag.get("public_web_query_count")
    if isinstance(public_web_query_count, int) and public_web_query_count > 0:
        return True
    completed = checkpoint.get("completed_queries")
    failed = checkpoint.get("failed_queries")
    return bool(
        (isinstance(completed, list) and completed)
        or (isinstance(failed, list) and failed)
    )


def _zero_seed_reason_for_provider_state(diag: dict, checkpoint: dict) -> str | None:
    if _provider_failed_but_fallback_ran(diag, checkpoint):
        return "provider_failed_but_fallback_no_results"
    provider_state = checkpoint.get("provider_availability_state")
    if not isinstance(provider_state, dict) or not provider_state:
        provider_state = diag.get("provider_availability_state")
    if not isinstance(provider_state, dict):
        return None
    pinterest_state = provider_state.get("pinterest_apify")
    if not isinstance(pinterest_state, dict):
        return None
    reason = str(pinterest_state.get("reason") or "")
    if reason == "query_timeout":
        return "pinterest_apify_timeout"
    if reason == "network_unreachable":
        return "pinterest_apify_network_unreachable"
    if reason == "apify_memory_limit_exceeded":
        return "apify_memory_limit_exceeded"
    return None


class ShoppingSeedDiscoveryService:
    @staticmethod
    async def _discover_seeds(db: AsyncSession, task: CollectionTask):
        signature = inspect.signature(discover_shopping_seeds_from_task)
        if "db" in signature.parameters:
            return await discover_shopping_seeds_from_task(task, db=db)
        return await discover_shopping_seeds_from_task(task)

    @staticmethod
    async def _process_seed_items(
        db: AsyncSession,
        task: CollectionTask,
        seeds,
        *,
        run_at: datetime,
    ) -> tuple[LinkImportExecuteResult, int, int, int]:
        exec_result = LinkImportExecuteResult(import_failed=0)
        seed_enriched_count = 0
        platform_failed_count = 0
        skipped_platform_count = 0
        checkpoint = dict(task.run_checkpoint or {})
        completed_seed_urls = checkpoint_set(checkpoint, "completed_seed_urls")
        completed_profile_urls = checkpoint_set(checkpoint, "completed_profile_urls")
        pending_seeds = []

        async def _persist_checkpoint() -> None:
            task.run_checkpoint = checkpoint
            await db.commit()

        def _is_profile_detail_completed(platform: str | None, profile_url: str | None) -> bool:
            marker = normalize_checkpoint_key(profile_url)
            if not marker:
                return False
            if marker in completed_profile_urls:
                return True
            platform_key = normalize_checkpoint_key(platform)
            return bool(
                platform_key
                and marker in checkpoint_nested_set(checkpoint, "platform_detail_completed", platform_key)
            )

        for seed in seeds:
            seed_url = seed.profile_url
            if (
                normalize_checkpoint_key(seed_url) in completed_seed_urls
                or _is_profile_detail_completed(seed.platform, seed_url)
            ):
                increment_checkpoint_count(checkpoint, "skipped_due_checkpoint_count")
                append_checkpoint_value(checkpoint, "completed_seed_urls", seed_url)
                await _persist_checkpoint()
                continue
            pending_seeds.append(seed)

        async def _enrich_one(seed):
            seed_url = seed.profile_url
            try:
                timeout = max(3, settings.link_seed_enrich_timeout_seconds)
                enrichment = await asyncio.wait_for(enrich_link_seed_item(seed), timeout=timeout)
                return seed, enrichment, None
            except TimeoutError:
                return seed, None, f"Shopping seed timed out {seed_url}: link_seed_enrich_timeout"
            except Exception as exc:
                return seed, None, f"Shopping seed failed {seed_url}: {exc}"

        sem = asyncio.Semaphore(max(1, settings.link_seed_enrich_concurrency))

        async def _bounded_enrich(seed):
            async with sem:
                return await _enrich_one(seed)

        concurrency = max(1, settings.link_seed_enrich_concurrency)
        target = target_qualified_count(task)
        for start in range(0, len(pending_seeds), concurrency):
            if exec_result.new_count + exec_result.updated_count >= target:
                break
            batch = pending_seeds[start : start + concurrency]
            enrich_results = await asyncio.gather(*[_bounded_enrich(seed) for seed in batch])

            for seed, enrichment, error in enrich_results:
                if exec_result.new_count + exec_result.updated_count >= target:
                    break
                seed_url = seed.profile_url
                if error or enrichment is None:
                    exec_result.import_failed += 1
                    exec_result.import_errors.append(error or f"Shopping seed failed {seed_url}")
                    append_checkpoint_value(checkpoint, "failed_seed_urls", seed_url)
                    await _persist_checkpoint()
                    continue

                item = enrichment.item
                if _is_profile_detail_completed(item.platform, item.profile_url):
                    increment_checkpoint_count(checkpoint, "skipped_due_checkpoint_count")
                    append_checkpoint_value(checkpoint, "completed_seed_urls", seed_url)
                    if append_checkpoint_value(checkpoint, "completed_profile_urls", item.profile_url):
                        completed_profile_urls.add(normalize_checkpoint_key(item.profile_url))
                    append_nested_checkpoint_value(
                        checkpoint,
                        "platform_detail_completed",
                        item.platform,
                        item.profile_url,
                    )
                    await _persist_checkpoint()
                    continue

                exec_result.seed_enrichment_attempted += 1
                enrichment_meta = enrichment_meta_dict(enrichment)
                seed_source_meta = dict(getattr(seed, "source_meta", {}) or {})
                for key, value in seed_source_meta.items():
                    enrichment_meta.setdefault(key, value)
                if enrichment.enriched_profile_url or enrichment.primary_platform:
                    seed_enriched_count += 1
                for candidate in enrichment.enrichment_candidates or []:
                    status = str(candidate.get("status") or "").lower()
                    if status == "failed":
                        platform_failed_count += 1
                    elif status in {"skipped", "timeout"}:
                        skipped_platform_count += 1
                exec_result.seed_social_profiles_found += enrichment.social_profiles_found
                if enrichment.enrichment_attempted:
                    exec_result.hydrated_profile_count += 1
                await LinkImportService._process_import_item(
                    db,
                    item,
                    source_post_url=seed.source_post_url,
                    source_input_url=seed_url,
                    run_at=run_at,
                    product_id=task.product_id,
                    task=task,
                    exec_result=exec_result,
                    enrichment_meta=enrichment_meta,
                    source_type=CandidateSourceType.LINK_SEED_DISCOVERED.value,
                    source_discovery_type="link_seed_expanded",
                )
                append_checkpoint_value(checkpoint, "completed_seed_urls", seed_url)
                if item.profile_url:
                    if append_checkpoint_value(checkpoint, "completed_profile_urls", item.profile_url):
                        completed_profile_urls.add(normalize_checkpoint_key(item.profile_url))
                    append_nested_checkpoint_value(
                        checkpoint,
                        "platform_detail_completed",
                        item.platform,
                        item.profile_url,
                    )
                checkpoint["seed_enriched_count"] = seed_enriched_count
                await _persist_checkpoint()

        task.run_checkpoint = checkpoint
        return exec_result, seed_enriched_count, platform_failed_count, skipped_platform_count

    @staticmethod
    async def run_keyword_seed_discovery(
        db: AsyncSession,
        task: CollectionTask,
        *,
        run_at: datetime | None = None,
    ) -> KeywordSeedDiscoveryResult:
        if not task.product_id:
            raise ValueError("任务未绑定产品，无法执行")

        run_at = run_at or datetime.now(UTC)
        seeds = await ShoppingSeedDiscoveryService._discover_seeds(db, task)
        exec_result, seed_enriched_count, platform_failed_count, skipped_platform_count = (
            await ShoppingSeedDiscoveryService._process_seed_items(db, task, seeds, run_at=run_at)
        )
        return KeywordSeedDiscoveryResult(
            exec_result=exec_result,
            discovered_count=len(seeds),
            seed_enriched_count=seed_enriched_count,
            platform_failed_count=platform_failed_count,
            skipped_platform_count=skipped_platform_count,
        )

    @staticmethod
    async def run_collection_task(db: AsyncSession, task: CollectionTask) -> dict[str, int]:
        if not task.product_id:
            raise ValueError("任务未绑定产品，无法执行")
        if task.collection_mode != CollectionMode.LINK_SEED_DISCOVERY.value:
            raise ValueError("仅导购 seed 自动发现任务可通过该执行器运行")

        run_at = datetime.now(UTC)
        seeds = await ShoppingSeedDiscoveryService._discover_seeds(db, task)
        exec_result, seed_enriched_count, platform_failed_count, skipped_platform_count = (
            await ShoppingSeedDiscoveryService._process_seed_items(db, task, seeds, run_at=run_at)
        )
        discovered = len(seeds)
        inserted_total = exec_result.new_count + exec_result.updated_count
        resolved_count = (
            inserted_total
            + exec_result.pending_profile_count
            + exec_result.not_inserted_count
            + exec_result.filtered_out_count
        )

        if discovered > 0 and exec_result.import_failed > 0 and inserted_total == 0 and resolved_count == 0:
            final_status = CollectionTaskStatus.PARTIAL_FAILED
        elif inserted_total > 0:
            final_status = CollectionTaskStatus.COMPLETED_WITH_RESULTS
        elif resolved_count > 0 or exec_result.pending_profile_count > 0:
            final_status = CollectionTaskStatus.COMPLETED_NO_RESULTS
        elif discovered == 0:
            final_status = CollectionTaskStatus.COMPLETED_NO_RESULTS
        else:
            final_status = CollectionTaskStatus.FAILED

        task.status = final_status.value
        task.last_run_at = run_at
        task.last_error = None
        task.discovered_count = discovered
        task.deduped_count = discovered
        task.profile_fetched_count = exec_result.hydrated_profile_count
        task.profile_failed_count = exec_result.import_failed
        task.inserted_count = inserted_total
        task.result_count = inserted_total
        task.filtered_out_count = exec_result.filtered_out_count
        task.filtered_below_min_followers_count = exec_result.filtered_below_min
        task.filtered_excluded_keyword_count = exec_result.filtered_excluded
        task.current_stage = STAGE_COMPLETED

        checkpoint = dict(task.run_checkpoint or {})
        seed_platforms = [
            str(platform).strip().lower()
            for platform in (task.platforms or [])
            if str(platform).strip().lower() in {"ltk", "shopmy", "pinterest"}
        ]
        discovery_diag = build_seed_search_diagnostics(
            keywords=build_shopping_seed_search_keywords_for_task(task),
            seed_platforms=seed_platforms or ["ltk", "shopmy", "pinterest"],
            category=task.category,
            profiles_returned_count=discovered,
            seed_extracted_count=discovered,
        )
        existing_discovery_diag = checkpoint.get("shopping_seed_discovery")
        if isinstance(existing_discovery_diag, dict):
            merged_discovery_diag = {**discovery_diag, **existing_discovery_diag}
            existing_provider_state = existing_discovery_diag.get("provider_availability_state")
            new_provider_state = discovery_diag.get("provider_availability_state")
            if isinstance(new_provider_state, dict) or isinstance(existing_provider_state, dict):
                merged_discovery_diag["provider_availability_state"] = {
                    **(new_provider_state if isinstance(new_provider_state, dict) else {}),
                    **(existing_provider_state if isinstance(existing_provider_state, dict) else {}),
                }
        else:
            merged_discovery_diag = discovery_diag
        if discovered == 0:
            attempted_seed_queries = set()
            for key in ("completed_queries", "failed_queries"):
                values = checkpoint.get(key)
                if isinstance(values, list):
                    attempted_seed_queries.update(str(value) for value in values if str(value or "").strip())
            if attempted_seed_queries:
                merged_discovery_diag["provider_call_count"] = max(
                    int(merged_discovery_diag.get("provider_call_count") or 0),
                    len(attempted_seed_queries),
                )
                if "public_web" in (merged_discovery_diag.get("search_platforms") or []):
                    merged_discovery_diag["public_web_query_count"] = max(
                        int(merged_discovery_diag.get("public_web_query_count") or 0),
                        len(attempted_seed_queries),
                    )
        product_evidence_filtered_count = int(
            checkpoint.get("seed_product_evidence_filtered_count")
            or merged_discovery_diag.get("product_evidence_filtered_count")
            or 0
        )
        if product_evidence_filtered_count > 0 and discovered == 0:
            merged_discovery_diag["zero_seed_reason"] = "seed_found_but_no_product_evidence"
        elif discovered > 0 and merged_discovery_diag.get("zero_seed_reason") in {
            "seed_search_no_profiles_returned",
            "seed_search_no_seed_urls_extracted",
            "provider_failed_but_fallback_no_results",
            "pinterest_apify_timeout",
            "pinterest_apify_network_unreachable",
            "apify_memory_limit_exceeded",
            "public_web_no_results",
        }:
            merged_discovery_diag["zero_seed_reason"] = None
        elif discovered == 0 and merged_discovery_diag.get("zero_seed_reason") == "seed_search_no_profiles_returned":
            provider_reason = _zero_seed_reason_for_provider_state(merged_discovery_diag, checkpoint)
            if provider_reason:
                merged_discovery_diag["zero_seed_reason"] = provider_reason
            elif "public_web" in (merged_discovery_diag.get("search_platforms") or []):
                merged_discovery_diag["zero_seed_reason"] = "public_web_no_results"
        if (
            discovered > 0
            and seed_enriched_count == 0
            and exec_result.seed_social_profiles_found == 0
            and inserted_total == 0
            and not product_evidence_filtered_count
            and not merged_discovery_diag.get("zero_seed_reason")
        ):
            merged_discovery_diag["zero_seed_reason"] = "seed_found_but_social_enrichment_failed"
        checkpoint["link_seed_enrichment"] = {
            "attempted": exec_result.seed_enrichment_attempted,
            "social_profiles_found": exec_result.seed_social_profiles_found,
            "low_value_seed_count": exec_result.low_value_seed_count,
            "mode": CollectionMode.LINK_SEED_DISCOVERY.value,
            "concurrency": settings.link_seed_enrich_concurrency,
        }
        checkpoint["shopping_seed_discovery"] = merged_discovery_diag
        checkpoint.update(
            {
                "seed_discovered_count": discovered,
                "seed_enriched_count": seed_enriched_count,
                "social_profiles_found_count": exec_result.seed_social_profiles_found,
                "same_product_candidates_count": inserted_total
                + exec_result.not_inserted_count
                + exec_result.filtered_out_count,
                "filtered_by_product_match_count": product_evidence_filtered_count,
                "filtered_by_quality_count": exec_result.filtered_out_count + exec_result.not_inserted_count,
                "inserted_count": inserted_total,
                "platform_failed_count": platform_failed_count,
                "skipped_platform_count": skipped_platform_count,
            }
        )
        task.run_checkpoint = checkpoint

        enrich_note = ""
        if exec_result.seed_enrichment_attempted:
            enrich_note = (
                f"; 已尝试社媒补全 {exec_result.seed_enrichment_attempted} 条"
                f"（找到社媒主页 {exec_result.seed_social_profiles_found} 个）"
            )
        task.status_summary = (
            f"导购 seed 自动发现完成：发现 {discovered} 个 seed，新增 {exec_result.new_count}，"
            f"更新 {exec_result.updated_count}，未入库 {exec_result.not_inserted_count}，"
            f"过滤 {exec_result.filtered_out_count}{enrich_note}"
        )
        if discovered == 0 and merged_discovery_diag.get("zero_seed_reason") == "seed_search_provider_not_configured":
            task.status_summary = (
                "导购 seed 自动发现完成：发现 0 个 seed。"
                "未配置 seed 搜索来源，当前仅能解析已提供的 LTK/ShopMy/Pinterest 链接；"
                "已生成 Amazon 商品查询词，但未执行 provider 搜索"
            )
        if discovered == 0 and merged_discovery_diag.get("zero_seed_reason") == "shopmy_keyword_search_requires_authenticated_provider":
            task.status_summary = (
                "ShopMy keyword seed discovery completed: found 0 seeds. "
                "No authenticated ShopMy keyword search provider is configured; "
                "public web and ShopMy page search ran but did not return parseable ShopMy creator profiles. "
                "Try a more specific topic, brand, product keyword, or provide ShopMy seed links directly."
            )
        query_errors: list[str] = []
        for query, errors in (checkpoint.get("query_errors") or {}).items():
            if not isinstance(errors, list):
                continue
            for error in errors:
                query_errors.append(f"Seed search query {query}: {error}")
        all_errors = query_errors + exec_result.import_errors
        task.error_message = summarize_errors(
            all_errors,
            prefix="导购 seed 发现已完成，部分条目存在问题：" if exec_result.import_errors else "",
        )

        if query_errors and not task.error_message:
            task.error_message = summarize_errors(query_errors, prefix="Seed search issues: ")

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
        task.result_count = max(task.result_count or 0, inserted_total)
        await db.commit()
        await db.refresh(task)

        return {
            "new_count": exec_result.new_count,
            "updated_count": exec_result.updated_count,
            "skipped_count": exec_result.not_inserted_count,
            "filtered_count": exec_result.filtered_out_count,
            "total_count": inserted_total,
            "discovered_count": discovered,
            "inserted_count": inserted_total,
        }
