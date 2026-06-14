"""报价价格自主学习：候选 → 统计建议 → 批准/驳回 → 正式覆盖层。"""
from __future__ import annotations

import os
import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

try:
    from openpyxl import Workbook
except Exception:  # pragma: no cover
    Workbook = None

import quote_price_auto_learning as qpal
from price_admin_store import lookup_confirmed_price_override, upsert_confirmed_price_override
from price_kb import apply_material_price_lookup
from price_source_resolver import PRICE_SOURCE_OVERRIDE


@unittest.skipIf(Workbook is None, "openpyxl is required")
class QuotePriceAutoLearningTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_conn = qpal._TEST_CONN
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        qpal._TEST_CONN = conn
        qpal.ensure_price_learning_tables()

    def tearDown(self) -> None:
        if qpal._TEST_CONN is not None:
            qpal._TEST_CONN.close()
        qpal._TEST_CONN = self._old_conn

    def _root(self) -> Path:
        root = Path(__file__).resolve().parents[1] / "data" / f"_tmp_qpal_{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _kb(self, root: Path) -> Path:
        kb_path = root / "price_kb.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "材料询价"
        ws.append(["材料名称", "规格大小", "单价", "标记", "状态", "备注", "更新时间", "更新人"])
        wb.save(kb_path)
        wb.close()
        return kb_path

    def _record_deviation(
        self,
        *,
        material: str = "测试织带",
        spec: str = "20MM",
        system_price: str = "10",
        manual_price: str = "12.5",
        quote_uid: str | None = None,
    ) -> dict | None:
        return qpal.record_price_learning_candidate(
            quote_uid=quote_uid or f"q-{uuid.uuid4().hex[:6]}",
            quote_id="Q-TEST",
            material_name=material,
            spec=spec,
            system_price=system_price,
            manual_price=manual_price,
            correction_reason="测试改价",
        )

    def test_small_deviation_skipped(self) -> None:
        row = self._record_deviation(system_price="10", manual_price="10.5")
        self.assertIsNone(row)
        items = qpal.list_learning_records(learning_status=qpal.LEARNING_CANDIDATE)
        self.assertEqual(len(items), 0)

    def test_large_deviation_creates_candidate(self) -> None:
        row = self._record_deviation()
        self.assertIsNotNone(row)
        self.assertEqual(row["learning_status"], qpal.LEARNING_CANDIDATE)
        self.assertGreater(abs(float(row["deviation_pct"])), qpal.DEVIATION_THRESHOLD_PCT)
        items = qpal.list_learning_records(learning_status=qpal.LEARNING_CANDIDATE)
        self.assertEqual(len(items), 1)

    def test_three_deviations_generate_pending_suggestion(self) -> None:
        for _ in range(3):
            self._record_deviation()
        suggestions = qpal.list_learning_suggestions(status=qpal.SUGGESTION_PENDING)
        self.assertEqual(len(suggestions), 1)
        sug = suggestions[0]
        self.assertGreaterEqual(int(sug["sample_count"]), 3)
        self.assertGreater(abs(float(sug["avg_deviation_pct"])), qpal.DEVIATION_THRESHOLD_PCT)
        self.assertLessEqual(abs(float(sug["suggested_adjust_pct"])), qpal.MAX_AUTO_SUGGEST_ADJUST_PCT)

    @patch("core.knowledge_reload.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_approve_writes_override_and_rule_applied(self, _n: object, _r: object) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root)
            override_path = root / "price_overrides.jsonl"
            for _ in range(3):
                self._record_deviation(material="学习批准织带", spec="25MM")
            sug = qpal.list_learning_suggestions(status=qpal.SUGGESTION_PENDING)[0]
            env = {
                "PRICE_REVIEW_DATA_DIR": str(root),
                "PRICE_KB_OFFICIAL_PATH": str(kb_path),
            }
            with patch.dict(os.environ, env, clear=False):
                result = qpal.approve_learning_suggestion(
                    str(sug["suggestion_id"]),
                    approved_by="boss_tester",
                    final_price="12.5元/米",
                )
            self.assertTrue(result.get("ok"))
            self.assertEqual(result.get("rule_source"), "manual_approved_learning")
            hit = lookup_confirmed_price_override("学习批准织带", "25MM", override_path=override_path)
            self.assertIsNotNone(hit)
            self.assertEqual(hit.get("source_type"), "manual_approved_learning")
            with patch.dict(os.environ, env, clear=False):
                fields = apply_material_price_lookup(
                    material_name="学习批准织带",
                    spec="25MM",
                    existing_row={"name": "学习批准织带", "spec": "25MM", "unit_price": "-"},
                    kb_hit=None,
                )
            self.assertEqual(fields.get("price_source"), PRICE_SOURCE_OVERRIDE)
            self.assertEqual(fields.get("rule_applied"), "manual_approved_learning")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_reject_does_not_write_override(self) -> None:
        root = self._root()
        try:
            override_path = root / "price_overrides.jsonl"
            for _ in range(3):
                self._record_deviation(material="学习驳回织带", spec="30MM")
            sug = qpal.list_learning_suggestions(status=qpal.SUGGESTION_PENDING)[0]
            result = qpal.reject_learning_suggestion(
                str(sug["suggestion_id"]),
                operator="admin_tester",
                reason="样本不代表常态",
            )
            self.assertTrue(result.get("ok"))
            self.assertIsNone(
                lookup_confirmed_price_override("学习驳回织带", "30MM", override_path=override_path)
            )
            pending = qpal.list_learning_suggestions(status=qpal.SUGGESTION_PENDING)
            self.assertEqual(len(pending), 0)
            records = qpal.list_learning_records(learning_status=qpal.LEARNING_REJECTED)
            self.assertGreaterEqual(len(records), 3)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_special_material_blocked_from_suggestion(self) -> None:
        for _ in range(3):
            self._record_deviation(material="稀有进口真皮", spec="-", system_price="100", manual_price="130")
        suggestions = qpal.list_learning_suggestions(status=qpal.SUGGESTION_PENDING)
        self.assertEqual(len(suggestions), 0)

    def test_exclude_learning_record(self) -> None:
        row = self._record_deviation()
        assert row is not None
        result = qpal.exclude_learning_record(str(row["record_id"]), operator="admin")
        self.assertTrue(result.get("ok"))
        items = qpal.list_learning_records(learning_status=qpal.LEARNING_EXCLUDED)
        self.assertEqual(len(items), 1)

    def test_patch_deal_info_on_record(self) -> None:
        row = self._record_deviation()
        assert row is not None
        result = qpal.patch_learning_record_deal_info(
            str(row["record_id"]),
            deal_status=qpal.DEAL_DEAL,
            final_price="11.8",
            loss_reason="",
            operator="admin",
        )
        self.assertTrue(result.get("ok"))
        items = qpal.list_learning_records(learning_status=qpal.LEARNING_CANDIDATE)
        self.assertEqual(items[0]["deal_status"], qpal.DEAL_DEAL)
        self.assertEqual(items[0]["final_price"], "11.8")

    def test_pending_suggestion_does_not_affect_lookup(self) -> None:
        root = self._root()
        try:
            kb_path = self._kb(root)
            for _ in range(3):
                self._record_deviation(material="待审不影响织带", spec="18MM", system_price="8", manual_price="10")
            env = {
                "PRICE_REVIEW_DATA_DIR": str(root),
                "PRICE_KB_OFFICIAL_PATH": str(kb_path),
            }
            with patch.dict(os.environ, env, clear=False):
                fields = apply_material_price_lookup(
                    material_name="待审不影响织带",
                    spec="18MM",
                    existing_row={"name": "待审不影响织带", "spec": "18MM", "unit_price": "-"},
                    kb_hit=None,
                )
            self.assertNotEqual(fields.get("rule_applied"), "manual_approved_learning")
            self.assertNotIn("manual_approved_learning", str(fields.get("learning_rule_source") or ""))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_quote_engine_detail_rows_include_price_trace(self) -> None:
        from quote_engine import calculate_quote

        payload = {
            "items": [
                {
                    "name": "测试追溯织带",
                    "spec": "20MM",
                    "usage": "1米",
                    "unit_price": "12.5元/米",
                    "amount": 12.5,
                    "price_source": "override",
                    "rule_applied": "manual_approved_learning",
                    "learning_rule_source": "manual_approved_learning",
                    "override_id": "ov-test-1",
                    "evidence": "人工批准学习规则",
                }
            ],
            "quantities": [300],
        }
        result = calculate_quote(payload)
        row = (result.get("detail_rows") or [{}])[0]
        self.assertEqual(row.get("rule_applied"), "manual_approved_learning")
        self.assertEqual(row.get("learning_rule_source"), "manual_approved_learning")
        self.assertEqual(row.get("override_id"), "ov-test-1")
        self.assertEqual(row.get("evidence"), "人工批准学习规则")
        self.assertEqual(row.get("price_source"), "override")


if __name__ == "__main__":
    unittest.main()
