"""SMTP 配置状态测试。"""

from app.core.config import SMTP_FROM_USER_MISMATCH_MSG, Settings


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://postgres:postgres@localhost:5432/test",
        "smtp_host": "smtp.exmail.qq.com",
        "smtp_port": 465,
        "smtp_user": "amazon03@ptraveldesign.com",
        "smtp_password": "secret",
        "SMTP_FROM": "amazon03@ptraveldesign.com",
    }
    base.update(overrides)
    return Settings(**base)


def test_smtp_from_user_mismatch_detected():
    settings = _settings(smtp_from="amazon03@ptraveldesign.com", smtp_user="other@example.com")
    assert settings.smtp_from_user_mismatch is True
    status = settings.get_smtp_status()
    assert status["from_user_mismatch"] is True
    assert status["warning"] == SMTP_FROM_USER_MISMATCH_MSG
    assert "腾讯企业邮箱" in status["message"]


def test_smtp_from_user_match_no_warning():
    settings = _settings()
    assert settings.smtp_from_user_mismatch is False
    status = settings.get_smtp_status()
    assert status["from_user_mismatch"] is False
    assert status["warning"] is None
    assert status["user_address"] == "amazon03@ptraveldesign.com"


def test_smtp_status_includes_user_address():
    settings = _settings()
    status = settings.get_smtp_status()
    assert status["user_address"] == "amazon03@ptraveldesign.com"
    assert status["from_address"] == "amazon03@ptraveldesign.com"


def test_klaviyo_status_requires_api_key_and_list_id():
    empty = _settings(klaviyo_api_key="", klaviyo_list_id="")
    assert empty.get_klaviyo_status()["configured"] is False

    configured = _settings(
        klaviyo_api_key="pk_test",
        klaviyo_list_id="YwwBQq",
    )

    status = configured.get_klaviyo_status()
    assert status["configured"] is True
    assert status["list_id"] == "YwwBQq"
