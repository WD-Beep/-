"""收款账户类型分栏：分类、筛选、导出校验。"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from company_payment_accounts import (
    ACCOUNT_TYPE_CN,
    ACCOUNT_TYPE_FOREIGN,
    classify_account_bucket,
    search_company_accounts,
)
from quote_sheet_export_validate import validate_quote_sheet_export_payload

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "static" / "quote_sheet.js"
HTML_PATH = ROOT / "static" / "index.html"


class QuoteSheetPayeeAccountTypeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_classify_cny_account_as_cn(self) -> None:
        bucket = classify_account_bucket(
            {
                "company_name": "深圳市栢博旅游用品有限公司",
                "currency": "CNY",
                "bank_name": "中国银行深圳宝安支行",
            }
        )
        self.assertEqual(bucket, ACCOUNT_TYPE_CN)

    def test_classify_usd_account_as_foreign(self) -> None:
        bucket = classify_account_bucket(
            {
                "company_name": "SHENZHEN PEBOZ PRODUCTS LIMITED（美金账户）",
                "currency": "USD",
                "swift_code": "BKCHCNBJ45A",
            }
        )
        self.assertEqual(bucket, ACCOUNT_TYPE_FOREIGN)

    def test_search_cn_excludes_foreign_accounts(self) -> None:
        result = search_company_accounts("", limit=50, account_type=ACCOUNT_TYPE_CN)
        for row in result["candidates"]:
            self.assertEqual(row.get("account_type"), ACCOUNT_TYPE_CN)

    def test_search_foreign_only_usd_accounts(self) -> None:
        result = search_company_accounts("", limit=50, account_type=ACCOUNT_TYPE_FOREIGN)
        self.assertGreaterEqual(len(result["candidates"]), 1)
        for row in result["candidates"]:
            self.assertEqual(row.get("account_type"), ACCOUNT_TYPE_FOREIGN)

    def test_foreign_missing_swift_allows_export(self) -> None:
        result = validate_quote_sheet_export_payload(
            export_lang="en",
            bundle={
                "selected_bank_account_type": ACCOUNT_TYPE_FOREIGN,
                "payee": {
                    "account_type": ACCOUNT_TYPE_FOREIGN,
                    "company_name": "TEST CO",
                    "company_name_en": "TEST CO",
                    "currency": "USD",
                    "bank_name_en": "TEST BANK",
                    "bank_account": "123",
                },
            },
        )
        self.assertTrue(result.get("ok"))
        keys = {item.get("key") for item in result.get("blocking_issues", [])}
        self.assertNotIn("payee_swift", keys)

    def test_ui_has_account_type_selector(self) -> None:
        self.assertIn('name="qsPayeeAccountType"', self.html)
        self.assertIn('value="cn"', self.html)
        self.assertIn('value="foreign"', self.html)
        self.assertIn("中国账户", self.html)
        self.assertIn("美金账户", self.html)

    def test_js_filters_by_account_type(self) -> None:
        self.assertIn("readPayeeAccountType", self.js)
        self.assertIn("account_type=", self.js)
        self.assertIn("resetPayeeSelectionForTypeChange", self.js)
        self.assertIn("selected_bank_account_type", self.js)
        self.assertIn("payee_swift", self.js)

    def test_js_candidate_summary_format(self) -> None:
        self.assertIn("formatPayeeCandidateSummary", self.js)
        self.assertRegex(self.js, r"join\(\"｜\"\)")

    def test_js_payee_input_label_strips_account_type_suffix(self) -> None:
        self.assertIn("function payeeInputLabel", self.js)
        self.assertIn("stripPayeeAccountTypeSuffix", self.js)
        self.assertIn("payeeInputLabel(payeeState.selected)", self.js)
        title_body = self.js[
            self.js.index("function formatPayeeCandidateTitle") : self.js.index("function setPayeeDropdownOpen")
        ]
        self.assertIn("payeeInputLabel(account)", title_body)

    def test_js_cn_account_keeps_chinese_payee_on_english_pdf(self) -> None:
        self.assertIn("function useChinesePayeePresentationForPdf", self.js)
        resolve_body = self.js[
            self.js.index("function resolvePayeeAccountForPdf") : self.js.index("function sanitizeEnglishExportText")
        ]
        self.assertIn("useChinesePayeePresentationForPdf()", resolve_body)
        self.assertIn("shouldPreservePayeeChineseInEnglishPdf", self.js)
        bank_body = self.js[
            self.js.index("function buildBankPdfPresentation") : self.js.index("function buildBankNamePdfText")
        ]
        self.assertIn("!useChinesePayeePresentationForPdf()", bank_body)


if __name__ == "__main__":
    unittest.main()
