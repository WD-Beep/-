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

    def test_format_exception_reason_missing_price(self) -> None:
        from kb_data_quality import format_exception_reason_label, KbDataQualityVerdict

        verdict = judge_kb_insert_candidate("NEW_BUCKLE", "777ZZ", "-")
        self.assertEqual(format_exception_reason_label(verdict), "缺少价格")

    def test_drop_piece_names(self) -> None:
        for name in ("前袋", "网袋", "隔层", "前片"):
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


if __name__ == "__main__":
    unittest.main()
