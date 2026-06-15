"""红人与来源作品链接的多对多关系（同一红人可来自多个作品）。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.collection_task import CollectionTask
    from app.models.product_influencer import ProductInfluencer


class ProductInfluencerSource(Base):
    __tablename__ = "product_influencer_sources"
    __table_args__ = (
        UniqueConstraint(
            "product_influencer_id",
            "source_key",
            name="uq_product_influencer_source_key",
        ),
        Index("ix_product_influencer_sources_product_influencer_id", "product_influencer_id"),
        Index("ix_product_influencer_sources_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_influencer_id: Mapped[int] = mapped_column(
        ForeignKey("product_influencers.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_tasks.id", ondelete="SET NULL"), nullable=True
    )
    import_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_post_url: Mapped[str | None] = mapped_column(String(512))
    source_input_url: Mapped[str | None] = mapped_column(String(512))
    source_platform: Mapped[str | None] = mapped_column(String(50))
    task_name: Mapped[str | None] = mapped_column(String(255))
    source_key: Mapped[str] = mapped_column(String(512), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    product_influencer: Mapped["ProductInfluencer"] = relationship(back_populates="sources")
    task: Mapped["CollectionTask | None"] = relationship()
