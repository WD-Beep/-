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
    extracted_knowledge = link_knowledge_base.extracted_knowledge or {}
    effective_selling_points = merge_selling_points(
        link_knowledge_base.manual_selling_points,
        extracted_knowledge.get("selling_points"),
    )
    return {
        "link_knowledge": {
            "id": link_knowledge_base.id,
            "name": link_knowledge_base.name,
            "url": link_knowledge_base.url,
            "domain": link_knowledge_base.domain,
            "summary": link_knowledge_base.summary,
            "manual_selling_points": link_knowledge_base.manual_selling_points or [],
            "effective_selling_points": effective_selling_points,
            "extracted_knowledge": extracted_knowledge,
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


def _readable_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def merge_selling_points(manual_points: Any, extracted_points: Any) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in [*_readable_list(manual_points), *_readable_list(extracted_points)]:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _script_length(text: str, language: str | None) -> int:
    normalized_language = (language or "").lower()
    if normalized_language.startswith("zh") or any("\u4e00" <= char <= "\u9fff" for char in text):
        return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return len(text.split())


def _link_script_validation_errors(data: dict[str, Any], config: dict[str, Any]) -> list[str]:
    template = config.get("message_template") or {}
    rules = template.get("generation_rules") or {}
    errors: list[str] = []
    min_length = int(rules.get("min_length") or 90)
    max_length = int(rules.get("max_length") or 300)
    language = str(rules.get("language") or config.get("language") or "en")
    long_copy_fields = ("email_first_touch", "youtube_pitch")
    for field in long_copy_fields:
        text = str(data.get(field) or "").strip()
        length = _script_length(text, language)
        if length < min_length:
            errors.append(f"{field} length {length} is below {min_length}")
        if max_length and length > max_length:
            errors.append(f"{field} length {length} exceeds {max_length}")
    for field in ("instagram_dm", "tiktok_dm"):
        text = str(data.get(field) or "").strip()
        length = _script_length(text, language)
        if length < 45:
            errors.append(f"{field} length {length} is below 45")
        if length > 90:
            errors.append(f"{field} length {length} exceeds 90")
    combined = "\n".join(str(data.get(field) or "") for field in SCRIPT_KEYS).casefold()
    required = [str(item).strip() for item in rules.get("required_content") or [] if str(item).strip()]
    cta = str(rules.get("cta") or "").strip()
    if cta:
        required.append(cta)
    for item in required:
        if item.casefold() not in combined:
            errors.append(f"missing required content: {item}")
    for item in rules.get("forbidden_content") or []:
        text = str(item).strip()
        if text and text.casefold() in combined:
            errors.append(f"contains forbidden content: {text}")
    link_knowledge = config.get("link_knowledge") or {}
    manual_points = _readable_list(link_knowledge.get("manual_selling_points"))
    effective_points = _readable_list(link_knowledge.get("effective_selling_points"))
    priority_points = manual_points or effective_points
    if priority_points and not any(point.casefold() in combined for point in priority_points):
        errors.append("missing supplied selling point")
    return errors


def _join_phrase(items: list[str], fallback: str) -> str:
    if not items:
        return fallback
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:2])


def _strip_cjk_text(value: str) -> str:
    replacements = {
        "＊": "'",
        "＇": "'",
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "〞": " - ",
        "—": " - ",
        "–": " - ",
        "每": " - ",
        "，": ", ",
        "。": ". ",
        "：": ": ",
        "；": "; ",
        "（": "(",
        "）": ")",
    }
    cleaned = value or ""
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    cleaned = "".join(" " if "\u4e00" <= char <= "\u9fff" else char for char in cleaned)
    cleaned = "".join(char for char in cleaned if char in "\t\n\r" or " " <= char <= "~")
    return " ".join(cleaned.split())


