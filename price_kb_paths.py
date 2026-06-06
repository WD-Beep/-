"""正式价格库与本地待审核队列路径（单一真相源）。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 正式价格知识库（只读用于报价；人工/审批写入需显式放行）
OFFICIAL_KB_FILENAME = "栢博材料询价登记表_三列_含本批追加.xlsx"
OFFICIAL_KB_PATH_DEFAULT = Path(f"D:/知识库/{OFFICIAL_KB_FILENAME}")

# 项目内遗留副本，不再作为正式数据源
LEGACY_PROJECT_KB_PATH = ROOT / "data" / "price_kb.xlsx"
LEGACY_EXCEPTION_PATH = ROOT / "data" / "price_exceptions.jsonl"
LEGACY_DROP_LOG_PATH = ROOT / "data" / "price_auto_drops.jsonl"


def official_kb_path() -> Path:
    raw = os.environ.get("PRICE_KB_OFFICIAL_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return OFFICIAL_KB_PATH_DEFAULT.resolve()


def review_data_dir() -> Path:
    raw = os.environ.get("PRICE_REVIEW_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (ROOT / "data" / "price_review").resolve()


def exception_path() -> Path:
    return review_data_dir() / "price_exceptions.jsonl"


def drop_log_path() -> Path:
    return review_data_dir() / "price_auto_drops.jsonl"


def history_path() -> Path:
    return review_data_dir() / "price_kb_history.jsonl"


def quote_sync_suggestions_path() -> Path:
    return review_data_dir() / "quote_sync_suggestions.jsonl"


def auto_learn_log_path() -> Path:
    return review_data_dir() / "quote_auto_learn_log.jsonl"


def is_official_kb_path(path: Path | str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).expanduser().resolve() == official_kb_path()
    except OSError:
        return False


def official_kb_write_allowed(*, updated_by: str = "", source: str = "") -> bool:
    """正式库默认禁止自动写入；仅后台管理员确认或显式环境变量放行。"""
    by = str(updated_by or "").strip().lower()
    src = str(source or "").strip().lower()
    if src in {"pytest", "test", "auto_sync", "knowledge_auto", "agent_auto", "quote_auto_learn"}:
        return False
    if by in {"agent_auto", "system", "pytest", "test", "quote_auto_learn"}:
        return False
    if os.environ.get("ALLOW_OFFICIAL_KB_WRITE", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if src in {"admin_upsert", "admin_import", "admin_approve"}:
        return True
    if src == "quote_auto_learn" and os.environ.get(
        "ALLOW_OFFICIAL_KB_AUTO_LEARN", "0"
    ).strip().lower() in {"1", "true", "yes"}:
        return True
    if src in {"", "admin_upsert"} and by in {"admin", "pm", "operator"}:
        return True
    return False


def assert_official_kb_write_allowed(
    path: Path | str,
    *,
    updated_by: str = "",
    source: str = "",
) -> Path:
    target = Path(path).expanduser().resolve()
    if is_official_kb_path(target) and not official_kb_write_allowed(updated_by=updated_by, source=source):
        raise PermissionError(
            "禁止向正式价格库自动写入。"
            f" 目标={target}；请仅通过后台人工确认后写入，或使用待审核队列。"
        )
    return target


def admin_price_meta() -> dict[str, str | bool]:
    """后台价格库页：数据源说明。"""
    official = official_kb_path()
    review = review_data_dir()
    return {
        "official_kb_path": str(official),
        "official_kb_exists": official.is_file(),
        "official_kb_readonly_for_auto": True,
        "review_data_dir": str(review),
        "exception_queue_path": str(exception_path()),
        "quote_sync_suggestions_path": str(quote_sync_suggestions_path()),
        "legacy_exception_path": str(LEGACY_EXCEPTION_PATH),
        "legacy_kb_path": str(LEGACY_PROJECT_KB_PATH),
    }
