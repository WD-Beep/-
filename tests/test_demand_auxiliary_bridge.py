"""辅 sheet 合并、表内底料锚点、cost_bridge 对照。"""
from __future__ import annotations

import unittest

from demand_parser import (
    Material,
    _extract_sheet_material_subtotal_anchors,
    absorb_quotation_detail_into_demand_fabric_rows,
    enrich_quote_item_rows_with_quotation_calc,
    extend_materials_dedupe_by_name,
    materials_from_rows_quotation_detail_block,
)
from quote_engine import calculate_quote


class DemandAuxiliaryBridgeTest(unittest.TestCase):
    def test_quotation_detail_skips_cost_reference_label_row(self) -> None:
        rows = [
            ["项目", "计算方式", "报价用量", "单价", "金额/个"],
            ["210D再生尼龙", "系统估外袋面积", "0.5码", "80元/码", "40"],
            ["成本参考", "成品尺寸：长 21cm x 高 12cm x 厚 6cm", "1套", "15元/码", "15"],
            ["300D涤纶", "里布", "0.3码", "10元/码", "3"],
        ]
        mats = materials_from_rows_quotation_detail_block(rows, sheet_slug="需求表")
        names = [m.name for m in mats]
        self.assertNotIn("成本参考", names)
        self.assertIn("210D再生尼龙", names)
        self.assertIn("300D涤纶", names)

    def test_embedded_quotation_detail_rows_on_main_sheet(self) -> None:
        rows = [
            ["项目", "计算方式", "报价用量", "单价", "金额/个"],
            ["DCF外料", "圆筒侧片+底片+15%损耗", "0.0744码", "450元/码", "33.49"],
        ]
        mats = materials_from_rows_quotation_detail_block(rows, sheet_slug="需求表")
        self.assertEqual(len(mats), 1)
        self.assertIn("损耗", mats[0].calc_method)
        self.assertTrue(mats[0].source.startswith("bom_detail:"))

    def test_quotation_detail_figure2_formula_column_merged_into_calc_note(self) -> None:
        """「计算方式」+「单位用量（具体算法）」双列时合并进 calc_method，且不把算式列当数值用量."""
        rows = [
            ["项目", "计算方式", "单位用量（具体算法）", "报价用量", "单价", "金额/个"],
            [
                "ULTRA 200X",
                "主料展开",
                "包身面积=(48+2)×(48+14)÷10000=0.52㎡；损耗30%",
                "0.52㎡",
                "420元/㎡",
                "218",
            ],
        ]
        mats = materials_from_rows_quotation_detail_block(rows, sheet_slug="细表")
        self.assertEqual(len(mats), 1)
        self.assertEqual(mats[0].quoted_usage, "0.52㎡")
        cn = mats[0].calc_method or ""
        self.assertIn("包身面积", cn)
        self.assertIn("主料展开", cn)

    def test_absorb_detail_calc_into_primary_when_usage_already_filled(self) -> None:
        mats = [
            Material(role="外料", name="主面料DCF", quoted_usage="0.35码", source="demand_form"),
            Material(
                role="外料",
                name="DCF外料",
                quoted_usage="0.0744码",
                calc_method="圆筒侧片 + 底片 + 压胶条面积，损耗15%",
                source="bom_detail:DCF",
            ),
        ]
        out = absorb_quotation_detail_into_demand_fabric_rows(list(mats))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].name, "主面料DCF")
        self.assertEqual(out[0].quoted_usage, "0.35码")
        self.assertIn("圆筒侧片", out[0].calc_method or "")

    def test_sheet_subtotal_anchor_extract(self) -> None:
        rows = [
            ["底料：101.80元", ""],
            ["其它", "物料合计 55.5"],
        ]
        anchors = _extract_sheet_material_subtotal_anchors(rows)
        amounts = {a["material_subtotal"]: a["anchor_label"] for a in anchors}
        self.assertIn(101.8, amounts)
        self.assertEqual(amounts[101.8], "底料")

    def test_enrich_quote_items_from_quotation_detail_by_fabric_family(self) -> None:
        mats = [
            Material(
                role="外料",
                name="DCF外料",
                quoted_usage="0.0744码",
                calc_method="圆筒侧片+底片+压胶条 同面料面积，再加15%损耗",
                source="bom_detail:细表",
            )
        ]
        rows: list[dict] = [{"name": "主面料DCF", "spec": "-", "usage": "0.35码"}]
        out = enrich_quote_item_rows_with_quotation_calc(rows, mats)
        self.assertIn("损耗", str(out[0].get("calc_note") or ""))

    def test_extend_materials_skips_duplicate_name(self) -> None:
        base = [Material(role="外料", name="600D牛津", source="demand_form")]
        add = [
            Material(role="外料", name="600d 牛津", spec="粉色", inline_price="8元/米", source="bom_sheet:X"),
            Material(role="拉链", name="防水拉链", source="bom_sheet:X"),
        ]
        out = extend_materials_dedupe_by_name(base, add)
        self.assertEqual(len(out), 2)
        names = [m.name for m in out]
        self.assertIn("防水拉链", names)

    def test_cost_bridge_sheet_anchor_gap(self) -> None:
        r = calculate_quote(
            {
                "items": [
                    {
                        "name": "测试主料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "120元",
                        "amount": 120.0,
                    },
                ],
                "reference_prices": [
                    {
                        "kind": "sheet_material_subtotal",
                        "anchor_label": "底料",
                        "material_subtotal": 100.0,
                        "source_text": "",
                    },
                ],
            },
        )
        cb = r.get("cost_bridge") or {}
        self.assertEqual(cb.get("sheet_anchor_material_subtotal"), 100.0)
        self.assertEqual(cb.get("sheet_anchor_vs_computed_material_gap"), 20.0)


if __name__ == "__main__":
    unittest.main()
