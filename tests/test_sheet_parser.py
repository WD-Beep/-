import base64
import io
import unittest
import zipfile

from sheet_parser import SheetParseError, parse_sheet_items_from_payload


def to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def build_xlsx_multi_sheet_bytes() -> bytes:
    workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Summary" sheetId="1" r:id="rId1"/>
    <sheet name="材料与配件" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>
"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
                Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
                Target="worksheets/sheet2.xml"/>
</Relationships>
"""
    sheet1_xml = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>A. 客户与报价信息</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>客户名称</t></is></c></row>
  </sheetData>
</worksheet>
"""
    sheet2_xml = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>物料名称</t></is></c>
      <c r="B1" t="inlineStr"><is><t>规格</t></is></c>
      <c r="C1" t="inlineStr"><is><t>用量</t></is></c>
      <c r="D1" t="inlineStr"><is><t>单价参考</t></is></c>
      <c r="E1" t="inlineStr"><is><t>小计</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>1.43oz DCF</t></is></c>
      <c r="B2" t="inlineStr"><is><t>1.43oz</t></is></c>
      <c r="C2" t="inlineStr"><is><t>2.1码</t></is></c>
      <c r="D2" t="inlineStr"><is><t>96元/码</t></is></c>
      <c r="E2"><v>201.6</v></c>
    </row>
  </sheetData>
</worksheet>
"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet1_xml)
        archive.writestr("xl/worksheets/sheet2.xml", sheet2_xml)
    return buffer.getvalue()


