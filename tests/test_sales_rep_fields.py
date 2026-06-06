"""业务员字段提取与展示回归测试。"""
from __future__ import annotations

import unittest

from sales_rep_fields import (
    enrich_quote_sales_fields,
    extract_sales_fields,
    format_sales_display,
    merge_quote_sales_from_payload,
    split_combined_sales,
)


class TestSalesRepFields(unittest.TestCase):
    def test_code_only(self) -> None:
        fields = extract_sales_fields({"A": {"业务员编号": "23"}})
        self.assertEqual(fields["sales_code"], "23")
        self.assertEqual(fields["sales_name"], "")
        self.assertEqual(fields["sales_display"], "23")

    def test_name_only(self) -> None:
        fields = extract_sales_fields({"A": {"业务员姓名": "刘朋"}})
        self.assertEqual(fields["sales_code"], "")
        self.assertEqual(fields["sales_name"], "刘朋")
        self.assertEqual(fields["sales_display"], "刘朋")

    def test_code_and_name_columns(self) -> None:
        fields = extract_sales_fields({"A": {"业务员编号": "23", "业务员姓名": "刘朋"}})
        self.assertEqual(fields["sales_display"], "23-刘朋")

    def test_combined_cell(self) -> None:
        code, name = split_combined_sales("23-刘朋")
        self.assertEqual((code, name), ("23", "刘朋"))
        fields = extract_sales_fields({"A": {"业务员编号": "23-刘朋"}})
        self.assertEqual(fields["sales_code"], "23")
        self.assertEqual(fields["sales_name"], "刘朋")
        self.assertEqual(fields["sales_display"], "23-刘朋")

    def test_combined_cell_space_slash(self) -> None:
        self.assertEqual(split_combined_sales("23 刘朋"), ("23", "刘朋"))
        self.assertEqual(split_combined_sales("23/刘朋"), ("23", "刘朋"))

    def test_both_empty(self) -> None:
        fields = extract_sales_fields({"A": {}})
        self.assertEqual(fields["sales_display"], "-")
        self.assertEqual(format_sales_display("", ""), "-")

    def test_legacy_quote_without_sales_fields(self) -> None:
        quote = {"product_name": "测试包", "tiers": []}
        enrich_quote_sales_fields(quote)
        self.assertEqual(quote["sales_display"], "-")
        self.assertEqual(quote.get("sales_code"), "")
        self.assertEqual(quote.get("sales_name"), "")

    def test_merge_preserves_quote_params_and_sales(self) -> None:
        payload = {
            "quote_params": {"A": {"业务员编号": "23-刘朋"}},
            "items": [],
        }
        quote = {"material_total": 1.0, "tiers": []}
        merge_quote_sales_from_payload(quote, payload)
        self.assertIn("quote_params", quote)
        self.assertEqual(quote["sales_code"], "23")
        self.assertEqual(quote["sales_name"], "刘朋")
        self.assertEqual(quote["sales_display"], "23-刘朋")

    def test_sales_name_alias(self) -> None:
        fields = extract_sales_fields({"A": {"销售姓名": "王五"}})
        self.assertEqual(fields["sales_name"], "王五")
        self.assertEqual(fields["sales_display"], "王五")


class TestAdminBundleEnrichment(unittest.TestCase):
    def test_enrich_from_quote_params_in_saved_json(self) -> None:
        quote = {
            "quote_params": {
                "A": {"业务员编号": "23-刘朋", "客户名称": "某客户"},
            }
        }
        enrich_quote_sales_fields(quote)
        self.assertEqual(quote["sales_display"], "23-刘朋")


if __name__ == "__main__":
    unittest.main()
