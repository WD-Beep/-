from __future__ import annotations

import unittest

from quote_sheet_i18n import translate_pack_for_quote_sheet, translate_quote_sheet_fields


class QuoteSheetI18nTest(unittest.TestCase):
    def test_translate_fields_and_keep_numeric(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {
                    "co_name": "深圳市栢博旅游用品有限公司",
                    "quote_date_iso": "2026-05-17",
                    "seller_email": "a@bb.com",
                    "co_phone": "0755-28223791",
                },
                "rows": [
                    {
                        "name": "尼龙拉链袋",
                        "size": "20x10cm",
                        "desc": "尼龙材质，金属拉链",
                        "pack": "单个包装",
                        "qty": "300",
                        "price": "12.5",
                        "note": "按实际打样",
                    }
                ],
            }
        )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result["meta_en"]["quote_date_iso"], "2026-05-17")
        self.assertEqual(result["meta_en"]["seller_email"], "a@bb.com")
        self.assertEqual(result["meta_en"]["co_phone"], "0755-28223791")
        self.assertEqual(result["meta_en"]["co_name"], "Shenzhen Baibo Travel Products Co., Ltd.")
        self.assertEqual(result["rows_en"][0]["qty"], "300")
        self.assertEqual(result["rows_en"][0]["price"], "12.5")
        self.assertEqual(result["rows_en"][0]["pack"], "Individual packing")
        self.assertEqual(result["rows_en"][0]["note"], "Subject to actual sample evaluation")

    def test_untranslated_fallback_marks_suffix(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {"co_name": "未知专有词甲乙丙"},
                "rows": [{"name": "未知词条丁戊己"}],
            }
        )
        self.assertTrue(result["meta_en"]["co_name"].endswith("[UNTRANSLATED]"))
        self.assertTrue(result["rows_en"][0]["name"].endswith("[UNTRANSLATED]"))
        self.assertIn("meta.co_name", result["untranslated_fields"])
        self.assertIn("rows[0].name", result["untranslated_fields"])

    def test_keep_ascii_numeric_symbol_values(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {
                    "co_name": "ABC Travel Co.,Ltd.",
                    "co_phone": "+86-755-28223791",
                    "seller_email": "sales@example.com",
                    "quote_no": "Q-2026/05-17#A1",
                    "quote_date_iso": "2026-05-17",
                },
                "rows": [
                    {
                        "name": "Nylon bag",
                        "size": "20x10cm",
                        "desc": "Waterproof / black",
                        "pack": "1pc/opp",
                        "qty": "300",
                        "price": "12.5",
                        "note": "EXW only",
                    }
                ],
            }
        )
        self.assertEqual(result["meta_en"]["co_name"], "ABC Travel Co.,Ltd.")
        self.assertEqual(result["meta_en"]["co_phone"], "+86-755-28223791")
        self.assertEqual(result["meta_en"]["seller_email"], "sales@example.com")
        self.assertEqual(result["meta_en"]["quote_no"], "Q-2026/05-17#A1")
        self.assertEqual(result["meta_en"]["quote_date_iso"], "2026-05-17")
        self.assertEqual(result["rows_en"][0]["name"], "Nylon bag")
        self.assertEqual(result["rows_en"][0]["size"], "20x10cm")
        self.assertEqual(result["rows_en"][0]["desc"], "Waterproof / black")
        self.assertEqual(result["rows_en"][0]["pack"], "1pc / opp")
        self.assertEqual(result["rows_en"][0]["qty"], "300")
        self.assertEqual(result["rows_en"][0]["price"], "12.5")
        self.assertEqual(result["rows_en"][0]["note"], "EXW only")

    def test_pack_qty_translates_without_untranslated_marker(self) -> None:
        out = translate_pack_for_quote_sheet("1个", [])
        self.assertEqual(out, "1 pc")
        self.assertNotIn("UNTRANSLATED", out)

    def test_translate_bundle_carries_fob_usd_fields(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {},
                "rows": [
                    {
                        "name": "篮球包",
                        "pack": "1个",
                        "qty": "500",
                        "price": "85.19",
                        "fob_price_usd": "12.47",
                        "fob_total_usd": "6235.00",
                    }
                ],
            }
        )
        row = result["rows_en"][0]
        self.assertEqual(row["fob_price_usd"], "12.47")
        self.assertEqual(row["fob_total_usd"], "6235.00")
        self.assertEqual(row["pack"], "1 pc")

    def test_sample_fee_and_lead_time_translate_for_fob_pdf(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {
                    "sample_fee": "300元",
                    "sample_lead_time": "5-7天",
                },
                "rows": [],
            }
        )
        self.assertEqual(result["meta_en"]["sample_fee"], "300 RMB")
        self.assertEqual(result["meta_en"]["sample_lead_time"], "5-7 days")

    def test_sample_fields_empty_no_null_tokens(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {
                    "sample_fee": "",
                    "sample_lead_time": "",
                },
                "rows": [],
            }
        )
        self.assertEqual(result["meta_en"]["sample_fee"], "")
        self.assertEqual(result["meta_en"]["sample_lead_time"], "")
        self.assertNotIn("null", str(result["meta_en"]).lower())
        self.assertNotIn("undefined", str(result["meta_en"]).lower())
        self.assertNotIn("nan", str(result["meta_en"]).lower())

    def test_sample_required_passthrough_without_translation(self) -> None:
        for value in ("yes", "no", "pending"):
            result = translate_quote_sheet_fields(
                {
                    "meta": {
                        "sample_required": value,
                        "sample_fee": "300元",
                        "sample_lead_time": "5-7天",
                    },
                    "rows": [],
                }
            )
            self.assertEqual(result["meta_en"]["sample_required"], value)

    def test_brief_desc_pending_material_translates(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {},
                "rows": [{"name": "篮球包", "desc": "主料待确认", "qty": "500"}],
            }
        )
        self.assertEqual(result["rows_en"][0]["desc"], "Main material TBD")

    def test_brief_desc_translates_to_english_format(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {},
                "rows": [
                    {
                        "name": "篮球包",
                        "desc": "主料：600D牛津布",
                        "qty": "500",
                        "price": "12.5",
                    }
                ],
            }
        )
        self.assertEqual(
            result["rows_en"][0]["desc"],
            "Main materials: 600D Oxford fabric",
        )


if __name__ == "__main__":
    unittest.main()
