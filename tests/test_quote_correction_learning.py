"""修正反馈闭环：记录、规则应用、可观察性。"""
from __future__ import annotations

import sqlite3
import unittest
import uuid

import quote_correction_learning as qcl
import quote_engine
from material_detail_display import enrich_quote_material_detail_display
from quote_sheet_content import is_trusted_quote_sheet_image_item


class QuoteCorrectionLearningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._conn = sqlite3.connect(":memory:", check_same_thread=False)
        cls._conn.row_factory = sqlite3.Row
        qcl.set_test_connection(cls._conn)
        qcl.ensure_correction_tables(cls._conn)
        qcl._seed_builtin_rules(cls._conn)
        cls._conn.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        qcl.set_test_connection(None)
        cls._conn.close()

    def test_record_correction_history(self) -> None:
        hid = qcl.record_correction(
            quote_uid="uid-1",
            material_name="塑胶插扣",
            field_name="usage",
            old_value="1套",
            new_value="2个",
            corrected_by="admin",
            product_name="双肩包",
            structure_text="双肩包；两侧插扣",
        )
        self.assertTrue(hid)
        row = self._conn.execute(
            "SELECT * FROM quote_correction_history WHERE history_id = ?", (hid,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["new_value"], "2个")

    def test_promote_rule_after_two_similar_corrections(self) -> None:
        for _ in range(2):
            qcl.record_correction(
                quote_uid="uid-2",
                material_name="D扣",
                field_name="usage",
                old_value="1组",
                new_value="2个",
                corrected_by="admin",
                structure_text="左右肩带",
            )
        rule = self._conn.execute(
            "SELECT * FROM quote_correction_rules WHERE rule_id LIKE 'learned-buckle%'"
        ).fetchone()
        self.assertIsNotNone(rule)
        self.assertEqual(rule["corrected_value"], "2个")

    def test_buckle_rule_applies_for_dual_shoulder(self) -> None:
        payload = {
            "product_name": "双肩包",
            "structure_text": "双肩；两侧插扣",
            "items": [
                {
                    "name": "塑胶插扣",
                    "spec": "-",
                    "usage": "1套",
                    "unit_price": "0.5元/个",
                    "amount": 0.5,
                }
            ],
            "quantities": [500],
            "gross_margin_rate": 0.35,
        }
        hits = qcl.apply_correction_rules_to_payload(payload)
        self.assertTrue(hits)
        self.assertEqual(payload["items"][0]["usage"], "2个")
        self.assertEqual(payload["items"][0].get("correction_rule_id"), "builtin-buckle-dual-qty")
        self.assertTrue(payload["items"][0].get("_correction_rule_hits"))

    def test_raw_bom_explicit_usage_not_overridden(self) -> None:
        row = {
            "name": "塑胶插扣",
            "usage": "-",
            "raw_usage": "1个",
            "sheet_usage": "1个",
            "unit_price": "0.5元/个",
        }
        ctx = {"structure_text": "双肩；两侧", "product_name": "双肩包"}
        out, hits = qcl.apply_correction_rules_to_row(row, ctx)
        self.assertEqual(out["usage"], "-")
        self.assertFalse(hits)

    def test_admin_usage_not_overridden(self) -> None:
        row = {
            "name": "塑胶插扣",
            "usage": "1套",
            "admin_corrected_usage": "3个",
            "unit_price": "0.5元/个",
        }
        ctx = {"structure_text": "双肩；两侧", "product_name": "双肩包"}
        out, hits = qcl.apply_correction_rules_to_row(row, ctx)
        self.assertEqual(out.get("admin_corrected_usage"), "3个")
        self.assertFalse(hits)

    def test_calculate_quote_includes_rule_hits(self) -> None:
        result = quote_engine.calculate_quote(
            {
                "product_name": "双肩包",
                "structure_text": "双肩；两侧",
                "items": [
                    {
                        "name": "插扣",
                        "spec": "-",
                        "usage": "1组",
                        "unit_price": "1元/个",
                        "amount": 1.0,
                    }
                ],
                "quantities": [300],
                "gross_margin_rate": 0.35,
            }
        )
        apps = result.get("correction_rule_applications") or []
        self.assertTrue(apps)
        self.assertEqual(apps[0].get("rule_id"), "builtin-buckle-dual-qty")
        self.assertEqual(apps[0].get("applied_value"), "2个")

    def test_pack_rule_hit_and_sanitize(self) -> None:
        text, hits = qcl.apply_customer_pack_text(
            "系统估算 / 1个",
            {"product_name": "篮球包"},
        )
        self.assertEqual(text, "1个")
        self.assertNotIn("系统估算", text)
        self.assertTrue(hits)
        self.assertEqual(hits[0].rule_id, "builtin-customer-pack-sanitize")

    def test_pack_rule_strips_pure_internal(self) -> None:
        text, _hits = qcl.apply_customer_pack_text(
            "系统估算/系统估算",
            {"product_name": "篮球包"},
        )
        self.assertEqual(text, "")
        self.assertNotIn("系统估算", text)

    def test_image_filter_rule_hit(self) -> None:
        item = {"from_sheet_embed": True, "sheet_row": 2, "data_base64": ""}
        ok, hits = qcl.evaluate_product_image_item(item, {"product_name": "包"})
        self.assertFalse(ok)
        self.assertFalse(is_trusted_quote_sheet_image_item(item))
        self.assertTrue(hits)
        self.assertEqual(hits[0].rule_id, "builtin-product-image-filter")
        self.assertEqual(hits[0].mode, "rejected")

    def test_side_piece_part_rule_removes_group(self) -> None:
        row = {
            "name": "600D牛津布",
            "piece_part": "前片 10×22；侧片（2片）（1组）；拉链弧形盖 估算",
        }
        ctx = {"product_name": "包", "structure_text": ""}
        out, hits = qcl.apply_correction_rules_to_row(row, ctx)
        self.assertTrue(hits)
        self.assertNotIn("1组", out.get("piece_part", ""))
        self.assertNotIn("组", out.get("piece_part", ""))
        self.assertEqual(hits[0].field_name, "piece_part")

    def test_capture_bom_multiple_fields(self) -> None:
        uid = f"uid-{uuid.uuid4().hex[:8]}"
        res = qcl.capture_bom_edit_corrections(
            uid,
            old_items=[
                {
                    "name": "插扣",
                    "usage": "1套",
                    "spec": "-",
                    "unit_price": "0.5元/个",
                    "calc_note": "旧",
                }
            ],
            new_items=[
                {
                    "name": "插扣",
                    "usage": "2个",
                    "spec": "常规",
                    "unit_price": "0.6元/个",
                    "calc_note": "新",
                }
            ],
            quote={"product_name": "包", "structure_text": "双肩"},
            corrected_by="admin",
        )
        self.assertTrue(res.ok)
        self.assertGreaterEqual(res.recorded_count, 3)
        rows = self._conn.execute(
            "SELECT field_name FROM quote_correction_history WHERE quote_uid = ?", (uid,)
        ).fetchall()
        fnames = {str(r[0]) for r in rows}
        self.assertIn("usage", fnames)
        self.assertIn("spec", fnames)
        self.assertIn("unit_price", fnames)

    def test_learning_capture_returns_error_on_db_failure(self) -> None:
        class BadConn:
            def execute(self, *a, **k):
                raise sqlite3.OperationalError("disk I/O error")

            def commit(self):
                pass

        old_conn = qcl._TEST_CONN
        try:
            qcl.set_test_connection(BadConn())  # type: ignore[arg-type]
            res = qcl.capture_learning_from_bom_save(
                "uid-fail",
                old_items=[{"name": "x", "usage": "1"}],
                new_items=[{"name": "x", "usage": "2"}],
            )
            self.assertFalse(res.ok)
            self.assertTrue(res.errors)
            self.assertTrue(res.warnings)
        finally:
            qcl.set_test_connection(old_conn)

    def test_side_piece_qty_group_shows_two_pieces_not_group(self) -> None:
        """侧片 qty 1组：展示为 2片，不出现「组」（裁片表 + 展示层）。"""
        quote = {
            "product_name": "双肩包",
            "structure_text": "双肩",
            "detail_rows": [
                {
                    "name": "600D牛津布",
                    "piece_part": "侧片（2片）（1组）",
                    "usage": "1码",
                    "spec": "600D",
                    "amount": 1.0,
                }
            ],
            "piece_area_calculation": {
                "rows": [
                    {"piece": "侧片（2片）", "size_text": "22×10×2", "qty_text": "1组"},
                ]
            },
        }
        enrich_quote_material_detail_display(quote)
        fabric = quote["detail_rows"][0]
        pp = str(fabric.get("piece_part", ""))
        self.assertNotIn("1组", pp)
        self.assertNotIn("组", pp)
        self.assertIn("侧片（2片）", pp)
        self.assertNotIn("22×10", pp)


if __name__ == "__main__":
    unittest.main()
