"""价格知识库自动学习 / 异常待审核规则验收。"""
from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

try:
    from openpyxl import Workbook
except Exception:  # pragma: no cover
    Workbook = None

from kb_data_quality import KB_ACTION_AUTO, KB_ACTION_DROP, KB_ACTION_REVIEW, judge_kb_insert_candidate
from price_admin_store import (
    AUTO_CONFLICT_MARKER,
    AUTO_PENDING_MARKER,
    list_price_entries,
    list_price_exceptions,
    price_admin_stats,
    price_exception_stats,
    sync_quote_detail_rows_to_price_kb,
)


@unittest.skipIf(Workbook is None, "openpyxl is required")
class KbAutoLearnRulesTest(unittest.TestCase):
    def _make_root(self) -> Path:
        root = Path(__file__).resolve().parents[1] / "data" / f"_tmp_kb_learn_{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _make_kb(self, root: Path, rows: list[tuple[str, str, str]] | None = None) -> Path:
        kb_path = root / "price_kb.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "材料询价"
        ws.append(["材料名称", "规格大小", "单价", "标记", "状态", "备注", "更新时间", "更新人"])
        for name, spec, price in rows or []:
            ws.append([name, spec, price, "", "active", "", "2026-06-05 10:00:00", "seed"])
        wb.save(kb_path)
        wb.close()
        return kb_path

    def _sync(self, root: Path, kb_path: Path, quote: dict) -> dict:
        with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
            return sync_quote_detail_rows_to_price_kb(
                quote,
                kb_path=kb_path,
                history_path=root / "history.jsonl",
                exception_path=root / "price_exceptions.jsonl",
            )

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_trusted_fabric_auto_inserts(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root)
            summary = self._sync(
                root,
                kb_path,
                {
                    "quote_ready": True,
                    "quote_id": "Q-FAB-001",
                    "product_name": "篮球包",
                    "detail_rows": [
                        {
                            "name": "600D牛津布",
                            "spec": "140*90CM",
                            "unit_price": "14元/码²",
                            "kb_hit": False,
                            "source": "kb",
                        }
                    ],
                },
            )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertEqual(summary["pending"], 1)
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 0)
            pending, pending_total = list_price_exceptions(
                page=1, page_size=20, exception_path=root / "price_exceptions.jsonl"
            )
            self.assertEqual(pending_total, 1)
            self.assertEqual(pending[0]["name"], "600D牛津布")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_trusted_zipper_auto_inserts(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root)
            summary = self._sync(
                root,
                kb_path,
                {
                    "quote_ready": True,
                    "quote_id": "Q-ZIP-001",
                    "product_name": "篮球包",
                    "detail_rows": [
                        {
                            "name": "#5尼龙拉链",
                            "spec": "#5",
                            "unit_price": "0.3元/条",
                            "kb_hit": True,
                            "source": "kb",
                        }
                    ],
                },
            )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertEqual(summary["pending"], 1)
            items, _ = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(len(items), 0)
            pending, total = list_price_exceptions(
                page=1, page_size=20, exception_path=root / "price_exceptions.jsonl"
            )
            self.assertEqual(total, 1)
            self.assertEqual(pending[0]["price"], "0.3元/条")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_ai_inferred_goes_pending_review(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root)
            summary = self._sync(
                root,
                kb_path,
                {
                    "quote_ready": True,
                    "quote_id": "Q-AI-001",
                    "product_name": "篮球包",
                    "detail_rows": [
                        {
                            "name": "210D涤纶",
                            "spec": "152cm",
                            "unit_price": "12.5579元/㎡",
                            "source": "ai",
                            "unit_price_ai": True,
                        }
                    ],
                },
            )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertEqual(summary["pending"], 1)
            pending, total = list_price_exceptions(
                page=1, page_size=20, exception_path=root / "price_exceptions.jsonl"
            )
            self.assertEqual(total, 1)
            self.assertEqual(pending[0]["marker"], AUTO_PENDING_MARKER)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_suspicious_slider_price_from_kb_goes_pending_review(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root)
            summary = self._sync(
                root,
                kb_path,
                {
                    "quote_ready": True,
                    "quote_id": "Q-SLIDER-001",
                    "product_name": "双层保温午餐包",
                    "detail_rows": [
                        {
                            "name": "黑色拉头*1",
                            "spec": "普通拉头",
                            "unit_price": "60元/个",
                            "kb_hit": True,
                            "source": "kb",
                        }
                    ],
                },
            )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertEqual(summary["pending"], 1)
            pending, total = list_price_exceptions(
                page=1, page_size=20, exception_path=root / "price_exceptions.jsonl"
            )
            self.assertEqual(total, 1)
            self.assertEqual(pending[0]["marker"], AUTO_PENDING_MARKER)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_suspicious_metal_zipper_price_from_kb_goes_pending_review(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root)
            summary = self._sync(
                root,
                kb_path,
                {
                    "quote_ready": True,
                    "quote_id": "Q-ZIPPER-001",
                    "product_name": "双层保温午餐包",
                    "detail_rows": [
                        {
                            "name": "金色金属拉链",
                            "spec": "金色金属拉链",
                            "unit_price": "120元/条",
                            "usage": "0.2米",
                            "kb_hit": True,
                            "source": "kb",
                        }
                    ],
                },
            )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertEqual(summary["pending"], 1)
            pending, total = list_price_exceptions(
                page=1, page_size=20, exception_path=root / "price_exceptions.jsonl"
            )
            self.assertEqual(total, 1)
            self.assertEqual(pending[0]["marker"], AUTO_PENDING_MARKER)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_piece_names_drop_not_insert(self) -> None:
        for name in ("前片", "网袋", "隔层", "侧片", "拉链弧形盖"):
            verdict = judge_kb_insert_candidate(name, "19×45", "2元/个")
            self.assertEqual(verdict.action, KB_ACTION_DROP, name)

    def test_system_estimate_packaging_not_inserted(self) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root, [("EXISTING", "A", "1/PCS")])
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "Q-PACK-001",
                        "product_name": "篮球包",
                        "detail_rows": [
                            {
                                "name": "外纸箱/包装费（系统估算）",
                                "spec": "系统估算",
                                "unit_price": "2.00元/个",
                            }
                        ],
                    },
                    kb_path=kb_path,
                    history_path=root / "history.jsonl",
                    exception_path=root / "price_exceptions.jsonl",
                )
            self.assertEqual(summary.get("auto_inserted", 0), 0)
            self.assertEqual(summary.get("pending", 0), 0)
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 1)
            self.assertEqual(items[0]["name"], "EXISTING")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_price_conflict_goes_pending_not_overwrite(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root, [("600D牛津布", "140*90CM", "14元/码²")])
            summary = self._sync(
                root,
                kb_path,
                {
                    "quote_ready": True,
                    "quote_id": "Q-CONFLICT-001",
                    "product_name": "篮球包",
                    "detail_rows": [
                        {
                            "name": "600D牛津布",
                            "spec": "140*90CM",
                            "unit_price": "60元/码²",
                            "kb_hit": True,
                            "source": "kb",
                        }
                    ],
                },
            )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertEqual(summary["conflicts"], 1)
            items, _ = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(items[0]["price"], "14元/码²")
            pending, total = list_price_exceptions(
                page=1, page_size=20, exception_path=root / "price_exceptions.jsonl"
            )
            self.assertEqual(total, 1)
            self.assertEqual(pending[0]["marker"], AUTO_CONFLICT_MARKER)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_duplicate_same_price_not_reinserted(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root, [("#5尼龙拉链", "#5", "0.3元/条")])
            summary = self._sync(
                root,
                kb_path,
                {
                    "quote_ready": True,
                    "quote_id": "Q-DUP-001",
                    "product_name": "篮球包",
                    "detail_rows": [
                        {
                            "name": "#5尼龙拉链",
                            "spec": "#5",
                            "unit_price": "0.3元/条",
                            "kb_hit": True,
                            "source": "kb",
                        }
                    ],
                },
            )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertEqual(summary["skipped"], 1)
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_stats_counts_include_pending_and_ignored(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root)
            self._sync(
                root,
                kb_path,
                {
                    "quote_ready": True,
                    "quote_id": "Q-STAT-001",
                    "product_name": "篮球包",
                    "detail_rows": [
                        {"name": "前片", "spec": "19×45", "unit_price": "1元/个"},
                        {
                            "name": "仿尼龙织带",
                            "spec": "25MM",
                            "unit_price": "0.55元/米",
                            "source": "ai",
                            "unit_price_ai": True,
                        },
                    ],
                },
            )
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root), "PRICE_KB_OFFICIAL_PATH": str(kb_path)}):
                stats = price_admin_stats(kb_path=kb_path)
                exc_stats = price_exception_stats(exception_path=root / "price_exceptions.jsonl")
            self.assertGreaterEqual(exc_stats["open_exceptions"], 1)
            self.assertIn("pending_review_count", exc_stats)
            self.assertIn("ignored_count", exc_stats)
            self.assertGreaterEqual(exc_stats["ignored_count"], 1)
            self.assertIn("official_count", stats)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class KbDataQualityRulesTest(unittest.TestCase):
    def test_inference_marker_review_not_auto(self) -> None:
        verdict = judge_kb_insert_candidate(
            "侧袋（推理待核）",
            "推理待核",
            "2元/个",
            row={"source": "ai", "unit_price_ai": True},
        )
        self.assertEqual(verdict.action, KB_ACTION_DROP)

    def test_missing_spec_ai_review(self) -> None:
        verdict = judge_kb_insert_candidate(
            "210D涤纶",
            "-",
            "12.5元/㎡",
            row={"source": "ai", "unit_price_ai": True},
        )
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)


if __name__ == "__main__":
    unittest.main()
