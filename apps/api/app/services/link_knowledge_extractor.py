# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：link knowledge extractor
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.ai.openai_client import chat_completion_json


KNOWLEDGE_KEYS = [
    "brand_name",
    "product_name",
    "category",
    "price",
    "target_audience",
    "brand_summary",
    "product_summary",
    "selling_points",
    "brand_tone",
    "collaboration_angles",
    "faq",
    "do_not_claim",
    "keywords",
]


def empty_knowledge() -> dict[str, Any]:
    return {
        "brand_name": "",
        "product_name": "",
        "category": "",
        "price": "",
        "target_audience": "",
        "brand_summary": "",
        "product_summary": "",
        "selling_points": [],
        "brand_tone": "",
        "collaboration_angles": [],
        "faq": [],
        "do_not_claim": [],
        "keywords": [],
    }


def normalize_knowledge(data: dict[str, Any]) -> dict[str, Any]:
    normalized = empty_knowledge()
    for key in KNOWLEDGE_KEYS:
        value = data.get(key)
        if key in {"selling_points", "collaboration_angles", "faq", "do_not_claim", "keywords"}:
            normalized[key] = value if isinstance(value, list) else []
        else:
            normalized[key] = "" if value is None else str(value)
    return normalized


def _heuristic_extract(clean_text: str, url: str, title: str | None = None) -> dict[str, Any]:
    text = " ".join(clean_text.split())
    summary = text[:500]
    words = [part.strip(".,:;()[]").lower() for part in text.split()]
    keywords = []
    for word in words:
        if len(word) >= 5 and word not in keywords:
            keywords.append(word)
        if len(keywords) >= 8:
            break
    knowledge = empty_knowledge()
    knowledge.update(
        {
            "brand_name": (title or "").split("|")[0].strip()[:120],
            "product_name": (title or "").strip()[:120],
            "brand_summary": summary,
            "product_summary": summary,
            "selling_points": keywords[:5],
            "collaboration_angles": ["honest product review", "routine integration"],
            "do_not_claim": ["Do not claim effects that are not present in the source page."],
            "keywords": keywords,
            "source_url": url,
            "provider": "heuristic",
        }
    )
    return knowledge


async def extract_link_knowledge(clean_text: str, url: str, title: str | None = None) -> dict[str, Any]:
    if not settings.is_openai_configured:
        return _heuristic_extract(clean_text, url, title)

    prompt = f"""You are a brand research extraction assistant. Extract brand/product knowledge useful for influencer outreach.
Rules:
1. Only use the provided URL and page content. Do not invent facts.
2. If information is missing, use empty strings or empty arrays.
3. Return strict JSON only, no Markdown.
4. Focus on brand name, product name, selling points, audience, tone, collaboration angles, and cautions.
5. Do not generate outreach scripts.

URL: {url}
Title: {title or ""}
Content:
{clean_text[:30000]}

Return JSON:
{{
  "brand_name": "",
  "product_name": "",
  "category": "",
  "price": "",
  "target_audience": "",
  "brand_summary": "",
  "product_summary": "",
  "selling_points": [],
  "brand_tone": "",
  "collaboration_angles": [],
  "faq": [],
  "do_not_claim": [],
  "keywords": []
}}"""
    try:
        parsed = await chat_completion_json(
            system_prompt="Extract structured brand/product knowledge. Return JSON only.",
            user_prompt=prompt,
            temperature=0.2,
            max_tokens=4096,
        )
        return normalize_knowledge(parsed) | {"provider": "openai"}
    except Exception as exc:
        fallback = _heuristic_extract(clean_text, url, title)
        fallback["error_message"] = str(exc)
        return fallback


def _join_items(items: list[Any]) -> str:
    parts = []
    for item in items:
        if isinstance(item, dict):
            text = " - ".join(str(v) for v in item.values() if v)
        else:
            text = str(item)
        if text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def build_chunks_from_extracted_knowledge(
    extracted_knowledge: dict[str, Any] | None,
    clean_text: str | None,
) -> list[dict[str, Any]]:
    data = normalize_knowledge(extracted_knowledge or {})
    chunk_defs: list[tuple[str, str, str]] = [
        ("brand_intro", "Brand summary", data["brand_summary"]),
        ("product_features", "Product summary", data["product_summary"]),
        ("selling_points", "Selling points", _join_items(data["selling_points"])),
        ("collaboration_angle", "Collaboration angles", _join_items(data["collaboration_angles"])),
        ("faq", "FAQ", _join_items(data["faq"])),
        ("warnings", "Claims to avoid", _join_items(data["do_not_claim"])),
    ]
    chunks: list[dict[str, Any]] = []
    for chunk_type, title, content in chunk_defs:
        if content.strip():
            chunks.append({"chunk_type": chunk_type, "title": title, "content": content.strip(), "metadata": {}})
    raw = (clean_text or "").strip()
    if raw:
        chunks.append(
            {
                "chunk_type": "raw_text",
                "title": "Source page excerpt",
                "content": raw[:4000],
                "metadata": {"truncated": len(raw) > 4000},
            }
        )
    return chunks
