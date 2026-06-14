"""需求表多行分区、数量阶梯与包装区解析。"""
from __future__ import annotations

import base64
import unittest
from pathlib import Path

from demand_parser import parse_demand_from_payload, parse_demand_from_rows
from sheet_parser import detect_section_marker, extract_quote_parameters, row_is_quantity_tier_header


class DemandParserMultrowSectionsTest(unittest.TestCase):
    def test_section_c_merges_multiple_value_rows(self) -> None:
        rows = [
            ["C. 材料与配件（标准名/编码）"],
            [
                "外料(标准名/编码)",
                "里料(标准名/编码)",
                "拉链",
                "拉头类型",
                "拉片",
            ],
            ["600D牛津布", "210D涤纶", "5#拉链，金色金属拉链", "金色拉头", "PU拉片"],
            ["", "2-3mm EPE保温棉", "5#拉链，黑色金属拉链", "黑色拉头*1", "黑色常规拉片*1"],
            ["D. 工艺（多选用;分隔）"],
        ]
        out = parse_demand_from_rows(rows)
        names = [m.name for m in out.materials]
        self.assertIn("600D牛津布", names)
        self.assertIn("210D涤纶", names)
        self.assertIn("2-3mm EPE保温棉", names)
        self.assertIn("5#拉链", names)
        self.assertTrue(any("金色" in n and "拉链" in n for n in names))
        self.assertTrue(any("黑色" in n and "拉链" in n for n in names))
        self.assertIn("金色拉头", names)
        self.assertTrue(any("黑色拉头" in n for n in names))
        pullers = [m for m in out.materials if "拉头" in m.name and "黑色" in m.name]
        self.assertTrue(pullers)
        self.assertEqual(pullers[0].name, "黑色拉头")
        self.assertNotIn("*1", pullers[0].name)
        self.assertTrue(any("拉片" in n for n in names))
        self.assertGreaterEqual(len(out.materials), 8)

    def test_implicit_quantity_ladder_without_f_title(self) -> None:
        rows = [
            ["E. 模具与开料成本"],
            ["是否需要开料模/刀模", "开料模/刀模费用(RMB)"],
            ["否", "500"],
            ["数量1", "数量2", "数量3", "数量4"],
            ["500", "1000", "1500"],
            ["G. 包装与装箱"],
            ["单个包装", "外箱类型"],
            ["礼盒包装", "普通纸箱"],
        ]
        out = parse_demand_from_rows(rows)
        self.assertEqual(out.quantities, (500, 1000, 1500))
        self.assertEqual(out.sections.get("G", {}).get("单个包装"), "礼盒包装")
        self.assertEqual(out.sections.get("G", {}).get("外箱类型"), "普通纸箱")

    def test_detect_section_marker_supports_g(self) -> None:
        marker = detect_section_marker(["G. 包装与装箱"])
        self.assertIsNotNone(marker)
        assert marker is not None
        self.assertEqual(marker[0].upper(), "G")

    def test_quantity_header_row_detection(self) -> None:
        self.assertTrue(row_is_quantity_tier_header(["数量1", "数量2", "数量3", "数量4"]))
        self.assertFalse(row_is_quantity_tier_header(["500", "1000", "1500"]))

    def test_quote_params_include_packaging_section_g(self) -> None:
        rows = [
            ["G. 包装与装箱"],
            ["单个包装", "外箱类型", "装箱量(pcs/ctn)"],
            ["礼盒包装", "普通纸箱", "24"],
        ]
        params = extract_quote_parameters(rows)
        self.assertEqual(params.get("G", {}).get("单个包装"), "礼盒包装")
        self.assertEqual(params.get("G", {}).get("外箱类型"), "普通纸箱")

    def test_simple_demand_template_still_parses(self) -> None:
        rows = [
            ["A. 客户与报价信息"],
            ["客户名称", "国家"],
            ["ACME", "中国"],
            ["B. 产品规格"],
            ["产品类型", "结构说明"],
            ["背包", "标准双肩结构"],
            ["C. 材料与配件"],
            ["外料(标准名/编码)", "里料(标准名/编码)"],
            ["600D牛津布", "210D涤纶"],
            ["F. 数量阶梯"],
            ["数量1", "数量2"],
            ["300", "500"],
        ]
        out = parse_demand_from_rows(rows)
        names = [m.name for m in out.materials]
        self.assertEqual(names, ["600D牛津布", "210D涤纶"])
        self.assertEqual(out.quantities, (300, 500))


