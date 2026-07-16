"""采集配置与数据源测试。"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.models.collection_task import CollectionTask
from app.models.enums import CollectionTaskStatus
from app.services.collection_task import CollectionTaskService
from app.main import app
from app.services.api_direct_provider import get_platform_capability, list_platform_capabilities
from app.services.instagram_provider import ensure_instagram_provider_ready


def test_collection_defaults_allow_ten_running_tasks():
    assert settings.collection_max_running_tasks == 10
    assert settings.collection_max_concurrency_per_user == 3
    assert settings.collection_max_concurrency_per_platform == 3
    # Field default is 4; conftest forces 0 so queue tests stay deterministic.
    assert settings.model_fields["collection_worker_count"].default == 4


def test_collection_profile_enrichment_defaults():
    assert settings.collection_profile_enrich_concurrency == 3
    assert settings.collection_profile_request_timeout_seconds == 20
    assert settings.collection_running_stale_seconds >= 30


def test_instagram_pipeline_imports_stage_constants():
    from app.services import instagram_pipeline as mod

    assert mod.STAGE_DISCOVERY == "discovery"
    assert mod.STAGE_HYDRATION == "hydration"


@pytest.mark.anyio
async def test_platform_capabilities_expose_collection_limits():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/collection-tasks/platform-capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["collection_max_running_tasks"] == 10
    assert data["collection_max_concurrency_per_user"] == 3
    assert data["collection_max_concurrency_per_platform"] == 3
    assert data["collection_worker_count"] == 0  # conftest disables embedded workers
    assert data["collection_profile_enrich_concurrency"] >= 3
    assert data["collection_profile_request_timeout_seconds"] == 20
    assert data["collection_running_stale_seconds"] >= 30


def test_reconcile_skips_fresh_running_tasks():
    fresh = CollectionTask(
        id=99,
        name="fresh",
        platform="instagram",
        platforms=["instagram"],
        keywords=["test"],
        collection_mode="keyword",
        status=CollectionTaskStatus.RUNNING.value,
    )
    fresh.updated_at = datetime.now(UTC)

    async def _run():
        db = AsyncMock()

        async def _execute(_query):
            result = MagicMock()
            result.scalars.return_value = iter([fresh])
            return result

        db.execute = AsyncMock(side_effect=_execute)
        count = await CollectionTaskService.reconcile_stale_running_tasks(db)
        db.commit.assert_not_awaited()
        return count

    assert anyio.run(_run) == 0
    assert fresh.status == CollectionTaskStatus.RUNNING.value


def test_instagram_collector_requires_api_direct_even_with_legacy_apify_config():
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
                with pytest.raises(Exception):
                    ensure_instagram_provider_ready()


def test_instagram_capability_legacy_apify_config_uses_api_direct():
    with patch.object(settings, "instagram_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            with patch.object(settings, "api_direct_api_key", ""):
                cap = get_platform_capability("instagram")
    assert cap.status == "not_configured"
    assert "API_DIRECT_API_KEY" in cap.message


def test_tiktok_capability_legacy_apify_config_uses_api_direct():
    with patch.object(settings, "tiktok_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            with patch.object(settings, "api_direct_api_key", ""):
                cap = get_platform_capability("tiktok")
    assert cap.status == "not_configured"
    assert "API_DIRECT_API_KEY" in cap.message


def test_tiktok_capability_falls_back_to_api_direct_when_configured():
    with patch.object(settings, "tiktok_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", "test-key"):
            cap = get_platform_capability("tiktok")
    assert cap.status == "supported"
    assert "API Direct" in cap.message


def test_tiktok_capability_legacy_apify_without_api_direct_is_not_configured():
    with patch.object(settings, "tiktok_data_provider", "apify"):
        with patch.object(settings, "api_direct_api_key", ""):
            with patch.object(settings, "apify_token", "apify_api_test_token"):
                cap = get_platform_capability("tiktok")
    assert cap.status == "not_configured"
    assert "API_DIRECT_API_KEY" in cap.message


def test_facebook_capability_legacy_apify_config_uses_api_direct():
    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            cap = get_platform_capability("facebook")
    assert cap.status == "supported"
    assert "API Direct" in cap.message


def test_facebook_legacy_apify_preference_resolves_to_api_direct():
    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", ""):
            with patch.object(settings, "api_direct_api_key", "test-key"):
                assert settings.active_facebook_provider == "api_direct"
                cap = get_platform_capability("facebook")
    assert cap.status == "supported"
    assert "API Direct" in cap.message


def test_facebook_capability_api_direct_without_key():
    with patch.object(settings, "facebook_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", ""):
            with patch.object(settings, "apify_token", ""):
                cap = get_platform_capability("facebook")
    assert cap.status == "not_configured"
    assert "API_DIRECT_API_KEY" in cap.message


def test_facebook_capability_does_not_fallback_to_apify_when_api_direct_missing():
    with patch.object(settings, "facebook_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", ""):
            with patch.object(settings, "apify_token", "apify_api_test_token"):
                cap = get_platform_capability("facebook")
    assert cap.status == "not_configured"
    assert "API_DIRECT_API_KEY" in cap.message


def test_facebook_provider_uses_api_direct_when_legacy_apify_configured():
    from app.services.api_direct_provider import _provider_cls

    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            assert _provider_cls("facebook").__name__ == "FacebookApiDirectProvider"


def test_youtube_provider_routes_to_api_direct_by_default_and_official_when_requested():
    from app.services.api_direct_provider import _provider_cls

    with patch.object(settings, "youtube_data_provider", "auto"):
        assert _provider_cls("youtube").__name__ == "YouTubeApiDirectProvider"

    with patch.object(settings, "youtube_data_provider", "official"):
        assert _provider_cls("youtube").__name__ == "YouTubeOfficialProvider"

    with patch.object(settings, "youtube_data_provider", "api_direct"):
        assert _provider_cls("youtube").__name__ == "YouTubeApiDirectProvider"


def test_facebook_provider_stays_api_direct_when_api_direct_unconfigured():
    from app.services.api_direct_provider import _provider_cls

    with patch.object(settings, "facebook_data_provider", "api_direct"):
        with patch.object(settings, "api_direct_api_key", ""):
            with patch.object(settings, "apify_token", "apify_api_test_token"):
                assert _provider_cls("facebook").__name__ == "FacebookApiDirectProvider"


@pytest.mark.anyio
async def test_settings_status_reports_facebook_legacy_apify_as_api_direct_source():
    with patch.object(settings, "facebook_data_provider", "apify"):
        with patch.object(settings, "apify_token", "apify_api_test_token"):
            with patch.object(settings, "api_direct_api_key", ""):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get("/api/settings/status")
    assert response.status_code == 200
    data = response.json()
    assert data["collection"]["facebook_data_provider"] == "api_direct"
    assert data["collection"]["facebook_collector_configured"] is False
    assert "API_DIRECT_API_KEY" in data["collection"]["facebook_message"]


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
async def test_settings_status_reports_legacy_apify_as_api_direct_source():
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
    assert data["collection"]["tiktok_data_provider"] == "api_direct"
    assert data["collection"]["youtube_data_provider"] == "api_direct"


def test_list_platform_capabilities_includes_provider_metadata():
    caps = list_platform_capabilities()
    assert any(item.platform == "instagram" for item in caps)
    assert any(item.platform == "tiktok" for item in caps)
    assert any(item.platform == "amazon" for item in caps)
    by_platform = {item.platform: item for item in caps}
    assert by_platform["instagram"].keyword_discovery is True
    assert by_platform["instagram"].native_keyword_discovery is True
    assert by_platform["instagram"].link_import is True
    assert by_platform["pinterest"].keyword_discovery is False
    assert by_platform["pinterest"].native_keyword_discovery is False
    assert by_platform["pinterest"].external_seed_discovery is True
    assert by_platform["pinterest"].reverse_link_expansion is True
    assert by_platform["pinterest"].link_import is True
    assert by_platform["ltk"].external_seed_discovery is True
    assert by_platform["ltk"].reverse_link_expansion is True
    assert by_platform["shopmy"].external_seed_discovery is True
    assert by_platform["shopmy"].reverse_link_expansion is True
    assert by_platform["amazon"].product_seed is True
    assert by_platform["amazon"].keyword_discovery is False
    assert by_platform["amazon"].external_seed_discovery is False
