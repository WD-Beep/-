"""板房排刀用量表展示数据整理。"""
from __future__ import annotations

import math
import unittest

from marker_room_bom_display import (
    build_marker_room_bom_table,
    enrich_quote_marker_room_bom_table,
    is_auxiliary_detail_row,
    is_fabric_detail_row,
)
from piece_area_table import attach_piece_area_calculation


def _basketball_quote() -> dict:
    payload = {
        "product_name": "篮球包",
        "structure_text": "篮球包。成品32×19×45cm。幅宽140CM。前片、后片、底片、侧片2片、拉链弧形盖。",
        "product_size": {"LCM": 32, "WCM": 19, "HCM": 45},
        "detail_rows": [
            {
                "name": "600D 牛津布",
                "piece_part": "前片；后片；底片；侧片（2片）；拉链弧形盖",
                "spec": "140*90CM",
                "usage": "1.13㎡",
                "unit_price": "16元/㎡",
                "amount": 18.08,
            },
            {
                "name": "210D涤纶",
                "piece_part": "前片；后片；底片；侧片（2片）；拉链弧形盖",
                "spec": "152cm",
                "usage": "0.25㎡",
                "usage_ai": True,
                "unit_price": "12元/㎡",
                "amount": 3.14,
            },
            {
                "name": "#5 尼龙拉链",
                "piece_part": "拉链",
                "usage": "1.12米",
                "unit_price": "0.3元/米",
                "amount": 0.34,
            },
        ],
    }
    attach_piece_area_calculation(payload)
    return payload


class MarkerRoomBomDisplayTest(unittest.TestCase):
    def test_piece_rows_rendered_for_fabric(self) -> None:
        table = build_marker_room_bom_table(_basketball_quote())
        self.assertGreater(len(table["fabric_groups"]), 0)
        fabric_rows = [r for r in table["rows"] if r.get("is_piece_row")]
        self.assertGreaterEqual(len(fabric_rows), 3)
        first_group = table["fabric_groups"][0]
        self.assertEqual(first_group["rows"][0]["material_name"], "600D 牛津布")
        self.assertEqual(first_group["rows"][1].get("material_name"), "")

    def test_material_header_only_once_per_group(self) -> None:
        table = build_marker_room_bom_table(_basketball_quote())
        for grp in table["fabric_groups"]:
            names = [r["material_name"] for r in grp["rows"] if str(r.get("material_name") or "").strip()]
            self.assertEqual(len(names), 1)
            totals = [
                r["total_marker_usage"]
                for r in grp["rows"]
                if str(r.get("total_marker_usage") or "").strip()
            ]
            self.assertEqual(len(totals), 1)

    def test_no_null_tokens_in_cells(self) -> None:
        table = build_marker_room_bom_table(_basketball_quote())
        blob = str(table)
        for bad in ("null", "undefined", "NaN", "__SHARED_BODY_M2__"):
            self.assertNotIn(bad, blob)

    def test_unsplit_shows_pending_not_fake_dims(self) -> None:
        quote = {
            "product_name": "测试",
            "detail_rows": [{"name": "600D牛津布", "usage": "1㎡", "unit_price": "10元/㎡", "amount": 10}],
        }
        table = build_marker_room_bom_table(quote)
        grp = table["fabric_groups"][0]
        self.assertIn(grp["split_status"], ("未拆分", "待核"))
        row = grp["rows"][0]
        self.assertIn(row["piece_name"], ("未拆分", "待核"))

    def test_same_piece_set_label_for_main_and_lining(self) -> None:
        table = build_marker_room_bom_table(_basketball_quote())
        keys = {g["piece_set_key"] for g in table["fabric_groups"] if g["piece_set_key"]}
        self.assertEqual(len(keys), 1)
        labels = [g["piece_set_label"] for g in table["fabric_groups"]]
        self.assertTrue(all("前片" in lb for lb in labels))

    def test_zipper_not_split_into_pieces(self) -> None:
        table = build_marker_room_bom_table(_basketball_quote())
        aux = table["auxiliary_rows"]
        self.assertTrue(any("拉链" in str(r.get("material_name")) for r in aux))
        piece_zip = [
            r for r in table["rows"] if r.get("is_piece_row") and "拉链" in str(r.get("piece_name"))
        ]
        self.assertFalse(any("尼龙拉链" in str(r.get("material_name")) for r in table["fabric_groups"]))

    def test_enrich_attaches_on_quote(self) -> None:
        quote = _basketball_quote()
        enrich_quote_marker_room_bom_table(quote)
        self.assertIn("marker_room_bom_table", quote)
        self.assertTrue(quote["marker_room_bom_table"]["rows"])

    def test_fabric_vs_auxiliary_classification(self) -> None:
        self.assertTrue(is_fabric_detail_row({"name": "600D牛津布"}))
        self.assertTrue(is_auxiliary_detail_row({"name": "#5 尼龙拉链"}))

    def test_numeric_cells_finite(self) -> None:
        table = build_marker_room_bom_table(_basketball_quote())
        for row in table["rows"]:
            for key in ("single_marker_usage", "amount", "qty"):
                val = str(row.get(key) or "")
                if re_num := __import__("re").search(r"([\d.]+)", val):
                    n = float(re_num.group(1))
                    self.assertTrue(math.isfinite(n))


if __name__ == "__main__":
    unittest.main()
