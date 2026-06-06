from __future__ import annotations

import unittest

from material_row_dedupe import collapse_fabric_reverse_use_shadow_rows


class FabricReverseCollapseTest(unittest.TestCase):
    def test_merges_shadow_into_main_dch(self) -> None:
        items = [
            {"name": "3.2oz DCH", "spec": "黑色", "amount": 95.0},
            {
                "name": "前幅等部位使用3.2oz DCH面料反用（450元/码）说明很长",
                "spec": "-",
                "usage": "1码",
                "unit_price": "450元/码",
                "amount": 450.0,
            },
        ]
        out = collapse_fabric_reverse_use_shadow_rows(items)
        self.assertEqual(len(out), 1)
        spec = str(out[0].get("spec") or "")
        self.assertIn("并入工艺备注", spec)
        self.assertIn("反用", spec)

    def test_shadow_can_appear_before_main_row(self) -> None:
        items = [
            {
                "name": "悬用3.2oz DCH的面料反用来做面",
                "spec": "-",
                "amount": 1,
            },
            {"name": "3.2oz DCH", "spec": "", "amount": 20},
        ]
        out = collapse_fabric_reverse_use_shadow_rows(items)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
