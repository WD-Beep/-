from __future__ import annotations

import unittest

from demand_parser import (
    Material,
    calc_note_looks_like_bom_sheet,
    enrich_items_calc_note_from_structure,
    enrich_quote_item_rows_with_quotation_calc,
    should_prefer_calc_note_incoming,
)


class StructureCalcNoteEnrichTest(unittest.TestCase):
    def test_quotation_sheet_overwrites_placeholder_calc_note(self) -> None:
        mats = [
            Material(
                role="主料",
                name="DCF外料",
                calc_method="圆筒侧片+底片+压胶条同面料面积再加15%损耗",
            ),
        ]
        rows = [
            {
                "name": "1.43oz DCF",
                "calc_note": "用量为 AI 估计，数据源不含「计算方式」；请以业务 BOM 手写公式为正。",
            },
        ]
        out = enrich_quote_item_rows_with_quotation_calc(rows, mats)
        self.assertIn("圆筒侧片", str(out[0].get("calc_note") or ""))
        self.assertIn("压胶", str(out[0].get("calc_note") or ""))

    def test_structure_sentence_fills_ultra_row(self) -> None:
        st = "主料采用ULTRA 200X；圆筒侧片+底片+压胶贴合展开面积，损耗约12%。"
        rows = [{"name": "ULTRA 200X", "calc_note": ""}]
        out = enrich_items_calc_note_from_structure(rows, st)
        cn = str(out[0].get("calc_note") or "")
        self.assertTrue("侧片" in cn or "底片" in cn)

    def test_merge_prefers_longer_sheet_when_structure_subset(self) -> None:
        rows = [
            {
                "name": "ULTRA 200X",
                "calc_note": "圆筒侧片+底片+压胶展开；损耗12%",
            },
        ]
        st = "圆筒侧片+底片"
        out = enrich_items_calc_note_from_structure(rows, st)
        self.assertIn("损耗12%", str(out[0].get("calc_note") or ""))

    def test_bom_style_detection(self) -> None:
        self.assertTrue(calc_note_looks_like_bom_sheet("侧缝14cm+底部圆周37.70cm"))
        self.assertFalse(calc_note_looks_like_bom_sheet("包身侧面设置了垂直防水拉链可直接从侧面打开"))

    def test_prefer_ai_calc_note_over_engine_placeholder(self) -> None:
        self.assertTrue(
            should_prefer_calc_note_incoming(
                "构件分项未载入；用量为 AI 估算，请对照 BOM / 业务员手写公式。",
                "圆筒侧片+底片+压胶展开；损耗约15%",
            )
        )

    def test_keep_existing_bom_when_incoming_weak(self) -> None:
        self.assertFalse(
            should_prefer_calc_note_incoming(
                "侧缝14cm+袋口圆周37.70cm+余量约8%",
                "配件按惯例预估，请以业务核算为准",
            )
        )

    def test_webbing_structure_note_does_not_attach_to_nylon_zipper(self) -> None:
        st = "中下部两道横向仿尼龙织带，总长度约1.5米，其中0.9米用于主带，另有0.6米用于辅带。"
        rows = [
            {"name": "#5尼龙拉链", "calc_note": ""},
            {"name": "仿尼龙织带", "calc_note": ""},
        ]

        out = enrich_items_calc_note_from_structure(rows, st)

        self.assertNotIn("仿尼龙织带", str(out[0].get("calc_note") or ""))
        self.assertIn("仿尼龙织带", str(out[1].get("calc_note") or ""))

    def test_b260169_labeled_structure_notes_bind_correct_rows(self) -> None:
        st = (
            "尺寸：长37cm × 高17cm × 厚12cm\n"
            "YKK拉链：共3条，总长度约0.9米。具体分布为：主仓拉链约0.35米，前袋拉链约0.25米，背部手机暗袋拉链约0.3米。\n"
            "仿尼龙织带：总长度约1.5米。其中约0.9米用于制作肩带主体，另有约0.6米分散用于包体两侧的辅助挂载环及拉链拉片连接绳。\n"
            "普通POM扣具：共3个。包含1个用于肩带快拆的普通插扣，1个用于调节肩带长度的日字扣（调节扣），"
            "以及1个用于连接肩带与包体主体的普通三角连接扣（或称D型环）。"
        )
        rows = [
            {"name": "国产X-PAC", "calc_note": ""},
            {"name": "210D涤纶", "calc_note": ""},
            {"name": "#5尼龙拉链", "calc_note": ""},
            {"name": "YKK防水拉链", "calc_note": ""},
            {"name": "普通拉头", "calc_note": ""},
            {"name": "塑胶标准扣具", "calc_note": ""},
            {"name": "仿尼龙织带", "calc_note": ""},
        ]
        out = enrich_items_calc_note_from_structure(rows, st)
        by_name = {str(r.get("name") or ""): str(r.get("calc_note") or "") for r in out}

        self.assertIn("总长度约1.5米", by_name["仿尼龙织带"])
        self.assertNotIn("总长度约1.5米", by_name["YKK防水拉链"])
        self.assertIn("总长度约0.9米", by_name["YKK防水拉链"])
        self.assertNotIn("总长度约1.5米", by_name["#5尼龙拉链"])
        self.assertIn("共3个", by_name["塑胶标准扣具"])
        self.assertNotIn("主仓", str(by_name.get("普通拉头") or ""))


if __name__ == "__main__":
    unittest.main()
