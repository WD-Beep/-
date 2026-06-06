"""需求表模板：结构说明/备注不得误生成推理待核 BOM 行。"""

from __future__ import annotations

import unittest

from bag_quote_pipeline import apply_bag_quote_preparse
from demand_field_sources import (
    EXPLICIT_ACCESSORY_FIELD,
    EXPLICIT_MATERIAL_FIELD,
    REMARK_FIELD,
    STRUCTURE_NOTE_FIELD,
    build_field_source_map,
    build_structure_inference_text,
    classify_demand_field,
    collect_structure_note_hints,
)
from demand_parser import parse_demand_from_rows
from material_inference import infer_missing_cost_candidates, is_inferred_cost_row


def _template_rows() -> list[list[str]]:
    """模拟图二/图三规范需求表关键区块。"""
    return [
        ["A. 客户与报价信息", "", "", "", "", "", "", "", "", "", "", ""],
        ["客户名称", "国家", "城市", "Incoterms", "币种", "是否含税13", "利润率", "价格类型", "", "", "", ""],
        ["Vicky", "美国", "LA", "FOB深圳", "USD", "是", "30%", "FOB价", "", "", "", ""],
        ["B. 产品规格", "", "", "", "", "", "", "", "", "", "", ""],
        ["产品类型", "产品名称/款号", "L(cm)", "W(cm)", "H(cm)", "结构复杂度", "结构说明", "", "参考图片/链接", "", "", ""],
        [
            "保温包",
            "2000个",
            "45",
            "13",
            "15",
            "标准",
            "两边可以扣在一起",
            "",
            "大身面料：210涤纶印花 里布：PEVA；成本要控制在20元以内",
            "",
            "",
            "",
        ],
        ["C. 材料与配件（标准名/编码）", "", "", "", "", "", "", "", "", "", "", ""],
        [
            "外料(标准名/编码)",
            "外料颜色",
            "里料(标准名/编码)",
            "里料颜色",
            "防水等级",
            "拉链类型",
            "拉链颜色",
            "拉头类型",
            "扣具等级",
            "肩带/织带类型",
            "肩带长度(cm)",
            "",
        ],
        [
            "dyneema DCH",
            "数码印",
            "无",
            "",
            "防泼水",
            "普通拉链",
            "黑色",
            "绳结拉尾",
            "多耐福品牌扣具",
            "",
            "70",
            "",
        ],
        ["D. 工艺 (多选用; 分隔)", "", "", "", "", "", "", "", "", "", "", ""],
        ["LOGO方式(多选)", "LOGO内容", "关键工艺(多选)", "特殊工艺备注", "", "", "", "", "", "", "", ""],
        ["丝印", "12345", "", "", "", "", "", "", "", "", "", ""],
        ["F. 数量阶梯 (必须三档)", "", "", "", "", "", "", "", "", "", "", ""],
        ["数量1", "数量2", "数量3", "", "", "", "", "", "", "", "", ""],
        ["500", "1000", "3000", "", "", "", "", "", "", "", "", ""],
    ]


