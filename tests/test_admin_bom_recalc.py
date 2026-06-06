"""admin BOM 编辑重算校验与 payload 组装。"""
from __future__ import annotations

import unittest

from admin_bom_recalc import (
    build_calc_payload_from_saved_quote,
    is_count_based_unit,
    parse_bom_measure_value,
    validate_bom_edit_body,
    _default_count_usage,
    _normalize_items,
    _parse_quantities_from_text,
    _validate_bom_measure_text,
)
from quote_engine import calculate_quote


class AdminBomRecalcTest(unittest.TestCase):
    def test_validate_requires_product_name_and_items(self) -> None:
        errs, fields = validate_bom_edit_body({"product": {}, "items": []})
        self.assertTrue(errs)
        self.assertIn("product.product_name", fields)

    def test_validate_rejects_empty_material_name(self) -> None:
        _, fields = validate_bom_edit_body(
            {
                "product": {"product_name": "测试包"},
                "items": [{"name": "", "unit_price": "6", "usage": "1"}],
            }
        )
        self.assertIn("items.0.name", fields)

    def test_validate_rejects_invalid_unit_price_digits(self) -> None:
        _, fields = validate_bom_edit_body(
            {
                "product": {"product_name": "测试包"},
                "items": [{"name": "尼龙布", "unit_price": "abc", "usage": "1"}],
            }
        )
        self.assertIn("items.0.unit_price", fields)

    def test_validate_rejects_loose_invalid_unit_price(self) -> None:
        for bad in ("1abc", "abc9", "2..3", "--1", "1abc2"):
            _, fields = validate_bom_edit_body(
                {
                    "product": {"product_name": "测试包"},
                    "items": [{"name": "尼龙布", "unit_price": bad, "usage": "1"}],
                }
            )
            self.assertIn("items.0.unit_price", fields, msg=bad)

    def test_validate_rejects_loose_invalid_usage(self) -> None:
        for bad in ("abc", "abc1", "1abc2", "2..3", "--1", "1abc"):
            _, fields = validate_bom_edit_body(
                {
                    "product": {"product_name": "测试包"},
                    "items": [{"name": "尼龙布", "unit_price": "5元/个", "usage": bad}],
                }
            )
            self.assertIn("items.0.usage", fields, msg=bad)

    def test_validate_accepts_number_with_unit_text(self) -> None:
        for up, usage in (
            ("5元/个", "1"),
            ("10元/㎡", "0.5㎡"),
            ("7.5", "2.5码"),
            ("3.2", "0.12 m"),
        ):
            errs, fields = validate_bom_edit_body(
                {
                    "product": {"product_name": "测试包"},
                    "items": [{"name": "尼龙布", "unit_price": up, "usage": usage}],
                }
            )
            self.assertFalse(errs, msg=(up, usage, errs))
            self.assertNotIn("items.0.unit_price", fields, msg=up)
            self.assertNotIn("items.0.usage", fields, msg=usage)

    def test_parse_bom_measure_value(self) -> None:
        self.assertAlmostEqual(parse_bom_measure_value("5元/个"), 5.0)
        self.assertAlmostEqual(parse_bom_measure_value("0.12 m"), 0.12)
        self.assertIsNone(parse_bom_measure_value("1abc"))
        self.assertIsNotNone(_validate_bom_measure_text("2..3", allow_empty=False))

    def test_validate_requires_at_least_one_item(self) -> None:
        errs, _ = validate_bom_edit_body(
            {"product": {"product_name": "测试包"}, "items": [{"name": " ", "usage": "1", "unit_price": "6"}]}
        )
        self.assertTrue(errs)

    def test_parse_quantities_text(self) -> None:
        out = _parse_quantities_from_text("300个 / 500个 / 1000个", [100])
        self.assertEqual(out, [300, 500, 1000])

    def test_build_payload_preserves_fees(self) -> None:
        quote = {
            "product_name": "旧名",
            "mold_fee": 800,
            "processing_fee": 15,
            "tiers": [{"quantity": 500}],
            "settings": {"gross_margin_rate": 0.3},
        }
        items = _normalize_items(
            [{"name": "尼龙布", "spec": "-", "usage": "0.5㎡", "unit_price": "10元/㎡"}]
        )
        payload = build_calc_payload_from_saved_quote(
            quote,
            product={"product_name": "新名", "quantities_text": "500个", "margin_text": "35%"},
            items=items,
        )
        self.assertEqual(payload["product_name"], "新名")
        self.assertEqual(payload["mold_fee"], 800)
        self.assertEqual(payload["processing_fee"], 15)
        self.assertEqual(payload["quantities"], [500])
        self.assertAlmostEqual(payload["gross_margin_rate"], 0.35)

    def test_is_count_based_unit(self) -> None:
        self.assertTrue(is_count_based_unit("元/个", "0.3"))
        self.assertTrue(is_count_based_unit("", "0.3元/个"))
        self.assertTrue(is_count_based_unit("个", ""))
        self.assertTrue(is_count_based_unit("", "5元/套"))
        self.assertFalse(is_count_based_unit("元/码", "10元/码"))
        self.assertFalse(is_count_based_unit("", "10元/㎡"))

    def test_validate_allows_empty_usage_for_count_based_unit(self) -> None:
        for usage in ("", "-", "—"):
            errs, fields = validate_bom_edit_body(
                {
                    "product": {"product_name": "测试包"},
                    "items": [
                        {
                            "name": "普通拉头",
                            "unit": "元/个",
                            "unit_price": "0.3",
                            "usage": usage,
                        }
                    ],
                }
            )
            self.assertFalse(errs, msg=usage)
            self.assertNotIn("items.0.usage", fields, msg=usage)

    def test_validate_rejects_empty_usage_for_non_count_unit(self) -> None:
        _, fields = validate_bom_edit_body(
            {
                "product": {"product_name": "测试包"},
                "items": [{"name": "DCH外料", "unit_price": "10元/码", "usage": "-"}],
            }
        )
        self.assertIn("items.0.usage", fields)

    def test_validate_rejects_invalid_usage_even_for_count_unit(self) -> None:
        for bad in ("1abc", "2..3", "abc9"):
            _, fields = validate_bom_edit_body(
                {
                    "product": {"product_name": "测试包"},
                    "items": [{"name": "拉头", "unit_price": "0.3元/个", "usage": bad}],
                }
            )
            self.assertIn("items.0.usage", fields, msg=bad)

    def test_normalize_count_based_empty_usage_defaults_to_one(self) -> None:
        items = _normalize_items(
            [{"name": "普通拉头", "unit": "元/个", "unit_price": "0.3", "usage": "-"}]
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["usage"], "1个")
        self.assertEqual(_default_count_usage("元/个", "0.3"), "1个")

    def test_normalize_count_based_usage_used_in_calc_payload(self) -> None:
        quote = {"tiers": [{"quantity": 500}], "settings": {"gross_margin_rate": 0.35}}
        items = _normalize_items(
            [{"name": "普通拉头", "unit_price": "0.3元/个", "usage": "-"}]
        )
        payload = build_calc_payload_from_saved_quote(
            quote,
            product={"product_name": "测试包", "quantities_text": "500个"},
            items=items,
        )
        self.assertEqual(payload["items"][0]["usage"], "1个")
        result = calculate_quote(payload)
        self.assertTrue(result.get("quote_ready") or result.get("detail_rows"))


if __name__ == "__main__":
    unittest.main()
