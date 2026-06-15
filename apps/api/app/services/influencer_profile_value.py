"""判断入库红人资料是否具备业务可用价值（非空壳链接占位）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, cast, exists, func, not_, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.services.contact_signals import (
    detect_external_link_contact_reason,
    detect_storefront_from_urls,
)

_EMPTY_JSONB = cast("[]", JSONB)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_url_for_compare(url: str) -> str:
    return url.strip().lower().rstrip("/")


def _is_self_profile_url(item: Any, url: str) -> bool:
    """平台主页 URL 本身不算额外商业外链（空壳占位）。"""
    needle = _normalize_url_for_compare(url)
    if not needle:
        return False
    for field in ("profile_url", "normalized_profile_url"):
        candidate = _normalize_url_for_compare(_text(getattr(item, field, None)))
        if candidate and needle == candidate:
            return True
    return False


def _meaningful_external_links(item: Any) -> list:
    links = getattr(item, "other_social_links", None) or []
    if not isinstance(links, list):
        return []
    meaningful: list = []
    for link in links:
        if not isinstance(link, dict):
            continue
        url = _text(link.get("url") or link.get("href"))
        if not url or _is_self_profile_url(item, url):
            continue
        meaningful.append(link)
    return meaningful


def _has_direct_contact(item: Any) -> bool:
    for field in (
        "email",
        "final_email",
        "public_email",
        "business_email",
        "contact_page",
        "linktree_url",
        "whatsapp",
        "telegram",
    ):
        if _text(getattr(item, field, None)):
            return True
    website = _text(getattr(item, "website", None))
    if website and not _is_self_profile_url(item, website):
        if not detect_storefront_from_urls(website):
            return True
        if _has_influence_metrics(item) or _has_profile_context(item):
            return True
    links = _meaningful_external_links(item)
    if links:
        if detect_external_link_contact_reason(links):
            return True
        for link in links:
            url = _text(link.get("url") or link.get("href"))
            if not url:
                continue
            if detect_storefront_from_urls(url) and (
                _has_influence_metrics(item) or _has_profile_context(item)
            ):
                return True
            if not detect_storefront_from_urls(url):
                return True
    return False


def _has_influence_metrics(item: Any) -> bool:
    for field in (
        "followers_count",
        "engagement_rate",
        "avg_views",
        "avg_likes",
        "avg_comments",
    ):
        if getattr(item, field, None) is not None:
            return True
    return False


def _has_profile_context(item: Any) -> bool:
    if _text(getattr(item, "bio", None)):
        return True
    for field in ("category", "country", "language", "niche"):
        if _text(getattr(item, field, None)):
            return True
    topics = getattr(item, "content_topics", None) or []
    if isinstance(topics, list) and any(_text(t) for t in topics):
        return True
    return False


def is_influencer_profile_valuable(item: Any) -> bool:
    """至少具备联系方式、影响力指标、简介/类目等可用资料之一。"""
    if _has_direct_contact(item):
        return True
    if _has_influence_metrics(item):
        return True
    if _has_profile_context(item):
        return True
    return False


def is_candidate_row_valuable(candidate: Any) -> bool:
    if bool(getattr(candidate, "has_email", False)) or bool(getattr(candidate, "has_contact", False)):
        return True
    if getattr(candidate, "followers_count", None) is not None:
        return True
    if getattr(candidate, "engagement_rate", None) is not None:
        return True
    if bool(getattr(candidate, "is_high_value", False)):
        return True
    return is_influencer_profile_valuable(candidate)


def _normalized_url_sql(url_column):
    return func.lower(func.rtrim(func.trim(url_column), "/"))


def _url_is_self_profile_sql(url_column):
    url_norm = _normalized_url_sql(url_column)
    return or_(
        url_norm == _normalized_url_sql(GlobalInfluencerProfile.profile_url),
        url_norm == _normalized_url_sql(GlobalInfluencerProfile.normalized_profile_url),
    )


def _is_storefront_url_sql(url_column):
    lower_url = func.lower(url_column)
    return or_(
        lower_url.like("%//shopmy.us%"),
        lower_url.like("%//www.shopmy.us%"),
        lower_url.like("%//shopltk.com%"),
        lower_url.like("%//www.shopltk.com%"),
        lower_url.like("%amazon.com/shop/%"),
        lower_url.like("%amazon.com/stores/%"),
        lower_url.like("%amzn.to/%"),
        lower_url.like("%amzlink.to/%"),
        lower_url.like("%urlgeni.us/amzn/%"),
    )


def _influence_metrics_sql():
    return or_(
        GlobalInfluencerProfile.followers_count.isnot(None),
        GlobalInfluencerProfile.engagement_rate.isnot(None),
        GlobalInfluencerProfile.avg_views.isnot(None),
        GlobalInfluencerProfile.avg_likes.isnot(None),
        GlobalInfluencerProfile.avg_comments.isnot(None),
    )


def _has_nonempty_content_topics_sql():
    topics = func.coalesce(GlobalInfluencerProfile.content_topics, _EMPTY_JSONB)
    topic_elem = func.jsonb_array_elements_text(topics).table_valued("value")
    return exists(
        select(1)
        .select_from(topic_elem)
        .where(func.length(func.trim(topic_elem.c.value)) > 0)
    )


def _profile_context_sql():
    return or_(
        func.length(func.coalesce(GlobalInfluencerProfile.bio, "")) > 0,
        func.coalesce(GlobalInfluencerProfile.category, "") != "",
        func.coalesce(GlobalInfluencerProfile.country, "") != "",
        func.coalesce(GlobalInfluencerProfile.language, "") != "",
        func.coalesce(GlobalInfluencerProfile.niche, "") != "",
        _has_nonempty_content_topics_sql(),
    )


def _direct_contact_fields_sql():
    return or_(
        func.coalesce(GlobalInfluencerProfile.email, "") != "",
        func.coalesce(GlobalInfluencerProfile.final_email, "") != "",
        func.coalesce(GlobalInfluencerProfile.public_email, "") != "",
        func.coalesce(GlobalInfluencerProfile.business_email, "") != "",
        func.coalesce(GlobalInfluencerProfile.contact_page, "") != "",
        func.coalesce(GlobalInfluencerProfile.linktree_url, "") != "",
        func.coalesce(GlobalInfluencerProfile.whatsapp, "") != "",
        func.coalesce(GlobalInfluencerProfile.telegram, "") != "",
    )


def _website_valuable_sql():
    website = GlobalInfluencerProfile.website
    nonempty = func.coalesce(website, "") != ""
    context_or_metrics = or_(_influence_metrics_sql(), _profile_context_sql())
    return and_(
        nonempty,
        not_(_url_is_self_profile_sql(website)),
        or_(
            not_(_is_storefront_url_sql(website)),
            context_or_metrics,
        ),
    )


def _meaningful_other_social_links_sql():
    """存在非空且非自身 profile_url 的外链（与 Python _meaningful_external_links 一致）。"""
    links = func.coalesce(GlobalInfluencerProfile.other_social_links, _EMPTY_JSONB)
    link_elem = func.jsonb_array_elements(links).table_valued("value")
    link_url = func.coalesce(
        link_elem.c.value.op("->>")("url"),
        link_elem.c.value.op("->>")("href"),
        "",
    )
    return exists(
        select(1)
        .select_from(link_elem)
        .where(
            func.length(func.trim(link_url)) > 0,
            not_(_url_is_self_profile_sql(link_url)),
        )
    )


def global_profile_valuable_sql():
    """与 is_influencer_profile_valuable() 对齐的全局红人 SQL 有价值条件。"""
    context = _profile_context_sql()
    metrics = _influence_metrics_sql()
    return or_(
        _direct_contact_fields_sql(),
        _website_valuable_sql(),
        _meaningful_other_social_links_sql(),
        metrics,
        context,
    )
