# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：business quality
"""Commercial quality signals for TikTok/YouTube style creator discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from app.services.contact_signals import (
    collect_contact_channel_keys,
    detect_dm_collab_signal,
    detect_storefront_from_links,
    detect_storefront_from_urls,
)


COMMERCIAL_INTENT_TERMS: tuple[tuple[str, str, int], ...] = (
    ("amazon storefront", "Amazon storefront", 38),
    ("tiktok shop", "TikTok Shop", 36),
    ("shop my", "Shop-my link", 32),
    ("affiliate", "Affiliate signal", 30),
    ("commissionable", "Affiliate signal", 28),
    ("ltk", "LTK", 34),
    ("shopmy", "ShopMy", 34),
    ("sponsored by", "Sponsored content", 34),
    ("sponsored", "Sponsored content", 26),
    ("use code", "Promo code", 28),
    ("discount code", "Promo code", 28),
    ("promo code", "Promo code", 26),
    ("gifted", "Gifted/PR content", 22),
    ("pr package", "Gifted/PR content", 26),
    ("brand partner", "Brand partnership", 32),
    ("brand partnership", "Brand partnership", 34),
    ("business inquiry", "Business inquiry", 32),
    ("business inquiries", "Business inquiry", 32),
    ("media kit", "Media kit", 30),
    ("collab", "Collaboration signal", 24),
    ("collaboration", "Collaboration signal", 24),
    ("partnership", "Partnership signal", 24),
    ("product review", "Product review", 28),
    ("honest review", "Product review", 24),
    ("unboxing", "Unboxing", 22),
    ("i tested", "Testing content", 18),
    ("links below", "Description links", 18),
    ("link in bio", "Bio-link signal", 20),
    ("合作", "合作信号", 28),
    ("商务", "商务信号", 30),
    ("带货", "带货信号", 30),
    ("测评", "测评内容", 24),
)

PRODUCT_INTENT_TERMS: tuple[str, ...] = (
    "amazon finds",
    "tiktok made me buy it",
    "best amazon",
    "product review",
    "honest review",
    "unboxing",
    "gift guide",
    "favorites",
    "must haves",
    "gadgets",
    "beauty finds",
    "home finds",
    "kitchen finds",
    "deal",
    "deals",
    "测评",
    "好物",
    "开箱",
)

LOW_VALUE_TERMS: tuple[tuple[str, str, int], ...] = (
    ("coupon", "Coupon/deal-only account", 36),
    ("deals only", "Deal-only account", 34),
    ("freebie", "Freebie audience", 30),
    ("giveaway only", "Giveaway-only account", 30),
    ("meme", "Meme/news account", 32),
    ("news", "Meme/news account", 30),
    ("fan page", "Fan page", 36),
    ("official fan", "Fan page", 36),
    ("scam", "Scam/controversy content", 34),
    ("fake", "Scam/controversy content", 24),
    ("exposed", "Expose/controversy content", 30),
    ("warning", "Warning/controversy content", 22),
    ("lawsuit", "Legal controversy", 30),
    ("prank", "Prank/challenge account", 24),
    ("challenge", "Prank/challenge account", 20),
    ("storytime", "Broad entertainment account", 18),
)


@dataclass
class CreatorQualityAssessment:
    commercial_score: float
    contactability_score: float
    content_match_score: float
    engagement_score: float
    risk_score: float
    product_fit: float
    sales_potential_score: float
    audience_match_score: float
    roi_forecast: float
    final_priority: str
    score: float
    positive_reasons: list[str] = field(default_factory=list)
    negative_reasons: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    collaboration_formats: list[str] = field(default_factory=list)
    content_topics: list[str] = field(default_factory=list)

    @property
    def reason_text(self) -> str:
        positives = "；".join(self.positive_reasons[:4]) or "商业合作信号较弱"
        negatives = "；".join(self.negative_reasons[:2])
        if negatives:
            return f"{positives}；风险提示：{negatives}"
        return positives


def _text_blob(row: Any) -> str:
    parts: list[str] = []
    for field_name in (
        "username",
        "display_name",
        "bio",
        "category",
        "niche",
        "profile_url",
        "source_post_url",
        "source_comment_text",
        "ai_summary",
        "score_reason",
        "ai_collaboration_suggestion",
    ):
        value = getattr(row, field_name, None)
        if value:
            parts.append(str(value))
    for field_name in ("tags", "content_topics", "recent_post_titles", "collaboration_formats"):
        values = getattr(row, field_name, None) or []
        parts.extend(str(item) for item in values if item)
    return " ".join(parts).lower()


def _contact_row(row: Any) -> Any:
    defaults = {
        "platform": None,
        "final_email": None,
        "email": None,
        "public_email": None,
        "business_email": None,
        "website": None,
        "contact_page": None,
        "linktree_url": None,
        "whatsapp": None,
        "telegram": None,
        "bio": None,
        "profile_url": None,
        "other_social_links": [],
        "contact_score": None,
        "contactability_score": None,
    }
    defaults.update({key: getattr(row, key, value) for key, value in defaults.items()})
    return SimpleNamespace(**defaults)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


YOUTUBE_COMMERCIAL_CONTENT_TERMS: tuple[str, ...] = (
    "review",
    "tutorial",
    "amazon finds",
    "product",
    "deals",
    "shopping",
    "unboxing",
    "honest review",
    "gift guide",
)


def _youtube_performance_boost(row: Any) -> tuple[float, list[str]]:
    if getattr(row, "platform", None) != "youtube":
        return 0.0, []

    boost = 0.0
    reasons: list[str] = []
    avg_views = getattr(row, "avg_views", None) or 0
    if avg_views >= 250_000:
        boost += 14.0
        reasons.append("YouTube 视频均播较高")
    elif avg_views >= 50_000:
        boost += 10.0
        reasons.append("YouTube 视频表现稳定")
    elif avg_views >= 10_000:
        boost += 6.0
        reasons.append("YouTube 有基础播放体量")

    titles_text = " ".join(getattr(row, "recent_post_titles", None) or []).lower()
    blob = _text_blob(row)
    hits = [term for term in YOUTUBE_COMMERCIAL_CONTENT_TERMS if term in titles_text or term in blob]
    if hits:
        boost += min(18.0, 8.0 + len(hits) * 3.0)
        reasons.append(f"YouTube 商业内容：{', '.join(hits[:3])}")

    return boost, reasons


def _score_engagement(row: Any) -> float:
    rate = getattr(row, "engagement_rate", None)
    if rate is not None:
        if rate >= 8:
            return 92.0
        if rate >= 5:
            return 82.0
        if rate >= 3:
            return 70.0
        if rate >= 1.5:
            return 55.0
        if rate >= 0.5:
            return 35.0
        return 18.0

    views = getattr(row, "avg_views", None) or 0
    likes = getattr(row, "avg_likes", None) or 0
    comments = getattr(row, "avg_comments", None) or 0
    if views and (likes or comments):
        inferred = (likes + comments) / views * 100
        return _score_engagement(type("_Row", (), {"engagement_rate": inferred})())
    if views >= 1_000_000:
        return 68.0
    if views >= 100_000:
        return 58.0
    if views >= 10_000:
        return 42.0
    return 25.0


def _size_fit_score(row: Any) -> tuple[float, str | None]:
    followers = getattr(row, "followers_count", None)
    avg_views = getattr(row, "avg_views", None)
    size = followers or avg_views or 0
    if not size:
        return 35.0, "体量数据不足"
    if 20_000 <= size <= 500_000:
        return 86.0, "中腰部体量适合测试合作"
    if 500_000 < size <= 2_000_000:
        return 70.0, "体量较大，适合预算充足的品牌曝光"
    if size > 2_000_000:
        return 52.0, "体量过大，触达成本和转化不确定性较高"
    return 55.0, "体量偏小，适合低成本试水"


def _task_keywords(task: Any | None) -> list[str]:
    if not task:
        return []
    keywords: list[str] = []
    for field_name in ("keywords", "filter_include_keywords"):
        keywords.extend(str(item).strip().lower().lstrip("#") for item in (getattr(task, field_name, None) or []) if str(item).strip())
    category = getattr(task, "category", None)
    if category:
        keywords.append(str(category).strip().lower())
    return _unique(keywords)


def _content_match_score(text: str, task: Any | None, positive_reasons: list[str]) -> float:
    keywords = _task_keywords(task)
    if not keywords:
        hits = [term for term in PRODUCT_INTENT_TERMS if term in text]
        if hits:
            positive_reasons.append(f"内容含产品/测评意图：{', '.join(hits[:2])}")
            return 76.0
        return 58.0
    matched = [kw for kw in keywords if kw and kw in text]
    if matched:
        positive_reasons.append(f"命中任务关键词：{', '.join(matched[:3])}")
        return min(92.0, 64.0 + len(matched) * 8)
    return 42.0


def assess_creator_quality(row: Any, task: Any | None = None) -> CreatorQualityAssessment:
    text = _text_blob(row)
    positives: list[str] = []
    negatives: list[str] = []
    tags: list[str] = list(getattr(row, "tags", None) or [])
    content_topics: list[str] = list(getattr(row, "content_topics", None) or [])
    collaboration_formats: list[str] = list(getattr(row, "collaboration_formats", None) or [])

    safe_contact_row = _contact_row(row)
    contact_keys = collect_contact_channel_keys(safe_contact_row)
    contactability = 0.0
    if "email" in contact_keys:
        contactability = 100.0
        positives.append("有邮箱，可直接外联")
    elif "contact_page" in contact_keys:
        contactability = 82.0
        positives.append("有联系页/表单")
    elif "linktree" in contact_keys:
        contactability = 74.0
        positives.append("有 Linktree/链接页")
    elif "website" in contact_keys:
        contactability = 66.0
        positives.append("有官网")
    elif "whatsapp" in contact_keys or "telegram" in contact_keys:
        contactability = 72.0
        positives.append("有即时通讯联系方式")
    elif "dm_collab" in contact_keys:
        contactability = 58.0
        positives.append("Bio 明确支持私信合作")
    elif any(key in contact_keys for key in ("shopmy", "ltk", "amazon_storefront")):
        contactability = 54.0
        positives.append("有商业外链")
    elif any(key in contact_keys for key in ("instagram", "facebook", "twitter", "tiktok", "linkedin", "external_link")):
        contactability = 52.0
        positives.append("有其他外链")
    else:
        negatives.append("暂无明确联系方式")

    commercial = 12.0
    storefront = detect_storefront_from_urls(safe_contact_row.website, safe_contact_row.profile_url) or detect_storefront_from_links(
        safe_contact_row.other_social_links
    )
    if storefront:
        commercial += 42.0
        positives.append(storefront)
    if detect_dm_collab_signal(safe_contact_row.bio):
        commercial += 24.0

    for term, label, weight in COMMERCIAL_INTENT_TERMS:
        if term in text:
            commercial += weight
            positives.append(label)
            if label in {"Product review", "Unboxing", "Testing content"}:
                collaboration_formats.append(label)
            if label in {"Affiliate signal", "Promo code", "Amazon storefront", "TikTok Shop"}:
                tags.append(label)

    risk = 10.0
    for term, label, weight in LOW_VALUE_TERMS:
        if term in text:
            risk += weight
            negatives.append(label)

    content_match = _content_match_score(text, task, positives)
    engagement = _score_engagement(row)
    youtube_boost, youtube_reasons = _youtube_performance_boost(row)
    if youtube_boost:
        commercial += youtube_boost
        engagement = round(min(100.0, engagement + youtube_boost * 0.35), 1)
        content_match = round(min(100.0, content_match + youtube_boost * 0.25), 1)
        positives.extend(youtube_reasons)
    size_fit, size_reason = _size_fit_score(row)
    if size_reason:
        positives.append(size_reason)

    product_fit = round(min(100.0, commercial * 0.45 + content_match * 0.35 + size_fit * 0.20), 1)
    sales = round(min(100.0, commercial * 0.40 + engagement * 0.25 + contactability * 0.20 + size_fit * 0.15), 1)
    audience = round(min(100.0, content_match * 0.55 + size_fit * 0.25 + engagement * 0.20), 1)
    commercial = round(min(100.0, commercial), 1)
    contactability = round(min(100.0, contactability), 1)
    risk = round(min(100.0, risk), 1)
    engagement = round(engagement, 1)

    score = commercial * 0.28 + contactability * 0.22 + content_match * 0.18 + sales * 0.18 + engagement * 0.10 + size_fit * 0.04
    score -= max(0.0, risk - 35.0) * 0.28
    score = round(max(0.0, min(100.0, score)), 1)

    if score >= 75 and contactability >= 50:
        priority = "P0"
    elif score >= 62:
        priority = "P1"
    elif score >= 48:
        priority = "P2"
    else:
        priority = "P3"

    roi = round(max(0.8, min(5.0, (sales / 30.0) + (commercial / 70.0) - (risk / 100.0))), 1)

    return CreatorQualityAssessment(
        commercial_score=commercial,
        contactability_score=contactability,
        content_match_score=round(content_match, 1),
        engagement_score=engagement,
        risk_score=risk,
        product_fit=product_fit,
        sales_potential_score=sales,
        audience_match_score=audience,
        roi_forecast=roi,
        final_priority=priority,
        score=score,
        positive_reasons=_unique(positives),
        negative_reasons=_unique(negatives),
        tags=_unique(tags)[:8],
        collaboration_formats=_unique(collaboration_formats)[:5],
        content_topics=_unique(content_topics)[:8],
    )


def apply_creator_quality(row: Any, task: Any | None = None, *, overwrite: bool = False) -> CreatorQualityAssessment:
    assessment = assess_creator_quality(row, task)

    updates = {
        "commercial_signal_score": assessment.commercial_score,
        "contactability_score": assessment.contactability_score,
        "content_match_score": assessment.content_match_score,
        "engagement_score": assessment.engagement_score,
        "risk_score": assessment.risk_score,
        "product_fit": assessment.product_fit,
        "sales_potential_score": assessment.sales_potential_score,
        "audience_match_score": assessment.audience_match_score,
        "roi_forecast": assessment.roi_forecast,
        "final_priority": assessment.final_priority,
        "score": assessment.score,
        "score_reason": assessment.reason_text,
    }
    for field_name, value in updates.items():
        if overwrite or getattr(row, field_name, None) is None:
            setattr(row, field_name, value)

    if overwrite or not getattr(row, "tags", None):
        row.tags = assessment.tags
    else:
        row.tags = _unique(list(getattr(row, "tags", None) or []) + assessment.tags)[:8]

    if overwrite or not getattr(row, "collaboration_formats", None):
        row.collaboration_formats = assessment.collaboration_formats
    else:
        row.collaboration_formats = _unique(list(getattr(row, "collaboration_formats", None) or []) + assessment.collaboration_formats)[:5]

    if overwrite or not getattr(row, "content_topics", None):
        row.content_topics = assessment.content_topics
    else:
        row.content_topics = _unique(list(getattr(row, "content_topics", None) or []) + assessment.content_topics)[:8]

    return assessment
