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

    task: Mapped["CollectionTask | None"] = relationship(back_populates="email_logs")
