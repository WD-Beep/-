# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：cross platform instagram enrichment
"""Cross-platform Instagram email enrichment for non-Instagram candidates."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Sequence

from app.collectors.base import CollectedInfluencer
from app.core.config import settings
from app.services.contact_discovery import extract_emails_from_text, normalize_email
from app.services.high_value_filter import CONTACT_FOUND
from app.services.instagram_urls import (
    extract_profile_username,
    is_valid_instagram_username,
    normalize_instagram_profile_url,
)
from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import profile_to_collected

logger = logging.getLogger(__name__)

ScrapeFunc = Callable[..., Awaitable[object]]

_AUTO_CONFIDENCE = frozenset({"high", "medium"})
_TEXT_SPLIT_RE = re.compile(r"[\s,;，；、|]+")
_DISPLAY_CLEAN_RE = re.compile(r"[^a-z0-9._]+", re.I)


@dataclass(frozen=True)
class InstagramContactProbe:
    profile_url: str
    confidence: str
    reason: str


def _has_email(profile: PlatformCandidateProfile) -> bool:
    return bool(normalize_email(profile.email))


def _walk_values(value, *, depth: int = 0) -> Iterable[str]:
    if depth > 4 or value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk_values(nested, depth=depth + 1)
        return
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _walk_values(nested, depth=depth + 1)


def _text_sources(profile: PlatformCandidateProfile) -> list[str]:
    values: list[str] = []
    for link in profile.other_social_links or []:
        if isinstance(link, dict):
            url = link.get("url")
            if url:
                values.append(str(url))
    values.extend(
        str(value)
        for value in (
            profile.bio,
            profile.website,
            getattr(profile, "contact_page", None),
            profile.profile_url,
        )
        if value
    )
    values.extend(_walk_values(profile.source_meta or {}))
    return values


def _explicit_instagram_probe(profile: PlatformCandidateProfile) -> InstagramContactProbe | None:
    for text in _text_sources(profile):
        for part in _TEXT_SPLIT_RE.split(str(text)):
            if "instagram.com" not in part.lower():
                continue
            url = normalize_instagram_profile_url(part)
            if url:
                return InstagramContactProbe(url, "high", "explicit_instagram_link")
    return None


def _normalized_handle(value: str | None) -> str:
    return (value or "").strip().lower().lstrip("@")


def _display_handle(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    text = _DISPLAY_CLEAN_RE.sub("", text.replace(" ", ""))
    if not is_valid_instagram_username(text):
        return None
    return text


def _candidate_probes(profile: PlatformCandidateProfile) -> list[InstagramContactProbe]:
    explicit = _explicit_instagram_probe(profile)
    if explicit:
        return [explicit]

    probes: list[InstagramContactProbe] = []
    username = _normalized_handle(profile.username)
    if is_valid_instagram_username(username):
        url = normalize_instagram_profile_url(username)
        if url:
            probes.append(InstagramContactProbe(url, "medium", "username_match"))

    display = _display_handle(profile.display_name)
    if display and display != username:
        url = normalize_instagram_profile_url(display)
        if url:
            probes.append(InstagramContactProbe(url, "low", "display_name_guess"))
    return probes[:2]


def _email_from_instagram_result(item: CollectedInfluencer) -> str | None:
    for field in ("final_email", "email", "public_email", "business_email"):
        value = normalize_email(getattr(item, field, None))
        if value:
            return value
    for field in ("bio", "website", "contact_page", "linktree_url"):
        text = getattr(item, field, None)
        if not text:
            continue
        for candidate in extract_emails_from_text(str(text), f"instagram_{field}"):
            if candidate.email:
                return candidate.email
    return None


def _instagram_username(item: CollectedInfluencer) -> str:
    return _normalized_handle(item.username) or _normalized_handle(extract_profile_username(item.profile_url))


def _matches_probe(profile: PlatformCandidateProfile, probe: InstagramContactProbe, item: CollectedInfluencer) -> bool:
    if probe.confidence == "high":
        return True
    source_username = _normalized_handle(profile.username)
    ig_username = _instagram_username(item)
    if probe.confidence == "medium":
        return bool(source_username and source_username == ig_username)
    return False


def _mark_success(
    profile: PlatformCandidateProfile,
    item: CollectedInfluencer,
    *,
    email: str,
    probe: InstagramContactProbe,
) -> None:
    profile.email = email
    item.email = email
    item.final_email = email
    item.public_email = item.public_email or email
    item.contact_fetch_status = item.contact_fetch_status or "success"
    meta = dict(profile.source_meta or {})
    meta.update(
        {
            "email_enriched_from": "instagram",
            "instagram_contact_profile_url": probe.profile_url,
            "instagram_contact_confidence": probe.confidence,
            "instagram_contact_reason": probe.reason,
            "has_email": True,
            "has_contact": True,
            "contact_status": CONTACT_FOUND,
        }
    )
    profile.source_meta = meta


def _mark_low_confidence(
    profile: PlatformCandidateProfile,
    *,
    email: str | None,
    probe: InstagramContactProbe,
) -> None:
    meta = dict(profile.source_meta or {})
    meta.update(
        {
            "instagram_contact_profile_url": probe.profile_url,
            "instagram_contact_confidence": probe.confidence,
            "instagram_contact_reason": probe.reason,
        }
    )
    if email:
        meta["instagram_contact_candidate_email"] = email
    profile.source_meta = meta


def _mark_failure(profile: PlatformCandidateProfile, *, probe: InstagramContactProbe, error: str) -> None:
    meta = dict(profile.source_meta or {})
    meta.update(
        {
            "instagram_contact_profile_url": probe.profile_url,
            "instagram_contact_confidence": probe.confidence,
            "instagram_contact_reason": probe.reason,
            "instagram_contact_error": error[:500],
        }
    )
    profile.source_meta = meta


async def _default_scrape(urls: Sequence[str], **kwargs):
    from app.services.instagram_provider import scrape_instagram_profiles

    return await scrape_instagram_profiles(list(urls), **kwargs)


async def enrich_profiles_with_instagram_email(
    profiles: list[PlatformCandidateProfile],
    *,
    scrape_func: ScrapeFunc | None = None,
) -> list[CollectedInfluencer]:
    """Return collected items after best-effort Instagram email enrichment."""
    scrape = scrape_func or _default_scrape
    collected = [profile_to_collected(profile) for profile in profiles]
    max_attempts = max(0, settings.collection_cross_platform_instagram_enrichment_limit)
    timeout_seconds = max(1, settings.collection_cross_platform_instagram_enrichment_timeout_seconds)
    attempted = 0

    for profile, item in zip(profiles, collected, strict=False):
        platform = (profile.platform or "").strip().lower()
        if platform == "instagram" or _has_email(profile) or item.final_email or item.email:
            continue
        if attempted >= max_attempts:
            break

        probes = _candidate_probes(profile)
        if not probes:
            continue

        for probe in probes:
            if attempted >= max_attempts:
                break
            attempted += 1
            try:
                result = await asyncio.wait_for(
                    scrape([probe.profile_url]),
                    timeout=timeout_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "Instagram email enrichment failed for %s %s via %s: %s",
                    profile.platform,
                    profile.profile_url,
                    probe.profile_url,
                    exc,
                )
                _mark_failure(profile, probe=probe, error=str(exc) or exc.__class__.__name__)
                break

            result_items = list(getattr(result, "profiles", None) or [])
            errors = list(getattr(result, "errors", None) or [])
            if not result_items:
                if errors:
                    _mark_failure(profile, probe=probe, error="; ".join(str(err) for err in errors[:2]))
                continue

            ig_item = result_items[0]
            email = _email_from_instagram_result(ig_item)
            if probe.confidence not in _AUTO_CONFIDENCE:
                _mark_low_confidence(profile, email=email, probe=probe)
                continue
            if not email:
                continue
            if not _matches_probe(profile, probe, ig_item):
                _mark_low_confidence(profile, email=email, probe=probe)
                continue
            _mark_success(profile, item, email=email, probe=probe)
            break

    return collected
