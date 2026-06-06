"""展示数字格式化：最多 1 位小数。"""
from __future__ import annotations

import unittest

from display_number_format import (
    format_display_money_cny,
    format_display_number,
    format_numbers_in_display_text,
)
from quote_engine import format_money


class DisplayNumberFormatTest(unittest.TestCase):
    def test_format_display_number(self) -> None:
        self.assertEqual(format_display_number(15.0), "15")
        self.assertEqual(format_display_number(12.5579), "12.6")
        self.assertEqual(format_display_number(0.3), "0.3")
        self.assertEqual(format_display_number(2.3901), "2.4")

    def test_format_numbers_in_display_text(self) -> None:
        self.assertEqual(format_numbers_in_display_text("12.5579元/㎡"), "12.6元/㎡")
        self.assertEqual(format_numbers_in_display_text("0.3000元/条"), "0.3元/条")
        self.assertEqual(format_numbers_in_display_text("15.000元/条"), "15元/条")
        self.assertEqual(format_numbers_in_display_text("0.19㎡"), "0.2㎡")

    def test_format_money_uses_one_decimal(self) -> None:
        self.assertEqual(format_money(20.5), "20.5元")
        self.assertEqual(format_display_money_cny(2.39), "2.4元")


if __name__ == "__main__":
    unittest.main()
