from __future__ import annotations

import json
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

    def test_untranslatable_uses_fallback_not_marker(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {"co_name": "未知专有词甲乙丙", "seller_contact": "刘朋"},
                "rows": [{"name": "未知词条丁戊己"}],
            }
        )
        self.assertNotIn("UNTRANSLATED", json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["meta_en"]["co_name"], "To be confirmed")
        self.assertEqual(result["meta_en"]["seller_contact"], "To be confirmed")
        self.assertEqual(result["rows_en"][0]["name"], "To be confirmed")
        self.assertIn("meta.co_name", result["english_warnings"])

    def test_english_export_contains_no_cjk_except_cn_payee(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {
                    "co_name": "深圳市栢博旅游用品有限公司",
                    "co_addr": "广东省深圳市龙岗区平湖街道宝能智创谷B栋A单元6A01",
                    "seller_contact": "刘朋",
                    "quote_no": "23-刘朋",
                    "sample_fee": "300元",
                    "sample_lead_time": "5-7天",
                },
                "rows": [
                    {
                        "name": "双层保温午餐包",
                        "size": "20x12x22cm",
                        "desc": "FJ-18 600D舞龙布 防水PU, PU皮拉片",
                        "pack": "1个",
                        "qty": "500",
                        "price": "12.5",
                        "note": "按实际打样",
                    }
                ],
                "payee": {
                    "account_type": "cn",
                    "company_name": "深圳市六合春实业有限公司",
                    "bank_name": "中国银行股份有限公司深圳宝安支行",
                    "bank_account": "7640 7120 6409",
                    "alipay": "us@ptraveldesign.com-120156",
                },
                "selected_bank_account_type": "cn",
            }
        )
        blob = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("UNTRANSLATED", blob)
        self.assertEqual(
            result["meta_en"]["co_name"],
            "Shenzhen Baibo Travel Products Co., Ltd.",
        )
        self.assertIn("Baoneng", result["meta_en"]["co_addr"])
        self.assertEqual(result["payee_en"]["company_name"], "深圳市六合春实业有限公司")
        self.assertEqual(result["payee_en"]["bank_name"], "中国银行股份有限公司深圳宝安支行")
        self.assertEqual(result["payee_en"].get("preserve_chinese"), "1")
        self.assertEqual(result["rows_en"][0]["name"], "Double-layer insulated lunch bag")
        meta_rows_blob = json.dumps(
            {"meta_en": result["meta_en"], "rows_en": result["rows_en"]},
            ensure_ascii=False,
        )
        self.assertNotRegex(meta_rows_blob, r"[\u4e00-\u9fff]")

    def test_foreign_account_payee_stays_english_on_translate(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {},
                "rows": [],
                "payee": {
                    "account_type": "foreign",
                    "company_name": "SHENZHEN PEBOZ PRODUCTS LIMITED（美金账户）",
                    "company_name_en": "SHENZHEN PEBOZ PRODUCTS LIMITED",
                    "currency": "USD",
                    "bank_name_en": "BANK OF CHINA, BAOAN SUB-BRANCH, SHENZHEN",
                    "bank_account": "7419 7587 9516",
                    "swift_code": "BKCHCNBJ45A",
                },
                "selected_bank_account_type": "foreign",
            }
        )
        payee_en = result.get("payee_en") or {}
        self.assertEqual(payee_en.get("currency"), "USD")
        self.assertIn("SHENZHEN PEBOZ PRODUCTS LIMITED", str(payee_en.get("bank_block_text") or ""))
        self.assertNotEqual(payee_en.get("preserve_chinese"), "1")

    def test_chinese_fields_not_used_for_english_meta_defaults(self) -> None:
        result = translate_quote_sheet_fields(
            {
                "meta": {
                    "co_name": "深圳市栢博旅游用品有限公司",
                    "co_addr": "广东省深圳市龙岗区平湖街道宝能智创谷B栋A单元6A01",
                },
                "rows": [],
            }
        )
        self.assertEqual(
            result["meta_en"]["co_addr"],
            "Unit 6A01, Building A, Baoneng Zhichuang Valley, Pinghu Street, Longgang District, Shenzhen, Guangdong, China",
        )

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
