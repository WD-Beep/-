# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：influencer
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, BeforeValidator, EmailStr, Field, HttpUrl, computed_field, field_validator, model_validator

from app.schemas.common import ORMModel, TimestampMixin


def _list_or_empty(value: Any) -> list:
    return value if isinstance(value, list) else []


def _empty_email_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _empty_optional_string_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


OptionalEmail = Annotated[EmailStr | None, BeforeValidator(_empty_email_to_none)]
OptionalUrl = Annotated[HttpUrl | str | None, BeforeValidator(_empty_optional_string_to_none)]


class InfluencerSourceRead(ORMModel):
    id: int
    source_post_url: str | None = None
    source_input_url: str | None = None
    source_platform: str | None = None
    task_id: int | None = None
    task_name: str | None = None
    import_batch_id: int | None = None
    collected_at: datetime


class InfluencerBase(BaseModel):
    platform: str = Field(..., max_length=50)
    username: str = Field(..., max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    profile_url: str = Field(..., max_length=1024)
    avatar_url: str | None = Field(default=None, max_length=1024)
    country: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    niche: str | None = Field(default=None, max_length=100)
    bio: str | None = None
    followers_count: int | None = Field(default=None, ge=0)
    avg_views: int | None = Field(default=None, ge=0)
    avg_likes: int | None = Field(default=None, ge=0)
    avg_comments: int | None = Field(default=None, ge=0)
    engagement_rate: float | None = Field(default=None, ge=0)
    email: OptionalEmail = None
    final_email: OptionalEmail = None
    public_email: OptionalEmail = None
    business_email: OptionalEmail = None
    email_source: str | None = Field(default=None, max_length=100)
    contact_credibility: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Legacy numeric mirror of contact_credibility_level; do not use for business rules.",
    )
    contact_score: float | None = Field(default=None, ge=0, le=100)
    contact_credibility_level: str | None = Field(
        default=None,
        max_length=20,
        description="Authoritative contact credibility: high/medium/low/unknown.",
    )
    website: OptionalUrl = None
    contact_page: OptionalUrl = None
    linktree_url: OptionalUrl = None
    whatsapp: str | None = Field(default=None, max_length=1024)
    telegram: str | None = Field(default=None, max_length=100)
    other_social_links: list[dict[str, str]] = Field(default_factory=list)
    product_fit: float | None = Field(default=None, ge=0, le=100)
    data_completeness: float | None = Field(default=None, ge=0, le=100)
    has_brand_collaboration: bool | None = None
    estimated_collab_price: str | None = Field(default=None, max_length=100)
    collaboration_formats: list[str] = Field(default_factory=list)
    content_topics: list[str] = Field(default_factory=list)
    audience_country: str | None = Field(default=None, max_length=100)
    audience_language: str | None = Field(default=None, max_length=50)
    travel_fit_score: float | None = Field(default=None, ge=0, le=100)
    purchasing_power_score: float | None = Field(default=None, ge=0, le=100)
    sales_potential_score: float | None = Field(default=None, ge=0, le=100)
    audience_match_score: float | None = Field(default=None, ge=0, le=100)
    roi_forecast: float | None = Field(default=None, ge=0)
    recent_post_titles: list[str] = Field(default_factory=list)
    recent_post_urls: list[str] = Field(default_factory=list)
    last_post_at: datetime | None = None
    posting_frequency: str | None = Field(default=None, max_length=50)
    tags: list[str] = Field(default_factory=list)
    engagement_score: float | None = Field(default=None, ge=0, le=100)
    content_match_score: float | None = Field(default=None, ge=0, le=100)
    contactability_score: float | None = Field(default=None, ge=0, le=100)
    commercial_signal_score: float | None = Field(default=None, ge=0, le=100)
    activity_score: float | None = Field(default=None, ge=0, le=100)
    risk_score: float | None = Field(default=None, ge=0, le=100)
    final_priority: str | None = Field(default=None, max_length=10)
    score: float | None = Field(default=None, ge=0, le=100)
    risk_level: str | None = Field(default=None, max_length=20)
    score_reason: str | None = None
    ai_summary: str | None = None
    ai_collaboration_suggestion: str | None = None
    ai_outreach_message: str | None = None
    follow_status: str | None = Field(default=None, max_length=50)
    owner: str | None = Field(default=None, max_length=100)
    note: str | None = None
    next_follow_up_at: datetime | None = None
    last_contacted_at: datetime | None = None
    last_reply_at: datetime | None = None
    invalid_reason: str | None = None
    blacklist_reason: str | None = None
    contact_discovered_at: datetime | None = None
    contact_sources: list[dict[str, Any]] = Field(default_factory=list)
    contact_fetch_status: str | None = Field(default=None, max_length=32)
    contact_fetch_error: str | None = None
    last_collected_at: datetime | None = None
    source_discovery_type: str | None = Field(default=None, max_length=32)
    source_post_url: str | None = Field(default=None, max_length=512)
    source_comment_url: str | None = Field(default=None, max_length=512)
    source_comment_text: str | None = None

    @field_validator(
        "other_social_links",
        "collaboration_formats",
        "content_topics",
        "recent_post_titles",
        "recent_post_urls",
        "tags",
        "contact_sources",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, value: Any) -> list:
        return _list_or_empty(value)

    @field_validator("profile_url", mode="before")
    @classmethod
    def normalize_profile_url_field(cls, value: Any) -> Any:
        from app.services.instagram_urls import normalize_instagram_profile_url

        if not value:
            return value
        text = str(value).strip()
        if "instagram.com" not in text.lower():
            return text
        return normalize_instagram_profile_url(text) or text

    @field_validator("source_post_url", "source_comment_url", mode="before")
    @classmethod
    def normalize_instagram_post_fields(cls, value: Any) -> Any:
        from app.services.instagram_urls import normalize_instagram_post_url, sanitize_url_text

        if not value:
            return value
        text = str(value)
        return normalize_instagram_post_url(text) or sanitize_url_text(text) or value

    @field_validator("recent_post_urls", mode="before")
    @classmethod
    def normalize_recent_post_urls(cls, value: Any) -> list:
        from app.services.instagram_urls import normalize_instagram_post_url, sanitize_url_text

        urls = _list_or_empty(value)
        normalized: list[str] = []
        for url in urls:
            if not isinstance(url, str):
                continue
            text = url.strip()
            if not text:
                continue
            lowered = text.lower()
            if "instagram.com" in lowered:
                post = normalize_instagram_post_url(text)
                if post:
                    normalized.append(post)
                continue
            cleaned = sanitize_url_text(text) or text
            if cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class InfluencerCreate(InfluencerBase):
    pass


