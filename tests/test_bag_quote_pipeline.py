from __future__ import annotations

import unittest

from bag_quote_pipeline import (
    apply_bag_quote_preparse,
    build_bag_structure_llm_addon,
    build_structure_cost_candidates,
    find_structure_extraction_leaks,
    pipeline_high_codes,
)
from material_row_validity import RECOGNITION_CANDIDATE, apply_material_validity_layer
from bag_structure_list import build_bag_structure_checklist
from bag_quote_costing import detect_bag_product
from quote_validation_gate import apply_pricing_gate


class BagQuotePipelineTest(unittest.TestCase):
    def test_preparse_extracts_structure_before_quote(self) -> None:
        structure = "户外登山背包：顶包+翻盖+腰封，三明治网布背垫，肩带可调，侧袋网袋。"
        payload = {"items": [{"name": "420D外料", "usage": "0.5码", "unit_price": "18元/码", "amount": 9.0}]}
        meta = apply_bag_quote_preparse(
            payload,
            structure_text=structure,
            product_name="登山包",
        )
        self.assertTrue(meta["active"])
        checklist = payload["structure_checklist"]
        names = {it["name"] for it in checklist["items"]}
        for expected in ("肩带", "腰封", "侧袋", "背垫", "网袋", "顶包", "翻盖"):
            self.assertIn(expected, names)
        self.assertIn("bag_quote_pipeline", payload)
        self.assertGreater(len(payload["items"]), 1)

    def test_cost_candidates_for_missing_structure_rows(self) -> None:
        structure = "斜挎包，配备可调腰封；肩带可调。"
        ctx = detect_bag_product(product_name="斜挎包", structure_text=structure)
        checklist = build_bag_structure_checklist(ctx=ctx, structure_text=structure, detail_rows=[])
        rows, meta = build_structure_cost_candidates(checklist, [])
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(any("推理待核" in r["name"] or "结构待核" in r["name"] for r in rows))
        self.assertTrue(all(r.get("from_bag_structure_extraction") for r in rows))

    def test_extraction_leak_high_code(self) -> None:
        structure = "登山包，顶包+腰封+肩带。"
        empty_checklist = {"is_bag_product": True, "items": []}
        leaks = find_structure_extraction_leaks(structure, empty_checklist)
        self.assertGreater(len(leaks), 0)
        codes = pipeline_high_codes(structure, empty_checklist)
        self.assertIn("bag_structure_extraction_leak", codes)

    def test_gate_high_when_structure_missing_cost(self) -> None:
        structure = "登山包，顶包+腰封+肩带+侧袋。"
        payload = {"product_name": "登山包", "structure_text_snapshot": structure}
        result = {
            "product_name": "登山包",
            "material_total": 20.0,
            "detail_rows": [{"name": "主料", "usage": "0.3码", "unit_price": "20元/码", "amount": 6.0}],
        }
        apply_bag_quote_preparse(payload, structure_text=structure, product_name="登山包")
        apply_pricing_gate(result, payload, manual_confirmed=False)
        codes = (result.get("pricing_gate") or {}).get("high_risk_codes") or []
        self.assertTrue(
            "bag_structure_missing_cost" in codes or "bag_structure_extraction_leak" in codes
        )
        self.assertIn("structure_checklist", result)

    def test_preparse_candidates_survive_validity_layer(self) -> None:
        structure = "户外登山背包：顶包+翻盖+腰封，三明治网布背垫。"
        payload = {"items": [{"name": "420D外料", "usage": "0.5码", "unit_price": "18元/码", "amount": 9.0}]}
        apply_bag_quote_preparse(payload, structure_text=structure, product_name="登山包")
        rows = apply_material_validity_layer(list(payload["items"]))
        pending = [r for r in rows if "结构待核" in str(r.get("name") or "") or "推理待核" in str(r.get("name") or "")]
        self.assertGreater(len(pending), 0)
        self.assertTrue(all(r.get("recognition_status") == RECOGNITION_CANDIDATE for r in pending))

    def test_llm_addon_mentions_split_missing_price(self) -> None:
        addon = build_bag_structure_llm_addon(
            {
                "items": [{"name": "插扣", "structure_id": "x", "category": "accessory", "source_text": "侧袋插扣"}],
            }
        )
        self.assertIn("recognition_status='split'", addon)
        self.assertIn("unit_price_ai=true", addon)
        self.assertIn("结构待核", addon)


if __name__ == "__main__":
    unittest.main()
