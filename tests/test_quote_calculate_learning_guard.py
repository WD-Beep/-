"""calculate_quote / 学习规则：BOM 优先、动态令牌、异常待核。"""
from __future__ import annotations

import re
import sqlite3
import unittest
import uuid

import quote_anomaly_learning as qal
import quote_correction_learning as qcl
import quote_engine
from material_spec_usage_enricher import is_dynamic_rule_usage_token


def _m2(usage: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*㎡", usage)
    assert m, usage
    return float(m.group(1))


def _rel_gap(a: float, b: float) -> float:
    return abs(a - b) / max(max(a, b), 1e-6)


class QuoteCalculateLearningGuardTest(unittest.TestCase):
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

    def _basketball_payload(self, *, lining_usage: str, lining_ai: bool = False) -> dict:
        return {
            "quote_uid": f"uid-{uuid.uuid4().hex[:8]}",
            "product_name": "篮球包",
            "product_size": {"LCM": 32, "WCM": 19, "HCM": 45},
            "structure_text": "篮球包。成品32×19×45cm",
            "quantities": [300],
            "gross_margin_rate": 0.35,
            "items": [
                {
                    "name": "600D 牛津布",
                    "piece_part": "前片；后片；底片；侧片（2片）；拉链弧形盖",
                    "usage": "1.13㎡",
                    "unit_price": "16元/㎡",
                    "amount": 18.08,
                },
                {
                    "name": "210D涤纶",
                    "piece_part": "前片；后片；底片；侧片（2片）；拉链弧形盖",
                    "usage": lining_usage,
                    "unit_price": "12元/㎡",
                    "amount": 3.14,
                    "usage_ai": lining_ai,
                    "calc_note": "里布占比0.22" if lining_ai else "",
                },
            ],
        }

    def test_explicit_bom_with_raw_usage_not_auto_overwritten(self) -> None:
        payload = self._basketball_payload(lining_usage="0.25㎡", lining_ai=False)
        payload["items"][1]["bom_usage"] = "0.25㎡"
        payload["items"][1]["source"] = "bom"
        result = quote_engine.calculate_quote(payload)
        self.assertEqual(payload["items"][1]["usage"], "0.25㎡")

    def test_explicit_bom_lining_not_auto_overwritten(self) -> None:
        payload = self._basketball_payload(lining_usage="0.25㎡", lining_ai=False)
        result = quote_engine.calculate_quote(payload)
        lining = payload["items"][1]
        self.assertEqual(lining["usage"], "0.25㎡")
        self.assertEqual(lining.get("bom_usage"), "0.25㎡")
        self.assertTrue(lining.get("_anomaly_pending_review") or lining.get("_anomaly_flags"))
        scan = payload.get("anomaly_scan") or {}
        self.assertTrue(
            (scan.get("detected_count") or 0) > 0
            or len(scan.get("anomalies") or []) > 0
            or lining.get("_anomaly_pending_review")
        )
        for row in result.get("detail_rows") or []:
            self.assertFalse(is_dynamic_rule_usage_token(row.get("usage")))

    def test_admin_usage_not_overwritten_by_calculate_quote(self) -> None:
        payload = self._basketball_payload(lining_usage="0.25㎡", lining_ai=True)
        payload["items"][1]["admin_corrected_usage"] = "0.30㎡"
        result = quote_engine.calculate_quote(payload)
        lining = payload["items"][1]
        self.assertEqual(lining.get("admin_corrected_usage"), "0.30㎡")
        self.assertEqual(lining.get("usage"), "0.25㎡")
        self.assertNotEqual(lining.get("usage"), "__SHARED_BODY_M2__")
        dr = next(
            (r for r in (result.get("detail_rows") or []) if "210D" in str(r.get("name"))),
            None,
        )
        self.assertIsNotNone(dr)
        self.assertFalse(is_dynamic_rule_usage_token(dr.get("usage")))

    def test_no_product_size_no_dynamic_token_or_nan_amount(self) -> None:
        payload = {
            "product_name": "测试包",
            "quantities": [100],
            "gross_margin_rate": 0.35,
            "items": [
                {
                    "name": "210D涤纶",
                    "usage": "0.25㎡",
                    "usage_ai": True,
                    "unit_price": "12元/㎡",
                    "calc_note": "里布占比0.22",
                },
            ],
        }
        result = quote_engine.calculate_quote(payload)
        self.assertNotIn("__SHARED_BODY_M2__", str(payload["items"][0].get("usage")))
        amt = float(payload["items"][0].get("amount") or result["detail_rows"][0].get("amount") or 0)
        self.assertTrue(amt >= 0)

    def test_main_explicit_lining_ai_aligns_to_main_bom_not_piece_table(self) -> None:
        """主料明确 1.13㎡ + 里布 AI 0.25㎡：里布应对齐主料，不能落成 1.13/0.51。"""
        payload = self._basketball_payload(lining_usage="0.25㎡", lining_ai=True)
        quote_engine.calculate_quote(payload)
        main = payload["items"][0]
        lining = payload["items"][1]
        self.assertEqual(main["usage"], "1.13㎡")
        main_m2 = _m2(str(main["usage"]))
        lin_m2 = _m2(str(lining["usage"]))
        self.assertLessEqual(_rel_gap(main_m2, lin_m2), 0.30)
        self.assertNotAlmostEqual(lin_m2, 0.51, delta=0.06)
        self.assertAlmostEqual(lin_m2, main_m2, delta=0.02)
        fixes = payload.get("anomaly_auto_fixes") or []
        self.assertTrue(fixes)
        hit = next(h for h in fixes if "210D" in str(h.get("material_name") or ""))
        self.assertEqual(hit.get("old_inferred_value"), "0.25㎡")
        self.assertIn("1.13", str(hit.get("applied_value") or ""))

    def test_main_bom_vs_piece_area_gap_marks_main_pending(self) -> None:
        payload = self._basketball_payload(lining_usage="0.25㎡", lining_ai=True)
        quote_engine.calculate_quote(payload)
        main = payload["items"][0]
        types = {f.get("type") for f in (main.get("_anomaly_flags") or [])}
        scan_types = {
            a.get("anomaly_type") for a in (payload.get("anomaly_scan") or {}).get("anomalies") or []
        }
        self.assertTrue(
            "main_bom_vs_piece_area_gap" in types
            or "main_bom_vs_piece_area_gap" in scan_types
            or main.get("_anomaly_pending_review")
        )
        self.assertEqual(main["usage"], "1.13㎡")

    def test_both_ai_fabrics_align_to_piece_area_table(self) -> None:
        """主料/里布均为 AI 推断时，可共同按裁片面积表修复为接近值。"""
        payload = self._basketball_payload(lining_usage="0.25㎡", lining_ai=True)
        payload["items"][0]["usage_ai"] = True
        quote_engine.calculate_quote(payload)
        main_m2 = _m2(str(payload["items"][0]["usage"]))
        lin_m2 = _m2(str(payload["items"][1]["usage"]))
        self.assertLessEqual(_rel_gap(main_m2, lin_m2), 0.30)
        self.assertGreater(lin_m2, 0.40)
        self.assertLess(lin_m2, 0.60)
        self.assertGreater(main_m2, 0.40)
        self.assertLess(main_m2, 0.60)

    def test_ai_inferred_lining_auto_fixed_with_dimensions(self) -> None:
        """双 AI 场景：保留 rule 命中元数据。"""
        payload = self._basketball_payload(lining_usage="0.25㎡", lining_ai=True)
        payload["items"][0]["usage_ai"] = True
        quote_engine.calculate_quote(payload)
        fixes = payload.get("anomaly_auto_fixes") or []
        self.assertTrue(fixes)
        hit = fixes[0]
        self.assertIn(hit.get("rule_id"), ("builtin-fabric-lining-shared-area",))
        self.assertEqual(hit.get("old_inferred_value"), "0.25㎡")
        self.assertIn("㎡", str(hit.get("applied_value") or ""))
        self.assertGreater(float(hit.get("confidence") or 0), 0.8)
        self.assertTrue(str(hit.get("reason") or ""))

    def test_correction_rule_never_writes_shared_body_token(self) -> None:
        row = {
            "name": "210D涤纶",
            "usage": "1套",
            "unit_price": "12元/㎡",
            "usage_ai": True,
        }
        ctx = {"product_name": "包", "structure_text": ""}
        rules = [r for r in qcl.load_enabled_rules() if r.rule_id == "builtin-fabric-lining-shared-area"]
        self.assertTrue(rules)
        out, hits = qcl.apply_correction_rules_to_row(row, ctx, rules=qcl.load_enabled_rules())
        self.assertFalse(is_dynamic_rule_usage_token(out.get("usage")))
        usage_hits = [h for h in hits if h.field_name == "usage"]
        for h in usage_hits:
            self.assertNotEqual(h.applied_value, "__SHARED_BODY_M2__")


if __name__ == "__main__":
    unittest.main()
