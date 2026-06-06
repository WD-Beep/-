"""Tests-local DB root (avoid system temp dir permission issues)."""
from __future__ import annotations

import shutil
import sqlite3
import time
import uuid
from pathlib import Path

import quote_upload_storage as qus


def release_sqlite_db_locks(db_path: Path) -> None:
    """Checkpoint WAL and close handles so Windows can delete quotes.db/-wal/-shm."""
    path = Path(db_path)
    if not path.is_file():
        return
    try:
        conn = sqlite3.connect(str(path), timeout=2.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        pass
    time.sleep(0.05)


def mount_isolated_quote_db() -> tuple[Path, tuple]:
    root = Path(__file__).resolve().parent / "_pytest_data" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    saved = (qus.ROOT, qus.DATA_DIR, qus.UPLOADS_DIR, qus.DB_PATH)
    qus.ROOT = root
    qus.DATA_DIR = root / "data"
    qus.UPLOADS_DIR = root / "data" / "uploads"
    qus.DB_PATH = root / "data" / "quotes.db"
    qus.init_quote_storage()
    return root, saved


def restore_quote_db(saved: tuple) -> None:
    qus.ROOT, qus.DATA_DIR, qus.UPLOADS_DIR, qus.DB_PATH = saved
    qus._invalidate_admin_cache()


def cleanup_isolated_quote_db(root: Path) -> None:
    db_path = root / "data" / "quotes.db"
    release_sqlite_db_locks(db_path)
    for attempt in range(3):
        try:
            shutil.rmtree(root)
            return
        except PermissionError:
            release_sqlite_db_locks(db_path)
            if attempt >= 2:
                shutil.rmtree(root, ignore_errors=True)
                return
            time.sleep(0.1 * (attempt + 1))
        except OSError:
            shutil.rmtree(root, ignore_errors=True)
            return


WECOM_TEST_SALES_SECRET = "pytest-wecom-sales-secret"
WECOM_TEST_UA = "Mozilla/5.0 wxwork/4.0"


def sales_user_cookie(sales_user_id: str, *, session_id: str | None = None, sales_user_name: str = "") -> str:
    sid = session_id or uuid.uuid4().hex
    parts = [f"aq_sales_user_id={sales_user_id}", f"aq_session_id={sid}"]
    if sales_user_name:
        from urllib import parse as urllib_parse

        parts.append(f"aq_sales_user_name={urllib_parse.quote(sales_user_name, safe='')}")
    return "; ".join(parts)


def wecom_sales_user_cookie(userid: str, *, name: str = "", session_id: str | None = None) -> str:
    from sales_auth import issue_sales_session_token

    sid = session_id or uuid.uuid4().hex
    token = issue_sales_session_token(f"wecom:{userid}", name)
    return f"aq_sales_sess={token}; aq_session_id={sid}"


def forged_wecom_plain_cookie(userid: str, *, name: str = "", session_id: str | None = None) -> str:
    """仅用于测试：伪造未签名的明文 Cookie（应被拒绝）。"""
    sid = session_id or uuid.uuid4().hex
    parts = [f"aq_sales_user_id=wecom:{userid}", f"aq_session_id={sid}"]
    if name:
        from urllib import parse as urllib_parse

        parts.append(f"aq_sales_user_name={urllib_parse.quote(name, safe='')}")
    return "; ".join(parts)
