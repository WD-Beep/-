from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import CollectionMode, CollectionTaskStatus
from app.schemas.common import ORMModel, TimestampMixin


from app.services.platform_types import KEYWORD_DISCOVERY_PLATFORMS, URL_ONLY_PLATFORMS

KEYWORD_SEED_PLATFORMS = frozenset({"pinterest", "shopmy"})
from app.services.url_parser import split_link_import_entries, validate_link_import_url_lines


COMPETITOR_DISCOVERY_PLATFORMS: tuple[str, ...] = ("instagram", "youtube", "tiktok", "facebook")


def build_link_import_task_fields(valid: list[dict[str, str]]) -> dict[str, Any]:
    """Build collection-task fields from validated link-import URL entries."""
    from app.services.competitor_product_discovery import (
        competitor_product_max_search_keywords,
        filter_competitor_phrase_keywords,
    )

    amazon_entries, profile_entries = split_link_import_entries(valid)
    if amazon_entries:
        keywords: list[str] = []
        max_kw = competitor_product_max_search_keywords()
        for entry in amazon_entries:
            asin = entry.get("asin")
            if asin and asin not in keywords:
                keywords.append(asin)
            for kw in entry.get("search_keywords") or entry.get("strong_keywords") or []:
                token = str(kw).strip()
                if token and token not in keywords:
                    keywords.append(token)
        keywords = filter_competitor_phrase_keywords(keywords)[:max_kw]
        seeds = [
            {
                "url": entry.get("url") or entry["normalized_url"],
                "normalized_url": entry["normalized_url"],
                "platform": "amazon",
                "asin": entry.get("asin", ""),
                "marketplace": entry.get("marketplace", ""),
                "source_type": "amazon_product",
                "product_keywords": list(entry.get("product_keywords") or []),
                "strong_keywords": list(entry.get("strong_keywords") or []),
                "weak_keywords": list(entry.get("weak_keywords") or []),
                "negative_keywords": list(entry.get("negative_keywords") or []),
                "search_keywords": list(entry.get("search_keywords") or []),
                "exact_phrases": list(entry.get("exact_phrases") or []),
                "variant_attributes": list(entry.get("variant_attributes") or []),
                "broad_category_keywords": list(entry.get("broad_category_keywords") or []),
                "product_videos": list(entry.get("product_videos") or []),
                "title_slug": entry.get("title_slug"),
                "product_title": entry.get("product_title"),
                "brand": entry.get("brand"),
                "product_category": entry.get("product_category"),
                "require_brand_match": entry.get("require_brand_match"),
            }
            for entry in amazon_entries
        ]
        discovery_platforms = list(COMPETITOR_DISCOVERY_PLATFORMS)
        return {
            "collection_mode": CollectionMode.COMPETITOR_PRODUCT,
            "platform": "multi",
            "platforms": discovery_platforms,
            "input_urls": [entry["normalized_url"] for entry in amazon_entries],
            "keywords": keywords,
            "comment_discovery_enabled": False,
            "run_checkpoint": {
                "amazon_product_seeds": seeds,
                "link_import_source": True,
                "competitor_discovery_platforms": discovery_platforms,
            },
        }

    inferred = list(dict.fromkeys(entry["platform"] for entry in profile_entries))
    return {
        "collection_mode": CollectionMode.LINK_IMPORT,
        "platforms": inferred,
        "platform": inferred[0] if len(inferred) == 1 else "multi",
        "input_urls": [entry["url"] for entry in profile_entries],
        "keywords": [],
        "comment_discovery_enabled": False,
        "run_checkpoint": {
            "link_import_platforms": inferred,
            "link_import_source": True,
        },
    }


def _apply_amazon_link_import(task: "CollectionTaskCreate", amazon_entries: list[dict[str, str]]) -> None:
    """Amazon 商品链接作为竞品发现 seed，不当作红人 profile。"""
    fields = build_link_import_task_fields(amazon_entries)
    task.collection_mode = fields["collection_mode"]
    task.platform = fields["platform"]
    task.platforms = fields["platforms"]
    task.input_urls = fields["input_urls"]
    task.keywords = fields["keywords"]
    task.comment_discovery_enabled = fields["comment_discovery_enabled"]
    task.run_checkpoint = {
        **(getattr(task, "run_checkpoint", None) or {}),
        **fields["run_checkpoint"],
    }