class InfluencerUpdate(BaseModel):
    platform: str | None = Field(default=None, max_length=50)
    username: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    profile_url: str | None = Field(default=None, max_length=1024)
    avatar_url: str | None = Field(default=None, max_length=1024)
    country: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    niche: str | None = Field(default=None, max_length=100)
    bio: str | None = None
    followers_count: int | None = Field(default=None, ge=0)
    avg_views: int | None = Field(default=None, ge=0)
    avg_likes: int | None = Field(default=None, ge=0)
    avg_comments: int | None = Field(default=None, ge=0)
    engagement_rate: float | None = Field(default=None, ge=0)
    email: OptionalEmail = None
    final_email: OptionalEmail = None
    public_email: OptionalEmail = None
    business_email: OptionalEmail = None
    email_source: str | None = Field(default=None, max_length=100)
    contact_credibility: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Legacy numeric mirror of contact_credibility_level; do not use for business rules.",
    )
    contact_score: float | None = Field(default=None, ge=0, le=100)
    contact_credibility_level: str | None = Field(
        default=None,
        max_length=20,
        description="Authoritative contact credibility: high/medium/low/unknown.",
    )
    website: OptionalUrl = None
    contact_page: OptionalUrl = None
    linktree_url: OptionalUrl = None
    whatsapp: str | None = Field(default=None, max_length=1024)
    telegram: str | None = Field(default=None, max_length=100)
    other_social_links: list[dict[str, str]] | None = None
    product_fit: float | None = Field(default=None, ge=0, le=100)
    data_completeness: float | None = Field(default=None, ge=0, le=100)
    has_brand_collaboration: bool | None = None
    estimated_collab_price: str | None = Field(default=None, max_length=100)
    collaboration_formats: list[str] | None = None
    content_topics: list[str] | None = None
    audience_country: str | None = Field(default=None, max_length=100)
    audience_language: str | None = Field(default=None, max_length=50)
    travel_fit_score: float | None = Field(default=None, ge=0, le=100)
    purchasing_power_score: float | None = Field(default=None, ge=0, le=100)
    sales_potential_score: float | None = Field(default=None, ge=0, le=100)
    audience_match_score: float | None = Field(default=None, ge=0, le=100)
    roi_forecast: float | None = Field(default=None, ge=0)
    recent_post_titles: list[str] | None = None
    recent_post_urls: list[str] | None = None
    last_post_at: datetime | None = None
    posting_frequency: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    engagement_score: float | None = Field(default=None, ge=0, le=100)
    content_match_score: float | None = Field(default=None, ge=0, le=100)
    contactability_score: float | None = Field(default=None, ge=0, le=100)
    commercial_signal_score: float | None = Field(default=None, ge=0, le=100)
    activity_score: float | None = Field(default=None, ge=0, le=100)
    risk_score: float | None = Field(default=None, ge=0, le=100)
    final_priority: str | None = Field(default=None, max_length=10)
    score: float | None = Field(default=None, ge=0, le=100)
    risk_level: str | None = Field(default=None, max_length=20)
    score_reason: str | None = None
    ai_summary: str | None = None
    ai_collaboration_suggestion: str | None = None
    ai_outreach_message: str | None = None
    follow_status: str | None = Field(default=None, max_length=50)
    owner: str | None = Field(default=None, max_length=100)
    note: str | None = None
    next_follow_up_at: datetime | None = None
    last_contacted_at: datetime | None = None
    last_reply_at: datetime | None = None
    invalid_reason: str | None = None
    blacklist_reason: str | None = None
    last_collected_at: datetime | None = None
    email_sent: bool = False
    last_email_sent_at: datetime | None = None
    last_email_subject: str | None = None


