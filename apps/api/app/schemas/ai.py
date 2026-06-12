from pydantic import BaseModel, Field

from app.schemas.influencer import InfluencerRead


class InfluencerAnalysisResult(BaseModel):
    ai_summary: str
    ai_collaboration_suggestion: str
    ai_outreach_message: str = ""
    tags: list[str]
    risk_level: str
    score_reason: str
    source: str = Field(description="kimi | heuristic | heuristic_fallback")
    error_message: str | None = Field(default=None, description="Kimi 调用失败时的错误详情")


class AnalyzeInfluencerResponse(BaseModel):
    influencer: InfluencerRead
    analysis: InfluencerAnalysisResult


class BatchAnalyzeRequest(BaseModel):
    influencer_ids: list[int] = Field(..., min_length=1, max_length=100)


class BatchAnalyzeItemResult(BaseModel):
    influencer_id: int
    success: bool
    message: str | None = None
    influencer: InfluencerRead | None = None
    analysis: InfluencerAnalysisResult | None = None


class BatchAnalyzeResponse(BaseModel):
    total: int
    success_count: int
    failed_count: int
    results: list[BatchAnalyzeItemResult]


class AiStatusResponse(BaseModel):
    provider: str
    model: str | None
    configured: bool
    mode: str
