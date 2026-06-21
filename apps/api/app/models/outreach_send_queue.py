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
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_by_ai: Mapped[bool] = mapped_column(default=True)
    matched_knowledge: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    allow_resend: Mapped[bool] = mapped_column(default=False)
    email_log_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("email_logs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
