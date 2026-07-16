from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserSmtpAccount(Base):
    __tablename__ = "user_smtp_accounts"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_smtp_account_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="gmail", server_default="gmail")
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False, default="smtp.gmail.com", server_default="smtp.gmail.com")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587, server_default="587")
    smtp_user: Mapped[str] = mapped_column(String(320), nullable=False)
    smtp_password: Mapped[str] = mapped_column(Text, nullable=False)
    smtp_from: Mapped[str] = mapped_column(String(320), nullable=False)
    smtp_from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imap_user: Mapped[str | None] = mapped_column(String(320), nullable=True)
    imap_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