def _english_brand_name(snapshot: dict[str, Any]) -> str:
    knowledge = snapshot.get("link_knowledge") or {}
    extracted = knowledge.get("extracted_knowledge") or {}
    candidates = [
        extracted.get("brand_name"),
        extracted.get("brand"),
        knowledge.get("brand_name"),
        knowledge.get("name"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and not any("\u4e00" <= char <= "\u9fff" for char in text):
            return text
    return "our brand"


def _required_offer_line(snapshot: dict[str, Any]) -> str:
    link = str((snapshot.get("link_knowledge") or {}).get("url") or "").strip()
    link_part = f" Product link: {link}" if link else ""
    return (
        "We would like to invite you to create a video and post it on Amazon and/or your social media channels."
        f"{link_part} You can also join our Amazon Affiliate Program and earn 10%-30% commission on qualified sales."
    )


def _append_if_missing(text: str, required: str, needles: tuple[str, ...]) -> str:
    haystack = text.casefold()
    if all(needle.casefold() in haystack for needle in needles):
        return text
    separator = "\n\n" if "\n" in text else " "
    return f"{text.strip()}{separator}{required}".strip()


def _compact_required_dm(snapshot: dict[str, Any], brand: str) -> str:
    link = str((snapshot.get("link_knowledge") or {}).get("url") or "").strip()
    link_part = f" Product link: {link}" if link else ""
    return (
        f"{brand} would love to explore a creator video for Amazon or your social channels."
        f"{link_part} We can also invite you to our Amazon Affiliate Program with 10%-30% commission."
    )


def _enforce_link_script_business_requirements(
    data: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_script_output(data)
    brand = _english_brand_name(snapshot)
    required = _required_offer_line(snapshot)
    compact = _compact_required_dm(snapshot, brand)
    required_needles = ("Amazon", "Affiliate", "10%-30%")

    for field in ("match_reason", "email_first_touch", "instagram_dm", "tiktok_dm", "youtube_pitch", "follow_up_1", "follow_up_2", "negotiation_reply", "comment_script"):
        normalized[field] = _strip_cjk_text(str(normalized.get(field) or ""))

    normalized["email_subjects"] = [
        _strip_cjk_text(str(subject)) for subject in normalized.get("email_subjects") or [] if _strip_cjk_text(str(subject))
    ]
    if not normalized["email_subjects"]:
        display = (snapshot.get("influencer") or {}).get("display_name") or (snapshot.get("influencer") or {}).get("username") or "Creator"
        normalized["email_subjects"] = [f"{brand} collaboration idea for {display}"]
    normalized["personalization_points"] = [
        _strip_cjk_text(str(point)) for point in normalized.get("personalization_points") or [] if _strip_cjk_text(str(point))
    ]

    for field in ("email_first_touch", "youtube_pitch"):
        text = str(normalized.get(field) or "").strip()
        if brand.casefold() not in text.casefold():
            text = f"{brand} is looking for creators whose content style feels practical and authentic.\n\n{text}".strip()
        normalized[field] = _append_if_missing(text, required, required_needles)

    for field in ("instagram_dm", "tiktok_dm"):
        text = str(normalized.get(field) or "").strip()
        if not text:
            text = compact
        normalized[field] = _append_if_missing(text, compact, required_needles)

    if not normalized["match_reason"]:
        category = (snapshot.get("influencer") or {}).get("category") or "content"
        normalized["match_reason"] = f"This creator's {category} profile style can support a natural {brand} collaboration."
    return normalized


def _first_touch_script(
    *,
    display: str,
    brand: str,
    product: str,
    category: str,
    match_reason: str,
    selling_points: list[str],
    collaboration_angles: list[str],
) -> str:
    selling = _join_phrase(selling_points, "a practical product benefit your audience can understand quickly")
    angle = _join_phrase(collaboration_angles, f"a natural {category} routine")
    return (
        f"Hi {display},\n\n"
        f"I liked how naturally you create {category} content, especially the way your recommendations feel practical "
        "and easy for your audience to picture using in real life.\n\n"
        f"Why I thought of you: {match_reason} {brand}'s {product} is built around {selling}, which could give you "
        "a clear, useful angle instead of a generic product mention.\n\n"
        f"Collaboration idea: we can share the product details and explore a lightweight post, reel, story, or short "
        f"review angle around {angle}. We can keep the brief simple so it fits your normal content style.\n\n"
        "Would you be open to taking a quick look at the details? If it feels aligned, I can send the product info, "
        "gifting terms, and a simple content outline.\n\n"
        "Best,\n"
        "[Your Name]"
    )


def _fallback_script(snapshot: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    influencer = snapshot["influencer"]
    knowledge = snapshot["link_knowledge"]["extracted_knowledge"]
    display = influencer.get("display_name") or influencer.get("username") or "there"
    brand = _english_brand_name(snapshot)
    product = knowledge.get("product_name") or "your product"
    category = influencer.get("category") or "content"
    match_reason = f"{display} creates {category} content that can connect with {brand}."
    email_first_touch = _first_touch_script(
        display=display,
        brand=brand,
        product=product,
        category=category,
        match_reason=match_reason,
        selling_points=_readable_list(snapshot["link_knowledge"].get("effective_selling_points"))
        or _readable_list(knowledge.get("selling_points")),
        collaboration_angles=_readable_list(knowledge.get("collaboration_angles")),
    )
    notes = reason or OPENAI_NOT_CONFIGURED_MSG
    return _enforce_link_script_business_requirements({
        "match_reason": match_reason,
        "personalization_points": [category],
        "email_subjects": [f"{brand} x {display}", f"Collab idea for {display}"],
        "email_first_touch": email_first_touch,
        "instagram_dm": (
            f"Hi {display}, I liked your {category} content and thought {brand}'s {product} could fit your audience. "
            "Would you be open to a lightweight collaboration? I can send product details, gifting terms, and a simple "
            "content idea if it sounds relevant."
        ),
        "tiktok_dm": f"Hi {display}, your {category} videos feel like a fit for {brand}. Want details?",
        "youtube_pitch": email_first_touch,
        "follow_up_1": (
            f"Hi {display}, just checking whether a {brand} collaboration could be interesting. Happy to keep it "
            "lightweight and send the details for you to review first."
        ),
        "follow_up_2": "Happy to share product details and keep this lightweight if helpful.",
        "negotiation_reply": "Thanks for sharing your rates. Could you send the deliverables and timeline you recommend?",
        "comment_script": "Love this routine, it feels very natural.",
        "notes": notes,
    }, snapshot)


async def generate_scripts_for_influencer(
    db: AsyncSession,
    link_knowledge_base: LinkKnowledgeBase,
    product_row: ProductInfluencer,
    global_row: GlobalInfluencerProfile,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = await build_input_snapshot(db, link_knowledge_base, product_row, global_row, config)
    config = {
        **config,
        "link_knowledge": {
            "manual_selling_points": snapshot["link_knowledge"].get("manual_selling_points") or [],
            "effective_selling_points": snapshot["link_knowledge"].get("effective_selling_points") or [],
        },
    }
    if not settings.is_openai_configured:
        return _fallback_script(snapshot), snapshot

    prompt = f"""You are an expert overseas influencer outreach copywriter. Generate personalized English outreach scripts based on link knowledge and influencer information.
Rules:
1. Only use the provided brand knowledge and influencer information. Do not invent product claims.
2. Write natural, complete human copy that can be sent directly after light editing.
3. Reflect the match between creator content and brand/product selling points.
4. If platform is Instagram, emphasize DM and short email. If YouTube, use a more formal pitch.
5. If influencer information is limited, generate conservative usable copy.
6. email_first_touch and youtube_pitch must be 90-130 words, split into 4-5 short paragraphs, and include:
   greeting, why this creator fits, product value, collaboration idea, soft CTA, and signature placeholder.
7. instagram_dm and tiktok_dm must be 45-70 words: short enough for DM, but not a one-line generic pitch.
8. Avoid emojis unless the influencer profile clearly uses that tone.
9. Treat config.message_template as the required writing framework when present. Follow its content, tone, length, structure, required content, forbidden content, and CTA rules while still personalizing each creator.
10. Select 2-4 relevant items only from link_knowledge.effective_selling_points. Manual selling points appear first and take priority. Never invent a selling point.
11. Final scripts must be pure English. Do not output Chinese characters in recipient-facing copy.
12. Use the English brand name from link_knowledge.extracted_knowledge.brand_name. If the brand name is not English, use "our brand" instead of Chinese text.
13. Open long email/pitch copy by introducing the brand first, then explain why this creator's homepage/profile style is a fit.
14. Ask the creator to make a video and upload/post it to Amazon and/or their relevant social media platform.
15. Include the product link from link_knowledge.url when available.
16. Mention they can join our Amazon Affiliate Program and earn 10%-30% commission. Keep this as an invitation, not a guaranteed income claim.
17. Return strict JSON only, no Markdown or explanations.

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
        normalized = _enforce_link_script_business_requirements(parsed, snapshot)
        validation_errors = _link_script_validation_errors(normalized, config)
        if validation_errors:
            retry_prompt = f"""{prompt}

The previous JSON failed validation:
- {chr(10).join(validation_errors)}
Regenerate the complete JSON and strictly follow the template, length, supplied selling points, structure, and CTA rules."""
            parsed = await chat_completion_json(
                system_prompt="Generate influencer outreach scripts. Return JSON only.",
                user_prompt=retry_prompt,
                temperature=0.45,
                max_tokens=4096,
            )
            normalized = _enforce_link_script_business_requirements(parsed, snapshot)
            validation_errors = _link_script_validation_errors(normalized, config)
        if validation_errors:
            return _fallback_script(snapshot, "; ".join(validation_errors)), snapshot
        return normalized | {"provider": "openai"}, snapshot
    except Exception as exc:
        return _fallback_script(snapshot, str(exc)), snapshot
