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