def _finalize_link_import_urls(task: "CollectionTaskCreate", valid: list[dict[str, str]]) -> None:
    fields = build_link_import_task_fields(valid)
    task.collection_mode = fields["collection_mode"]
    task.platform = fields["platform"]
    task.platforms = fields["platforms"]
    task.input_urls = fields["input_urls"]
    task.keywords = fields["keywords"]
    task.comment_discovery_enabled = fields["comment_discovery_enabled"]
    task.run_checkpoint = {
        **(getattr(task, "run_checkpoint", None) or {}),
        **fields["run_checkpoint"],
    }


def _has_amazon_product_seeds(task: "CollectionTaskCreate") -> bool:
    checkpoint = getattr(task, "run_checkpoint", None) or {}
    return bool(checkpoint.get("amazon_product_seeds"))


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

URL_ONLY_PLATFORM_LABELS = {
    "pinterest": "Pinterest",
    "ltk": "LTK",
    "shopmy": "ShopMy",
}

ACTIVE_DISCOVERY_MODE_BLOCK = frozenset(
    {
        CollectionMode.KEYWORD,
        CollectionMode.DISCOVERY,
        CollectionMode.CATEGORY_DISCOVERY,
        CollectionMode.CLUSTERING,
        CollectionMode.MIXED,
        CollectionMode.COMPETITOR_PRODUCT,
    }
)
HIGH_VALUE_FIRST_MODES = frozenset(
    {
        CollectionMode.KEYWORD,
        CollectionMode.DISCOVERY,
        CollectionMode.CATEGORY_DISCOVERY,
        CollectionMode.MIXED,
    }
)
HIGH_VALUE_FIRST_MIN_FOLLOWERS = 10_000


def _resolved_task_platforms(platform: str, platforms: list[str]) -> list[str]:
    normalized = normalize_platform_list(platforms) if platforms else []
    if not normalized and platform:
        legacy = (platform or "").strip().lower()
        if legacy in SUPPORTED_TASK_PLATFORMS:
            normalized = [legacy]
    return normalized


def validate_url_only_platforms_for_mode(
    collection_mode: CollectionMode,
    platform: str,
    platforms: list[str],
) -> None:
    """Pinterest / LTK / ShopMy 仅支持链接导入，不可用于关键词/自动发现/竞品商品发现。"""
    if collection_mode in (CollectionMode.LINK_IMPORT, CollectionMode.URLS, CollectionMode.COMMENT_AUTHORS):
        return
    if collection_mode == CollectionMode.LINK_SEED_DISCOVERY:
        return
    if collection_mode not in ACTIVE_DISCOVERY_MODE_BLOCK:
        return
    resolved = _resolved_task_platforms(platform, platforms)
    blocked = set(resolved) & URL_ONLY_PLATFORMS
    if collection_mode in (CollectionMode.KEYWORD, CollectionMode.DISCOVERY, CollectionMode.MIXED):
        blocked = blocked - KEYWORD_SEED_PLATFORMS
    if blocked:
        labels = [URL_ONLY_PLATFORM_LABELS.get(name, name) for name in sorted(blocked)]
        if len(labels) == 1:
            raise ValueError(f"{labels[0]} 当前主要通过链接导入或外链发现，请切换到「链接导入」模式")
        joined = "、".join(labels)
        raise ValueError(f"{joined} 当前主要通过链接导入或外链发现，请切换到「链接导入」模式")
    if collection_mode == CollectionMode.COMPETITOR_PRODUCT:
        invalid = set(resolved) - KEYWORD_DISCOVERY_PLATFORMS
        if invalid:
            raise ValueError(
                "竞品商品发现仅支持 Instagram / YouTube / TikTok / Facebook 作为后续发现平台"
            )


