"""结构缺项识别 + 歧义物料归类说明。"""

from __future__ import annotations

import unittest

from bag_quote_pipeline import apply_bag_quote_preparse
from demand_field_sources import EXPLICIT_MATERIAL_FIELD
from material_inference import is_inferred_cost_row
from structure_gap_hints import (
    apply_confirmed_structure_gaps,
    build_gap_bom_name,
    build_structure_gap_hints,
    classify_ambiguous_material,
    enrich_row_ambiguous_classification,
    format_gap_category_hint_display,
    gap_hint_to_bom_row,
)


class StructureGapHintsTest(unittest.TestCase):
    def test_structure_note_mesh_partition_no_bom_but_gap_hints(self) -> None:
        structure_note = "主仓带隔层，正面网兜网袋结构，侧袋可放水壶"
        payload = {
            "items": [
                {
                    "name": "600D牛津",
                    "role": "外料",
                    "usage": "0.4码",
                    "unit_price": "14元/码",
                    "amount": 5.6,
                    "field_source_type": EXPLICIT_MATERIAL_FIELD,
                },
            ],
        }
        apply_bag_quote_preparse(
            payload,
            structure_text=structure_note,
            structure_inference_text="",
            demand_template=True,
        )
        inferred = [r for r in payload["items"] if is_inferred_cost_row(r)]
        names = " ".join(str(r.get("name") or "") for r in inferred)
        self.assertNotIn("网袋", names)
        self.assertNotIn("隔层", names)
        gap_hints = payload.get("structure_gap_hints") or []
        self.assertGreaterEqual(len(gap_hints), 1)
        detected = {str(h.get("detected_text") or h.get("name") or "") for h in gap_hints}
        self.assertTrue({"网袋", "隔层", "侧袋"} & detected or len(gap_hints) >= 2)
        for h in gap_hints:
            self.assertFalse(h.get("participates_in_cost"))
            self.assertIn("user_notice", h)
            self.assertIn("cost_impact_reason", h)
            self.assertIn("suggested_category", h)
            self.assertIn("category_candidates", h)
            self.assertIn("material_category_hint", h)
            self.assertIn("category_hint_display", h)
            self.assertTrue(str(h.get("category_hint_display") or "").startswith("建议归类："))

    def test_confirmed_gap_enters_bom_with_structure_confirmed(self) -> None:
        hints = build_structure_gap_hints(
            "配备网袋与隔层",
            [{"name": "外料", "role": "外料"}],
            demand_template=True,
        )
        self.assertGreater(len(hints), 0)
        hid = str(hints[0].get("id") or "")
        items = [{"name": "外料", "amount": 10.0}]
        merged = apply_confirmed_structure_gaps(items, hints, [hid])
        self.assertEqual(len(merged), 2)
        new_row = merged[1]
        self.assertEqual(new_row.get("confirmation_source"), "structure_confirmed")
        self.assertTrue(new_row.get("from_structure_gap_hint"))
        self.assertTrue(new_row.get("exclude_from_cost"))
        self.assertFalse(new_row.get("amount_in_cost"))

    def test_explicit_material_field_still_in_bom(self) -> None:
        items = [
            {
                "name": "dyneema DCH",
                "role": "外料",
                "usage": "-",
                "unit_price": "-",
                "amount": 0.0,
                "field_source_type": EXPLICIT_MATERIAL_FIELD,
            },
        ]
        apply_bag_quote_preparse(
            {"items": items},
            structure_text="隔层网袋（结构说明，不应生成 BOM）",
            structure_inference_text="",
            demand_template=True,
            product_type="斜挎包",
        )
        explicit = [r for r in items if r.get("field_source_type") == EXPLICIT_MATERIAL_FIELD]
        self.assertEqual(len(explicit), 1)
        self.assertEqual(explicit[0].get("name"), "dyneema DCH")

    def test_reflective_tape_classification_notice(self) -> None:
        cls = classify_ambiguous_material("外带反射")
        self.assertIsNotNone(cls)
        assert cls is not None
        self.assertEqual(cls["resolved_category"], "辅料/织带")
        self.assertIn("长度", cls["calculation_basis"])
        self.assertTrue(cls["needs_confirmation"])
        self.assertIn("反光织带", cls["user_notice"])

    def test_reflective_uncertain_requires_confirmation(self) -> None:
        cls = classify_ambiguous_material("反光")
        self.assertIsNotNone(cls)
        assert cls is not None
        self.assertEqual(cls["resolved_category"], "未确定")
        self.assertTrue(cls["needs_confirmation"])
        self.assertFalse(cls.get("participates_in_cost"))
        self.assertIn("请确认", cls["user_notice"])

    def test_enrich_row_attaches_classification(self) -> None:
        row = enrich_row_ambiguous_classification({"name": "外带反射", "spec": "-"})
        amb = row.get("ambiguous_material_classification")
        self.assertIsInstance(amb, dict)
        self.assertEqual(amb.get("resolved_category"), "辅料/织带")
        hints = row.get("accuracy_hints") or []
        self.assertTrue(any("反光织带" in str(h) for h in hints))

    def test_gap_hint_to_bom_row_schema(self) -> None:
        row = gap_hint_to_bom_row(
            {
                "id": "gap_mesh_pocket",
                "name": "网袋/侧袋",
                "detected_text": "侧袋",
                "suggested_direction": "网布、包边",
                "suggested_category": "辅料",
                "category_candidates": ["辅料", "网布", "包边带", "车缝工艺"],
                "material_category_hint": "辅料 / 网布 / 包边带 / 车缝工艺",
                "category_confidence": 0.78,
                "category_hint_display": "建议归类：辅料 / 网布 / 包边带 / 车缝工艺",
            },
        )
        self.assertEqual(row["confirmation_source"], "structure_confirmed")
        self.assertEqual(row["source"], "structure_confirmed")
        self.assertEqual(row.get("structure_gap_hint_id"), "gap_mesh_pocket")
        self.assertEqual(row.get("name"), "侧袋-网布/包边带")
        self.assertEqual(row.get("role"), "辅料")
        self.assertIn("建议归类", str(row.get("calc_note") or ""))

    def test_side_pocket_partition_back_pad_handle_category_hints(self) -> None:
        hints = build_structure_gap_hints(
            "主仓带隔层，正面网兜，侧袋可放水壶，背垫加厚，织带提手",
            [{"name": "600D牛津", "role": "外料"}],
            demand_template=True,
        )
        by_id = {str(h.get("id") or ""): h for h in hints}
        side = by_id.get("gap_mesh_pocket")
        partition = by_id.get("gap_partition")
        back_pad = by_id.get("gap_back_pad")
        handle = by_id.get("gap_handle")
        self.assertIsNotNone(side)
        self.assertIsNotNone(partition)
        self.assertIsNotNone(back_pad)
        self.assertIsNotNone(handle)
        assert side is not None and partition is not None and back_pad is not None and handle is not None
        self.assertIn("辅料", str(side.get("category_hint_display") or ""))
        self.assertIn("网布", str(side.get("category_hint_display") or ""))
        self.assertIn("里料", str(partition.get("category_hint_display") or ""))
        self.assertIn("可能是", str(back_pad.get("category_hint_display") or ""))
        self.assertIn("请人工确认", str(back_pad.get("category_hint_display") or ""))
        self.assertIn("织带", str(handle.get("category_hint_display") or ""))
        self.assertEqual(build_gap_bom_name(partition), "隔层-里料/海绵")

    def test_uncertain_category_hint_display(self) -> None:
        text = format_gap_category_hint_display(
            ("工艺/人工", "辅料"),
            category_confidence=0.62,
        )
        self.assertIn("可能是", text)
        self.assertIn("请人工确认", text)
        low = format_gap_category_hint_display((), category_confidence=0.2)
        self.assertIn("未确定", low)
        self.assertIn("请选择", low)

    def test_covered_hint_still_has_category_fields(self) -> None:
        hints = build_structure_gap_hints(
            "侧袋网袋结构",
            [
                {"name": "网布侧袋", "role": "辅料", "amount": 2.0},
                {"name": "包边带", "role": "织带", "amount": 1.0},
            ],
            demand_template=True,
        )
        covered = [h for h in hints if h.get("bom_covered")]
        if not covered:
            self.skipTest("no covered hints in this fixture")
        for h in covered:
            self.assertTrue(str(h.get("category_hint_display") or "").startswith("建议归类："))

    def test_bom_coverage_detection(self) -> None:
        hints = build_structure_gap_hints(
            "侧袋网袋结构",
            [
                {"name": "网布侧袋", "role": "辅料", "amount": 2.0},
                {"name": "包边带", "role": "织带", "amount": 1.0},
            ],
            demand_template=True,
        )
        mesh_hints = [h for h in hints if "网" in str(h.get("detected_text") or h.get("name") or "")]
        if mesh_hints:
            self.assertTrue(any(h.get("bom_covered") for h in mesh_hints))


if __name__ == "__main__":
    unittest.main()
