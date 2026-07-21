# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：shopping seed discovery
"""导购型 seed（LTK/ShopMy/Pinterest）关键词/类目自动发现。"""

from __future__ import annotations

import re

import httpx
from app.collectors.base import CollectedInfluencer
from app.models.collection_task import CollectionTask
from app.services.amazon_url import parse_amazon_product_input
from app.services.category_discovery import slugify_category
from app.services.link_seed_enrichment import LINK_SEED_PLATFORMS
from app.services.shopping_seed_checkpoint import (
    append_checkpoint_value,
    checkpoint_set,
    increment_checkpoint_count,
)
from app.services.shopping_seed_discovery_provider import discover_shopping_seeds_via_social_search

_WORD_RE = re.compile(r"[a-z0-9]+", re.I)

def expand_keyword_to_handles(keyword: str) -> list[str]:
    """从关键词/类目生成可用于社媒搜索查询的候选用户名。"""
    text = (keyword or "").strip()
    if not text:
        return []

    handles: list[str] = []
    slug = slugify_category(text)
    if slug and len(slug) >= 2:
        handles.append(slug)

    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    if compact and len(compact) >= 2 and compact not in handles:
        handles.append(compact)

    words = _WORD_RE.findall(text.lower())
    if len(words) > 1:
        joined = "".join(words)
        underscored = "_".join(words)
        if len(joined) >= 2 and joined not in handles:
            handles.append(joined)
        if len(underscored) >= 2 and underscored not in handles:
            handles.append(underscored)

    return list(dict.fromkeys(handles))


def _as_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _amazon_product_seeds_for_task(task: CollectionTask) -> list[dict]:
    checkpoint = getattr(task, "run_checkpoint", None) or {}
    seeds = [seed for seed in checkpoint.get("amazon_product_seeds") or [] if isinstance(seed, dict)]
    seen = {str(seed.get("normalized_url") or seed.get("asin") or "").lower() for seed in seeds}
    for raw in getattr(task, "input_urls", None) or []:
        seed = parse_amazon_product_input(str(raw))
        if not seed:
            continue
        key = str(seed.get("normalized_url") or seed.get("asin") or "").lower()
        if key and key not in seen:
            seen.add(key)
            seeds.append(seed)
    return seeds


def _add_unique(values: list[str], value: str | None) -> None:
    text = (value or "").strip()
    if text and text not in values:
        values.append(text)


def build_amazon_seed_search_queries(seed: dict) -> list[str]:
    """Build seed-discovery queries from an Amazon product fingerprint."""
    queries: list[str] = []
    asin = str(seed.get("asin") or "").strip().upper()
    brand = str(seed.get("brand") or "").strip()
    title = str(seed.get("product_title") or "").strip()
    exact_phrases = _as_list(seed.get("exact_phrases"))
    strong_keywords = _as_list(seed.get("strong_keywords") or seed.get("search_keywords"))
    variants = _as_list(seed.get("variant_attributes"))
    broad_category_keywords = _as_list(seed.get("broad_category_keywords"))
    core_phrases = exact_phrases or strong_keywords

    _add_unique(queries, asin)
    if brand and title:
        _add_unique(queries, f"{brand} {title}")
    for variant in variants[:8]:
        if brand:
            _add_unique(queries, f"{brand} {variant}")
    for phrase in core_phrases[:8]:
        if brand and not phrase.lower().startswith(brand.lower()):
            _add_unique(queries, f"{brand} {phrase}")
        else:
            _add_unique(queries, phrase)
    if brand:
        _add_unique(queries, f"{brand} LTK")
        _add_unique(queries, f"{brand} ShopMy")
        _add_unique(queries, f"{brand} Pinterest")
        _add_unique(queries, f"{brand} Amazon finds")
    for broad in broad_category_keywords[:6]:
        _add_unique(queries, f"{broad} LTK")
        _add_unique(queries, f"{broad} ShopMy")
        _add_unique(queries, f"{broad} Pinterest")
        _add_unique(queries, f"{broad} Amazon finds")
    phrase = core_phrases[0] if core_phrases else title
    if brand and phrase:
        phrase_text = phrase if phrase.lower().startswith(brand.lower()) else f"{brand} {phrase}"
        _add_unique(queries, f"{phrase_text} influencer")
        _add_unique(queries, f"{phrase_text} blogger")
        _add_unique(queries, f"site:shopltk.com/explore {phrase_text}")
        _add_unique(queries, f"site:shopmy.us {phrase_text}")
        _add_unique(queries, f"site:pinterest.com {phrase_text}")
        if brand and phrase:
            strong_phrase = phrase
            _add_unique(queries, f'"{brand}" "{strong_phrase}" "shopltk"')
            _add_unique(queries, f'"{brand}" "{strong_phrase}" "shopmy"')
    return queries