def validate_seed_only_discovery_mode(
    collection_mode: CollectionMode,
    platform: str,
    platforms: list[str],
) -> None:
    if collection_mode not in (CollectionMode.KEYWORD, CollectionMode.DISCOVERY, CollectionMode.MIXED):
        return
    resolved = _resolved_task_platforms(platform, platforms)
    if not resolved:
        return
    if set(resolved).issubset(KEYWORD_SEED_PLATFORMS):
        labels = [URL_ONLY_PLATFORM_LABELS.get(name, name) for name in resolved]
        raise ValueError(
            f"{' / '.join(labels)} 鍏抽敭璇嶉噰闆嗚浣跨敤銆岄瀵艰喘 seed 鑷姩鍙戠幇銆嶏紝涓嶈鐢ㄦ櫘閫氬叧閿瘝鍙戠幇"
        )


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
    min_engagement_rate: float | None = Field(default=None, ge=0, le=100)
    min_followers_count: int | None = Field(default=HIGH_VALUE_FIRST_MIN_FOLLOWERS, ge=0)
    max_followers_count: int | None = Field(default=None, ge=0)
    filter_include_keywords: list[str] = Field(default_factory=list)
    filter_exclude_keywords: list[str] = Field(default_factory=list)
    require_email: bool = False
    require_contact: bool = False
    strict_quality_filter: bool = False
    insert_qualified_only: bool = False
    export_qualified_only: bool = False
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
    stable_collection_mode: bool = False
    name: str = Field(..., max_length=255)
    collection_mode: CollectionMode = CollectionMode.KEYWORD
    platform: str = Field(default="instagram", max_length=50)
    platforms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    input_urls: list[str] = Field(default_factory=list)
    country: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    discovery_limit: int | None = Field(default=100, ge=1, le=500)
    min_engagement_rate: float | None = Field(default=None, ge=0, le=100)
    min_followers_count: int | None = Field(default=HIGH_VALUE_FIRST_MIN_FOLLOWERS, ge=0)
    max_followers_count: int | None = Field(default=None, ge=0)
    filter_include_keywords: list[str] = Field(default_factory=list)
    filter_exclude_keywords: list[str] = Field(default_factory=list)
    require_email: bool = False
    require_contact: bool = False
    strict_quality_filter: bool = False
    insert_qualified_only: bool = False
    export_qualified_only: bool = False
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
    run_checkpoint: dict[str, Any] = Field(default_factory=dict)

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
        if self.collection_mode == CollectionMode.LINK_IMPORT:
            urls = [u.strip() for u in self.input_urls if u and u.strip()]
            if urls:
                valid = validate_link_import_url_lines(urls)
                fields = build_link_import_task_fields(valid)
                self.collection_mode = fields["collection_mode"]
                self.platform = fields["platform"]
                self.platforms = fields["platforms"]
                self.input_urls = fields["input_urls"]
                self.keywords = fields["keywords"]
                self.comment_discovery_enabled = fields["comment_discovery_enabled"]
                self.run_checkpoint = {
                    **(self.run_checkpoint or {}),
                    **fields["run_checkpoint"],
                }
                return self
            self.platform, self.platforms = resolve_task_platform_fields(
                self.platform,
                self.platforms,
                require_platforms=False,
            )
            return self
        self.platform, self.platforms = resolve_task_platform_fields(self.platform, self.platforms)
        return self

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "CollectionTaskCreate":
        keywords = [k.strip() for k in self.keywords if k and k.strip()]
        urls = [u.strip() for u in self.input_urls if u and u.strip()]
        self.keywords = keywords
        self.input_urls = urls

        if self.collection_mode == CollectionMode.LINK_IMPORT:
            if not urls:
                raise ValueError("链接导入至少需要一个链接")
            if not _has_amazon_product_seeds(self):
                valid = validate_link_import_url_lines(urls)
                _finalize_link_import_urls(self, valid)
        elif self.collection_mode == CollectionMode.LINK_SEED_DISCOVERY:
            checkpoint = dict(self.run_checkpoint or {})
            if urls and not checkpoint.get("amazon_product_seeds"):
                seeds = []
                normalized_urls: list[str] = []
                for raw in urls:
                    from app.services.amazon_url import parse_amazon_product_input

                    seed = parse_amazon_product_input(raw)
                    if seed:
                        seeds.append(seed)
                        normalized_urls.append(str(seed.get("normalized_url") or raw))
                    else:
                        normalized_urls.append(raw)
                if seeds:
                    self.input_urls = list(dict.fromkeys(normalized_urls))
                    checkpoint["amazon_product_seeds"] = seeds
                    self.run_checkpoint = checkpoint
                    for seed in seeds:
                        asin = str(seed.get("asin") or "").strip()
                        if asin and asin not in self.keywords:
                            self.keywords.append(asin)
            if not keywords and not urls and not (self.category or "").strip():
                raise ValueError("导购 seed 自动发现需填写关键词或类目")
            resolved = _resolved_task_platforms(self.platform, self.platforms)
            if not resolved:
                self.platforms = ["ltk", "shopmy", "pinterest"]
                self.platform = "multi"
            elif not set(resolved) & URL_ONLY_PLATFORMS:
                raise ValueError("导购 seed 自动发现请至少选择 LTK、ShopMy 或 Pinterest 作为 seed 来源平台")
        elif self.collection_mode == CollectionMode.COMPETITOR_PRODUCT:
            if not keywords and not urls:
                raise ValueError("竞品商品发现需填写 Amazon 链接、ASIN 或商品关键词")
            self.comment_discovery_enabled = False
            checkpoint = dict(self.run_checkpoint or {})
            if urls and not checkpoint.get("amazon_product_seeds"):
                seeds = []
                normalized_urls: list[str] = []
                for raw in urls:
                    from app.services.amazon_url import parse_amazon_product_input

                    seed = parse_amazon_product_input(raw)
                    if seed:
                        seeds.append(seed)
                        normalized_urls.append(seed["normalized_url"])
                    else:
                        normalized_urls.append(raw)
                if seeds:
                    self.input_urls = list(dict.fromkeys(normalized_urls))
                    checkpoint["amazon_product_seeds"] = seeds
                    self.run_checkpoint = checkpoint
                    for seed in seeds:
                        asin = seed.get("asin")
                        if asin and asin not in self.keywords:
                            self.keywords.append(asin)
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
        validate_seed_only_discovery_mode(self.collection_mode, self.platform, self.platforms)
        validate_url_only_platforms_for_mode(self.collection_mode, self.platform, self.platforms)
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
    require_email: bool | None = None
    require_contact: bool | None = None
    strict_quality_filter: bool | None = None
    insert_qualified_only: bool | None = None
    export_qualified_only: bool | None = None
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
        if self.input_urls is not None:
            valid = validate_link_import_url_lines(self.input_urls)
            if self.collection_mode == CollectionMode.LINK_IMPORT:
                fields = build_link_import_task_fields(valid)
                self.collection_mode = fields["collection_mode"]
                self.platform = fields["platform"]
                self.platforms = fields["platforms"]
                self.input_urls = fields["input_urls"]
                self.keywords = fields["keywords"]
                self.comment_discovery_enabled = fields["comment_discovery_enabled"]
                self.run_checkpoint = fields["run_checkpoint"]
        if self.collection_mode is not None:
            validate_seed_only_discovery_mode(
                self.collection_mode,
                self.platform or "",
                self.platforms or [],
            )
            validate_url_only_platforms_for_mode(
                self.collection_mode,
                self.platform or "",
                self.platforms or [],
            )
        elif self.platforms is not None or self.platform is not None:
            selected = set(_resolved_task_platforms(self.platform or "", self.platforms or []))
            if selected & URL_ONLY_PLATFORMS:
                labels = [URL_ONLY_PLATFORM_LABELS.get(name, name) for name in sorted(selected & URL_ONLY_PLATFORMS)]
                label = labels[0] if len(labels) == 1 else "、".join(labels)
                raise ValueError(f"{label} 当前主要通过链接导入或外链发现，请切换到「链接导入」模式")
        return self


