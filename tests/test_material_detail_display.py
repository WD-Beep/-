"""物料明细展示：裁片/部位、规格、用量三列互不串字段。"""

from __future__ import annotations



import copy

import re

import unittest



from material_detail_display import (

    _looks_like_piece_manifest,

    enrich_quote_material_detail_display,

)

from material_spec_usage_enricher import enrich_material_rows

from quote_engine import calculate_quote



_DIM_RE = re.compile(r"\d+(?:\.\d+)?\s*[×xX*]\s*\d+")

_MANIFEST_SAMPLE = "前片 19×45；后片 19×45；底片 32×19；侧片（2片）45×19×2；拉链弧形盖 估算"





def _basketball_quote() -> dict:

    payload = {

        "product_name": "篮球包",

        "structure_text": "高度45cm，长度32cm，宽度19cm；双侧袋",

        "product_size": {"height": 45, "length": 32, "width": 19},

        "quantities": [500],

        "gross_margin_rate": 0.35,

        "items": [

            {

                "name": "600D牛津布",

                "spec": "140*90CM",

                "usage": "0.83码",

                "unit_price": "9元/码",

                "amount": 7.47,

                "source": "kb",

            },

            {

                "name": "210D涤纶",

                "spec": "152cm",

                "usage": "0.25㎡",

                "unit_price": "8元/㎡",

                "amount": 2.0,

                "source": "kb",

            },

            {

                "name": "#5尼龙拉链",

                "spec": "/",

                "usage": "1.12米",

                "unit_price": "3元/米",

                "amount": 3.36,

                "source": "kb",

            },

            {

                "name": "背垫（推理待核）",

                "spec": _MANIFEST_SAMPLE,

                "usage": "1套",

                "unit_price": "2元/个",

                "amount": 2.0,

                "source": "ai",

            },

            {

                "name": "提手（推理待核）",

                "spec": _MANIFEST_SAMPLE,

                "usage": "1套",

                "unit_price": "2元/个",

                "amount": 2.0,

                "source": "ai",

            },

            {

                "name": "隔层（推理待核）",

                "spec": _MANIFEST_SAMPLE,

                "usage": "1套",

                "unit_price": "2元/个",

                "amount": 2.0,

                "source": "ai",

            },

            {

                "name": "工艺费（推理待核）",

                "spec": _MANIFEST_SAMPLE,

                "usage": "1套",

                "unit_price": "2元/单位",

                "amount": 2.0,

                "source": "ai",

            },

            {

                "name": "外纸箱/包装费（系统估算）",

                "spec": _MANIFEST_SAMPLE,

                "usage": "1个",

                "unit_price": "2元/个",

                "amount": 2.0,

                "source": "ai",

            },

        ],

    }

    result = calculate_quote(payload)

    result["detail_rows"] = copy.deepcopy(payload["items"])

    for i, row in enumerate(result["detail_rows"], start=1):

        row["line_no"] = i

    result["structure_text"] = payload["structure_text"]

    result["product_size"] = payload["product_size"]

    result["piece_area_calculation"] = {

        "size_text": "32×19×45cm",

        "rows": [

            {"piece": "前片", "size_text": "19×45", "qty_text": "1片", "unit_area_cm2": 855, "total_area_cm2": 855},

            {"piece": "后片", "size_text": "19×45", "qty_text": "1片", "unit_area_cm2": 855, "total_area_cm2": 855},

            {"piece": "底片", "size_text": "32×19", "qty_text": "1片", "unit_area_cm2": 608, "total_area_cm2": 608},

            {

                "piece": "侧片（2片）",

                "size_text": "45×19",

                "qty_text": "2片",

                "unit_area_cm2": 855,

                "total_area_cm2": 1710,

            },

            {"piece": "拉链弧形盖", "size_text": "估算", "qty_text": "1片", "unit_area_cm2": 200, "total_area_cm2": 200},

            {"piece": "合计", "size_text": "", "qty_text": "", "is_total": True, "total_area_cm2": 4228},

        ],

    }

    return result





class MaterialDetailDisplayTest(unittest.TestCase):

    def test_looks_like_piece_manifest(self) -> None:

        self.assertTrue(_looks_like_piece_manifest(_MANIFEST_SAMPLE))

        self.assertFalse(_looks_like_piece_manifest("140*90CM"))

        self.assertFalse(_looks_like_piece_manifest("推理待核"))



    def test_inference_rows_spec_not_piece_manifest(self) -> None:

        quote = _basketball_quote()

        amounts = {r["name"]: float(r["amount"]) for r in quote["detail_rows"]}

        enrich_quote_material_detail_display(quote)

        expected_parts = {
            "背垫": "背垫",
            "提手": "提手",
            "隔层": "隔层",
            "工艺费": "工艺费",
        }
        for key, part_label in expected_parts.items():
            row = next(r for r in quote["detail_rows"] if key in r["name"])
            spec = str(row.get("spec") or "")
            self.assertNotRegex(spec, _DIM_RE, key)
            self.assertFalse(_looks_like_piece_manifest(spec), key)
            self.assertIn("推理待核", spec, key)
            self.assertEqual(row["piece_part"], part_label, key)
            self.assertAlmostEqual(float(row["amount"]), amounts[row["name"]], places=2)



    def test_fabric_keeps_material_spec_without_manifest(self) -> None:

        quote = _basketball_quote()

        enrich_quote_material_detail_display(quote)

        ox = next(r for r in quote["detail_rows"] if "牛津" in r["name"])

        spec = str(ox.get("spec") or "")

        self.assertFalse(_looks_like_piece_manifest(spec))

        self.assertRegex(spec, r"140|600|牛津", spec)

        part = str(ox.get("piece_part") or "")

        self.assertIn("前片", part)

        self.assertNotRegex(part, _DIM_RE)



    def test_zipper_spec_and_usage_separate(self) -> None:

        quote = _basketball_quote()

        enrich_quote_material_detail_display(quote)

        z = next(r for r in quote["detail_rows"] if "尼龙拉链" in r["name"])

        self.assertNotIn("/", str(z.get("spec") or ""))

        self.assertIn("拉链", str(z.get("spec") or ""))

        self.assertIn("米", str(z.get("usage") or ""))

        self.assertFalse(_looks_like_piece_manifest(str(z.get("spec") or "")))



    def test_packaging_spec_system_estimate(self) -> None:

        quote = _basketball_quote()

        enrich_quote_material_detail_display(quote)

        pack = next(r for r in quote["detail_rows"] if "包装" in r["name"])

        spec = str(pack.get("spec") or "")

        self.assertIn("系统估算", spec)

        self.assertFalse(_looks_like_piece_manifest(spec))

        self.assertIn("包装", str(pack.get("piece_part") or ""))



    def test_amounts_unchanged_after_display(self) -> None:

        quote = _basketball_quote()

        before = sum(float(r["amount"]) for r in quote["detail_rows"])

        enrich_material_rows(quote["detail_rows"], structure_text=quote.get("structure_text") or "")

        enrich_quote_material_detail_display(quote)

        after = sum(float(r["amount"]) for r in quote["detail_rows"])

        self.assertAlmostEqual(before, after, places=2)





if __name__ == "__main__":

    unittest.main()