def build_shopping_seed_search_keywords_for_task(task: CollectionTask) -> list[str]:
    """Return real provider search queries for seed discovery, including Amazon product fingerprints."""
    keywords: list[str] = []
    for seed in _amazon_product_seeds_for_task(task):
        for query in build_amazon_seed_search_queries(seed):
            _add_unique(keywords, query)
    for keyword in getattr(task, "keywords", None) or []:
        _add_unique(keywords, str(keyword))
    if getattr(task, "category", None):
        _add_unique(keywords, str(task.category))
    return keywords


async def _fetch_seed_profile_text(profile_url: str | None) -> str:
    url = (profile_url or "").strip()
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=12,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text or ""
    except Exception:
        return ""


def _seed_matches_amazon_product_evidence(seed: CollectedInfluencer, product_info, text: str | None) -> bool:
    from app.services.competitor_product_discovery import match_competitor_caption

    parts = [
        text or "",
        getattr(seed, "bio", None) or "",
        getattr(seed, "display_name", None) or "",
        getattr(seed, "username", None) or "",
    ]
    source_meta = getattr(seed, "source_meta", None) or {}
    if isinstance(source_meta, dict):
        for key in ("source_caption", "caption", "title", "description"):
            value = source_meta.get(key)
            if value:
                parts.append(str(value))
    combined = "\n".join(part for part in parts if part)
    match = match_competitor_caption(combined, product_info)
    return bool(match.matched)


async def _filter_seeds_by_amazon_product_evidence(
    seeds: list[CollectedInfluencer],
    task: CollectionTask,
    checkpoint: dict,
) -> list[CollectedInfluencer]:
    amazon_seeds = _amazon_product_seeds_for_task(task)
    if not amazon_seeds or not seeds:
        return seeds

    from app.services.competitor_product_discovery import parse_competitor_product_inputs

    product_info = parse_competitor_product_inputs(task)
    filtered: list[CollectedInfluencer] = []
    rejected = 0
    for seed in seeds:
        platform = (getattr(seed, "platform", None) or "").strip().lower()
        text = ""
        if platform in {"ltk", "shopmy", "pinterest"}:
            text = await _fetch_seed_profile_text(seed.profile_url)
        if _seed_matches_amazon_product_evidence(seed, product_info, text):
            filtered.append(seed)
        else:
            rejected += 1

    diagnostics = checkpoint.setdefault("shopping_seed_discovery", {})
    if isinstance(diagnostics, dict):
        diagnostics["product_evidence_filter_enabled"] = True
        diagnostics["product_evidence_filtered_count"] = rejected
        diagnostics["product_evidence_verified_count"] = len(filtered)
        if seeds and rejected == len(seeds) and not filtered:
            diagnostics["zero_seed_reason"] = "seed_found_but_no_product_evidence"
    checkpoint["seed_product_evidence_filtered_count"] = rejected
    return filtered


