"""报价单描述清洗与产品图筛选。"""
from __future__ import annotations

import base64
import io
import unittest
import zipfile

from quote_sheet_content import (
    annotate_sheet_embed_image_item,
    brief_customer_description_for_quote_sheet,
    customer_description_for_quote_sheet,
    extract_main_material_for_quote_sheet,
    extract_materials_for_quote_sheet,
    filter_product_image_items,
    is_acceptable_product_image_bytes,
    is_trusted_quote_sheet_image_item,
    looks_like_bag_product_photo,
    looks_like_document_screenshot,
    minimal_png_bytes,
    product_image_score,
    sanitize_quote_sheet_description,
)
from quote_sheet_images import extract_embedded_images_with_rows_from_xlsx_bytes
from quote_sheet_images import merge_product_images_by_priority


def _png_data_url(width: int = 120, height: int = 120) -> str:
    b64 = base64.b64encode(minimal_png_bytes(width, height)).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _trusted_item(**kwargs) -> dict:
    base = {
        "image_role": "product_style",
        "from_sheet_embed": False,
    }
    base.update(kwargs)
    return base


class QuoteSheetContentTest(unittest.TestCase):
    def test_sanitize_removes_problem_description_colon(self) -> None:
        raw = "一、面料\n600D牛津布\n问题一描述：这是内部解析标题\n问题二描述 另一段内部话"
        out = sanitize_quote_sheet_description(raw)
        self.assertIn("600D牛津布", out)
        self.assertNotIn("问题一描述", out)
        self.assertNotIn("内部解析", out)

    def test_brief_desc_product_and_main_material(self) -> None:
        rows = [{"name": "600D牛津布", "spec": "600D牛津布"}]
        out = brief_customer_description_for_quote_sheet(
            product_name="篮球包",
            detail_rows=rows,
        )
        self.assertEqual(out, "主料：600D牛津布")
        self.assertNotRegex(out, r"[。.]$")
        self.assertNotIn("篮球包", out)

    def test_brief_desc_excludes_structure_long_text(self) -> None:
        structure = (
            "问题一描述：内部解析\n前片1片；后片1片\n"
            "系统估算用量\n计算方式：按面积\n辅料清单很长的一段说明"
        )
        out = brief_customer_description_for_quote_sheet(
            product_name="篮球包",
            structure_text=structure,
        )
        self.assertEqual(out, "主料待确认")
        self.assertNotRegex(out, r"[。.]$")
        self.assertNotIn("篮球包", out)
        self.assertNotIn("前片", out)
        self.assertNotIn("系统估算", out)
        self.assertNotIn("计算方式", out)

    def test_brief_desc_structure_short_main_material_line_only(self) -> None:
        out = brief_customer_description_for_quote_sheet(
            product_name="篮球包",
            structure_text="主体面料：210D涤纶\n裁片明细…",
        )
        self.assertIn("主料", out)
        self.assertIn("210D", out)
        self.assertNotIn("篮球包", out)
        self.assertNotIn("裁片", out)

    def test_multiple_main_and_lining_in_desc(self) -> None:
        rows = [
            {"name": "600D牛津布", "spec": "145cm"},
            {"name": "格子尼龙布", "spec": "210D"},
            {"name": "210D里布", "spec": "210D涤纶"},
            {"name": "尼龙拉链", "spec": "5#"},
        ]
        out = brief_customer_description_for_quote_sheet(
            product_name="篮球包",
            detail_rows=rows,
        )
        self.assertIn("主料", out)
        self.assertIn("600D", out)
        self.assertIn("里布", out)
        self.assertIn("210D", out)
        self.assertNotIn("篮球包", out)
        self.assertNotIn("拉链", out)
        self.assertLessEqual(len(out), 101)

    def test_extract_materials_dedupes_and_limits(self) -> None:
        rows = [
            {"name": "600D牛津布", "spec": "600D牛津布"},
            {"name": "外料-600D牛津布", "spec": "600D牛津布"},
            {"name": "210D里布", "spec": "210D"},
            {"name": "190T里布", "spec": "190T"},
        ]
        mats = extract_materials_for_quote_sheet(rows)
        self.assertGreaterEqual(len(mats["main"]), 1)
        self.assertLessEqual(len(mats["main"]), 3)
        self.assertLessEqual(len(mats["lining"]), 2)

    def test_extract_main_material_skips_lining_and_zipper(self) -> None:
        rows = [
            {"name": "210D里布", "spec": "210D"},
            {"name": "尼龙拉链", "spec": "5#"},
            {"name": "600D牛津布", "spec": "600D牛津布"},
        ]
        mat = extract_main_material_for_quote_sheet(rows)
        self.assertEqual(mat, "600D牛津布")

    def test_customer_description_omission_note_when_truncated(self) -> None:
        lines = [f"第{i}行：面料说明与结构细节。" for i in range(30)]
        raw = "\n".join(lines)
        out = customer_description_for_quote_sheet(raw, max_lines=5, max_chars=200)
        self.assertIn("省略", out)
        self.assertLessEqual(len(out.split("\n")), 6)

    def test_reject_large_document_screenshot(self) -> None:
        self.assertTrue(looks_like_document_screenshot(900, 200))
        blob = minimal_png_bytes(900, 200)
        item = _trusted_item(data_base64=base64.b64encode(blob).decode())
        self.assertFalse(is_trusted_quote_sheet_image_item(item))

    def test_reject_sheet_embed_without_role(self) -> None:
        blob = minimal_png_bytes(140, 180)
        item = {
            "data_base64": base64.b64encode(blob).decode(),
            "sheet_row": 5,
            "from_sheet_embed": True,
            "image_source": "sheet_embed",
        }
        self.assertFalse(is_trusted_quote_sheet_image_item(item))
        self.assertEqual(filter_product_image_items([item]), [])

    def test_accept_trusted_product_style(self) -> None:
        blob = minimal_png_bytes(140, 180)
        item = _trusted_item(data_base64=base64.b64encode(blob).decode())
        self.assertTrue(is_trusted_quote_sheet_image_item(item))

    def test_merge_rejects_anonymous_sheet_images(self) -> None:
        url = _png_data_url()
        merged = merge_product_images_by_priority(
            sales_images=[{"row_index": 0, "sheet_row": 0, "data_url": url, "from_sheet_embed": True}],
            product_count=1,
        )
        self.assertEqual(merged, {})

    def test_merge_accepts_agent_product_role(self) -> None:
        url = _png_data_url()
        merged = merge_product_images_by_priority(
            quote_images=[
                {
                    "product_line": 0,
                    "data_url": url,
                    "image_role": "agent_product",
                    "from_agent_product": True,
                }
            ],
            product_count=1,
        )
        self.assertEqual(merged.get(0), url)

    def test_bag_photo_geometry(self) -> None:
        self.assertTrue(looks_like_bag_product_photo(140, 180))
        self.assertFalse(looks_like_bag_product_photo(900, 200))

    def test_annotate_sheet_embed_marks_bag_not_table(self) -> None:
        bag = annotate_sheet_embed_image_item(
            {
                "data_base64": base64.b64encode(minimal_png_bytes(140, 180)).decode(),
                "source_path": "xl/media/image1.png",
            }
        )
        self.assertEqual(bag.get("image_role"), "product_style")
        self.assertTrue(bag.get("product_image"))
        table = annotate_sheet_embed_image_item(
            {
                "data_base64": base64.b64encode(minimal_png_bytes(900, 200)).decode(),
                "source_path": "xl/media/image2.png",
            }
        )
        self.assertFalse(table.get("product_image"))
        self.assertNotEqual(table.get("image_role"), "product_style")

    def test_extract_xlsx_marks_bag_embed(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
            )
            zf.writestr("xl/media/image1.png", minimal_png_bytes(140, 180))
        imgs = extract_embedded_images_with_rows_from_xlsx_bytes(buf.getvalue())
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0].get("image_role"), "product_style")
        self.assertTrue(imgs[0].get("product_image"))

    def test_extract_xlsx_omits_table_screenshot(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
            )
            zf.writestr("xl/media/image1.png", minimal_png_bytes(900, 200))
        imgs = extract_embedded_images_with_rows_from_xlsx_bytes(buf.getvalue())
        self.assertEqual(imgs, [])

    def test_merge_marked_sales_embed_for_single_product(self) -> None:
        b64 = base64.b64encode(minimal_png_bytes(140, 180)).decode()
        item = annotate_sheet_embed_image_item(
            {
                "row_index": 8,
                "sheet_row": 8,
                "data_url": f"data:image/png;base64,{b64}",
                "data_base64": b64,
                "source_path": "xl/media/image1.png",
            }
        )
        merged = merge_product_images_by_priority(sales_images=[item], product_count=1)
        self.assertTrue(str(merged.get(0) or "").startswith("data:image/png"))

    def test_merge_rejects_unmarked_sheet_embed(self) -> None:
        url = _png_data_url(140, 180)
        merged = merge_product_images_by_priority(
            sales_images=[
                {
                    "row_index": 0,
                    "sheet_row": 0,
                    "data_url": url,
                    "from_sheet_embed": True,
                    "image_source": "sheet_embed",
                }
            ],
            product_count=1,
        )
        self.assertEqual(merged, {})

    def test_filter_keeps_trusted_over_document(self) -> None:
        good = _trusted_item(
            data_base64=base64.b64encode(minimal_png_bytes(120, 160)).decode(),
            sheet_row=0,
        )
        bad = _trusted_item(
            data_base64=base64.b64encode(minimal_png_bytes(900, 180)).decode(),
            sheet_row=0,
        )
        kept = filter_product_image_items([bad, good])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["data_base64"], good["data_base64"])

    def test_reject_packaging_label_filename_keywords(self) -> None:
        blob = minimal_png_bytes(140, 180)
        b64 = base64.b64encode(blob).decode()
        for path in (
            "xl/media/packaging_label.png",
            "xl/media/包装图.png",
            "xl/media/hangtag.jpg",
            "xl/media/bank_payment_qrcode.png",
        ):
            ann = annotate_sheet_embed_image_item(
                {"data_base64": b64, "source_path": path},
            )
            self.assertNotEqual(ann.get("image_role"), "product_style")
            self.assertFalse(ann.get("product_image"))

    def test_prefer_bag_keyword_over_packaging_when_both_embedded(self) -> None:
        bag_b64 = base64.b64encode(minimal_png_bytes(140, 180)).decode()
        label_b64 = base64.b64encode(minimal_png_bytes(160, 200)).decode()
        bag = annotate_sheet_embed_image_item(
            {
                "data_base64": bag_b64,
                "source_path": "xl/media/bag_style_main.png",
                "sheet_row": 0,
            }
        )
        label = annotate_sheet_embed_image_item(
            {
                "data_base64": label_b64,
                "source_path": "xl/media/packaging_label.png",
                "sheet_row": 1,
            }
        )
        merged = merge_product_images_by_priority(
            sales_images=[label, bag],
            product_count=1,
        )
        self.assertTrue(str(merged.get(0) or "").startswith("data:image/png"))
        self.assertIn(bag_b64, str(merged.get(0) or ""))

    def test_only_non_product_embeds_yield_empty_map(self) -> None:
        b64 = base64.b64encode(minimal_png_bytes(140, 180)).decode()
        items = [
            annotate_sheet_embed_image_item(
                {
                    "data_base64": b64,
                    "source_path": "xl/media/material_sample.png",
                    "sheet_row": 0,
                }
            ),
            annotate_sheet_embed_image_item(
                {
                    "data_base64": b64,
                    "source_path": "xl/media/label_hangtag.png",
                    "sheet_row": 1,
                }
            ),
        ]
        merged = merge_product_images_by_priority(sales_images=items, product_count=1)
        self.assertEqual(merged, {})

    def test_product_keyword_boosts_score(self) -> None:
        blob = minimal_png_bytes(120, 150)
        b64 = base64.b64encode(blob).decode()
        base = {"data_base64": b64, "user_uploaded": True}
        plain = {**base, "source_path": "xl/media/image2.png"}
        named = {**base, "source_path": "xl/media/bag_main_style.png"}
        self.assertGreater(product_image_score(named), product_image_score(plain))


if __name__ == "__main__":
    unittest.main()
