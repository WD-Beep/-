"""修正学习规则审批边界：未审批不得影响正式报价。"""
from __future__ import annotations

import sqlite3
import unittest

import quote_correction_learning as qcl
import quote_engine


class QuoteCorrectionLearningGuardTest(unittest.TestCase):
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

    def test_calculate_quote_builtin_still_applies(self) -> None:
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

    def test_calculate_quote_unapproved_learned_rule_does_not_apply(self) -> None:
        for _ in range(2):
            qcl.record_correction(
                quote_uid="uid-calc-guard",
                material_name="测试织带B",
                field_name="usage",
                old_value="1套",
                new_value="4米",
                corrected_by="admin",
            )
        result = quote_engine.calculate_quote(
            {
                "product_name": "测试包",
                "structure_text": "",
                "items": [
                    {
                        "name": "测试织带B",
                        "spec": "-",
                        "usage": "1套",
                        "unit_price": "2元/米",
                        "amount": 2.0,
                        "usage_ai": True,
                    }
                ],
                "quantities": [300],
                "gross_margin_rate": 0.35,
            }
        )
        row = (result.get("detail_rows") or [{}])[0]
        self.assertEqual(row.get("usage"), "1套")
        rule = self._conn.execute(
            "SELECT rule_id, enabled, rule_status FROM quote_correction_rules WHERE rule_id LIKE 'learned-generic%'"
        ).fetchone()
        self.assertIsNotNone(rule)
        self.assertEqual(int(rule["enabled"]), 0)

    def test_approve_correction_rule_sets_audit_fields(self) -> None:
        for _ in range(2):
            qcl.record_correction(
                quote_uid="uid-audit",
                material_name="测试扣具C",
                field_name="usage",
                old_value="1套",
                new_value="5个",
                corrected_by="admin",
            )
        rule = self._conn.execute(
            "SELECT rule_id FROM quote_correction_rules WHERE rule_id LIKE 'learned-%' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert rule is not None
        out = qcl.approve_correction_rule(
            str(rule["rule_id"]),
            approved_by="boss_guard",
        )
        self.assertEqual(out.get("rule_source"), qcl.RULE_SOURCE_ADMIN_APPROVED)
        self.assertEqual(out.get("approved_by"), "boss_guard")
        self.assertTrue(out.get("approved_at"))


if __name__ == "__main__":
    unittest.main()
