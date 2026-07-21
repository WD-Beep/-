# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：multi platform runner
"""Multi-platform collection aggregation and summary helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import CollectionTaskStatus
from app.services.collection_funnel import CollectionFunnelStats, determine_task_status
from app.services.collect_errors import (
    filter_fatal_discovery_errors,
    is_informational_empty_discovery_message,
)
from app.services.instagram_pipeline import PipelineRunStats
from app.services.platform_types import PlatformDiscoveryResult

_LINK_TYPE_LABELS = {
    "amazon_storefront": "Amazon storefront",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "facebook": "Facebook",
    "twitter": "X",
    "linkedin": "LinkedIn",
    "linktree": "Linktree",
    "shopmy": "ShopMy",
    "ltk": "LTK",
    "website": "独立站",
    "beacons": "Beacons",
    "stan_store": "Stan Store",
    "carrd": "Carrd",
}


def funnel_from_pipeline_stats(stats: object | None) -> CollectionFunnelStats:
    if stats is None:
        return CollectionFunnelStats()
    if isinstance(stats, CollectionFunnelStats):
        return stats
    return CollectionFunnelStats(
        discovered_count=getattr(stats, "discovered_count", 0),
        deduped_count=getattr(stats, "deduped_count", 0),
        profile_fetched_count=getattr(stats, "profile_fetched_count", 0),
        profile_failed_count=getattr(stats, "profile_failed_count", 0),
        filtered_out_count=getattr(stats, "filtered_out_count", 0),
        inserted_count=getattr(stats, "inserted_count", 0),
        preference_mismatch_count=getattr(stats, "preference_mismatch_count", 0),
        hashtag_count=getattr(stats, "hashtag_count", 0),
        post_count=getattr(stats, "post_count", 0),
        comment_author_count=getattr(stats, "comment_author_count", 0),
        filtered_below_min_followers_count=getattr(stats, "filtered_below_min_followers_count", 0),
        filtered_excluded_keyword_count=getattr(stats, "filtered_excluded_keyword_count", 0),
        target_qualified_count=getattr(stats, "target_qualified_count", 0),
        overfetch_stop_reason=getattr(stats, "overfetch_stop_reason", None),
        external_link_count=getattr(stats, "external_link_count", 0),
        commercial_link_count=getattr(stats, "commercial_link_count", 0),
        social_only_link_count=getattr(stats, "social_only_link_count", 0),
        missing_contact_or_landing_count=getattr(stats, "missing_contact_or_landing_count", 0),
        external_link_types=getattr(stats, "external_link_types", None),
    )


@dataclass
class MultiPlatformRunAggregate:
    funnel: CollectionFunnelStats
    collected_items: list = field(default_factory=list)
    platform_profiles: list = field(default_factory=list)
    candidate_rows: list[dict] = field(default_factory=list)
    collection_errors: list[str] = field(default_factory=list)
    platform_summaries: list[str] = field(default_factory=list)
    platform_api_counts: dict[str, int] = field(default_factory=dict)
    platform_failures: list[str] = field(default_factory=list)
    platform_successes: list[str] = field(default_factory=list)
    platform_completed: list[str] = field(default_factory=list)
    provider_availability_state: dict[str, dict] = field(default_factory=dict)
    discovery_api_failed: bool = False
    has_api_warnings: bool = False
    instagram_pipeline_result: object | None = None


def _strip_platform_prefix(message: str) -> str:
    text = (message or "").strip()
    if text.startswith("[") and "]" in text:
        return text.split("]", 1)[1].strip()
    return text


def _query_error_count(errors: list[str]) -> int:
    return sum(1 for err in errors if str(err).strip().lower().startswith("query "))


def _last_error(errors: list[str]) -> str:
    return str(errors[-1]).strip() if errors else ""


def _error_excerpt(errors: list[str]) -> str:
    values = [str(err).strip() for err in errors if str(err).strip()]
    return "; ".join(values[:2])


def _platform_empty_label(platform: str, api_requests: int) -> str:
    return f"{platform}: no same-product results (API {api_requests} calls)"


def _platform_empty_completion(result: PlatformDiscoveryResult) -> bool:
    """API executed normally but returned no candidates or same-product matches."""
    if result.skipped or result.items or result.candidate_rows:
        return False
    fatal_errors = filter_fatal_discovery_errors(result.errors or [])
    if fatal_errors:
        return False
    if result.api_requests > 0:
        return True
    return bool(result.errors) and all(
        is_informational_empty_discovery_message(err) for err in result.errors
    )


def _platform_provider_skip(result: PlatformDiscoveryResult) -> bool:
    """Provider never ran or was explicitly skipped — not an empty search result."""
    if result.skipped:
        return True
    if result.api_requests > 0:
        return False
    if _platform_empty_completion(result):
        return False
    return bool(result.skip_reason or result.errors)


def _platform_has_fatal_failure(result: PlatformDiscoveryResult) -> bool:
    if result.skipped or result.items or result.candidate_rows:
        return False
    if _platform_empty_completion(result):
        return False
    fatal_errors = filter_fatal_discovery_errors(result.errors or [])
    if not fatal_errors:
        return False
    return result.fatal or result.api_requests <= 0


def build_multi_platform_error_prefix(
    aggregate: MultiPlatformRunAggregate,
    *,
    discovery_api_failed: bool,
    instagram_only: bool,
) -> str:
    if not aggregate.collection_errors:
        return ""
    if aggregate.platform_completed and not aggregate.platform_successes and not aggregate.platform_failures:
        return ""
    if instagram_only:
        if discovery_api_failed:
            return "Instagram 采集 API 失败："
        return "采集已完成，部分条目存在问题："
    if discovery_api_failed and not aggregate.platform_completed:
        return "多平台采集 API 失败："
    if aggregate.platform_failures:
        return "多平台采集部分平台异常："
    return "采集已完成，部分条目存在问题："


def merge_platform_results(
    *,
    instagram_result: object | None,
    instagram_funnel: CollectionFunnelStats | PipelineRunStats | None,
    instagram_errors: list[str],
    instagram_candidate_rows: list[dict],
    instagram_collected: list,
    platform_results: list[PlatformDiscoveryResult],
) -> MultiPlatformRunAggregate:
    funnel = funnel_from_pipeline_stats(instagram_funnel)
    collected = list(instagram_collected or [])
    platform_profiles: list = []
    all_candidate_rows: list[dict] = list(instagram_candidate_rows or [])
    errors = list(instagram_errors or [])
    platform_summaries: list[str] = []
    platform_api_counts: dict[str, int] = {}
    platform_failures: list[str] = []
    platform_successes: list[str] = []
    platform_completed: list[str] = []
    provider_availability_state: dict[str, dict] = {}

    instagram_details: list[str] = []
    for err in instagram_errors or []:
        detail = _strip_platform_prefix(err)
        if detail:
            instagram_details.append(detail)
    for detail in instagram_details[:2]:
        platform_summaries.append(f"instagram: {detail}")
    if len(instagram_details) > 2:
        platform_summaries.append(f"instagram: 另有 {len(instagram_details) - 2} 条详情见错误详情")

    for result in platform_results:
        platform_api_counts[result.platform] = result.api_requests
        if result.provider_availability_state:
            provider_availability_state.update(result.provider_availability_state)
        skip_reason = result.skip_reason
        if _platform_provider_skip(result):
            reason = skip_reason or _last_error(result.errors) or "platform skipped"
            platform_failures.append(f"{result.platform}: {reason}")
            errors.append(f"[{result.platform}] {reason}")
            platform_summaries.append(
                f"{result.platform}: skipped (API {result.api_requests} calls): {reason}"
            )
            continue

        for err in result.errors or []:
            errors.append(f"[{result.platform}] {err}")

        # Always merge candidate_rows from each platform result
        if result.candidate_rows:
            all_candidate_rows.extend(result.candidate_rows)
            # Count filtered_out rows into funnel
            filtered_out_from_rows = sum(
                1 for row in result.candidate_rows
                if row.get("status") == "filtered_out"
            )
            funnel.filtered_out_count += filtered_out_from_rows

        # Always merge funnel counts when they have values, regardless of items
        has_pre_filter_candidates = (
            result.discovered_count > 0
            or result.deduped_count > 0
            or result.profile_fetched_count > 0
        )
        if has_pre_filter_candidates:
            funnel.discovered_count += result.discovered_count
            funnel.deduped_count += result.deduped_count
            funnel.profile_fetched_count += result.profile_fetched_count
            funnel.profile_failed_count += result.profile_failed_count

        # Determine if this is a fatal failure or a completed platform
        has_same_product_filtered = bool(result.candidate_rows) and not result.items
        if _platform_empty_completion(result):
            platform_completed.append(result.platform)
            for err in result.errors or []:
                errors.append(f"[{result.platform}] {err}")
            detail = _last_error(result.errors or [])
            platform_summaries.append(
                f"{result.platform}: {detail or _platform_empty_label(result.platform, result.api_requests)}"
            )
            continue

        if _platform_has_fatal_failure(result):
            detail = _error_excerpt(result.errors) or _last_error(result.errors)
            query_count = _query_error_count(result.errors)
            suffix = f": {detail}" if detail else ""
            query_suffix = f"; queries {query_count}" if query_count else ""
            platform_failures.append(f"{result.platform}: {detail or 'failed'}")
            platform_summaries.append(
                f"{result.platform}: failed (API {result.api_requests} calls){suffix}{query_suffix}"
            )
            continue

        platform_completed.append(result.platform)

        if result.items:
            platform_successes.append(result.platform)
            collected.extend(result.items)
            platform_profiles.extend(result.profiles or [])
            # Only add funnel counts here if not already added above
            if not has_pre_filter_candidates:
                funnel.discovered_count += result.discovered_count
                funnel.deduped_count += result.deduped_count
                funnel.profile_fetched_count += result.profile_fetched_count
                funnel.profile_failed_count += result.profile_failed_count
            platform_summaries.append(
                f"{result.platform}: discovered {result.discovered_count}, deduped {result.deduped_count}, "
                f"API {result.api_requests} calls"
            )
        elif has_same_product_filtered:
            # API returned candidates but same-product filter rejected all
            filtered_count = len(result.candidate_rows)
            platform_summaries.append(
                f"{result.platform}: 同款过滤后 0/{filtered_count} "
                f"(discovered {result.discovered_count}, API {result.api_requests} calls)"
            )
        elif result.errors:
            detail = _last_error(result.errors)
            query_count = _query_error_count(result.errors)
            query_suffix = f"; queries {query_count}" if query_count else ""
            platform_summaries.append(
                f"{result.platform}: no same-product results with warnings "
                f"(API {result.api_requests} calls): {detail}{query_suffix}"
            )
        else:
            platform_summaries.append(_platform_empty_label(result.platform, result.api_requests))

    all_failed = bool(platform_results) and not platform_successes and not collected
    instagram_requested = (
        instagram_result is not None
        or instagram_funnel is not None
        or bool(instagram_errors)
    )
    instagram_failed = instagram_requested and instagram_result is None and instagram_funnel is None
    discovery_api_failed = instagram_failed and all_failed and bool(platform_failures) and not platform_completed

    return MultiPlatformRunAggregate(
        funnel=funnel,
        collected_items=collected,
        platform_profiles=platform_profiles,
        candidate_rows=all_candidate_rows,
        collection_errors=errors,
        platform_summaries=platform_summaries,
        platform_api_counts=platform_api_counts,
        platform_failures=platform_failures,
        platform_successes=platform_successes,
        platform_completed=platform_completed,
        provider_availability_state=provider_availability_state,
        discovery_api_failed=discovery_api_failed,
        has_api_warnings=bool(platform_failures and (platform_successes or platform_completed)),
        instagram_pipeline_result=instagram_result,
    )


def determine_multi_platform_status(
    aggregate: MultiPlatformRunAggregate,
    *,
    inserted_count: int,
    instagram_only: bool,
    instagram_fatal: bool,
) -> CollectionTaskStatus:
    if instagram_only:
        return determine_task_status(
            inserted_count=inserted_count,
            profile_failed_count=aggregate.funnel.profile_failed_count,
            discovered_count=aggregate.funnel.discovered_count,
            fatal_error=instagram_fatal,
            has_api_warnings=aggregate.has_api_warnings,
        )

    has_any_result = inserted_count > 0
    all_platforms_empty = (
        not has_any_result
        and aggregate.platform_completed
        and not aggregate.platform_successes
        and not aggregate.platform_failures
    )
    if all_platforms_empty:
        return CollectionTaskStatus.COMPLETED_NO_RESULTS

    all_platforms_failed = (
        not has_any_result
        and aggregate.platform_failures
        and not aggregate.platform_successes
        and not aggregate.platform_completed
    )
    if all_platforms_failed or (instagram_fatal and not aggregate.platform_successes and not aggregate.platform_completed and not has_any_result):
        return CollectionTaskStatus.FAILED

    if has_any_result:
        if aggregate.platform_failures or aggregate.funnel.profile_failed_count > 0:
            return CollectionTaskStatus.PARTIAL_FAILED
        return CollectionTaskStatus.COMPLETED_WITH_RESULTS

    if aggregate.platform_failures and (aggregate.platform_successes or aggregate.platform_completed):
        return CollectionTaskStatus.PARTIAL_FAILED

    if aggregate.platform_failures or aggregate.funnel.profile_failed_count > 0:
        return CollectionTaskStatus.PARTIAL_FAILED

    return CollectionTaskStatus.COMPLETED_NO_RESULTS


def build_multi_platform_summary(
    aggregate: MultiPlatformRunAggregate,
    *,
    status: CollectionTaskStatus,
    inserted_count: int,
    target_qualified_count: int = 0,
    overfetch_stop_reason: str | None = None,
    filtered_below_min: int = 0,
    filtered_excluded: int = 0,
    filtered_out: int = 0,
) -> str:
    parts: list[str] = []
    if aggregate.platform_summaries:
        parts.append("; ".join(aggregate.platform_summaries))
    if aggregate.platform_api_counts:
        api_bits = [f"{p} {c} calls" for p, c in sorted(aggregate.platform_api_counts.items())]
        parts.append(f"API calls: {', '.join(api_bits)}")

    if inserted_count > 0:
        parts.insert(
            0,
            f"多平台合格入库 {inserted_count} 个（已发现 {aggregate.funnel.discovered_count} 个候选，已过滤 {filtered_out} 个）",
        )
    elif status == CollectionTaskStatus.FAILED:
        parts.insert(0, "多平台采集全部失败")
    elif aggregate.platform_failures and (aggregate.platform_successes or aggregate.platform_completed):
        parts.insert(0, "部分平台失败，其余平台已完成")
    elif aggregate.platform_failures:
        parts.insert(0, "部分平台失败或未执行")
    elif filtered_out > 0 or aggregate.funnel.filtered_out_count > 0:
        parts.insert(0, "发现候选但未达入库条件")
    else:
        parts.insert(0, "多平台任务完成，未发现同款产品合作红人")

    base = "。".join(part for part in parts if part)
    if target_qualified_count <= 0:
        return base
    if inserted_count >= target_qualified_count:
        return f"{base}（目标 {target_qualified_count} 条合格入库，已达标）"

    reasons: list[str] = []
    if filtered_below_min:
        reasons.append("低粉/粉丝未知")
    if filtered_excluded:
        reasons.append("排除词")
    other = filtered_out - filtered_below_min - filtered_excluded
    if other > 0:
        reasons.append("无效主页、重复或商业信号不足")
    external_link_count = getattr(aggregate.funnel, "external_link_count", 0)
    if external_link_count > 0:
        labels = ", ".join(
            _LINK_TYPE_LABELS.get(link_type, link_type)
            for link_type in (getattr(aggregate.funnel, "external_link_types", None) or [])[:6]
        )
        link_reason = f"发现主页外链 {external_link_count} 个"
        if labels:
            link_reason += f"（{labels}）"
        commercial_link_count = getattr(aggregate.funnel, "commercial_link_count", 0)
        if commercial_link_count > 0:
            link_reason += f"，商业外链 {commercial_link_count} 个"
        social_only_link_count = getattr(aggregate.funnel, "social_only_link_count", 0)
        if social_only_link_count > 0:
            link_reason += f"，{social_only_link_count} 个仅有社媒链接"
        missing_contact_or_landing_count = getattr(aggregate.funnel, "missing_contact_or_landing_count", 0)
        if missing_contact_or_landing_count > 0:
            link_reason += f"，其中 {missing_contact_or_landing_count} 个缺少有效联系方式或商业落地页"
        reasons.append(link_reason)
    if overfetch_stop_reason:
        if "平台无更多结果" in overfetch_stop_reason or "no more" in overfetch_stop_reason.lower():
            reasons.append("未发现同款产品合作红人")
        else:
            reasons.append(overfetch_stop_reason)
    elif aggregate.platform_failures and aggregate.platform_completed:
        reasons.append("部分平台 API 失败，其余平台正常但未发现同款产品")
    elif filtered_out > 0 or aggregate.funnel.filtered_out_count > 0:
        reasons.append("发现候选但未达入库条件")
    elif aggregate.funnel.discovered_count == 0:
        reasons.append("未发现同款产品合作红人")

    reason_text = "、".join(reasons) if reasons else "过滤后合格数不足"
    return f"{base}。目标 {target_qualified_count} 条合格入库，实际 {inserted_count} 条；原因：{reason_text}"
