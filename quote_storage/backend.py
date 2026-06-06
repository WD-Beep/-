"""QUOTE_DB_BACKEND：sqlite（默认）或 postgres。

环境变量：
- QUOTE_DB_BACKEND：sqlite | postgres
- QUOTE_DATABASE_URL：postgres 模式下必填"""

from __future__ import annotations

import os


def configured_quote_db_backend() -> str:
    raw = os.environ.get("QUOTE_DB_BACKEND", "sqlite").strip().lower()
    if raw in ("sqlite", "postgres"):
        return raw
    return "sqlite"


def ensure_quote_db_backend_supported() -> None:
    if configured_quote_db_backend() != "postgres":
        return
    url = os.environ.get("QUOTE_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "已设置 QUOTE_DB_BACKEND=postgres，但未配置 QUOTE_DATABASE_URL（PostgreSQL 连接串）。"
        )
    try:
        import psycopg  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "PostgreSQL 后端需要安装依赖：pip install \"psycopg[binary]>=3.1\""
        ) from e
