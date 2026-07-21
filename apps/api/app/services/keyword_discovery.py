# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：keyword discovery
"""关键词发现：扩展 hashtag → 帖子作者 + 评论用户。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.models.collection_task import CollectionTask
from app.core.config import settings
from app.services.apify_instagram import PostAuthorCandidate
from app.services.concurrency import map_bounded
from app.services.hashtag_expansion import expand_keywords_to_hashtags
from app.services.instagram_provider import (
    InstagramProviderError,
    discover_comment_authors_from_post_urls,
    discover_post_authors_from_hashtags,
    ensure_instagram_provider_ready,
)
from app.services.task_run_progress import RunCheckpoint, STAGE_DISCOVERY, update_task_progress
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class KeywordDiscoveryMeta:
    hashtag_count: int = 0
    post_count: int = 0
    post_author_count: int = 0
    comment_author_count: int = 0


@dataclass
class KeywordDiscoveryResult:
    """raw_candidates：各 hashtag/评论阶段追加的全部条目（含重复）；candidates 为去重后列表（兼容）。"""
    candidates: list[PostAuthorCandidate] = field(default_factory=list)
    raw_candidates: list[PostAuthorCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    meta: KeywordDiscoveryMeta = field(default_factory=KeywordDiscoveryMeta)
    post_urls: list[str] = field(default_factory=list)
    hashtag_api_all_failed: bool = False
    all_discovery_apis_failed: bool = False


async def discover_candidates_from_keywords(
    task: CollectionTask,
    *,
    limit: int = 100,
    max_hashtags: int = 15,
    max_posts_for_comments: int = 8,
    include_comments: bool = True,
    checkpoint: RunCheckpoint | None = None,
    db: AsyncSession | None = None,
) -> KeywordDiscoveryResult:
    """关键词真实发现：hashtag → 帖子作者；评论区由统一流水线可选追加。"""
    ensure_instagram_provider_ready()
    checkpoint = checkpoint or RunCheckpoint()

    keywords = [k.strip() for k in (task.keywords or []) if k and str(k).strip()]
    if not keywords:
        return KeywordDiscoveryResult(errors=["关键词发现模式需要至少一个关键词"])

    hashtags = expand_keywords_to_hashtags(keywords, max_hashtags=max_hashtags)
    if not hashtags:
        return KeywordDiscoveryResult(errors=["未能从关键词生成有效 hashtag"])

    checkpoint.extra["keyword_expansion"] = {
        "original_keyword_count": len(keywords),
        "expanded_keyword_count": len(hashtags),
        "attempted_keywords": list(hashtags),
    }

    pending_tags = [tag for tag in hashtags if not checkpoint.hashtag_done(tag)]
    if db is not None:
        await update_task_progress(
            db,
            task,
            stage=STAGE_DISCOVERY,
            total=max(limit, len(hashtags)),
            processed=len(checkpoint.completed_hashtags),
            commit=True,
        )

    errors: list[str] = []
    raw_candidates: list[PostAuthorCandidate] = []
    all_post_urls: list[str] = []
    post_count = 0
    post_author_count = 0

    per_tag_limit = max(15, limit // max(len(hashtags), 1))
    hashtag_successes = len([t for t in hashtags if checkpoint.hashtag_done(t)])

    async def _fetch_hashtag(tag: str):
        try:
            discovery = await discover_post_authors_from_hashtags([tag], limit=per_tag_limit)
            return tag, discovery, None
        except InstagramProviderError as exc:
            return tag, None, str(exc)

    tag_outcomes = await map_bounded(
        pending_tags,
        _fetch_hashtag,
        concurrency=settings.collection_search_concurrency,
    )

    for outcome in tag_outcomes:
        if isinstance(outcome, BaseException):
            errors.append(str(outcome))
            continue
        tag, discovery, err = outcome
        if err:
            errors.append(f"Hashtag #{tag}: {err}")
            checkpoint.mark_provider_unavailable("instagram", err)
            continue
        assert discovery is not None
        hashtag_successes += 1
        checkpoint.mark_hashtag(tag)
        errors.extend(discovery.errors)
        for detail in discovery.errors:
            checkpoint.mark_provider_unavailable("instagram", detail)
        post_count += discovery.post_count
        for post_url in discovery.post_urls:
            if post_url not in all_post_urls:
                all_post_urls.append(post_url)
        for candidate in discovery.candidates:
            raw_candidates.append(candidate)
            post_author_count += 1
        if db is not None:
            await update_task_progress(
                db,
                task,
                stage=STAGE_DISCOVERY,
                processed=len(checkpoint.completed_hashtags),
                total=max(limit, len(hashtags)),
                discovered_count=len(raw_candidates),
                deduped_count=len({c.profile_url.lower() for c in raw_candidates}),
                checkpoint=checkpoint,
                commit=True,
            )
        if len(raw_candidates) >= limit * 4:
            break

    comment_author_count = 0
    posts_to_scan = [
        url for url in all_post_urls[:max_posts_for_comments] if not checkpoint.post_url_done(url)
    ]
    if include_comments and posts_to_scan:
        comment_limit = max(limit, 50)
        try:
            comment_discovery = await discover_comment_authors_from_post_urls(
                posts_to_scan,
                limit=comment_limit,
            )
        except InstagramProviderError as exc:
            errors.append(f"评论发现: {exc}")
        else:
            errors.extend(comment_discovery.errors)
            for candidate in comment_discovery.candidates:
                raw_candidates.append(candidate)
                comment_author_count += 1
            for url in posts_to_scan:
                checkpoint.mark_post_url(url)
            if db is not None:
                await update_task_progress(db, task, checkpoint=checkpoint, commit=True)

    deduped_map: dict[str, PostAuthorCandidate] = {}
    for candidate in raw_candidates:
        key = candidate.profile_url.lower()
        if key not in deduped_map:
            deduped_map[key] = candidate
    candidates = list(deduped_map.values())[: limit * 2]

    hashtag_api_all_failed = bool(hashtags) and hashtag_successes == 0
    all_discovery_apis_failed = len(deduped_map) == 0 and hashtag_api_all_failed
    if all_discovery_apis_failed and include_comments:
        errors.insert(
            0,
            "Instagram 关键词/Hashtag 发现 API 全部失败，未获得任何候选账号。"
            "请检查 API_DIRECT_API_KEY 或 Apify 配置与账户额度。",
        )

    logger.info(
        "[KeywordDiscovery] keywords=%s hashtags=%d posts=%d authors=%d comments=%d raw=%d deduped=%d",
        keywords,
        len(hashtags),
        post_count,
        post_author_count,
        comment_author_count,
        len(raw_candidates),
        len(candidates),
    )

    return KeywordDiscoveryResult(
        candidates=candidates,
        raw_candidates=raw_candidates,
        errors=errors,
        meta=KeywordDiscoveryMeta(
            hashtag_count=len(hashtags),
            post_count=post_count,
            post_author_count=post_author_count,
            comment_author_count=comment_author_count,
        ),
        post_urls=all_post_urls,
        hashtag_api_all_failed=hashtag_api_all_failed,
        all_discovery_apis_failed=all_discovery_apis_failed,
    )
