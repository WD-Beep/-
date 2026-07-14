from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import CollectionMode, CollectionTaskStatus


class CollectionTask(Base):
    __tablename__ = "collection_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_tasks.id", ondelete="CASCADE"), index=True
    )
    batch_group_id: Mapped[str | None] = mapped_column(String(64), index=True)
    batch_round_index: Mapped[int | None] = mapped_column(Integer)
    batch_round_count: Mapped[int | None] = mapped_column(Integer)
    max_runtime_minutes: Mapped[int | None] = mapped_column(Integer, default=60)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    collection_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CollectionMode.KEYWORD.value
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platforms: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    input_urls: Mapped[list | None] = mapped_column(JSONB, default=list)
    country: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
    discovery_limit: Mapped[int | None] = mapped_column(Integer)
    min_engagement_rate: Mapped[float | None] = mapped_column(Float)
    min_followers_count: Mapped[int | None] = mapped_column(Integer)
    max_followers_count: Mapped[int | None] = mapped_column(Integer)
    filter_include_keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    filter_exclude_keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    require_email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    strict_quality_filter: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    insert_qualified_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    export_qualified_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    comment_discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=CollectionTaskStatus.DRAFT.value)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(100))
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_recipients: Mapped[list | None] = mapped_column(JSONB, default=list)
    outreach_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    outreach_provider: Mapped[str] = mapped_column(String(50), default="smtp", nullable=False)
    outreach_dry_run: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    outreach_templates: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    email_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_contact_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deduped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profile_fetched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profile_failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_out_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hashtag_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    post_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment_author_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_below_min_followers_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_excluded_keyword_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_summary: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    run_checkpoint: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    email_logs: Mapped[list["EmailLog"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    candidates: Mapped[list["CollectionTaskCandidate"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    parent_task: Mapped["CollectionTask | None"] = relationship(
        remote_side=[id],
        back_populates="child_task_rows",
    )
    child_task_rows: Mapped[list["CollectionTask"]] = relationship(
        back_populates="parent_task",
        cascade="all, delete-orphan",
        order_by="CollectionTask.batch_round_index",
    )
