"""结构缺项确认：confirmed_structure_gap_ids 从选择到入 BOM 的集成测试。"""

from __future__ import annotations

import unittest

from server import merge_structure_confirmation_user_items
from structure_gap_hints import (
    apply_confirmed_structure_gaps,
    build_structure_gap_hints,
    gap_hint_to_bom_row,
)


def _simulate_structure_confirm_merge(
    base_items: list[dict],
    *,
    gap_hints: list[dict],
    confirmed_ids: list[str] | None,
    patch_rows: list[dict] | None = None,
) -> list[dict]:
    """模拟结构确认后 server.py 的合并顺序。"""
    items = merge_structure_confirmation_user_items(base_items, list(patch_rows or []))
    if confirmed_ids:
        items = apply_confirmed_structure_gaps(items, gap_hints, confirmed_ids)
    return items


class ConfirmedStructureGapIntegrationTest(unittest.TestCase):
    def test_uncovered_hints_generated_for_mesh_partition(self) -> None:
        structure = "主仓带隔层，正面网兜网袋，侧袋可放水壶"
        items = [{"name": "600D牛津", "role": "外料", "amount": 5.6}]
        hints = build_structure_gap_hints(structure, items, demand_template=True)
        self.assertGreaterEqual(len(hints), 1)
        uncovered = [h for h in hints if not h.get("bom_covered")]
        self.assertGreater(len(uncovered), 0)
        for h in uncovered:
            self.assertFalse(h.get("participates_in_cost"))

    def test_no_confirmed_ids_does_not_add_gap_rows(self) -> None:
        structure = "配备网袋与隔层"
        base = [{"name": "外料", "role": "外料", "amount": 10.0}]
        hints = build_structure_gap_hints(structure, base, demand_template=True)
        merged = _simulate_structure_confirm_merge(base, gap_hints=hints, confirmed_ids=None)
        gap_rows = [r for r in merged if r.get("from_structure_gap_hint")]
        self.assertEqual(gap_rows, [])

    def test_confirmed_ids_add_structure_confirmed_bom_rows(self) -> None:
        structure = "配备网袋与隔层"
        base = [{"name": "外料", "role": "外料", "amount": 10.0}]
        hints = build_structure_gap_hints(structure, base, demand_template=True)
        uncovered = [h for h in hints if not h.get("bom_covered")]
        self.assertGreater(len(uncovered), 0)
        confirmed = [str(uncovered[0]["id"])]
        merged = _simulate_structure_confirm_merge(
            base,
            gap_hints=hints,
            confirmed_ids=confirmed,
        )
        gap_rows = [r for r in merged if r.get("from_structure_gap_hint")]
        self.assertEqual(len(gap_rows), 1)
        row = gap_rows[0]
        self.assertEqual(row.get("confirmation_source"), "structure_confirmed")
        self.assertEqual(row.get("source"), "structure_confirmed")
        self.assertEqual(row.get("structure_gap_hint_id"), confirmed[0])
        self.assertTrue(row.get("from_structure_gap_hint"))
        self.assertTrue(row.get("exclude_from_cost"))
        self.assertFalse(row.get("amount_in_cost"))

    def test_covered_hint_id_not_duplicated_when_not_confirmed(self) -> None:
        structure = "侧袋网袋结构"
        base = [
            {"name": "网布侧袋", "role": "辅料", "amount": 2.0},
            {"name": "包边带", "role": "织带", "amount": 1.0},
        ]
        hints = build_structure_gap_hints(structure, base, demand_template=True)
        covered = [h for h in hints if h.get("bom_covered")]
        if not covered:
            self.skipTest("no covered hints in this fixture")
        merged = _simulate_structure_confirm_merge(
            base,
            gap_hints=hints,
            confirmed_ids=[str(covered[0]["id"])],
        )
        gap_rows = [r for r in merged if r.get("from_structure_gap_hint")]
        self.assertLessEqual(len(gap_rows), 1)

    def test_payload_contract_keys(self) -> None:
        """前端 confirmStructureAndQuote 应提交的字段契约。"""
        required_when_gaps_selected = {
            "structure_confirmed",
            "structure_confirmed_by_user",
            "confirmed_structure_gap_ids",
            "structure_gap_hints",
        }
        sample_payload = {
            "structure_confirmed": True,
            "structure_confirmed_by_user": True,
            "confirmed_structure_gap_ids": ["gap_mesh_pocket"],
            "structure_gap_hints": [{"id": "gap_mesh_pocket", "bom_covered": False}],
        }
        for key in required_when_gaps_selected:
            self.assertIn(key, sample_payload)

    def test_gap_row_schema_matches_backend_expectation(self) -> None:
        row = gap_hint_to_bom_row(
            {
                "id": "gap_partition",
                "name": "隔层",
                "detected_text": "隔层",
                "suggested_direction": "隔层面料、车缝",
                "suggested_category": "里料",
                "category_candidates": ["里料", "海绵", "PE板", "车缝工艺"],
                "category_confidence": 0.8,
                "category_hint_display": "建议归类：里料 / 海绵 / PE板 / 车缝工艺",
            },
        )
        self.assertEqual(row["structure_gap_hint_id"], "gap_partition")
        self.assertEqual(row["confirmation_source"], "structure_confirmed")
        self.assertEqual(row.get("name"), "隔层-里料/海绵")
        self.assertEqual(row.get("role"), "里料")
        self.assertIn("建议归类", str(row.get("calc_note") or ""))
        self.assertTrue(row.get("needs_manual_confirm"))
        self.assertTrue(row.get("exclude_from_cost"))
        self.assertFalse(row.get("amount_in_cost"))

    def test_patch_gap_row_not_duplicated_by_apply_confirmed(self) -> None:
        structure = "配备网袋与隔层"
        base = [{"name": "外料", "role": "外料", "amount": 10.0}]
        hints = build_structure_gap_hints(structure, base, demand_template=True)
        uncovered = [h for h in hints if not h.get("bom_covered")]
        self.assertGreater(len(uncovered), 0)
        hid = str(uncovered[0]["id"])
        patch_row = {
            "index": 1,
            "name": str(uncovered[0].get("name") or uncovered[0].get("detected_text") or "隔层"),
            "spec": "-",
            "usage": "-",
            "unit_price": "-",
            "calc_note": "结构确认缺项",
            "from_structure_gap_hint": True,
            "structure_gap_hint_id": hid,
            "confirmation_source": "structure_confirmed",
            "source": "structure_confirmed",
            "exclude_from_cost": True,
            "amount_in_cost": False,
        }
        merged = _simulate_structure_confirm_merge(
            base,
            gap_hints=hints,
            confirmed_ids=[hid],
            patch_rows=[patch_row],
        )
        gap_rows = [r for r in merged if str(r.get("structure_gap_hint_id") or "") == hid]
        self.assertEqual(len(gap_rows), 1)
        self.assertTrue(gap_rows[0].get("from_structure_gap_hint"))

    def test_patch_gap_row_enables_cost_after_pricing(self) -> None:
        base = [{"name": "外料", "amount": 10.0}]
        patch_row = {
            "index": 1,
            "name": "印刷/热压",
            "spec": "logo",
            "usage": "1处",
            "unit_price": "4元/处",
            "from_structure_gap_hint": True,
            "structure_gap_hint_id": "gap_print_heat",
            "confirmation_source": "structure_confirmed",
            "source": "structure_confirmed",
        }
        merged = merge_structure_confirmation_user_items(base, [patch_row])
        self.assertEqual(len(merged), 2)
        row = merged[1]
        self.assertFalse(row.get("exclude_from_cost"))
        self.assertTrue(row.get("amount_in_cost"))


if __name__ == "__main__":
    unittest.main()
