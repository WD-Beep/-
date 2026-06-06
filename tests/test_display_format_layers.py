"""展示层数字格式化：静态契约 + 预填接口断言（最多 1 位小数）。"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "app.js"
ADMIN_JS = ROOT / "static" / "admin" / "admin.js"
QUOTE_SHEET_JS = ROOT / "static" / "quote_sheet.js"
PROJECT_WORDING_PATHS = (
    ROOT / "README.md",
    ROOT / "static" / "index.html",
    ROOT / "static" / "admin" / "index.html",
    ROOT / "static" / "admin" / "login.html",
    ROOT / "docs" / "wecom_server_test_deploy.md",
    ROOT / "docs" / "ai_quote_assistant_requirements.md",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_function_body(name: str, js: str) -> str:
    match = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\(", js)
    if not match:
        raise AssertionError(f"unable to locate function: {name}")
    paren_start = match.end() - 1
    paren_depth = 0
    paren_end = -1
    for idx in range(paren_start, len(js)):
        ch = js[idx]
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
            if paren_depth == 0:
                paren_end = idx
                break
    if paren_end < 0:
        raise AssertionError(f"unable to parse function params: {name}")
    brace = js.index("{", paren_end)
    depth = 0
    for idx in range(brace, len(js)):
        ch = js[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[brace : idx + 1]
    raise AssertionError(f"unable to extract function body: {name}")


class AppJsDisplayFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(APP_JS)

    def test_no_cleaned_material_total_to_fixed_two(self) -> None:
        self.assertNotIn("cleanedMaterialTotal.toFixed(2)", self.js)
        self.assertIn("cleanedMaterialTotalNum", self.js)
        self.assertIn("formatDisplayNumber(cleanedMaterialTotalNum)", self.js)

    def test_process_material_lines_formats_price_fields(self) -> None:
        body = _extract_function_body("renderProcessMaterialLines", self.js)
        self.assertIn("formatNumbersInDisplayText(String(mt.unit_price", body)
        self.assertIn("formatNumbersInDisplayText(String(mt.formula_short", body)
        self.assertIn("formatNumbersInDisplayText(String(mt.subtotal", body)

    def test_app_js_no_business_to_fixed_two(self) -> None:
        self.assertNotRegex(self.js, r"toFixed\(2\)")

    def test_sales_sheet_checkpoints_gap_labels_use_display_format(self) -> None:
        body = _extract_function_body("buildSalesSheetCheckpointsHtml", self.js)
        self.assertIn("formatDisplayNumber(g)", body)
        self.assertIn("formatDisplayNumber(Math.abs(g))", body)
        self.assertNotIn("toFixed(2)", body)

    def test_gap_label_display_number_examples(self) -> None:
        from display_number_format import format_display_number

        self.assertEqual(format_display_number(1.234), "1.2")
        self.assertEqual(format_display_number(1.0), "1")
        self.assertEqual(format_display_number(abs(-1.0)), "1")


class ProjectWordingTest(unittest.TestCase):
    def test_no_car_quote_wording_in_docs_and_pages(self) -> None:
        banned = ("汽车报价", "车辆报价", "车价系统")
        for path in PROJECT_WORDING_PATHS:
            text = path.read_text(encoding="utf-8")
            for word in banned:
                self.assertNotIn(word, text, msg=f"{path.name} contains {word}")

    def test_readme_uses_auto_quote_system_title(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("# 自动报价系统", readme)
        self.assertNotIn("汽车报价", readme)


class AdminJsDisplayFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(ADMIN_JS)

    def test_render_detail_table_uses_bom_display_format(self) -> None:
        body = _extract_function_body("renderDetailTable", self.js)
        self.assertIn("formatBomDisplayNumberText(r.spec", body)
        self.assertIn("formatBomDisplayNumberText(r.usage", body)
        self.assertIn("formatBomDisplayNumberText(r.unit_price", body)
        self.assertIn("formatBomDisplayNumberText(r.amount_text)", body)
        self.assertNotRegex(body, r"escapeHtml\(String\(r\.spec")

    def test_render_marker_room_table_uses_bom_display_format(self) -> None:
        body = _extract_function_body("renderMarkerRoomTable", self.js)
        for field in (
            "length",
            "width",
            "occupied_length",
            "occupied_width",
            "qty",
            "single_marker_usage",
            "loss_pct",
            "total_marker_usage",
            "unit_price",
            "amount",
        ):
            self.assertIn(f"formatBomDisplayNumberText(r.{field}", body, field)
        self.assertIn("escapeHtml(String(r.unit ||", body)

    def test_render_overview_embedded_detail_legacy_formats_numbers(self) -> None:
        body = _extract_function_body("renderOverviewEmbeddedDetailLegacy", self.js)
        self.assertIn("formatBomDisplayNumberText(r.spec", body)
        self.assertIn("formatBomDisplayNumberText(r.usage", body)
        self.assertIn("formatBomDisplayNumberText(r.unit_price", body)
        self.assertIn("formatBomDisplayNumberText(r.amount_text)", body)


class QuoteSheetJsDisplayFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(QUOTE_SHEET_JS)

    def test_pdf_row_price_total_qty_formatted_before_text_content(self) -> None:
        self.assertIn("priceDisp = formatNumbersInDisplayText(priceDisp)", self.js)
        self.assertIn("totalDisp = formatNumbersInDisplayText(totalDisp)", self.js)
        self.assertIn("qtyDisp = formatNumbersInDisplayText(qtyDisp)", self.js)
        price_pos = self.js.index("formatNumbersInDisplayText(priceDisp)")
        total_pos = self.js.index("formatNumbersInDisplayText(totalDisp)")
        qty_pos = self.js.index("formatNumbersInDisplayText(qtyDisp)")
        self.assertLess(price_pos, self.js.index("priceTd.textContent = priceDisp"))
        self.assertLess(total_pos, self.js.index("totTd.textContent = totalDisp"))
        self.assertLess(qty_pos, self.js.index("qtyTd.textContent = qtyDisp"))


class QuoteSheetPrefillDisplayFormatTest(unittest.TestCase):
    def test_format_customer_price_text(self) -> None:
        from quote_sheet_prefill import _format_customer_price_text

        self.assertEqual(_format_customer_price_text("12.5579元/㎡"), "12.6元/㎡")
        self.assertEqual(_format_customer_price_text("2.3901元"), "2.4元")
        self.assertEqual(_format_customer_price_text("20.00元"), "20元")

    def test_product_row_formats_taxed_price_text(self) -> None:
        from quote_sheet_prefill import _product_row

        tier = {
            "quantity": 500,
            "exw_price": 12.5579,
            "exw_price_text": "12.5579元",
            "taxed_price_text": "14.1234元",
        }
        quote = {"product_name": "测试包", "tiers": [tier]}
        row = _product_row(
            quote=quote,
            tier=tier,
            row_index=0,
            image_map={},
            product_count=1,
        )
        self.assertEqual(row["price"], "12.6")
        self.assertEqual(row["taxed_price_text"], "14.1元")
        self.assertAlmostEqual(float(tier["exw_price"]), 12.5579, places=4)

    def test_tier_unit_price_from_tier_formats_numeric(self) -> None:
        from quote_sheet_prefill import _tier_unit_price_from_tier

        tier = {"exw_price": 12.5579}
        self.assertEqual(_tier_unit_price_from_tier(tier), "12.6")

    def test_tier_unit_price_from_tier_formats_text_without_numeric(self) -> None:
        from quote_sheet_prefill import _tier_unit_price_from_tier

        tier = {"exw_unit_price_text": "面议/件"}
        self.assertEqual(_tier_unit_price_from_tier(tier), "面议/件")

    def test_tier_fob_display_fields_format_text(self) -> None:
        from quote_sheet_prefill import _tier_fob_display_fields

        tier = {
            "fob_price": 20.501,
            "fob_price_text": "20.501元",
            "fob_price_usd_text": "$2.8765",
        }
        out = _tier_fob_display_fields(tier, 500, {})
        self.assertEqual(out["fob_price"], "20.5")
        self.assertEqual(out["fob_price_text"], "20.5元")
        self.assertEqual(out["fob_price_usd_text"], "$2.9")


if __name__ == "__main__":
    unittest.main()
