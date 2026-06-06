from __future__ import annotations

import unittest

from demand_parser import _extract_materials_from_section_c, _split_name_spec_inline
from structure_usage import piece_count_usage_from_cell_note, usage_hint_from_bracket


class PieceCountCellUsageTest(unittest.TestCase):
    def test_parenthesis_extracts_three_pcs_for_puller_cell(self) -> None:
        self.assertEqual(piece_count_usage_from_cell_note("3个"), "3PCS")

    def test_usage_hint_from_note_only(self) -> None:
        self.assertEqual(usage_hint_from_bracket("2PCS", ""), "2PCS")

    def test_section_c拉头_maps_quoted_usage(self) -> None:
        section_c = {"拉头类型": "5#YKK拉头-短柄 (3个)"}
        mats = _extract_materials_from_section_c(section_c)
        self.assertEqual(len(mats), 1)
        self.assertEqual(mats[0].quoted_usage, "3PCS")
        self.assertEqual(mats[0].name.strip(), "5#YKK拉头-短柄")

    def test_split_spec_decimal_cm_not_eight_cm(self) -> None:
        _n, spec, *_ = _split_name_spec_inline("彩色圆绳提手，约0.8cm粗")
        self.assertEqual(spec, "0.8cm")

    def test_shoulder_length_column_locks_usage(self) -> None:
        section_c = {
            "肩带/织带类型": "彩色圆绳提手，约0.8cm粗",
            "肩带长度cm": "30cm",
        }
        mats = _extract_materials_from_section_c(section_c)
        self.assertEqual(len(mats), 1)
        self.assertEqual(mats[0].spec, "0.8cm")
        self.assertEqual(mats[0].quoted_usage, "30cm")


if __name__ == "__main__":
    unittest.main()
