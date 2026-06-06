"""打样是否需要 / 打样费 / 打样时间：保存、回填、非阻断导出与 PDF 展示。"""
from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

from quote_sheet_meta import (
    build_prefill_meta,
    extract_sample_meta_from_quote,
    extract_saved_meta,
    format_sample_required_label,
    merge_meta_for_prefill,
    normalize_meta_payload,
    normalize_sample_required,
    resolve_sample_pdf_display,
    save_quote_sheet_meta,
    validate_sample_export_meta,
)
from quote_sheet_prefill import build_quote_sheet_prefill_payload
from quote_upload_storage import save_quote_calculation
from test_db_isolation import cleanup_isolated_quote_db, mount_isolated_quote_db, restore_quote_db

ROOT = Path(__file__).resolve().parents[1]


class QuoteSheetSampleRequiredTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()

    def tearDown(self) -> None:
        cleanup_isolated_quote_db(self._root)
        restore_quote_db(self._saved_db)

    def _seed_quote(self, series_uid: str, sales_uid: str = "sales_a") -> None:
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=f"calc-{series_uid[:8]}",
            sheet_original_display_name="demo.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": f"Q-{series_uid[:8]}",
                "product_name": "测试包",
                "customer_name": "kelly case",
                "tiers": [
                    {
                        "quantity": 500,
                        "exw_price": 10.0,
                        "exw_price_text": "10.00元",
                        "fob_price_usd": 1.5,
                        "fob_total_usd": 750.0,
                    }
                ],
                "material_total": 8.5,
            },
            sales_user_id=sales_uid,
            sales_user_name="业务员A",
        )

    def test_normalize_sample_required_aliases(self) -> None:
        self.assertEqual(normalize_sample_required("yes"), "yes")
        self.assertEqual(normalize_sample_required("需要打样"), "yes")
        self.assertEqual(normalize_sample_required("no"), "no")
        self.assertEqual(normalize_sample_required("不需要打样"), "no")
        self.assertEqual(normalize_sample_required("pending"), "pending")
        self.assertEqual(normalize_sample_required("待确认"), "pending")
        self.assertEqual(normalize_sample_required(""), "")
        self.assertEqual(normalize_sample_required("null"), "")

    def test_save_and_prefill_sample_required_fields(self) -> None:
        uid = str(uuid.uuid4())
        self._seed_quote(uid)
        meta = {
            "cust_name": "kelly case",
            "sample_required": "yes",
            "sample_fee": "300元",
            "sample_lead_time": "5-7天",
        }
        out = save_quote_sheet_meta(uid, "sales_a", meta)
        self.assertTrue(out.get("ok"))

        from quote_sheet_meta import _load_latest_quote_object

        quote = _load_latest_quote_object(uid)
        saved = extract_saved_meta(quote)
        self.assertEqual(saved["sample_required"], "yes")
        self.assertEqual(saved["sample_fee"], "300元")
        self.assertEqual(saved["sample_lead_time"], "5-7天")

        prefill = build_prefill_meta(
            {"quote_series_uid": uid, "sales_user_id": "sales_a"},
            quote,
            sales_user_id="sales_a",
        )
        self.assertEqual(prefill["sample_required"], "yes")
        self.assertEqual(prefill["sample_fee"], "300元")
        self.assertEqual(prefill["sample_lead_time"], "5-7天")

    def test_sample_required_not_overwritten_by_history(self) -> None:
        merged = merge_meta_for_prefill(
            inferred={"sample_required": "no", "sample_fee": "推断费", "sample_lead_time": "推断时间"},
            saved={"sample_required": "pending", "sample_fee": "300元", "sample_lead_time": "5-7天"},
            history={"sample_required": "yes", "sample_fee": "历史费", "sample_lead_time": "历史时间"},
        )
        self.assertEqual(merged["sample_required"], "pending")
        self.assertEqual(merged["sample_fee"], "300元")
        self.assertEqual(merged["sample_lead_time"], "5-7天")

    def test_validate_export_allows_empty_sample_required(self) -> None:
        result = validate_sample_export_meta({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["sample_required"], "")
        self.assertEqual(result["pdf_cn"]["status_text"], "")
        self.assertFalse(result["pdf_cn"]["show_status"])
        self.assertFalse(result["pdf_cn"]["show_fee"])
        self.assertFalse(result["pdf_cn"]["show_lead"])

    def test_validate_export_allows_yes_without_fee_or_lead(self) -> None:
        result = validate_sample_export_meta({"sample_required": "yes", "sample_fee": "", "sample_lead_time": ""})
        self.assertTrue(result["ok"])
        self.assertEqual(result["pdf_cn"]["status_text"], "")
        self.assertFalse(result["pdf_cn"]["show_status"])
        self.assertFalse(result["pdf_cn"]["show_fee"])
        self.assertFalse(result["pdf_cn"]["show_lead"])
        self.assertEqual(result["pdf_en"]["status_text"], "")

    def test_validate_export_yes_complete_shows_fee_and_lead(self) -> None:
        result = validate_sample_export_meta(
            {
                "sample_required": "yes",
                "sample_fee": "300元",
                "sample_lead_time": "5-7天",
            }
        )
        self.assertTrue(result["ok"])
        pdf = result["pdf_cn"]
        self.assertFalse(pdf["show_status"])
        self.assertEqual(pdf["status_text"], "")
        self.assertTrue(pdf["show_fee"])
        self.assertTrue(pdf["show_lead"])
        self.assertEqual(pdf["fee_text"], "300元")
        self.assertEqual(pdf["lead_text"], "5-7天")

    def test_pdf_display_no_longer_shows_status_row(self) -> None:
        pdf_cn = resolve_sample_pdf_display({"sample_required": "no"}, lang="cn")
        pdf_en = resolve_sample_pdf_display({"sample_required": "no"}, lang="en")
        self.assertEqual(pdf_cn["status_text"], "")
        self.assertEqual(pdf_en["status_text"], "")
        self.assertFalse(pdf_cn["show_status"])
        self.assertFalse(pdf_en["show_status"])
        self.assertFalse(pdf_cn["show_fee"])
        self.assertFalse(pdf_cn["show_lead"])

    def test_pdf_display_only_shows_fee_and_lead_when_present(self) -> None:
        for payload in ({}, {"sample_required": "pending"}, {"sample_required": ""}):
            pdf = resolve_sample_pdf_display(payload, lang="cn")
            self.assertEqual(pdf["status_text"], "")
            self.assertFalse(pdf["show_status"])
        pdf = resolve_sample_pdf_display(
            {"sample_fee": "300", "sample_lead_time": "五天"},
            lang="cn",
        )
        self.assertTrue(pdf["show_fee"])
        self.assertTrue(pdf["show_lead"])
        self.assertEqual(pdf["fee_text"], "300")
        self.assertEqual(pdf["lead_text"], "五天")

    def test_old_quote_without_sample_fields_prefill_and_export(self) -> None:
        uid = str(uuid.uuid4())
        self._seed_quote(uid)
        from quote_sheet_meta import _load_latest_quote_object

        quote = _load_latest_quote_object(uid)
        prefill = build_prefill_meta(
            {"quote_series_uid": uid, "sales_user_id": "sales_a"},
            quote,
            sales_user_id="sales_a",
        )
        self.assertEqual(prefill["sample_required"], "")
        self.assertEqual(prefill["sample_fee"], "")
        self.assertEqual(prefill["sample_lead_time"], "")
        self.assertTrue(validate_sample_export_meta(prefill)["ok"])

        payload = build_quote_sheet_prefill_payload(uid, "sales_a")
        self.assertIsNotNone(payload)
        meta = payload.get("meta") or {}
        self.assertEqual(meta.get("sample_required"), "")
        rows = payload.get("rows") or []
        self.assertTrue(rows)
        self.assertNotIn("sample_fee", str(rows[0]))

    def test_sample_fee_does_not_affect_product_totals(self) -> None:
        uid = str(uuid.uuid4())
        self._seed_quote(uid)
        save_quote_sheet_meta(
            uid,
            "sales_a",
            {
                "sample_required": "yes",
                "sample_fee": "300元",
                "sample_lead_time": "5-7天",
            },
        )
        payload = build_quote_sheet_prefill_payload(uid, "sales_a")
        self.assertIsNotNone(payload)
        row = (payload.get("rows") or [{}])[0]
        self.assertNotEqual(str(row.get("price") or ""), "300元")
        self.assertNotEqual(str(row.get("total") or ""), "300元")
        self.assertNotIn("300元", str(row.get("fob_total_usd") or ""))
        quote = payload.get("quote") if isinstance(payload, dict) else None
        if isinstance(quote, dict):
            tiers = quote.get("tiers") or []
            if tiers:
                self.assertNotEqual(float(tiers[0].get("fob_total_usd") or 0), 300.0)

    def test_extract_sample_meta_from_quote(self) -> None:
        quote = {
            "quote_sheet_meta": {
                "sample_required": "no",
                "sample_fee": "免费",
                "sample_lead_time": "3天",
            }
        }
        block = extract_sample_meta_from_quote(quote)
        self.assertEqual(block["sample_required"], "no")
        self.assertEqual(block["sample_fee"], "免费")
        self.assertEqual(format_sample_required_label("no"), "不需要打样")

    def test_normalize_rejects_nullish_text(self) -> None:
        payload = normalize_meta_payload(
            {
                "sample_required": "yes",
                "sample_fee": " null ",
                "sample_lead_time": "undefined",
            }
        )
        self.assertEqual(payload["sample_required"], "yes")
        self.assertEqual(payload["sample_fee"], "")
        self.assertEqual(payload["sample_lead_time"], "")

    def test_html_hides_sample_required_ui(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="qsSampleRequired"', html)
        self.assertNotIn("是否需要打样", html)
        self.assertIn('id="qsSampleFee"', html)
        self.assertIn('id="qsSampleLeadTime"', html)
        self.assertIn('id="pvSampleStatusLine"', html)

    def test_js_export_no_longer_blocks_on_empty_required(self) -> None:
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn("ensureSampleExportReady", js)
        self.assertIn("resolveFooterCompanyNameForPdf", js)
        self.assertNotIn("missing_sample_required", js)
        self.assertNotIn("openSampleExportGate", js)

    def test_admin_detail_shows_sample_fields(self) -> None:
        js = (ROOT / "static" / "admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("是否需要打样", js)
        self.assertIn("打样费", js)
        self.assertIn("打样时间", js)
        self.assertIn("extractQuoteSheetSampleMeta", js)

    def test_i18n_sample_status_labels_present(self) -> None:
        data = json.loads((ROOT / "data" / "i18n" / "quote_sheet_zh_en.json").read_text(encoding="utf-8"))
        labels = data.get("labels") or {}
        self.assertEqual(labels.get("lbl_meta_sample_status"), "Sample:")
        self.assertEqual(labels.get("lbl_sample_status_no"), "Not required")
        self.assertEqual(labels.get("lbl_sample_status_pending"), "To be confirmed")


if __name__ == "__main__":
    unittest.main()
