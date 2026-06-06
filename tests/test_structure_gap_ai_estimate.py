"""结构缺项：AI/规则估算用量单价后可继续报价。"""

from __future__ import annotations

import unittest

from kimi_client import finalize_structure_gap_rows, prepare_structure_rows_for_market_estimate
from material_row_validity import (
    row_has_ai_estimate_pricing,
    validate_structure_items_for_formal_quote,
)
from server import merge_structure_confirmation_user_items
from structure_gap_hints import apply_confirmed_structure_gaps, build_structure_gap_hints, gap_hint_to_bom_row


class StructureGapAiEstimateTest(unittest.TestCase):
    def test_gap_print_and_sewing_rows_get_ai_estimate(self) -> None:
        hints = build_structure_gap_hints(
            "配备丝印 logo，加强车缝",
            [{"name": "600D牛津", "role": "外料", "amount": 5.0}],
            demand_template=True,
        )
        uncovered = [h for h in hints if not h.get("bom_covered")]
        print_hint = next((h for h in uncovered if h.get("id") == "gap_print_heat"), None)
        sewing_hint = next((h for h in uncovered if h.get("id") == "gap_sewing"), None)
        self.assertIsNotNone(print_hint)
        self.assertIsNotNone(sewing_hint)
        assert print_hint is not None and sewing_hint is not None
        items = apply_confirmed_structure_gaps(
            [{"name": "外料", "amount": 5.0}],
            hints,
            [str(print_hint["id"]), str(sewing_hint["id"])],
        )
        estimated = finalize_structure_gap_rows(items)
        gap_rows = [r for r in estimated if r.get("from_structure_gap_hint")]
        self.assertEqual(len(gap_rows), 2)
        for row in gap_rows:
            self.assertTrue(row.get("unit_price_ai") or row.get("usage_ai"))
            self.assertFalse(row.get("exclude_from_cost"))
            self.assertTrue(row.get("pricing_review_required"))
            self.assertIn("AI估算", str(row.get("recognition_reason") or ""))

    def test_gap_hint_to_bom_row_estimated_via_prepare(self) -> None:
        row = gap_hint_to_bom_row(
            {
                "id": "gap_print_heat",
                "name": "丝印",
                "detected_text": "丝印",
                "suggested_category": "工艺/人工",
                "category_confidence": 0.82,
            }
        )
        out = prepare_structure_rows_for_market_estimate([row])[0]
        self.assertEqual(out.get("usage"), "1处")
        self.assertIn("元/处", str(out.get("unit_price") or ""))
        self.assertTrue(row_has_ai_estimate_pricing(out))

    def test_merge_structure_confirmation_preserves_ai_flags(self) -> None:
        base = [{"name": "外料", "usage": "5码", "unit_price": "14元/码²"}]
        patch = [
            {
                "index": 1,
                "name": "丝印",
                "usage": "1处",
                "unit_price": "4元/处",
                "from_structure_gap_hint": True,
                "structure_gap_hint_id": "gap_print_heat",
                "usage_ai": True,
                "unit_price_ai": True,
                "pricing_review_required": True,
                "recognition_reason": "AI估算用量/单价，待管理员复核",
                "source": "ai",
            }
        ]
        merged = merge_structure_confirmation_user_items(base, patch)
        gap = merged[1]
        self.assertTrue(gap.get("unit_price_ai"))
        self.assertTrue(gap.get("pricing_review_required"))
        self.assertEqual(gap.get("source"), "ai")

    def test_validate_allows_ai_estimated_gap_rows(self) -> None:
        rows = prepare_structure_rows_for_market_estimate(
            [
                {
                    "name": "丝印",
                    "usage": "-",
                    "unit_price": "-",
                    "from_structure_gap_hint": True,
                    "structure_gap_hint_id": "gap_print_heat",
                    "recognition_status": "candidate_review",
                },
                {
                    "name": "车缝",
                    "usage": "-",
                    "unit_price": "-",
                    "from_structure_gap_hint": True,
                    "structure_gap_hint_id": "gap_sewing",
                    "recognition_status": "candidate_review",
                },
            ]
        )
        ok, summary = validate_structure_items_for_formal_quote(rows, allow_estimate=True)
        self.assertTrue(ok)
        self.assertGreaterEqual(int(summary.get("ai_estimate_count") or 0), 2)


if __name__ == "__main__":
    unittest.main()
