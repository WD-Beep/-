from __future__ import annotations

import unittest

from bag_quote_costing import (
    build_bag_quote_report,
    check_leak_risks,
    classify_bag_complexity,
    detect_bag_product,
    enrich_pricing_gate_for_bag_quote,
)
from quote_validation_gate import apply_pricing_gate


def _simple_pouch_rows() -> list[dict]:
    return [
        {"name": "210D尼龙外料", "usage": "0.45码", "unit_price": "12元/码", "amount": 5.4},
        {"name": "210D里布", "usage": "0.35码", "unit_price": "8元/码", "amount": 2.8},
        {"name": "5#拉链", "usage": "0.6米", "unit_price": "3元/米", "amount": 1.8},
        {"name": "拉头", "usage": "1 PCS", "unit_price": "0.3元/个", "amount": 0.3},
        {"name": "插扣", "usage": "1 PCS", "unit_price": "0.5元/个", "amount": 0.5},
        {"name": "织带", "usage": "0.5米", "unit_price": "1元/米", "amount": 0.5},
        {"name": "加工费", "usage": "1", "unit_price": "8元/件", "amount": 8.0},
        {"name": "包装纸箱", "usage": "1", "unit_price": "1.2元/个", "amount": 1.2},
    ]


def _medium_sling_rows() -> list[dict]:
    return [
        {"name": "600D外料前幅", "usage": "0.35码", "unit_price": "15元/码", "amount": 5.25},
        {"name": "600D外料后幅", "usage": "0.32码", "unit_price": "15元/码", "amount": 4.8},
        {"name": "里布", "usage": "0.28码", "unit_price": "9元/码", "amount": 2.52},
        {"name": "前袋外料", "usage": "0.12码", "unit_price": "15元/码", "amount": 1.8},
        {"name": "侧袋网布", "usage": "0.08码", "unit_price": "10元/码", "amount": 0.8},
        {"name": "肩带织带", "usage": "1.2米", "unit_price": "2元/米", "amount": 2.4},
        {"name": "提手织带", "usage": "0.4米", "unit_price": "2元/米", "amount": 0.8},
        {"name": "5#拉链主仓", "usage": "0.7米", "unit_price": "4元/米", "amount": 2.8},
        {"name": "5#拉链前袋", "usage": "0.35米", "unit_price": "4元/米", "amount": 1.4},
        {"name": "拉头", "usage": "2 PCS", "unit_price": "0.35元/个", "amount": 0.7},
        {"name": "插扣", "usage": "2 PCS", "unit_price": "0.6元/个", "amount": 1.2},
        {"name": "D环", "usage": "2 PCS", "unit_price": "0.2元/个", "amount": 0.4},
        {"name": "加工费", "usage": "1", "unit_price": "15元/件", "amount": 15.0},
        {"name": "裁剪损耗", "usage": "1", "unit_price": "1.5元/件", "amount": 1.5},
        {"name": "包装", "usage": "1", "unit_price": "1.5元/套", "amount": 1.5},
    ]


def _complex_backpack_rows() -> list[dict]:
    rows = [
        {"name": "420D前幅", "usage": "0.55码", "unit_price": "18元/码", "amount": 9.9},
        {"name": "420D后幅", "usage": "0.52码", "unit_price": "18元/码", "amount": 9.36},
        {"name": "420D侧片", "usage": "0.40码", "unit_price": "18元/码", "amount": 7.2},
        {"name": "420D底片", "usage": "0.25码", "unit_price": "18元/码", "amount": 4.5},
        {"name": "顶包外料", "usage": "0.18码", "unit_price": "18元/码", "amount": 3.24},
        {"name": "翻盖外料", "usage": "0.22码", "unit_price": "18元/码", "amount": 3.96},
        {"name": "里布", "usage": "0.85码", "unit_price": "10元/码", "amount": 8.5},
        {"name": "三明治网布背垫", "usage": "0.30码", "unit_price": "25元/码", "amount": 7.5},
        {"name": "肩带+腰封织带", "usage": "2.5米", "unit_price": "3元/米", "amount": 7.5},
        {"name": "胸扣插扣组", "usage": "1 SET", "unit_price": "2.5元/套", "amount": 2.5},
        {"name": "调节扣", "usage": "4 PCS", "unit_price": "0.4元/个", "amount": 1.6},
        {"name": "8#拉链主仓", "usage": "1.1米", "unit_price": "6元/米", "amount": 6.6},
        {"name": "5#拉链顶包", "usage": "0.45米", "unit_price": "4元/米", "amount": 1.8},
        {"name": "5#拉链侧袋", "usage": "0.6米", "unit_price": "4元/米", "amount": 2.4},
        {"name": "拉头", "usage": "4 PCS", "unit_price": "0.5元/个", "amount": 2.0},
        {"name": "弹力绳系统", "usage": "1.2米", "unit_price": "1.5元/米", "amount": 1.8},
        {"name": "补强片", "usage": "4 PCS", "unit_price": "0.3元/片", "amount": 1.2},
        {"name": "压胶工艺", "usage": "1", "unit_price": "6元/件", "amount": 6.0},
        {"name": "车缝加工", "usage": "1", "unit_price": "35元/件", "amount": 35.0},
        {"name": "裁剪结构损耗", "usage": "1", "unit_price": "4元/件", "amount": 4.0},
        {"name": "刀模摊销", "usage": "1", "unit_price": "2元/件", "amount": 2.0},
        {"name": "包装纸箱吊牌", "usage": "1", "unit_price": "3元/套", "amount": 3.0},
    ]
    return rows