class CollectionTaskRead(CollectionTaskBase, TimestampMixin, ORMModel):
    id: int
    is_archived: bool = False
    archived_at: datetime | None = None
    stale: bool = False
    recoverable: bool = False
    stale_after_seconds: int = Field(default=0, ge=0)
    is_ineffective: bool = False
    effectiveness_category: Literal["high_value", "effective", "low_value_result", "no_result", "failed"] = "no_result"
    has_retention_traces: bool = False
    management_tags: list[str] = Field(default_factory=list)
    is_possible_duplicate: bool = False


class CollectionTaskFilter(BaseModel):
    product_id: int | None = None
    owner_user_id: int | None = None
    owner_scope: Literal["mine", "all"] = "mine"
    owner_is_admin: bool = False
    platform: str | None = None
    status: CollectionTaskStatus | None = None
    search: str | None = None
    effectiveness: Literal["high_value", "effective", "ineffective", "low_value_result", "no_result", "failed"] | None = None
    task_view: Literal[
        "all",
        "high_value",
        "effective",
        "ineffective",
        "low_value_result",
        "no_result",
        "test_history",
        "archived",
    ] | None = None


class CollectionTaskBulkDelete(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=100)


class CollectionTaskBulkDeleteResult(BaseModel):
    deleted_count: int = 0
    archived_count: int = 0
    skipped_count: int = 0
    deleted_ids: list[int] = Field(default_factory=list)
    archived_ids: list[int] = Field(default_factory=list)
    skipped_ids: list[int] = Field(default_factory=list)


