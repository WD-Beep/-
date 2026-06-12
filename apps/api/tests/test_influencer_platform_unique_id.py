"""Influencer.platform_unique_id ORM 与迁移链最小验证。"""

from __future__ import annotations

from sqlalchemy import Index

from app.models.influencer import Influencer


def test_influencer_model_declares_partial_unique_platform_unique_id():
    indexes = [arg for arg in Influencer.__table_args__ if isinstance(arg, Index)]
    partial = next(idx for idx in indexes if idx.name == "uq_influencers_platform_unique_id")
    assert partial.unique is True
    pg_opts = partial.dialect_options.get("postgresql") or {}
    where_clause = pg_opts.get("where") if hasattr(pg_opts, "get") else None
    if where_clause is None:
        where_clause = partial.dialect_options.get("postgresql_where")
    assert where_clause is not None
    assert "platform_unique_id IS NOT NULL" in str(where_clause)


def test_youtube_platform_unique_id_migration_chain():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    revisions = {rev.revision for rev in script.walk_revisions()}
    assert "021_influencer_platform_unique_id" in revisions
    assert "022_youtube_platform_unique_id_backfill" in revisions
    rev022 = script.get_revision("022_youtube_platform_unique_id_backfill")
    assert rev022.down_revision == "021_influencer_platform_unique_id"