class SheetParserTest(unittest.TestCase):
    def test_parse_xls_reads_sheet_and_prefers_material_sheet(self):
        try:
            import xlwt as _xlwt  # type: ignore[import-untyped]
        except ImportError:
            self.skipTest("xlwt not installed")
        wb = _xlwt.Workbook()
        ws0 = wb.add_sheet("Sheet1")
        ws0.write(0, 0, "misc")
        ws1 = wb.add_sheet("材料清单")
        ws1.write(0, 0, "物料名称")
        ws1.write(0, 1, "规格")
        ws1.write(0, 2, "用量")
        ws1.write(0, 3, "单价参考")
        ws1.write(1, 0, "210D尼龙")
        ws1.write(1, 1, "黑色")
        ws1.write(1, 2, "1.2码")
        ws1.write(1, 3, "10元/码")
        buf = io.BytesIO()
        wb.save(buf)
        blob = buf.getvalue()

        from sheet_parser import parse_rows_from_bytes, rows_to_items

        parsed, _ = parse_rows_from_bytes(file_name="t.xls", file_bytes=blob)
        self.assertEqual(parsed.sheet_name, "材料清单")
        extraction = rows_to_items(parsed.rows, start_row=None)
        names = [str(r.get("name", "")) for r in extraction.items]
        self.assertTrue(any("210D尼龙" in n for n in names))

    def test_xlsx_disguised_as_xls_hint(self):
        xlsx_blob = build_xlsx_multi_sheet_bytes()
        from sheet_parser import SheetParseError, parse_rows_from_bytes

        with self.assertRaises(SheetParseError) as ctx:
            parse_rows_from_bytes(file_name="fake.xls", file_bytes=xlsx_blob)
        self.assertIn("xlsx", str(ctx.exception).lower())

    def test_fixed_upload_layout_keeps_calc_note_detail(self):
        csv_text = (
            "项目,计算方式,报价用量,单价,金额/个\n"
            "DCF外料,圆筒侧片+底片+压胶条 同面积再加15%损耗,0.0744码,450元/码,33.49\n"
        )
        payload = {"name": "calc_note.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        self.assertEqual(result["item_count"], 1)
        row = result["items"][0]
        self.assertEqual(row["name"], "DCF外料")
        blob = str(row.get("calc_note") or "") + str(row.get("spec") or "")
        self.assertIn("底片", blob)

    def test_filter_non_material_rows_from_csv(self):
        csv_text = (
            "业务报价需求表（用于AI自动报价）- 中文 V1.0,,,,\n"
            "填写说明：黄色标题为分组,,,,\n"
            "A. 客户与报价信息,,,,\n"
            "客户名称,customer_name,ACME,,\n"
            "B. 产品规格,,,,\n"
            "产品类型,product_type,backpack,,\n"
            "C. 材料与配件,,,,\n"
            "物料名称,规格,用量,单价参考,小计\n"
            "外料,210D,1.3码,80元/码,104\n"
            "里料,210D,1.2码,5元/码,6\n"
            "拉链,5#,1条,是,7\n"
            "城市,customer_name,country,否,1\n"
            "D. 工艺,,,,\n"
            "热切,边缘处理,1处,3元/处,3\n"
            "F. 数量阶梯,,,,\n"
            "数量1,qty1,300,是,\n"
        )
        payload = {"name": "complex.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)

        names = [row["name"] for row in result["items"]]
        self.assertEqual(names, ["外料", "里料", "热切"])
        self.assertNotIn("A", names)
        self.assertNotIn("B", names)
        self.assertNotIn("C", names)
        self.assertGreaterEqual(result["filtered_count"], 8)

    def test_choose_material_sheet_when_multiple_sheets_exist(self):
        payload = {
            "name": "multi.xlsx",
            "content_base64": to_base64(build_xlsx_multi_sheet_bytes()),
        }
        result = parse_sheet_items_from_payload(payload)

        self.assertEqual(result["sheet_name"], "材料与配件")
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(result["items"][0]["name"], "1.43oz DCF")

    def test_fallback_keeps_material_rows_without_unit_price(self):
        csv_text = (
            "A. 客户与报价信息,,,,\n"
            "客户名称,customer_name,ACME,,\n"
            "C组 材料与配件,,,,\n"
            "外料,outer_material,1.43oz DCF,,\n"
            "布标,label_material,woven label,,\n"
            "城市,customer_city,上海,,\n"
            "F. 数量阶梯,,,,\n"
            "数量1,qty1,300,,\n"
        )
        payload = {"name": "fallback.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)

        names = [row["name"] for row in result["items"]]
        self.assertEqual(names, ["外料", "布标"])
        self.assertNotIn("城市", names)

    def test_skip_column_label_header_row(self):
        csv_text = (
            "C. 材料与配件,,,,\n"
            "外料(标准名/编码),外料颜色,里料(标准名/编码),里料颜色,\n"
            "外料,210D,1.3码,80元/码,104\n"
        )
        payload = {"name": "mapping.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)

        names = [row["name"] for row in result["items"]]
        self.assertEqual(names, ["外料"])
        self.assertNotIn("外料(标准名/编码)", names)

    def test_raise_when_only_column_label_rows(self):
        csv_text = (
            "C. 材料与配件,,,,\n"
            "外料(标准名/编码),外料颜色,里料(标准名/编码),里料颜色,\n"
            "LOGO方式,刺绣/丝印,数量阶梯,300/500/1000,\n"
        )
        payload = {"name": "bad.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        with self.assertRaises(SheetParseError):
            parse_sheet_items_from_payload(payload)

    def test_extract_material_from_label_value_pairs(self):
        csv_text = (
            "A. 客户与报价信息,,,,\n"
            "客户名称,customer_name,ACME,,\n"
            "C. 材料与配件,,,,\n"
            "外料(标准名/编码),outer_material,1.43oz DCF,外料颜色,black,\n"
            "里料(标准名/编码),lining_material,210D涤纶,里料颜色,grey,\n"
            "D. 工艺,,,,\n"
            "LOGO方式,丝印,数量阶梯,300/500/1000,\n"
        )
        payload = {"name": "pair.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        names = [row["name"] for row in result["items"]]
        self.assertIn("1.43oz DCF", names)
        self.assertIn("210D涤纶", names)
        self.assertNotIn("黑色", names)

    def test_extract_multi_material_pairs_in_one_row(self):
        csv_text = (
            "C. 材料与配件,,,,,,\n"
            "外料(标准名/编码),outer_material,1.43oz DCF,里料(标准名/编码),lining_material,210D涤纶\n"
        )
        payload = {"name": "pair_multi.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        names = [row["name"] for row in result["items"]]
        self.assertIn("1.43oz DCF", names)
        self.assertIn("210D涤纶", names)

    def test_extract_english_material_label_value_pairs(self):
        csv_text = (
            "C. Materials and Accessories,,,,\n"
            "outer_material_name/code,outer_material,1.43oz DCF,outer_color,black,\n"
            "lining_material_name/code,lining_material,210d nylon ripstop,lining_color,grey,\n"
        )
        payload = {"name": "pair_en.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        names = [row["name"] for row in result["items"]]
        self.assertIn("1.43oz DCF", names)
        self.assertIn("210d nylon ripstop", names)
        self.assertNotIn("black", names)

    def test_merge_table_and_pair_extraction_results(self):
        csv_text = (
            "A. 客户与报价信息,,,,\n"
            "产品名称,product_name,城市日行 28L,,\n"
            "C. 材料与配件,,,,\n"
            "加固/辅料,尼龙补强片,1处,3元/处,3\n"
            "外料(标准名/编码),outer_material,1.43oz DCF,外料颜色,black,\n"
            "里料(标准名/编码),lining_material,210D涤纶,里料颜色,grey,\n"
        )
        payload = {"name": "mixed.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        names = [row["name"] for row in result["items"]]
        self.assertIn("加固/辅料", names)
        self.assertIn("1.43oz DCF", names)
        self.assertIn("210D涤纶", names)
        self.assertEqual(result["sheet_product_name"], "城市日行 28L")

    def test_block_description_sentence_from_material_value(self):
        csv_text = (
            "C. Materials and Accessories,,,,\n"
            "outer_material_name/code,outer_material,1.43oz DCF,outer_color,black,\n"
            "lining_material_name/code,lining_material,\u5916\u4fa7\u4f7f\u7528\u4e3b\u9762\u6599,lining_color,grey,\n"
        )
        payload = {"name": "desc_block.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        names = [row["name"] for row in result["items"]]
        self.assertIn("1.43oz DCF", names)
        self.assertNotIn("\u5916\u4fa7\u4f7f\u7528\u4e3b\u9762\u6599", names)

    def test_split_concatenated_material_name_into_candidates(self):
        csv_text = (
            "\u7269\u6599\u540d\u79f0,\u89c4\u683c/\u7528\u91cf,\u5355\u4ef7\u53c2\u8003,\u5c0f\u8ba1\n"
            "1\u5bf8\u63d2\u62631\u4e2a6\u5206\u63d2\u62632\u4e2a\u731d\u9f3b\u62631\u4e2a,1\u5bf8,0.6\u5143/\u4e2a,0.6\n"
        )
        payload = {"name": "split_concat.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        names = [row["name"] for row in result["items"]]
        self.assertIn("1\u5bf8\u63d2\u62631\u4e2a", names)
        self.assertIn("6\u5206\u63d2\u62632\u4e2a", names)
        self.assertIn("\u731d\u9f3b\u62631\u4e2a", names)
        self.assertAlmostEqual(sum(float(row["amount"]) for row in result["items"]), 0.6, places=2)

    def test_keep_normal_single_material_row_unaffected(self):
        csv_text = (
            "\u7269\u6599\u540d\u79f0,\u89c4\u683c/\u7528\u91cf,\u5355\u4ef7\u53c2\u8003,\u5c0f\u8ba1\n"
            "\u666e\u901a\u62c9\u5934,5#,0.3\u5143/\u4e2a,0.3\n"
        )
        payload = {"name": "single_ok.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(result["items"][0]["name"], "\u666e\u901a\u62c9\u5934")
        self.assertAlmostEqual(float(result["items"][0]["amount"]), 0.3, places=2)

    def test_mixed_table_does_not_introduce_duplicate_rows(self):
        csv_text = (
            "C. Materials and Accessories,,,,\n"
            "\u7269\u6599\u540d\u79f0,\u89c4\u683c/\u7528\u91cf,\u5355\u4ef7\u53c2\u8003,\u5c0f\u8ba1,\n"
            "1\u5bf8\u63d2\u62631\u4e2a6\u5206\u63d2\u62632\u4e2a,1\u5bf8,0.6\u5143/\u4e2a,0.6,\n"
            "outer_material_name/code,outer_material,1\u5bf8\u63d2\u62631\u4e2a,outer_color,black,\n"
        )
        payload = {"name": "mixed_dedupe.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        names = [row["name"] for row in result["items"]]
        self.assertEqual(len(names), len(set(names)))

    def test_reject_invalid_base64(self):
        with self.assertRaises(SheetParseError):
            parse_sheet_items_from_payload({"name": "items.csv", "content_base64": "###"})

    def test_fixed_columns_dedup_and_noise_filter(self):
        csv_text = (
            "填写说明,,,,\n"
            "物料名称,规格/用量,单价参考,小计\n"
            "3号尼龙拉链,1条,0.35元/条,0.35\n"
            "0.35元/条,1条,0.35元/条,0.35\n"
            "3号尼龙拉链,1条,0.35元/条,0.35\n"
            "PE包装，纸箱外箱,1个,1.5元/个,1.5\n"
            "图片,报价资料B260128 / -, -, -\n"
            "1.5元/个,1个,1.5元/个,1.5\n"
            "PE包装，纸箱外箱,1个,1.5元/个,1.5\n"
        )
        payload = {"name": "clean.csv", "content_base64": to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)

        self.assertEqual(result["item_count"], 2)
        self.assertEqual([row["name"] for row in result["items"]], ["3号尼龙拉链", "PE包装，纸箱外箱"])
        self.assertAlmostEqual(sum(float(row["amount"]) for row in result["items"]), 1.85, places=2)
        self.assertGreaterEqual(result["filtered_count"], 5)

    def test_simple_bom_template_splits_and_filters_description(self) -> None:
        from simple_bom_parser import parse_simple_bom_from_rows

        rows = [
            ["图片", "报价资料", "", "", ""],
            ["", "类型", "说明", "宽幅", "单价"],
            ["", "尺寸", "长150mm", "", ""],
            ["", "辅料", "1寸插扣 1个 6分插扣 2个 猪鼻扣 1个", "", "0.6元/个"],
            ["", "肩带", "肩带 (内侧为黑色网布", "", ""],
            ["", "面料", "外侧使用主面料)", "", ""],
            ["", "拉链", "普通拉链", "", "0.3元/条"],
        ]
        result = parse_simple_bom_from_rows(rows, file_name="B260174.xlsx")
        names = [m.name for m in result.materials]
        self.assertIn("1寸插扣 1个", names)
        self.assertIn("6分插扣 2个", names)
        self.assertIn("猪鼻扣 1个", names)
        self.assertNotIn("1寸插扣 1个 6分插扣 2个 猪鼻扣 1个", names)
        self.assertNotIn("肩带 (内侧为黑色网布", names)
        self.assertNotIn("外侧使用主面料)", names)
        self.assertIn("普通拉链", names)


class TestExtractQuoteParameters(unittest.TestCase):
    def _section_a_horizontal_rows(self) -> list[list[str]]:
        return [
            ["A. 客户与报价信息", "", "", "", ""],
            ["客户名称", "业务员编号", "国家", "币种", "利润率%"],
            ["芝", "23-刘朋", "中国", "RMB", "30%"],
        ]

    def test_section_a_horizontal_salesperson_combined(self) -> None:
        from sales_rep_fields import extract_sales_fields
        from sheet_parser import extract_quote_parameters

        params = extract_quote_parameters(self._section_a_horizontal_rows())
        sec_a = params.get("A") or {}
        self.assertEqual(sec_a.get("客户名称"), "芝")
        self.assertEqual(sec_a.get("业务员编号"), "23-刘朋")
        self.assertEqual(sec_a.get("国家"), "中国")
        sales = extract_sales_fields(params)
        self.assertEqual(sales["sales_code"], "23")
        self.assertEqual(sales["sales_name"], "刘朋")
        self.assertEqual(sales["sales_display"], "23-刘朋")

    def test_section_a_split_code_and_name_columns(self) -> None:
        from sales_rep_fields import extract_sales_fields
        from sheet_parser import extract_quote_parameters

        rows = [
            ["A. 客户与报价信息", "", "", ""],
            ["客户名称", "业务员编号", "业务员姓名", "国家"],
            ["芝", "23", "刘朋", "中国"],
        ]
        params = extract_quote_parameters(rows)
        sales = extract_sales_fields(params)
        self.assertEqual(sales["sales_display"], "23-刘朋")

    def test_section_a_code_only(self) -> None:
        from sales_rep_fields import extract_sales_fields
        from sheet_parser import extract_quote_parameters

        rows = [
            ["A. 客户与报价信息", "", ""],
            ["客户名称", "业务员编号", "国家"],
            ["芝", "23", "中国"],
        ]
        sales = extract_sales_fields(extract_quote_parameters(rows))
        self.assertEqual(sales["sales_code"], "23")
        self.assertEqual(sales["sales_name"], "")
        self.assertEqual(sales["sales_display"], "23")

    def test_section_a_name_only(self) -> None:
        from sales_rep_fields import extract_sales_fields
        from sheet_parser import extract_quote_parameters

        rows = [
            ["A. 客户与报价信息", "", ""],
            ["客户名称", "业务员姓名", "国家"],
            ["芝", "刘朋", "中国"],
        ]
        sales = extract_sales_fields(extract_quote_parameters(rows))
        self.assertEqual(sales["sales_name"], "刘朋")
        self.assertEqual(sales["sales_display"], "刘朋")

    def test_legacy_vertical_key_value_still_works(self) -> None:
        from sheet_parser import extract_quote_parameters

        rows = [
            ["A. 客户与报价信息", ""],
            ["客户名称", "测试客户"],
            ["利润率", "35%"],
        ]
        params = extract_quote_parameters(rows)
        sec_a = params.get("A") or {}
        self.assertEqual(sec_a.get("客户名称"), "测试客户")
        self.assertIn("35", sec_a.get("利润率", ""))

    def test_material_sections_not_parsed_as_quote_params(self) -> None:
        from sheet_parser import extract_quote_parameters

        rows = [
            ["C. 材料与配件 (标准名/编码)", "", "", ""],
            ["外料 (标准名/编码)", "外料颜色", "里料 (标准名/编码)", "里料颜色"],
            ["600D涤纶牛津布", "红色", "210D防水涤纶内里", "印花"],
            ["D. 工艺 (多选;分隔)", "", ""],
            ["LOGO方式 (多选)", "LOGO内容", "关键工艺 (多选)"],
            ["丝印", "品牌Logo", "车缝"],
        ]
        params = extract_quote_parameters(rows)
        self.assertNotIn("C", params)
        self.assertNotIn("D", params)


if __name__ == "__main__":
    unittest.main()
