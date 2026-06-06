"""裁片面积核算归档字段测试。"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from piece_area_table import (
    _is_complete_piece_area_calc,
    _parse_lwh_from_text,
    _should_rebuild_piece_area,
    attach_piece_area_calculation,
    build_piece_area_calculation,
    enrich_quote_piece_area_on_read,
    normalize_piece_area_display,
)

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "quotes.db"


class PieceAreaTableTests(unittest.TestCase):
    def test_parse_lwh_without_space_after_chengpin(self) -> None:
        got = _parse_lwh_from_text("主料按包身外包络≈1.133㎡（成品32x19x45cm，展开系数1.32量级）")
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got, (32.0, 19.0, 45.0))

    def test_parse_lwh_labeled_height_length_width(self) -> None:
        got = _parse_lwh_from_text("高度 : 45 cm，长度 : 32 cm，宽度 : 19 cm")
        self.assertEqual(got, (32.0, 19.0, 45.0))

    def test_partial_explicit_with_dims_uses_geometry(self) -> None:
        """篮球包场景：局部拉链盖 explicit 不能替代完整几何裁片。"""
        payload = {
            "product_name": "篮球包",
            "detail_rows": [
                {
                    "name": "600D 牛津布",
                    "spec": "140*90CM",
                    "calc_method": "主料按包身外包络≈1.133㎡（成品32x19x45cm，展开系数1.32量级）",
                },
                {
                    "name": "#5尼龙拉链",
                    "calc_note": "拉链盖估算 200cm²",
                },
            ],
            "items": [
                {"line_no": 1, "name": "600D 牛津布", "spec": "140*90CM", "calc_note": ""},
                {"line_no": 2, "name": "#5尼龙拉链", "calc_note": "高度 : 45 cm，长度 : 32 cm，宽度 : 19 cm"},
            ],
            "piece_area_calculation": {
                "rows": [
                    {"piece": "拉链盖", "size_text": "估算", "total_area_cm2": 200, "is_total": False},
                    {"piece": "拉链盖", "size_text": "估算", "total_area_cm2": 200, "is_total": False},
                    {"piece": "合计", "total_area_cm2": 400, "is_total": True},
                ]
            },
        }
        calc = build_piece_area_calculation(payload)
        self.assertIsNotNone(calc)
        assert calc is not None
        pieces = [r["piece"] for r in calc["rows"] if not r.get("is_total")]
        self.assertIn("前片", pieces)
        self.assertIn("后片", pieces)
        self.assertIn("底片", pieces)
        self.assertIn("侧片（2片）", pieces)
        self.assertTrue(any("拉链" in p for p in pieces))
        self.assertEqual(pieces.count("拉链盖"), 0)
        self.assertIn("32×19×45cm", calc["product_size_label"])
        notes = " ".join(calc.get("notes") or [])
        self.assertIn("推理待核", notes)
        self.assertIn("加损耗", notes)
        self.assertIn("门幅140cm", notes)
        self.assertIn("换算码", notes)

    def test_should_rebuild_incomplete_archive(self) -> None:
        bad = {"rows": [{"piece": "拉链盖", "total_area_cm2": 200}, {"piece": "合计", "is_total": True}]}
        self.assertTrue(_should_rebuild_piece_area(bad))
        self.assertTrue(_should_rebuild_piece_area(None))

    def test_derive_from_product_size_10x10x22(self) -> None:
        payload = {
            "product_size": {"LCM": 10, "WCM": 10, "HCM": 22},
            "structure_text_snapshot": "主仓拉链开口；损耗15%",
            "items": [{"name": "600D牛津布", "spec": "140*90CM"}],
        }
        calc = build_piece_area_calculation(payload)
        self.assertIsNotNone(calc)
        assert calc is not None
        self.assertEqual(calc["total_area_cm2"], 1180.0)
        self.assertTrue(_is_complete_piece_area_calc(calc))

    def test_enrich_merges_db_items_with_detail_rows(self) -> None:
        quote = {
            "detail_rows": [
                {
                    "name": "600D 牛津布",
                    "calc_method": "主料按包身外包络≈1.133㎡（成品32x19x45cm，展开系数1.32量级）",
                    "spec": "140*90CM",
                }
            ],
            "piece_area_calculation": {
                "rows": [
                    {"piece": "拉链盖", "total_area_cm2": 200},
                    {"piece": "合计", "total_area_cm2": 200, "is_total": True},
                ]
            },
        }
        items_db = [{"line_no": 1, "name": "600D 牛津布", "spec": "140*90CM", "calc_note": ""}]
        enrich_quote_piece_area_on_read(quote, items_db)
        self.assertTrue(_is_complete_piece_area_calc(quote.get("piece_area_calculation")))

    def test_no_dims_returns_none(self) -> None:
        self.assertIsNone(build_piece_area_calculation({"items": [{"name": "拉链"}]}))

    def test_side_piece_qty_two_pieces_not_group(self) -> None:
        payload = {
            "product_name": "篮球包",
            "product_size": {"LCM": 32, "WCM": 19, "HCM": 45},
            "structure_text_snapshot": "高度45cm，长度32cm，宽度19cm",
            "items": [{"name": "600D牛津布", "spec": "140*90CM"}],
        }
        calc = build_piece_area_calculation(payload)
        self.assertIsNotNone(calc)
        calc = normalize_piece_area_display(calc)
        assert calc is not None
        side = next(r for r in calc["rows"] if "侧片" in str(r.get("piece") or ""))
        self.assertEqual(side.get("qty_text"), "2片")
        self.assertNotIn("组", str(side.get("qty_text") or ""))
        self.assertEqual(side.get("size_text"), "45×19")
        self.assertEqual(float(side.get("unit_area_cm2")), 855.0)
        self.assertEqual(float(side.get("total_area_cm2")), 1710.0)


@unittest.skipUnless(DB_PATH.is_file(), "quotes.db not present")
class PieceAreaSqliteQuotesTests(unittest.TestCase):
    def _load(self, name_hint: str) -> tuple[dict, list[dict]] | None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            qrow = conn.execute(
                "SELECT quote_uid, latest_version_no FROM quotes "
                "WHERE product_name LIKE ? ORDER BY latest_saved_at DESC LIMIT 1",
                (f"%{name_hint}%",),
            ).fetchone()
            if not qrow:
                return None
            uid = str(qrow["quote_uid"])
            ver = int(qrow["latest_version_no"] or 1)
            vrow = conn.execute(
                "SELECT quote_json FROM quote_versions WHERE quote_uid=? AND version_no=?",
                (uid, ver),
            ).fetchone()
            items = conn.execute(
                "SELECT line_no,name,spec,usage,unit_price,amount,calc_note FROM quote_items "
                "WHERE quote_uid=? AND version_no=? ORDER BY line_no",
                (uid, ver),
            ).fetchall()
            quote = json.loads(vrow["quote_json"] or "{}")
            return quote, [dict(r) for r in items]
        finally:
            conn.close()

    def test_basketball_bag_sqlite_complete(self) -> None:
        got = self._load("篮球")
        if got is None:
            self.skipTest("no basketball quote in sqlite")
        quote, items_db = got
        enrich_quote_piece_area_on_read(quote, items_db)
        pac = quote.get("piece_area_calculation")
        self.assertTrue(_is_complete_piece_area_calc(pac if isinstance(pac, dict) else None))
        assert isinstance(pac, dict)
        pieces = [r["piece"] for r in pac["rows"] if not r.get("is_total")]
        self.assertTrue(any("拉链" in p for p in pieces))
        notes = " ".join(pac.get("notes") or [])
        self.assertIn("门幅140cm", notes)

    def test_cosmetic_bag_sqlite_complete(self) -> None:
        got = self._load("化妆")
        if got is None:
            self.skipTest("no cosmetic bag quote in sqlite")
        quote, items_db = got
        enrich_quote_piece_area_on_read(quote, items_db)
        pac = quote.get("piece_area_calculation")
        self.assertTrue(_is_complete_piece_area_calc(pac if isinstance(pac, dict) else None))


if __name__ == "__main__":
    unittest.main()