async def discover_shopping_seed_profiles(
    *,
    keywords: list[str],
    seed_platforms: list[str],
    category: str | None = None,
    limit: int = 100,
    completed_queries: set[str] | None = None,
    on_query_complete=None,
    on_query_error=None,
    on_query_skip=None,
    on_provider_unavailable=None,
) -> list[CollectedInfluencer]:
    """发现导购 seed（LTK / ShopMy / Pinterest）。

    不再使用 Instagram / TikTok / YouTube / Facebook 作为搜索平台。
    社交平台仅在后续 link_seed_enrichment 阶段用于补全社媒主页详情。
    """
    cap = max(1, min(limit or 100, 500))
    seeds = await discover_shopping_seeds_via_social_search(
        keywords=keywords,
        seed_platforms=seed_platforms,
        category=category,
        limit=cap,
        completed_queries=completed_queries,
        on_query_complete=on_query_complete,
        on_query_error=on_query_error,
        on_query_skip=on_query_skip,
        on_provider_unavailable=on_provider_unavailable,
    )
    return seeds[:cap]


async def discover_shopping_seeds_from_task(task: CollectionTask, db=None) -> list[CollectedInfluencer]:
    from app.schemas.collection_task import resolve_task_platform_fields

    _, platforms = resolve_task_platform_fields(task.platform, task.platforms or [], require_platforms=False)
    seed_platforms = [p for p in platforms if p in LINK_SEED_PLATFORMS]
    if not seed_platforms:
        seed_platforms = sorted(LINK_SEED_PLATFORMS)
    checkpoint = dict(getattr(task, "run_checkpoint", None) or {})
    keywords = build_shopping_seed_search_keywords_for_task(task)

    async def _persist_checkpoint() -> None:
        task.run_checkpoint = checkpoint
        if db is not None:
            await db.commit()

    async def _mark_query_done(query: str, count: int) -> None:
        append_checkpoint_value(checkpoint, "completed_queries", query)
        checkpoint["seed_query_completed_count"] = len(checkpoint_set(checkpoint, "completed_queries"))
        checkpoint["seed_discovered_count"] = int(checkpoint.get("seed_discovered_count") or 0) + max(0, count or 0)
        await _persist_checkpoint()

    async def _mark_query_error(query: str, errors: list[str]) -> None:
        append_checkpoint_value(checkpoint, "failed_queries", query)
        query_errors = checkpoint.setdefault("query_errors", {})
        if isinstance(query_errors, dict):
            query_errors[query] = list(errors)
        await _persist_checkpoint()

    async def _mark_query_skipped(query: str, reason: str) -> None:
        if reason == "checkpoint":
            increment_checkpoint_count(checkpoint, "skipped_due_checkpoint_count")
        else:
            append_checkpoint_value(checkpoint, "skipped_low_signal_queries", query)
        await _persist_checkpoint()

    async def _mark_provider_unavailable(provider: str, state: dict) -> None:
        provider_state = checkpoint.setdefault("provider_availability_state", {})
        if isinstance(provider_state, dict):
            provider_state[provider] = dict(state)
        diagnostics = checkpoint.get("shopping_seed_discovery")
        if isinstance(diagnostics, dict):
            diag_state = diagnostics.setdefault("provider_availability_state", {})
            if isinstance(diag_state, dict):
                diag_state[provider] = dict(state)
        await _persist_checkpoint()

    from app.services.shopping_seed_discovery_provider import build_seed_search_diagnostics

    checkpoint["shopping_seed_discovery"] = build_seed_search_diagnostics(
        keywords=keywords,
        seed_platforms=seed_platforms,
        category=task.category,
        profiles_returned_count=int(checkpoint.get("seed_discovered_count") or 0),
        seed_extracted_count=int(checkpoint.get("seed_discovered_count") or 0),
    )
    await _persist_checkpoint()

    seeds = await discover_shopping_seed_profiles(
        keywords=keywords,
        seed_platforms=seed_platforms,
        category=task.category,
        limit=task.discovery_limit or 100,
        completed_queries=checkpoint_set(checkpoint, "completed_queries"),
        on_query_complete=_mark_query_done,
        on_query_error=_mark_query_error,
        on_query_skip=_mark_query_skipped,
        on_provider_unavailable=_mark_provider_unavailable,
    )
    seeds = await _filter_seeds_by_amazon_product_evidence(seeds, task, checkpoint)
    checkpoint["seed_discovered_count"] = len(seeds)
    task.run_checkpoint = checkpoint
    return seeds
