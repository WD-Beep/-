from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CollectionTaskCandidate(Base):
    """采集任务候选账号（含主页补采失败 / 待补采）。"""

    __tablename__ = "collection_task_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("collection_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("products.id", ondelete="SET NULL"), index=True)
    global_influencer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("global_influencer_profiles.id", ondelete="SET NULL"), index=True
    )
    product_influencer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("product_influencers.id", ondelete="SET NULL"), index=True
    )
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_url: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, default="instagram")
    source_type: Mapped[str | None] = mapped_column(String(32))
    source_keyword: Mapped[str | None] = mapped_column(String(255))
    source_hashtag: Mapped[str | None] = mapped_column(String(255))
    source_post_url: Mapped[str | None] = mapped_column(String(512))
    source_input_url: Mapped[str | None] = mapped_column(String(512))
    source_caption: Mapped[str | None] = mapped_column(Text)
    source_comment_url: Mapped[str | None] = mapped_column(String(512))
    source_comment_text: Mapped[str | None] = mapped_column(Text)
    source_discovery_type: Mapped[str | None] = mapped_column(String(32))
    source_meta: Mapped[dict | None] = mapped_column(JSONB)
    followers_count: Mapped[int | None] = mapped_column(Integer)
    engagement_rate: Mapped[float | None] = mapped_column(Float)
    is_high_value: Mapped[bool | None] = mapped_column(Boolean)
    has_email: Mapped[bool | None] = mapped_column(Boolean)
    has_contact: Mapped[bool | None] = mapped_column(Boolean)
    contact_status: Mapped[str | None] = mapped_column(String(32))
    insert_blocked_reason: Mapped[str | None] = mapped_column(Text)
    profile_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    influencer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("influencers.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_profile")
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    failure_detail: Mapped[str | None] = mapped_column(Text)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task: Mapped["CollectionTask"] = relationship(back_populates="candidates")
