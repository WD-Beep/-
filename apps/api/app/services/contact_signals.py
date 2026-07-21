# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：contact signals
"""联系方式信号识别：邮箱以外的可触达渠道与商业外链。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

URL_IN_TEXT_RE = re.compile(r"https?://[^\s)>\]\"']+", re.I)

DM_COLLAB_TERMS: tuple[str, ...] = (
    "dm for collab",
    "dm me for collab",
    "dm for collaboration",
    "dm for business",
    "dm for partnerships",
    "message for collab",
    "business inquiry",
    "business inquiries",
    "business enquiries",
    "for business",
    "collab inquiries",
    "collaboration inquiries",
    "pr inquiries",
    "media kit",
    "mediakit",
    "合作请私信",
    "商务合作",
    "商务咨询",
    "私信合作",
    "合作咨询",
    "品牌合作",
)

COMMERCIAL_STOREFRONT_TERMS: tuple[str, ...] = (
    "amazon storefront",
    "shop my",
    "shopmy",
    "ltk",
    "liketoknow",
    "beacons",
    "stan store",
)

AGGREGATOR_HOSTS: dict[str, str] = {
    "linktr.ee": "linktree",
    "linktree.com": "linktree",
    "lnktr.ee": "linktree",
    "lnkrtr.ee": "linktree",
    "beacons.ai": "beacons",
    "beacons.page": "beacons",
    "stan.store": "stan_store",
    "carrd.co": "carrd",
    "carrd.site": "carrd",
    "solo.to": "linktree",
    "msha.ke": "linktree",
    "bio.site": "linktree",
}

COMMERCIAL_STOREFRONT_HOSTS: dict[str, str] = {
    "shopmy.us": "ShopMy",
    "www.shopmy.us": "ShopMy",
    "shopltk.com": "LTK",
    "www.shopltk.com": "LTK",
}

AMAZON_STOREFRONT_FRAGMENTS: tuple[str, ...] = (
    "amazon.com/shop/",
    "amazon.com/stores/",
    "amzn.to/",
    "amzlink.to/",
    "urlgeni.us/amzn/",
)

CONTACT_PATH_KEYWORDS: tuple[str, ...] = (
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

CONTACT_CHANNEL_LABELS: dict[str, str] = {
    "email": "邮箱",
    "website": "官网",
    "contact_page": "联系页",
    "linktree": "Linktree",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "shopmy": "ShopMy",
    "ltk": "LTK",
    "amazon_storefront": "Amazon storefront",
    "beacons": "Beacons",
    "stan_store": "Stan Store",
    "carrd": "Carrd",
    "dm_collab": "Bio 支持私信合作",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "twitter": "Twitter",
    "tiktok": "TikTok",
    "linkedin": "LinkedIn",
    "external_link": "外链",
}

EXTERNAL_CONTACT_LINK_TYPES: frozenset[str] = frozenset(
    {"instagram", "facebook", "twitter", "tiktok", "linkedin", "website"}
)


class _ContactRow(Protocol):
    platform: str | None
    final_email: str | None
    email: str | None
    public_email: str | None
    business_email: str | None
    website: str | None
    contact_page: str | None
    linktree_url: str | None
    whatsapp: str | None
    telegram: str | None
    bio: str | None
    profile_url: str | None
    other_social_links: list | None
    contact_score: float | None
    contactability_score: float | None
    contact_fetch_status: str | None


@dataclass
class BioContactHints:
    website: str | None = None
    contact_page: str | None = None
    linktree_url: str | None = None
    whatsapp: str | None = None
    telegram: str | None = None
    other_social_links: list[dict[str, str]] = field(default_factory=list)


def _non_empty(value: str | None) -> bool:
    return bool(value and str(value).strip())


def _normalize_host(url: str) -> str:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    return host


def extract_urls_from_text(text: str | None) -> list[str]:
    if not text:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_IN_TEXT_RE.findall(text):
        clean = match.rstrip(".,)")
        if clean not in seen:
            seen.add(clean)
            urls.append(clean)
    return urls


def classify_commercial_storefront(url: str) -> str | None:
    lower = url.lower()
    host = _normalize_host(url)
    if host in COMMERCIAL_STOREFRONT_HOSTS:
        return COMMERCIAL_STOREFRONT_HOSTS[host]
    for fragment in AMAZON_STOREFRONT_FRAGMENTS:
        if fragment in lower:
            return "Amazon storefront"
    return None


def classify_aggregator_url(url: str) -> str | None:
    host = _normalize_host(url)
    for known_host, page_type in AGGREGATOR_HOSTS.items():
        if host == known_host or host.endswith("." + known_host):
            return page_type
    return None


def classify_contact_page_url(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return any(keyword in path for keyword in CONTACT_PATH_KEYWORDS)


def _contains_any(text: str, terms: tuple[str, ...]) -> str | None:
    if not text:
        return None
    lower = text.lower()
    ordered = sorted(terms, key=len, reverse=True)
    for term in ordered:
        if term.lower() in lower:
            return term
    return None


def detect_dm_collab_signal(bio: str | None) -> str | None:
    hit = _contains_any(bio or "", DM_COLLAB_TERMS)
    if not hit:
        return None
    return f"Bio 明确支持私信合作（{hit.strip()}）"


def detect_storefront_from_urls(*urls: str | None) -> str | None:
    for url in urls:
        if not url:
            continue
        label = classify_commercial_storefront(url)
        if label:
            return f"有 {label} 商业外链"
    return None


def detect_storefront_from_links(other_social_links: list | None) -> str | None:
    for link in other_social_links or []:
        if not isinstance(link, dict):
            continue
        url = link.get("url")
        label = classify_commercial_storefront(str(url or ""))
        if label:
            return f"有 {label} 商业外链"
        link_type = str(link.get("type") or link.get("label") or "").lower()
        if link_type in {"shopmy", "ltk", "amazon_storefront"}:
            return f"有 {link.get('label') or link_type} 商业外链"
    return None


def extract_bio_contact_hints(bio: str | None, *, platform: str | None = None) -> BioContactHints:
    hints = BioContactHints()
    if not bio:
        return hints

    from app.services.contact_discovery import extract_telegram, extract_whatsapp

    hints.whatsapp = extract_whatsapp(bio)
    hints.telegram = extract_telegram(bio)

    for url in extract_urls_from_text(bio):
        storefront = classify_commercial_storefront(url)
        if storefront:
            hints.other_social_links.append(
                {
                    "type": storefront.lower().replace(" ", "_"),
                    "label": storefront,
                    "url": url,
                }
            )
            continue

        aggregator = classify_aggregator_url(url)
        if aggregator == "linktree":
            hints.linktree_url = hints.linktree_url or url
            continue
        if aggregator in {"beacons", "stan_store", "carrd"}:
            hints.website = hints.website or url
            hints.other_social_links.append(
                {"type": aggregator, "label": aggregator.replace("_", " ").title(), "url": url}
            )
            continue

        if classify_contact_page_url(url):
            hints.contact_page = hints.contact_page or url
            continue

        host = _normalize_host(url)
        if host and platform and host.endswith(f"{platform.lower()}.com"):
            continue
        if host and "instagram.com" not in host:
            hints.website = hints.website or url

    return hints


def merge_other_social_links(
    existing: list[dict[str, str]] | None,
    discovered: list[dict[str, str]],
) -> list[dict[str, str]]:
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


def apply_bio_contact_hints(target: Any) -> None:
    """从 bio 补全 website / linktree / whatsapp 等字段（原地修改）。"""
    bio = getattr(target, "bio", None)
    platform = getattr(target, "platform", None)
    hints = extract_bio_contact_hints(bio, platform=platform)

    if hints.website and not getattr(target, "website", None):
        target.website = hints.website
    if hints.contact_page and not getattr(target, "contact_page", None):
        target.contact_page = hints.contact_page
    if hints.linktree_url and not getattr(target, "linktree_url", None):
        target.linktree_url = hints.linktree_url
    if hints.whatsapp and not getattr(target, "whatsapp", None):
        target.whatsapp = hints.whatsapp
    if hints.telegram and not getattr(target, "telegram", None):
        target.telegram = hints.telegram
    if hints.other_social_links:
        current = getattr(target, "other_social_links", None) or []
        target.other_social_links = merge_other_social_links(current, hints.other_social_links)


def detect_external_link_contact_reason(other_social_links: list | None) -> str | None:
    for link in other_social_links or []:
        if not isinstance(link, dict):
            continue
        url = str(link.get("url") or "").strip()
        if not url:
            continue
        link_type = str(link.get("type") or "").lower()
        label = str(link.get("label") or "").strip()
        storefront = classify_commercial_storefront(url)
        if storefront:
            return f"有 {storefront} 商业外链"
        if link_type in EXTERNAL_CONTACT_LINK_TYPES:
            display = CONTACT_CHANNEL_LABELS.get(link_type, label or link_type.title())
            return f"有 {display} 外链"
        if label and label not in {"Website", "外链"}:
            return f"有 {label} 外链"
    return None


def _has_email(row: _ContactRow) -> bool:
    return any(
        _non_empty(getattr(row, field, None))
        for field in ("final_email", "email", "public_email", "business_email")
    )


def _email_verification_reason(row: _ContactRow) -> str | None:
    status = getattr(row, "contact_fetch_status", None)
    if status not in {"verification_required", "manual_required"}:
        return None
    if not _has_email(row):
        return None
    return "邮箱需人工验证"


def _has_explicit_direct_channel(row: _ContactRow) -> bool:
    if _has_email(row):
        return True
    if any(_non_empty(getattr(row, field, None)) for field in ("website", "contact_page", "linktree_url", "whatsapp", "telegram")):
        return True
    if detect_dm_collab_signal(row.bio):
        return True
    if detect_storefront_from_urls(row.website, row.profile_url) or detect_storefront_from_links(row.other_social_links):
        return True
    return False


def collect_contact_channel_keys(row: _ContactRow) -> list[str]:
    keys: list[str] = []
    if _has_email(row):
        keys.append("email")
    if _non_empty(row.website):
        keys.append("website")
    if _non_empty(row.contact_page):
        keys.append("contact_page")
    if _non_empty(row.linktree_url):
        keys.append("linktree")
    if _non_empty(row.whatsapp):
        keys.append("whatsapp")
    if _non_empty(row.telegram):
        keys.append("telegram")

    for link in row.other_social_links or []:
        if not isinstance(link, dict):
            continue
        url = str(link.get("url") or "")
        link_type = str(link.get("type") or "").lower()
        label = classify_commercial_storefront(url)
        if label == "ShopMy" or link_type == "shopmy":
            keys.append("shopmy")
        elif label == "LTK" or link_type == "ltk":
            keys.append("ltk")
        elif label == "Amazon storefront" or link_type == "amazon_storefront":
            keys.append("amazon_storefront")
        elif link_type == "beacons":
            keys.append("beacons")
        elif link_type == "stan_store":
            keys.append("stan_store")
        elif link_type == "linktree":
            keys.append("linktree")
        elif link_type in EXTERNAL_CONTACT_LINK_TYPES:
            keys.append(link_type)
        elif label:
            keys.append(link_type or "external_link")

    storefront = detect_storefront_from_urls(row.website, row.profile_url)
    if storefront:
        lower = storefront.lower()
        if "shopmy" in lower:
            keys.append("shopmy")
        elif "ltk" in lower:
            keys.append("ltk")
        elif "amazon" in lower:
            keys.append("amazon_storefront")

    if detect_dm_collab_signal(row.bio):
        keys.append("dm_collab")

    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def build_contact_summary(row: _ContactRow) -> str:
    if _has_email(row):
        for field in ("final_email", "email", "public_email", "business_email"):
            value = getattr(row, field, None)
            if _non_empty(value):
                return str(value).strip()

    labels: list[str] = []
    verification_reason = _email_verification_reason(row)
    if verification_reason and _has_email(row):
        email_value = None
        for field in ("final_email", "email", "public_email", "business_email"):
            value = getattr(row, field, None)
            if _non_empty(value):
                email_value = str(value).strip()
                break
        if email_value:
            return f"{email_value}（需人工验证）"

    for key in collect_contact_channel_keys(row):
        if key == "email":
            continue
        label = CONTACT_CHANNEL_LABELS.get(key)
        if label and label not in labels:
            labels.append(label)

    if labels:
        return " · ".join(labels[:4])

    for link in row.other_social_links or []:
        if not isinstance(link, dict):
            continue
        label = str(link.get("label") or link.get("type") or "").strip()
        url = str(link.get("url") or "").strip()
        if label and url and label not in labels:
            labels.append(label)
    if labels:
        return " · ".join(labels[:4])
    return "缺联系方式"


def direct_contact_reason(row: _ContactRow, *, contact_score: float | None = None, contactability_score: float | None = None) -> str | None:
    verification_reason = _email_verification_reason(row)
    if verification_reason:
        return verification_reason
    if _has_email(row):
        return "有邮箱"
    if _non_empty(row.website):
        return "有官网"
    if _non_empty(row.contact_page):
        return "有联系页"
    if _non_empty(row.linktree_url):
        return "有 Linktree"
    if _non_empty(row.whatsapp):
        return "有 WhatsApp"
    if _non_empty(row.telegram):
        return "有 Telegram"

    dm_signal = detect_dm_collab_signal(row.bio)
    if dm_signal:
        return dm_signal

    storefront = detect_storefront_from_urls(row.website, row.profile_url) or detect_storefront_from_links(row.other_social_links)
    if storefront:
        return storefront

    external = detect_external_link_contact_reason(row.other_social_links)
    if external:
        return external

    score = contact_score if contact_score is not None else getattr(row, "contact_score", None)
    reachability = contactability_score if contactability_score is not None else getattr(row, "contactability_score", None)
    if score is not None and score >= 50:
        return f"联系方式评分 {score:.0f}"
    if reachability is not None and reachability >= 50:
        return f"可联系评分 {reachability:.0f}"
    return None


def has_direct_contact_channel(row: _ContactRow) -> bool:
    return direct_contact_reason(row) is not None


def commercial_storefront_manual_reason(row: _ContactRow) -> str | None:
    storefront = detect_storefront_from_urls(row.website, row.profile_url) or detect_storefront_from_links(row.other_social_links)
    if storefront:
        return storefront
    return None
