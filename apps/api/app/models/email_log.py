# 文件说明：后端数据库模型，定义业务数据表结构；当前文件：email log
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import EmailLogStatus

if TYPE_CHECKING:
    from app.models.collection_task import CollectionTask


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("products.id", ondelete="SET NULL"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("collection_tasks.id", ondelete="SET NULL"))
    product_influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_influencers.id", ondelete="SET NULL"),
        index=True,
    )
    sender_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    smtp_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user_smtp_accounts.id", ondelete="SET NULL"), index=True)
    sender_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    follow_up_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320))
    influencer_username: Mapped[str | None] = mapped_column(String(255))
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EmailLogStatus.PENDING.value)
    attachment_path: Mapped[str | None] = mapped_column(String(1024))
    error_message: Mapped[str | None] = mapped_column(Text)
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_provider: Mapped[str | None] = mapped_column(String(50))
    ai_reason: Mapped[str | None] = mapped_column(Text)
    matched_knowledge: Mapped[list | None] = mapped_column(JSONB)
    risk_notes: Mapped[list | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_id: Mapped[str | None] = mapped_column(String(512), index=True)
    has_replied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    reply_email_log_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("email_replies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reply_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    follow_up_status: Mapped[str | None] = mapped_column(String(32), nullable=True, default="none", server_default="none", index=True)
    follow_up_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_followups: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    stop_follow_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    task: Mapped["CollectionTask | None"] = relationship(back_populates="email_logs")
