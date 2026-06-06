import unittest

from structure_usage import apply_structure_usage_hints


class StructureGeometryDerivationTest(unittest.TestCase):
    def test_main_fabric_linear_yards_from_shell_and_roll_width(self) -> None:
        st = "便当午餐包。\n幅宽145CM。\n长22cm,宽12cm，高20cm"
        rows = [
            {
                "name": "FJ-114 水洗尼龙布",
                "usage": "1码",
                "unit_price": "12/码",
                "amount": 0,
            },
        ]
        meta = apply_structure_usage_hints(rows, st, product_size={})
        self.assertGreater(meta.get("geometry_matched") or 0, 0)
        self.assertIn("码", rows[0]["usage"])
        v = rows[0]["usage"].replace("码", "").strip()
        self.assertGreater(float(v), 0.05)

    def test_bento_default_hardware_piece_counts(self) -> None:
        st = (
            "便当袋。\n长22厘米，宽12厘米，高20厘米。\n"
            "口字扣与结构说明见附件。"
        )
        rows = [
            {"name": "口字扣", "usage": "1套", "unit_price": "0.25/个"},
            {"name": "日字扣", "usage": "1套", "unit_price": "0.5"},
            {"name": "圆心弹簧圈口扣", "usage": "1套", "unit_price": "0.65元/个"},
        ]
        apply_structure_usage_hints(rows, st, product_size={})
        self.assertEqual(rows[0]["usage"], "4个")
        self.assertEqual(rows[1]["usage"], "1个")
        self.assertEqual(rows[2]["usage"], "2个")

    def test_explicit_hardware_overrides_defaults(self) -> None:
        st = "便当包。口字扣6个。\n长22厘米，宽12厘米，高20厘米"
        rows = [{"name": "矩形扣", "usage": "1套", "unit_price": "1元/个"}]
        apply_structure_usage_hints(rows, st, product_size={})
        self.assertEqual(rows[0]["usage"], "6个")

    def test_ultra_style_main_fabric_geometry_over_placeholder_yard(self) -> None:
        """主料名含 ULTRA 时应识别为主线面料并替换占位「1码」，并写入可追溯 calc_note."""
        st = "双肩背包。\n幅宽145CM。\n长24cm,宽14cm，高48cm"
        rows = [
            {
                "name": "ULTRA 200X",
                "usage": "1码",
                "unit_price": "420",
                "amount": 0,
            },
        ]
        meta = apply_structure_usage_hints(rows, st, product_size={})
        self.assertGreater(meta.get("geometry_matched") or 0, 0)
        self.assertNotEqual(rows[0]["usage"].strip(), "1码")
        cn = str(rows[0].get("calc_note") or "")
        self.assertIn("外包络", cn)
        self.assertIn("门幅", cn)
        self.assertNotIn("系统推算", cn)
        self.assertNotIn("未计排版损耗", cn)

    def test_skip_when_real_usage_present(self) -> None:
        st = "长22cm,宽12cm，高20cm"
        rows = [{"name": "FJ面料", "usage": "1.310码²", "unit_price": "14元/码²"}]
        before = rows[0]["usage"]
        apply_structure_usage_hints(rows, st, product_size={})
        self.assertEqual(rows[0]["usage"], before)

    def test_small_sling_bag_uses_business_floor_not_raw_shell(self) -> None:
        st = (
            "斜挎包。成品尺寸：长 21cm x 高 12cm x 厚 6cm。"
            "主面料：210D 再生尼龙，成本参考15元/码；"
            "内衬面料：300D涤纶，成本参考12元/码；"
            "肩带主要参考图二的肩带。"
        )
        rows = [
            {"name": "210D再生尼龙", "usage": "1码", "unit_price": "15元/码", "amount": 0},
            {"name": "300D涤纶", "usage": "-", "unit_price": "10.5元/㎡", "amount": 0},
            {"name": "YKK防水拉链", "usage": "-", "unit_price": "7.5元/码", "amount": 0},
            {"name": "仿尼龙织带", "spec": "织带约130-150cm长", "usage": "-", "unit_price": "0.9元/米", "amount": 0},
        ]
        apply_structure_usage_hints(rows, st, product_size={"LCM": 21, "WCM": 12, "HCM": 6})

        self.assertEqual(rows[0]["usage"], "0.32码")
        self.assertEqual(rows[1]["usage"], "0.32㎡")
        self.assertEqual(rows[2]["usage"], "0.25码")
        self.assertEqual(rows[3]["usage"], "1.55米")
        self.assertIn("最低取量", str(rows[0].get("calc_note") or ""))


if __name__ == "__main__":
    unittest.main()