class DemandParserB260178FixtureTest(unittest.TestCase):
    _FIXTURE = Path(r"D:/测试数据/B260178报价资料.xlsx")

    @unittest.skipUnless(_FIXTURE.is_file(), "B260178 fixture xlsx not present")
    def test_b260178_parses_full_material_list(self) -> None:
        blob = base64.b64encode(self._FIXTURE.read_bytes()).decode("ascii")
        out = parse_demand_from_payload({"name": self._FIXTURE.name, "content_base64": blob})
        names = [m.name for m in out.materials]
        self.assertEqual(out.quantities, (500, 1000, 1500))
        self.assertEqual(out.sections.get("G", {}).get("单个包装"), "礼盒包装")
        self.assertEqual(out.sections.get("G", {}).get("外箱类型"), "普通纸箱")
        self.assertGreaterEqual(len(out.materials), 10, msg=names)
        expected_fragments = (
            "FJ-18 600D舞龙布",
            "PEVA",
            "EPE保温棉",
            "金色",
            "黑色金属拉链",
            "黑色拉头",
            "拉片",
            "五金",
            "织带",
            "网袋",
        )
        joined = " ".join(names)
        for frag in expected_fragments:
            self.assertIn(frag, joined, msg=f"missing {frag} in {names}")
        self.assertTrue(out.structure_gap_hints or out.structure_text.strip())


class DemandParserStrapLengthMetadataTest(unittest.TestCase):
    def test_strap_length_fragment_not_material_name(self) -> None:
        rows = [
            ["C. 材料与配件（标准名/编码）"],
            ["肩带/织带类型", "肩带长度(cm)"],
            ["1寸坑纹尼龙织带,约1.3m", "70"],
        ]
        out = parse_demand_from_rows(rows)
        names = [m.name for m in out.materials]
        self.assertIn("1寸坑纹尼龙织带", names)
        self.assertFalse(any("约1.3m" in n or n.startswith("约") for n in names))
        webbing = next(m for m in out.materials if "坑纹尼龙织带" in m.name)
        self.assertIn("1.3", str(webbing.quoted_usage or ""))

    def test_length_only_strap_cell_does_not_create_material(self) -> None:
        from demand_parser import _extract_materials_from_section_c

        materials = _extract_materials_from_section_c({"肩带/织带类型": "约1.3m"})
        names = [m.name for m in materials]
        self.assertEqual(names, [])

    def test_strap_thickness_descriptor_not_material_name(self) -> None:
        from demand_parser import _extract_materials_from_section_c

        materials = _extract_materials_from_section_c(
            {"肩带/织带类型": "25mm坑带,约0.8cm粗"}
        )
        names = [m.name for m in materials]
        self.assertTrue(any("坑带" in n for n in names))
        self.assertFalse(any("0.8cm" in n and "坑" not in n for n in names))
        webbing = next(m for m in materials if "坑带" in m.name)
        blob = f"{webbing.spec or ''} {webbing.quoted_usage or ''}"
        self.assertIn("0.8", blob)

    def test_spec_plus_material_name_not_filtered(self) -> None:
        from demand_parser import _extract_materials_from_section_c, _looks_like_length_or_dimension_metadata

        self.assertFalse(_looks_like_length_or_dimension_metadata("2-3mm EPE保温棉"))
        self.assertFalse(_looks_like_length_or_dimension_metadata("3mm海绵"))
        self.assertFalse(_looks_like_length_or_dimension_metadata("5#拉链"))
        self.assertTrue(_looks_like_length_or_dimension_metadata("约1.3m"))
        self.assertTrue(_looks_like_length_or_dimension_metadata("约---1.3m"))
        self.assertTrue(_looks_like_length_or_dimension_metadata("约1.1-1.3m"))
        self.assertTrue(_looks_like_length_or_dimension_metadata("约0.8cm粗"))

        materials = _extract_materials_from_section_c({"里料(标准名/编码)": "2-3mm EPE保温棉"})
        names = [m.name for m in materials]
        self.assertIn("2-3mm EPE保温棉", names)


if __name__ == "__main__":
    unittest.main()
