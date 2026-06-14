from __future__ import annotations

import base64
import unittest

from material_row_validity import (
    RECOGNITION_CANDIDATE,
    RECOGNITION_IGNORED,
    RECOGNITION_SPLIT,
    apply_material_validity_layer,
    build_quote_participation_summary,
    classify_material_row,
    confirm_material_candidates_for_quote,
    promote_quotable_rows_for_quote,
    row_exclusion_reasons_for_quote,
    row_is_quotable_for_cost,
    should_skip_knowledge_learn_row,
)
from sheet_parser import parse_sheet_items_from_payload


def _to_base64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class MaterialRowValidityTest(unittest.TestCase):
    def test_ignore_outer_fabric_description_fragment(self) -> None:
        status, reason = classify_material_row("外侧使用主面料)")
        self.assertEqual(status, RECOGNITION_IGNORED)
        self.assertIn("说明", reason)

    def test_shoulder_strap_description_is_candidate_not_whole_material(self) -> None:
        text = "肩带（内侧为黑色网布，外侧使用主面料和黑色织带）"
        status, reason = classify_material_row(text)
        self.assertEqual(status, RECOGNITION_CANDIDATE)
        self.assertIn("人工确认", reason)
        rows = apply_material_validity_layer([{"name": text, "unit_price": "-", "kb_hit": False}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["recognition_status"], RECOGNITION_CANDIDATE)
        self.assertTrue(rows[0]["exclude_from_cost"])
        self.assertEqual(rows[0].get("material_clue"), "内侧为黑色网布，外侧使用主面料和黑色织带")

    def test_split_combined_buckles(self) -> None:
        text = "1寸插扣 1个6分插扣 2个胸带调节扣 2个6分D扣 2个6分梯扣 4个1寸梯扣 2个猪鼻扣 12个"
        rows = apply_material_validity_layer(
            [{"name": text, "spec": "1寸", "unit_price": "0.6元/个", "amount": 0.6, "kb_hit": False}]
        )
        names = [r["name"] for r in rows]
        self.assertGreaterEqual(len(names), 5)
        self.assertNotIn(text, names)
        self.assertTrue(all(r["recognition_status"] == RECOGNITION_SPLIT for r in rows))
        quotable = [r for r in rows if not r["exclude_from_cost"]]
        excluded = [r for r in rows if r["exclude_from_cost"]]
        self.assertGreaterEqual(len(quotable), 1)
        self.assertGreaterEqual(len(excluded), 1)

    def test_matched_kb_row_stays_matched(self) -> None:
        rows = apply_material_validity_layer(
            [{"name": "普通拉头", "unit_price": "0.3元/个", "kb_hit": True, "kb_auto_learned": True}]
        )
        self.assertEqual(rows[0]["recognition_status"], "matched")
        self.assertFalse(rows[0]["exclude_from_cost"])

    def test_confirm_structure_allows_candidate_into_quote(self) -> None:
        rows = apply_material_validity_layer(
            [{"name": "普通拉头", "usage": "1个", "unit_price": "0.3元/个", "kb_hit": False}]
        )
        confirmed = confirm_material_candidates_for_quote(rows)
        self.assertTrue(confirmed[0]["recognition_confirmed"])
        self.assertFalse(confirmed[0]["exclude_from_cost"])

    def test_pending_row_with_price_and_usage_participates_in_quote(self) -> None:
        from quote_engine import calculate_quote, parse_items

        row = {
            "name": "旋转钩扣具",
            "usage": "2个",
            "unit_price": "0.60元/个",
            "recognition_status": RECOGNITION_CANDIDATE,
            "recognition_reason": "知识库匹配名称但缺有效单价，待补价/待确认",
            "kb_hit": False,
        }
        self.assertTrue(row_is_quotable_for_cost(row))
        promoted = promote_quotable_rows_for_quote([row])
        self.assertFalse(promoted[0]["exclude_from_cost"])
        confirmed = confirm_material_candidates_for_quote(promoted)
        parsed = parse_items(confirmed)
        self.assertEqual(len(parsed), 1)
        self.assertGreater(parsed[0].amount, 0)

    def test_missing_price_row_listed_as_excluded_not_silent(self) -> None:
        row = {
            "name": "2-3mm EPE保温棉",
            "spec": "3mm",
            "usage": "-",
            "unit_price": "-",
            "recognition_status": RECOGNITION_CANDIDATE,
        }
        reasons = row_exclusion_reasons_for_quote(row)
        self.assertIn("缺少单价", reasons)
        summary = build_quote_participation_summary([row], [])
        self.assertEqual(summary["excluded_count"], 1)
        self.assertEqual(summary["excluded"][0]["name"], "2-3mm EPE保温棉")

    def test_calc_note_derivable_usage_participates_in_quote(self) -> None:
        from quote_engine import parse_items

        row = {
            "name": "食品级PEVA易擦洗内里",
            "usage": "-",
            "unit_price": "12元/码²",
            "calc_note": "PEVA按包身外包络≈0.347m² x 覆盖系数0.32≈0.111m²",
            "recognition_status": RECOGNITION_CANDIDATE,
        }
        confirmed = confirm_material_candidates_for_quote(promote_quotable_rows_for_quote([row]))
        parsed = parse_items(confirmed)
        self.assertEqual(len(parsed), 1)
        self.assertNotEqual(parsed[0].usage, "-")

    def test_manual_patch_promotes_row_for_quote(self) -> None:
        from server import merge_structure_confirmation_user_items

        base = [
            {
                "name": "五金标准扣具",
                "usage": "-",
                "unit_price": "-",
                "recognition_status": RECOGNITION_CANDIDATE,
                "exclude_from_cost": True,
            }
        ]
        merged = merge_structure_confirmation_user_items(
            base,
            [{"index": 0, "unit_price": "0.60元/个", "usage": "1个"}],
        )
        self.assertFalse(merged[0]["exclude_from_cost"])
        self.assertTrue(merged[0].get("recognition_confirmed"))

    def test_calculate_quote_includes_participation_summary(self) -> None:
        from quote_engine import calculate_quote

        items = [
            {
                "name": "旋转钩扣具",
                "usage": "2个",
                "unit_price": "0.60元/个",
                "amount": 1.2,
                "recognition_status": RECOGNITION_CANDIDATE,
                "exclude_from_cost": False,
            },
            {
                "name": "2-3mm EPE保温棉",
                "spec": "3mm",
                "usage": "-",
                "unit_price": "-",
                "recognition_status": RECOGNITION_CANDIDATE,
                "exclude_from_cost": True,
            },
        ]
        result = calculate_quote(
            {
                "items": items,
                "product_name": "测试包",
                "quantities": [500],
                "processing_fee": 10,
            }
        )
        summary = result.get("quote_participation_summary") or {}
        self.assertGreaterEqual(summary.get("included_count", 0), 1)
        self.assertGreaterEqual(summary.get("excluded_count", 0), 1)

    def test_quotable_pending_rows_drive_material_total_and_tiers(self) -> None:
        from quote_engine import calculate_quote

        items = [
            {
                "name": "旋转钩扣具",
                "usage": "2个",
                "unit_price": "0.60元/个",
                "amount": 1.2,
                "recognition_status": RECOGNITION_CANDIDATE,
            },
            {
                "name": "食品级PEVA内里",
                "usage": "0.11m²",
                "unit_price": "12元/码²",
                "amount": 1.32,
                "recognition_status": RECOGNITION_CANDIDATE,
            },
            {
                "name": "2-3mm EPE保温棉",
                "spec": "3mm",
                "usage": "-",
                "unit_price": "-",
                "recognition_status": RECOGNITION_CANDIDATE,
                "exclude_from_cost": True,
            },
        ]
        confirmed = confirm_material_candidates_for_quote(promote_quotable_rows_for_quote(items))
        result = calculate_quote(
            {
                "items": confirmed,
                "product_name": "测试包",
                "quantities": [300, 500, 1000],
                "processing_fee": 5.0,
                "mold_fee": 500.0,
                "system_overhead": 0.0,
            }
        )
        detail_names = {str(r.get("name") or "") for r in result.get("detail_rows") or []}
        self.assertIn("旋转钩扣具", detail_names)
        self.assertIn("食品级PEVA内里", detail_names)
        self.assertNotIn("2-3mm EPE保温棉", detail_names)

        included_sum = round(
            sum(
                float(r.get("amount") or 0)
                for r in result.get("detail_rows") or []
                if str(r.get("name") or "") in {"旋转钩扣具", "食品级PEVA内里"}
            ),
            2,
        )
        material_total = round(float(result.get("material_total") or 0), 2)
        self.assertAlmostEqual(material_total, included_sum, places=2)
        self.assertGreater(material_total, 0)

        overhead = float((result.get("settings") or {}).get("system_overhead") or 0)
        processing = float((result.get("settings") or {}).get("processing_fee") or 0)
        for tier in result.get("tiers") or []:
            qty = float(tier.get("quantity") or 1)
            mold_share = round(500.0 / qty, 2)
            expected_cost = round(material_total + processing + overhead + mold_share, 2)
            self.assertAlmostEqual(float(tier.get("total_cost") or 0), expected_cost, places=2)

        summary = result.get("quote_participation_summary") or {}
        self.assertGreaterEqual(int(summary.get("excluded_count") or 0), 1)
        excluded_names = {str(x.get("name") or "") for x in summary.get("excluded") or []}
        self.assertIn("2-3mm EPE保温棉", excluded_names)

    def test_bag_structure_extraction_row_is_candidate_not_ignored(self) -> None:
        rows = apply_material_validity_layer(
            [
                {
                    "name": "bottle pocket structure pending",
                    "unit_price": "-",
                    "from_bag_structure_extraction": True,
                    "recognition_status": RECOGNITION_CANDIDATE,
                }
            ]
        )
        self.assertEqual(rows[0]["recognition_status"], RECOGNITION_CANDIDATE)
        self.assertNotEqual(rows[0]["recognition_status"], RECOGNITION_IGNORED)
        self.assertTrue(rows[0]["exclude_from_cost"])

        confirmed = confirm_material_candidates_for_quote(rows)
        self.assertTrue(confirmed[0]["recognition_confirmed"])
        self.assertTrue(confirmed[0]["exclude_from_cost"])

    def test_structure_pending_suffix_not_ignored_without_flag(self) -> None:
        rows = apply_material_validity_layer(
            [{"name": "背垫（结构待核）", "unit_price": "-", "kb_hit": False}]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["recognition_status"], RECOGNITION_CANDIDATE)
        self.assertNotEqual(rows[0]["recognition_status"], RECOGNITION_IGNORED)
        self.assertTrue(rows[0].get("from_bag_structure_extraction"))

    def test_split_accessory_rows_stay_split_not_ignored(self) -> None:
        text = "6分D扣 2个6分梯扣 4个"
        rows = apply_material_validity_layer(
            [{"name": text, "unit_price": "0.6元/个", "amount": 0.6, "kb_hit": False}]
        )
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all(r["recognition_status"] != RECOGNITION_IGNORED for r in rows))
        self.assertTrue(all(r["recognition_status"] == RECOGNITION_SPLIT for r in rows))

    def test_confirmed_structure_pending_row_parses_into_quote(self) -> None:
        from quote_engine import parse_items

        rows = apply_material_validity_layer(
            [
                {
                    "name": "腰封（结构待核）",
                    "usage": "1套",
                    "unit_price": "3.5元/套",
                    "amount": 3.5,
                    "from_bag_structure_extraction": True,
                }
            ]
        )
        confirmed = confirm_material_candidates_for_quote(rows)
        parsed = parse_items(confirmed)
        self.assertEqual(len(parsed), 1)
        self.assertIn("腰封", parsed[0].name)

    def test_skip_knowledge_learn_for_unconfirmed_rows(self) -> None:
        row = {"recognition_status": RECOGNITION_CANDIDATE, "exclude_from_cost": True}
        self.assertTrue(should_skip_knowledge_learn_row(row))

    def test_sheet_parser_filters_description_and_splits_buckles(self) -> None:
        csv_text = (
            "物料名称,规格/用量,单价参考,小计\n"
            "外侧使用主面料),-,-,0\n"
            "肩带（内侧为黑色网布,-,-,0\n"
            "1寸插扣 1个6分插扣 2个胸带调节扣 2个猪鼻扣 12个,1寸,0.6元/个,0.6\n"
            "普通拉头,5#,0.3元/个,0.3\n"
        )
        payload = {"name": "acceptance.csv", "content_base64": _to_base64(csv_text.encode("utf-8"))}
        result = parse_sheet_items_from_payload(payload)
        names = [row["name"] for row in result["items"]]
        self.assertNotIn("外侧使用主面料)", names)
        self.assertNotIn("肩带（内侧为黑色网布", names)
        self.assertIn("普通拉头", names)
        self.assertTrue(any("插扣" in n for n in names))
        self.assertFalse(any("胸带调节扣 2个 猪鼻扣" in n for n in names))


if __name__ == "__main__":
    unittest.main()
