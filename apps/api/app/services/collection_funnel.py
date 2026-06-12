"""Collection funnel stats and human-readable task summaries."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import CollectionTaskStatus


@dataclass
class CollectionFunnelStats:
    discovered_count: int = 0
    deduped_count: int = 0
    profile_fetched_count: int = 0
    profile_failed_count: int = 0
    filtered_out_count: int = 0
    inserted_count: int = 0
    preference_mismatch_count: int = 0
    hashtag_count: int = 0
    post_count: int = 0
    comment_author_count: int = 0
    filtered_below_min_followers_count: int = 0
    filtered_excluded_keyword_count: int = 0
    target_qualified_count: int = 0
    overfetch_stop_reason: str | None = None
    external_link_count: int = 0
    commercial_link_count: int = 0
    social_only_link_count: int = 0
    missing_contact_or_landing_count: int = 0
    external_link_types: list[str] | None = None


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


def determine_task_status(
    *,
    inserted_count: int,
    profile_failed_count: int,
    discovered_count: int,
    fatal_error: bool,
    has_api_warnings: bool = False,
) -> CollectionTaskStatus:
    if fatal_error:
        return CollectionTaskStatus.FAILED
    if inserted_count > 0:
        if profile_failed_count > 0 or has_api_warnings:
            return CollectionTaskStatus.PARTIAL_FAILED
        return CollectionTaskStatus.COMPLETED_WITH_RESULTS
    if profile_failed_count > 0 or has_api_warnings:
        return CollectionTaskStatus.PARTIAL_FAILED
    if discovered_count > 0:
        return CollectionTaskStatus.COMPLETED_NO_RESULTS
    return CollectionTaskStatus.COMPLETED_NO_RESULTS


def _link_signal_summary(stats: CollectionFunnelStats) -> str | None:
    if stats.external_link_count <= 0:
        return None

    labels: list[str] = []
    for link_type in stats.external_link_types or []:
        label = _LINK_TYPE_LABELS.get(link_type, link_type)
        if label not in labels:
            labels.append(label)

    parts = [f"已发现主页外链 {stats.external_link_count} 个"]
    if labels:
        parts.append(f"类型包括 {', '.join(labels[:6])}")
    if stats.commercial_link_count > 0:
        parts.append(f"其中商业外链 {stats.commercial_link_count} 个")
    if stats.social_only_link_count > 0:
        parts.append(f"{stats.social_only_link_count} 个仅有社媒链接")
    if stats.missing_contact_or_landing_count > 0:
        parts.append(f"{stats.missing_contact_or_landing_count} 个缺少有效联系方式或商业落地页")
    return "；".join(parts)


def build_status_summary(
    stats: CollectionFunnelStats,
    *,
    status: CollectionTaskStatus,
    collection_mode: str | None = None,
    competitor_meta: object | None = None,
) -> str:
    s = stats
    mode = (collection_mode or "").lower()
    if mode == "comment_authors":
        mode = "urls"

    if mode == "competitor_product" and competitor_meta is not None:
        info = getattr(competitor_meta, "product_info", None)
        asin = getattr(info, "asin", None) if info else None
        brand = getattr(info, "brand", None) if info else None
        keywords = getattr(info, "core_keywords", None) if info else None
        posts_scanned = getattr(competitor_meta, "posts_scanned", s.post_count) or 0
        authors_matched = getattr(competitor_meta, "authors_matched", s.discovered_count) or 0
        keyword_text = "、".join(keywords[:5]) if keywords else "未解析到关键词"
        parse_bits = []
        if asin:
            parse_bits.append(f"ASIN {asin}")
        if brand:
            parse_bits.append(f"品牌 {brand}")
        parse_bits.append(f"关键词 {keyword_text}")
        parse_line = "，".join(parse_bits)
        if s.inserted_count > 0:
            return (
                f"竞品商品发现：{parse_line}。扫描 {posts_scanned} 条帖子，"
                f"caption 命中 {authors_matched} 个疑似推广账号，入库 {s.inserted_count} 个"
            )
        if authors_matched > 0:
            return (
                f"竞品商品发现：{parse_line}。扫描 {posts_scanned} 条帖子，"
                f"caption 命中 {authors_matched} 个疑似推广账号，但未满足入库条件"
            )
        if posts_scanned > 0:
            return f"竞品商品发现：{parse_line}。扫描 {posts_scanned} 条帖子，未找到命中的疑似推广账号"
        return f"竞品商品发现：{parse_line}。未发现相关 Instagram 帖子"

    if status == CollectionTaskStatus.FAILED:
        return "采集流程失败：平台 API 未返回可用候选，请查看错误详情"

    if s.inserted_count > 0:
        base = (
            f"发现 {s.discovered_count} 个候选，去重后 {s.deduped_count} 个，"
            f"补采成功 {s.profile_fetched_count} 个，已过滤 {s.filtered_out_count} 个，"
            f"合格入库 {s.inserted_count} 个"
        )
        if s.filtered_out_count:
            parts = []
            if s.filtered_below_min_followers_count:
                parts.append(f"{s.filtered_below_min_followers_count} 个因粉丝低于门槛")
            if s.filtered_excluded_keyword_count:
                parts.append(f"{s.filtered_excluded_keyword_count} 个命中排除词")
            other = s.filtered_out_count - s.filtered_below_min_followers_count - s.filtered_excluded_keyword_count
            if other > 0:
                parts.append(f"{other} 个因主页无效或商业信号不足")
            base += f"；{'、'.join(parts)}被硬过滤" if parts else f"；{s.filtered_out_count} 个被硬过滤"
        if s.profile_failed_count:
            base += f"；{s.profile_failed_count} 个主页补采失败"
        if s.comment_author_count:
            base += f"；其中 {s.comment_author_count} 个来自评论区"
        if mode in ("discovery", "keyword", "mixed") and (s.hashtag_count or s.post_count):
            base += f"；来源包含 {s.hashtag_count} 个 hashtag、{s.post_count} 条帖子/Reels"
        if status == CollectionTaskStatus.PARTIAL_FAILED:
            base += "；部分 API 步骤失败，详见错误信息"
        if s.preference_mismatch_count:
            base += f"；其中 {s.preference_mismatch_count} 个未完全满足偏好条件，建议在红人库二次筛选"
        return append_target_qualified_summary(base, s)

    if s.discovered_count == 0:
        return "任务完成，但未发现任何候选账号（关键词 / hashtag / 链接 / 评论均未命中）"

    if s.profile_failed_count > 0 and s.filtered_out_count == 0:
        return (
            f"发现 {s.discovered_count} 个候选（去重 {s.deduped_count}），"
            f"{s.profile_failed_count} 个主页补采失败，未能入库"
        )

    if s.filtered_out_count > 0:
        filter_bits = []
        if s.filtered_below_min_followers_count:
            filter_bits.append(f"{s.filtered_below_min_followers_count} 个因粉丝低于门槛")
        if s.filtered_excluded_keyword_count:
            filter_bits.append(f"{s.filtered_excluded_keyword_count} 个命中排除词")
        other = s.filtered_out_count - s.filtered_below_min_followers_count - s.filtered_excluded_keyword_count
        if other > 0:
            filter_bits.append(f"{other} 个因主页无效、重复或商业信号不足")
        link_text = _link_signal_summary(s)
        if link_text:
            filter_bits.append(link_text)
        filter_text = "、".join(filter_bits) if filter_bits else f"{s.filtered_out_count} 个被硬过滤"
        return append_target_qualified_summary(
            (
                f"发现 {s.discovered_count} 个候选，去重后 {s.deduped_count} 个；"
                f"补采成功 {s.profile_fetched_count} 个，失败 {s.profile_failed_count} 个；"
                f"已过滤 {s.filtered_out_count} 个，合格入库 {s.inserted_count} 个（{filter_text}）"
                + (f"；{s.comment_author_count} 个来自评论区" if s.comment_author_count else "")
            ),
            s,
        )

    if status == CollectionTaskStatus.PARTIAL_FAILED:
        return append_target_qualified_summary(
            f"发现 {s.discovered_count} 个候选，但部分 API 步骤失败，请查看错误信息",
            s,
        )

    base = "任务完成，但未发现可入库的有效红人（如粉丝门槛、联系方式或商业落地页不满足）"
    link_text = _link_signal_summary(s)
    if link_text:
        base = f"{base}；{link_text}"
    return append_target_qualified_summary(base, s)


def _shortfall_reasons(stats: CollectionFunnelStats) -> list[str]:
    reasons: list[str] = []
    if stats.filtered_below_min_followers_count:
        reasons.append("低粉/粉丝未知")
    if stats.filtered_excluded_keyword_count:
        reasons.append("排除词")
    other = stats.filtered_out_count - stats.filtered_below_min_followers_count - stats.filtered_excluded_keyword_count
    if other > 0:
        reasons.append("无效主页或商业信号不足")
    if stats.missing_contact_or_landing_count:
        reasons.append("缺少有效联系方式或商业落地页")
    if stats.overfetch_stop_reason:
        reasons.append(stats.overfetch_stop_reason)
    elif stats.discovered_count == 0:
        reasons.append("平台无更多结果")
    return reasons


def append_target_qualified_summary(base: str, stats: CollectionFunnelStats) -> str:
    target = stats.target_qualified_count
    if target <= 0:
        return base
    if stats.inserted_count >= target:
        return f"{base}（目标 {target} 条合格入库，已达标）"
    reasons = _shortfall_reasons(stats)
    reason_text = "、".join(reasons) if reasons else "过滤后合格数不足"
    return f"{base}。目标 {target} 条合格入库，实际 {stats.inserted_count} 条；原因：{reason_text}"


def _provider_label(provider: str | None, *, platform: str | None = None) -> str:
    normalized_platform = (platform or "").strip().lower()
    if not provider:
        if normalized_platform == "facebook":
            return "Apify Facebook Scraper"
        if normalized_platform == "tiktok":
            return "Apify TikTok Scraper"
        return "YouTube"
    normalized = provider.strip().lower()
    if normalized == "apify":
        if normalized_platform == "facebook":
            return "Apify Facebook Scraper"
        if normalized_platform == "tiktok":
            return "Apify TikTok Scraper"
        return "Apify YouTube Scraper"
    if normalized == "api_direct":
        if normalized_platform == "facebook":
            return "API Direct Facebook"
        if normalized_platform == "tiktok":
            return "API Direct TikTok"
        return "API Direct YouTube"
    return provider


def _keyword_progress_note(
    *,
    current_keyword: str | None,
    provider: str | None,
    keywords_completed: int | None,
    keywords_total: int | None,
    platform: str | None = None,
) -> str | None:
    provider_text = _provider_label(provider, platform=platform)
    if current_keyword:
        if keywords_total and keywords_completed is not None:
            return f"正在通过 {provider_text} 搜索关键词「{current_keyword}」（{keywords_completed}/{keywords_total}）"
        return f"正在通过 {provider_text} 搜索关键词「{current_keyword}」"
    if keywords_total and keywords_completed is not None and keywords_total > 0:
        return f"正在通过 {provider_text} 搜索关键词（{keywords_completed}/{keywords_total}）"
    return None


def _hydration_progress_note(
    *,
    profiles_hydrating_total: int | None,
    profiles_hydrating_completed: int | None,
) -> str | None:
    if not profiles_hydrating_total or profiles_hydrating_total <= 0:
        return None
    completed = profiles_hydrating_completed or 0
    return f"正在补采主页（{completed}/{profiles_hydrating_total}）"


def build_running_discovery_summary(
    *,
    phase: str,
    target: int,
    discovered: int,
    deduped: int,
    profile_fetched: int,
    filtered_out: int = 0,
    inserted: int = 0,
    rate_limited: bool = False,
    slow_api: bool = False,
    current_keyword: str | None = None,
    provider: str | None = None,
    keywords_completed: int | None = None,
    keywords_total: int | None = None,
    profiles_hydrating_total: int | None = None,
    profiles_hydrating_completed: int | None = None,
    partial_skip_note: str | None = None,
    platform: str | None = None,
) -> str:
    phase_labels = {
        "discovery": "发现候选",
        "hydration": "主页补采",
        "persist": "过滤入库",
        "ai_processing": "AI 评分",
    }
    phase_label = phase_labels.get(phase, phase)
    keyword_note = _keyword_progress_note(
        current_keyword=current_keyword,
        provider=provider,
        keywords_completed=keywords_completed,
        keywords_total=keywords_total,
        platform=platform,
    )
    hydration_note = _hydration_progress_note(
        profiles_hydrating_total=profiles_hydrating_total,
        profiles_hydrating_completed=profiles_hydrating_completed,
    )
    if rate_limited:
        prefix = "平台接口限流，系统正在降速重试；"
    elif slow_api:
        prefix = f"{phase_label}中（接口响应较慢）；"
    else:
        prefix = f"{phase_label}中；"
    if partial_skip_note:
        prefix = f"{prefix}部分请求已跳过并继续处理；"

    body = (
        f"已发现 {discovered} 个候选，去重 {deduped} 个，"
        f"已补采主页 {profile_fetched} 个，已过滤 {filtered_out} 个，"
        f"合格入库 {inserted} / 目标 {target}"
    )

    if discovered == 0 and deduped == 0 and profile_fetched == 0 and inserted == 0:
        if rate_limited:
            hint = "可能原因：平台限流，系统正在降速重试"
        elif phase == "discovery":
            if slow_api:
                hint = "可能原因：Apify/API 响应较慢或暂无结果，请稍候或检查 API 配置与关键词"
            else:
                hint = "可能原因：关键词搜索/API 调用中暂时无结果"
        elif phase == "hydration":
            hint = "可能原因：正在补采频道 About / 主页，请稍候"
        else:
            hint = "可能原因：处理中，请稍候"
        notes = [note for note in (keyword_note, hydration_note) if note]
        if notes:
            return f"{prefix}{body}。{'。'.join(notes)}。{hint}"
        return f"{prefix}{body}。{hint}"

    if discovered > 0 and inserted == 0 and filtered_out > 0:
        return f"{prefix}{body}。部分账号已被过滤（粉丝门槛 / 排除词 / 主页无效等）"

    notes = [note for note in (keyword_note, hydration_note) if note]
    if notes:
        return f"{prefix}{body}。{'。'.join(notes)}"
    return f"{prefix}{body}"
