# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：value tier
"""红人价值分层：可直接外联 / 值得人工找联系 / 暂时跳过。"""

from __future__ import annotations

from typing import Literal, Protocol

from sqlalchemy import String, and_, func, not_, or_

from app.models.influencer import Influencer
from app.services.contact_signals import (
    COMMERCIAL_STOREFRONT_TERMS,
    DM_COLLAB_TERMS,
    commercial_storefront_manual_reason,
    detect_dm_collab_signal,
    direct_contact_reason as _shared_direct_contact_reason,
    has_direct_contact_channel,
)

ValueTier = Literal["direct_contact", "manual_research", "skip"]

VALUE_TIER_LABELS: dict[ValueTier, str] = {
    "direct_contact": "可直接外联",
    "manual_research": "值得人工找联系",
    "skip": "暂时跳过",
}

COMMERCIAL_TERMS: tuple[str, ...] = (
    "affiliate",
    "amazon storefront",
    "business",
    "collab",
    "collaboration",
    "partnership",
    "pr ",
    "product curator",
    "review",
    "shop my",
    "shopmy",
    "ltk",
    "sponsored",
    "unboxing",
    "合作",
    "商务",
    "带货",
    "测评",
) + COMMERCIAL_STOREFRONT_TERMS

LOW_VALUE_TERMS: tuple[str, ...] = (
    "coupon",
    "deal",
    "fan page",
    "group",
    "marketplace",
    "meme",
    "news",
    "official",
    "优惠",
    "官方",
    "店铺",
    "新闻",
    "粉丝页",
    "群组",
)

LOW_VALUE_URL_PATTERNS: tuple[str, ...] = (
    "%facebook.com/people/%",
    "%/groups/%",
    "%/pages/%",
    "%/watch/%",
    "%/reel/%",
    "%/video/%",
)

STOREFRONT_URL_PATTERNS: tuple[str, ...] = (
    "%shopmy.us/%",
    "%shopltk.com/%",
    "%amazon.com/shop/%",
    "%amazon.com/stores/%",
)


class _InfluencerLike(Protocol):
    platform: str | None
    final_email: str | None
    email: str | None
    public_email: str | None
    business_email: str | None
    website: str | None
    contact_page: str | None
    linktree_url: str | None
    whatsapp: str | None
    telegram: str | None
    other_social_links: list | None
    contact_score: float | None
    contactability_score: float | None
    final_priority: str | None
    score: float | None
    product_fit: float | None
    commercial_signal_score: float | None
    bio: str | None
    ai_summary: str | None
    score_reason: str | None
    ai_collaboration_suggestion: str | None
    tags: list | None
    content_topics: list | None
    profile_url: str | None
    username: str | None
    display_name: str | None


def _row_field(row: object, name: str, default=None):
    return getattr(row, name, default)


def _content_text_blob(row: _InfluencerLike) -> str:
    parts: list[str] = []
    for name in ("bio", "ai_summary", "score_reason", "ai_collaboration_suggestion"):
        field = _row_field(row, name)
        if field:
            parts.append(str(field))
    for name in ("tags", "content_topics"):
        collection = _row_field(row, name)
        if collection:
            parts.append(" ".join(str(item) for item in collection if item))
    return " ".join(parts).lower()


def _identity_text_blob(row: _InfluencerLike) -> str:
    parts: list[str] = []
    for name in ("display_name", "username", "bio", "profile_url"):
        field = _row_field(row, name)
        if field:
            parts.append(str(field))
    for name in ("tags", "content_topics"):
        collection = _row_field(row, name)
        if collection:
            parts.append(" ".join(str(item) for item in collection if item))
    parts.append(_content_text_blob(row))
    return " ".join(parts).lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> str | None:
    if not text:
        return None
    ordered = sorted(terms, key=len, reverse=True)
    for term in ordered:
        if term.lower() in text:
            return term
    return None


