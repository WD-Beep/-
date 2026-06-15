"""采集任务高价值评估：粉丝/互动/联系方式与入库门禁。"""

from __future__ import annotations

from dataclasses import dataclass

from app.collectors.base import CollectedInfluencer
from app.models.collection_task import CollectionTask
from app.services.collection_filters import (
    build_searchable_text,
    get_quality_preference_mismatch_reasons,
    required_min_followers_for_item,
    uses_discovery_hard_min_followers_for_item,
)
from app.services.contact_discovery import extract_emails_from_text
from app.services.platform_types import URL_ONLY_PLATFORMS
from app.services.contact_signals import (
    _has_email,
    _has_explicit_direct_channel,
    detect_external_link_contact_reason,
    detect_storefront_from_links,
    detect_storefront_from_urls,
)

CONTACT_PENDING_STATUSES = frozenset({None, "", "not_started", "pending"})
METRIC_QUALIFIED = "qualified"
METRIC_BELOW = "below"
METRIC_MISSING = "missing"
METRIC_NOT_REQUIRED = "not_required"
CONTACT_FOUND = "found"
CONTACT_MISSING = "missing"
CONTACT_PENDING = "pending"

REASON_LABELS: dict[str, str] = {
    "below_min_followers": "粉丝数低于门槛",
    "above_max_followers": "粉丝数超过上限",
    "below_min_engagement_rate": "互动率低于门槛",
    "missing_engagement_rate": "互动率数据缺失",
    "missing_include_keyword": "未命中偏好关键词",
    "missing_email": "未发现邮箱",
    "missing_contact": "未发现联系方式",
}


@dataclass(frozen=True)
class HighValueAssessment:
    is_high_value: bool
    has_email: bool
    has_contact: bool
    contact_status: str
    followers_status: str
    engagement_status: str
    mismatch_codes: tuple[str, ...]
    insert_blocked: bool
    insert_blocked_reason: str | None
    filter_reason: str | None
    filter_detail: str | None


def _normalize_keywords(keywords: list | None) -> list[str]:
    if not keywords:
        return []
    return [str(k).strip().lower() for k in keywords if k and str(k).strip()]


def _contact_discovery_pending(item: CollectedInfluencer) -> bool:
    status = getattr(item, "contact_fetch_status", None)
    if status not in CONTACT_PENDING_STATUSES:
        return False
    return not has_collection_contact_channel(item)


def has_collection_email(item: CollectedInfluencer) -> bool:
    if _has_email(item):
        return True
    bio = getattr(item, "bio", None)
    if bio and extract_emails_from_text(bio, "bio"):
        return True
    return False


def is_url_only_metrics_pending(item: CollectedInfluencer) -> bool:
    platform = (getattr(item, "platform", None) or "").strip().lower()
    if platform not in URL_ONLY_PLATFORMS:
        return False
    return item.followers_count is None and item.engagement_rate is None


def has_collection_contact_channel(item: CollectedInfluencer) -> bool:
    if has_collection_email(item):
        return True
    if _has_explicit_direct_channel(item):
        return True
    if detect_storefront_from_urls(item.website, item.profile_url):
        return True
    if detect_storefront_from_links(item.other_social_links):
        return True
    if detect_external_link_contact_reason(item.other_social_links):
        return True
    return False


def assess_contact(item: CollectedInfluencer) -> tuple[bool, bool, str]:
    has_email = has_collection_email(item)
    has_contact = has_collection_contact_channel(item)
    if has_email or has_contact:
        return has_email, has_contact, CONTACT_FOUND
    if _contact_discovery_pending(item):
        return False, False, CONTACT_PENDING
    return False, False, CONTACT_MISSING


def _followers_status(item: CollectedInfluencer, task: CollectionTask) -> tuple[str, str | None]:
    followers = item.followers_count
    required_min = required_min_followers_for_item(item, task)
    if task.min_followers_count is not None and not uses_discovery_hard_min_followers_for_item(item, task):
        required_min = task.min_followers_count
    if required_min is not None:
        if followers is None:
            return METRIC_MISSING, "below_min_followers"
        if followers < required_min:
            return METRIC_BELOW, "below_min_followers"
    if task.max_followers_count is not None:
        if followers is None:
            return METRIC_MISSING, None
        if followers > task.max_followers_count:
            return METRIC_BELOW, "above_max_followers"
    if followers is None and task.min_followers_count is not None:
        return METRIC_MISSING, "below_min_followers"
    return METRIC_QUALIFIED, None


def _engagement_status(item: CollectedInfluencer, task: CollectionTask) -> tuple[str, str | None]:
    if task.min_engagement_rate is None:
        return METRIC_NOT_REQUIRED, None
    rate = item.engagement_rate
    if rate is None:
        return METRIC_MISSING, "missing_engagement_rate"
    if rate < task.min_engagement_rate:
        return METRIC_BELOW, "below_min_engagement_rate"
    return METRIC_QUALIFIED, None


def _include_keyword_status(item: CollectedInfluencer, task: CollectionTask) -> str | None:
    include_keywords = _normalize_keywords(task.filter_include_keywords)
    if not include_keywords:
        return None
    searchable = build_searchable_text(item)
    if not any(kw in searchable for kw in include_keywords):
        return "missing_include_keyword"
    return None


def _primary_reason(codes: list[str]) -> str | None:
    priority = (
        "below_min_followers",
        "above_max_followers",
        "below_min_engagement_rate",
        "missing_engagement_rate",
        "missing_email",
        "missing_contact",
        "missing_include_keyword",
    )
    for code in priority:
        if code in codes:
            return code
    return codes[0] if codes else None


