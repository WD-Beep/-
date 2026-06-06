"""价格学习闭环：发现 → 审核 → 写库 → reload。"""
from __future__ import annotations

import json
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

from core.knowledge_pending_apply import apply_pending_auto_learn
from price_admin_store import (
    AUTO_PENDING_MARKER,
    AUTO_SYNC_MARKER,
    approve_price_exception,
    approve_price_exceptions_bulk,
    enqueue_price_learn_candidate,
    list_price_entries,
    list_price_exceptions,
    reject_price_exception,
    sync_quote_detail_rows_to_price_kb,
)
from price_learn_candidate import QUEUE_QUOTE_SYNC_SUGGESTIONS
from price_kb import get_price_kb, reset_price_kb
from price_kb_paths import official_kb_write_allowed


@unittest.skipIf(Workbook is None, "openpyxl is required")
class PriceLearnLoopTest(unittest.TestCase):
    def _root(self) -> Path:
        root = Path(__file__).resolve().parents[1] / "data" / f"_tmp_learn_loop_{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _kb(self, root: Path, rows: list[tuple[str, str, str]] | None = None) -> Path:
        kb_path = root / "price_kb.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "材料询价"
        ws.append(["材料名称", "规格大小", "单价", "标记", "状态", "备注", "更新时间", "更新人"])
        for name, spec, price in rows or []:
            ws.append([name, spec, price, "", "active", "", "2026-06-06 10:00:00", "seed"])
        wb.save(kb_path)
        wb.close()
        return kb_path

    def test_quote_auto_learn_default_blocked_from_official_kb(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLOW_OFFICIAL_KB_AUTO_LEARN", None)
            os.environ.pop("ALLOW_OFFICIAL_KB_WRITE", None)
            self.assertFalse(
                official_kb_write_allowed(updated_by="quote_auto_learn", source="quote_auto_learn")
            )
            self.assertTrue(official_kb_write_allowed(updated_by="admin", source="admin_approve"))

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_missing_price_generates_pending_candidate(self, _n: object, _r: object) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root)
            exc_path = root / "price_exceptions.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "Q-MISS-001",
                        "product_name": "篮球包",
                        "detail_rows": [
                            {"name": "新织带", "spec": "20MM", "unit_price": "", "kb_hit": False},
                        ],
                    },
                    kb_path=kb_path,
                    history_path=root / "history.jsonl",
                    exception_path=exc_path,
                )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertGreaterEqual(summary["pending"], 1)
            pending, total = list_price_exceptions(page=1, page_size=20, exception_path=exc_path)
            self.assertEqual(total, 1)
            self.assertEqual(pending[0].get("source_type"), "missing_price")
            self.assertIn("candidate_id", pending[0])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_ai_estimate_only_pending_not_kb(self, _n: object, _r: object) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root)
            exc_path = root / "price_exceptions.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "Q-AI-002",
                        "product_name": "篮球包",
                        "detail_rows": [
                            {
                                "name": "210D涤纶",
                                "spec": "152cm",
                                "unit_price": "12.5元/㎡",
                                "source": "ai",
                                "unit_price_ai": True,
                            }
                        ],
                    },
                    kb_path=kb_path,
                    history_path=root / "history.jsonl",
                    exception_path=exc_path,
                )
            self.assertEqual(summary["auto_inserted"], 0)
            self.assertEqual(summary["pending"], 1)
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 0)
            pending, _ = list_price_exceptions(page=1, page_size=20, exception_path=exc_path)
            self.assertEqual(pending[0].get("source_type"), "ai_estimate")
            self.assertEqual(pending[0].get("marker"), AUTO_PENDING_MARKER)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_approve_writes_kb_and_reload(self, mock_reload: object, _n: object) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root)
            exc_path = root / "price_exceptions.jsonl"
            hist_path = root / "history.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "Q-APPROVE-001",
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
                    kb_path=kb_path,
                    history_path=hist_path,
                    exception_path=exc_path,
                )
                pending, _ = list_price_exceptions(page=1, page_size=20, exception_path=exc_path)
                exc_id = str(pending[0]["exception_id"])
                result = approve_price_exception(
                    exc_id,
                    {
                        "name": "600D牛津布",
                        "spec": "140*90CM",
                        "price": "14元/码²",
                        "updated_by": "admin_tester",
                    },
                    kb_path=kb_path,
                    history_path=hist_path,
                    exception_path=exc_path,
                )
            self.assertTrue(result.get("ok"))
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 1)
            self.assertEqual(items[0]["price"], "14元/码²")
            self.assertEqual(getattr(mock_reload, "call_count", 0), 1)
            reset_price_kb()
            kb = get_price_kb(kb_path)
            hit = kb.lookup("600D牛津布", "140*90CM", min_score=0.1)
            self.assertIsNotNone(hit)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_reject_does_not_write_kb(self, mock_reload: object, _n: object) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root)
            exc_path = root / "price_exceptions.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "Q-REJECT-001",
                        "product_name": "篮球包",
                        "detail_rows": [
                            {"name": "新扣具", "spec": "25MM", "unit_price": "1.2元/个", "kb_hit": False},
                        ],
                    },
                    kb_path=kb_path,
                    exception_path=exc_path,
                )
                pending, _ = list_price_exceptions(page=1, page_size=20, exception_path=exc_path)
                exc_id = str(pending[0]["exception_id"])
                reject_price_exception(exc_id, exception_path=exc_path, reject_reason="测试驳回")
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 0)
            self.assertEqual(getattr(mock_reload, "call_count", 0), 0)
            open_rows, open_total = list_price_exceptions(
                page=1, page_size=20, status="open", exception_path=exc_path
            )
            self.assertEqual(open_total, 0)
            self.assertEqual(len(open_rows), 0)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_duplicate_candidate_deduped(self, _n: object, _r: object) -> None:
        root = self._root()
        try:
            exc_path = root / "price_exceptions.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                first = enqueue_price_learn_candidate(
                    material_name="dedupe-row",
                    spec="M",
                    new_price="2.5/PCS",
                    source_type="smart_lookup_miss",
                    exception_path=exc_path,
                )
                second = enqueue_price_learn_candidate(
                    material_name="dedupe-row",
                    spec="M",
                    new_price="2.5/PCS",
                    source_type="smart_lookup_miss",
                    exception_path=exc_path,
                )
            self.assertEqual(first.get("candidate_id"), second.get("candidate_id"))
            pending, total = list_price_exceptions(page=1, page_size=50, exception_path=exc_path)
            self.assertEqual(total, 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_price_conflict_stays_pending(self, _n: object, _r: object) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root, [("600D牛津布", "140*90CM", "14元/码²")])
            exc_path = root / "price_exceptions.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "Q-CONF-002",
                        "product_name": "篮球包",
                        "detail_rows": [
                            {
                                "name": "600D牛津布",
                                "spec": "140*90CM",
                                "unit_price": "60元/码²",
                                "kb_hit": True,
                            }
                        ],
                    },
                    kb_path=kb_path,
                    exception_path=exc_path,
                )
                self.assertEqual(summary["conflicts"], 1)
                with self.assertRaises(ValueError):
                    pending, _ = list_price_exceptions(page=1, page_size=20, exception_path=exc_path)
                    approve_price_exception(
                        str(pending[0]["exception_id"]),
                        {
                            "name": "600D牛津布",
                            "spec": "140*90CM",
                            "price": "60元/码²",
                            "updated_by": "admin",
                        },
                        kb_path=kb_path,
                        exception_path=exc_path,
                    )
            items, _ = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(items[0]["price"], "14元/码²")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_pending_apply_enqueues_not_writes_kb(self, _n: object, _r: object) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root)
            pending_file = root / "pending_auto_learn.jsonl"
            exc_path = root / "price_exceptions.jsonl"
            pending_file.write_text(
                '{"type":"kb_auto_learn_candidate","confidence":0.96,'
                '"material":{"name":"pending-enqueue-row","spec":"XL","price":"2.50/PCS"}}\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                result = apply_pending_auto_learn(
                    pending_file=pending_file,
                    kb_path=kb_path,
                    min_confidence=0.8,
                    reload_after_write=False,
                    exception_path=exc_path,
                )
            self.assertEqual(result.applied, 1)
            self.assertEqual(result.enqueued, 1)
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 0)
            pending, exc_total = list_price_exceptions(page=1, page_size=20, exception_path=exc_path)
            self.assertEqual(exc_total, 1)
            self.assertEqual(pending[0]["name"], "pending-enqueue-row")
        finally:
            shutil.rmtree(root, ignore_errors=True)


    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_abnormal_price_blocked_on_approve(self, _n: object, _r: object) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root)
            exc_path = root / "price_exceptions.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                row = enqueue_price_learn_candidate(
                    material_name="300D??",
                    spec="152cm",
                    new_price="10.5?/Y",
                    source_type="smart_lookup_miss",
                    exception_path=exc_path,
                )
                with self.assertRaises(ValueError):
                    approve_price_exception(
                        str(row["exception_id"]),
                        {
                            "name": "300D??",
                            "spec": "152cm",
                            "price": "10.5?/Y",
                            "updated_by": "admin",
                        },
                        kb_path=kb_path,
                        exception_path=exc_path,
                    )
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 0)
        finally:
            shutil.rmtree(root, ignore_errors=True)


    @patch("price_admin_store.note_kb_disk_write_success")
    def test_e2e_sync_approve_real_reload_and_smart_lookup_hit(self, _n: object) -> None:
        """端到端：候选 -> 审核 -> 写 xlsx -> 真实 reload -> smart_lookup 命中。"""
        from core.smart_lookup import smart_lookup

        root = self._root()
        try:
            kb_path = self._kb(root)
            exc_path = root / "price_exceptions.jsonl"
            hist_path = root / "history.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root), "EMBEDDING_ENABLED": "0"}):
                sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "Q-E2E-001",
                        "product_name": "篮球包",
                        "detail_rows": [
                            {
                                "name": "E2E测试牛津布",
                                "spec": "150CM",
                                "unit_price": "13.5元/码",
                                "kb_hit": False,
                                "source": "kb",
                            }
                        ],
                    },
                    kb_path=kb_path,
                    history_path=hist_path,
                    exception_path=exc_path,
                )
                pending, _ = list_price_exceptions(page=1, page_size=20, exception_path=exc_path)
                exc_id = str(pending[0]["exception_id"])
                approve_price_exception(
                    exc_id,
                    {
                        "name": "E2E测试牛津布",
                        "spec": "150CM",
                        "price": "13.5元/码",
                        "updated_by": "admin_e2e",
                    },
                    kb_path=kb_path,
                    history_path=hist_path,
                    exception_path=exc_path,
                )
                reset_price_kb()
                lookup = smart_lookup("E2E测试牛津布", "150CM", kb=get_price_kb(kb_path))
            self.assertTrue(lookup.get("kb_hit"))
            self.assertIn("13.5", str(lookup.get("unit_price") or ""))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_unified_queue_reads_legacy_suggestion_file(self, _n: object, _r: object) -> None:
        root = self._root()
        try:
            exc_path = root / "price_exceptions.jsonl"
            sugg_path = root / "quote_sync_suggestions.jsonl"
            sugg_path.write_text(
                json.dumps(
                    {
                        "name": "LEGACY-SYNC-ROW",
                        "spec": "25MM",
                        "price": "0.55/M",
                        "status": "pending_review",
                        "source": "quote_auto_sync",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                with patch("price_admin_store.quote_sync_suggestions_path", return_value=sugg_path):
                    with patch("price_admin_store.LEGACY_EXCEPTION_PATH", root / "_no_legacy.jsonl"):
                        pending, total = list_price_exceptions(page=1, page_size=20)
            row = next(x for x in pending if x.get("name") == "LEGACY-SYNC-ROW")
            self.assertEqual(row.get("queue_source"), QUEUE_QUOTE_SYNC_SUGGESTIONS)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_auto_insert_trusted_entries_never_writes_kb(self, _n: object, _r: object) -> None:
        from price_admin_store import _auto_insert_trusted_entries

        root = self._root()
        try:
            kb_path = self._kb(root)
            exc_path = root / "price_exceptions.jsonl"
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                inserted, fallback = _auto_insert_trusted_entries(
                    [
                        {
                            "name": "AUTO-TRUST-ROW",
                            "spec": "M",
                            "price": "1.2/PCS",
                            "marker": AUTO_SYNC_MARKER,
                        }
                    ],
                    kb_path=kb_path,
                    history_path=root / "history.jsonl",
                    quote_id="Q-AUTO",
                    product_name="篮球包",
                )
            self.assertEqual(inserted, [])
            self.assertEqual(fallback, [])
            items, total = list_price_entries(page=1, page_size=20, kb_path=kb_path)
            self.assertEqual(total, 0)
            pending, exc_total = list_price_exceptions(page=1, page_size=20, exception_path=exc_path)
            self.assertEqual(exc_total, 1)
            self.assertEqual(pending[0]["name"], "AUTO-TRUST-ROW")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
