# 文件说明：后端数据库模型，定义业务数据表结构；当前文件：outreach email campaign
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutreachEmailCampaign(Base):
    __tablename__ = "outreach_email_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    knowledge_base_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True
    )
    message_template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("message_templates.id", ondelete="SET NULL"), nullable=True
    )
    daily_limit: Mapped[int] = mapped_column(Integer, default=50)
    send_window_start: Mapped[str | None] = mapped_column(String(8), nullable=True)
    send_window_end: Mapped[str | None] = mapped_column(String(8), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    skip_sent: Mapped[bool] = mapped_column(Boolean, default=True)
    skip_replied: Mapped[bool] = mapped_column(Boolean, default=True)
    skip_blacklisted: Mapped[bool] = mapped_column(Boolean, default=True)
    skip_invalid: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_resend: Mapped[bool] = mapped_column(Boolean, default=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    previewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_send_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_send_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    auto_send_timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    last_auto_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_auto_process_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    influencer_filters_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
