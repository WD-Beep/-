# 文件说明：后端数据库模型，定义业务数据表结构；当前文件：outreach send queue
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutreachSendQueueItem(Base):
    __tablename__ = "outreach_send_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_influencer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product_influencers.id", ondelete="CASCADE"), index=True
    )
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    generated_by_ai: Mapped[bool] = mapped_column(default=True)
    matched_knowledge: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    allow_resend: Mapped[bool] = mapped_column(default=False)
    campaign_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("outreach_email_campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email_log_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("email_logs.id"), nullable=True)
    smtp_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    queue_type: Mapped[str] = mapped_column(String(32), nullable=False, default="first_touch", server_default="first_touch", index=True)
    follow_up_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_queue_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("outreach_send_queue.id"), nullable=True)
    outreach_record_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("email_logs.id"), nullable=True, index=True)
    should_skip_if_replied: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
