from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.link_knowledge_base import LinkKnowledgeBase, LinkKnowledgeChunk
from app.models.product_influencer import ProductInfluencer
from app.services.ai.openai_client import OPENAI_NOT_CONFIGURED_MSG, chat_completion_json


SCRIPT_KEYS = [
    "match_reason",
    "personalization_points",
    "email_subjects",
    "email_first_touch",
    "instagram_dm",
    "tiktok_dm",
    "youtube_pitch",
    "follow_up_1",
    "follow_up_2",
    "negotiation_reply",
    "comment_script",
    "notes",
]


def _influencer_snapshot(product_row: ProductInfluencer, global_row: GlobalInfluencerProfile) -> dict[str, Any]:
    return {
        "id": product_row.id,
        "platform": global_row.platform,
        "username": global_row.username,
        "display_name": global_row.display_name,
        "profile_url": global_row.profile_url,
        "bio": global_row.bio,
        "category": global_row.category,
        "niche": global_row.niche,
        "followers_count": global_row.followers_count,
        "engagement_rate": global_row.engagement_rate,
        "country": global_row.country,
        "language": global_row.language,
        "recent_post_titles": global_row.recent_post_titles or [],
        "content_topics": global_row.content_topics or [],
        "product_fit": product_row.product_fit,
        "score": product_row.score,
        "ai_summary": product_row.ai_summary,
        "ai_collaboration_suggestion": product_row.ai_collaboration_suggestion,
        "tags": product_row.tags or [],
    }


async def build_input_snapshot(
    db: AsyncSession,
    link_knowledge_base: LinkKnowledgeBase,
    product_row: ProductInfluencer,
    global_row: GlobalInfluencerProfile,
    config: dict[str, Any],
) -> dict[str, Any]:
    chunks = (
        await db.scalars(
            select(LinkKnowledgeChunk)
            .where(LinkKnowledgeChunk.link_knowledge_base_id == link_knowledge_base.id)
            .order_by(LinkKnowledgeChunk.chunk_index.asc())
        )
    ).all()
    return {
        "link_knowledge": {
            "id": link_knowledge_base.id,
            "name": link_knowledge_base.name,
            "url": link_knowledge_base.url,
            "domain": link_knowledge_base.domain,
            "summary": link_knowledge_base.summary,
            "extracted_knowledge": link_knowledge_base.extracted_knowledge or {},
            "chunks": [
                {
                    "chunk_type": chunk.chunk_type,
                    "title": chunk.title,
                    "content": chunk.content,
                }
                for chunk in chunks
            ],
        },
        "influencer": _influencer_snapshot(product_row, global_row),
        "config": config,
    }


def normalize_script_output(data: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "match_reason": "",
        "personalization_points": [],
        "email_subjects": [],
        "email_first_touch": "",
        "instagram_dm": "",
        "tiktok_dm": "",
        "youtube_pitch": "",
        "follow_up_1": "",
        "follow_up_2": "",
        "negotiation_reply": "",
        "comment_script": "",
        "notes": "",
    }
    for key in SCRIPT_KEYS:
        value = data.get(key)
        if key in {"personalization_points", "email_subjects"}:
            normalized[key] = value if isinstance(value, list) else ([] if value is None else [str(value)])
        else:
            normalized[key] = "" if value is None else str(value)
    return normalized


def _fallback_script(snapshot: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    influencer = snapshot["influencer"]
    knowledge = snapshot["link_knowledge"]["extracted_knowledge"]
    display = influencer.get("display_name") or influencer.get("username") or "there"
    brand = knowledge.get("brand_name") or snapshot["link_knowledge"].get("name") or "your brand"
    product = knowledge.get("product_name") or "your product"
    category = influencer.get("category") or "content"
    line = (
        f"Hi {display}, I liked how naturally you create {category} content. "
        f"{brand} is exploring creator partnerships around {product}, and your audience could be a good fit."
    )
    notes = reason or OPENAI_NOT_CONFIGURED_MSG
    return {
        "match_reason": f"{display} creates {category} content that can connect with {brand}.",
        "personalization_points": [category],
        "email_subjects": [f"{brand} x {display}", f"Collab idea for {display}"],
        "email_first_touch": line,
        "instagram_dm": f"Hi {display}, loved your {category} content. Open to a {brand} collab idea?",
        "tiktok_dm": f"Hi {display}, your {category} videos feel like a fit for {brand}. Want details?",
        "youtube_pitch": line,
        "follow_up_1": f"Hi {display}, just checking whether a {brand} collaboration could be interesting.",
        "follow_up_2": "Happy to share product details and keep this lightweight if helpful.",
        "negotiation_reply": "Thanks for sharing your rates. Could you send the deliverables and timeline you recommend?",
        "comment_script": "Love this routine, it feels very natural.",
        "notes": notes,
    }


async def generate_scripts_for_influencer(
    db: AsyncSession,
    link_knowledge_base: LinkKnowledgeBase,
    product_row: ProductInfluencer,
    global_row: GlobalInfluencerProfile,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = await build_input_snapshot(db, link_knowledge_base, product_row, global_row, config)
    if not settings.is_openai_configured:
        return _fallback_script(snapshot), snapshot

    prompt = f"""You are an expert overseas influencer outreach copywriter. Generate personalized English outreach scripts based on link knowledge and influencer information.
Rules:
1. Only use the provided brand knowledge and influencer information. Do not invent product claims.
2. Write natural, concise human copy.
3. Reflect the match between creator content and brand/product selling points.
4. If platform is Instagram, emphasize DM and short email. If YouTube, use a more formal pitch.
5. If influencer information is limited, generate conservative usable copy.
6. Return strict JSON only, no Markdown or explanations.

Input:
{json.dumps(snapshot, ensure_ascii=False, default=str)}

Return JSON:
{{
  "match_reason": "",
  "personalization_points": [],
  "email_subjects": [],
  "email_first_touch": "",
  "instagram_dm": "",
  "tiktok_dm": "",
  "youtube_pitch": "",
  "follow_up_1": "",
  "follow_up_2": "",
  "negotiation_reply": "",
  "comment_script": "",
  "notes": ""
}}"""
    try:
        parsed = await chat_completion_json(
            system_prompt="Generate influencer outreach scripts. Return JSON only.",
            user_prompt=prompt,
            temperature=0.55,
            max_tokens=4096,
        )
        return normalize_script_output(parsed) | {"provider": "openai"}, snapshot
    except Exception as exc:
        return _fallback_script(snapshot, str(exc)), snapshot
