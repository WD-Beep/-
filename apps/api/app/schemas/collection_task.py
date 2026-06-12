from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import CollectionMode, CollectionTaskStatus
from app.schemas.common import ORMModel, TimestampMixin


def _list_or_empty(value: Any) -> list:
    return value if isinstance(value, list) else []


SUPPORTED_TASK_PLATFORMS = {
    "instagram",
    "tiktok",
    "youtube",
    "facebook",
    "pinterest",
    "ltk",
    "shopmy",
}
SUPPORTED_TASK_PLATFORM_LABEL = ", ".join(sorted(SUPPORTED_TASK_PLATFORMS))
ALLOWED_PLATFORM_FIELD_VALUES = SUPPORTED_TASK_PLATFORMS | {"multi"}


def normalize_platform_list(platforms: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in platforms or []:
        name = (item or "").strip().lower()
        if name not in SUPPORTED_TASK_PLATFORMS:
            raise ValueError(
                f"不支持的平台: {item}，当前支持: {SUPPORTED_TASK_PLATFORM_LABEL}"
            )
        if name not in normalized:
            normalized.append(name)
    return normalized


def resolve_task_platform_fields(
    platform: str | None,
    platforms: list[str] | None,
    *,
    require_platforms: bool = True,
) -> tuple[str, list[str]]:
    normalized = normalize_platform_list(platforms)
    if not normalized and platform:
        legacy = (platform or "").strip().lower()
        if legacy in SUPPORTED_TASK_PLATFORMS:
            normalized = [legacy]
    if not normalized and require_platforms:
        raise ValueError("至少选择一个采集平台")
    if not normalized:
        return (platform or "instagram").strip().lower(), []
    resolved_platform = normalized[0] if len(normalized) == 1 else "multi"
    return resolved_platform, normalized


def validate_platform_field(value: str | None) -> str:
    name = (value or "").strip().lower()
    if name in ALLOWED_PLATFORM_FIELD_VALUES:
        return name
    raise ValueError(
        f"不支持的平台: {value}，当前支持: {SUPPORTED_TASK_PLATFORM_LABEL}, multi"
    )


class CollectionTaskBase(BaseModel):
    user_id: int | None = None
    workspace_id: int | None = None
    product_id: int | None = None
    name: str = Field(..., max_length=255)
    collection_mode: CollectionMode = CollectionMode.KEYWORD
    platform: str = Field(..., max_length=50)
    platforms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    input_urls: list[str] = Field(default_factory=list)
    country: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    discovery_limit: int | None = Field(default=100, ge=1, le=500)
    min_engagement_rate: float | None = Field(default=2.0, ge=0, le=100)
    min_followers_count: int | None = Field(default=50000, ge=0)
    max_followers_count: int | None = Field(default=None, ge=0)
    filter_include_keywords: list[str] = Field(default_factory=list)
    filter_exclude_keywords: list[str] = Field(default_factory=list)
    comment_discovery_enabled: bool = False
    status: CollectionTaskStatus = CollectionTaskStatus.DRAFT
    schedule_enabled: bool = False
    schedule_cron: str | None = Field(default=None, max_length=100)
    email_enabled: bool = False
    email_recipients: list[EmailStr] = Field(default_factory=list)
    outreach_enabled: bool = False
    outreach_provider: str = Field(default="smtp", max_length=50)
    outreach_dry_run: bool = True
    outreach_templates: dict[str, str] = Field(default_factory=dict)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    result_count: int = Field(default=0, ge=0)
    email_count: int = Field(default=0, ge=0)
    missing_contact_count: int = Field(default=0, ge=0)
    discovered_count: int = Field(default=0, ge=0)
    deduped_count: int = Field(default=0, ge=0)
    profile_fetched_count: int = Field(default=0, ge=0)
    profile_failed_count: int = Field(default=0, ge=0)
    filtered_out_count: int = Field(default=0, ge=0)
    inserted_count: int = Field(default=0, ge=0)
    hashtag_count: int = Field(default=0, ge=0)
    post_count: int = Field(default=0, ge=0)
    comment_author_count: int = Field(default=0, ge=0)
    filtered_below_min_followers_count: int = Field(default=0, ge=0)
    filtered_excluded_keyword_count: int = Field(default=0, ge=0)
    processed_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    total_estimate: int = Field(default=0, ge=0)
    current_stage: str | None = None
    last_error: str | None = None
    run_checkpoint: dict[str, Any] = Field(default_factory=dict)
    status_summary: str | None = None
    error_message: str | None = None

    @field_validator("keywords", "input_urls", "email_recipients", "filter_include_keywords", "filter_exclude_keywords", "platforms", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> list:
        return _list_or_empty(value)

    @model_validator(mode="after")
    def validate_follower_range(self) -> "CollectionTaskBase":
        self.platform, self.platforms = resolve_task_platform_fields(self.platform, self.platforms)
        if (
            self.min_followers_count is not None
            and self.max_followers_count is not None
            and self.min_followers_count > self.max_followers_count
        ):
            raise ValueError("最低粉丝数不能大于最高粉丝数")
        self.filter_include_keywords = [k.strip() for k in self.filter_include_keywords if k and k.strip()]
        self.filter_exclude_keywords = [k.strip() for k in self.filter_exclude_keywords if k and k.strip()]
        return self


class CollectionTaskCreate(BaseModel):
    name: str = Field(..., max_length=255)
    collection_mode: CollectionMode = CollectionMode.KEYWORD
    platform: str = Field(default="instagram", max_length=50)
    platforms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    input_urls: list[str] = Field(default_factory=list)
    country: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    discovery_limit: int | None = Field(default=100, ge=1, le=500)
    min_engagement_rate: float | None = Field(default=2.0, ge=0, le=100)
    min_followers_count: int | None = Field(default=50000, ge=0)
    max_followers_count: int | None = Field(default=None, ge=0)
    filter_include_keywords: list[str] = Field(default_factory=list)
    filter_exclude_keywords: list[str] = Field(default_factory=list)
    comment_discovery_enabled: bool = False
    status: CollectionTaskStatus = CollectionTaskStatus.DRAFT
    schedule_enabled: bool = False
    schedule_cron: str | None = Field(default=None, max_length=100)
    email_enabled: bool = False
    email_recipients: list[EmailStr] = Field(default_factory=list)
    outreach_enabled: bool = False
    outreach_provider: str = Field(default="smtp", max_length=50)
    outreach_dry_run: bool = True
    outreach_templates: dict[str, str] = Field(default_factory=dict)

    @field_validator("keywords", "input_urls", "email_recipients", "filter_include_keywords", "filter_exclude_keywords", "platforms", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> list:
        return _list_or_empty(value)

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str) -> str:
        return validate_platform_field(value)

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, value: list[str]) -> list[str]:
        return normalize_platform_list(value)

    @model_validator(mode="after")
    def normalize_platform_fields(self) -> "CollectionTaskCreate":
        self.platform, self.platforms = resolve_task_platform_fields(self.platform, self.platforms)
        return self

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "CollectionTaskCreate":
        keywords = [k.strip() for k in self.keywords if k and k.strip()]
        urls = [u.strip() for u in self.input_urls if u and u.strip()]
        self.keywords = keywords
        self.input_urls = urls

        if self.collection_mode in (CollectionMode.KEYWORD, CollectionMode.DISCOVERY) and not keywords:
            raise ValueError("关键词采集模式至少需要一个关键词")
        if self.collection_mode == CollectionMode.CATEGORY_DISCOVERY:
            if not (self.category or "").strip():
                raise ValueError("类目采集模式必须填写类目")
        if self.collection_mode in (
            CollectionMode.URLS,
            CollectionMode.CLUSTERING,
            CollectionMode.COMMENT_AUTHORS,
        ) and not urls:
            raise ValueError("请至少填写一个平台主页/帖子/Reel 链接")
        if self.collection_mode == CollectionMode.MIXED and not keywords and not urls:
            raise ValueError("混合模式需要填写关键词或链接至少一项")
        if self.collection_mode == CollectionMode.COMPETITOR_PRODUCT and not keywords and not urls:
            raise ValueError("竞品商品发现需填写 Amazon 链接、ASIN 或商品关键词")
        if self.collection_mode == CollectionMode.COMPETITOR_PRODUCT:
            self.comment_discovery_enabled = False
        if self.email_enabled and not self.email_recipients:
            raise ValueError("启用邮件发送时请填写收件人邮箱")
        if (
            self.min_followers_count is not None
            and self.max_followers_count is not None
            and self.min_followers_count > self.max_followers_count
        ):
            raise ValueError("最低粉丝数不能大于最高粉丝数")
        self.filter_include_keywords = [k.strip() for k in self.filter_include_keywords if k and k.strip()]
        self.filter_exclude_keywords = [k.strip() for k in self.filter_exclude_keywords if k and k.strip()]
        return self


class CollectionTaskUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    collection_mode: CollectionMode | None = None
    platform: str | None = Field(default=None, max_length=50)
    platforms: list[str] | None = None

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_platform_field(value)

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = normalize_platform_list(value)
        if not normalized:
            raise ValueError("至少选择一个采集平台")
        return normalized
    keywords: list[str] | None = None
    input_urls: list[str] | None = None
    country: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    discovery_limit: int | None = Field(default=None, ge=1, le=500)
    min_engagement_rate: float | None = Field(default=None, ge=0, le=100)
    min_followers_count: int | None = Field(default=None, ge=0)
    max_followers_count: int | None = Field(default=None, ge=0)
    filter_include_keywords: list[str] | None = None
    filter_exclude_keywords: list[str] | None = None
    comment_discovery_enabled: bool | None = None
    status: CollectionTaskStatus | None = None
    schedule_enabled: bool | None = None
    schedule_cron: str | None = Field(default=None, max_length=100)
    email_enabled: bool | None = None
    email_recipients: list[EmailStr] | None = None
    outreach_enabled: bool | None = None
    outreach_provider: str | None = Field(default=None, max_length=50)
    outreach_dry_run: bool | None = None
    outreach_templates: dict[str, str] | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    result_count: int | None = Field(default=None, ge=0)
    email_count: int | None = Field(default=None, ge=0)
    missing_contact_count: int | None = Field(default=None, ge=0)
    error_message: str | None = None

    @field_validator("keywords", "input_urls", "email_recipients", "filter_include_keywords", "filter_exclude_keywords", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> list | None:
        if value is None:
            return None
        return _list_or_empty(value)

    @model_validator(mode="after")
    def normalize_platform_fields(self) -> "CollectionTaskUpdate":
        if self.platforms is not None:
            self.platform, self.platforms = resolve_task_platform_fields(
                self.platform,
                self.platforms,
            )
        elif self.platform is not None:
            self.platform, self.platforms = resolve_task_platform_fields(
                self.platform,
                None,
            )
        if (
            self.min_followers_count is not None
            and self.max_followers_count is not None
            and self.min_followers_count > self.max_followers_count
        ):
            raise ValueError("最低粉丝数不能大于最高粉丝数")
        for field_name in ("filter_include_keywords", "filter_exclude_keywords"):
            value = getattr(self, field_name)
            if value is not None:
                setattr(self, field_name, [k.strip() for k in value if k and k.strip()])
        return self


class CollectionTaskRead(CollectionTaskBase, TimestampMixin, ORMModel):
    id: int
    stale: bool = False
    recoverable: bool = False
    stale_after_seconds: int = Field(default=0, ge=0)


class CollectionTaskFilter(BaseModel):
    product_id: int | None = None
    platform: str | None = None
    status: CollectionTaskStatus | None = None
    search: str | None = None


class CollectionRunResult(BaseModel):
    task_id: int
    new_count: int
    updated_count: int
    skipped_count: int
    filtered_count: int = 0
    total_count: int
    discovered_count: int = 0
    deduped_count: int = 0
    profile_fetched_count: int = 0
    profile_failed_count: int = 0
    filtered_out_count: int = 0
    inserted_count: int = 0
    hashtag_count: int = 0
    post_count: int = 0
    comment_author_count: int = 0
    filtered_below_min_followers_count: int = 0
    filtered_excluded_keyword_count: int = 0
    email_count: int = 0
    missing_contact_count: int = 0
    status_summary: str | None = None
    status: CollectionTaskStatus


class CollectionTaskCandidateFilter(BaseModel):
    status: str | None = None
    failure_reason: str | None = None
    source_type: str | None = None
    source_discovery_type: str | None = None
    search: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class CollectionTaskCandidateRead(ORMModel):
    id: int
    task_id: int
    username: str
    profile_url: str
    platform: str = "instagram"
    source_type: str | None = None
    source_keyword: str | None = None
    source_hashtag: str | None = None
    source_post_url: str | None = None
    source_caption: str | None = None
    source_comment_url: str | None = None
    source_comment_text: str | None = None
    source_discovery_type: str | None = None
    source_meta: dict | None = None
    followers_count: int | None = None
    engagement_rate: float | None = None
    profile_fetched_at: datetime | None = None
    influencer_id: int | None = None
    status: str
    failure_reason: str | None = None
    failure_detail: str | None = None
    run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