class CollectionTaskBulkRun(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=50)


class CollectionTaskBulkRunResult(BaseModel):
    started_ids: list[int] = Field(default_factory=list)
    skipped_ids: list[int] = Field(default_factory=list)
    skipped_reasons: dict[str, str] = Field(default_factory=dict)
    capacity: int = 1
    active_count: int = 0
    message: str = ""


class CollectionTaskBulkManage(BaseModel):
    action: Literal[
        "archive_test_history",
        "delete_no_result",
        "restore_archived",
        "archive_duplicates",
    ]
    task_ids: list[int] = Field(default_factory=list, max_length=200)


class CollectionTaskBulkManageResult(BaseModel):
    matched_count: int = 0
    archived_count: int = 0
    deleted_count: int = 0
    skipped_count: int = 0
    restored_count: int = 0
    archived_ids: list[int] = Field(default_factory=list)
    deleted_ids: list[int] = Field(default_factory=list)
    restored_ids: list[int] = Field(default_factory=list)
    skipped_ids: list[int] = Field(default_factory=list)
    skipped_reasons: dict[str, str] = Field(default_factory=dict)


class CollectionTaskDeleteResult(BaseModel):
    action: Literal["deleted", "archived"]
    task_id: int


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
    platform: str | None = None
    high_value: bool | None = None
    has_email: bool | None = None
    has_contact: bool | None = None
    min_followers_count: int | None = Field(default=None, ge=0)
    max_followers_count: int | None = Field(default=None, ge=0)
    min_engagement_rate: float | None = Field(default=None, ge=0, le=100)
    max_engagement_rate: float | None = Field(default=None, ge=0, le=100)
    insert_blocked_reason: str | None = None
    contact_status: str | None = None
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
    source_input_url: str | None = None
    source_caption: str | None = None
    source_comment_url: str | None = None
    source_comment_text: str | None = None
    source_discovery_type: str | None = None
    source_meta: dict | None = None
    followers_count: int | None = None
    engagement_rate: float | None = None
    is_high_value: bool | None = None
    has_email: bool | None = None
    has_contact: bool | None = None
    contact_status: str | None = None
    insert_blocked_reason: str | None = None
    profile_fetched_at: datetime | None = None
    influencer_id: int | None = None
    status: str
    failure_reason: str | None = None
    failure_detail: str | None = None
    run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CollectionTaskCandidateRecrawlRequest(BaseModel):
    candidate_id: int | None = None
    profile_url: str | None = None


class CollectionTaskCandidateRecrawlResult(BaseModel):
    candidate_id: int
    task_id: int
    status: str
    attempted: bool = True
    message: str | None = None
    global_influencer_id: int | None = None
    product_influencer_id: int | None = None


class CollectionTaskCandidateBatchRecrawlRequest(BaseModel):
    concurrency: int = Field(default=3, ge=1, le=5)
    limit: int | None = Field(default=None, ge=1, le=500)


class CollectionTaskCandidateBatchRecrawlResult(BaseModel):
    task_id: int
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[CollectionTaskCandidateRecrawlResult] = Field(default_factory=list)


class CollectionTaskCandidateEmailEnrichmentResult(BaseModel):
    candidate_id: int
    task_id: int
    status: str
    attempted: bool = True
    message: str | None = None
    email: str | None = None
    global_influencer_id: int | None = None
    product_influencer_id: int | None = None


class CollectionTaskCandidateBatchEmailEnrichmentRequest(BaseModel):
    limit: int | None = Field(default=20, ge=1, le=100)


class CollectionTaskCandidateBatchEmailEnrichmentResult(BaseModel):
    task_id: int
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[CollectionTaskCandidateEmailEnrichmentResult] = Field(default_factory=list)


def resolve_candidate_source_input_url(
    source_input_url: str | None,
    source_meta: dict | None,
) -> str | None:
    if source_input_url and str(source_input_url).strip():
        return str(source_input_url).strip()
    if isinstance(source_meta, dict):
        for key in ("source_input_url", "input_url"):
            value = source_meta.get(key)
            if value and str(value).strip():
                return str(value).strip()
    return None


def collection_task_candidate_read(row) -> CollectionTaskCandidateRead:
    read = CollectionTaskCandidateRead.model_validate(row)
    resolved = resolve_candidate_source_input_url(read.source_input_url, read.source_meta)
    if resolved != read.source_input_url:
        return read.model_copy(update={"source_input_url": resolved})
    return read
