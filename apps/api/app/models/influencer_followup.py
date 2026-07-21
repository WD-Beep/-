# 文件说明：后端数据库模型，定义业务数据表结构；当前文件：influencer followup
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.influencer import Influencer
    from app.models.product_influencer import ProductInfluencer


class InfluencerFollowup(Base):
    __tablename__ = "influencer_followups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    product_influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_influencers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(50))
    new_status: Mapped[str | None] = mapped_column(String(50))
    content: Mapped[str | None] = mapped_column(Text)
    operator_name: Mapped[str | None] = mapped_column(String(100))
    contact_channel: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    influencer: Mapped["Influencer | None"] = relationship(back_populates="followups")
    product_influencer: Mapped["ProductInfluencer | None"] = relationship(back_populates="followups")