class BagQuoteCostingTest(unittest.TestCase):
    def test_detect_bag_from_product_type(self) -> None:
        ctx = detect_bag_product(product_type="登山背包", product_name="测试款")
        self.assertTrue(ctx.is_bag)
        self.assertEqual(classify_bag_complexity("顶包、腰封、三明治网布背负"), "complex")

    def test_simple_pouch_passes_minimum_modules(self) -> None:
        structure = "单仓收纳包，一条拉链，无肩带。"
        ctx = detect_bag_product(product_name="收纳包", structure_text=structure)
        self.assertEqual(ctx.complexity, "simple")
        report = build_bag_quote_report(
            ctx=ctx,
            rows=_simple_pouch_rows(),
            structure_text=structure,
            material_total=20.5,
        )
        self.assertFalse(report["review_required"])
        self.assertGreaterEqual(report["line_item_count"], report["minimum_line_items"])

    def test_medium_sling_detects_missing_leak_when_structure_has_waist_belt(self) -> None:
        structure = "斜挎包，前袋+侧袋，肩带可调，另设腰封织带。"
        ctx = detect_bag_product(product_name="斜挎包", structure_text=structure)
        rows = _medium_sling_rows()
        leaks = check_leak_risks(structure, rows)
        self.assertTrue(any("腰封" in x["keyword"] for x in leaks))

    def test_complex_backpack_underquote_triggers_review(self) -> None:
        structure = (
            "户外登山背包：顶包+翻盖+腰封背负系统，三明治网布背垫，"
            "多拉链侧袋水壶袋，弹力绳外挂，多处调节织带。"
        )
        ctx = detect_bag_product(product_name="登山包", structure_text=structure)
        self.assertEqual(ctx.complexity, "complex")
        thin_rows = [
            {"name": "主料420D", "usage": "0.2码", "unit_price": "18元/码", "amount": 3.6, "usage_ai": True},
            {"name": "5#拉链", "usage": "1米", "unit_price": "4元/米", "amount": 4.0},
            {"name": "插扣", "usage": "2 PCS", "unit_price": "0.5元/个", "amount": 1.0},
            {"name": "包装", "usage": "1", "unit_price": "2元/套", "amount": 2.0},
        ]
        report = build_bag_quote_report(
            ctx=ctx,
            rows=thin_rows,
            structure_text=structure,
            material_total=10.6,
        )
        self.assertTrue(report["review_required"])
        codes = {r["code"] for r in report["underestimation_risks"]}
        self.assertIn("bag_too_few_line_items", codes)
        self.assertIn("bag_missing_core_modules", codes)

    def test_complex_backpack_full_bom_passes(self) -> None:
        structure = "顶包、翻盖、腰封、三明治网布背垫、弹力绳、侧袋。"
        ctx = detect_bag_product(product_name="登山包", structure_text=structure)
        report = build_bag_quote_report(
            ctx=ctx,
            rows=_complex_backpack_rows(),
            structure_text=structure,
            material_total=120.0,
        )
        self.assertFalse(report["review_required"])
        self.assertGreaterEqual(report["line_item_count"], 18)

    def test_pricing_gate_blocks_complex_underquote(self) -> None:
        structure = "登山包，顶包+腰封+三明治网布背垫+肩带。"
        payload = {
            "product_name": "登山包",
            "structure_text_snapshot": structure,
        }
        result = {
            "product_name": "登山包",
            "material_total": 9.0,
            "detail_rows": [
                {"name": "主料", "usage": "0.15码", "unit_price": "20元/码", "amount": 3.0, "usage_ai": True},
                {"name": "拉链", "usage": "1米", "unit_price": "4元/米", "amount": 4.0},
                {"name": "插扣", "usage": "1 PCS", "unit_price": "0.5元/个", "amount": 0.5},
                {"name": "包装", "usage": "1", "unit_price": "1.5元/套", "amount": 1.5},
            ],
        }
        apply_pricing_gate(result, payload, manual_confirmed=False)
        gate = result.get("pricing_gate") or {}
        self.assertTrue(result.get("bag_quote_review_required"))
        self.assertEqual(gate.get("quote_gate_status"), "NEED_CONFIRM")
        self.assertIn("bag_too_few_line_items", gate.get("high_risk_codes") or [])


if __name__ == "__main__":
    unittest.main()
