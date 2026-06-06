"""报价闸门：风险分级（低 / 中 / 高）。"""
from __future__ import annotations

import os
import unittest
import unittest.mock

from quote_engine import calculate_quote
from quote_validation_gate import apply_pricing_gate


def _gate(payload_items: list[dict], *, manual_confirmed: bool = False) -> dict:
    r = calculate_quote({"items": payload_items})
    apply_pricing_gate(r, {"items": payload_items}, manual_confirmed=manual_confirmed)
    return r


class QuoteRiskTierGateTest(unittest.TestCase):
    def test_high_unit_conflict_requires_confirm(self) -> None:
        r = calculate_quote(
            {
                "items": [
                    {
                        "name": "外布",
                        "spec": "-",
                        "usage": "1.2㎡",
                        "unit_price": "18元/码",
                        "amount": 1.0,
                    },
                ],
            },
        )
        apply_pricing_gate(r, {}, manual_confirmed=False)
        pg = r.get("pricing_gate") or {}
        self.assertEqual(pg.get("risk_level"), "HIGH")
        self.assertTrue(pg.get("confirm_required"))
        self.assertFalse(pg.get("final_price_allowed"))
        self.assertEqual(pg.get("quote_gate_status"), "NEED_CONFIRM")
        self.assertIn("unit_usage_price_conflict", pg.get("high_risk_codes") or [])
        self.assertIsNone(pg.get("confirmed_by"))

    def test_high_manual_confirm_sets_confirmed_by(self) -> None:
        r = calculate_quote(
            {
                "items": [
                    {
                        "name": "外布",
                        "usage": "1.2㎡",
                        "unit_price": "18元/码",
                        "amount": 1.0,
                    },
                ],
            },
        )
        apply_pricing_gate(r, {}, manual_confirmed=False)
        self.assertFalse(r["pricing_gate"]["final_price_allowed"])
        apply_pricing_gate(
            r,
            {},
            manual_confirmed=True,
            confirmed_by="session:user_confirm",
        )
        pg = r["pricing_gate"]
        self.assertTrue(pg["final_price_allowed"])
        self.assertFalse(pg["confirm_required"])
        self.assertEqual(pg["risk_level"], "HIGH")
        self.assertEqual(pg["confirmed_by"], "session:user_confirm")
        aud = r.get("pricing_audit") or {}
        self.assertEqual(aud.get("confirmed_by"), "session:user_confirm")

    def test_medium_ai_confidence_auto_final(self) -> None:
        r = calculate_quote(
            {
                "items": [
                    {
                        "name": "塑料插扣",
                        "spec": "-",
                        "usage": "2个",
                        "unit_price": "0.5元/个",
                        "amount": 1.0,
                        "usage_ai": True,
                        "ai_confidence": 0.70,
                        "calc_note": "按套件惯例用量",
                    },
                ],
            },
        )
        apply_pricing_gate(r, {}, manual_confirmed=False)
        pg = r.get("pricing_gate") or {}
        self.assertEqual(pg.get("risk_level"), "MEDIUM")
        self.assertTrue(pg.get("final_price_allowed"))
        self.assertFalse(pg.get("confirm_required"))
        self.assertEqual(pg.get("confirmed_by"), "system:auto_medium_risk")
        self.assertIsInstance(pg.get("ai_filled_fields"), list)
        self.assertGreater(len(pg["ai_filled_fields"]), 0)
        self.assertIsInstance(r.get("estimated_pricing"), dict)

    def test_env_bypass_unlocks_without_confirm_and_clears_data_notice(self) -> None:
        r = calculate_quote(
            {
                "items": [
                    {
                        "name": "外布",
                        "spec": "-",
                        "usage": "1.2㎡",
                        "unit_price": "18元/码",
                        "amount": 1.0,
                    },
                ],
            },
        )
        r["data_notice"] = "规格缺失提醒（测试）"
        with unittest.mock.patch.dict(os.environ, {"QUOTE_DISABLE_PRICING_GATE": "1"}):
            apply_pricing_gate(r, {}, manual_confirmed=False)
        pg = r.get("pricing_gate") or {}
        self.assertEqual(pg.get("risk_level"), "HIGH")
        self.assertFalse(pg.get("confirm_required"))
        self.assertTrue(pg.get("final_price_allowed"))
        self.assertTrue(pg.get("confirmation_bypassed"))
        self.assertEqual(pg.get("quote_gate_status"), "OK")
        self.assertEqual(pg.get("hint_cn"), "")
        self.assertFalse("estimated_pricing" in r)
        self.assertEqual(str(r.get("data_notice") or ""), "")
        audit = r.get("pricing_audit") or {}
        self.assertFalse(audit.get("confirm_required"))
        self.assertEqual(audit.get("confirmed_by"), "env:QUOTE_DISABLE_PRICING_GATE")

    def test_low_clean_row(self) -> None:
        r = calculate_quote(
            {
                "items": [
                    {
                        "name": "面料",
                        "spec": "-",
                        "usage": "1码²",
                        "unit_price": "10元/码²",
                        "amount": 10.0,
                        "calc_note": "表内用量×单价",
                    },
                ],
            },
        )
        apply_pricing_gate(r, {}, manual_confirmed=False)
        pg = r.get("pricing_gate") or {}
        self.assertEqual(pg.get("risk_level"), "LOW")
        self.assertTrue(pg.get("final_price_allowed"))
        self.assertEqual(pg.get("confirmed_by"), "system:auto_low_risk")
        self.assertNotIn("estimated_pricing", r)


