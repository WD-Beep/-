# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：scheduler
from pydantic import BaseModel, Field


class SchedulerRefreshResponse(BaseModel):
    registered: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
    message: str
