"""异常自动检测、记录、候选规则与自动修复。"""
from __future__ import annotations

import re
import sqlite3
import unittest
import uuid

import quote_anomaly_learning as qal
import quote_correction_learning as qcl


def _m2(usage: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*㎡", usage)
    assert m
    return float(m.group(1))


class QuoteAnomalyLearningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._conn = sqlite3.connect(":memory:", check_same_thread=False)
        cls._conn.row_factory = sqlite3.Row
        qcl.set_test_connection(cls._conn)
        qal.ensure_anomaly_tables(cls._conn)
        qcl._seed_builtin_rules(cls._conn)
        qal._seed_anomaly_builtin_rules(cls._conn)
        cls._conn.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        qcl.set_test_connection(None)
        cls._conn.close()

    def test_detect_fabric_lining_gap(self) -> None:
        quote = {
            "product_name": "篮球包",
            "product_size": {"LCM": 32, "WCM": 19, "HCM": 45},
            "structure_text": "篮球包",
            "detail_rows": [
                {
                    "name": "600D 牛津布",
                    "piece_part": "前片；后片；底片；侧片（2片）；拉链弧形盖",
                    "usage": "1.13㎡",
                    "calc_note": "主料按包身外包络",
                },
                {
                    "name": "210D涤纶",
                    "piece_part": "前片；后片；底片；侧片（2片）；拉链弧形盖",
                    "usage": "0.25㎡",
                    "calc_note": "里布按包身外包络×里布占比0.22",
                },
            ],
        }
        found = qal.detect_anomalies_in_quote(quote)
        types = {a.anomaly_type for a in found}
        self.assertIn("fabric_lining_usage_gap", types)
        self.assertIn("lining_ratio_in_calc_note", types)
        self.assertIn("fixed_low_lining_m2", types)

    def test_auto_record_and_fix_lining(self) -> None:
        uid = f"uid-{uuid.uuid4().hex[:8]}"
        quote = {
            "quote_uid": uid,
            "product_name": "篮球包",
            "product_size": {"LCM": 32, "WCM": 19, "HCM": 45},
            "structure_text": "篮球包",
            "items": [
                {
                    "name": "600D 牛津布",
                    "piece_part": "前片；后片；底片；侧片（2片）；拉链弧形盖",
                    "usage": "1.13㎡",
                    "usage_ai": True,
                    "unit_price": "16元/㎡",
                },
                {
                    "name": "210D涤纶",
                    "piece_part": "前片；后片；底片；侧片（2片）；拉链弧形盖",
                    "usage": "0.25㎡",
                    "unit_price": "12元/㎡",
                    "usage_ai": True,
                    "calc_note": "里布占比0.22",
                },
            ],
        }
        res = qal.scan_and_learn_from_quote(quote, quote_uid=uid, apply_auto_fix=True)
        self.assertTrue(res.detected)
        self.assertTrue(res.recorded_ids)
        lining = quote["items"][1]
        self.assertGreater(_m2(str(lining["usage"])), 0.45)
        self.assertNotAlmostEqual(_m2(str(lining["usage"])), 0.25, delta=0.05)
        main_m2 = _m2(str(quote["items"][0]["usage"]))
        lin_m2 = _m2(str(lining["usage"]))
        self.assertLessEqual(abs(main_m2 - lin_m2) / max(main_m2, 1e-6), 0.31)
        self.assertTrue(res.auto_fixes)
        self.assertIn("builtin-fabric-lining-shared-area", {a.rule_id for a in res.auto_fixes})
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM quote_anomaly_history WHERE quote_uid = ?", (uid,)
        ).fetchone()
        self.assertGreater(int(row["c"]), 0)

    def test_admin_usage_not_auto_fixed(self) -> None:
        quote = {
            "product_size": {"LCM": 32, "WCM": 19, "HCM": 45},
            "items": [
                {"name": "600D 牛津布", "usage": "1.13㎡", "piece_part": "前片；后片"},
                {
                    "name": "210D涤纶",
                    "usage": "0.25㎡",
                    "piece_part": "前片；后片",
                    "admin_corrected_usage": "0.30㎡",
                },
            ],
        }
        qal.apply_anomaly_auto_fixes(quote)
        self.assertEqual(quote["items"][1]["usage"], "0.25㎡")
        self.assertEqual(quote["items"][1].get("admin_corrected_usage"), "0.30㎡")

    def test_promote_after_two_anomalies(self) -> None:
        an = qal.DetectedAnomaly(
            anomaly_type="fabric_lining_usage_gap",
            material_name="210D涤纶",
            field_name="usage",
            old_value="0.25㎡",
            expected_value="≈1.13㎡",
            reason="同裁片主料里布差异过大",
            confidence=0.75,
        )
        sig = qal._anomaly_signature(an.anomaly_type, an.field_name, an.reason)
        for i in range(2):
            qal.record_anomaly(
                quote_uid=f"u-{i}",
                anomaly=an,
                product_name="包",
            )
        rid = qal.try_promote_candidate_rules(sig, an)
        self.assertTrue(rid)
        rule = self._conn.execute(
            "SELECT rule_status, enabled FROM quote_correction_rules WHERE rule_id = ?",
            (rid,),
        ).fetchone()
        self.assertIsNotNone(rule)

    def test_pack_internal_label_detected(self) -> None:
        found = qal.detect_anomalies_in_quote(
            {"product_name": "包", "pack": "系统估算 / 1个", "detail_rows": []}
        )
        self.assertTrue(any(a.anomaly_type == "customer_pack_internal_label" for a in found))

    def test_scan_attaches_observability(self) -> None:
        quote = {
            "product_name": "包",
            "items": [
                {"name": "600D牛津布", "usage": "1㎡", "piece_part": "前片"},
                {"name": "里布", "usage": "0.2㎡", "piece_part": "前片"},
            ],
            "product_size": {"LCM": 20, "WCM": 10, "HCM": 15},
        }
        qal.scan_and_learn_from_quote(quote, quote_uid="", record_history=False, apply_auto_fix=False)
        scan = quote.get("anomaly_scan") or {}
        self.assertIn("detected_count", scan)


if __name__ == "__main__":
    unittest.main()
