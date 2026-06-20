"""候选池：来源映射、失败原因规范化、错误文案脱敏。"""

from __future__ import annotations

import re
from types import SimpleNamespace

from app.models.enums import CandidateFailureReason, CandidateSourceType, ProfileFailureReason
from app.services.apify_instagram import PostAuthorCandidate
from app.services.collection_filters import (
    required_min_followers_for_item,
    uses_discovery_hard_min_followers_for_item,
)
from app.models.collection_task import CollectionTask

REEL_PATH_RE = re.compile(r"instagram\.com/reel/", re.I)
SECRET_PATTERNS = (
    re.compile(r"(api[_-]?key|token|secret|password)\s*[=:]\s*\S+", re.I),
    re.compile(r"Bearer\s+\S+", re.I),
    re.compile(r"x-access-key[:\s]+\S+", re.I),
)


def sanitize_failure_detail(text: str | None, *, max_len: int = 2000) -> str | None:
    if not text:
        return None
    cleaned = text
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub("[已隐藏]", cleaned)
    return cleaned[:max_len]


def resolve_source_type(
    meta: PostAuthorCandidate,
    *,
    collection_mode: str | None = None,
) -> str:
    discovery = (meta.source_discovery_type or "").lower()
    post_url = (meta.source_post_url or "").lower()
    mode = (collection_mode or "").lower()
    if mode == "clustering" or discovery == "related":
        return CandidateSourceType.RELATED_PROFILE.value
    if discovery == "competitor_product":
        return CandidateSourceType.COMPETITOR_PRODUCT_POST_AUTHOR.value
    if discovery == "comment_author":
        return CandidateSourceType.COMMENT_AUTHOR.value
    if discovery == "url_profile":
        return CandidateSourceType.INPUT_PROFILE.value
    if discovery == "post_author" and meta.source_hashtag:
        return CandidateSourceType.HASHTAG_POST_AUTHOR.value
    if discovery == "post_author":
        if REEL_PATH_RE.search(post_url):
            return CandidateSourceType.INPUT_REEL.value
        if post_url and ("/p/" in post_url or "/tv/" in post_url):
            return CandidateSourceType.INPUT_POST.value
        return CandidateSourceType.KEYWORD_POST_AUTHOR.value
    if mode in ("urls", "comment_authors") and post_url:
        if REEL_PATH_RE.search(post_url):
            return CandidateSourceType.INPUT_REEL.value
        return CandidateSourceType.INPUT_POST.value
    return CandidateSourceType.UNKNOWN.value


def normalize_profile_failure_reason(reason: str | None) -> str:
    value = (reason or "").strip().lower()
    mapping = {
        ProfileFailureReason.PRIVATE_ACCOUNT.value: CandidateFailureReason.PRIVATE_ACCOUNT.value,
        ProfileFailureReason.INVALID_USERNAME.value: CandidateFailureReason.INVALID_USERNAME.value,
        ProfileFailureReason.MISSING_PROFILE_DETAIL.value: CandidateFailureReason.MISSING_PROFILE_DETAIL.value,
        ProfileFailureReason.PROFILE_NOT_FOUND.value: CandidateFailureReason.DISABLED_OR_DELETED.value,
        ProfileFailureReason.SCRAPER_BLOCKED.value: CandidateFailureReason.API_FAILED.value,
    }
    return mapping.get(value, CandidateFailureReason.PROFILE_FETCH_FAILED.value)


def normalize_hard_filter_reason(reason: str | None) -> str:
    if not reason:
        return CandidateFailureReason.UNKNOWN.value
    if reason == "no_same_product_match":
        return CandidateFailureReason.NO_SAME_PRODUCT_MATCH.value
    if reason == "below_min_followers":
        return CandidateFailureReason.BELOW_MIN_FOLLOWERS.value
    if reason == "below_min_engagement_rate":
        return CandidateFailureReason.BELOW_MIN_ENGAGEMENT_RATE.value
    if reason == "above_max_followers":
        return CandidateFailureReason.ABOVE_MAX_FOLLOWERS.value
    if reason == "missing_engagement_rate":
        return CandidateFailureReason.MISSING_ENGAGEMENT_RATE.value
    if reason == "missing_email":
        return CandidateFailureReason.MISSING_EMAIL.value
    if reason == "missing_contact":
        return CandidateFailureReason.MISSING_CONTACT.value
    if reason in ("invalid_profile", "invalid_username"):
        return CandidateFailureReason.INVALID_USERNAME.value
    if reason.startswith("excluded_keyword:"):
        return CandidateFailureReason.EXCLUDED_KEYWORD.value
    if reason == "low_value_seed":
        return CandidateFailureReason.LOW_VALUE_SEED.value
    return CandidateFailureReason.UNKNOWN.value


def hard_filter_failure_detail(
    reason: str | None,
    *,
    task: CollectionTask,
    followers_count: int | None = None,
    platform: str | None = None,
) -> str:
    if not reason:
        return "未通过硬筛选"
    if reason.startswith("excluded_keyword:"):
        kw = reason.split(":", 1)[1]
        return f"简介/内容命中排除词：{kw}"
    if reason == "invalid_profile":
        name = (platform or "instagram").strip().lower()
        if name != "instagram":
            return f"无效 {name} 主页或用户名"
        return "无效 Instagram 主页或用户名"
    if reason == "no_same_product_match":
        return "未命中同款商品指纹"
    if reason == "below_min_followers":
        item = SimpleNamespace(platform=platform or "instagram")
        required = required_min_followers_for_item(item, task)
        if followers_count is None:
            if required is not None:
                if uses_discovery_hard_min_followers_for_item(item, task):
                    return f"粉丝数未知，无法验证最低粉丝门槛（需 ≥{required:,}，系统至少 3 万）"
                return f"粉丝数未知，无法验证最低粉丝门槛（需 ≥{required:,}）"
            return "粉丝数未知，无法验证最低粉丝门槛"
        if required is not None:
            return f"粉丝数 {followers_count:,}，低于最低要求 {required:,}"
        return f"粉丝数 {followers_count:,}，低于最低粉丝门槛"
    return reason


def meta_source_fields(meta: PostAuthorCandidate, *, collection_mode: str | None = None) -> dict:
    source_meta = dict(meta.source_meta or {})
    source_input_url = meta.source_input_url or source_meta.get("source_input_url") or source_meta.get("input_url")
    if source_input_url:
        source_meta["source_input_url"] = str(source_input_url)
    fields = {
        "source_type": resolve_source_type(meta, collection_mode=collection_mode),
        "source_hashtag": meta.source_hashtag,
        "source_keyword": meta.source_hashtag,
        "source_post_url": meta.source_post_url,
        "source_input_url": source_input_url,
        "source_caption": meta.source_caption,
        "source_comment_url": meta.source_comment_url,
        "source_comment_text": meta.source_comment_text,
        "source_discovery_type": meta.source_discovery_type,
    }
    if source_meta:
        fields["source_meta"] = source_meta
    return fields
