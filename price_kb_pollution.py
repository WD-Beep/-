"""识别并过滤测试污染的价格库待审记录。"""
from __future__ import annotations

import re
from typing import Any

_TEST_PRODUCT_EXACT = frozenset(
    {
        "测试包",
        "quality bag",
        "quality-bag",
        "qa test bag",
        "pytest bag",
    }
)

_TEST_QUOTE_ID_PREFIXES = (
    "q-quality-drop",
    "q-quality",
    "pytest-",
    "test-quote-",
)

_TEST_NOTE_MARKERS = (
    "pytest",
    "integration test",
    "验收测试",
    "test_quote",
)


def _norm(s: object) -> str:
    return str(s or "").strip()


def is_test_product_name(product_name: object) -> bool:
    name = _norm(product_name)
    if not name:
        return False
    low = name.lower()
    if low in _TEST_PRODUCT_EXACT:
        return True
    if "测试包" in name or "测试报价" in name:
        return True
    if "quality" in low and "bag" in low:
        return True
    if re.fullmatch(r"测试[\w\-]*包?", name, re.I):
        return True
    return False


def is_test_quote_id(quote_id: object) -> bool:
    qid = _norm(quote_id)
    if not qid:
        return False
    low = qid.lower()
    for prefix in _TEST_QUOTE_ID_PREFIXES:
        if low.startswith(prefix):
            return True
    if low.startswith("q-") and "quality" in low:
        return True
    return False


def is_test_price_exception_record(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    if is_test_product_name(record.get("product_name")):
        return True
    if is_test_quote_id(record.get("source_quote_id")):
        return True
    note = _norm(record.get("note")).lower()
    if any(m in note for m in _TEST_NOTE_MARKERS):
        return True
    if "产品：测试包" in _norm(record.get("note")):
        return True
    by = _norm(record.get("updated_by")).lower()
    if by == "pytest":
        return True
    return False


def is_test_auto_drop_record(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    if is_test_product_name(record.get("product_name")):
        return True
    if is_test_quote_id(record.get("source_quote_id")):
        return True
    return False


def is_test_quote_sync_context(quote_result: dict[str, Any] | None) -> bool:
    if not isinstance(quote_result, dict):
        return False
    if is_test_product_name(quote_result.get("product_name")):
        return True
    if is_test_quote_id(quote_result.get("quote_id")):
        return True
    md = quote_result.get("metadata")
    if isinstance(md, dict) and md.get("is_test"):
        return True
    return False


def filter_visible_exceptions(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    visible: list[dict[str, Any]] = []
    hidden = 0
    for rec in records:
        if is_test_price_exception_record(rec):
            hidden += 1
            continue
        visible.append(rec)
    return visible, hidden
