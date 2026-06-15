"""URL-only platform providers for commerce/discovery surfaces.

These platforms are useful for curated creator URLs today, but do not have a
stable API Direct keyword discovery path in this app yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.models.collection_task import CollectionTask
from app.services.platform_types import PlatformCapability, PlatformCandidateProfile, PlatformDiscoveryResult
from app.services.platform_utils import dedupe_profiles, profile_to_collected


@dataclass(frozen=True)
class UrlOnlyPlatformConfig:
    platform: str
    label: str
    hosts: tuple[str, ...]
    message: str


CONFIGS = {
    "pinterest": UrlOnlyPlatformConfig(
        platform="pinterest",
        label="Pinterest",
        hosts=("pinterest.com", "www.pinterest.com"),
        message="当前主要通过链接导入或社媒外链发现补全；站内关键词采集暂未接入。",
    ),
    "ltk": UrlOnlyPlatformConfig(
        platform="ltk",
        label="LTK",
        hosts=("shopltk.com", "www.shopltk.com"),
        message="当前主要通过链接导入或社媒外链发现补全；站内关键词采集暂未接入。",
    ),
    "shopmy": UrlOnlyPlatformConfig(
        platform="shopmy",
        label="ShopMy",
        hosts=("shopmy.us", "www.shopmy.us"),
        message="当前主要通过链接导入或社媒外链发现补全；站内关键词采集暂未接入。",
    ),
}

PINTEREST_RESERVED = {
    "about",
    "business",
    "categories",
    "ideas",
    "login",
    "pin",
    "privacy",
    "search",
    "settings",
    "today",
}
SHOPMY_RESERVED = {"collections", "discover", "explore", "login", "products", "shop", "stores"}
HANDLE_RE = re.compile(r"^[A-Za-z0-9_.-]{2,80}$")
PINTEREST_PIN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _clean_url(raw_url: str) -> str:
    text = raw_url.strip()
    if not text:
        return ""
    if not re.match(r"^https?://", text, re.I):
        text = f"https://{text}"
    return text


def _path_parts(parsed) -> list[str]:
    return [part for part in parsed.path.split("/") if part]


def _parse_pinterest(raw_url: str) -> PlatformCandidateProfile | None:
    text = _clean_url(raw_url)
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if host not in CONFIGS["pinterest"].hosts:
        return None
    parts = _path_parts(parsed)
    if len(parts) == 2 and parts[0].lower() == "pin":
        pin_id = parts[1].strip()
        if not PINTEREST_PIN_ID_RE.match(pin_id):
            return None
        profile_url = f"https://www.pinterest.com/pin/{pin_id}/"
        return PlatformCandidateProfile(
            platform="pinterest",
            username=f"pin_{pin_id}",
            profile_url=profile_url,
            display_name=f"Pinterest Pin {pin_id}",
            source_url=text,
            source_post_url=text,
            source_type="input_url",
            source_discovery_type="url_import",
            source_meta={
                "provider": "url_only",
                "input_url": raw_url.strip(),
                "link_type": "pin",
                "pin_id": pin_id,
                "profile_hydration": "url_only_pending",
            },
        )
    if len(parts) != 1:
        return None
    username = parts[0].strip()
    if username.lower() in PINTEREST_RESERVED or not HANDLE_RE.match(username):
        return None
    profile_url = f"https://www.pinterest.com/{username}/"
    return PlatformCandidateProfile(
        platform="pinterest",
        username=username,
        profile_url=profile_url,
        display_name=username.replace("_", " "),
        source_url=text,
        source_type="input_url",
        source_discovery_type="url_import",
        source_meta={"provider": "url_only", "input_url": raw_url.strip(), "link_type": "profile", "profile_hydration": "url_only_pending"},
    )


def _parse_ltk(raw_url: str) -> PlatformCandidateProfile | None:
    text = _clean_url(raw_url)
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if host not in CONFIGS["ltk"].hosts:
        return None
    parts = _path_parts(parsed)
    if len(parts) < 2 or parts[0].lower() != "explore":
        return None
    username = parts[1].strip()
    if not HANDLE_RE.match(username):
        return None
    profile_url = f"https://www.shopltk.com/explore/{username}"
    link_type = "profile"
    source_post_url = None
    if len(parts) > 2:
        link_type = "product"
        source_post_url = text
    return PlatformCandidateProfile(
        platform="ltk",
        username=username,
        profile_url=profile_url,
        display_name=username.replace("_", " "),
        source_url=text,
        source_post_url=source_post_url,
        source_type="input_url",
        source_discovery_type="url_import",
        source_meta={
            "provider": "url_only",
            "input_url": raw_url.strip(),
            "link_type": link_type,
            "profile_hydration": "url_only_pending",
        },
    )


def _parse_shopmy(raw_url: str) -> PlatformCandidateProfile | None:
    text = _clean_url(raw_url)
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if host not in CONFIGS["shopmy"].hosts:
        return None
    parts = _path_parts(parsed)
    if len(parts) >= 2 and parts[0].lower() not in SHOPMY_RESERVED:
        username = parts[0].strip()
        if HANDLE_RE.match(username):
            return PlatformCandidateProfile(
                platform="shopmy",
                username=username,
                profile_url=f"https://shopmy.us/{username}",
                display_name=username.replace("_", " "),
                source_url=text,
                source_post_url=text,
                source_type="input_url",
                source_discovery_type="url_import",
                source_meta={
                    "provider": "url_only",
                    "input_url": raw_url.strip(),
                    "link_type": "product",
                    "profile_hydration": "url_only_pending",
                },
            )
        return None
    if len(parts) != 1:
        return None
    username = parts[0].strip()
    if username.lower() in SHOPMY_RESERVED or not HANDLE_RE.match(username):
        return None
    profile_url = f"https://shopmy.us/{username}"
    return PlatformCandidateProfile(
        platform="shopmy",
        username=username,
        profile_url=profile_url,
        display_name=username.replace("_", " "),
        source_url=text,
        source_type="input_url",
        source_discovery_type="url_import",
        source_meta={
            "provider": "url_only",
            "input_url": raw_url.strip(),
            "link_type": "profile",
            "profile_hydration": "url_only_pending",
        },
    )


PARSERS = {
    "pinterest": _parse_pinterest,
    "ltk": _parse_ltk,
    "shopmy": _parse_shopmy,
}


class UrlOnlyPlatformProvider:
    platform = ""

    @classmethod
    def capability(cls) -> PlatformCapability:
        config = CONFIGS[cls.platform]
        return PlatformCapability(
            platform=config.platform,
            label=config.label,
            status="url_only",
            message=config.message,
            endpoints=[],
        )

    @classmethod
    async def discover(cls, task: CollectionTask) -> PlatformDiscoveryResult:
        input_urls = [u.strip() for u in (task.input_urls or []) if u and str(u).strip()]
        parser = PARSERS[cls.platform]
        profiles = [parser(url) for url in input_urls]
        profiles = [profile for profile in profiles if profile is not None]
        deduped = dedupe_profiles(profiles)
        if not deduped:
            cap = cls.capability()
            return PlatformDiscoveryResult(
                platform=cls.platform,
                fatal=True,
                skipped=True,
                skip_reason=cap.message,
                errors=[cap.message],
            )
        return PlatformDiscoveryResult(
            platform=cls.platform,
            items=[profile_to_collected(profile) for profile in deduped],
            profiles=deduped,
            discovered_count=len(profiles),
            deduped_count=len(deduped),
            profile_fetched_count=len(deduped),
            api_requests=0,
        )


class PinterestUrlOnlyProvider(UrlOnlyPlatformProvider):
    platform = "pinterest"


class LtkUrlOnlyProvider(UrlOnlyPlatformProvider):
    platform = "ltk"


class ShopMyUrlOnlyProvider(UrlOnlyPlatformProvider):
    platform = "shopmy"
