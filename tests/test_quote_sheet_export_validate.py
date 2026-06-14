"""报价单导出收款语言一致性校验。"""
from __future__ import annotations

import unittest

from quote_sheet_export_validate import validate_quote_sheet_export_payload
from quote_sheet_i18n import format_usd_bank_block_en, translate_quote_sheet_fields


USD_PAYEE = {
    "account_id": "peboz-usd-boc",
    "display_label_cn": "栢博美金账户 · SHENZHEN PEBOZ PRODUCTS LIMITED",
    "company_name": "SHENZHEN PEBOZ PRODUCTS LIMITED（美金账户）",
    "company_name_en": "SHENZHEN PEBOZ PRODUCTS LIMITED",
    "currency": "USD",
    "account_variant": "usd",
    "bank_name_en": "BANK OF CHINA, BAOAN SUB-BRANCH, SHENZHEN",
    "bank_account": "7419 7587 9516",
    "bank_address_en": "1/F BLOCK 1, WANJUN COMMERCLAL BLDG, BAOXING ROAD WEST, BAOAN DISTRICT SHENZHEN, CHINA",
    "swift_code": "BKCHCNBJ45A",
    "bank_note_en": "please note that all remitter bank charges are on buyer's account",
    "alipay": "",
}

CNY_PAYEE = {
    "company_name": "深圳市栢博旅游用品有限公司",
    "company_name_en": "Shenzhen Baibo Travel Products Co., Ltd.",
    "currency": "CNY",
    "bank_name": "中国银行深圳宝安支行",
    "bank_name_en": "Bank of China, Shenzhen Bao'an Sub-branch",
    "bank_account": "753660197656",
    "alipay": "myin@ptraveldesign.com-060156",
}

CN_ONLY_PAYEE = {
    "company_name": "深圳市六合春实业有限公司",
    "currency": "CNY",
    "bank_name": "中国银行股份有限公司深圳宝安支行",
    "bank_account": "7640 7120 6409",
    "alipay": "us@ptraveldesign.com-120156",
}


class QuoteSheetExportValidateTest(unittest.TestCase):
    def test_usd_payee_allows_english_export(self) -> None:
        result = validate_quote_sheet_export_payload(
            export_lang="en",
            bundle={"payee": USD_PAYEE, "meta": {}, "rows": []},
        )
        self.assertTrue(result.get("ok"))

    def test_usd_payee_allows_chinese_export(self) -> None:
        result = validate_quote_sheet_export_payload(
            export_lang="cn",
            bundle={"payee": USD_PAYEE, "meta": {}, "rows": []},
        )
        self.assertTrue(result.get("ok"))

    def test_chinese_payee_without_english_allows_english_export(self) -> None:
        result = validate_quote_sheet_export_payload(
            export_lang="en",
            bundle={"payee": CN_ONLY_PAYEE, "meta": {}, "rows": []},
        )
        self.assertTrue(result.get("ok"))

    def test_bilingual_cny_payee_allows_english_export(self) -> None:
        result = validate_quote_sheet_export_payload(
            export_lang="en",
            bundle={"payee": CNY_PAYEE, "meta": {}, "rows": []},
        )
        self.assertTrue(result.get("ok"))

    def test_cny_payee_allows_chinese_export(self) -> None:
        result = validate_quote_sheet_export_payload(
            export_lang="cn",
            bundle={"payee": CNY_PAYEE, "meta": {}, "rows": []},
        )
        self.assertTrue(result.get("ok"))

    def test_usd_translate_includes_bank_block(self) -> None:
        translated = translate_quote_sheet_fields(
            {"meta": {}, "rows": [], "payee": USD_PAYEE},
        )
        payee_en = translated.get("payee_en") or {}
        self.assertEqual(payee_en.get("currency"), "USD")
        block = str(payee_en.get("bank_block_text") or "")
        self.assertIn("Bank Information:", block)
        self.assertIn("SWIFT CODE: BKCHCNBJ45A", block)
        self.assertIn("SHENZHEN PEBOZ PRODUCTS LIMITED", block)

    def test_format_usd_bank_block_helper(self) -> None:
        block = format_usd_bank_block_en(USD_PAYEE)
        self.assertIn("NOTE: please note that all remitter bank charges", block)


if __name__ == "__main__":
    unittest.main()
