# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：instagram quality
"""Instagram 采集第 3 步：质量评分与 P0-P3 优先级。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.collectors.base import CollectedInfluencer
from app.models.collection_task import CollectionTask
from app.services.collection_filters import (
    build_searchable_text,
    get_quality_preference_mismatch_reasons,
)

PRIORITY_P0 = "P0"
PRIORITY_P1 = "P1"
PRIORITY_P2 = "P2"
PRIORITY_P3 = "P3"
AI_PRIORITIES = frozenset({PRIORITY_P0, PRIORITY_P1})

COMMERCE_WORDS = (
    "amazon",
    "affiliate",
    "collab",
    "collaboration",
    "brand",
    "sponsor",
    "paid",
    "partnership",
    "shop",
    "discount",
    "coupon",
    "pr ",
    "gifted",
)
RISK_WORDS = ("giveaway", "fan page", "fanpage", "meme", "repost", "spam", "bot")


@dataclass
class InfluencerQualityScores:
    engagement_score: float
    content_match_score: float
    contactability_score: float
    commercial_signal_score: float
    activity_score: float
    risk_score: float
    final_priority: str
    quality_composite: float


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, value)), 1)


def _engagement_score(item: CollectedInfluencer) -> float:
    rate = item.engagement_rate
    if rate is None:
        likes = item.avg_likes or 0
        followers = item.followers_count or 0
        if followers > 0 and likes > 0:
            rate = (likes + (item.avg_comments or 0)) / followers * 100
        else:
            return 25.0
    if rate >= 8:
        return 95.0
    if rate >= 5:
        return 86.0
    if rate >= 3:
        return 75.0
    if rate >= 1.5:
        return 62.0
    if rate >= 0.5:
        return 46.0
    return 28.0


def _content_match_score(item: CollectedInfluencer, task: CollectionTask | None) -> float:
    searchable = build_searchable_text(item)
    keywords: list[str] = []
    if task:
        keywords.extend(task.filter_include_keywords or [])
        keywords.extend(task.keywords or [])
        if task.category:
            keywords.append(task.category)
    keywords = [k.strip().lower() for k in keywords if k and str(k).strip()]
    if not keywords:
        return 55.0 if item.bio else 40.0

    hits = sum(1 for kw in keywords if kw in searchable)
    ratio = hits / len(keywords)
    base = 35.0 + ratio * 55.0
    if item.recent_post_titles:
        base = min(100.0, base + 8.0)
    return _clamp(base)


def _contactability_score(item: CollectedInfluencer) -> float:
    score = 15.0
    if item.final_email or item.email or item.business_email or item.public_email:
        score += 55.0
    if item.linktree_url or item.website or item.contact_page:
        score += 18.0
    if item.whatsapp or item.telegram:
        score += 12.0
    if item.contact_score:
        score = max(score, float(item.contact_score))
    return _clamp(score)


def _commercial_signal_score(item: CollectedInfluencer) -> float:
    text = " ".join(
        [
            item.bio or "",
            " ".join(item.recent_post_titles or []),
            " ".join(item.content_topics or []),
        ]
    ).lower()
    hits = sum(1 for word in COMMERCE_WORDS if word in text)
    score = 30.0 + min(50.0, hits * 12.0)
    if item.has_brand_collaboration:
        score += 18.0
    if item.estimated_collab_price:
        score += 8.0
    return _clamp(score)


def _activity_score(item: CollectedInfluencer) -> float:
    score = 25.0
    posts = len(item.recent_post_urls or []) + len(item.recent_post_titles or [])
    if posts >= 5:
        score += 35.0
    elif posts >= 2:
        score += 22.0
    elif posts >= 1:
        score += 12.0

    if item.last_post_at:
        days = (datetime.now(UTC) - item.last_post_at).days
        if days <= 7:
            score += 35.0
        elif days <= 30:
            score += 25.0
        elif days <= 90:
            score += 12.0
        else:
            score += 4.0
    elif item.posting_frequency:
        score += 10.0

    if item.avg_likes or item.avg_views:
        score += 8.0
    return _clamp(score)


def _risk_score(item: CollectedInfluencer, task: CollectionTask | None) -> float:
    """越高表示风险越大。"""
    risk = 20.0
    followers = item.followers_count or 0
    if followers < 1000:
        risk += 28.0
    elif followers < 5000:
        risk += 12.0

    if item.engagement_rate is not None and item.engagement_rate < 0.3:
        risk += 22.0
    elif item.engagement_rate is not None and item.engagement_rate < 1.0:
        risk += 10.0

    if not (item.final_email or item.email):
        risk += 12.0

    searchable = build_searchable_text(item)
    if any(word in searchable for word in RISK_WORDS):
        risk += 18.0

    if task and task.filter_exclude_keywords:
        exclude = [k.strip().lower() for k in task.filter_exclude_keywords if k and k.strip()]
        if any(kw in searchable for kw in exclude):
            risk += 35.0

    if task:
        mismatches = get_quality_preference_mismatch_reasons(item, task)
        risk += min(24.0, len(mismatches) * 8.0)

    if (item.data_completeness or 0) < 50:
        risk += 8.0
    return _clamp(risk)


def _assign_priority(
    engagement: float,
    content: float,
    contact: float,
    commercial: float,
    activity: float,
    risk: float,
) -> tuple[str, float]:
    positive = (engagement + content + contact + commercial + activity) / 5.0
    composite = _clamp(positive - risk * 0.35)

    if composite >= 75 and risk <= 35 and contact >= 50:
        return PRIORITY_P0, composite
    if composite >= 62 and risk <= 50:
        return PRIORITY_P1, composite
    if composite >= 45:
        return PRIORITY_P2, composite
    return PRIORITY_P3, composite


def compute_quality_scores(
    item: CollectedInfluencer,
    task: CollectionTask | None = None,
) -> InfluencerQualityScores:
    engagement = _engagement_score(item)
    content = _content_match_score(item, task)
    contact = _contactability_score(item)
    commercial = _commercial_signal_score(item)
    activity = _activity_score(item)
    risk = _risk_score(item, task)
    priority, composite = _assign_priority(engagement, content, contact, commercial, activity, risk)
    return InfluencerQualityScores(
        engagement_score=engagement,
        content_match_score=content,
        contactability_score=contact,
        commercial_signal_score=commercial,
        activity_score=activity,
        risk_score=risk,
        final_priority=priority,
        quality_composite=composite,
    )


def apply_quality_scores_to_item(
    item: CollectedInfluencer,
    scores: InfluencerQualityScores,
) -> None:
    item.engagement_score = scores.engagement_score
    item.content_match_score = scores.content_match_score
    item.contactability_score = scores.contactability_score
    item.commercial_signal_score = scores.commercial_signal_score
    item.activity_score = scores.activity_score
    item.risk_score = scores.risk_score
    item.final_priority = scores.final_priority
    item.score = scores.quality_composite
    item.risk_level = "high" if scores.risk_score >= 65 else "medium" if scores.risk_score >= 40 else "low"
