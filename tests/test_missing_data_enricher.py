from __future__ import annotations

import unittest

from missing_data_enricher import enrich_missing_quote_data
from quote_engine import calculate_quote


class MissingDataEnricherTest(unittest.TestCase):
    def test_fills_amount_from_usage_and_unit_price(self) -> None:
        payload, report = enrich_missing_quote_data(
            {
                "items": [
                    {
                        "name": "拉链",
                        "usage": "30cm",
                        "unit_price": "3.5元/米",
                        "amount": 0,
                    }
                ]
            }
        )
        row = payload["items"][0]
        self.assertAlmostEqual(float(row["amount"]), 1.05, places=2)
        self.assertTrue(row["amount_ai"])
        self.assertEqual(report["filled_count"], 1)
        self.assertEqual(report["filled"][0]["field"], "amount")

    def test_reports_packaging_estimate_without_overriding_engine_ai_row(self) -> None:
        payload, report = enrich_missing_quote_data(
            {
                "product_size": {"length_cm": 16, "width_cm": 9, "height_cm": 19},
                "items": [
                    {
                        "name": "面料",
                        "usage": "1个",
                        "unit_price": "10元/个",
                        "amount": 10,
                    }
                ],
                "quantities": [1000],
            }
        )
        self.assertFalse(payload.get("packaging_addon_per_piece"))
        self.assertTrue(any(x["field"] == "packaging_addon_per_piece" for x in report["filled"]))
        quote = calculate_quote(payload)
        pkg = [x for x in quote["detail_rows"] if "包装费" in str(x.get("name"))]
        self.assertEqual(len(pkg), 1)
        self.assertEqual(pkg[0]["source"], "ai")
        # 16×19×9cm → 小件基础包装 0.80 元/个（与 quote_engine._estimate_packaging_addon 一致）
        self.assertAlmostEqual(float(pkg[0]["amount"]), 0.8, places=2)
        filled_pkg = [x for x in report["filled"] if x.get("field") == "packaging_addon_per_piece"]
        self.assertEqual(len(filled_pkg), 1)
        self.assertAlmostEqual(float(filled_pkg[0]["value"]), 0.8, places=2)

    def test_unresolved_price_is_reported_not_guessed(self) -> None:
        _, report = enrich_missing_quote_data(
            {"items": [{"name": "特殊五金", "usage": "1个", "unit_price": "-", "amount": 0}]}
        )
        self.assertEqual(report["filled_count"], 0)
        self.assertTrue(any(x["field"] == "unit_price" for x in report["unresolved"]))


if __name__ == "__main__":
    unittest.main()
