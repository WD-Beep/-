from pydantic import BaseModel, Field


class SchedulerRefreshResponse(BaseModel):
    registered: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
    message: str
