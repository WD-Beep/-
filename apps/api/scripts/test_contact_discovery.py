# 文件说明：后端维护脚本，用于检查、迁移、验证或批处理任务；当前文件：test contact discovery
"""联系方式深挖单元验证（不访问外网）。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.contact_discovery import (
    ContactDiscoveryService,
    EmailCandidate,
    SOURCE_PRIORITY,
    _pick_best_email,
    extract_emails_from_text,
    is_public_web_url,
    normalize_email,
)


def test_email_priority_order() -> None:
    candidates = [
        EmailCandidate("bio@gmail.com", "instagram_bio", 0.7),
        EmailCandidate("tree@creator.com", "linktree", 0.85),
        EmailCandidate("page@brand.com", "website_contact", 0.9),
        EmailCandidate("pub@brand.com", "public_email", 0.9),
        EmailCandidate("biz@brand.com", "business_email", 0.95),
    ]
    best = _pick_best_email(candidates)
    assert best is not None
    assert best.email == "biz@brand.com"
    assert SOURCE_PRIORITY["business_email"] < SOURCE_PRIORITY["public_email"]
    assert SOURCE_PRIORITY["public_email"] < SOURCE_PRIORITY["website_contact"]
    assert SOURCE_PRIORITY["website_contact"] < SOURCE_PRIORITY["linktree"]
    assert SOURCE_PRIORITY["linktree"] < SOURCE_PRIORITY["instagram_bio"]


def test_pseudo_emails_rejected() -> None:
    assert normalize_email("test@example.com") is None
    assert normalize_email("image.png@cdn.com") is None
    assert normalize_email("file.jpg@x.com") is None
    assert normalize_email("user@brand.com") == "user@brand.com"

    noisy = extract_emails_from_text(
        "banner image.png junk@test.com file.jpg@x.com real@agency.co",
        "other_page",
    )
    emails = {item.email for item in noisy}
    assert emails == {"real@agency.co"}


def test_mailto_and_bio_extraction() -> None:
    bio_emails = extract_emails_from_text("collab: hello@creator.com", "instagram_bio")
    assert bio_emails[0].email == "hello@creator.com"

    mailto_emails = extract_emails_from_text(
        '<a href="mailto:team@brand.com">Email</a>',
        "website_contact",
    )
    assert mailto_emails[0].email == "team@brand.com"


def test_blocked_urls() -> None:
    blocked = [
        "http://127.0.0.1/contact",
        "http://localhost/page",
        "http://10.0.0.5/page",
        "http://172.16.0.10/page",
        "http://192.168.1.20/page",
        "http://[::1]/page",
        "http://device.local/contact",
    ]
    for url in blocked:
        assert is_public_web_url(url, resolve_dns=False) is False


async def _contact_page_followup_extracts_email() -> None:
    item = SimpleNamespace(
        platform="instagram",
        username="creator",
        profile_url="https://www.instagram.com/creator/",
        website="https://brand.example.com",
        business_email=None,
        public_email=None,
        final_email=None,
        email=None,
        bio=None,
        linktree_url=None,
        contact_page=None,
        whatsapp=None,
        telegram=None,
        other_social_links=[],
        recent_post_titles=[],
    )
    pages = {
        "https://brand.example.com": '<html><a href="/contact">Contact us</a></html>',
        "https://brand.example.com/contact": '<html><a href="mailto:hello@brand.com">Email</a></html>',
    }

    async def fake_fetch(_client, url: str) -> str | None:
        return pages.get(url)

    with (
        patch("app.services.contact_discovery.is_public_web_url", return_value=True),
        patch.object(ContactDiscoveryService, "_fetch_html", side_effect=fake_fetch),
        patch("app.services.contact_discovery.settings.contact_discovery_enabled", True),
        patch("app.services.contact_discovery.settings.contact_discovery_max_pages", 5),
    ):
        result = await ContactDiscoveryService.discover(item)

    assert result.final_email == "hello@brand.com"
    assert result.email_source == "website_contact"
    assert result.pages_fetched == 2


def test_contact_page_followup_extracts_email() -> None:
    asyncio.run(_contact_page_followup_extracts_email())


async def _enrich_failure_does_not_raise() -> None:
    item = SimpleNamespace(
        platform="instagram",
        username="creator",
        profile_url="https://www.instagram.com/creator/",
        business_email=None,
        public_email=None,
        final_email=None,
        email=None,
        bio=None,
        linktree_url=None,
        contact_page=None,
        whatsapp=None,
        telegram=None,
        other_social_links=[],
        recent_post_titles=[],
        contact_fetch_status=None,
        contact_fetch_error=None,
        contact_discovered_at=None,
    )

    with patch.object(
        ContactDiscoveryService,
        "discover",
        AsyncMock(side_effect=RuntimeError("fetch exploded")),
    ):
        result = await ContactDiscoveryService.enrich_collected(item)

    assert result.contact_fetch_status == "failed"
    assert item.contact_fetch_status == "failed"
    assert "fetch exploded" in (item.contact_fetch_error or "")


def test_enrich_failure_does_not_raise() -> None:
    asyncio.run(_enrich_failure_does_not_raise())


def run_tests() -> None:
    test_email_priority_order()
    test_pseudo_emails_rejected()
    test_mailto_and_bio_extraction()
    test_blocked_urls()
    asyncio.run(_contact_page_followup_extracts_email())
    asyncio.run(_enrich_failure_does_not_raise())
    print("contact discovery unit checks passed")


if __name__ == "__main__":
    run_tests()