def _low_value_text_hit(row: _InfluencerLike) -> str | None:
    if has_direct_contact_channel(row):
        return None

    text = _identity_text_blob(row)
    if not text:
        return None
    if _contains_any(text, COMMERCIAL_TERMS):
        return None
    if detect_dm_collab_signal(_row_field(row, "bio")):
        return None
    return _contains_any(text, LOW_VALUE_TERMS)


def _low_value_url_hit(row: _InfluencerLike) -> str | None:
    url = (_row_field(row, "profile_url") or "").lower()
    if not url:
        return None
    if "facebook.com/people/" in url:
        return "Facebook people 链接"
    for fragment in ("/groups/", "/pages/", "/watch/", "/reel/", "/video/"):
        if fragment in url:
            return f"Facebook 非主页路径({fragment.strip('/')})"
    return None


def _has_direct_contact(row: _InfluencerLike) -> bool:
    return has_direct_contact_channel(row)


def _verification_required_reason(row: _InfluencerLike) -> str | None:
    status = _row_field(row, "contact_fetch_status")
    if status not in {"verification_required", "manual_required"}:
        return None
    reason = _shared_direct_contact_reason(row)
    if reason:
        return reason
    error = _row_field(row, "contact_fetch_error")
    if error:
        return str(error)
    return "邮箱需人工验证"


def _manual_research_match(row: _InfluencerLike) -> str | None:
    storefront_reason = commercial_storefront_manual_reason(row)
    if storefront_reason:
        return storefront_reason

    final_priority = _row_field(row, "final_priority")
    if final_priority in ("P0", "P1", "P2"):
        return f"优先级 {final_priority}"
    score = _row_field(row, "score")
    if score is not None and score >= 50:
        return f"综合评分 {score:.0f}"
    product_fit = _row_field(row, "product_fit")
    if product_fit is not None and product_fit >= 60:
        return f"产品匹配 {product_fit:.0f}"
    commercial_signal_score = _row_field(row, "commercial_signal_score")
    if commercial_signal_score is not None and commercial_signal_score >= 50:
        return f"商业信号 {commercial_signal_score:.0f}"
    text = _content_text_blob(row)
    hit = _contains_any(text, COMMERCIAL_TERMS)
    if hit:
        return f"含合作关键词「{hit.strip()}」"
    return None


def classify_value_tier(row: _InfluencerLike) -> tuple[ValueTier, str, str]:
    url_hit = _low_value_url_hit(row)
    if url_hit:
        return "skip", VALUE_TIER_LABELS["skip"], url_hit

    term_hit = _low_value_text_hit(row)
    if term_hit:
        return "skip", VALUE_TIER_LABELS["skip"], f"低价值特征「{term_hit.strip()}」"

    verification_reason = _verification_required_reason(row)
    if verification_reason:
        return "direct_contact", VALUE_TIER_LABELS["direct_contact"], verification_reason

    if _has_direct_contact(row):
        reason = _shared_direct_contact_reason(row) or "有直接联系方式"
        return "direct_contact", VALUE_TIER_LABELS["direct_contact"], reason

    manual_hit = _manual_research_match(row)
    if manual_hit:
        return "manual_research", VALUE_TIER_LABELS["manual_research"], manual_hit

    return "skip", VALUE_TIER_LABELS["skip"], "无联系方式且无商业价值"


def value_tier_label(tier: ValueTier) -> str:
    return VALUE_TIER_LABELS[tier]


def _content_text_signal_condition(terms: tuple[str, ...]):
    text_fields = (
        Influencer.bio,
        Influencer.ai_summary,
        Influencer.score_reason,
        Influencer.ai_collaboration_suggestion,
        Influencer.tags.cast(String),
        Influencer.content_topics.cast(String),
    )
    return or_(
        *(
            func.coalesce(field, "").ilike(f"%{term}%")
            for field in text_fields
            for term in terms
        )
    )


