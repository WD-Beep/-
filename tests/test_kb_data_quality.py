from __future__ import annotations

import unittest

from kb_data_quality import (
    KB_ACTION_AUTO,
    KB_ACTION_DROP,
    KB_ACTION_REVIEW,
    judge_kb_insert_candidate,
)


class KbDataQualityTest(unittest.TestCase):
    def test_drop_garbage_fragment(self) -> None:
        verdict = judge_kb_insert_candidate("侧面的主面")
        self.assertEqual(verdict.action, KB_ACTION_DROP)
        self.assertEqual(verdict.tier, "garbage")

    def test_drop_description_sentence(self) -> None:
        verdict = judge_kb_insert_candidate("外侧使用主面料)")
        self.assertEqual(verdict.action, KB_ACTION_DROP)

    def test_review_part_description(self) -> None:
        verdict = judge_kb_insert_candidate("肩带（内侧为黑色网布，外侧使用主面料和黑色织带）")
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)

    def test_auto_insert_trusted_material_with_price(self) -> None:
        verdict = judge_kb_insert_candidate(
            "普通拉头",
            "5#",
            "0.3元/个",
            row={"source": "kb", "kb_hit": True},
            kb_hit=True,
        )
        self.assertEqual(verdict.action, KB_ACTION_AUTO)

    def test_review_missing_price(self) -> None:
        verdict = judge_kb_insert_candidate("NEW_BUCKLE", "777ZZ", "-")
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)

    def test_review_ai_estimated_price(self) -> None:
        verdict = judge_kb_insert_candidate(
            "NEW_WEBBING",
            "25MM",
            "0.5/M",
            row={"unit_price_ai": True, "source": "ai"},
        )
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)

    def test_drop_when_recognition_ignored(self) -> None:
        verdict = judge_kb_insert_candidate(
            "外侧使用主面料)",
            row={"recognition_status": "ignored", "recognition_reason": "说明句"},
        )
        self.assertEqual(verdict.action, KB_ACTION_DROP)

    def test_embedded_quantity_name_blocked_from_kb_auto(self) -> None:
        verdict = judge_kb_insert_candidate("黑色拉头*1", "普通拉头", "0.3元/个")
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)
        self.assertIn("数量词", verdict.reason)

    def test_review_suspicious_slider_price(self) -> None:
        verdict = judge_kb_insert_candidate(
            "黑色拉头",
            "普通拉头",
            "60元/个",
            kb_hit=True,
            row={"source": "kb", "kb_hit": True},
        )
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)
        self.assertIn("拉链/拉头单价明显异常", verdict.reason)

    def test_review_suspicious_zipper_price(self) -> None:
        verdict = judge_kb_insert_candidate(
            "金色金属拉链",
            "金色金属拉链",
            "120元/条",
            kb_hit=True,
            row={"source": "kb", "kb_hit": True},
        )
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)
        self.assertIn("拉链/拉头单价明显异常", verdict.reason)

    def test_normal_slider_price_still_auto(self) -> None:
        verdict = judge_kb_insert_candidate(
            "普通拉头",
            "5#",
            "0.3元/个",
            kb_hit=True,
            row={"source": "kb", "kb_hit": True},
        )
        self.assertEqual(verdict.action, KB_ACTION_AUTO)

    def test_normal_zipper_price_still_auto(self) -> None:
        verdict = judge_kb_insert_candidate(
            "5#尼龙拉链",
            "#5",
            "0.3元/条",
            kb_hit=True,
            row={"source": "kb", "kb_hit": True},
        )
        self.assertEqual(verdict.action, KB_ACTION_AUTO)

    def test_format_exception_reason_zipper_outlier(self) -> None:
        from kb_data_quality import format_exception_reason_label

        verdict = judge_kb_insert_candidate("黑色拉头", "普通拉头", "60元/个")
        self.assertEqual(format_exception_reason_label(verdict), "拉链拉头单价异常")

        from kb_data_quality import format_exception_reason_label, KbDataQualityVerdict

        verdict = judge_kb_insert_candidate("NEW_BUCKLE", "777ZZ", "-")
        self.assertEqual(format_exception_reason_label(verdict), "缺少价格")

    def test_drop_piece_names(self) -> None:
        for name in ("前袋", "网袋", "隔层", "前片", "侧片", "合计", "小计"):
            verdict = judge_kb_insert_candidate(name, "19×45", "2元/个")
            self.assertEqual(verdict.action, KB_ACTION_DROP, name)

    def test_drop_system_estimate_packaging_name(self) -> None:
        verdict = judge_kb_insert_candidate("外纸箱/包装费（系统估算）", "系统估算", "2.00元/个")
        self.assertEqual(verdict.action, KB_ACTION_DROP)

    def test_review_hint_exclude_for_part_description(self) -> None:
        from kb_data_quality import classify_exception_review_hint

        name = "肩带（内侧为黑色网布，外侧使用主面料和黑色织带）"
        verdict = judge_kb_insert_candidate(name)
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)
        self.assertEqual(
            classify_exception_review_hint(name, verdict, has_price=False),
            "exclude_suggest",
        )

    def test_special_fee_semantic_mismatch(self) -> None:
        from kb_data_quality import is_material_semantic_mismatch, validate_price_override_target

        self.assertTrue(is_material_semantic_mismatch("拉头烤漆费", "普通拉头"))
        ok, reason = validate_price_override_target("拉头烤漆费", "普通拉头")
        self.assertFalse(ok)
        self.assertIn("特殊费用", reason)


    def test_quote_blocking_marker_constants(self) -> None:
        from price_learn_candidate import AUTO_PENDING_MARKER, QUOTE_BLOCKING_MARKERS, is_quote_blocking_learn_candidate

        self.assertIn(AUTO_PENDING_MARKER, QUOTE_BLOCKING_MARKERS)
        row = {
            "material_name": "五金标准扣具",
            "spec": "常规",
            "new_price": "0.35元/个",
            "status": "pending",
            "exception_status": "open",
            "marker": AUTO_PENDING_MARKER,
        }
        self.assertTrue(is_quote_blocking_learn_candidate(row))


if __name__ == "__main__":
    unittest.main()
