"""统一 Instagram 发现：关键词/链接/混合 + 可选评论区增强。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.models.collection_task import CollectionTask
from app.services.apify_instagram import PostAuthorCandidate
from app.services.task_run_progress import RunCheckpoint
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.instagram_comment_discovery import (
    classify_instagram_input_url,
    resolve_target_post_urls,
)
from app.services.instagram_provider import (
    InstagramProviderError,
    discover_comment_authors_from_post_urls,
    discover_post_authors_from_post_urls,
)
from app.services.keyword_discovery import (
    KeywordDiscoveryMeta,
    KeywordDiscoveryResult,
    discover_candidates_from_keywords,
)
from app.services.apify_instagram import (
    _normalize_profile_url,
    _username_from_url,
)
from app.services.instagram_provider import PROVIDER_API_DIRECT, PROVIDER_APIFY, active_provider_name
from app.services.discovery_accumulator import DiscoveryAccumulator

logger = logging.getLogger(__name__)

USERNAME_ONLY_RE = re.compile(r"^[a-zA-Z0-9._]{1,30}$")


@dataclass
class UnifiedDiscoveryResult:
    """candidates 与 deduped_candidates 相同，保留兼容；raw_candidates 含发现阶段全部条目（含重复）。"""
    candidates: list[PostAuthorCandidate] = field(default_factory=list)
    raw_candidates: list[PostAuthorCandidate] = field(default_factory=list)
    deduped_candidates: list[PostAuthorCandidate] = field(default_factory=list)
    discovery_duplicates: list[PostAuthorCandidate] = field(default_factory=list)
    duplicate_count: int = 0
    errors: list[str] = field(default_factory=list)
    meta: KeywordDiscoveryMeta | None = None
    competitor_meta: object | None = None
    discovery_api_failed: bool = False
    hashtag_api_all_failed: bool = False
    hashtag_count: int = 0
    post_count: int = 0
    comment_author_count: int = 0


def normalize_collection_mode(mode: str | None) -> str:
    """comment_authors 旧模式并入链接采集。"""
    value = (mode or "keyword").lower()
    if value == "comment_authors":
        return "urls"
    return value


def is_comment_discovery_enabled(task: CollectionTask) -> bool:
    mode = normalize_collection_mode(getattr(task, "collection_mode", None))
    if mode == "competitor_product":
        return False
    enabled = getattr(task, "comment_discovery_enabled", None)
    if enabled is None:
        return True
    return bool(enabled)


def _candidate_from_profile_url(url: str) -> PostAuthorCandidate | None:
    username = _username_from_url(url)
    if not username:
        if USERNAME_ONLY_RE.match(url.strip().lstrip("@")):
            username = url.strip().lstrip("@")
        else:
            return None
    return PostAuthorCandidate(
        username=username,
        profile_url=_normalize_profile_url(username),
        source_discovery_type="url_profile",
    )


def _append_post_url(post_urls: list[str], seen: set[str], url: str) -> None:
    from app.services.instagram_comment_discovery import _normalize_post_url

    normalized = _normalize_post_url(url)
    key = normalized.lower()
    if key not in seen:
        seen.add(key)
        post_urls.append(normalized)


async def discover_candidates_from_input_urls(
    task: CollectionTask,
    *,
    limit: int,
    posts_per_profile: int = 5,
) -> tuple[list[PostAuthorCandidate], list[str], list[str], int]:
    """链接采集：识别主页/帖子/Reel/用户名，收集候选与待扫评论的帖子 URL（不去重）。"""
    found: list[PostAuthorCandidate] = []
    errors: list[str] = []
    post_urls: list[str] = []
    seen_posts: set[str] = set()

    for raw in task.input_urls or []:
        text = (raw or "").strip()
        if not text:
            continue

        if "instagram.com" not in text.lower():
            if USERNAME_ONLY_RE.match(text.lstrip("@")):
                candidate = _candidate_from_profile_url(text)
                if candidate:
                    found.append(candidate)
                continue
            errors.append(f"无法识别的输入: {text}")
            continue

        kind = classify_instagram_input_url(text)
        if kind == "post":
            _append_post_url(post_urls, seen_posts, text)
            continue

        if kind == "profile":
            candidate = _candidate_from_profile_url(text)
            if candidate:
                found.append(candidate)
            resolved, resolve_errors = await resolve_target_post_urls(
                [text],
                posts_per_profile=posts_per_profile,
            )
            errors.extend(resolve_errors)
            for post in resolved:
                _append_post_url(post_urls, seen_posts, post)
            continue

        errors.append(f"无法识别的 Instagram 链接: {text}")

    post_scrape_count = 0
    if post_urls:
        direct_posts = list(dict.fromkeys(post_urls))[: max(8, min(20, len(post_urls)))]
        try:
            post_discovery = await discover_post_authors_from_post_urls(direct_posts, limit=limit)
            errors.extend(post_discovery.errors)
            post_scrape_count = post_discovery.post_count
            found.extend(post_discovery.candidates)
        except InstagramProviderError as exc:
            errors.append(f"帖子作者发现: {exc}")

    return found[: limit * 2], errors, post_urls, post_scrape_count


async def enrich_with_comment_discovery(
    acc: DiscoveryAccumulator,
    post_urls: list[str],
    *,
    limit: int,
    errors: list[str],
) -> int:
    """评论区发现：失败仅记入 errors，不抛异常。"""
    from app.core.config import settings
    from app.services.instagram_provider import PROVIDER_APIFY, active_provider_name

    clean = list(dict.fromkeys(post_urls))[: max(8, min(20, len(post_urls)))]
    if not clean:
        return 0

    if active_provider_name() == PROVIDER_APIFY and not settings.apify_instagram_comment_actor_id:
        errors.append("评论发现: APIFY_INSTAGRAM_COMMENT_ACTOR_ID 未配置，已跳过评论区采集")
        return 0

    from app.services.apify_client import ApifyError

    try:
        discovery = await discover_comment_authors_from_post_urls(clean, limit=max(limit, 50))
    except (InstagramProviderError, ApifyError, Exception) as exc:
        errors.append(f"评论发现: {exc}")
        return 0

    errors.extend(discovery.errors)
    added = 0
    for candidate in discovery.candidates:
        if acc.add(candidate):
            added += 1
    return added


def evaluate_discovery_fatal(
    *,
    candidates: list[PostAuthorCandidate],
    hashtag_api_all_failed: bool,
    had_keyword_phase: bool,
) -> bool:
    """仅当无任何候选且关键词阶段 hashtag API 全部失败时视为致命失败。"""
    if candidates:
        return False
    if not had_keyword_phase:
        return False
    return hashtag_api_all_failed


async def unified_discover_candidates(
    task: CollectionTask,
    *,
    limit: int,
    db: AsyncSession | None = None,
    checkpoint: RunCheckpoint | None = None,
) -> UnifiedDiscoveryResult:
    checkpoint = checkpoint or RunCheckpoint()
    mode = normalize_collection_mode(task.collection_mode)
    comment_on = is_comment_discovery_enabled(task)
    acc = DiscoveryAccumulator()
    post_urls: list[str] = []
    seen_posts: set[str] = set()
    errors: list[str] = []
    meta: KeywordDiscoveryMeta | None = None
    competitor_meta: object | None = None
    hashtag_api_all_failed = False
    had_keyword_phase = False
    hashtag_count = 0
    post_count = 0

    if mode == "competitor_product":
        from app.services.competitor_product_discovery import discover_competitor_product_candidates

        had_keyword_phase = True
        cp_result = await discover_competitor_product_candidates(task, limit=limit)
        errors.extend(cp_result.errors)
        meta = cp_result.meta
        competitor_meta = cp_result.competitor_meta
        hashtag_api_all_failed = cp_result.hashtag_api_all_failed
        if meta:
            hashtag_count = meta.hashtag_count
            post_count = meta.post_count
        for candidate in cp_result.raw_candidates:
            acc.add(candidate)
        if cp_result.competitor_meta and cp_result.competitor_meta.product_info.parse_notes:
            errors.extend(cp_result.competitor_meta.product_info.parse_notes)

    if mode == "clustering":
        if not task.input_urls:
            raise NotImplementedError("相似账号发现需要至少一个种子主页链接。")
        provider = active_provider_name()
        if provider == PROVIDER_API_DIRECT:
            related_errors = [
                "相似账号发现: API Direct 暂不支持，请改用关键词/混合采集，"
                "或设置 INSTAGRAM_DATA_PROVIDER=apify 并配置 APIFY_INSTAGRAM_RELATED_ACTOR_ID。"
            ]
            urls = []
        else:
            from app.services.apify_instagram import discover_related_candidate_urls

            urls, related_errors = await discover_related_candidate_urls(task.input_urls, limit=limit)
        errors.extend(related_errors)
        for url in urls:
            candidate = _candidate_from_profile_url(url)
            if candidate:
                candidate.source_discovery_type = candidate.source_discovery_type or "related"
                acc.add(candidate)
        if comment_on and task.input_urls:
            resolved, resolve_errors = await resolve_target_post_urls(
                list(task.input_urls),
                posts_per_profile=5,
            )
            errors.extend(resolve_errors)
            for post in resolved:
                _append_post_url(post_urls, seen_posts, post)

    if mode in ("urls", "mixed") and task.input_urls:
        link_candidates, link_errors, link_posts, link_post_count = await discover_candidates_from_input_urls(
            task,
            limit=limit,
        )
        errors.extend(link_errors)
        post_count += link_post_count
        for candidate in link_candidates:
            acc.add(candidate)
        for post in link_posts:
            _append_post_url(post_urls, seen_posts, post)

    if mode in ("discovery", "keyword", "category_discovery") or (mode == "mixed" and task.keywords):
        if not task.keywords:
            if mode in ("discovery", "keyword", "category_discovery"):
                raise NotImplementedError("自动发现模式需要至少一个关键词。")
        else:
            had_keyword_phase = True
            kw_result = await discover_candidates_from_keywords(
                task,
                limit=limit,
                include_comments=False,
                checkpoint=checkpoint,
                db=db,
            )
            errors.extend(kw_result.errors)
            meta = kw_result.meta
            hashtag_api_all_failed = kw_result.hashtag_api_all_failed
            if meta:
                hashtag_count = meta.hashtag_count
                post_count += meta.post_count
            for candidate in kw_result.raw_candidates:
                acc.add(candidate)
            for post in kw_result.post_urls:
                _append_post_url(post_urls, seen_posts, post)

    if comment_on:
        await enrich_with_comment_discovery(acc, post_urls, limit=limit, errors=errors)

    deduped = acc.deduped_candidates[: limit * 2]
    raw = acc.raw_candidates
    comment_author_count = sum(
        1 for c in deduped if (c.source_discovery_type or "") == "comment_author"
    )
    discovery_api_failed = evaluate_discovery_fatal(
        candidates=deduped,
        hashtag_api_all_failed=hashtag_api_all_failed,
        had_keyword_phase=had_keyword_phase,
    )
    if discovery_api_failed:
        errors.insert(
            0,
            "Instagram 关键词/Hashtag 发现 API 全部失败，未获得任何候选账号。"
            "请检查 API_DIRECT_API_KEY 或 Apify 配置与账户额度。",
        )

    logger.info(
        "[UnifiedDiscovery] mode=%s comment=%s raw=%d deduped=%d dup=%d posts=%d errors=%d fatal=%s",
        mode,
        comment_on,
        len(raw),
        len(deduped),
        acc.duplicate_count,
        len(post_urls),
        len(errors),
        discovery_api_failed,
    )

    return UnifiedDiscoveryResult(
        candidates=deduped,
        raw_candidates=raw,
        deduped_candidates=deduped,
        discovery_duplicates=acc.discovery_duplicates,
        duplicate_count=acc.duplicate_count,
        errors=errors,
        meta=meta,
        competitor_meta=competitor_meta,
        discovery_api_failed=discovery_api_failed,
        hashtag_api_all_failed=hashtag_api_all_failed,
        hashtag_count=hashtag_count,
        post_count=post_count,
        comment_author_count=comment_author_count,
    )
