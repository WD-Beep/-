# 文件说明：后端数据库模型，定义业务数据表结构；当前文件：product influencer
"""产品维度红人业务记录（评分、跟进、备注等按产品隔离）。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.global_influencer_profile import GlobalInfluencerProfile
    from app.models.influencer_followup import InfluencerFollowup
    from app.models.product_influencer_source import ProductInfluencerSource


class ProductInfluencer(Base):
    __tablename__ = "product_influencers"
    __table_args__ = (
        UniqueConstraint("product_id", "global_influencer_id", name="uq_product_influencer_product_global"),
        Index("ix_product_influencers_product_id", "product_id"),
        Index("ix_product_influencers_follow_status", "follow_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    global_influencer_id: Mapped[int] = mapped_column(
        ForeignKey("global_influencer_profiles.id", ondelete="CASCADE"), nullable=False
    )
    legacy_influencer_id: Mapped[int | None] = mapped_column(Integer, index=True)

    product_fit: Mapped[float | None] = mapped_column(Float)
    engagement_score: Mapped[float | None] = mapped_column(Float)
    content_match_score: Mapped[float | None] = mapped_column(Float)
    contactability_score: Mapped[float | None] = mapped_column(Float)
    commercial_signal_score: Mapped[float | None] = mapped_column(Float)
    activity_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    travel_fit_score: Mapped[float | None] = mapped_column(Float)
    purchasing_power_score: Mapped[float | None] = mapped_column(Float)
    sales_potential_score: Mapped[float | None] = mapped_column(Float)
    audience_match_score: Mapped[float | None] = mapped_column(Float)
    roi_forecast: Mapped[float | None] = mapped_column(Float)
    final_priority: Mapped[str | None] = mapped_column(String(10))
    score: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    score_reason: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_collaboration_suggestion: Mapped[str | None] = mapped_column(Text)
    ai_outreach_message: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSONB, default=list)
    follow_status: Mapped[str | None] = mapped_column(String(50), index=True)
    owner: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalid_reason: Mapped[str | None] = mapped_column(Text)
    blacklist_reason: Mapped[str | None] = mapped_column(Text)
    source_discovery_type: Mapped[str | None] = mapped_column(String(32))
    source_post_url: Mapped[str | None] = mapped_column(String(512))
    source_comment_url: Mapped[str | None] = mapped_column(String(512))
    source_comment_text: Mapped[str | None] = mapped_column(Text)
    is_inserted: Mapped[bool] = mapped_column(default=True, nullable=False)
    filter_reason: Mapped[str | None] = mapped_column(String(64))
    filter_detail: Mapped[str | None] = mapped_column(Text)
    first_inserted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    global_profile: Mapped["GlobalInfluencerProfile"] = relationship(back_populates="product_records")
    followups: Mapped[list["InfluencerFollowup"]] = relationship(
        back_populates="product_influencer",
        cascade="all, delete-orphan",
        order_by="InfluencerFollowup.created_at.desc()",
    )
    sources: Mapped[list["ProductInfluencerSource"]] = relationship(
        back_populates="product_influencer",
        cascade="all, delete-orphan",
        order_by="ProductInfluencerSource.collected_at.desc()",
    )
