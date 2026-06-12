"""全局红人基础资料池（跨产品共享、按平台身份去重）。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GlobalInfluencerProfile(Base):
    __tablename__ = "global_influencer_profiles"
    __table_args__ = (
        UniqueConstraint("platform", "normalized_profile_url", name="uq_global_influencer_platform_url"),
        Index("ix_global_influencer_platform", "platform"),
        Index("ix_global_influencer_username", "platform", "normalized_username"),
        Index(
            "uq_global_influencer_platform_unique_id",
            "platform",
            "platform_unique_id",
            unique=True,
            postgresql_where=text("platform_unique_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_unique_id: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_profile_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    country: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(50))
    category: Mapped[str | None] = mapped_column(String(100))
    niche: Mapped[str | None] = mapped_column(String(100))
    bio: Mapped[str | None] = mapped_column(Text)
    followers_count: Mapped[int | None] = mapped_column(Integer)
    avg_views: Mapped[int | None] = mapped_column(Integer)
    avg_likes: Mapped[int | None] = mapped_column(Integer)
    avg_comments: Mapped[int | None] = mapped_column(Integer)
    engagement_rate: Mapped[float | None] = mapped_column(Float)
    email: Mapped[str | None] = mapped_column(String(255))
    final_email: Mapped[str | None] = mapped_column(String(255))
    public_email: Mapped[str | None] = mapped_column(String(255))
    business_email: Mapped[str | None] = mapped_column(String(255))
    email_source: Mapped[str | None] = mapped_column(String(100))
    contact_credibility: Mapped[float | None] = mapped_column(Float)
    contact_score: Mapped[float | None] = mapped_column(Float)
    contact_credibility_level: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(String(1024))
    contact_page: Mapped[str | None] = mapped_column(String(1024))
    linktree_url: Mapped[str | None] = mapped_column(String(1024))
    whatsapp: Mapped[str | None] = mapped_column(String(50))
    telegram: Mapped[str | None] = mapped_column(String(100))
    other_social_links: Mapped[list | None] = mapped_column(JSONB, default=list)
    contact_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contact_sources: Mapped[list | None] = mapped_column(JSONB, default=list)
    contact_fetch_status: Mapped[str | None] = mapped_column(String(32), index=True)
    contact_fetch_error: Mapped[str | None] = mapped_column(Text)
    recent_post_titles: Mapped[list | None] = mapped_column(JSONB, default=list)
    recent_post_urls: Mapped[list | None] = mapped_column(JSONB, default=list)
    last_post_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posting_frequency: Mapped[str | None] = mapped_column(String(50))
    data_completeness: Mapped[float | None] = mapped_column(Float)
    has_brand_collaboration: Mapped[bool | None] = mapped_column()
    estimated_collab_price: Mapped[str | None] = mapped_column(String(100))
    collaboration_formats: Mapped[list | None] = mapped_column(JSONB, default=list)
    content_topics: Mapped[list | None] = mapped_column(JSONB, default=list)
    audience_country: Mapped[str | None] = mapped_column(String(100))
    audience_language: Mapped[str | None] = mapped_column(String(50))
    legacy_influencer_id: Mapped[int | None] = mapped_column(Integer, index=True)
    profile_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    product_records: Mapped[list["ProductInfluencer"]] = relationship(back_populates="global_profile")
