# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：influencer persistence
"""全局红人资料 + 产品维度业务记录：去重与入库。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task import CollectionTask
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.services.business_quality import apply_creator_quality
from app.collectors.base import CollectedInfluencer
from app.services.platform_utils import normalize_profile_url, platform_identity_key
from app.services.scoring import calculate_risk_level, calculate_score

GLOBAL_PROFILE_STALE_DAYS = 7
GLOBAL_URL_FIELD_MAX_LENGTH = 1024
PRODUCT_SOURCE_URL_FIELD_MAX_LENGTH = 512
PRODUCT_SOURCE_TYPE_MAX_LENGTH = 32


def normalize_username(username: str | None) -> str:
    return (username or "").strip().lower().lstrip("@")


def identity_key_for_item(item: CollectedInfluencer) -> tuple[str, str]:
    return platform_identity_key(
        item.platform,
        item.profile_url,
        platform_unique_id=getattr(item, "platform_unique_id", None),
    )


def should_refresh_global_profile(profile: GlobalInfluencerProfile, *, now: datetime | None = None) -> bool:
    reference = profile.profile_refreshed_at or profile.updated_at or profile.created_at
    if reference is None:
        return True
    current = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return current - reference.astimezone(UTC) > timedelta(days=GLOBAL_PROFILE_STALE_DAYS)


def _limit_text(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[:max_length]


def clamp_collected_influencer_db_fields(data: CollectedInfluencer) -> None:
    for field in (
        "profile_url",
        "avatar_url",
        "website",
        "contact_page",
        "linktree_url",
        "whatsapp",
    ):
        setattr(data, field, _limit_text(getattr(data, field, None), GLOBAL_URL_FIELD_MAX_LENGTH))
    data.source_post_url = _limit_text(data.source_post_url, PRODUCT_SOURCE_URL_FIELD_MAX_LENGTH)
    data.source_comment_url = _limit_text(data.source_comment_url, PRODUCT_SOURCE_URL_FIELD_MAX_LENGTH)
    data.source_input_url = _limit_text(data.source_input_url, PRODUCT_SOURCE_URL_FIELD_MAX_LENGTH)
    data.source_discovery_type = _limit_text(data.source_discovery_type, PRODUCT_SOURCE_TYPE_MAX_LENGTH)


def apply_global_profile_data(
    profile: GlobalInfluencerProfile,
    data: CollectedInfluencer,
    *,
    run_at: datetime,
) -> None:
    clamp_collected_influencer_db_fields(data)
    profile.username = data.username
    profile.normalized_username = normalize_username(data.username)
    profile.display_name = getattr(data, "display_name", None)
    profile.profile_url = data.profile_url
    profile.normalized_profile_url = normalize_profile_url(data.profile_url)
    if getattr(data, "platform_unique_id", None):
        profile.platform_unique_id = data.platform_unique_id
    profile.avatar_url = getattr(data, "avatar_url", None)
    profile.country = data.country
    profile.language = data.language
    profile.category = data.category
    profile.niche = data.niche
    profile.bio = data.bio
    profile.followers_count = data.followers_count
    profile.avg_views = data.avg_views
    profile.avg_likes = data.avg_likes
    profile.avg_comments = data.avg_comments
    profile.engagement_rate = data.engagement_rate
    profile.email = data.final_email or data.email
    profile.final_email = data.final_email or data.email
    profile.public_email = data.public_email
    profile.business_email = data.business_email
    profile.email_source = data.email_source
    profile.contact_credibility = data.contact_credibility
    profile.contact_score = data.contact_score
    profile.contact_credibility_level = getattr(data, "contact_credibility_level", None)
    profile.website = data.website
    profile.contact_page = data.contact_page
    profile.linktree_url = data.linktree_url
    profile.whatsapp = data.whatsapp
    profile.telegram = data.telegram
    profile.other_social_links = data.other_social_links or []
    profile.contact_discovered_at = getattr(data, "contact_discovered_at", None)
    profile.contact_sources = getattr(data, "contact_sources", None) or []
    profile.contact_fetch_status = getattr(data, "contact_fetch_status", None)
    profile.contact_fetch_error = getattr(data, "contact_fetch_error", None)
    profile.data_completeness = data.data_completeness
    profile.has_brand_collaboration = data.has_brand_collaboration
    profile.estimated_collab_price = data.estimated_collab_price
    profile.collaboration_formats = data.collaboration_formats or []
    profile.content_topics = data.content_topics or []
    profile.audience_country = data.audience_country
    profile.audience_language = data.audience_language
    profile.recent_post_titles = data.recent_post_titles or []
    profile.recent_post_urls = data.recent_post_urls or []
    profile.last_post_at = data.last_post_at
    profile.posting_frequency = data.posting_frequency
    profile.profile_refreshed_at = run_at


def create_global_profile_from_collected(data: CollectedInfluencer, *, run_at: datetime) -> GlobalInfluencerProfile:
    profile = GlobalInfluencerProfile(
        platform=data.platform,
        platform_unique_id=data.platform_unique_id,
        username=data.username,
        normalized_username=normalize_username(data.username),
        profile_url=data.profile_url,
        normalized_profile_url=normalize_profile_url(data.profile_url),
    )
    apply_global_profile_data(profile, data, run_at=run_at)
    return profile


def apply_product_influencer_data(
    record: ProductInfluencer,
    data: CollectedInfluencer,
    task: CollectionTask | None,
    *,
    run_at: datetime,
) -> None:
    clamp_collected_influencer_db_fields(data)
    apply_creator_quality(data, task)
    score = data.score if data.score is not None else calculate_score(data, task)
    risk_level = data.risk_level or calculate_risk_level(score)
    record.product_fit = data.product_fit
    record.engagement_score = data.engagement_score
    record.content_match_score = data.content_match_score
    record.contactability_score = data.contactability_score
    record.commercial_signal_score = data.commercial_signal_score
    record.activity_score = data.activity_score
    record.risk_score = data.risk_score
    record.travel_fit_score = data.travel_fit_score
    record.purchasing_power_score = data.purchasing_power_score
    record.sales_potential_score = data.sales_potential_score
    record.audience_match_score = data.audience_match_score
    record.roi_forecast = data.roi_forecast
    record.final_priority = data.final_priority
    record.score = score
    record.risk_level = risk_level
    record.tags = data.tags
    record.last_collected_at = run_at
    record.is_inserted = True
    if data.source_discovery_type:
        record.source_discovery_type = data.source_discovery_type
    if data.source_post_url:
        record.source_post_url = data.source_post_url
    if data.source_comment_url:
        record.source_comment_url = data.source_comment_url
    if data.source_comment_text:
        record.source_comment_text = data.source_comment_text
    if record.first_inserted_at is None:
        record.first_inserted_at = run_at


def create_product_influencer_from_collected(
    *,
    product_id: int,
    global_profile: GlobalInfluencerProfile,
    data: CollectedInfluencer,
    task: CollectionTask | None,
    run_at: datetime,
) -> ProductInfluencer:
    record = ProductInfluencer(
        product_id=product_id,
        global_influencer_id=global_profile.id,
        follow_status="new",
    )
    apply_product_influencer_data(record, data, task, run_at=run_at)
    return record


def product_record_has_changes(
    record: ProductInfluencer,
    data: CollectedInfluencer,
    task: CollectionTask | None,
) -> bool:
    apply_creator_quality(data, task)
    score = calculate_score(data, task)
    risk_level = calculate_risk_level(score)
    comparisons = {
        "product_fit": data.product_fit,
        "travel_fit_score": data.travel_fit_score,
        "purchasing_power_score": data.purchasing_power_score,
        "sales_potential_score": data.sales_potential_score,
        "audience_match_score": data.audience_match_score,
        "roi_forecast": data.roi_forecast,
        "score": score,
        "risk_level": risk_level,
    }
    for field, new_value in comparisons.items():
        if getattr(record, field) != new_value:
            return True
    return False


def global_profile_has_changes(profile: GlobalInfluencerProfile, data: CollectedInfluencer) -> bool:
    comparisons = {
        "username": data.username,
        "display_name": data.display_name,
        "bio": data.bio,
        "followers_count": data.followers_count,
        "engagement_rate": data.engagement_rate,
        "final_email": data.final_email or data.email,
        "website": data.website,
    }
    for field, new_value in comparisons.items():
        if getattr(profile, field) != new_value:
            return True
    return False


class InfluencerPersistenceService:
    @staticmethod
    async def find_global_profiles_batch(
        db: AsyncSession,
        items: list[CollectedInfluencer],
    ) -> dict[tuple[str, str], GlobalInfluencerProfile]:
        if not items:
            return {}
        result_map: dict[tuple[str, str], GlobalInfluencerProfile] = {}

        youtube_ids = {
            item.platform_unique_id
            for item in items
            if getattr(item, "platform", None) == "youtube" and getattr(item, "platform_unique_id", None)
        }
        if youtube_ids:
            rows = await db.execute(
                select(GlobalInfluencerProfile).where(
                    GlobalInfluencerProfile.platform == "youtube",
                    GlobalInfluencerProfile.platform_unique_id.in_(youtube_ids),
                )
            )
            for row in rows.scalars():
                key = platform_identity_key(
                    row.platform,
                    row.profile_url,
                    platform_unique_id=row.platform_unique_id,
                )
                result_map[key] = row

        platforms = {item.platform for item in items}
        normalized_urls = {normalize_profile_url(item.profile_url) for item in items}
        rows = await db.execute(
            select(GlobalInfluencerProfile).where(
                GlobalInfluencerProfile.platform.in_(platforms),
                GlobalInfluencerProfile.normalized_profile_url.in_(normalized_urls),
            )
        )
        for row in rows.scalars():
            key = platform_identity_key(
                row.platform,
                row.profile_url,
                platform_unique_id=row.platform_unique_id,
            )
            if key not in result_map:
                result_map[key] = row

        usernames = {
            normalize_username(item.username)
            for item in items
            if normalize_username(item.username)
        }
        if usernames:
            rows = await db.execute(
                select(GlobalInfluencerProfile).where(
                    GlobalInfluencerProfile.platform.in_(platforms),
                    GlobalInfluencerProfile.normalized_username.in_(usernames),
                )
            )
            username_by_platform: dict[tuple[str, str], GlobalInfluencerProfile] = {}
            for row in rows.scalars():
                username_by_platform[(row.platform, row.normalized_username)] = row
            for item in items:
                normalized = normalize_username(item.username)
                if not normalized:
                    continue
                key = identity_key_for_item(item)
                if key in result_map:
                    continue
                fallback = username_by_platform.get((item.platform, normalized))
                if fallback:
                    result_map[key] = fallback
        return result_map

    @staticmethod
    async def find_product_influencers_batch(
        db: AsyncSession,
        product_id: int,
        items: list[CollectedInfluencer],
        *,
        global_map: dict[tuple[str, str], GlobalInfluencerProfile] | None = None,
    ) -> dict[tuple[str, str], ProductInfluencer]:
        if not items:
            return {}
        global_map = global_map or await InfluencerPersistenceService.find_global_profiles_batch(db, items)
        global_ids = {profile.id for profile in global_map.values()}
        if not global_ids:
            return {}

        rows = await db.execute(
            select(ProductInfluencer).where(
                ProductInfluencer.product_id == product_id,
                ProductInfluencer.global_influencer_id.in_(global_ids),
            )
        )
        by_global_id = {row.global_influencer_id: row for row in rows.scalars()}
        result: dict[tuple[str, str], ProductInfluencer] = {}
        for item in items:
            key = identity_key_for_item(item)
            global_profile = global_map.get(key)
            if global_profile and global_profile.id in by_global_id:
                result[key] = by_global_id[global_profile.id]
        return result
