"""规格/用量补全逻辑。"""
from __future__ import annotations

import math
import unittest

from material_spec_usage_enricher import (
    TIER_ADMIN,
    TIER_CALC_NOTE,
    TIER_RAW,
    enrich_material_row,
    enrich_material_rows,
    is_missing_spec_usage_value,
    resolve_spec_from_row,
    resolve_usage_from_row,
    row_has_valid_amount,
    usage_for_amount_recalc,
)
from quote_engine import calculate_quote, parse_items


class MaterialSpecUsageEnricherTests(unittest.TestCase):
    def test_missing_detector(self) -> None:
        for v in ("", "-", "—", "null", "undefined", "NaN"):
            self.assertTrue(is_missing_spec_usage_value(v), v)

    def test_raw_spec_usage_priority(self) -> None:
        row = {
            "name": "外料",
            "spec": "-",
            "usage": "-",
            "raw_spec": "600D牛津",
            "raw_usage": "1.1码",
        }
        self.assertEqual(resolve_spec_from_row(row).value, "600D牛津")
        self.assertEqual(resolve_spec_from_row(row).tier, TIER_RAW)
        self.assertEqual(resolve_usage_from_row(row).value, "1.1码")
        self.assertEqual(resolve_usage_from_row(row).tier, TIER_RAW)
        enrich_material_row(row)
        self.assertEqual(row["spec"], "600D牛津")
        self.assertEqual(row["usage"], "1.1码")
        self.assertNotIn("_usage_display_inferred", row)

    def test_admin_corrected_priority(self) -> None:
        row = {
            "name": "织带",
            "spec": "旧规格",
            "usage": "0.2米",
            "raw_spec": "raw规格",
            "admin_corrected_spec": "管理员规格A",
            "admin_corrected_usage": "0.8米",
        }
        self.assertEqual(resolve_spec_from_row(row).tier, TIER_ADMIN)
        self.assertEqual(resolve_spec_from_row(row).value, "管理员规格A")
        self.assertEqual(resolve_usage_from_row(row).value, "0.8米")
        enrich_material_row(row)
        self.assertEqual(row["spec"], "管理员规格A")
        self.assertEqual(row["usage"], "0.8米")

    def test_preserves_existing_primary(self) -> None:
        row = {"name": "外料A", "spec": "600D牛津", "usage": "1.2码", "unit_price": "14元/码²"}
        enrich_material_row(row)
        self.assertEqual(row["spec"], "600D牛津")
        self.assertEqual(row["usage"], "1.2码")

    def test_calc_note_extraction(self) -> None:
        row = {
            "name": "织带",
            "spec": "",
            "usage": "",
            "calc_note": "规格：25mm黑色织带；用量：0.6米",
            "unit_price": "1.2元/米",
        }
        self.assertEqual(resolve_spec_from_row(row).tier, TIER_CALC_NOTE)
        self.assertIn("25", resolve_spec_from_row(row).value)
        enrich_material_row(row)
        self.assertIn("25", row["spec"])
        self.assertIn("0.6", row["usage"])

    def test_600d_oxford_fabric_spec(self) -> None:
        row = {"name": "600D牛津布", "spec": "-", "usage": "-", "unit_price": "14元/码²"}
        enrich_material_row(row)
        self.assertIn("600", row["spec"])
        self.assertIn("牛津", row["spec"])
        self.assertNotEqual(row["spec"], "常规辅料规格")
        self.assertNotEqual(row["spec"], "按表内面料规格")

    def test_nylon_zipper_spec_not_slash(self) -> None:
        row = {
            "name": "#5尼龙拉链",
            "spec": "/",
            "usage": "1.12米",
            "unit_price": "3元/米",
            "amount": 3.36,
        }
        enrich_material_row(row)
        self.assertNotIn("/", row["spec"])
        self.assertIn("拉链", row["spec"])
        self.assertEqual(row["usage"], "1.12米")

    def test_small_parts_display(self) -> None:
        cases = [
            ("普通拉头", "拉头", "个"),
            ("D扣扣具", "扣", "个"),
            ("金属挂钩", "挂钩", "个"),
            ("织标", "织标", "个"),
            ("PE包装袋", "包装", "包装袋"),
        ]
        for name, spec_needle, unit_needle in cases:
            row = {"name": name, "spec": "-", "usage": "-", "unit_price": "1元/个"}
            enrich_material_row(row)
            self.assertFalse(is_missing_spec_usage_value(row["spec"]), name)
            self.assertFalse(is_missing_spec_usage_value(row["usage"]), name)
            self.assertIn(spec_needle, row["spec"], name)
            self.assertIn(unit_needle, row["usage"], name)

    def test_inferred_usage_not_used_for_recalc_when_amount_present(self) -> None:
        from unittest.mock import patch

        row = {
            "name": "普通拉头",
            "spec": "-",
            "usage": "-",
            "unit_price": "0.3元/个",
            "amount": 5.0,
        }
        with patch(
            "quote_correction_learning.apply_correction_rules_to_row",
            return_value=([], 0),
        ):
            enrich_material_row(row)
        self.assertTrue(row.get("_usage_display_inferred"))
        self.assertEqual(usage_for_amount_recalc(row), "-")
        items = parse_items([row])
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0].amount, 5.0, places=2)

    def test_trusted_usage_can_recalc_when_no_amount(self) -> None:
        row = {
            "name": "织带",
            "spec": "25mm",
            "raw_usage": "0.5米",
            "unit_price": "2元/米",
            "amount": 0,
        }
        self.assertEqual(usage_for_amount_recalc(row), "0.5米")
        items = parse_items([row])
        self.assertAlmostEqual(items[0].amount, 1.0, places=2)

    def test_calculate_quote_material_total_finite(self) -> None:
        rows = enrich_material_rows(
            [
                {
                    "name": "拉头",
                    "spec": "-",
                    "usage": "-",
                    "unit_price": "0.3元/个",
                    "amount": 3.0,
                },
                {
                    "name": "600D牛津布",
                    "spec": "-",
                    "usage": "-",
                    "unit_price": "10元/码",
                    "amount": 8.0,
                },
            ]
        )
        result = calculate_quote(
            {
                "items": rows,
                "quantities": [300],
                "gross_margin_rate": 0.35,
            }
        )
        mt = float(result.get("material_total") or 0)
        self.assertTrue(math.isfinite(mt))
        self.assertAlmostEqual(mt, 11.0, places=2)
        for dr in result.get("detail_rows") or []:
            self.assertFalse(is_missing_spec_usage_value(dr.get("spec")))
            self.assertFalse(is_missing_spec_usage_value(dr.get("usage")))

    def test_display_enrich_does_not_set_spec_ai(self) -> None:
        row = {"name": "面料", "spec": "-", "usage": "1码²", "unit_price": "10元/码²", "amount": 10.0}
        enrich_material_row(row)
        self.assertFalse(row.get("spec_ai"))
        self.assertFalse(row.get("usage_ai"))

    def test_dimension_usage_keeps_spec_dash_on_display(self) -> None:
        row = {"name": "面料", "spec": "140*90CM", "usage": "-", "amount": 17.0}
        enrich_material_row(row)
        self.assertEqual(row["spec"], "-")
        self.assertIn("140", row["usage"])

    def test_batch_enrich_no_dash(self) -> None:
        rows = enrich_material_rows(
            [
                {"name": "扣具", "spec": "-", "usage": ""},
                {"name": "挂钩", "spec": "", "usage": "-"},
            ]
        )
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertFalse(is_missing_spec_usage_value(r.get("spec")))
            self.assertFalse(is_missing_spec_usage_value(r.get("usage")))

    def test_row_has_valid_amount(self) -> None:
        self.assertTrue(row_has_valid_amount({"amount": 1.5}))
        self.assertFalse(row_has_valid_amount({"amount": 0}))
        self.assertFalse(row_has_valid_amount({"amount": float("nan")}))


if __name__ == "__main__":
    unittest.main()
