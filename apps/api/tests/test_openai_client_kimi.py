from app.services.ai import openai_client
from app.core.config import Settings


def test_ai_defaults_use_deepseek_when_env_absent(monkeypatch):
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_API_BASE",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_API_BASE",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.openai_model == "deepseek-v4-flash"
    assert settings.openai_api_base == "https://api.deepseek.com"
    assert settings.active_ai_provider == "deepseek"


def test_deepseek_env_aliases_configure_ai(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek_test_key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_API_BASE"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "deepseek_test_key"
    assert settings.openai_model == "deepseek-v4-flash"
    assert settings.openai_api_base == "https://api.deepseek.com"
    assert settings.is_openai_configured
    assert settings.active_ai_provider == "deepseek"


def test_kimi_k26_temperature_is_forced_to_one(monkeypatch):
    monkeypatch.setattr(openai_client.settings, "openai_api_base", "https://api.moonshot.cn/v1")

    assert openai_client._chat_temperature("kimi-k2.6", 0.4) == 1.0


def test_non_kimi_temperature_is_preserved(monkeypatch):
    monkeypatch.setattr(openai_client.settings, "openai_api_base", "https://api.openai.com/v1")

    assert openai_client._chat_temperature("gpt-4.1", 0.4) == 0.4


def test_parse_json_content_tolerates_raw_newlines_inside_strings():
    parsed = openai_client._parse_json_content(
        '{"subject":"Hello","body":"Line one\nLine two\tTabbed","risk_notes":[]}'
    )

    assert parsed["subject"] == "Hello"
    assert parsed["body"] == "Line one\nLine two\tTabbed"
