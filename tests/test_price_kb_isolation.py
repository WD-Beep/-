"""价格库路径、污染过滤与自动学习写入保护。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from price_admin_store import (
    list_price_exceptions,
    price_exception_stats,
    sync_quote_detail_rows_to_price_kb,
)
from price_kb_paths import (
    LEGACY_EXCEPTION_PATH,
    OFFICIAL_KB_PATH_DEFAULT,
    official_kb_path,
    review_data_dir,
)
from price_kb_pollution import (
    filter_visible_exceptions,
    is_test_price_exception_record,
    is_test_quote_sync_context,
)


class PriceKbIsolationTest(unittest.TestCase):
    def test_official_path_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            if "PRICE_KB_OFFICIAL_PATH" in os.environ:
                del os.environ["PRICE_KB_OFFICIAL_PATH"]
            p = official_kb_path()
        self.assertEqual(p, OFFICIAL_KB_PATH_DEFAULT.resolve())

    def test_filter_test_exceptions(self) -> None:
        rows = [
            {
                "exception_id": "ex-1",
                "product_name": "测试包",
                "exception_status": "open",
            },
            {
                "exception_id": "ex-2",
                "product_name": "篮球包",
                "exception_status": "open",
            },
        ]
        visible, hidden = filter_visible_exceptions(rows)
        self.assertEqual(hidden, 1)
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["exception_id"], "ex-2")

    def test_sync_skips_test_quote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review"
            review.mkdir()
            official = Path(tmp) / "kb.xlsx"
            self._write_kb(official)
            with patch.dict(
                os.environ,
                {
                    "PRICE_KB_OFFICIAL_PATH": str(official),
                    "PRICE_REVIEW_DATA_DIR": str(review),
                },
            ):
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_id": "Q-QUALITY-DROP-1",
                        "product_name": "quality bag",
                        "detail_rows": [
                            {
                                "name": "插扣",
                                "spec": "-",
                                "unit_price": "1元/个",
                                "kb_hit": False,
                            }
                        ],
                    }
                )
        self.assertTrue(summary.get("ignored_test_quote"))
        self.assertEqual(summary.get("pending"), 0)
        self.assertEqual(summary.get("suggestions_queued"), 0)

    def test_sync_queues_suggestion_not_official(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review"
            review.mkdir()
            official = Path(tmp) / "kb.xlsx"
            self._write_kb(official)
            with patch.dict(
                os.environ,
                {
                    "PRICE_KB_OFFICIAL_PATH": str(official),
                    "PRICE_REVIEW_DATA_DIR": str(review),
                },
            ):
                from price_kb import get_price_kb, reset_price_kb

                reset_price_kb()
                before = get_price_kb().size
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_id": "real-quote-001",
                        "product_name": "双肩包",
                        "detail_rows": [
                            {
                                "name": "全新辅料XYZ",
                                "spec": "常规",
                                "unit_price": "2.5/M",
                                "kb_hit": False,
                            }
                        ],
                    }
                )
                after = get_price_kb().size
                from price_kb_paths import quote_sync_suggestions_path

                sugg_exists = quote_sync_suggestions_path().is_file()
        self.assertGreaterEqual(int(summary.get("suggestions_queued") or 0), 1)
        self.assertEqual(before, after)
        self.assertTrue(sugg_exists)

    def test_legacy_pollution_hidden_from_list(self) -> None:
        if not LEGACY_EXCEPTION_PATH.is_file():
            self.skipTest("no legacy exception file")
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review"
            review.mkdir()
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(review)}):
                items, total = list_price_exceptions(status="open", page_size=500)
                stats = price_exception_stats()
        self.assertEqual(total, len(items))
        self.assertTrue(all(not is_test_price_exception_record(x) for x in items))
        self.assertGreaterEqual(int(stats.get("hidden_test_pollution") or 0), 1)

    def _write_kb(self, path: Path) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            raise unittest.SkipTest("openpyxl required")
        wb = Workbook()
        ws = wb.active
        ws.title = "材料询价"
        ws.append(["材料名称", "规格大小", "单价"])
        ws.append(["600D牛津布", "150CM", "12元/码"])
        wb.save(path)
        wb.close()


if __name__ == "__main__":
    unittest.main()
