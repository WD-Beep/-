"""ProductInfluencer + GlobalInfluencerProfile 投影为 API 红人模型。"""

from __future__ import annotations

from types import SimpleNamespace

from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.influencer import Influencer
from app.models.product_influencer import ProductInfluencer
from app.schemas.influencer import InfluencerRead
def merged_influencer_for_ai(
    product_row: ProductInfluencer,
    global_row: GlobalInfluencerProfile,
) -> Influencer:
    """为 AI 分析构造兼容 Influencer ORM 的临时对象（不落库）。"""
    return Influencer(
        id=product_row.id,
        platform=global_row.platform,
        username=global_row.username,
        display_name=global_row.display_name,
        profile_url=global_row.profile_url,
        platform_unique_id=global_row.platform_unique_id,
        avatar_url=global_row.avatar_url,
        country=global_row.country,
        language=global_row.language,
        category=global_row.category,
        niche=global_row.niche,
        bio=global_row.bio,
        followers_count=global_row.followers_count,
        avg_views=global_row.avg_views,
        avg_likes=global_row.avg_likes,
        avg_comments=global_row.avg_comments,
        engagement_rate=global_row.engagement_rate,
        email=global_row.final_email or global_row.email,
        final_email=global_row.final_email or global_row.email,
        public_email=global_row.public_email,
        business_email=global_row.business_email,
        email_source=global_row.email_source,
        contact_credibility=global_row.contact_credibility,
        contact_score=global_row.contact_score,
        contact_credibility_level=global_row.contact_credibility_level,
        website=global_row.website,
        contact_page=global_row.contact_page,
        linktree_url=global_row.linktree_url,
        whatsapp=global_row.whatsapp,
        telegram=global_row.telegram,
        other_social_links=global_row.other_social_links or [],
        contact_discovered_at=global_row.contact_discovered_at,
        contact_sources=global_row.contact_sources or [],
        contact_fetch_status=global_row.contact_fetch_status,
        contact_fetch_error=global_row.contact_fetch_error,
        product_fit=product_row.product_fit,
        data_completeness=global_row.data_completeness,
        has_brand_collaboration=global_row.has_brand_collaboration,
        estimated_collab_price=global_row.estimated_collab_price,
        collaboration_formats=global_row.collaboration_formats or [],
        content_topics=global_row.content_topics or [],
        audience_country=global_row.audience_country,
        audience_language=global_row.audience_language,
        travel_fit_score=product_row.travel_fit_score,
        purchasing_power_score=product_row.purchasing_power_score,
        sales_potential_score=product_row.sales_potential_score,
        audience_match_score=product_row.audience_match_score,
        roi_forecast=product_row.roi_forecast,
        recent_post_titles=global_row.recent_post_titles or [],
        recent_post_urls=global_row.recent_post_urls or [],
        last_post_at=global_row.last_post_at,
        posting_frequency=global_row.posting_frequency,
        tags=product_row.tags or [],
        engagement_score=product_row.engagement_score,
        content_match_score=product_row.content_match_score,
        contactability_score=product_row.contactability_score,
        commercial_signal_score=product_row.commercial_signal_score,
        activity_score=product_row.activity_score,
        risk_score=product_row.risk_score,
        final_priority=product_row.final_priority,
        score=product_row.score,
        risk_level=product_row.risk_level,
        score_reason=product_row.score_reason,
        ai_summary=product_row.ai_summary,
        ai_collaboration_suggestion=product_row.ai_collaboration_suggestion,
        ai_outreach_message=product_row.ai_outreach_message,
        follow_status=product_row.follow_status,
        owner=product_row.owner,
        note=product_row.note,
        next_follow_up_at=product_row.next_follow_up_at,
        last_contacted_at=product_row.last_contacted_at,
        last_reply_at=product_row.last_reply_at,
        invalid_reason=product_row.invalid_reason,
        blacklist_reason=product_row.blacklist_reason,
        last_collected_at=product_row.last_collected_at,
        source_discovery_type=product_row.source_discovery_type,
        source_post_url=product_row.source_post_url,
        source_comment_url=product_row.source_comment_url,
        source_comment_text=product_row.source_comment_text,
        created_at=product_row.created_at,
        updated_at=product_row.updated_at,
    )


def to_influencer_read(
    product_row: ProductInfluencer,
    global_row: GlobalInfluencerProfile,
) -> InfluencerRead:
    merged = merged_influencer_for_ai(product_row, global_row)
    read = InfluencerRead.model_validate(merged)
    return read.model_copy(
        update={
            "id": product_row.id,
            "lead_status": product_row.follow_status,
            "lead_priority": product_row.final_priority,
            "owner_name": product_row.owner,
            "lead_note": product_row.note,
        }
    )


def apply_ai_to_product_record(
    product_row: ProductInfluencer,
    analysis,
    *,
    global_row: GlobalInfluencerProfile | None = None,
) -> None:
    from app.services.scoring import calculate_composite_score_from_metrics, calculate_risk_level

    product_row.ai_summary = analysis.ai_summary or None
    product_row.ai_collaboration_suggestion = analysis.ai_collaboration_suggestion or None
    product_row.ai_outreach_message = analysis.ai_outreach_message or None
    product_row.tags = analysis.tags
    product_row.risk_level = analysis.risk_level
    product_row.score_reason = analysis.score_reason
    product_row.product_fit = analysis.product_fit
    product_row.travel_fit_score = analysis.travel_fit_score
    product_row.purchasing_power_score = analysis.purchasing_power_score
    product_row.sales_potential_score = analysis.sales_potential_score
    product_row.audience_match_score = analysis.audience_match_score
    product_row.roi_forecast = analysis.roi_forecast
    if global_row is not None:
        composite = calculate_composite_score_from_metrics(
            product_fit=product_row.product_fit,
            travel_fit_score=product_row.travel_fit_score,
            purchasing_power_score=product_row.purchasing_power_score,
            sales_potential_score=product_row.sales_potential_score,
            audience_match_score=product_row.audience_match_score,
            engagement_rate=global_row.engagement_rate,
            email=global_row.final_email or global_row.email,
        )
        if composite is not None:
            product_row.score = composite
            product_row.risk_level = calculate_risk_level(composite)
