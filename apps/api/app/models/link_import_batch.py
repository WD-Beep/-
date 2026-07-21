# 文件说明：后端数据库模型，定义业务数据表结构；当前文件：link import batch
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import LinkImportBatchStatus


class LinkImportBatch(Base):
    __tablename__ = "link_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    workspace_id: Mapped[int | None] = mapped_column(Integer, index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_urls: Mapped[str] = mapped_column(Text, nullable=False)
    valid_urls: Mapped[list | None] = mapped_column(JSONB, default=list)
    invalid_urls: Mapped[list | None] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=LinkImportBatchStatus.PENDING.value
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
