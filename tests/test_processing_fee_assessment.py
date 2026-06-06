import unittest

from demand_parser import resolve_demand_processing_fee


class ProcessingFeeAssessmentTest(unittest.TestCase):
    def test_standard_label_can_move_to_complex_low_band(self) -> None:
        sections = {
            "B": {
                "产品类型": "背包",
                "产品名称/款号": "商务出行袋",
                "L(cm)": "45",
                "W(cm)": "30",
                "H(cm)": "17",
                "结构复杂度": "标准",
            },
            "C": {
                "外料(标准名/编码)": "600D塔丝隆格子布",
                "里料(标准名/编码)": "210D涤纶",
                "拉链类型": "#5尼龙拉链+YKK防水拉链",
                "拉头类型": "普通",
                "扣具等级": "塑胶标准",
                "肩带/织带类型": "仿尼龙织带",
                "包边带": "涤纶包边带（细纹）",
            },
            "D": {"LOGO方式(多选)": "丝印"},
        }
        structure = (
            "尺寸：长45cm × 宽30cm × 厚17cm。"
            "风格：180°全开口行李舱式设计。"
            "结构概述：顶部提手、背部双肩垫带、正面多功能绑带、底部加固防磨、内部分层收纳。"
            "主仓YKK长拉链实现180°全开，内部一侧设有网眼拉链袋，内部底层设有衣物固定绑带。"
            "侧面配有侧收缩扣带，中下部两道横向仿尼龙织带，顶部标识区丝印。"
        )

        fee, locked, rule = resolve_demand_processing_fee(sections, structure)

        self.assertEqual(rule, "structure_assessment")
        self.assertFalse(locked)
        self.assertGreaterEqual(fee or 0, 21.0)
        self.assertLessEqual(fee or 0, 26.0)

    def test_simple_structure_stays_low(self) -> None:
        sections = {
            "B": {"产品类型": "束口袋", "结构复杂度": "简单"},
            "C": {"外料(标准名/编码)": "210D涤纶", "拉链类型": ""},
            "D": {},
        }

        fee, locked, rule = resolve_demand_processing_fee(
            sections,
            "基础裁片，简单车缝，无内袋无特殊工艺。",
        )

        self.assertEqual(rule, "structure_assessment")
        self.assertFalse(locked)
        self.assertLessEqual(fee or 0, 12.0)

    def test_small_sling_bag_does_not_jump_to_backpack_labor_band(self) -> None:
        sections = {
            "B": {
                "产品类型": "其他",
                "产品名称/款号": "斜挎包",
                "L(cm)": "21",
                "W(cm)": "12",
                "H(cm)": "6",
                "结构复杂度": "标准",
            },
            "C": {
                "外料(标准名/编码)": "210D再生尼龙",
                "里料(标准名/编码)": "300D涤纶",
                "拉链类型": "#5尼龙拉链+YKK防水拉链",
                "扣具等级": "塑胶标准",
                "肩带/织带类型": "仿尼龙织带",
            },
            "D": {"LOGO方式(多选)": "丝印"},
        }
        structure = (
            "成品尺寸：长21cm x 高12cm x 厚6cm。"
            "YKK防水拉链，配注塑拉头，前幅丝印LOGO。"
            "肩带含D型环、龙虾扣和可调节织带，包身侧边缝挂耳。"
        )

        fee, locked, rule = resolve_demand_processing_fee(sections, structure)

        self.assertEqual(rule, "structure_assessment")
        self.assertFalse(locked)
        self.assertLessEqual(fee or 0, 14.0)


if __name__ == "__main__":
    unittest.main()
