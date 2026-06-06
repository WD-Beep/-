"""local_quote_patch 模块：基于 active_quote 的局部试算。"""
from __future__ import annotations

import copy
import unittest

from local_quote_patch import apply_local_patch, parse_local_patch, run_local_quote_trial
from quote_engine import calculate_quote


class LocalQuotePatchTest(unittest.TestCase):
    def _payload_with_packaging(self) -> dict:
        return {
            "items": [
                {"name": "主料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0},
                {"name": "外纸箱", "spec": "-", "usage": "1个", "unit_price": "8元/个", "amount": 8.0},
            ],
            "quantities": [300],
            "processing_fee": 15.0,
            "system_overhead": 4.0,
            "gross_margin_rate": 0.30,
        }

    def test_run_local_packaging_trial(self) -> None:
        payload = self._payload_with_packaging()
        base = calculate_quote(payload)
        out = run_local_quote_trial(
            sid="s1",
            user_message="箱子换5元一个那么成本价是多少",
            session_context={
                "currentQuoteId": "q1",
                "active_quote": {
                    "quote_id": "q1",
                    "payload_snapshot": payload,
                    "last_quote_result": base,
                },
            },
        )
        self.assertTrue(out.get("quote_ready"))
        qp = out.get("quote_patch") or {}
        self.assertEqual(qp.get("patch_type"), "packaging_unit_price")
        self.assertAlmostEqual(float(qp.get("old_amount") or 0), 8.0, places=2)
        self.assertAlmostEqual(float(qp.get("new_amount") or 0), 5.0, places=2)

    def test_parse_material_yi_ma_unit(self) -> None:
        u = parse_local_patch("600D改12元一码")
        pp = u.get("price_patch") or {}
        self.assertEqual(pp.get("unit"), "元/码")

    def test_apply_local_patch_material_not_found(self) -> None:
        payload = {
            "items": [{"name": "主料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0}],
            "quantities": [500],
        }
        u = parse_local_patch("600D改12元/码")
        patched, meta, err = apply_local_patch(payload, calculate_quote(payload), u, "600D改12元/码")
        self.assertIsNone(patched)
        self.assertIn("600D", err)


if __name__ == "__main__":
    unittest.main()
