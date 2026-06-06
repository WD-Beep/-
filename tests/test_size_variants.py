"""多尺寸识别与分别报价。"""
from __future__ import annotations

import copy
import unittest

from multi_size_quote import calculate_quote_with_size_variants
from quote_engine import calculate_quote
from size_variants import (
    enrich_payload_size_variants,
    extract_size_variants_from_payload,
    parse_size_variants_from_text,
)


class SizeVariantsParseTest(unittest.TestCase):
    def test_single_size_returns_empty_from_text_parser(self) -> None:
        self.assertEqual(parse_size_variants_from_text("10×10×22cm"), [])

    def test_slash_separated_sizes(self) -> None:
        parsed = parse_size_variants_from_text("10×10×22cm / 12×12×25cm / 15×15×30cm")
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["product_size"]["LCM"], 10.0)
        self.assertEqual(parsed[2]["product_size"]["HCM"], 30.0)

    def test_labeled_sizes(self) -> None:
        parsed = parse_size_variants_from_text("小号 10×10×22cm，中号 12×12×25cm，大号 15×15×30cm")
        self.assertEqual(len(parsed), 3)
        labels = [v["label"] for v in parsed]
        self.assertIn("小号", labels)
        self.assertIn("中号", labels)
        self.assertIn("大号", labels)

    def test_size_columns_in_section_b(self) -> None:
        payload = {
            "quote_params": {
                "B": {
                    "尺寸1": "10×10×22cm",
                    "尺寸2": "12×12×25cm",
                }
            }
        }
        variants = extract_size_variants_from_payload(payload)
        self.assertEqual(len(variants), 2)

    def test_single_size_compat_via_product_size_dict(self) -> None:
        payload = {
            "product_size": {"LCM": 32, "WCM": 19, "HCM": 45},
            "product_size_text": "32×19×45cm",
        }
        variants = extract_size_variants_from_payload(payload)
        self.assertEqual(len(variants), 1)
        self.assertFalse(payload.get("multi_size"))


class MultiSizeQuoteCalcTest(unittest.TestCase):
    def _base_payload(self) -> dict:
        return {
            "product_name": "多尺寸测试包",
            "structure_text_snapshot": "方形软包，主袋+拉链",
            "product_size_text": "10×10×22cm / 12×12×25cm",
            "quantities": [300, 500, 1000],
            "processing_fee": 5.0,
            "gross_margin_rate": 0.35,
            "include_fob": True,
            "items": [
                {
                    "name": "600D牛津布",
                    "spec": "-",
                    "usage": "-",
                    "unit_price": "12元/㎡",
                    "amount": 0.0,
                    "source": "kb",
                },
                {
                    "name": "5号尼龙拉链",
                    "spec": "-",
                    "usage": "-",
                    "unit_price": "2元/条",
                    "amount": 0.0,
                    "source": "kb",
                },
            ],
        }

    def test_multi_size_produces_different_material_totals(self) -> None:
        payload = self._base_payload()
        enrich_payload_size_variants(payload)
        self.assertTrue(payload.get("multi_size"))
        payload["_size_variant_items_template"] = copy.deepcopy(payload["items"])
        result = calculate_quote_with_size_variants(payload, calculate_quote)
        variants = result.get("size_variants") or []
        self.assertGreaterEqual(len(variants), 2)
        totals = [float(v["quote_result"].get("material_total") or 0) for v in variants]
        self.assertGreater(max(totals), 0)
        self.assertNotEqual(totals[0], totals[1])

    def test_multi_size_tiers_differ_between_variants(self) -> None:
        payload = self._base_payload()
        enrich_payload_size_variants(payload)
        payload["_size_variant_items_template"] = copy.deepcopy(payload["items"])
        result = calculate_quote_with_size_variants(payload, calculate_quote)
        v0 = result["size_variants"][0]["quote_result"]["tiers"][0]["exw_price_text"]
        v1 = result["size_variants"][1]["quote_result"]["tiers"][0]["exw_price_text"]
        self.assertNotEqual(v0, v1)

    def test_single_size_uses_original_calculate_path(self) -> None:
        payload = self._base_payload()
        payload["product_size_text"] = "10×10×22cm"
        payload["product_size"] = {"LCM": 10, "WCM": 10, "HCM": 22}
        enrich_payload_size_variants(payload)
        self.assertFalse(payload.get("multi_size"))
        result = calculate_quote_with_size_variants(payload, calculate_quote)
        self.assertNotIn("size_variants", result)
        self.assertTrue(result.get("tiers"))

    def test_piece_area_per_variant(self) -> None:
        payload = self._base_payload()
        enrich_payload_size_variants(payload)
        payload["_size_variant_items_template"] = copy.deepcopy(payload["items"])
        result = calculate_quote_with_size_variants(payload, calculate_quote)
        labels = [
            v["quote_result"].get("piece_area_calculation", {}).get("product_size_label", "")
            for v in result.get("size_variants") or []
        ]
        self.assertTrue(any("10×10×22" in x for x in labels))
        self.assertTrue(any("12×12×25" in x for x in labels))


if __name__ == "__main__":
    unittest.main()
