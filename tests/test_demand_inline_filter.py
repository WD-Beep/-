"""结构说明 inline 料子名过滤 — 避免出现幅宽 CM、单价断层等伪物料行。"""

import unittest

from demand_parser import (
    _extract_inline_prices,
    _extract_materials_from_section_c,
    _is_excel_error_value,
    _is_spurious_structure_inline_name,
    _looks_like_fabric_name_not_descriptor,
    _split_multi_value,
    _split_section_c_material_chunks,
    _trim_leading_for_inline,
    parse_demand_from_rows,
)


class StructureInlineMaterialFilter(unittest.TestCase):
    def test_split_multi_value_for_zipper_connectors(self):
        out = _split_multi_value("#5尼龙拉链+YKK防水拉链；普通拉头，尾绳")
        self.assertEqual(out, ["#5尼龙拉链", "YKK防水拉链", "普通拉头", "尾绳"])

    def test_outer_fabric_comma_descriptor_not_second_material(self) -> None:
        self.assertFalse(_looks_like_fabric_name_not_descriptor("亮面折光效果"))
        self.assertTrue(_looks_like_fabric_name_not_descriptor("20D尼龙精品亮光防水面料"))
        chunks = _split_section_c_material_chunks(
            "外料",
            "20D尼龙精品亮光防水面料，亮面折光效果",
        )
        self.assertEqual(chunks, ["20D尼龙精品亮光防水面料"])
        mats = _extract_materials_from_section_c(
            {"外料": "20D尼龙精品亮光防水面料，亮面折光效果", "里料": "210D涤纶里布"},
        )
        outer = [m for m in mats if m.role == "外料"]
        self.assertEqual(len(outer), 1)
        self.assertIn("20D尼龙", outer[0].name)
        self.assertNotIn("折光效果外料", outer[0].name)
        self.assertIn("亮面折光效果", outer[0].note)

    def test_b260172_style_outer_cell_parse(self) -> None:
        rows = [
            ["B. 产品规格"],
            ["产品类型", "产品名称/款号", "结构说明"],
            ["收纳包", "B260172", "外层采用亮面仿尼龙面料，表面有轻微反光折射效果；内里为210D涤纶内衬。"],
            ["C. 材料与配件（标准名/编码）"],
            [
                "外料(标准名/编码)",
                "外料颜色",
                "里料(标准名/编码)",
                "拉链类型",
                "拉头类型",
                "扣具等级",
            ],
            [
                "20D尼龙精品亮光防水面料，亮面折光效果",
                "紫色",
                "210D涤纶里布",
                "5号尼龙拉链",
                "普通拉头",
                "五金标准",
            ],
            ["D. 工艺（多选用;分隔）"],
            ["LOGO方式(多选)"],
            ["丝印"],
        ]
        out = parse_demand_from_rows(rows, file_name="B260172报价资料.xlsx")
        outer_names = [m.name for m in out.materials if m.role == "外料"]
        self.assertEqual(len(outer_names), 1)
        self.assertIn("20D尼龙", outer_names[0])
        self.assertFalse(any("折光效果" in n and "外料" in n for n in outer_names))

    def test_spurious_dimension_only_names(self):
        self.assertTrue(_is_spurious_structure_inline_name("幅宽137CM"))
        self.assertTrue(_is_spurious_structure_inline_name("长 27 CM"))
        self.assertTrue(_is_spurious_structure_inline_name("宽12cm"))

    def test_spurious_price_tail_fragments(self):
        self.assertTrue(_is_spurious_structure_inline_name("5元/码)+5#YKK拉头"))
        self.assertTrue(_is_spurious_structure_inline_name("63元/个)+拉尾"))

    def test_keeps_material_like_snippets(self):
        self.assertFalse(_is_spurious_structure_inline_name("1.43oz DCF"))
        self.assertFalse(_is_spurious_structure_inline_name("5号YKK防水拉链"))

    def test_spurious_price_intro_names(self):
        self.assertTrue(_is_spurious_structure_inline_name("价格为"))
        self.assertTrue(_is_spurious_structure_inline_name("成本参考"))
        _, mats = _extract_inline_prices("X-PAC 主料，价格为50元/码")
        self.assertEqual([m.name for m in mats], ["X-PAC 主料"])

    def test_section_c_skips_excel_error_material_cells(self):
        self.assertTrue(_is_excel_error_value("#NAME?"))
        mats = _extract_materials_from_section_c(
            {
                "外料标准名编码": "#NAME?",
                "里料标准名编码": "210D涤纶",
            }
        )
        self.assertEqual([m.name for m in mats], ["210D涤纶"])

    def test_extract_skips_dimension_wrapped_mini_price(self):
        _, mats = _extract_inline_prices("裁片幅宽137CM（辅料0.4元/m）")
        self.assertEqual(len(mats), 0)

    def test_trim_keeps_denier_prefixed_names(self):
        """600D… 前缀不得被章节序号正则当成「600」拆掉。"""
        w = "主面料：600D塔丝隆格子布（"
        self.assertEqual(_trim_leading_for_inline(w), "600D塔丝隆格子布")

    def test_extract_inline_keeps_denier_on_multiline_structure(self):
        blob = (
            "尺寸：长45cm × 宽30cm × 高17cm\n"
            "主面料：600D塔丝隆格子布（12元/码）\n"
            "拉链：5号YKK（7元/码）"
        )
        rows, mats = _extract_inline_prices(blob)
        names = [m.name for m in mats]
        self.assertIn("600D塔丝隆格子布", names)
        self.assertNotIn("D塔丝隆格子布", names)


if __name__ == "__main__":
    unittest.main()
