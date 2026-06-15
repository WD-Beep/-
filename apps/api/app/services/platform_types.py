"""多平台 API Direct 统一数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PlatformSupportStatus = Literal[
    "supported",
    "not_configured",
    "not_available",
    "url_only",
]

SUPPORTED_PLATFORMS = (
    "instagram",
    "tiktok",
    "youtube",
    "facebook",
    "pinterest",
    "ltk",
    "shopmy",
)

PLATFORM_DISCOVERY_CATEGORIES: dict[str, str] = {
    "instagram": "search_discovery",
    "youtube": "search_discovery",
    "tiktok": "search_discovery",
    "facebook": "search_discovery",
    "pinterest": "link_completion",
    "ltk": "link_completion",
    "shopmy": "link_completion",
    "amazon": "link_completion",
}

DISCOVERY_CATEGORY_LABELS: dict[str, str] = {
    "search_discovery": "可搜索发现",
    "external_link_discovery": "外链发现",
    "link_completion": "链接补全",
}

DISCOVERY_CATEGORY_HINTS: dict[str, str] = {
    "search_discovery": "支持关键词、话题/标签、竞品商品词扩展，以及从帖子/视频/评论/主页发现红人。",
    "external_link_discovery": "可从 Instagram/TikTok/YouTube/Facebook 的 bio、视频描述、主页外链，或已采集红人的 other_social_links 中识别；也可作为商业化能力信号。",
    "link_completion": "主要通过链接导入定向补全资料，也可从其他社媒外链反向发现；不保证粉丝/互动/联系方式完整，空资料会标记为低信息量结果。",
}

LINK_COMPLETION_PLATFORMS = frozenset({"pinterest", "ltk", "shopmy", "amazon"})
URL_ONLY_PLATFORMS = frozenset({"pinterest", "ltk", "shopmy"})
EXTERNAL_LINK_PLATFORMS = frozenset({"ltk", "shopmy"})
KEYWORD_DISCOVERY_PLATFORMS = frozenset({"instagram", "tiktok", "youtube", "facebook"})

LINK_IMPORT_PROFILE_PLATFORMS = frozenset(
    {"instagram", "youtube", "tiktok", "facebook", "pinterest", "ltk", "shopmy"}
)

PLATFORM_FEATURE_FLAGS: dict[str, dict[str, bool]] = {
    "instagram": {"keyword_discovery": True, "link_import": True, "product_seed": False},
    "youtube": {"keyword_discovery": True, "link_import": True, "product_seed": False},
    "tiktok": {"keyword_discovery": True, "link_import": True, "product_seed": False},
    "facebook": {"keyword_discovery": True, "link_import": True, "product_seed": False},
    "pinterest": {"keyword_discovery": False, "link_import": True, "product_seed": False},
    "ltk": {"keyword_discovery": False, "link_import": True, "product_seed": False},
    "shopmy": {"keyword_discovery": False, "link_import": True, "product_seed": False},
    "amazon": {"keyword_discovery": False, "link_import": True, "product_seed": True},
}

LINK_IMPORT_HINTS: dict[str, str] = {
    "instagram": "Instagram：主页链接；也支持关键词/话题发现",
    "youtube": "YouTube：频道链接；也支持关键词/话题发现",
    "tiktok": "TikTok：主页链接；也支持关键词/话题发现",
    "facebook": "Facebook：主页/Page 链接；也支持关键词/话题发现",
    "pinterest": "Pinterest：主页/Board/Pin 链接；主要通过链接导入或外链发现补全",
    "ltk": "LTK：创作者/商品链接；可通过链接导入或社媒外链/已采集红人反向发现",
    "shopmy": "ShopMy：创作者/商品链接；可通过链接导入或社媒外链/已采集红人反向发现",
    "amazon": "Amazon：商品链接线索；用于竞品商品发现，不是红人主页平台",
}


def platform_discovery_category(platform: str) -> str:
    return PLATFORM_DISCOVERY_CATEGORIES.get(platform.lower(), "link_completion")


def platform_feature_flags(platform: str) -> dict[str, bool]:
    return PLATFORM_FEATURE_FLAGS.get(
        platform.lower(),
        {"keyword_discovery": False, "link_import": False, "product_seed": False},
    )


def apply_platform_feature_flags(cap: "PlatformCapability") -> "PlatformCapability":
    flags = platform_feature_flags(cap.platform)
    cap.keyword_discovery = flags["keyword_discovery"]
    cap.link_import = flags["link_import"]
    cap.product_seed = flags["product_seed"]
    cap.discovery_category = platform_discovery_category(cap.platform)
    cap.external_link_discovery = cap.platform.lower() in EXTERNAL_LINK_PLATFORMS
    return cap


@dataclass
class PlatformCandidateProfile:
    platform: str
    username: str
    profile_url: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    followers_count: int | None = None
    avg_views: int | None = None
    avg_likes: int | None = None
    avg_comments: int | None = None
    engagement_rate: float | None = None
    website: str | None = None
    email: str | None = None
    other_social_links: list[dict[str, str]] = field(default_factory=list)
    recent_post_titles: list[str] = field(default_factory=list)
    recent_post_urls: list[str] = field(default_factory=list)
    source_url: str | None = None
    source_post_url: str | None = None
    source_input_url: str | None = None
    source_type: str | None = None
    source_discovery_type: str | None = None
    source_meta: dict[str, Any] = field(default_factory=dict)
    channel_id: str | None = None


@dataclass
class PlatformDiscoveryResult:
    platform: str
    items: list[Any] = field(default_factory=list)
    profiles: list["PlatformCandidateProfile"] = field(default_factory=list)
    candidate_rows: list[dict] = field(default_factory=list)
    discovered_count: int = 0
    deduped_count: int = 0
    profile_fetched_count: int = 0
    profile_failed_count: int = 0
    api_requests: int = 0
    errors: list[str] = field(default_factory=list)
    rate_limited: bool = False
    rate_limit_count: int = 0
    fatal: bool = False
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class PlatformCapability:
    platform: str
    label: str
    status: PlatformSupportStatus
    message: str
    endpoints: list[str] = field(default_factory=list)
    keyword_discovery: bool = False
    link_import: bool = False
    product_seed: bool = False
    link_import_hint: str | None = None
    discovery_category: str = "link_completion"
    external_link_discovery: bool = False