class QuoteUnitDimensionGateTest(unittest.TestCase):
    """原始单位口径冲突：按维度判 HIGH，同维度可换算的不误拦。"""

    def test_sqm_usage_yard_price_is_high(self) -> None:
        r = _gate([{"name": "外布", "usage": "1.2㎡", "unit_price": "18元/码", "amount": 1.0}])
        pg = r["pricing_gate"]
        row = r["detail_rows"][0]
        self.assertEqual(pg["risk_level"], "HIGH")
        self.assertFalse(pg["final_price_allowed"])
        self.assertIn("unit_usage_price_conflict", pg["high_risk_codes"])
        self.assertTrue(row.get("unit_converted"))
        self.assertEqual(row.get("raw_usage"), "1.2㎡")
        self.assertEqual(row.get("raw_unit_price"), "18元/码")
        self.assertEqual(row.get("raw_quantity_unit"), "㎡")
        self.assertEqual(row.get("raw_price_unit"), "码")
        self.assertEqual(row.get("converted_price_unit"), "㎡")
        self.assertIn("原始用量单位与单价单位口径不一致", row.get("validation_detail") or "")

    def test_sqm_usage_sqm_price_is_low(self) -> None:
        r = _gate([{"name": "外布", "usage": "1.2㎡", "unit_price": "18元/㎡", "amount": 21.6}])
        pg = r["pricing_gate"]
        row = r["detail_rows"][0]
        self.assertEqual(pg["risk_level"], "LOW")
        self.assertTrue(pg["final_price_allowed"])
        self.assertNotIn("unit_usage_price_conflict", pg.get("high_risk_codes") or [])
        self.assertEqual(row.get("raw_quantity_unit"), "㎡")
        self.assertEqual(row.get("raw_price_unit"), "㎡")

    def test_yard_usage_yard_price_is_low(self) -> None:
        r = _gate([{"name": "织带", "usage": "2码", "unit_price": "5元/码", "amount": 10.0}])
        pg = r["pricing_gate"]
        self.assertEqual(pg["risk_level"], "LOW")
        self.assertTrue(pg["final_price_allowed"])
        self.assertNotIn("unit_usage_price_conflict", pg.get("high_risk_codes") or [])

    def test_meter_usage_meter_price_is_low(self) -> None:
        r = _gate([{"name": "织带", "usage": "2米", "unit_price": "3元/米", "amount": 6.0}])
        pg = r["pricing_gate"]
        self.assertEqual(pg["risk_level"], "LOW")
        self.assertTrue(pg["final_price_allowed"])

    def test_piece_usage_piece_price_is_low(self) -> None:
        r = _gate([{"name": "插扣", "usage": "2个", "unit_price": "0.5元/个", "amount": 1.0}])
        pg = r["pricing_gate"]
        self.assertEqual(pg["risk_level"], "LOW")
        self.assertTrue(pg["final_price_allowed"])

    def test_meter_usage_piece_price_is_high(self) -> None:
        r = _gate([{"name": "织带", "usage": "2米", "unit_price": "0.5元/个", "amount": 1.0}])
        pg = r["pricing_gate"]
        self.assertEqual(pg["risk_level"], "HIGH")
        self.assertFalse(pg["final_price_allowed"])
        self.assertIn("unit_usage_price_conflict", pg["high_risk_codes"])

    def test_piece_usage_linear_price_is_high(self) -> None:
        r = _gate([{"name": "辅料", "usage": "2个", "unit_price": "3元/码", "amount": 6.0}])
        pg = r["pricing_gate"]
        self.assertEqual(pg["risk_level"], "HIGH")
        self.assertFalse(pg["final_price_allowed"])
        self.assertIn("unit_usage_price_conflict", pg["high_risk_codes"])

    def test_auto_converted_cross_dimension_still_high(self) -> None:
        r = calculate_quote(
            {
                "items": [
                    {
                        "name": "外布",
                        "usage": "1.2㎡",
                        "unit_price": "18元/码",
                        "amount": 1.0,
                    },
                ],
            },
        )
        row = r["detail_rows"][0]
        self.assertTrue(row.get("unit_converted"))
        self.assertIn("单位换算", row.get("calc_note") or "")
        apply_pricing_gate(r, {}, manual_confirmed=False)
        pg = r["pricing_gate"]
        self.assertEqual(pg["risk_level"], "HIGH")
        self.assertFalse(pg["final_price_allowed"])
        self.assertIn("unit_usage_price_conflict", pg["high_risk_codes"])


if __name__ == "__main__":
    unittest.main()
