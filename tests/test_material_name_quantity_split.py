"""材料名内嵌数量拆分与用量修正。"""
from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

try:
    from openpyxl import Workbook
except Exception:  # pragma: no cover
    Workbook = None

from demand_parser import Material, _normalize_materials_embedded_quantity, parse_demand_from_rows
from kb_data_quality import KB_ACTION_AUTO, KB_ACTION_REVIEW, judge_kb_insert_candidate
from material_row_validity import apply_embedded_quantity_to_row
from price_admin_store import upsert_confirmed_price_override
from quote_engine import parse_items
from sheet_parser import material_name_has_embedded_quantity, split_quantity_from_material_name


class MaterialNameQuantitySplitTest(unittest.TestCase):
    def test_prefix_quantity_split(self) -> None:
        name, usage, src = split_quantity_from_material_name("4个PU皮拉片")
        self.assertEqual(name, "PU皮拉片")
        self.assertEqual(usage, "4个")
        self.assertEqual(src, "name_prefix")

    def test_suffix_quantity_split(self) -> None:
        name, usage, src = split_quantity_from_material_name("D扣2个")
        self.assertEqual(name, "D扣")
        self.assertEqual(usage, "2个")
        self.assertEqual(src, "name_suffix")

        name2, usage2, src2 = split_quantity_from_material_name("日字扣1个")
        self.assertEqual(name2, "日字扣")
        self.assertEqual(usage2, "1个")
        self.assertEqual(src2, "name_suffix")

    def test_middle_and_asterisk_quantity_split(self) -> None:
        name, usage, src = split_quantity_from_material_name("旋转钩2个扣具")
        self.assertEqual(name, "旋转钩扣具")
        self.assertEqual(usage, "2个")
        self.assertEqual(src, "name_middle")

        name2, usage2, src2 = split_quantity_from_material_name("黑色拉头*1")
        self.assertEqual(name2, "黑色拉头")
        self.assertEqual(usage2, "1个")
        self.assertEqual(src2, "name_asterisk")

    def test_demand_section_c_strips_asterisk_from_name(self) -> None:
        rows = [
            ["C. 材料与配件（标准名/编码）"],
            ["拉头类型", "拉片"],
            ["黑色拉头*1", "黑色常规拉片*1"],
        ]
        out = parse_demand_from_rows(rows)
        names = [m.name for m in out.materials]
        self.assertIn("黑色拉头", names)
        self.assertNotIn("黑色拉头*1", names)
        puller = next(m for m in out.materials if m.name == "黑色拉头")
        self.assertEqual(puller.quoted_usage, "1个")
        self.assertEqual(puller.quantity_source, "name_asterisk")

    def test_wrong_usage_corrected_from_name_for_quote(self) -> None:
        row = apply_embedded_quantity_to_row(
            {
                "name": "4个PU皮拉片",
                "spec": "个",
                "usage": "1个",
                "unit_price": "0.3元/个",
                "amount": 0.3,
                "kb_hit": True,
            }
        )
        self.assertEqual(row["name"], "PU皮拉片")
        self.assertEqual(row["usage"], "4个")
        self.assertEqual(row.get("quantity_source"), "name_prefix")
        items = parse_items([row])
        self.assertEqual(items[0].unit_price, "0.3元/个")
        self.assertAlmostEqual(items[0].amount, 1.2, places=2)

    @unittest.skipIf(Workbook is None, "openpyxl is required")
    def test_dirty_name_with_qty_cannot_auto_insert_or_override(self) -> None:
        root = Path(__file__).resolve().parents[1] / "data" / f"_tmp_qty_name_{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            verdict = judge_kb_insert_candidate("4个PU皮拉片", "个", "0.3元/个")
            self.assertEqual(verdict.action, KB_ACTION_REVIEW)
            self.assertTrue(material_name_has_embedded_quantity("4个PU皮拉片"))
            with self.assertRaises(ValueError):
                upsert_confirmed_price_override(
                    material_name="4个PU皮拉片",
                    spec="个",
                    price="0.3元/个",
                    override_path=root / "price_overrides.jsonl",
                )
            clean_verdict = judge_kb_insert_candidate("PU皮拉片", "个", "0.3元/个")
            self.assertEqual(clean_verdict.action, KB_ACTION_AUTO)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_normalize_materials_helper(self) -> None:
        mats = [Material(role="拉片", name="4个PU皮拉片", spec="个", quoted_usage="1个")]
        _normalize_materials_embedded_quantity(mats)
        self.assertEqual(mats[0].name, "PU皮拉片")
        self.assertEqual(mats[0].quoted_usage, "4个")
        self.assertEqual(mats[0].quantity_source, "name_prefix")


if __name__ == "__main__":
    unittest.main()
