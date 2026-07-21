# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：category discovery
"""类目采集：根据类目 + 国家 + 平台自动生成关键词与链接种子。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.collection_task import CollectionTask
from app.schemas.collection_task import resolve_task_platform_fields
from app.services.instagram_unified_discovery import normalize_collection_mode

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_PLATFORM_KEYWORD_TEMPLATES: dict[str, tuple[str, ...]] = {
    "instagram": (
        "{category}",
        "{category} influencer",
        "{category} creator",
        "{category} brand collab",
        "{category_slug}",
    ),
    "tiktok": (
        "{category}",
        "{category} tiktok",
        "{category} creator",
        "{category} influencer",
    ),
    "youtube": (
        "{category}",
        "{category} review",
        "{category} youtuber",
        "{category} channel",
    ),
    "facebook": (
        "{category}",
        "{category} creator",
        "{category} influencer",
        "{category} page",
    ),
    "pinterest": (
        "{category}",
        "{category} ideas",
        "{category} product curator",
        "pinterest {category}",
    ),
    "ltk": (
        "{category}",
        "{category} ltk",
        "ltk {category}",
        "{category} shopltk",
    ),
    "shopmy": (
        "{category}",
        "{category} shopmy",
        "shop my {category}",
        "{category} amazon storefront",
    ),
}

_COMMON_TEMPLATES: tuple[str, ...] = (
    "{category}",
    "{category} influencer",
    "{category} creator",
    "{category} blogger",
)


@dataclass(frozen=True)
class CategoryDiscoveryExpansion:
    keywords: list[str]
    input_urls: list[str]
    generated_keywords: list[str]
    supplementary_keywords: list[str]


def slugify_category(category: str) -> str:
    text = (category or "").strip().lower()
    if not text:
        return ""
    return _SLUG_RE.sub("", text)


def _render_template(template: str, *, category: str, category_slug: str, country: str | None) -> str:
    values = {
        "category": category.strip(),
        "category_slug": category_slug,
        "country": (country or "").strip(),
    }
    rendered = template.format(**values).strip()
    if "{country}" in template and not values["country"]:
        return ""
    return rendered


def _dedupe_keywords(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = (item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _dedupe_urls(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = (item or "").strip()
        if not text:
            continue
        key = text.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def generate_category_keywords(
    *,
    category: str,
    country: str | None,
    platforms: list[str],
    supplementary_keywords: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    category_text = (category or "").strip()
    if not category_text:
        return [], []

    category_slug = slugify_category(category_text)
    generated: list[str] = []

    for template in _COMMON_TEMPLATES:
        rendered = _render_template(
            template,
            category=category_text,
            category_slug=category_slug,
            country=country,
        )
        if rendered:
            generated.append(rendered)

    if country:
        generated.append(f"{category_text} {country.strip()}")
        generated.append(f"{country.strip()} {category_text} influencer")

    for platform in platforms:
        for template in _PLATFORM_KEYWORD_TEMPLATES.get(platform, ()):
            rendered = _render_template(
                template,
                category=category_text,
                category_slug=category_slug,
                country=country,
            )
            if rendered:
                generated.append(rendered)

    generated = _dedupe_keywords(generated)
    supplementary = _dedupe_keywords([k for k in (supplementary_keywords or []) if k and str(k).strip()])
    merged = _dedupe_keywords([*generated, *supplementary])
    return merged, generated


def generate_category_link_urls(*, category: str, platforms: list[str]) -> list[str]:
    slug = slugify_category(category)
    if not slug:
        return []

    urls: list[str] = []
    if "pinterest" in platforms:
        urls.append(f"https://www.pinterest.com/{slug}/")
    if "ltk" in platforms:
        urls.append(f"https://www.shopltk.com/explore/{slug}")
    if "shopmy" in platforms:
        urls.append(f"https://shopmy.us/{slug}")
    return _dedupe_urls(urls)


def expand_category_discovery_inputs(
    *,
    category: str,
    country: str | None,
    platforms: list[str],
    supplementary_keywords: list[str] | None = None,
    existing_input_urls: list[str] | None = None,
) -> CategoryDiscoveryExpansion:
    merged_keywords, generated_keywords = generate_category_keywords(
        category=category,
        country=country,
        platforms=platforms,
        supplementary_keywords=supplementary_keywords,
    )
    link_urls = generate_category_link_urls(category=category, platforms=platforms)
    merged_urls = _dedupe_urls([*(existing_input_urls or []), *link_urls])
    supplementary = _dedupe_keywords([k for k in (supplementary_keywords or []) if k and str(k).strip()])
    return CategoryDiscoveryExpansion(
        keywords=merged_keywords,
        input_urls=merged_urls,
        generated_keywords=generated_keywords,
        supplementary_keywords=supplementary,
    )


def apply_category_discovery_expansion(task: CollectionTask) -> CategoryDiscoveryExpansion | None:
    if normalize_collection_mode(task.collection_mode) != "category_discovery":
        return None

    category = (task.category or "").strip()
    if not category:
        raise ValueError("类目采集模式必须填写类目")

    _, platforms = resolve_task_platform_fields(task.platform, task.platforms or [], require_platforms=True)
    expansion = expand_category_discovery_inputs(
        category=category,
        country=task.country,
        platforms=platforms,
        supplementary_keywords=task.keywords or [],
        existing_input_urls=task.input_urls or [],
    )
    task.keywords = expansion.keywords
    task.input_urls = expansion.input_urls
    return expansion
