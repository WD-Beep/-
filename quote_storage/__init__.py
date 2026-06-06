"""报价持久化后端入口（SQLite / 预留 PostgreSQL）。"""
from quote_storage.backend import (
    configured_quote_db_backend,
    ensure_quote_db_backend_supported,
)

__all__ = ["configured_quote_db_backend", "ensure_quote_db_backend_supported"]
