"""collection_targets：discovery_limit 作为合格入库目标，发现阶段 over-fetch。"""

from types import SimpleNamespace

from app.models.collection_task import CollectionTask
from app.services.collection_targets import (
    CollectionRunContext,
    discovery_fetch_limit,
    max_candidates_to_process,
    max_overfetch_rounds_for_task,
    reset_run_context,
    set_run_context,
    should_stop_overfetch_round,
    target_qualified_count,
)


def test_target_qualified_count_uses_discovery_limit():
    task = CollectionTask(name="t", platform="youtube", keywords=["a"], discovery_limit=30)
    assert target_qualified_count(task) == 30


def test_discovery_fetch_limit_overfetch_for_target_30():
    task = CollectionTask(name="t", platform="youtube", keywords=["a"], discovery_limit=30)
    assert discovery_fetch_limit(task, round_index=0) == 240
    assert discovery_fetch_limit(task, round_index=1) == 300


def test_max_candidates_caps_at_10000():
    task = CollectionTask(name="t", platform="youtube", keywords=["a"], discovery_limit=100)
    assert max_candidates_to_process(task) == 800


def test_target_qualified_count_allows_10000():
    task = CollectionTask(name="t", platform="youtube", keywords=["a"], discovery_limit=10_000)
    assert target_qualified_count(task) == 10_000
    assert max_candidates_to_process(task) == 10_000


def test_run_context_overrides_fetch_limit():
    task = CollectionTask(name="t", platform="youtube", keywords=["a"], discovery_limit=30)
    token = set_run_context(
        CollectionRunContext(
            target_qualified_count=30,
            max_candidates=240,
            fetch_limit=180,
        )
    )
    try:
        assert discovery_fetch_limit(task) == 180
    finally:
        reset_run_context(token)


def test_should_stop_overfetch_round_when_no_new_unique_items():
    assert should_stop_overfetch_round(new_unique_count=0) == "平台无更多结果"
    assert should_stop_overfetch_round(new_unique_count=-1) == "平台无更多结果"
    assert should_stop_overfetch_round(new_unique_count=1) is None


def test_max_overfetch_rounds_for_small_target():
    task = CollectionTask(name="t", platform="youtube", keywords=["a"], discovery_limit=10)
    assert max_overfetch_rounds_for_task(task) == 2


def test_max_overfetch_rounds_for_large_target():
    task = CollectionTask(name="t", platform="youtube", keywords=["a"], discovery_limit=30)
    assert max_overfetch_rounds_for_task(task) == 3
