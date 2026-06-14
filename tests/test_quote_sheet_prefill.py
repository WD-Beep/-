"""报价单预填与表格嵌入图提取。"""
from __future__ import annotations

import base64
import io
import unittest
import uuid
import zipfile
from xml.etree import ElementTree as ET

import quote_sheet_images as qsi
from quote_sheet_content import minimal_png_bytes, product_like_png_bytes
from quote_sheet_images import (
    extract_embedded_images_with_rows_from_xlsx_bytes,
    merge_product_images_by_priority,
    normalize_sheet_images_to_product_map,
    persist_sheet_product_images,
)
from quote_sheet_content import annotate_sheet_embed_image_item
from quote_sheet_prefill import _rows_from_quote, build_quote_sheet_prefill_payload
from quote_upload_storage import save_quote_calculation
from test_db_isolation import (
    cleanup_isolated_quote_db,
    mount_isolated_quote_db,
    restore_quote_db,
)

XDR_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _png_data_url(width: int = 120, height: int = 120) -> str:
    b64 = base64.b64encode(minimal_png_bytes(width, height)).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _minimal_xlsx_with_png() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        zf.writestr("xl/media/image1.png", product_like_png_bytes(120, 140))
    return buf.getvalue()


def _xlsx_with_drawing_anchors(row_numbers: list[int]) -> bytes:
    ET.register_namespace("xdr", XDR_NS)
    ET.register_namespace("a", A_NS)
    ET.register_namespace("r", R_NS)

    anchors_xml: list[str] = []
    rels_xml: list[str] = []
    for idx, row_no in enumerate(row_numbers, start=1):
        rid = f"rId{idx}"
        anchors_xml.append(
            f'<xdr:oneCellAnchor xmlns:xdr="{XDR_NS}" xmlns:a="{A_NS}" xmlns:r="{R_NS}">'
            f"<xdr:from><xdr:col>1</xdr:col><xdr:row>{row_no}</xdr:row></xdr:from>"
            f'<xdr:ext cx="914400" cy="914400"/>'
            f'<xdr:pic>'
            f"<xdr:nvPicPr><xdr:cNvPr id=\"{idx}\" name=\"Picture {idx}\"/></xdr:nvPicPr>"
            f"<xdr:blipFill><a:blip r:embed=\"{rid}\"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>"
            f"</xdr:pic><xdr:clientData/></xdr:oneCellAnchor>"
        )
        rels_xml.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            f'Target="../media/image{idx}.png"/>'
        )

    drawing = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<xdr:wsDr xmlns:xdr="{XDR_NS}" xmlns:a="{A_NS}" xmlns:r="{R_NS}">'
        f"{''.join(anchors_xml)}</xdr:wsDr>"
    )
    drawing_rels = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">{"".join(rels_xml)}</Relationships>'
    )
    content_types = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Types xmlns="{CT_NS}">'
        f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f'<Default Extension="xml" ContentType="application/xml"/>'
        f'<Default Extension="png" ContentType="image/png"/>'
        f'<Override PartName="/xl/drawings/drawing1.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        f"</Types>"
    )
    sheet_rels = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
        f'Target="../drawings/drawing1.xml"/>'
        f"</Relationships>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("xl/drawings/drawing1.xml", drawing)
        zf.writestr("xl/drawings/_rels/drawing1.xml.rels", drawing_rels)
        zf.writestr("xl/worksheets/_rels/sheet1.xml.rels", sheet_rels)
        for idx in range(1, len(row_numbers) + 1):
            zf.writestr(
                f"xl/media/image{idx}.png",
                product_like_png_bytes(120 + idx * 12, 140 + idx * 10),
            )
    return buf.getvalue()


class QuoteSheetPrefillTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()

    def tearDown(self) -> None:
        restore_quote_db(self._saved_db)
        cleanup_isolated_quote_db(self._root)

    def test_extract_embedded_images_fallback(self) -> None:
        raw = _minimal_xlsx_with_png()
        imgs = extract_embedded_images_with_rows_from_xlsx_bytes(raw)
        self.assertGreaterEqual(len(imgs), 1)
        self.assertTrue(str(imgs[0].get("data_base64") or ""))

    def test_drawing_anchor_rows_preserved(self) -> None:
        raw = _xlsx_with_drawing_anchors([5, 12])
        imgs = extract_embedded_images_with_rows_from_xlsx_bytes(raw)
        rows = sorted(int(i.get("sheet_row", i.get("row_index"))) for i in imgs)
        self.assertEqual(rows, [5, 12])

    def test_normalize_sheet_embed_not_used_in_merge(self) -> None:
        sheet_images = [
            {
                "row_index": 5,
                "sheet_row": 5,
                "data_url": _png_data_url(),
                "from_sheet_embed": True,
                "image_source": "sheet_embed",
            },
        ]
        mapped = merge_product_images_by_priority(
            sales_images=sheet_images,
            product_count=1,
        )
        self.assertEqual(mapped, {})

    def test_normalize_trusted_admin_role_images(self) -> None:
        url = _png_data_url(128, 148)
        sheet_images = [
            {
                "row_index": 8,
                "sheet_row": 8,
                "data_url": url,
                "image_role": "product_style",
                "from_sheet_embed": False,
            },
        ]
        mapped = merge_product_images_by_priority(
            admin_images=sheet_images,
            product_count=1,
            product_source_rows=[8],
        )
        self.assertTrue(str(mapped.get(0) or "").startswith("data:image/png;base64,"))

    def test_image_priority_agent_over_sheet(self) -> None:
        url_a, url_d = _png_data_url(), _png_data_url(136, 164)
        merged = merge_product_images_by_priority(
            sales_images=[
                {
                    "row_index": 0,
                    "sheet_row": 0,
                    "data_url": url_a,
                    "from_sheet_embed": True,
                }
            ],
            quote_images=[
                {
                    "row_index": 0,
                    "product_line": 0,
                    "data_url": url_d,
                    "image_role": "agent_product",
                    "from_agent_product": True,
                }
            ],
            product_count=1,
        )
        self.assertEqual(merged.get(0), url_d)

    def test_prefill_desc_brief_from_main_material_not_structure_long_text(self) -> None:
        quote = {
            "product_name": "篮球包",
            "structure_text_snapshot": (
                "基本规格尺寸\n主体面料：600D牛津布\n辅料清单很长…\n"
                "前片1片；后片1片；系统估算用量\n计算方式：按裁片面积"
            ),
            "tiers": [
                {"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00"},
                {"quantity": 500, "exw_price": 9.5, "exw_price_text": "9.50"},
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(len(rows), 1)
        desc = rows[0]["desc"]
        self.assertIn("600D", desc)
        self.assertIn("主料", desc)
        self.assertNotIn("篮球包", desc)
        self.assertNotIn("前片", desc)
        self.assertNotIn("系统估算", desc)
        self.assertNotIn("计算方式", desc)
        self.assertNotIn("辅料清单", desc)

    def test_prefill_desc_from_detail_rows_prefers_main_fabric(self) -> None:
        quote = {
            "product_name": "篮球包",
            "detail_rows": [
                {"name": "600D牛津布", "spec": "600D牛津布", "usage": "0.83码"},
                {"name": "尼龙拉链", "spec": "5#", "usage": "1条"},
            ],
            "structure_text_snapshot": "很长的结构说明不应进入报价单描述列",
            "tiers": [{"quantity": 500, "exw_price": 12.5, "exw_price_text": "12.50"}],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(rows[0]["desc"], "主料：600D牛津布")
        self.assertNotIn("篮球包", rows[0]["desc"])

    def test_build_prefill_payload_desc_brief(self) -> None:
        sales_uid = f"sales-{uuid.uuid4().hex[:8]}"
        series_uid = f"series-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="demo.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "quote_series_uid": series_uid,
                "product_name": "篮球包",
                "structure_text": "主体面料：600D牛津布\n很长的结构说明不应进入报价单描述列",
                "tiers": [{"quantity": 500, "exw_price": 12.5, "exw_price_text": "12.50"}],
            },
            sales_user_id=sales_uid,
        )
        payload = build_quote_sheet_prefill_payload(series_uid, sales_uid, source="record")
        self.assertIsNotNone(payload)
        assert payload is not None
        rows = payload.get("rows") or []
        self.assertEqual(len(rows), 1)
        desc = str(rows[0].get("desc") or "")
        self.assertIn("600D", desc)
        self.assertIn("主料", desc)
        self.assertNotIn("篮球包", desc)
        self.assertNotIn("很长的结构说明", desc)
        self.assertEqual(rows[0].get("qty"), "500")
        self.assertEqual(rows[0].get("price"), "12.5")

    def test_three_tiers_yield_one_row_using_preferred_500_tier(self) -> None:
        quote = {
            "product_name": "篮球包",
            "tiers": [
                {
                    "quantity": 300,
                    "quantity_text": "300件",
                    "exw_price": 10.0,
                    "exw_price_text": "10.00",
                },
                {
                    "quantity": 500,
                    "quantity_text": "500件",
                    "exw_price": 9.5,
                    "exw_price_text": "9.50",
                },
                {
                    "quantity": 1000,
                    "quantity_text": "1000件",
                    "exw_price": 9.0,
                    "exw_price_text": "9.00",
                },
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "篮球包")
        self.assertEqual(rows[0]["qty"], "500")
        self.assertEqual(rows[0]["price"], "9.5")
        self.assertEqual(rows[0]["total"], "4750")

    def test_tier_unit_price_from_cost_before_margin_per_piece(self) -> None:
        quote = {
            "product_name": "篮球包",
            "tiers": [
                {
                    "quantity": 500,
                    "cost_before_margin": 17.0,
                    "margin_rate": 0.35,
                }
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(rows[0]["qty"], "500")
        self.assertEqual(rows[0]["price"], "26.2")
        self.assertEqual(rows[0]["total"], "13076.9")

    def test_size_excludes_piece_names_when_piece_area_present(self) -> None:
        quote = {
            "product_name": "篮球包",
            "product_size": {"length": 32, "width": 19, "height": 45},
            "piece_area_calculation": {
                "rows": [
                    {"piece": "前片", "size_text": "32×22", "qty_text": "1"},
                    {"piece": "后片", "size_text": "32×22", "qty_text": "1"},
                ]
            },
            "detail_rows": [
                {
                    "name": "600D牛津布",
                    "spec": "600D牛津布",
                    "usage": "0.83码",
                    "unit_price": "9元/码",
                    "amount": 7.47,
                }
            ],
            "tiers": [{"quantity": 500, "exw_price": 12.5, "exw_price_text": "12.50"}],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(len(rows), 1)
        self.assertIn("32", rows[0]["size"])
        self.assertIn("45", rows[0]["size"])
        self.assertNotIn("前片", rows[0]["size"])
        self.assertNotIn("后片", rows[0]["size"])
        self.assertEqual(rows[0]["price"], "12.5")

    def test_unit_price_from_checkpoint_when_tier_lacks_exw(self) -> None:
        quote = {
            "product_name": "篮球包",
            "tiers": [{"quantity": 500}],
            "sales_sheet_checkpoints": [
                {"quantity": 500, "computed_exw_quote_pc": 18.2, "computed_exw_quote_text": "18.20"},
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(rows[0]["qty"], "500")
        self.assertEqual(rows[0]["price"], "18.2")

    def test_pack_strips_system_estimate_still_has_unit_price(self) -> None:
        quote = {
            "product_name": "篮球包",
            "detail_rows": [
                {
                    "name": "外纸箱/包装费（系统估算）",
                    "spec": "系统估算",
                    "usage": "1个",
                    "unit_price": "2元/个",
                    "amount": 2.0,
                }
            ],
            "tiers": [{"quantity": 500, "exw_price": 15.0, "exw_price_text": "15.00"}],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(rows[0]["pack"], "1个")
        self.assertNotIn("系统估算", rows[0]["pack"])
        self.assertEqual(rows[0]["price"], "15")
        self.assertEqual(rows[0]["total"], "7500")

    def test_pack_defaults_when_only_internal_usage(self) -> None:
        quote = {
            "product_name": "篮球包",
            "detail_rows": [
                {
                    "name": "包装袋",
                    "spec": "-",
                    "usage": "系统估算",
                    "unit_price": "1元/个",
                    "amount": 1.0,
                }
            ],
            "tiers": [{"quantity": 500, "exw_price": 10.0, "exw_price_text": "10.00"}],
        }
        rows = _rows_from_quote(quote, {})
        pack = rows[0]["pack"]
        self.assertEqual(pack, "")
        self.assertNotIn("系统估算", pack)

    def test_pack_internal_duplicate_slash_empty(self) -> None:
        from quote_sheet_prefill import sanitize_customer_pack_display

        self.assertEqual(sanitize_customer_pack_display("系统估算/系统估算"), "")
        self.assertEqual(sanitize_customer_pack_display("系统估算 / AI估算"), "")

    def test_fob_quote_suggests_english_export(self) -> None:
        from quote_sheet_prefill import is_fob_quote_for_sheet

        self.assertTrue(
            is_fob_quote_for_sheet(
                {
                    "include_fob": True,
                    "price_type": "FOB深圳",
                    "tiers": [{"quantity": 500, "fob_price": 91.69, "exw_price": 87.69}],
                }
            )
        )
        self.assertFalse(is_fob_quote_for_sheet({"include_fob": False, "price_type": "出厂"}))

    def test_include_fob_alone_triggers_fob_sheet(self) -> None:
        from quote_sheet_prefill import is_fob_quote_for_sheet

        self.assertTrue(is_fob_quote_for_sheet({"include_fob": True}))
        self.assertFalse(is_fob_quote_for_sheet({"include_fob": False}))

    def test_fob_usd_derived_when_only_exw_and_addon_present(self) -> None:
        quote = {
            "product_name": "篮球包",
            "include_fob": True,
            "usd_cny_rate": 7.15,
            "fob_yuan_per_pc": 4,
            "tiers": [
                {
                    "quantity": 500,
                    "exw_price": 85.19,
                    "exw_price_text": "85.19元",
                }
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(rows[0]["price"], "85.2")
        self.assertEqual(rows[0]["fob_price"], "89.2")
        self.assertEqual(rows[0]["fob_price_usd"], "12.5")
        self.assertEqual(rows[0]["fob_total_usd"], "6237.1")

    def test_prefill_row_carries_tier_fob_without_overwriting_exw(self) -> None:
        quote = {
            "product_name": "篮球包",
            "include_fob": True,
            "tiers": [
                {
                    "quantity": 500,
                    "exw_price": 87.69,
                    "exw_price_text": "87.69元",
                    "fob_price": 91.69,
                    "fob_price_text": "91.69元",
                    "fob_price_usd": 12.81,
                    "fob_price_usd_text": "$12.81",
                }
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(rows[0]["price"], "87.7")
        self.assertEqual(rows[0]["fob_price"], "91.7")
        self.assertEqual(rows[0]["fob_price_usd"], "12.8")
        self.assertIn("12.8", rows[0]["fob_price_usd_text"])
        self.assertEqual(rows[0]["fob_total"], "45845")
        self.assertEqual(rows[0]["total"], "43845")

    def test_prefers_500_qty_tier_with_exw_price(self) -> None:
        quote = {
            "product_name": "篮球包",
            "tiers": [
                {"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00元"},
                {"quantity": 500, "exw_price": 12.5, "exw_price_text": "12.50元"},
                {"quantity": 1000, "exw_price": 9.0, "exw_price_text": "9.00元"},
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(rows[0]["qty"], "500")
        self.assertEqual(rows[0]["price"], "12.5")

    def test_selected_tier_index_used_for_single_product_row(self) -> None:
        quote = {
            "product_name": "篮球包",
            "selected_tier_index": 1,
            "tiers": [
                {"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00"},
                {"quantity": 500, "exw_price": 9.5, "exw_price_text": "9.50"},
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qty"], "500")
        self.assertEqual(rows[0]["price"], "9.5")

    def test_prefill_row_includes_taxed_price_when_tier_has_field(self) -> None:
        quote = {
            "product_name": "斜挎包",
            "tiers": [
                {
                    "quantity": 500,
                    "exw_price": 86.67,
                    "exw_price_text": "86.67",
                    "taxed_price": 97.94,
                    "taxed_price_text": "97.94元",
                }
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["taxed_price"], "97.9")

    def test_multi_size_variants_still_multiple_rows(self) -> None:
        quote = {
            "product_name": "篮球包",
            "size_variants": [
                {
                    "label": "大号",
                    "quote_result": {
                        "tiers": [{"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00"}],
                    },
                },
                {
                    "label": "小号",
                    "quote_result": {
                        "tiers": [{"quantity": 300, "exw_price": 11.0, "exw_price_text": "11.00"}],
                    },
                },
            ],
        }
        rows = _rows_from_quote(quote, {})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["price"], "10")
        self.assertEqual(rows[1]["price"], "11")

    def test_single_product_row_image_from_marked_excel_embed(self) -> None:
        b64 = base64.b64encode(product_like_png_bytes(140, 180)).decode()
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
        rows = _rows_from_quote(
            {
                "product_name": "篮球包",
                "tiers": [{"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00"}],
            },
            merged,
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(str(rows[0].get("image_data_url") or "").startswith("data:image/png"))

    def test_single_product_no_image_when_only_packaging_embeds(self) -> None:
        b64 = base64.b64encode(minimal_png_bytes(140, 180)).decode()
        items = [
            annotate_sheet_embed_image_item(
                {
                    "data_base64": b64,
                    "source_path": "xl/media/packaging_label.png",
                    "sheet_row": 0,
                }
            ),
            annotate_sheet_embed_image_item(
                {
                    "data_base64": b64,
                    "source_path": "xl/media/material_chart.png",
                    "sheet_row": 1,
                }
            ),
        ]
        merged = merge_product_images_by_priority(sales_images=items, product_count=1)
        rows = _rows_from_quote(
            {"product_name": "篮球包", "tiers": [{"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00"}]},
            merged,
        )
        self.assertEqual(rows[0].get("image_data_url"), "")

    def test_single_product_no_image_when_only_table_screenshot_in_xlsx(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
            )
            zf.writestr("xl/media/image1.png", minimal_png_bytes(900, 200))
        extracted = extract_embedded_images_with_rows_from_xlsx_bytes(buf.getvalue())
        self.assertEqual(extracted, [])
        merged = merge_product_images_by_priority(sales_images=extracted, product_count=1)
        rows = _rows_from_quote(
            {"product_name": "篮球包", "tiers": [{"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00"}]},
            merged,
        )
        self.assertEqual(rows[0].get("image_data_url"), "")

    def test_single_product_image_maps_to_row_zero(self) -> None:
        url = _png_data_url(128, 148)
        rows = _rows_from_quote(
            {"product_name": "篮球包", "tiers": [{"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00"}]},
            {8: url},
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(str(rows[0].get("image_data_url") or "").startswith("data:image/png"))

    def test_build_prefill_includes_trusted_product_image(self) -> None:
        sales_uid = f"sales-{uuid.uuid4().hex[:8]}"
        series_uid = f"series-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="demo.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "quote_series_uid": series_uid,
                "product_name": "测试篮球包",
                "material_total": 10.0,
                "tiers": [{"quantity": 300, "exw_price": 10.0, "exw_price_text": "10.00"}],
                "product_row_images": [
                    {
                        "product_line": 0,
                        "data_url": _png_data_url(),
                        "image_role": "product_style",
                        "product_image": True,
                    }
                ],
            },
            sales_user_id=sales_uid,
        )
        payload = build_quote_sheet_prefill_payload(series_uid, sales_uid, source="record")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertTrue(payload.get("ok"))
        rows = payload.get("rows") or []
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(str(rows[0].get("image_data_url") or "").startswith("data:"))


class QuoteSheetImagePersistTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()
        qsi.PRODUCT_IMAGES_ROOT = self._root / "quote_product_images"

    def tearDown(self) -> None:
        restore_quote_db(self._saved_db)
        cleanup_isolated_quote_db(self._root)

    def test_persist_sheet_images_marks_bag_embed_for_quote_sheet(self) -> None:
        uid = f"series-{uuid.uuid4().hex[:8]}"
        raw = _minimal_xlsx_with_png()
        entries = persist_sheet_product_images(uid, "sales_sheet", raw, original_name="a.xlsx")
        self.assertGreaterEqual(len(entries), 1)
        self.assertTrue(entries[0].get("from_sheet_embed"))
        self.assertEqual(entries[0].get("image_role"), "product_style")
        self.assertTrue(entries[0].get("product_image"))
        merged = merge_product_images_by_priority(sales_images=entries, product_count=1)
        self.assertTrue(str(merged.get(0) or "").startswith("data:image/png"))

    def test_persist_anchor_marked_bag_embeds_merge_by_product_count(self) -> None:
        raw = _xlsx_with_drawing_anchors([5, 12])
        extracted = extract_embedded_images_with_rows_from_xlsx_bytes(raw)
        self.assertEqual(sorted(int(i["sheet_row"]) for i in extracted), [5, 12])
        self.assertTrue(all(i.get("product_image") for i in extracted))
        uid = f"series-{uuid.uuid4().hex[:8]}"
        entries = persist_sheet_product_images(uid, "admin_calculated", raw, original_name="calc.xlsx")
        self.assertGreaterEqual(len(entries), 1)
        merged = merge_product_images_by_priority(sales_images=entries, product_count=2)
        self.assertGreaterEqual(len(merged), 1)


if __name__ == "__main__":
    unittest.main()
