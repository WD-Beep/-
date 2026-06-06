from __future__ import annotations

import unittest

from bag_quote_pipeline import apply_bag_quote_preparse
from material_inference import (
    INFERENCE_NOTE,
    SOURCE_IMAGE,
    SOURCE_STRUCTURE,
    assess_excel_sparse_risk,
    build_inferred_candidate_row,
    count_excel_explicit_rows,
    infer_missing_cost_candidates,
    is_excel_explicit_row,
    is_inferred_cost_row,
    merge_material_inference_candidates,
)
from material_row_validity import apply_material_validity_layer, should_skip_knowledge_learn_row
from quote_validation_gate import apply_pricing_gate


class MaterialInferenceTest(unittest.TestCase):
    def test_excel_explicit_row_not_treated_as_inferred(self) -> None:
        row = {"name": "420D外料", "unit_price": "18元/码", "amount": 9.0, "kb_hit": True}
        self.assertTrue(is_excel_explicit_row(row))
        self.assertFalse(is_inferred_cost_row(row))

    def test_inferred_row_markers(self) -> None:
        row = build_inferred_candidate_row(
            component_name="里布",
            source_type=SOURCE_STRUCTURE,
            source_snippet="内衬210D里布",
        )
        self.assertTrue(is_inferred_cost_row(row))
        self.assertFalse(is_excel_explicit_row(row))
        self.assertTrue(row.get("inferred_by_ai"))
        self.assertTrue(row.get("needs_manual_confirm"))
        self.assertEqual(row.get("source_type"), SOURCE_STRUCTURE)
        self.assertIn(INFERENCE_NOTE, str(row.get("calc_note") or ""))

    def test_structure_text_generates_missing_candidates(self) -> None:
        structure = (
            "户外登山背包：顶包+翻盖+腰封，三明治网布背垫，肩带可调，侧袋网袋，"
            "内衬210D里布，5#防水拉链配拉头拉尾，透明PVC视窗，包边织带，丝印logo。"
        )
        items = [{"name": "420D外料", "usage": "0.5码", "unit_price": "18元/码", "amount": 9.0}]
        candidates, report = infer_missing_cost_candidates(structure, items)
        names = " ".join(str(r.get("name") or "") for r in candidates)
        self.assertGreater(len(candidates), 3)
        self.assertIn("里布", names)
        self.assertTrue(any(r.get("source_type") == SOURCE_STRUCTURE for r in candidates))
        self.assertGreater(report.get("detected_structure_component_count", 0), 3)

    def test_image_present_may_upgrade_source_type(self) -> None:
        structure = "旅行背包，侧袋网袋，肩带可调。"
        items = [{"name": "主料", "usage": "1码", "unit_price": "10元/码", "amount": 10.0}]
        candidates, _ = infer_missing_cost_candidates(
            structure,
            items,
            vision_text="附图可见 side pocket mesh 网袋 shoulder strap",
            image_present=True,
        )
        self.assertTrue(
            any(r.get("source_type") == SOURCE_IMAGE for r in candidates)
            or len(candidates) >= 2
        )

    def test_sparse_excel_risk_triggers(self) -> None:
        structure = "户外登山背包：顶包+翻盖+腰封+肩带+侧袋+网袋+里布+拉链。"
        items = [{"name": "420D外料", "usage": "0.5码", "unit_price": "18元/码", "amount": 9.0}]
        risk = assess_excel_sparse_risk(
            structure_text=structure,
            items=items,
            detected_component_count=6,
            image_present=True,
        )
        self.assertTrue(risk.get("triggered"))
        self.assertEqual(risk.get("code"), "excel_sparse_vs_structure_complex")

    def test_preparse_merges_inference_without_overwriting_excel(self) -> None:
        structure = "斜挎包，配备可调腰封；肩带可调；里布210D；5#拉链。"
        payload = {
            "items": [
                {
                    "name": "600D牛津",
                    "usage": "0.4码",
                    "unit_price": "14元/码",
                    "amount": 5.6,
                    "kb_hit": True,
                }
            ]
        }
        apply_bag_quote_preparse(payload, structure_text=structure, product_name="斜挎包")
        explicit = [r for r in payload["items"] if is_excel_explicit_row(r)]
        inferred = [r for r in payload["items"] if is_inferred_cost_row(r)]
        self.assertEqual(len(explicit), 1)
        self.assertEqual(explicit[0].get("unit_price"), "14元/码")
        self.assertTrue(explicit[0].get("kb_hit"))
        self.assertGreater(len(inferred), 0)
        self.assertTrue(payload.get("material_inference_report"))

    def test_inferred_rows_skip_knowledge_learn(self) -> None:
        row = build_inferred_candidate_row(
            component_name="织带",
            source_type=SOURCE_STRUCTURE,
            source_snippet="25mm织带",
        )
        self.assertTrue(should_skip_knowledge_learn_row(row))

    def test_inferred_rows_survive_validity_layer(self) -> None:
        row = build_inferred_candidate_row(
            component_name="织带",
            source_type=SOURCE_STRUCTURE,
            source_snippet="25mm织带",
        )
        rows = apply_material_validity_layer([row])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("exclude_from_cost"))

    def test_pricing_gate_flags_inferred_pending(self) -> None:
        structure = "登山包，顶包+腰封+肩带+侧袋。"
        payload = {"product_name": "登山包", "structure_text_snapshot": structure}
        inferred = build_inferred_candidate_row(
            component_name="腰封",
            source_type=SOURCE_STRUCTURE,
            source_snippet="可调腰封",
        )
        payload["items"] = [
            {"name": "主料", "usage": "0.3码", "unit_price": "20元/码", "amount": 6.0},
            inferred,
        ]
        payload["material_inference_report"] = {
            "inferred_row_count": 1,
            "sparse_excel_risk": {"triggered": True, "code": "excel_sparse_vs_structure_complex"},
        }
        result = {
            "product_name": "登山包",
            "material_total": 20.0,
            "detail_rows": list(payload["items"]),
        }
        apply_bag_quote_preparse(payload, structure_text=structure, product_name="登山包")
        apply_pricing_gate(result, payload, manual_confirmed=False)
        codes = (result.get("pricing_gate") or {}).get("high_risk_codes") or []
        self.assertTrue(
            "inferred_cost_candidates_pending" in codes
            or "excel_sparse_vs_structure_complex" in codes
            or "bag_structure_missing_cost" in codes
        )
        self.assertIn("推理", str(result.get("data_notice") or ""))

    def test_merge_does_not_duplicate(self) -> None:
        payload = {"items": [{"name": "主料", "unit_price": "1元/码"}]}
        merge_material_inference_candidates(payload, structure_text="肩带+腰封", image_present=False)
        n1 = len(payload["items"])
        merge_material_inference_candidates(payload, structure_text="肩带+腰封", image_present=False)
        self.assertEqual(len(payload["items"]), n1)


if __name__ == "__main__":
    unittest.main()
