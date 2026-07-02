from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutreachCampaignRecipient(Base):
    __tablename__ = "outreach_campaign_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("outreach_email_campaigns.id", ondelete="CASCADE"), index=True
    )
    product_influencer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product_influencers.id", ondelete="CASCADE")
    )
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_knowledge: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    can_queue: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", server_default="pending_review", index=True)
    is_high_value: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    approval_block_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    previewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queue_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("outreach_send_queue.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
