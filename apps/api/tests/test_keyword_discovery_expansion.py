import anyio

from app.models.collection_task import CollectionTask
from app.services.collection_funnel import CollectionFunnelStats
from app.services.collection_runner import CollectionRunnerService
from app.services.apify_instagram import DiscoveryResult
from app.services.keyword_discovery import discover_candidates_from_keywords
from app.services.task_run_progress import RunCheckpoint


def test_keyword_discovery_uses_expanded_keywords_without_mutating_task(monkeypatch):
    captured: list[str] = []

    async def fake_discover(tags: list[str], *, limit: int = 100):
        captured.extend(tags)
        return DiscoveryResult()

    monkeypatch.setattr(
        "app.services.keyword_discovery.ensure_instagram_provider_ready",
        lambda: "api_direct",
    )
    monkeypatch.setattr(
        "app.services.keyword_discovery.discover_post_authors_from_hashtags",
        fake_discover,
    )

    task = CollectionTask(
        name="makeup bags",
        platform="instagram",
        collection_mode="keyword",
        keywords=["travel makeup bag", "makeup bag"],
    )
    checkpoint = RunCheckpoint()
    original_keywords = list(task.keywords)

    async def run():
        return await discover_candidates_from_keywords(
            task,
            limit=10,
            max_hashtags=15,
            include_comments=False,
            checkpoint=checkpoint,
            db=None,
        )

    result = anyio.run(run)

    assert task.keywords == original_keywords
    assert result.meta.hashtag_count <= 15
    for keyword in [
        "travel makeup bag",
        "travelmakeupbag",
        "travel makeup",
        "makeup bag",
        "makeupbag",
        "cosmetic bag",
        "toiletry bag",
        "makeup pouch",
    ]:
        assert keyword in captured

    diagnostic = checkpoint.extra["keyword_expansion"]
    assert diagnostic["original_keyword_count"] == 2
    assert diagnostic["expanded_keyword_count"] == len(captured)
    assert diagnostic["attempted_keywords"] == captured


def test_keyword_no_result_summary_lists_attempted_terms():
    task = CollectionTask(
        name="makeup bags",
        platform="instagram",
        collection_mode="keyword",
        keywords=["travel makeup bag", "makeup bag"],
    )
    task.run_checkpoint = {
        "keyword_expansion": {
            "original_keyword_count": 2,
            "expanded_keyword_count": 8,
            "attempted_keywords": ["makeup bag", "makeupbag", "cosmetic bag"],
        }
    }

    summary = CollectionRunnerService._keyword_no_result_summary(task, CollectionFunnelStats())

    assert summary is not None
    assert "系统已尝试 8 个发现词" in summary
    assert "makeupbag" in summary
    assert "链接导入/竞品发现" in summary


def test_keyword_no_result_summary_skips_link_import():
    task = CollectionTask(
        name="link import",
        platform="instagram",
        collection_mode="link_import",
        keywords=["makeup bag"],
    )
    task.run_checkpoint = {
        "keyword_expansion": {
            "expanded_keyword_count": 1,
            "attempted_keywords": ["makeupbag"],
        }
    }

    assert CollectionRunnerService._keyword_no_result_summary(task, CollectionFunnelStats()) is None
