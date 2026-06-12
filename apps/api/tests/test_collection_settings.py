"""采集配置与数据源测试。"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.main import app
from app.services.api_direct_provider import get_platform_capability, list_platform_capabilities
from app.services.instagram_provider import ensure_instagram_provider_ready


def test_instagram_collector_available_with_apify_only():
    from app.collectors import get_collector

    task = CollectionTask(
        name="ig-apify",
        platform="instagram",
        platforms=["instagram"],
        keywords=["travel"],
        collection_mode="keyword",
    )
    with patch.object(settings, "instagram_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            with patch.object(settings, "api_direct_api_key", ""):
                ensure_instagram_provider_ready()
                collector = get_collector(task)
    assert collector is not None


def test_instagram_capability_shows_apify_when_provider_is_apify():
    with patch.object(settings, "instagram_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            with patch.object(settings, "api_direct_api_key", ""):
                cap = get_platform_capability("instagram")
    assert cap.status == "supported"
    assert "Apify" in cap.message
    assert "API Direct 已配置" not in cap.message


def test_tiktok_capability_uses_apify_when_configured():
    with patch.object(settings, "tiktok_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            with patch.object(settings, "api_direct_api_key", ""):
                cap = get_platform_capability("tiktok")
    assert cap.status == "supported"
    assert "Apify" in cap.message
    assert "未接入" not in cap.message


def test_tiktok_capability_falls_back_to_api_direct_when_configured():
    with patch.object(settings, "tiktok_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", "test-key"):
            cap = get_platform_capability("tiktok")
    assert cap.status == "supported"
    assert "API Direct" in cap.message


def test_tiktok_capability_apify_without_token_is_not_configured():
    with patch.object(settings, "tiktok_data_provider", "apify"):
        with patch.object(settings, "apify_token", ""):
            cap = get_platform_capability("tiktok")
    assert cap.status == "not_configured"
    assert "APIFY_TOKEN" in cap.message


def test_facebook_capability_apify_with_token():
    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            cap = get_platform_capability("facebook")
    assert cap.status == "supported"
    assert "Apify" in cap.message
    assert "APIFY_TOKEN" in cap.message or "Apify" in cap.message
    assert "未接入" not in cap.message
    assert "Apify provider" not in cap.message


def test_facebook_apify_preference_stays_apify_without_token_even_if_api_direct_configured():
    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", ""):
            with patch.object(settings, "api_direct_api_key", "test-key"):
                assert settings.active_facebook_provider == "apify"
                cap = get_platform_capability("facebook")
    assert cap.status == "not_configured"
    assert "APIFY_TOKEN" in cap.message
    assert "API Direct" not in cap.message


def test_facebook_capability_api_direct_without_key():
    with patch.object(settings, "facebook_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", ""):
            with patch.object(settings, "apify_token", ""):
                cap = get_platform_capability("facebook")
    assert cap.status == "not_configured"
    assert "API_DIRECT_API_KEY" in cap.message


def test_facebook_capability_falls_back_to_apify_when_api_direct_missing():
    with patch.object(settings, "facebook_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", ""):
            with patch.object(settings, "apify_token", "apify_api_test_token"):
                cap = get_platform_capability("facebook")
    assert cap.status == "supported"
    assert "Apify" in cap.message
    assert "API_DIRECT_API_KEY" not in cap.message


def test_facebook_provider_routes_to_apify_when_configured():
    from app.services.api_direct_provider import _provider_cls

    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            assert _provider_cls("facebook").__name__ == "FacebookApifyProvider"


def test_facebook_provider_falls_back_to_apify_when_api_direct_unconfigured():
    from app.services.api_direct_provider import _provider_cls

    with patch.object(settings, "facebook_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", ""):
            with patch.object(settings, "apify_token", "apify_api_test_token"):
                assert _provider_cls("facebook").__name__ == "FacebookApifyProvider"


@pytest.mark.anyio
async def test_settings_status_reports_facebook_apify_source():
    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            with patch.object(settings, "api_direct_api_key", ""):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get("/api/settings/status")
    assert response.status_code == 200
    data = response.json()
    assert data["collection"]["facebook_data_provider"] == "apify"
    assert data["collection"]["facebook_collector_configured"] is True
    assert "Apify" in data["collection"]["facebook_message"]
    assert "未接入" not in data["collection"]["facebook_message"]


@pytest.mark.anyio
async def test_settings_status_reports_facebook_api_direct_missing_key():
    with patch.object(settings, "facebook_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", ""):
            with patch.object(settings, "apify_token", ""):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get("/api/settings/status")
    assert response.status_code == 200
    data = response.json()
    assert data["collection"]["facebook_data_provider"] == "api_direct"
    assert data["collection"]["facebook_collector_configured"] is False
    assert "API_DIRECT_API_KEY" in data["collection"]["facebook_message"]


@pytest.mark.anyio
async def test_settings_status_reports_apify_tiktok_source():
    with patch.object(settings, "instagram_data_provider", "apify"):
        with patch.object(settings, "youtube_data_provider", "apify"):
            with patch.object(settings, "tiktok_data_provider", "apify"):
                with patch.object(settings, "apify_token", "apify_api_test_token"):
                    with patch.object(settings, "api_direct_api_key", ""):
                        transport = ASGITransport(app=app)
                        async with AsyncClient(transport=transport, base_url="http://test") as client:
                            response = await client.get("/api/settings/status")
    assert response.status_code == 200
    data = response.json()
    assert data["apify"]["configured"] is True
    assert "TikTok" in data["apify"]["message"]


def test_list_platform_capabilities_includes_provider_metadata():
    caps = list_platform_capabilities()
    assert any(item.platform == "instagram" for item in caps)
    assert any(item.platform == "tiktok" for item in caps)