class DemandTemplateStructureInferenceTest(unittest.TestCase):
    def test_field_source_classification(self) -> None:
        self.assertEqual(classify_demand_field("B", "结构说明"), STRUCTURE_NOTE_FIELD)
        self.assertEqual(classify_demand_field("B", "参考图片/链接"), REMARK_FIELD)
        self.assertEqual(classify_demand_field("C", "外料(标准名/编码)"), EXPLICIT_MATERIAL_FIELD)
        self.assertEqual(classify_demand_field("C", "拉链类型"), EXPLICIT_ACCESSORY_FIELD)
        self.assertEqual(classify_demand_field("C", "外料颜色"), REMARK_FIELD)
        self.assertEqual(classify_demand_field("D", "关键工艺(多选)"), "process_field")

    def test_demand_template_inference_text_empty(self) -> None:
        parsed = parse_demand_from_rows(_template_rows(), file_name="demo.xlsx", sheet_name="需求表")
        self.assertTrue(parsed.is_demand_template)
        self.assertEqual(parsed.structure_inference_text, "")
        self.assertIn("结构说明", parsed.field_sources.get("B", {}))
        self.assertEqual(parsed.field_sources["B"]["结构说明"], STRUCTURE_NOTE_FIELD)

    def test_template_structure_note_does_not_generate_bom_rows(self) -> None:
        structure_note = (
            "需一层主仓，内设有专用隔层，可容纳12.9英寸平板电脑；"
            "高弹力绑绳在包体正面交叉穿行，形成网兜结构；成本要控制在20元以内"
        )
        payload = {
            "items": [
                {
                    "name": "dyneema DCH",
                    "role": "外料",
                    "usage": "-",
                    "unit_price": "-",
                    "amount": 0.0,
                    "field_source_type": EXPLICIT_MATERIAL_FIELD,
                },
                {
                    "name": "普通拉链",
                    "role": "拉链",
                    "usage": "-",
                    "unit_price": "-",
                    "amount": 0.0,
                    "field_source_type": EXPLICIT_ACCESSORY_FIELD,
                },
            ]
        }
        apply_bag_quote_preparse(
            payload,
            structure_text=structure_note,
            structure_inference_text="",
            demand_template=True,
            product_name="斜挎包",
            product_type="斜挎包",
        )
        inferred = [r for r in payload["items"] if is_inferred_cost_row(r)]
        names = " ".join(str(r.get("name") or "") for r in inferred)
        self.assertNotIn("网袋", names)
        self.assertNotIn("隔层", names)
        hints = payload.get("structure_inference_hints") or []
        hint_names = {str(h.get("name") or "") for h in hints if isinstance(h, dict)}
        self.assertTrue({"网袋", "隔层"} & hint_names or len(hint_names) >= 1)

    def test_infer_missing_cost_suppressed_for_demand_template(self) -> None:
        structure = "斜挎包配备隔层与侧袋网袋，肩带可调。"
        items = [{"name": "600D牛津", "usage": "0.4码", "unit_price": "14元/码", "amount": 5.6}]
        candidates, report = infer_missing_cost_candidates(
            structure,
            items,
            demand_template=True,
        )
        self.assertEqual(candidates, [])
        self.assertTrue(report.get("demand_template_suppressed"))

    def test_non_template_structure_still_infers(self) -> None:
        structure = "户外登山背包：顶包+翻盖+腰封，三明治网布背垫，肩带可调，侧袋网袋。"
        items = [{"name": "420D外料", "usage": "0.5码", "unit_price": "18元/码", "amount": 9.0}]
        candidates, report = infer_missing_cost_candidates(structure, items, demand_template=False)
        self.assertGreater(len(candidates), 2)
        self.assertGreater(report.get("detected_structure_component_count", 0), 2)

    def test_collect_hints_from_note_only(self) -> None:
        hints = collect_structure_note_hints(
            "主仓带隔层，正面网兜网袋结构；成本要控制在20元以内",
            demand_template=True,
        )
        names = {h["name"] for h in hints}
        self.assertTrue("隔层" in names or "网袋" in names)

    def test_structure_note_guarded_words_not_in_materials(self) -> None:
        rows = _template_rows()
        # 覆盖 B 区结构说明为含网袋/隔层/侧袋/背垫/提手
        rows[5][6] = "配备网袋、隔层、侧袋、背垫与提手，成本要控制在20元以内"
        parsed = parse_demand_from_rows(rows)
        names = " ".join(m.name for m in parsed.materials)
        roles = {m.role for m in parsed.materials}
        for word in ("网袋", "隔层", "侧袋", "背垫", "提手"):
            self.assertNotIn(word, names, word)
        self.assertFalse(any(m.source.startswith("structure_inline") for m in parsed.materials))
        self.assertEqual(parsed.inline_prices, [])
        self.assertIn("外料", roles)
        self.assertIn("拉链", roles)
        self.assertIn("拉头", roles)

    def test_structure_note_fabric_price_not_in_materials(self) -> None:
        rows = _template_rows()
        rows[5][6] = "主面料 210D涤纶（15元/码），里布 PEVA（8元/码），5#拉链（3元/码）"
        rows[5][8] = "参考图备注：成本要控制在20元以内"
        parsed = parse_demand_from_rows(rows)
        names = [m.name for m in parsed.materials]
        self.assertNotIn("主面料 210D涤纶", names)
        self.assertNotIn("里布 PEVA", names)
        self.assertFalse(any("210D涤纶" in n and m.role != "里料" for m, n in zip(parsed.materials, names)))
        self.assertFalse(any(m.source.startswith("structure_inline") for m in parsed.materials))
        self.assertEqual(parsed.inline_prices, [])
        self.assertIn("dyneema DCH", names)

    def test_section_c_explicit_materials_preserved(self) -> None:
        parsed = parse_demand_from_rows(_template_rows())
        by_role = {}
        for m in parsed.materials:
            by_role.setdefault(m.role, []).append(m.name)
        self.assertIn("dyneema DCH", by_role.get("外料", []))
        self.assertTrue(any("拉链" in n for n in by_role.get("拉链", [])))
        self.assertTrue(any("拉" in n for n in by_role.get("拉头", [])))
        self.assertTrue(any("扣" in n for n in by_role.get("扣具", [])))
        self.assertEqual(
            {m.source for m in parsed.materials},
            {"demand_form"},
        )

    def test_remark_fields_not_in_structure_text_materials(self) -> None:
        parsed = parse_demand_from_rows(_template_rows())
        mat_blob = " ".join(m.name for m in parsed.materials)
        self.assertNotIn("成本要控制", mat_blob)
        self.assertNotIn("210涤纶印花", mat_blob)
        self.assertNotIn("PEVA", mat_blob)


if __name__ == "__main__":
    unittest.main()
