from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod

from app.models.collection_task import CollectionTask


@dataclass
class CollectedInfluencer:
    """采集器返回的标准红人数据结构。"""

    platform: str
    username: str
    profile_url: str
    display_name: str | None = None
    avatar_url: str | None = None
    country: str | None = None
    language: str | None = None
    category: str | None = None
    niche: str | None = None
    bio: str | None = None
    followers_count: int | None = None
    avg_views: int | None = None
    avg_likes: int | None = None
    avg_comments: int | None = None
    engagement_rate: float | None = None
    email: str | None = None
    final_email: str | None = None
    public_email: str | None = None
    business_email: str | None = None
    email_source: str | None = None
    contact_credibility: float | None = None
    contact_score: float | None = None
    contact_credibility_level: str | None = None
    website: str | None = None
    contact_page: str | None = None
    linktree_url: str | None = None
    whatsapp: str | None = None
    telegram: str | None = None
    other_social_links: list[dict[str, str]] = field(default_factory=list)
    product_fit: float | None = None
    data_completeness: float | None = None
    has_brand_collaboration: bool | None = None
    estimated_collab_price: str | None = None
    collaboration_formats: list[str] = field(default_factory=list)
    content_topics: list[str] = field(default_factory=list)
    audience_country: str | None = None
    audience_language: str | None = None
    travel_fit_score: float | None = None
    purchasing_power_score: float | None = None
    sales_potential_score: float | None = None
    audience_match_score: float | None = None
    roi_forecast: float | None = None
    recent_post_titles: list[str] = field(default_factory=list)
    recent_post_urls: list[str] = field(default_factory=list)
    last_post_at: datetime | None = None
    posting_frequency: str | None = None
    tags: list[str] = field(default_factory=list)
    engagement_score: float | None = None
    content_match_score: float | None = None
    contactability_score: float | None = None
    commercial_signal_score: float | None = None
    activity_score: float | None = None
    risk_score: float | None = None
    final_priority: str | None = None
    risk_level: str | None = None
    score: float | None = None
    source_discovery_type: str | None = None
    source_post_url: str | None = None
    source_input_url: str | None = None
    source_comment_url: str | None = None
    source_comment_text: str | None = None
    contact_discovered_at: datetime | None = None
    contact_sources: list[dict] = field(default_factory=list)
    contact_fetch_status: str | None = None
    contact_fetch_error: str | None = None
    platform_unique_id: str | None = None


class BaseCollector(ABC):
    """采集器基类。真实平台采集器需继承此类并实现 collect。"""

    @abstractmethod
    async def collect(self, task: CollectionTask) -> list[CollectedInfluencer]:
        """根据采集任务配置返回红人列表。"""

    @property
    def name(self) -> str:
        return self.__class__.__name__