class InfluencerRead(InfluencerBase, TimestampMixin, ORMModel):
    id: int
    source_records: list[InfluencerSourceRead] = Field(default_factory=list)
    email_sent: bool = False
    last_email_sent_at: datetime | None = None
    last_email_subject: str | None = None
    value_tier: Literal["direct_contact", "manual_research", "skip"] = "skip"
    value_tier_label: str = "暂时跳过"
    value_tier_reason: str = ""

    @model_validator(mode="after")
    def populate_value_tier_fields(self) -> Self:
        from app.services.value_tier import classify_value_tier

        tier, label, reason = classify_value_tier(self)
        self.value_tier = tier
        self.value_tier_label = label
        self.value_tier_reason = reason
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def contact_summary(self) -> str:
        from app.services.contact_signals import build_contact_summary

        return build_contact_summary(self)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_status(self) -> str | None:
        return self.follow_status

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_priority(self) -> str | None:
        return self.final_priority

    @computed_field  # type: ignore[prop-decorator]
    @property
    def owner_name(self) -> str | None:
        return self.owner

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_note(self) -> str | None:
        return self.note


class InfluencerFilter(BaseModel):
    platform: str | None = None
    country: str | None = None
    category: str | None = None
    niche: str | None = None
    tag: str | None = Field(
        default=None,
        description="Match product influencer tags (single tag)",
    )
    follow_status: str | None = None
    lead_status: str | None = None
    lead_priority: str | None = None
    owner_name: str | None = None
    source_discovery_type: str | None = None
    search: str | None = None
    min_score: float | None = Field(default=None, ge=0, le=100)
    min_product_fit: float | None = Field(default=None, ge=0, le=100)
    has_email: bool | None = None
    contactable: bool | None = None
    high_value: bool | None = None
    value_tier: str | None = Field(
        default=None,
        description="direct_contact | manual_research | skip",
    )
    high_match: bool | None = None
    today_recommended: bool | None = None
    pending_follow_up: bool | None = None
    unassigned: bool | None = None
    high_priority: bool | None = None
    missing_contact: bool | None = None
    high_credibility_contact: bool | None = None
    email_status: str | None = Field(
        default=None,
        description="sent | unsent — filter by successful email send history",
    )
    exclude_terminal_statuses: bool | None = Field(
        default=None,
        description="Exclude blacklisted, invalid, replied and active follow-up statuses",
    )
    collection_task_id: int | None = Field(default=None, ge=1)
    created_within_hours: int | None = Field(default=None, ge=1, le=720)
    collected_within_days: int | None = Field(default=None, ge=1, le=365)


class PlatformStatItem(BaseModel):
    platform: str
    total: int
    has_email: int
    direct_contact: int
    missing_contact: int
    high_value: int
    sent_email_count: int = 0
    unsent_email_count: int = 0


class PlatformStatsResponse(BaseModel):
    items: list[PlatformStatItem]


class InfluencerBulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class InfluencerBulkDeleteResponse(BaseModel):
    deleted_count: int
    deleted_ids: list[int] = Field(default_factory=list)
    missing_ids: list[int] = Field(default_factory=list)


class InfluencerExportFilter(InfluencerFilter):
    keyword: str | None = None

    def to_query_filter(self) -> InfluencerFilter:
        return InfluencerFilter(
            platform=self.platform,
            country=self.country,
            category=self.category,
            niche=self.niche,
            tag=self.tag,
            follow_status=self.follow_status,
            lead_status=self.lead_status,
            lead_priority=self.lead_priority,
            owner_name=self.owner_name,
            source_discovery_type=self.source_discovery_type,
            search=self.keyword or self.search,
            min_score=self.min_score,
            min_product_fit=self.min_product_fit,
            has_email=self.has_email,
            contactable=self.contactable,
            high_value=self.high_value,
            value_tier=self.value_tier,
            high_match=self.high_match,
            today_recommended=self.today_recommended,
            pending_follow_up=self.pending_follow_up,
            unassigned=self.unassigned,
            high_priority=self.high_priority,
            missing_contact=self.missing_contact,
            high_credibility_contact=self.high_credibility_contact,
            email_status=self.email_status,
            exclude_terminal_statuses=self.exclude_terminal_statuses,
            collection_task_id=self.collection_task_id,
            created_within_hours=self.created_within_hours,
            collected_within_days=self.collected_within_days,
        )