def _detail_for_reason(
    reason: str | None,
    *,
    task: CollectionTask,
    item: CollectedInfluencer,
) -> str | None:
    if not reason:
        return None
    if reason == "below_min_followers":
        required = required_min_followers_for_item(item, task)
        if required is None and task.min_followers_count is not None:
            required = task.min_followers_count
        followers = item.followers_count
        if followers is None:
            if required is not None:
                return f"粉丝数未知，无法验证最低门槛（需 ≥{required:,}）"
            return "粉丝数未知，无法验证最低门槛"
        if required is not None:
            return f"粉丝数 {followers:,}，低于最低要求 {required:,}"
        return f"粉丝数 {followers:,}，低于最低粉丝门槛"
    if reason == "above_max_followers" and task.max_followers_count is not None:
        followers = item.followers_count
        if followers is not None:
            return f"粉丝数 {followers:,}，超过上限 {task.max_followers_count:,}"
        return "粉丝数未知，无法验证上限"
    if reason == "below_min_engagement_rate" and task.min_engagement_rate is not None:
        rate = item.engagement_rate
        if rate is not None:
            return f"互动率 {rate:.2f}%，低于最低要求 {task.min_engagement_rate:.2f}%"
        return "互动率未知，无法验证最低门槛"
    if reason == "missing_engagement_rate":
        return "缺少互动率数据，无法判定是否达标"
    if reason == "missing_email":
        return "未发现邮箱"
    if reason == "missing_contact":
        return "未发现邮箱或可联系入口"
    if reason == "missing_include_keyword":
        return "简介/内容未命中偏好关键词"
    return REASON_LABELS.get(reason, reason)


def evaluate_high_value_assessment(item: CollectedInfluencer, task: CollectionTask) -> HighValueAssessment:
    mismatch_codes: list[str] = list(get_quality_preference_mismatch_reasons(item, task))
    has_email, has_contact, contact_status = assess_contact(item)
    followers_status, followers_code = _followers_status(item, task)
    engagement_status, engagement_code = _engagement_status(item, task)

    if followers_code and followers_code not in mismatch_codes:
        mismatch_codes.append(followers_code)
    if engagement_code and engagement_code not in mismatch_codes:
        mismatch_codes.append(engagement_code)

    include_code = _include_keyword_status(item, task)
    if include_code and include_code not in mismatch_codes:
        mismatch_codes.append(include_code)

    if getattr(task, "require_email", False):
        if contact_status == CONTACT_PENDING:
            pass
        elif not has_email:
            if "missing_email" not in mismatch_codes:
                mismatch_codes.append("missing_email")

    if getattr(task, "require_contact", False):
        if contact_status == CONTACT_PENDING:
            pass
        elif not has_contact:
            if "missing_contact" not in mismatch_codes:
                mismatch_codes.append("missing_contact")

    pending = contact_status == CONTACT_PENDING and (
        getattr(task, "require_email", False) or getattr(task, "require_contact", False)
    )
    blocking_codes = [
        code
        for code in mismatch_codes
        if code not in {"missing_email", "missing_contact"} or contact_status != CONTACT_PENDING
    ]
    insert_blocked = bool(blocking_codes) and not pending
    primary = _primary_reason(blocking_codes if insert_blocked else mismatch_codes)
    insert_blocked_reason = _detail_for_reason(primary, task=task, item=item) if insert_blocked else None
    filter_reason = primary if insert_blocked else None
    filter_detail = insert_blocked_reason

    is_high_value = not mismatch_codes and not pending
    if pending:
        is_high_value = False
    if is_url_only_metrics_pending(item):
        is_high_value = False

    return HighValueAssessment(
        is_high_value=is_high_value,
        has_email=has_email,
        has_contact=has_contact,
        contact_status=contact_status,
        followers_status=followers_status,
        engagement_status=engagement_status,
        mismatch_codes=tuple(mismatch_codes),
        insert_blocked=insert_blocked,
        insert_blocked_reason=insert_blocked_reason,
        filter_reason=filter_reason,
        filter_detail=filter_detail,
    )


def assessment_row_fields(assessment: HighValueAssessment) -> dict:
    return {
        "is_high_value": assessment.is_high_value,
        "has_email": assessment.has_email,
        "has_contact": assessment.has_contact,
        "contact_status": assessment.contact_status,
        "insert_blocked_reason": assessment.insert_blocked_reason,
    }


def should_strict_filter_out(task: CollectionTask, assessment: HighValueAssessment) -> bool:
    if not getattr(task, "strict_quality_filter", False):
        return False
    if assessment.contact_status == CONTACT_PENDING:
        pending_only = not assessment.mismatch_codes or all(
            code in {"missing_email", "missing_contact"} for code in assessment.mismatch_codes
        )
        if pending_only:
            return False
    return assessment.insert_blocked


def should_skip_insert(task: CollectionTask, assessment: HighValueAssessment) -> bool:
    if not getattr(task, "insert_qualified_only", False):
        return False
    if getattr(task, "strict_quality_filter", False):
        return False
    if assessment.contact_status == CONTACT_PENDING:
        return False
    return assessment.insert_blocked


def task_has_quality_gates(task: CollectionTask) -> bool:
    return any(
        [
            task.min_followers_count is not None,
            task.max_followers_count is not None,
            task.min_engagement_rate is not None,
            bool(task.filter_include_keywords),
            getattr(task, "require_email", False),
            getattr(task, "require_contact", False),
            getattr(task, "insert_qualified_only", False),
            getattr(task, "strict_quality_filter", False),
        ]
    )
