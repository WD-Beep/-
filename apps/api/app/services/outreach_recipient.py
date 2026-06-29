"""真实红人外联收件人校验（与 SMTP 测试邮件分离）。"""

from __future__ import annotations

import re

from fastapi import HTTPException, status

from app.core.config import settings

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$")
_EXCLUDED_DOMAINS = {"email.com", "domain.com", "test.com", "sample.com"}
_EXCLUDED_EMAILS = {"test@example.com", "name@example.com", "email@example.com", "you@example.com"}
_COMMON_REAL_TLDS = {
    "com",
    "net",
    "org",
    "co",
    "io",
    "me",
    "tv",
    "us",
    "uk",
    "ca",
    "au",
    "de",
    "fr",
    "it",
    "es",
    "nl",
    "ch",
    "se",
    "no",
    "dk",
    "fi",
    "ie",
    "be",
    "pl",
    "pt",
    "jp",
    "kr",
    "sg",
    "hk",
    "tw",
    "in",
    "br",
    "mx",
    "za",
    "nz",
    "edu",
    "gov",
    "work",
}

SENDER_RECIPIENT_ERROR = "收件人与发件邮箱相同，疑似配置或红人邮箱错误，已阻止发送"
SENDER_RECIPIENT_SKIP = "收件人与发件邮箱相同，疑似配置或红人邮箱错误，已跳过"


def normalize_email_address(address: str | None) -> str | None:
    if not address:
        return None
    cleaned = str(address).strip().lower()
    return cleaned or None


def is_sender_address(address: str | None) -> bool:
    normalized = normalize_email_address(address)
    if not normalized:
        return False
    for candidate in (settings.smtp_from, settings.smtp_user):
        if normalize_email_address(candidate) == normalized:
            return True
    return False


def outreach_recipient_skip_reason(recipient: str | None) -> str | None:
    """Campaign/batch preview skip reason, or None if recipient is valid."""
    normalized = normalize_email_address(recipient)
    if not normalized:
        return "缺少邮箱"
    if not _EMAIL_RE.match(normalized):
        return "收件人邮箱格式无效"
    domain = normalized.rsplit("@", 1)[-1]
    if normalized in _EXCLUDED_EMAILS or domain in _EXCLUDED_DOMAINS:
        return "测试邮箱域名，已跳过"
    tld = domain.rsplit(".", 1)[-1]
    if tld not in _COMMON_REAL_TLDS:
        return "收件人邮箱格式无效"
    if is_sender_address(normalized):
        return SENDER_RECIPIENT_SKIP
    return None


def validate_real_outreach_recipient(
    recipient: str | None,
    *,
    raise_http: bool = True,
) -> str:
    """Validate recipient for real influencer outreach; returns normalized email."""
    reason = outreach_recipient_skip_reason(recipient)
    if reason:
        if reason == SENDER_RECIPIENT_SKIP:
            detail = SENDER_RECIPIENT_ERROR
        else:
            detail = reason
        if raise_http:
            status_code = status.HTTP_400_BAD_REQUEST
            raise HTTPException(status_code=status_code, detail=detail)
        raise ValueError(detail)
    return normalize_email_address(recipient) or ""
