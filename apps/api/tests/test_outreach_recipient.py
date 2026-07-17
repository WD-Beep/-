"""真实外联收件人校验与 SMTP 测试邮件行为。"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services.email import EmailService
from app.services.outreach_recipient import (
    is_sender_address,
    outreach_recipient_skip_reason,
    validate_real_outreach_recipient,
)


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        "smtp_host": "smtp.example.com",
        "smtp_port": 465,
        "smtp_user": "sender@company.com",
        "smtp_password": "secret",
        "smtp_from": "sender@company.com",
    }
    base.update(overrides)
    return Settings(**base)


def test_is_sender_address_matches_from_and_user():
    with patch("app.services.outreach_recipient.settings", _settings()):
        assert is_sender_address("sender@company.com") is True
        assert is_sender_address("SENDER@company.com") is True
        assert is_sender_address("creator@example.com") is False


def test_outreach_recipient_skip_reason_missing_and_sender():
    with patch("app.services.outreach_recipient.settings", _settings()):
        assert outreach_recipient_skip_reason(None) == "缺少邮箱"
        assert outreach_recipient_skip_reason("") == "缺少邮箱"
        assert "发件邮箱相同" in (outreach_recipient_skip_reason("sender@company.com") or "")
        assert outreach_recipient_skip_reason("creator@gmail.com") is None


def test_outreach_recipient_skip_reason_rejects_pseudo_and_test_emails():
    with patch("app.services.outreach_recipient.settings", _settings()):
        assert outreach_recipient_skip_reason("u002f@sarah.colussi") == "收件人邮箱格式无效"
        assert outreach_recipient_skip_reason("creator@example.com") == "测试邮箱域名，已跳过"
        assert outreach_recipient_skip_reason("creator@gmail.com") is None


def test_outreach_recipient_skip_reason_rejects_sentry_ingest_email():
    with patch("app.services.outreach_recipient.settings", _settings()):
        reason = outreach_recipient_skip_reason("37df41a9eafc429585b01c3771b4af54@o468184.ingest.sentry.io")
    assert reason is not None
    assert "Sentry" in reason


def test_validate_real_outreach_recipient_rejects_sender():
    with patch("app.services.outreach_recipient.settings", _settings()):
        with pytest.raises(HTTPException) as exc:
            validate_real_outreach_recipient("sender@company.com")
        assert exc.value.status_code == 400
        assert "发件邮箱相同" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_send_test_email_requires_recipient():
    with patch("app.services.email.settings", _settings()):
        with patch(
            "app.services.email.EmailService.ensure_smtp_configured",
        ):
            result = await EmailService.send_test_email(None)
    assert result.success is False
    assert "请填写测试收件人" in result.message
    assert result.recipient is None


@pytest.mark.asyncio
async def test_send_test_email_allows_explicit_recipient():
    with patch("app.services.email.settings", _settings()):
        with patch("app.services.email.EmailService.ensure_smtp_configured"):
            with patch(
                "app.services.email.EmailService._send_message",
                new=AsyncMock(),
            ):
                result = await EmailService.send_test_email("ops@example.com")
    assert result.success is True
    assert result.recipient == "ops@example.com"
    assert "SMTP 测试邮件" in result.message
    assert "不是红人外联" in result.message
