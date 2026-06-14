"""收款公司账户资料匹配与 PDF 文案格式化。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from company_payment_accounts import (
    ACCOUNT_TYPE_CN,
    ACCOUNT_TYPE_FOREIGN,
    classify_account_bucket,
    find_exact_company_account,
    format_alipay_info_text,
    format_bank_info_text,
    normalize_company_name,
    search_company_accounts,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "company_payment_accounts.json"


class CompanyPaymentAccountsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.accounts = json.loads(DATA_PATH.read_text(encoding="utf-8"))["accounts"]

    def test_data_file_has_baibo_travel(self) -> None:
        names = [row["company_name"] for row in self.accounts]
        self.assertIn("深圳市栢博旅游用品有限公司", names)

    def test_data_file_has_peboz_usd_account(self) -> None:
        usd_rows = [row for row in self.accounts if str(row.get("currency") or "").upper() == "USD"]
        self.assertGreaterEqual(len(usd_rows), 1)
        hit = next(row for row in usd_rows if row.get("account_id") == "peboz-usd-boc")
        self.assertEqual(hit["company_name_en"], "SHENZHEN PEBOZ PRODUCTS LIMITED")
        self.assertEqual(hit["swift_code"], "BKCHCNBJ45A")
        self.assertIn("7419", hit["bank_account"])

    def test_normalize_company_name_strips_spaces(self) -> None:
        self.assertEqual(normalize_company_name("  深圳市 栢博 旅游用品有限公司  "), "深圳市栢博旅游用品有限公司")

    def test_exact_match_baibo_travel(self) -> None:
        hit = find_exact_company_account("深圳市栢博旅游用品有限公司")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["bank_name"], "中国银行深圳宝安支行")
        self.assertEqual(hit["bank_account"], "753660197656")
        self.assertEqual(hit["alipay"], "myin@ptraveldesign.com-060156")

    def test_bank_account_kept_as_text_with_spaces(self) -> None:
        hit = find_exact_company_account("深圳市六合春实业有限公司")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["bank_account"], "7640 7120 6409")

    def test_format_bank_info_combines_name_and_account(self) -> None:
        hit = find_exact_company_account("深圳市栢博旅游用品有限公司")
        text = format_bank_info_text(hit)
        self.assertIn("中国银行深圳宝安支行", text)
        self.assertIn("753660197656", text)

    def test_format_alipay_only_when_present(self) -> None:
        hit = find_exact_company_account("深圳弘睿控股有限公司")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(format_alipay_info_text(hit), "")
        self.assertIn("4000050909100921311", format_bank_info_text(hit))

    def test_alipay_only_company(self) -> None:
        hit = find_exact_company_account("深圳市多莱发户外用品有限公司")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(format_bank_info_text(hit), "")
        self.assertEqual(format_alipay_info_text(hit), "m17722645311@163.com")

    def test_search_no_match(self) -> None:
        result = search_company_accounts("不存在的企业名称XYZ")
        self.assertIsNone(result["exact"])
        self.assertEqual(result["candidates"], [])

    def test_search_fuzzy_candidates_for_baibo(self) -> None:
        result = search_company_accounts("栢博")
        self.assertIsNone(result["exact"])
        names = [row["company_name"] for row in result["candidates"]]
        self.assertGreaterEqual(len(names), 2)
        self.assertIn("深圳市栢博旅游用品有限公司", names)
        self.assertIn("东莞栢博箱包制品有限公司", names)

    def test_search_exact_returns_single_candidate(self) -> None:
        result = search_company_accounts("深圳市栢博旅游用品有限公司")
        self.assertIsNotNone(result["exact"])
        self.assertEqual(len(result["candidates"]), 1)

    def test_search_empty_query_returns_all_accounts(self) -> None:
        result = search_company_accounts("", limit=30)
        self.assertIsNone(result["exact"])
        self.assertGreaterEqual(len(result["candidates"]), len(self.accounts))
        names = [row["company_name"] for row in result["candidates"]]
        self.assertIn("深圳市栢博旅游用品有限公司", names)

    def test_search_fuzzy_candidates_for_duolai(self) -> None:
        result = search_company_accounts("多莱")
        self.assertIsNone(result["exact"])
        names = [row["company_name"] for row in result["candidates"]]
        self.assertIn("长沙市多莱达科技有限公司", names)
        self.assertGreaterEqual(len(names), 2)

    def test_search_usd_account_by_peboz(self) -> None:
        result = search_company_accounts("PEBOZ")
        names = [row.get("company_name_en") or row.get("company_name") for row in result["candidates"]]
        self.assertTrue(any("PEBOZ" in str(name).upper() for name in names))

    def test_exact_match_usd_company_name(self) -> None:
        hit = find_exact_company_account("SHENZHEN PEBOZ PRODUCTS LIMITED（美金账户）")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.get("currency"), "USD")
        self.assertEqual(hit.get("account_type"), ACCOUNT_TYPE_FOREIGN)

    def test_baibo_travel_classified_as_cn(self) -> None:
        hit = find_exact_company_account("深圳市栢博旅游用品有限公司")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(classify_account_bucket(hit), ACCOUNT_TYPE_CN)
        self.assertEqual(hit.get("account_type"), ACCOUNT_TYPE_CN)

    def test_search_foreign_filter(self) -> None:
        result = search_company_accounts("", limit=50, account_type=ACCOUNT_TYPE_FOREIGN)
        self.assertGreaterEqual(len(result["candidates"]), 1)
        self.assertTrue(all(row.get("account_type") == ACCOUNT_TYPE_FOREIGN for row in result["candidates"]))


if __name__ == "__main__":
    unittest.main()
