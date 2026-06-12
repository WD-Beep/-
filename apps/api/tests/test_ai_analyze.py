"""AI 分析入口测试（不调用真实 Kimi）。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio

from app.services.ai_service import analyze_influencer, heuristic_analyze


def _influencer(**kwargs):
    defaults = {
        "platform": "instagram",
        "username": "demo",
        "followers_count": 10_000,
        "engagement_rate": 2.0,
        "score": 70,
        "tags": ["travel"],
        "email": None,
        "final_email": None,
        "has_brand_collaboration": False,
        "category": "travel",
        "product_fit": None,
        "travel_fit_score": None,
        "purchasing_power_score": None,
        "sales_potential_score": None,
        "audience_match_score": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_analyze_without_kimi_key_uses_heuristic_not_kimi():
    async def _run():
        with patch("app.services.ai_service.settings") as mock_settings:
            mock_settings.is_kimi_configured = False
            return await analyze_influencer(_influencer())

    result = anyio.run(_run)
    assert result.source == "heuristic"
    assert "未配置 KIMI_API_KEY" in result.score_reason
    assert result.ai_summary == ""


def test_real_llm_payload_uses_kimi_k25_temperature():
    import inspect

    from app.services import ai_service

    source = inspect.getsource(ai_service.real_llm_analyze)
    assert '"temperature": 0.6' in source
    assert '"thinking": {"type": "disabled"}' in source


def test_analyze_kimi_failure_surfaces_error():
    async def _run():
        with patch("app.services.ai_service.settings") as mock_settings:
            mock_settings.is_kimi_configured = True
            with patch(
                "app.services.ai_service.real_llm_analyze",
                new_callable=AsyncMock,
                side_effect=RuntimeError("401 Unauthorized"),
            ):
                return await analyze_influencer(_influencer())

    result = anyio.run(_run)
    assert result.source == "heuristic_fallback"
    assert "AI 分析失败" in result.score_reason
    assert "401" in (result.error_message or "")


def test_heuristic_does_not_pretend_kimi_success():
    result = heuristic_analyze(_influencer(), reason="no_api_key")
    assert result.source == "heuristic"
    assert "未配置" in result.score_reason
