from __future__ import annotations

import unittest

from bag_quote_costing import detect_bag_product, enrich_pricing_gate_for_bag_quote
from bag_structure_list import (
    build_bag_structure_checklist,
    structure_checklist_high_codes,
)
from quote_validation_gate import apply_pricing_gate


def _complex_structure() -> str:
    return (
        "户外登山背包：顶包+翻盖+腰封背负系统，三明治网布背垫，"
        "肩带可调，侧袋网袋，多拉链。"
    )


class BagStructureListTest(unittest.TestCase):
    def test_structure_checklist_fields_on_bag_quote(self) -> None:
        structure = _complex_structure()
        ctx = detect_bag_product(product_name="登山包", structure_text=structure)
        rows = [
            {"name": "420D前幅", "usage": "0.55码", "unit_price": "18元/码", "amount": 9.9},
            {"name": "顶包外料", "usage": "0.18码", "unit_price": "18元/码", "amount": 3.24},
            {"name": "翻盖外料", "usage": "0.22码", "unit_price": "18元/码", "amount": 3.96},
            {"name": "三明治网布背垫", "usage": "0.30码", "unit_price": "25元/码", "amount": 7.5},
            {"name": "肩带+腰封织带", "usage": "2.5米", "unit_price": "3元/米", "amount": 7.5},
            {"name": "5#拉链侧袋", "usage": "0.6米", "unit_price": "4元/米", "amount": 2.4},
            {"name": "加工费", "usage": "1", "unit_price": "35元/件", "amount": 35.0},
            {"name": "包装", "usage": "1", "unit_price": "3元/套", "amount": 3.0},
        ]
        checklist = build_bag_structure_checklist(
            ctx=ctx,
            structure_text=structure,
            detail_rows=rows,
        )
        self.assertTrue(checklist["is_bag_product"])
        self.assertGreaterEqual(len(checklist["items"]), 5)
        names = {item["name"] for item in checklist["items"]}
        for expected in ("肩带", "腰封", "侧袋", "背垫", "网袋", "顶包", "翻盖"):
            self.assertIn(expected, names)

        shoulder = next(i for i in checklist["items"] if i["name"] == "肩带")
        self.assertEqual(shoulder["category"], "carry")
        self.assertTrue(shoulder["affects_cost"])
        self.assertTrue(shoulder["cost_item_ids"])
        self.assertIn(shoulder["estimate_status"], {"exact", "ai_estimated"})
        self.assertIn("structure_id", shoulder)
        self.assertTrue(str(shoulder["structure_id"]).startswith("carry_"))

    def test_missing_cost_item_marks_high_risk(self) -> None:
        structure = "斜挎包，前袋+侧袋，肩带可调，另设腰封织带。"
        ctx = detect_bag_product(product_name="斜挎包", structure_text=structure)
        rows = [
            {"name": "600D外料", "usage": "0.35码", "unit_price": "15元/码", "amount": 5.25},
            {"name": "肩带织带", "usage": "1.2米", "unit_price": "2元/米", "amount": 2.4},
            {"name": "前袋外料", "usage": "0.12码", "unit_price": "15元/码", "amount": 1.8},
            {"name": "加工费", "usage": "1", "unit_price": "15元/件", "amount": 15.0},
        ]
        checklist = build_bag_structure_checklist(
            ctx=ctx,
            structure_text=structure,
            detail_rows=rows,
        )
        waist = next(i for i in checklist["items"] if i["name"] == "腰封")
        self.assertEqual(waist["estimate_status"], "needs_manual")
        self.assertEqual(waist["risk_level"], "high")
        self.assertFalse(waist["cost_item_ids"])
        self.assertIn("bag_structure_missing_cost", structure_checklist_high_codes(checklist))

    def test_non_bag_product_returns_empty_checklist(self) -> None:
        ctx = detect_bag_product(product_name="塑料杯", structure_text="单层注塑杯")
        checklist = build_bag_structure_checklist(
            ctx=ctx,
            structure_text="单层注塑杯",
            detail_rows=[{"name": "PP料", "usage": "30g", "unit_price": "10元/kg", "amount": 0.3}],
        )
        self.assertFalse(checklist["is_bag_product"])
        self.assertEqual(checklist["items"], [])

    def test_enrich_pricing_gate_exposes_structure_fields(self) -> None:
        structure = "登山包，顶包+腰封+三明治网布背垫+肩带+侧袋。"
        payload = {"product_name": "登山包", "structure_text_snapshot": structure}
        result = {
            "product_name": "登山包",
            "material_total": 9.0,
            "detail_rows": [
                {"name": "主料", "usage": "0.15码", "unit_price": "20元/码", "amount": 3.0, "usage_ai": True},
                {"name": "肩带织带", "usage": "1.2米", "unit_price": "2元/米", "amount": 2.4},
                {"name": "拉链", "usage": "1米", "unit_price": "4元/米", "amount": 4.0},
                {"name": "插扣", "usage": "1 PCS", "unit_price": "0.5元/个", "amount": 0.5},
                {"name": "包装", "usage": "1", "unit_price": "1.5元/套", "amount": 1.5},
            ],
        }
        enrich_pricing_gate_for_bag_quote(result, payload)
        self.assertIn("structure_checklist", result)
        self.assertIn("structure_items", result)
        self.assertIsInstance(result["structure_items"], list)
        self.assertGreater(len(result["structure_items"]), 0)
        self.assertIn("bag_quote_costing", result)

    def test_pricing_gate_high_code_for_structure_missing_cost(self) -> None:
        structure = "登山包，顶包+腰封+三明治网布背垫+肩带。"
        payload = {"product_name": "登山包", "structure_text_snapshot": structure}
        result = {
            "product_name": "登山包",
            "material_total": 9.0,
            "detail_rows": [
                {"name": "主料", "usage": "0.15码", "unit_price": "20元/码", "amount": 3.0, "usage_ai": True},
                {"name": "肩带织带", "usage": "1.2米", "unit_price": "2元/米", "amount": 2.4},
                {"name": "拉链", "usage": "1米", "unit_price": "4元/米", "amount": 4.0},
                {"name": "包装", "usage": "1", "unit_price": "1.5元/套", "amount": 1.5},
            ],
        }
        apply_pricing_gate(result, payload, manual_confirmed=False)
        gate = result.get("pricing_gate") or {}
        codes = gate.get("high_risk_codes") or []
        self.assertIn("bag_structure_missing_cost", codes)
        checklist = result.get("structure_checklist") or {}
        self.assertTrue(checklist.get("is_bag_product"))

    def test_ignored_structure_item_skips_high_code(self) -> None:
        structure = "斜挎包，配备可调腰封。"
        ctx = detect_bag_product(product_name="斜挎包", structure_text=structure)
        rows = [{"name": "外料", "usage": "0.3码", "unit_price": "15元/码", "amount": 4.5}]
        draft = build_bag_structure_checklist(
            ctx=ctx,
            structure_text=structure,
            detail_rows=rows,
        )
        waist = next(i for i in draft["items"] if i["name"] == "腰封")
        checklist = build_bag_structure_checklist(
            ctx=ctx,
            structure_text=structure,
            detail_rows=rows,
            existing_items=[{"structure_id": waist["structure_id"], "user_status": "ignored", "user_note": "本款无腰封"}],
        )
        waist2 = next(i for i in checklist["items"] if i["name"] == "腰封")
        self.assertEqual(waist2["user_status"], "ignored")
        self.assertNotIn("bag_structure_missing_cost", structure_checklist_high_codes(checklist))

    def test_patch_structure_checklist_item_updates_user_status(self) -> None:
        structure = "斜挎包，配备可调腰封。"
        ctx = detect_bag_product(product_name="斜挎包", structure_text=structure)
        rows = [{"name": "外料", "usage": "0.3码", "unit_price": "15元/码", "amount": 4.5}]
        checklist = build_bag_structure_checklist(ctx=ctx, structure_text=structure, detail_rows=rows)
        waist = next(i for i in checklist["items"] if i["name"] == "腰封")
        from bag_structure_list import patch_structure_checklist_item

        patched = patch_structure_checklist_item(
            checklist,
            structure_id=waist["structure_id"],
            user_status="ignored",
        )
        item = next(i for i in patched["items"] if i["structure_id"] == waist["structure_id"])
        self.assertEqual(item["user_status"], "ignored")
        self.assertNotIn("bag_structure_missing_cost", structure_checklist_high_codes(patched))


if __name__ == "__main__":
    unittest.main()
