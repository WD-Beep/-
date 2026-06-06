from __future__ import annotations

import unittest

from material_row_dedupe import (
    drop_duplicate_structure_narrative_rows,
    drop_structure_duplicate_markup_rows,
    drop_zero_subtotal_merge_placeholder_rows,
)


class StructureDuplicateDropTest(unittest.TestCase):
    def test_drops_calc_note_merge_marker(self) -> None:
        items = [
            {"name": "ULTRA 200X", "calc_note": "主料展开"},
            {
                "name": "包身主体是ULTRA 200X面料",
                "calc_note": "【已并入第1行ULTRA 200X主料】结构说明不重复计价",
                "amount": 0.0,
            },
            {"name": "拉链", "calc_note": "袋口长度"},
        ]
        out = drop_structure_duplicate_markup_rows(items)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "ULTRA 200X")
        self.assertEqual(out[1]["name"], "拉链")

    def test_keeps_all_when_every_row_would_drop(self) -> None:
        lone = [{"name": "x", "calc_note": "已并入第2行主料"}]
        out = drop_structure_duplicate_markup_rows(lone)
        self.assertEqual(out, lone)

    def test_narrative_xpac_row_dropped_when_keeper_has_amount(self) -> None:
        items = [
            {"name": "VX21辅料", "amount": 84.0},
            {
                "name": "背板和肩带采用进口 X-PAC VX21",
                "amount": 388.8,
            },
        ]
        out = drop_duplicate_structure_narrative_rows(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "VX21辅料")

    def test_narrative_kept_when_only_it_has_amount(self) -> None:
        items = [
            {"name": "VX21辅料", "amount": 0.0},
            {"name": "背板和肩带采用进口 X-PAC VX21", "amount": 120.0},
        ]
        out = drop_duplicate_structure_narrative_rows(items)
        self.assertEqual(len(out), 2)

    def test_drops_zero_row_with_merge_into_first_line_note(self) -> None:
        items = [
            {"name": "1.43oz DCF", "amount": 33.49},
            {
                "name": "主面料DCF",
                "calc_note": "该行与首行DCF外料重复，已合并计入首行；禁止双计主面料",
                "amount": 0.0,
            },
            {"name": "绳子", "amount": 1.0},
        ]
        out = drop_zero_subtotal_merge_placeholder_rows(items)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "1.43oz DCF")

    def test_keeps_merge_note_row_when_amount_positive(self) -> None:
        items = [
            {"name": "A", "amount": 10.0},
            {"name": "主面料DCF", "calc_note": "已合并计入首行；禁止双计", "amount": 5.0},
        ]
        out = drop_zero_subtotal_merge_placeholder_rows(items)
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
