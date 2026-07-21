# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：influencer lead
from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from app.schemas.common import ORMModel


class InfluencerLeadUpdate(BaseModel):
    lead_status: str | None = Field(default=None, max_length=50)
    lead_priority: str | None = Field(default=None, max_length=10)
    owner_name: str | None = Field(default=None, max_length=100)
    next_follow_up_at: datetime | None = None
    lead_note: str | None = None
    invalid_reason: str | None = None
    blacklist_reason: str | None = None
    operator_name: str | None = Field(default=None, max_length=100)


class FollowupCreate(BaseModel):
    action_type: str = Field(..., max_length=50)
    content: str | None = None
    contact_channel: str | None = Field(default=None, max_length=50)
    operator_name: str | None = Field(default=None, max_length=100)


class FollowupRead(ORMModel):
    id: int
    influencer_id: int | None = None
    product_influencer_id: int | None = None
    action_type: str
    old_status: str | None
    new_status: str | None
    content: str | None
    operator_name: str | None
    contact_channel: str | None
    created_at: datetime


class InfluencerLeadReadMixin(BaseModel):
    """线索字段别名，映射到 influencers 表已有列。"""

    next_follow_up_at: datetime | None = None
    last_contacted_at: datetime | None = None
    last_reply_at: datetime | None = None
    invalid_reason: str | None = None
    blacklist_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_status(self) -> str | None:
        return getattr(self, "follow_status", None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_priority(self) -> str | None:
        return getattr(self, "final_priority", None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def owner_name(self) -> str | None:
        return getattr(self, "owner", None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_note(self) -> str | None:
        return getattr(self, "note", None)
