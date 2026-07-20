"""Inbound email parsing and outbound Message-ID helpers."""

from __future__ import annotations

import re
import uuid
from html import unescape
from email.utils import parseaddr

from app.core.config import settings

_MESSAGE_ID_RE = re.compile(r"<[^>]+>")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_BLOCK_RE = re.compile(r"</?(?:p|div|br|li|tr|table|h[1-6]|section|article|blockquote)[^>]*>", re.IGNORECASE)
_HTML_DROP_RE = re.compile(r"<(?:script|style|head)[^>]*>.*?</(?:script|style|head)>", re.IGNORECASE | re.DOTALL)


def normalize_message_id(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if not cleaned.startswith("<"):
        cleaned = f"<{cleaned.strip('<>')}>"
    return cleaned.lower()


def parse_references(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(parse_references(item))
        return parts
    found = _MESSAGE_ID_RE.findall(str(value))
    return [normalize_message_id(item) or item.lower() for item in found]


def extract_email_address(value: str | None) -> str | None:
    if not value:
        return None
    if isinstance(value, list):
        for item in value:
            parsed = extract_email_address(item)
            if parsed:
                return parsed
        return None
    _, addr = parseaddr(str(value))
    cleaned = addr.strip().lower()
    return cleaned or None


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    raw = str(value)
    if not re.search(r"<!doctype|<html|<body|</?[a-z][\s>/]", raw, re.IGNORECASE):
        return raw.strip()
    text = _HTML_DROP_RE.sub(" ", raw)
    text = _HTML_BLOCK_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


AUTOMATED_SENDER_PREFIXES = (
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "notification",
    "notifications",
    "mailer-daemon",
)

AUTOMATED_SENDER_DOMAINS = (
    "googlemail.com",
    "steampowered.com",
    "stripe.com",
)

BOUNCE_SUBJECT_KEYWORDS = (
    "delivery status notification",
    "message blocked",
    "mail delivery failed",
    "undelivered mail",
    "failure notice",
)


def is_automated_sender(value: str | None) -> bool:
    email = extract_email_address(value)
    if not email or "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    if local in AUTOMATED_SENDER_PREFIXES:
        return True
    if any(local.startswith(f"{prefix}.") or local.startswith(f"{prefix}-") for prefix in AUTOMATED_SENDER_PREFIXES):
        return True
    return domain in AUTOMATED_SENDER_DOMAINS


def is_delivery_status_notification(*, from_address: str | None, subject: str | None, body: str | None = None) -> bool:
    email = extract_email_address(from_address)
    local = email.rsplit("@", 1)[0] if email and "@" in email else ""
    text = f"{subject or ''}\n{body or ''}".casefold()
    if local == "mailer-daemon":
        return True
    return any(keyword in text for keyword in BOUNCE_SUBJECT_KEYWORDS)


def is_outbound_copy(*, from_address: str | None, configured_addresses: set[str]) -> bool:
    email = extract_email_address(from_address)
    return bool(email and email in configured_addresses)


def build_outbound_message_id(*, product_id: int | None = None) -> str:
    domain = "influencer-intel.local"
    if settings.smtp_from and "@" in settings.smtp_from:
        domain = settings.smtp_from.rsplit("@", 1)[-1].strip().lower() or domain
    token = uuid.uuid4().hex
    prefix = f"outreach-{product_id or 0}-{token}"
    return f"<{prefix}@{domain}>"


def normalize_subject(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    while text.startswith("re:"):
        text = text[3:].strip()
    while text.startswith("fwd:"):
        text = text[4:].strip()
    return text


def make_snippet(body: str | None, *, max_len: int = 200) -> str | None:
    if not body:
        return None
    collapsed = " ".join(html_to_text(body).split())
    if not collapsed:
        return None
    if len(collapsed) <= max_len:
        return collapsed
    return f"{collapsed[: max_len - 1]}…"


INTEREST_KEYWORDS = (
    "interested",
    "collaboration",
    "collab",
    "partnership",
    "partner",
    "quote",
    "pricing",
    "rate card",
    "let's work",
    "lets work",
    "would love to",
    "happy to collaborate",
    "合作",
    "有兴趣",
    "感兴趣",
    "报价",
    "档期",
    "可以合作",
)


def detect_cooperation_interest(*, subject: str | None, body: str | None) -> bool:
    text = (body or "").lower()
    return any(keyword in text for keyword in INTEREST_KEYWORDS)
