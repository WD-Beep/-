"""Pytest path: allow ``from test_db_isolation import ...`` inside tests/."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


def _make_minimal_kb_xlsx(path: Path) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "材料询价"
    ws.append(["材料名称", "规格大小", "单价"])
    ws.append(["测试牛津布", "150CM", "12元/码"])
    wb.save(path)
    wb.close()


@pytest.fixture(autouse=True)
def isolate_price_kb_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """禁止 pytest 读写正式知识库与项目内遗留污染文件。"""
    root = _TESTS_DIR / "_pytest_data" / uuid.uuid4().hex
    review = root / "review"
    review.mkdir(parents=True, exist_ok=True)
    official = root / "official_kb.xlsx"
    _make_minimal_kb_xlsx(official)

    monkeypatch.setenv("PRICE_KB_OFFICIAL_PATH", str(official))
    monkeypatch.setenv("PRICE_REVIEW_DATA_DIR", str(review))
    # 禁止误写 D: 正式库
    monkeypatch.delenv("ALLOW_OFFICIAL_KB_WRITE", raising=False)
    monkeypatch.delenv("ALLOW_OFFICIAL_KB_AUTO_APPLY", raising=False)

    import price_kb

    price_kb.reset_price_kb()
    yield
    price_kb.reset_price_kb()
