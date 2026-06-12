"""采集入库后触发 AI 分析。"""

from unittest.mock import AsyncMock, patch

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.collection_runner import CollectionRunnerService


def test_analyze_collected_influencers_calls_analyze():
    influencer = object()
    mock_analysis = object()

    async def _run():
        db = AsyncMock()
        with patch(
            "app.services.collection_runner.analyze_influencer",
            new_callable=AsyncMock,
            return_value=mock_analysis,
        ) as mock_analyze:
            with patch.object(
                CollectionRunnerService,
                "_apply_analysis_to_influencer",
            ) as mock_apply:
                await CollectionRunnerService._analyze_collected_influencers(db, [influencer])
        return mock_analyze, mock_apply

    mock_analyze, mock_apply = anyio.run(_run)
    mock_analyze.assert_awaited_once_with(influencer)
    mock_apply.assert_called_once_with(influencer, mock_analysis)
