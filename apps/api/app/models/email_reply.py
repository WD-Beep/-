# 文件说明：后端数据库模型，定义业务数据表结构；当前文件：email reply
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmailReply(Base):
    __tablename__ = "email_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    email_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    product_influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_influencers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("outreach_email_campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_id: Mapped[str | None] = mapped_column(String(512), nullable=True, unique=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(512))
    match_method: Mapped[str | None] = mapped_column(String(64))
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unprocessed", index=True)
    intent_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unprocessed", index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="webhook")
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(String(500))
    raw_headers: Mapped[dict | None] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manual_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
