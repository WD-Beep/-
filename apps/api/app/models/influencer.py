from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.influencer_followup import InfluencerFollowup


class Influencer(Base):
    __tablename__ = "influencers"
    __table_args__ = (
        UniqueConstraint("platform", "profile_url", name="uq_influencer_platform_profile_url"),
        Index("ix_influencers_platform", "platform"),
        Index("ix_influencers_country", "country"),
        Index("ix_influencers_category", "category"),
        Index(
            "uq_influencers_platform_unique_id",
            "platform",
            "platform_unique_id",
            unique=True,
            postgresql_where=text("platform_unique_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str] = mapped_column(String(1024), nullable=False)
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
    whatsapp: Mapped[str | None] = mapped_column(String(1024))
    telegram: Mapped[str | None] = mapped_column(String(100))
    other_social_links: Mapped[list | None] = mapped_column(JSONB, default=list)
    product_fit: Mapped[float | None] = mapped_column(Float)
    data_completeness: Mapped[float | None] = mapped_column(Float)
    has_brand_collaboration: Mapped[bool | None] = mapped_column(Boolean)
    estimated_collab_price: Mapped[str | None] = mapped_column(String(100))
    collaboration_formats: Mapped[list | None] = mapped_column(JSONB, default=list)
    content_topics: Mapped[list | None] = mapped_column(JSONB, default=list)
    audience_country: Mapped[str | None] = mapped_column(String(100))
    audience_language: Mapped[str | None] = mapped_column(String(50))
    travel_fit_score: Mapped[float | None] = mapped_column(Float)
    purchasing_power_score: Mapped[float | None] = mapped_column(Float)
    sales_potential_score: Mapped[float | None] = mapped_column(Float)
    audience_match_score: Mapped[float | None] = mapped_column(Float)
    roi_forecast: Mapped[float | None] = mapped_column(Float)
    recent_post_titles: Mapped[list | None] = mapped_column(JSONB, default=list)
    recent_post_urls: Mapped[list | None] = mapped_column(JSONB, default=list)
    last_post_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posting_frequency: Mapped[str | None] = mapped_column(String(50))
    tags: Mapped[list | None] = mapped_column(JSONB, default=list)
    engagement_score: Mapped[float | None] = mapped_column(Float)
    content_match_score: Mapped[float | None] = mapped_column(Float)
    contactability_score: Mapped[float | None] = mapped_column(Float)
    commercial_signal_score: Mapped[float | None] = mapped_column(Float)
    activity_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    final_priority: Mapped[str | None] = mapped_column(String(10))
    score: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    score_reason: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_collaboration_suggestion: Mapped[str | None] = mapped_column(Text)
    ai_outreach_message: Mapped[str | None] = mapped_column(Text)
    follow_status: Mapped[str | None] = mapped_column(String(50), index=True)
    owner: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalid_reason: Mapped[str | None] = mapped_column(Text)
    blacklist_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_discovery_type: Mapped[str | None] = mapped_column(String(32))
    source_post_url: Mapped[str | None] = mapped_column(String(512))
    source_comment_url: Mapped[str | None] = mapped_column(String(512))
    source_comment_text: Mapped[str | None] = mapped_column(Text)
    contact_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contact_sources: Mapped[list | None] = mapped_column(JSONB, default=list)
    contact_fetch_status: Mapped[str | None] = mapped_column(String(32), index=True)
    contact_fetch_error: Mapped[str | None] = mapped_column(Text)
    platform_unique_id: Mapped[str | None] = mapped_column(String(128), index=True)

    followups: Mapped[list["InfluencerFollowup"]] = relationship(
        back_populates="influencer",
        cascade="all, delete-orphan",
        order_by="InfluencerFollowup.created_at.desc()",
    )
