"""pytest 入口：自动使用项目 venv，并保证依赖包路径一致。"""

from __future__ import annotations

import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent.parent
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

import runtime_bootstrap

runtime_bootstrap.reexec_with_venv_python("PYTEST_VENV_REEXEC", "-m", "pytest", *sys.argv[1:])
runtime_bootstrap.prefer_project_venv_packages()

import asyncio

import pytest

from app.db.session import engine


@pytest.fixture(autouse=True)
def reset_async_engine():
    yield
    asyncio.run(engine.dispose())


@pytest.fixture(autouse=True)
def _disable_embedded_collection_workers(monkeypatch):
    """Tests drive the queue via dispatch/starters; keep worker pool off."""
    from app.core.config import settings
    from app.services import collection_runner as collection_runner_module

    monkeypatch.setattr(settings, "collection_worker_count", 0)
    collection_runner_module._active_collection_task_ids.clear()
    collection_runner_module._active_collection_async_tasks.clear()
    yield
    collection_runner_module._active_collection_task_ids.clear()
    collection_runner_module._active_collection_async_tasks.clear()