def _identity_text_signal_condition(terms: tuple[str, ...]):
    text_fields = (
        Influencer.display_name,
        Influencer.username,
        Influencer.bio,
        Influencer.profile_url,
        Influencer.tags.cast(String),
        Influencer.content_topics.cast(String),
        Influencer.ai_summary,
        Influencer.score_reason,
        Influencer.ai_collaboration_suggestion,
    )
    return or_(
        *(
            func.coalesce(field, "").ilike(f"%{term}%")
            for field in text_fields
            for term in terms
        )
    )


def _bio_dm_collab_condition():
    return or_(*(func.coalesce(Influencer.bio, "").ilike(f"%{term}%") for term in DM_COLLAB_TERMS))


def _commercial_storefront_url_condition():
    return or_(
        *(
            or_(
                func.coalesce(Influencer.profile_url, "").ilike(pattern),
                func.coalesce(Influencer.website, "").ilike(pattern),
            )
            for pattern in STOREFRONT_URL_PATTERNS
        )
    )


def _low_value_text_signal_condition():
    commercial_hits = _content_text_signal_condition(COMMERCIAL_TERMS)
    dm_hits = _bio_dm_collab_condition()
    low_value_hits = _identity_text_signal_condition(LOW_VALUE_TERMS)
    return and_(
        low_value_hits,
        not_(commercial_hits),
        not_(dm_hits),
        not_(_has_direct_contact_condition()),
    )


def _low_value_url_condition():
    return or_(
        *(
            Influencer.profile_url.ilike(pattern)
            for pattern in LOW_VALUE_URL_PATTERNS
        )
    )


def _has_direct_contact_condition():
    return or_(
        Influencer.final_email.isnot(None),
        Influencer.email.isnot(None),
        Influencer.public_email.isnot(None),
        Influencer.business_email.isnot(None),
        Influencer.website.isnot(None),
        Influencer.contact_page.isnot(None),
        Influencer.linktree_url.isnot(None),
        Influencer.whatsapp.isnot(None),
        Influencer.telegram.isnot(None),
        Influencer.contact_score >= 50.0,
        Influencer.contactability_score >= 50.0,
        _bio_dm_collab_condition(),
        _commercial_storefront_url_condition(),
    )


def _manual_research_condition():
    return and_(
        not_(_has_direct_contact_condition()),
        or_(
            _commercial_storefront_url_condition(),
            Influencer.final_priority.in_(("P0", "P1", "P2")),
            Influencer.score >= 50.0,
            Influencer.product_fit >= 60.0,
            Influencer.commercial_signal_score >= 50.0,
            _content_text_signal_condition(COMMERCIAL_TERMS),
        ),
    )


def _low_value_condition():
    return or_(
        _low_value_url_condition(),
        _low_value_text_signal_condition(),
    )


def direct_contact_tier_condition():
    return and_(not_(_low_value_condition()), _has_direct_contact_condition())


def manual_research_tier_condition():
    return and_(
        not_(_low_value_condition()),
        _manual_research_condition(),
    )


def skip_tier_condition():
    return or_(
        _low_value_condition(),
        and_(
            not_(_has_direct_contact_condition()),
            not_(
                or_(
                    _commercial_storefront_url_condition(),
                    Influencer.final_priority.in_(("P0", "P1", "P2")),
                    Influencer.score >= 50.0,
                    Influencer.product_fit >= 60.0,
                    Influencer.commercial_signal_score >= 50.0,
                    _content_text_signal_condition(COMMERCIAL_TERMS),
                )
            ),
        ),
    )


def reachable_contact_condition():
    """任一明确可触达渠道，用于 contactable / missing_contact 筛选。"""
    return _has_direct_contact_condition()


def high_value_tier_condition():
    """A+B：可直接外联或值得人工找联系。"""
    return or_(direct_contact_tier_condition(), manual_research_tier_condition())
