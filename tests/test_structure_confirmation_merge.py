import unittest

from server import build_structure_confirmation_payload, merge_structure_confirmation_user_items


class StructureConfirmationMergeTest(unittest.TestCase):
    def test_deleted_patch_removes_row_before_quote(self) -> None:
        base = [
            {"name": "有效主料", "usage": "1码", "unit_price": "10元/码", "amount": 10},
            {"name": "无效行", "usage": "1套", "unit_price": "50元/码", "amount": 50},
            {"name": "有效拉链", "usage": "1米", "unit_price": "7元/米", "amount": 7},
        ]

        out = merge_structure_confirmation_user_items(base, [{"index": 1, "deleted": True}])

        self.assertEqual([r["name"] for r in out], ["有效主料", "有效拉链"])


    def test_added_patch_appends_new_row_before_quote(self) -> None:
        base = [
            {"name": "210D涤纶", "usage": "0.09㎡", "unit_price": "10.5元/㎡", "amount": 0.94},
        ]

        out = merge_structure_confirmation_user_items(
            base,
            [
                {
                    "index": 1,
                    "name": "新增织带",
                    "spec": "25mm",
                    "usage": "1.2米",
                    "unit_price": "0.5元/米",
                    "calc_note": "手工补充",
                },
            ],
        )

        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["name"], "新增织带")
        self.assertEqual(out[1]["usage"], "1.2米")
        self.assertEqual(out[1]["calc_note"], "手工补充")

    def test_unit_price_edit_rescales_amount_when_amount_not_in_patch(self) -> None:
        base = [
            {
                "name": "五金标准扣具",
                "usage": "-",
                "unit_price": "2.5元/个",
                "amount": 2.5,
                "amount_ai": True,
            },
        ]
        out = merge_structure_confirmation_user_items(
            base,
            [{"index": 0, "unit_price": "1.5元/个"}],
        )
        self.assertEqual(out[0]["unit_price"], "1.5元/个")
        self.assertAlmostEqual(float(out[0]["amount"]), 1.5, places=2)
        self.assertFalse(out[0].get("amount_ai"))


    def test_structure_confirmation_payload_prefills_pending_market_price(self) -> None:
        payload = {
            "items": [
                {
                    "name": "\u8170\u5c01\uff08\u7ed3\u6784\u5f85\u6838\uff09",
                    "usage": "-",
                    "unit_price": "-",
                    "kb_hit": False,
                    "from_bag_structure_extraction": True,
                    "recognition_status": "candidate_review",
                }
            ]
        }
        resp = build_structure_confirmation_payload(
            payload,
            sheet_parse_result={"file_name": "demo.xlsx"},
            structure_text="",
        )
        row = resp["items_confirmation"][0]
        self.assertNotIn("\u5957", str(row["usage"]))
        self.assertIn(str(row["usage"]), {"\u5f85\u586b\u6570\u91cf", "\u51e0\u7247", "\u51e0\u4e2a"})
        self.assertNotIn(str(row.get("unit_price") or "").strip(), {"", "-", "\u2014"})
        self.assertEqual(float(row.get("amount") or 0), 0.0)
        self.assertTrue(row["ai"])

    def test_structure_confirmation_payload_prefills_kb_hit_missing_usage(self) -> None:
        payload = {
            "items": [
                {
                    "name": "6分D扣 2个",
                    "usage": "-",
                    "unit_price": "0.3元/个",
                    "amount": 0,
                    "kb_hit": True,
                    "recognition_status": "split",
                    "_source_combined_name": "6分D扣 2个6分梯扣 4个",
                }
            ]
        }
        resp = build_structure_confirmation_payload(
            payload,
            sheet_parse_result={"file_name": "demo.xlsx"},
            structure_text="",
        )
        row = resp["items_confirmation"][0]
        self.assertEqual(row["usage"], "2个")
        self.assertEqual(row["unit_price"], "0.3元/个")
        self.assertAlmostEqual(float(row["amount"] or 0), 0.6, places=2)
        self.assertFalse(row["ai"])

    def test_structure_confirmation_payload_prefills_split_accessories_with_kb_hit_dash(self) -> None:
        payload = {
            "items": [
                {
                    "name": "胸带调节扣 2个",
                    "usage": "-",
                    "unit_price": "-",
                    "kb_hit": True,
                    "recognition_status": "split",
                    "recognition_reason": "知识库命中",
                    "_source_combined_name": "胸带调节扣 2个6分D扣 2个6分梯扣 4个",
                },
                {
                    "name": "6分D扣 2个",
                    "usage": "-",
                    "unit_price": "-",
                    "kb_hit": True,
                    "recognition_status": "split",
                    "_source_combined_name": "胸带调节扣 2个6分D扣 2个6分梯扣 4个",
                },
                {
                    "name": "6分梯扣 4个",
                    "usage": "-",
                    "unit_price": "-",
                    "kb_hit": True,
                    "recognition_status": "split",
                    "_source_combined_name": "胸带调节扣 2个6分D扣 2个6分梯扣 4个",
                },
            ]
        }
        resp = build_structure_confirmation_payload(
            payload,
            sheet_parse_result={"file_name": "B260174报价资料.xlsx"},
            structure_text="",
        )
        for row in resp["items_confirmation"]:
            self.assertNotIn(str(row.get("unit_price") or "").strip(), {"", "-", "—"})
            self.assertIn("元/个", str(row.get("unit_price") or ""))
            self.assertGreater(float(row.get("amount") or 0), 0)
            self.assertTrue(row["ai"])

    def test_structure_confirmation_confirmed_items_keep_estimated_prices(self) -> None:
        from kimi_client import prepare_structure_rows_for_market_estimate
        from material_row_validity import confirm_material_candidates_for_quote

        items = [
            {
                "name": "胸带调节扣 2个",
                "usage": "-",
                "unit_price": "-",
                "kb_hit": True,
                "recognition_status": "split",
                "_source_combined_name": "胸带调节扣 2个6分D扣 2个",
            },
            {
                "name": "6分D扣 2个",
                "usage": "-",
                "unit_price": "-",
                "kb_hit": True,
                "recognition_status": "split",
                "_source_combined_name": "胸带调节扣 2个6分D扣 2个",
            },
        ]
        prefilled = prepare_structure_rows_for_market_estimate(items)
        confirmed = confirm_material_candidates_for_quote(prefilled)
        for row in confirmed:
            self.assertNotIn(str(row.get("unit_price") or "").strip(), {"", "-", "—"})
            self.assertGreater(float(row.get("amount") or 0), 0)
            self.assertTrue(row.get("unit_price_ai"))
            self.assertTrue(row.get("amount_ai"))


if __name__ == "__main__":
    unittest.main()
