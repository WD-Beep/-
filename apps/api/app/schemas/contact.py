# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：contact
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.influencer import InfluencerRead


class ContactRefreshResult(BaseModel):
    influencer: InfluencerRead
    contact_fetch_status: str
    contact_fetch_error: str | None = None
    contact_discovered_at: datetime | None = None
    contact_sources: list[dict[str, Any]] = Field(default_factory=list)
    final_email: str | None = None
    email_source: str | None = None
    contact_score: float | None = None
    contact_credibility_level: str | None = None
    contact_page: str | None = None
    linktree_url: str | None = None
    whatsapp: str | None = None
    telegram: str | None = None
