"""Multi-platform collection aggregation and summary helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import CollectionTaskStatus
from app.services.collection_funnel import CollectionFunnelStats, determine_task_status
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
    discovery_api_failed: bool = False
    has_api_warnings: bool = False
    instagram_pipeline_result: object | None = None


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
    errors = list(instagram_errors or [])
    platform_summaries: list[str] = []
    platform_api_counts: dict[str, int] = {}
    platform_failures: list[str] = []
    platform_successes: list[str] = []

    for result in platform_results:
        platform_api_counts[result.platform] = result.api_requests
        if result.skipped and result.skip_reason:
            platform_failures.append(f"{result.platform}: {result.skip_reason}")
            errors.append(f"[{result.platform}] {result.skip_reason}")
            continue
        if result.errors:
            for err in result.errors:
                errors.append(f"[{result.platform}] {err}")
        if result.fatal and not result.items:
            platform_failures.append(result.platform)
            platform_summaries.append(f"{result.platform}: failed (API {result.api_requests} calls)")
        elif result.items:
            platform_successes.append(result.platform)
            collected.extend(result.items)
            platform_profiles.extend(result.profiles or [])
            funnel.discovered_count += result.discovered_count
            funnel.deduped_count += result.deduped_count
            funnel.profile_fetched_count += result.profile_fetched_count
            funnel.profile_failed_count += result.profile_failed_count
            platform_summaries.append(
                f"{result.platform}: 发现 {result.discovered_count}，去重 {result.deduped_count}，"
                f"API {result.api_requests} 次"
            )
        elif result.errors:
            platform_summaries.append(f"{result.platform}: 无结果（API {result.api_requests} 次）")
        else:
            platform_summaries.append(f"{result.platform}: 无候选（API {result.api_requests} 次）")

    all_failed = bool(platform_results) and not platform_successes and not collected
    instagram_failed = bool(instagram_result is None and instagram_funnel is None)
    discovery_api_failed = instagram_failed and all_failed and bool(platform_failures)

    return MultiPlatformRunAggregate(
        funnel=funnel,
        collected_items=collected,
        platform_profiles=platform_profiles,
        candidate_rows=[],
        collection_errors=errors,
        platform_summaries=platform_summaries,
        platform_api_counts=platform_api_counts,
        platform_failures=platform_failures,
        platform_successes=platform_successes,
        discovery_api_failed=discovery_api_failed,
        has_api_warnings=bool(platform_failures and platform_successes),
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
    all_platforms_failed = (
        not has_any_result
        and aggregate.platform_failures
        and not aggregate.platform_successes
    )
    if all_platforms_failed or (instagram_fatal and not aggregate.platform_successes and not has_any_result):
        return CollectionTaskStatus.FAILED

    if has_any_result:
        if aggregate.platform_failures or aggregate.funnel.profile_failed_count > 0:
            return CollectionTaskStatus.PARTIAL_FAILED
        return CollectionTaskStatus.COMPLETED_WITH_RESULTS

    if aggregate.platform_failures or aggregate.funnel.profile_failed_count > 0:
        return CollectionTaskStatus.PARTIAL_FAILED

    if aggregate.funnel.discovered_count > 0:
        return CollectionTaskStatus.COMPLETED_NO_RESULTS

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
        parts.append("；".join(aggregate.platform_summaries))
    if aggregate.platform_api_counts:
        api_bits = [f"{p} {c} 次" for p, c in sorted(aggregate.platform_api_counts.items())]
        parts.append(f"API 调用：{', '.join(api_bits)}")

    if inserted_count > 0:
        parts.insert(
            0,
            f"多平台合格入库 {inserted_count} 个（已发现 {aggregate.funnel.discovered_count} 个候选，已过滤 {filtered_out} 个）",
        )
    elif status == CollectionTaskStatus.FAILED:
        parts.insert(0, "多平台采集全部失败")
    elif aggregate.platform_failures and aggregate.platform_successes:
        parts.insert(0, "部分平台失败，其余平台已继续")
    elif aggregate.platform_failures:
        parts.insert(0, "部分平台失败或无结果")
    else:
        parts.insert(0, "多平台任务完成，但未发现可入库候选")

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
            link_reason += (
                f"，其中 {missing_contact_or_landing_count} 个缺少有效联系方式或商业落地页"
            )
        reasons.append(link_reason)
    if overfetch_stop_reason:
        reasons.append(overfetch_stop_reason)
    elif aggregate.funnel.discovered_count == 0:
        reasons.append("平台无更多结果")

    reason_text = "、".join(reasons) if reasons else "过滤后合格数不足"
    return f"{base}。目标 {target_qualified_count} 条合格入库，实际 {inserted_count} 条；原因：{reason_text}"
