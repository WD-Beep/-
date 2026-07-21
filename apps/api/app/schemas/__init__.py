# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：init
from app.schemas.collection_task import (
    CollectionTaskCreate,
    CollectionTaskFilter,
    CollectionTaskRead,
    CollectionTaskUpdate,
)
from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.dashboard import DashboardSummary, PlatformCount
from app.schemas.email_log import EmailLogFilter, EmailLogRead
from app.schemas.influencer import (
    InfluencerCreate,
    InfluencerFilter,
    InfluencerRead,
    InfluencerUpdate,
)

__all__ = [
    "CollectionTaskCreate",
    "CollectionTaskFilter",
    "CollectionTaskRead",
    "CollectionTaskUpdate",
    "DashboardSummary",
    "EmailLogFilter",
    "EmailLogRead",
    "InfluencerCreate",
    "InfluencerFilter",
    "InfluencerRead",
    "InfluencerUpdate",
    "PaginatedResponse",
    "PaginationParams",
    "PlatformCount",
]
