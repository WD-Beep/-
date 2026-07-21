# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：contact discovery
"""联系方式深挖：从 IG 资料与公开外链页面提取邮箱与联系渠道。"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from app.collectors.base import CollectedInfluencer
from app.core.config import settings
from app.models.influencer import Influencer

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
MAILTO_RE = re.compile(r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", re.I)
HREF_RE = re.compile(r"""href=["']([^"'#]+)["']""", re.I)
WHATSAPP_URL_RE = re.compile(r"https?://(?:wa\.me|api\.whatsapp\.com/send)[^\s\"'<>]*", re.I)
WHATSAPP_LABELED_PHONE_RE = re.compile(
    r"(?:whatsapp|whats[\s-]?app|wa\.me)\s*[:\-]?\s*(\+?\d[\d\s\-()]{8,14}\d)",
    re.I,
)
WHATSAPP_E164_RE = re.compile(r"(?<!\d)\+\d{10,15}(?!\d)")
TELEGRAM_RE = re.compile(r"https?://(?:t\.me|telegram\.me)/[^\s\"'<>]+", re.I)

EXCLUDED_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
EXCLUDED_EMAIL_DOMAINS = {"example.com", "email.com", "domain.com", "test.com", "sample.com"}
EXCLUDED_EMAIL_DOMAIN_SUFFIXES = ("ingest.sentry.io",)
EXCLUDED_EMAILS = {"test@example.com", "name@example.com", "email@example.com", "you@example.com"}
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp", "gif", "svg"})
PSEUDO_EMAIL_CONTEXT_RE = re.compile(
    r"[\w.-]+\.(?:png|jpg|jpeg|webp|gif|svg)(?=[@\"'\s<])",
    re.I,
)

BLOCKED_HOSTNAMES = frozenset({"localhost", "0.0.0.0"})

BLOCKED_URL_SUFFIXES = (
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".mp4",
    ".mov",
    ".zip",
    ".rar",
    ".exe",
)

CONTACT_PATH_KEYWORDS = (
    "contact",
    "about",
    "collaboration",
    "collab",
    "work-with-me",
    "workwithme",
    "media-kit",
    "mediakit",
    "press",
    "booking",
    "inquiries",
)

AGGREGATOR_HOSTS = {
    "linktr.ee": "linktree",
    "linktree.com": "linktree",
    "beacons.ai": "beacons",
    "beacons.page": "beacons",
    "stan.store": "stan_store",
    "carrd.co": "carrd",
    "carrd.site": "carrd",
}

SOCIAL_PATTERNS: list[tuple[str, str]] = [
    ("youtube", r"youtube\.com|youtu\.be"),
    ("tiktok", r"tiktok\.com"),
    ("twitter", r"twitter\.com|x\.com"),
    ("facebook", r"facebook\.com|fb\.com"),
    ("linkedin", r"linkedin\.com"),
]

SOURCE_PRIORITY = {
    "business_email": 1,
    "public_email": 2,
    "website_contact": 3,
    "linktree": 4,
    "beacons": 4,
    "stan_store": 4,
    "carrd": 4,
    "website": 5,
    "instagram_bio": 6,
    "other_page": 7,
}

SOURCE_BASE_CONFIDENCE = {
    "business_email": 0.95,
    "public_email": 0.9,
    "website_contact": 0.9,
    "linktree": 0.85,
    "beacons": 0.85,
    "stan_store": 0.85,
    "carrd": 0.8,
    "website": 0.75,
    "instagram_bio": 0.7,
    "other_page": 0.55,
}

CREDIBILITY_LEVEL_SCORE = {"high": 85.0, "medium": 65.0, "low": 40.0, "unknown": 0.0}
CREDIBILITY_LEVEL_LABELS = {"high": "高", "medium": "中", "low": "低", "unknown": "未知"}


@dataclass
class EmailCandidate:
    email: str
    source_type: str
    confidence: float
    url: str | None = None


@dataclass
class ContactDiscoveryResult:
    contact_fetch_status: str = "not_started"
    contact_fetch_error: str | None = None
    contact_discovered_at: datetime | None = None
    contact_sources: list[dict[str, Any]] = field(default_factory=list)
    business_email: str | None = None
    public_email: str | None = None
    final_email: str | None = None
    email: str | None = None
    email_source: str | None = None
    website: str | None = None
    contact_page: str | None = None
    linktree_url: str | None = None
    whatsapp: str | None = None
    telegram: str | None = None
    other_social_links: list[dict[str, str]] = field(default_factory=list)
    contact_score: float | None = None
    contact_credibility_level: str = "unknown"
    contact_credibility: float | None = None
    pages_fetched: int = 0
    pages_failed: int = 0


def _local_part_looks_like_filename(local: str) -> bool:
    if not local:
        return True
    parts = local.lower().split(".")
    if len(parts) >= 2 and parts[-1] in IMAGE_EXTENSIONS:
        return True
    return any(local.lower().endswith(f".{ext}") for ext in IMAGE_EXTENSIONS)


def _pseudo_filename_adjacent_before(text: str, email_start: int, *, max_gap: int = 4) -> bool:
    """仅当图片文件名紧挨在当前邮箱前时才视为伪邮箱上下文。"""
    left_start = max(0, email_start - 40)
    left = text[left_start:email_start]
    for match in PSEUDO_EMAIL_CONTEXT_RE.finditer(left):
        if email_start - (left_start + match.end()) <= max_gap:
            return True
    return False


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    email = raw.strip().lower().strip(".,;)'\"")
    if not email or "@" not in email:
        return None
    if email in EXCLUDED_EMAILS:
        return None
    if any(email.endswith(suffix) for suffix in EXCLUDED_EMAIL_SUFFIXES):
        return None
    local, domain = email.split("@", 1)
    domain = domain.strip(".")
    if _local_part_looks_like_filename(local):
        return None
    if domain in EXCLUDED_EMAIL_DOMAINS:
        return None
    if any(domain == suffix or domain.endswith(f".{suffix}") for suffix in EXCLUDED_EMAIL_DOMAIN_SUFFIXES):
        return None
    if not EMAIL_RE.fullmatch(email):
        return None
    return email


def extract_emails_from_text(text: str | None, source_type: str, *, url: str | None = None) -> list[EmailCandidate]:
    if not text:
        return []
    found: list[EmailCandidate] = []
    seen: set[str] = set()
    confidence = SOURCE_BASE_CONFIDENCE.get(source_type, 0.5)

    for match in EMAIL_RE.finditer(text):
        start = match.start()
        if _pseudo_filename_adjacent_before(text, start):
            continue
        email = normalize_email(match.group(0))
        if email and email not in seen:
            seen.add(email)
            found.append(EmailCandidate(email=email, source_type=source_type, confidence=confidence, url=url))

    for match in MAILTO_RE.findall(text):
        email = normalize_email(unquote(match))
        if email and email not in seen:
            seen.add(email)
            found.append(
                EmailCandidate(
                    email=email,
                    source_type=source_type,
                    confidence=min(confidence + 0.05, 0.99),
                    url=url,
                )
            )
    return found


def classify_external_url(url: str) -> str | None:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    for known_host, page_type in AGGREGATOR_HOSTS.items():
        if host == known_host or host.endswith("." + known_host):
            return page_type
    if host and "instagram.com" not in host:
        path = (urlparse(url).path or "").lower()
        if any(keyword in path for keyword in CONTACT_PATH_KEYWORDS):
            return "website_contact"
        return "website"
    return None


def _parse_ip(host: str) -> ipaddress._BaseAddress | None:
    candidate = host
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _ip_is_non_public(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _hostname_blocked(host: str) -> bool:
    normalized = (host or "").lower().strip(".")
    if not normalized:
        return True
    if normalized in BLOCKED_HOSTNAMES or normalized.endswith(".local"):
        return True
    ip = _parse_ip(normalized)
    if ip is not None:
        return _ip_is_non_public(ip)
    return False


def _resolve_hostname_blocked(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return True
    if not infos:
        return True
    for info in infos:
        ip = _parse_ip(info[4][0])
        if ip is None or _ip_is_non_public(ip):
            return True
    return False


def is_public_web_url(url: str, *, resolve_dns: bool = False) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    lower = url.lower()
    if any(lower.split("?", 1)[0].endswith(ext) for ext in BLOCKED_URL_SUFFIXES):
        return False
    if "instagram.com" in hostname.lower():
        return False
    if _hostname_blocked(hostname):
        return False
    if resolve_dns and _parse_ip(hostname) is None and _resolve_hostname_blocked(hostname):
        return False
    return True


def is_fetchable_url(url: str) -> bool:
    return is_public_web_url(url, resolve_dns=False)


def _same_site(base_url: str, candidate_url: str) -> bool:
    base_host = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
    cand_host = (urlparse(candidate_url).hostname or "").lower().removeprefix("www.")
    if not base_host or not cand_host:
        return False
    return (
        base_host == cand_host
        or cand_host.endswith(f".{base_host}")
        or base_host.endswith(f".{cand_host}")
    )


def _discover_followup_urls(html: str, base_url: str, page_type: str) -> list[tuple[str, str]]:
    if page_type not in {"website", "beacons", "stan_store", "carrd", "linktree", "other_page"}:
        return []

    discovered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href in HREF_RE.findall(html or ""):
        candidate = href.strip()
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        elif candidate.startswith("/"):
            candidate = urljoin(base_url, candidate)
        if not candidate.startswith("http"):
            continue
        if candidate in seen:
            continue
        path = (urlparse(candidate).path or "").lower()
        if not any(keyword in path for keyword in CONTACT_PATH_KEYWORDS):
            continue
        if page_type == "website" and not _same_site(base_url, candidate):
            continue
        if not is_fetchable_url(candidate):
            continue
        seen.add(candidate)
        discovered.append((candidate, "website_contact"))
    return discovered


def credibility_level_label(level: str | None) -> str:
    if not level:
        return CREDIBILITY_LEVEL_LABELS["unknown"]
    return CREDIBILITY_LEVEL_LABELS.get(level, level)


def detect_social_links(text: str, base_url: str | None = None) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for href in HREF_RE.findall(text or ""):
        candidate = href.strip()
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        elif candidate.startswith("/") and base_url:
            candidate = urljoin(base_url, candidate)
        if not candidate.startswith("http"):
            continue
        lower = candidate.lower()
        for social_type, pattern in SOCIAL_PATTERNS:
            if re.search(pattern, lower) and candidate not in seen:
                seen.add(candidate)
                links.append({"type": social_type, "label": social_type.title(), "url": candidate})
    return links


def extract_whatsapp(text: str | None) -> str | None:
    if not text:
        return None
    url_match = WHATSAPP_URL_RE.search(text)
    if url_match:
        return url_match.group(0).strip().rstrip(".,)")[:120]
    labeled = WHATSAPP_LABELED_PHONE_RE.search(text)
    if labeled:
        return labeled.group(1).strip().rstrip(".,)")[:120]
    e164 = WHATSAPP_E164_RE.search(text)
    if e164:
        return e164.group(0).strip()[:120]
    return None


def extract_telegram(text: str | None) -> str | None:
    if not text:
        return None
    match = TELEGRAM_RE.search(text)
    if not match:
        return None
    return match.group(0).strip().rstrip(".,)")[:255]


def _credibility_level(score: float | None, has_email: bool, has_channels: bool) -> str:
    if score is None:
        if has_email:
            return "medium"
        if has_channels:
            return "low"
        return "unknown"
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    if score >= 20 or has_channels:
        return "low"
    return "unknown"


def _compute_contact_score(
    best: EmailCandidate | None,
    *,
    has_contact_page: bool,
    has_whatsapp: bool,
    has_telegram: bool,
    has_linktree: bool,
    has_website: bool,
    email_count: int,
) -> float:
    if best:
        score = best.confidence * 100
    elif has_contact_page:
        score = 45.0
    elif has_whatsapp or has_telegram:
        score = 35.0
    elif has_linktree or has_website:
        score = 25.0
    else:
        score = 0.0

    if has_contact_page:
        score += 8.0
    if has_whatsapp or has_telegram:
        score += 6.0
    if has_linktree:
        score += 4.0
    if email_count > 1:
        score -= min(10.0, (email_count - 1) * 4.0)
    return max(0.0, min(100.0, round(score, 1)))


def _pick_best_email(candidates: list[EmailCandidate]) -> EmailCandidate | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (SOURCE_PRIORITY.get(item.source_type, 99), -item.confidence, item.email),
    )[0]


def _merge_social_links(existing: list[dict[str, str]], discovered: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for item in existing or []:
        url = item.get("url")
        if url:
            merged[url] = item
    for item in discovered:
        url = item.get("url")
        if url and url not in merged:
            merged[url] = item
    return list(merged.values())


def _sources_to_json(candidates: list[EmailCandidate], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.source_type, candidate.email)
        if key in seen:
            continue
        seen.add(key)
        row: dict[str, Any] = {
            "type": candidate.source_type,
            "value": candidate.email,
            "confidence": round(candidate.confidence, 2),
        }
        if candidate.url:
            row["url"] = candidate.url
        rows.append(row)
    for item in extra:
        key = (str(item.get("type")), str(item.get("url") or item.get("value")))
        if key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


class ContactDiscoveryService:
    @staticmethod
    async def _fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
        if not is_public_web_url(url, resolve_dns=True):
            return None
        try:
            async with client.stream("GET", url, follow_redirects=True) as response:
                final_url = str(response.url)
                if not is_public_web_url(final_url, resolve_dns=True):
                    return None
                if response.status_code in {401, 403, 429}:
                    return None
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                if content_type and "text/html" not in content_type and "text/plain" not in content_type:
                    return None
                chunks: list[bytes] = []
                total = 0
                max_bytes = settings.contact_discovery_max_bytes
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.debug("Contact fetch failed url=%s err=%s", url, exc)
            return None

    @staticmethod
    def _process_page_html(
        html: str,
        url: str,
        page_type: str,
        *,
        candidates: list[EmailCandidate],
        partial: ContactDiscoveryResult,
    ) -> None:
        candidates.extend(extract_emails_from_text(html, page_type, url=url))
        partial.other_social_links = _merge_social_links(
            partial.other_social_links,
            detect_social_links(html, url),
        )
        partial.whatsapp = partial.whatsapp or extract_whatsapp(html)
        partial.telegram = partial.telegram or extract_telegram(html)

        if page_type == "linktree":
            partial.linktree_url = partial.linktree_url or url
        elif page_type == "website_contact":
            partial.contact_page = partial.contact_page or url
        elif page_type in {"website", "beacons", "stan_store", "carrd"}:
            partial.website = partial.website or url

    @staticmethod
    def _collect_seed_urls(item: CollectedInfluencer | Influencer) -> list[tuple[str, str]]:
        seeds: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(url: str | None, page_type: str) -> None:
            if not url or url in seen:
                return
            if not is_fetchable_url(url):
                return
            seen.add(url)
            seeds.append((url, page_type))

        add(getattr(item, "linktree_url", None), "linktree")
        add(getattr(item, "website", None), "website")
        add(getattr(item, "contact_page", None), "website_contact")

        for link in getattr(item, "other_social_links", None) or []:
            url = link.get("url") if isinstance(link, dict) else None
            if not url:
                continue
            page_type = classify_external_url(url) or "other_page"
            add(url, page_type)

        bio = getattr(item, "bio", None) or ""
        for match in re.findall(r"https?://[^\s)]+", bio):
            clean = match.rstrip(".,)")
            page_type = classify_external_url(clean) or "other_page"
            add(clean, page_type)

        return seeds

    @staticmethod
    def _extract_from_existing_fields(item: CollectedInfluencer | Influencer) -> tuple[list[EmailCandidate], ContactDiscoveryResult]:
        partial = ContactDiscoveryResult()
        candidates: list[EmailCandidate] = []

        business_email = normalize_email(getattr(item, "business_email", None))
        public_email = normalize_email(getattr(item, "public_email", None))
        if business_email:
            candidates.append(
                EmailCandidate(email=business_email, source_type="business_email", confidence=0.95)
            )
            partial.business_email = business_email
        if public_email and public_email != business_email:
            candidates.append(
                EmailCandidate(email=public_email, source_type="public_email", confidence=0.9)
            )
            partial.public_email = public_email

        bio = getattr(item, "bio", None)
        candidates.extend(extract_emails_from_text(bio, "instagram_bio"))

        for title in getattr(item, "recent_post_titles", None) or []:
            candidates.extend(extract_emails_from_text(title, "instagram_bio"))

        partial.whatsapp = extract_whatsapp(bio) or getattr(item, "whatsapp", None)
        partial.telegram = extract_telegram(bio) or getattr(item, "telegram", None)
        partial.website = getattr(item, "website", None)
        partial.contact_page = getattr(item, "contact_page", None)
        partial.linktree_url = getattr(item, "linktree_url", None)
        partial.other_social_links = list(getattr(item, "other_social_links", None) or [])

        from app.services.contact_signals import apply_bio_contact_hints

        apply_bio_contact_hints(partial)

        return candidates, partial

    @staticmethod
    async def discover(item: CollectedInfluencer | Influencer) -> ContactDiscoveryResult:
        if not settings.contact_discovery_enabled:
            result = ContactDiscoveryResult(contact_fetch_status="not_started")
            return result

        candidates, partial = ContactDiscoveryService._extract_from_existing_fields(item)
        extra_sources: list[dict[str, Any]] = []
        errors: list[str] = []
        pages_fetched = 0
        pages_failed = 0

        seeds = ContactDiscoveryService._collect_seed_urls(item)
        timeout = settings.contact_discovery_timeout_seconds
        headers = {"User-Agent": settings.contact_discovery_user_agent}
        max_pages = settings.contact_discovery_max_pages
        queue: list[tuple[str, str]] = list(seeds)
        visited: set[str] = set()
        queue_index = 0

        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            while queue_index < len(queue) and pages_fetched < max_pages:
                url, page_type = queue[queue_index]
                queue_index += 1
                if url in visited:
                    continue
                visited.add(url)

                html = await ContactDiscoveryService._fetch_html(client, url)
                if html is None:
                    pages_failed += 1
                    errors.append(f"{page_type}:{urlparse(url).netloc}")
                    continue

                pages_fetched += 1
                ContactDiscoveryService._process_page_html(
                    html,
                    url,
                    page_type,
                    candidates=candidates,
                    partial=partial,
                )

                for follow_url, follow_type in _discover_followup_urls(html, url, page_type):
                    if follow_url in visited:
                        continue
                    if any(existing_url == follow_url for existing_url, _ in queue):
                        continue
                    queue.append((follow_url, follow_type))

        best = _pick_best_email(candidates)
        unique_emails = list(dict.fromkeys(c.email for c in candidates))

        if best:
            partial.final_email = best.email
            partial.email = best.email
            partial.email_source = best.source_type
            if best.source_type == "business_email":
                partial.business_email = best.email
            elif best.source_type == "public_email":
                partial.public_email = best.email

        if not partial.final_email:
            partial.final_email = (
                partial.business_email
                or partial.public_email
                or normalize_email(getattr(item, "final_email", None))
                or normalize_email(getattr(item, "email", None))
            )
            partial.email = partial.final_email

        has_channels = bool(
            partial.contact_page
            or partial.linktree_url
            or partial.website
            or partial.whatsapp
            or partial.telegram
            or partial.other_social_links
        )
        partial.contact_score = _compute_contact_score(
            best,
            has_contact_page=bool(partial.contact_page),
            has_whatsapp=bool(partial.whatsapp),
            has_telegram=bool(partial.telegram),
            has_linktree=bool(partial.linktree_url),
            has_website=bool(partial.website),
            email_count=len(unique_emails),
        )
        partial.contact_credibility_level = _credibility_level(
            partial.contact_score,
            has_email=bool(partial.final_email),
            has_channels=has_channels,
        )
        partial.contact_credibility = CREDIBILITY_LEVEL_SCORE.get(partial.contact_credibility_level, 0.0)
        partial.contact_sources = _sources_to_json(candidates, extra_sources)
        partial.contact_discovered_at = datetime.now(UTC)
        partial.pages_fetched = pages_fetched
        partial.pages_failed = pages_failed

        if pages_fetched == 0 and pages_failed == 0:
            partial.contact_fetch_status = "success" if partial.final_email or has_channels else "failed"
        elif pages_failed and pages_fetched:
            partial.contact_fetch_status = "partial_failed"
        elif pages_failed:
            partial.contact_fetch_status = "failed" if not partial.final_email and not has_channels else "partial_failed"
        else:
            partial.contact_fetch_status = "success"

        if errors:
            partial.contact_fetch_error = "; ".join(errors)[:1000]
        elif partial.contact_fetch_status == "failed" and not partial.final_email and not has_channels:
            partial.contact_fetch_error = "未找到可用联系方式"

        return partial

    @staticmethod
    def apply_to_collected(item: CollectedInfluencer, result: ContactDiscoveryResult) -> None:
        if result.business_email and not item.business_email:
            item.business_email = result.business_email
        if result.public_email and not item.public_email:
            item.public_email = result.public_email

        if result.final_email:
            current_priority = SOURCE_PRIORITY.get(item.email_source or "", 99)
            new_priority = SOURCE_PRIORITY.get(result.email_source or "", 99)
            if not item.final_email or new_priority <= current_priority:
                item.final_email = result.final_email
                item.email = result.final_email
                item.email_source = result.email_source or item.email_source
        elif not item.final_email:
            item.final_email = item.business_email or item.public_email or item.email
            item.email = item.final_email

        item.website = item.website or result.website
        item.contact_page = item.contact_page or result.contact_page
        item.linktree_url = item.linktree_url or result.linktree_url
        item.whatsapp = item.whatsapp or result.whatsapp
        item.telegram = item.telegram or result.telegram
        item.other_social_links = _merge_social_links(item.other_social_links, result.other_social_links)
        item.contact_score = result.contact_score
        item.contact_credibility = result.contact_credibility
        item.contact_credibility_level = result.contact_credibility_level
        item.contact_sources = result.contact_sources
        item.contact_fetch_status = result.contact_fetch_status
        item.contact_fetch_error = result.contact_fetch_error
        item.contact_discovered_at = result.contact_discovered_at

    @staticmethod
    def apply_to_influencer(influencer: Influencer, result: ContactDiscoveryResult) -> None:
        if result.business_email and not influencer.business_email:
            influencer.business_email = result.business_email
        if result.public_email and not influencer.public_email:
            influencer.public_email = result.public_email

        if result.final_email:
            current_priority = SOURCE_PRIORITY.get(influencer.email_source or "", 99)
            new_priority = SOURCE_PRIORITY.get(result.email_source or "", 99)
            if not influencer.final_email or new_priority <= current_priority:
                influencer.final_email = result.final_email
                influencer.email = result.final_email
                influencer.email_source = result.email_source or influencer.email_source
        elif not influencer.final_email:
            influencer.final_email = (
                influencer.business_email or influencer.public_email or influencer.email
            )
            influencer.email = influencer.final_email

        influencer.website = influencer.website or result.website
        influencer.contact_page = influencer.contact_page or result.contact_page
        influencer.linktree_url = influencer.linktree_url or result.linktree_url
        influencer.whatsapp = influencer.whatsapp or result.whatsapp
        influencer.telegram = influencer.telegram or result.telegram
        influencer.other_social_links = _merge_social_links(
            influencer.other_social_links or [],
            result.other_social_links,
        )
        influencer.contact_score = result.contact_score
        influencer.contact_credibility = result.contact_credibility
        influencer.contact_credibility_level = result.contact_credibility_level
        influencer.contact_sources = result.contact_sources
        influencer.contact_fetch_status = result.contact_fetch_status
        influencer.contact_fetch_error = result.contact_fetch_error
        influencer.contact_discovered_at = result.contact_discovered_at

    @staticmethod
    async def enrich_collected(item: CollectedInfluencer) -> ContactDiscoveryResult:
        try:
            result = await ContactDiscoveryService.discover(item)
            ContactDiscoveryService.apply_to_collected(item, result)
            return result
        except Exception as exc:
            logger.warning("Contact discovery failed for %s: %s", item.username, exc)
            result = ContactDiscoveryResult(
                contact_fetch_status="failed",
                contact_fetch_error=str(exc)[:1000],
                contact_discovered_at=datetime.now(UTC),
            )
            item.contact_fetch_status = result.contact_fetch_status
            item.contact_fetch_error = result.contact_fetch_error
            item.contact_discovered_at = result.contact_discovered_at
            return result

    @staticmethod
    def collected_from_influencer(influencer: Influencer) -> CollectedInfluencer:
        return CollectedInfluencer(
            platform=influencer.platform,
            username=influencer.username,
            profile_url=influencer.profile_url,
            display_name=influencer.display_name,
            bio=influencer.bio,
            email=influencer.email,
            final_email=influencer.final_email,
            public_email=influencer.public_email,
            business_email=influencer.business_email,
            email_source=influencer.email_source,
            contact_credibility=influencer.contact_credibility,
            contact_score=influencer.contact_score,
            website=influencer.website,
            contact_page=influencer.contact_page,
            linktree_url=influencer.linktree_url,
            whatsapp=influencer.whatsapp,
            telegram=influencer.telegram,
            other_social_links=list(influencer.other_social_links or []),
            recent_post_titles=list(influencer.recent_post_titles or []),
            contact_sources=list(influencer.contact_sources or []),
            contact_fetch_status=influencer.contact_fetch_status,
            contact_fetch_error=influencer.contact_fetch_error,
            contact_discovered_at=influencer.contact_discovered_at,
            contact_credibility_level=influencer.contact_credibility_level,
        )

    @staticmethod
    async def refresh_influencer(influencer: Influencer) -> ContactDiscoveryResult:
        item = ContactDiscoveryService.collected_from_influencer(influencer)
        result = await ContactDiscoveryService.enrich_collected(item)
        ContactDiscoveryService.apply_to_influencer(influencer, result)
        return result
