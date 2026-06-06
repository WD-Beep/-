"""推理待核结构件/工艺件用量单位（禁止默认 1套）。"""
from __future__ import annotations

import unittest

from kimi_client import prepare_structure_rows_for_market_estimate
from material_inference import (
    PENDING_INFERENCE_USAGE_FALLBACK,
    pending_inference_usage_label,
)


class PendingInferenceUsageTest(unittest.TestCase):
    def test_pending_labels_by_component_name(self) -> None:
        cases = {
            "侧袋（推理待核）": "几个",
            "背垫（推理待核）": "几片",
            "提手（推理待核）": "几条",
            "隔层（推理待核）": "几片",
            "工艺费（推理待核）": "几道工序",
        }
        for name, expected in cases.items():
            self.assertEqual(pending_inference_usage_label(name), expected, name)

    def test_explicit_quantity_preserved(self) -> None:
        self.assertEqual(pending_inference_usage_label("侧袋 2个（推理待核）"), "2个")
        self.assertEqual(pending_inference_usage_label("6分D扣 2个"), "2个")

    def test_unknown_inference_falls_back_to_pending_fill(self) -> None:
        self.assertEqual(
            pending_inference_usage_label("未知结构件（推理待核）"),
            PENDING_INFERENCE_USAGE_FALLBACK,
        )

    def test_prepare_structure_rows_no_default_one_set(self) -> None:
        items = [
            {
                "name": "背垫（推理待核）",
                "usage": "-",
                "unit_price": "-",
                "inferred_by_ai": True,
                "source_type": "structure_inferred",
                "recognition_status": "candidate_review",
            },
            {
                "name": "6分D扣 2个",
                "usage": "-",
                "unit_price": "-",
                "recognition_status": "split",
                "_source_combined_name": "胸带调节扣 2个6分D扣 2个",
            },
        ]
        out = prepare_structure_rows_for_market_estimate(items)
        by_name = {r["name"]: r for r in out}
        back_pad = by_name["背垫（推理待核）"]
        self.assertEqual(back_pad["usage"], "几片")
        self.assertNotIn("套", str(back_pad["usage"]))
        self.assertEqual(float(back_pad.get("amount") or 0), 0.0)
        buckle = by_name["6分D扣 2个"]
        self.assertEqual(buckle["usage"], "2个")
        self.assertGreater(float(buckle.get("amount") or 0), 0.0)


if __name__ == "__main__":
    unittest.main()
