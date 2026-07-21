# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：ai analysis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.schemas.ai import (
    AnalyzeInfluencerResponse,
    BatchAnalyzeItemResult,
    BatchAnalyzeResponse,
    InfluencerAnalysisResult,
)
from app.services.ai_service import AnalysisOutput, analyze_influencer
from app.services.influencer_projection import apply_ai_to_product_record, merged_influencer_for_ai, to_influencer_read
from app.services.product_influencer_service import ProductInfluencerService


class AiAnalysisService:
    @staticmethod
    def _to_analysis_result(analysis: AnalysisOutput) -> InfluencerAnalysisResult:
        return InfluencerAnalysisResult(
            ai_summary=analysis.ai_summary,
            ai_collaboration_suggestion=analysis.ai_collaboration_suggestion,
            ai_outreach_message=analysis.ai_outreach_message,
            tags=analysis.tags,
            risk_level=analysis.risk_level,
            score_reason=analysis.score_reason,
            source=analysis.source,
            error_message=analysis.error_message,
        )

    @staticmethod
    async def analyze_and_save(
        db: AsyncSession,
        product_row: ProductInfluencer,
        global_row: GlobalInfluencerProfile,
    ) -> AnalyzeInfluencerResponse:
        merged = merged_influencer_for_ai(product_row, global_row)
        analysis = await analyze_influencer(merged)
        apply_ai_to_product_record(product_row, analysis, global_row=global_row)
        await db.commit()
        await db.refresh(product_row)
        await db.refresh(global_row)

        return AnalyzeInfluencerResponse(
            influencer=to_influencer_read(product_row, global_row),
            analysis=AiAnalysisService._to_analysis_result(analysis),
        )

    @staticmethod
    async def batch_analyze_and_save(
        db: AsyncSession,
        influencer_ids: list[int],
        *,
        product_id: int,
    ) -> BatchAnalyzeResponse:
        results: list[BatchAnalyzeItemResult] = []
        success_count = 0
        failed_count = 0

        for influencer_id in influencer_ids:
            pair = await ProductInfluencerService.get_product_influencer(
                db, product_id=product_id, record_id=influencer_id
            )
            if not pair:
                failed_count += 1
                results.append(
                    BatchAnalyzeItemResult(
                        influencer_id=influencer_id,
                        success=False,
                        message="Influencer not found",
                    )
                )
                continue

            product_row, global_row = pair
            try:
                response = await AiAnalysisService.analyze_and_save(db, product_row, global_row)
                success_count += 1
                results.append(
                    BatchAnalyzeItemResult(
                        influencer_id=influencer_id,
                        success=True,
                        influencer=response.influencer,
                        analysis=response.analysis,
                    )
                )
            except Exception as exc:
                await db.rollback()
                failed_count += 1
                results.append(
                    BatchAnalyzeItemResult(
                        influencer_id=influencer_id,
                        success=False,
                        message=str(exc),
                    )
                )

        return BatchAnalyzeResponse(
            total=len(influencer_ids),
            success_count=success_count,
            failed_count=failed_count,
            results=results,
        )
