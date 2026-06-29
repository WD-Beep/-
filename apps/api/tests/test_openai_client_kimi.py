from app.services.ai import openai_client


def test_kimi_k26_temperature_is_forced_to_one(monkeypatch):
    monkeypatch.setattr(openai_client.settings, "openai_api_base", "https://api.moonshot.cn/v1")

    assert openai_client._chat_temperature("kimi-k2.6", 0.4) == 1.0


def test_non_kimi_temperature_is_preserved(monkeypatch):
    monkeypatch.setattr(openai_client.settings, "openai_api_base", "https://api.openai.com/v1")

    assert openai_client._chat_temperature("gpt-4.1", 0.4) == 0.4
