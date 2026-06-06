"""图片 + 尺寸文字报价流程。"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from material_inference import SOURCE_IMAGE
from material_row_validity import should_skip_knowledge_learn_row
from photo_quote_flow import (
    SOURCE_USER_EXPLICIT,
    assess_photo_quote_prerequisites,
    build_photo_quote_clarify_response,
    build_user_explicit_bom_rows,
    is_photo_quote_candidate,
    mark_image_inferred_row,
    merge_photo_bom_draft,
    run_photo_quote_pipeline,
    summarize_photo_quote_sources,
)
from quote_engine import calculate_quote

ROOT_TEXT = (
    "我要报价这个斜挎包，尺寸 37×12×17cm，数量 500 个，面料 210D 涤纶，"
    "有里布，一个主拉链，一个前袋拉链，普通肩带，常规包装。"
)


class PhotoQuotePrerequisiteTest(unittest.TestCase):
    def test_image_only_without_dimensions_asks_clarify(self) -> None:
        ready, missing, _ = assess_photo_quote_prerequisites("帮我报价这个包")
        self.assertFalse(ready)
        self.assertTrue(any("长宽高" in x for x in missing))

    def test_image_with_full_text_ready(self) -> None:
        ready, missing, fields = assess_photo_quote_prerequisites(ROOT_TEXT)
        self.assertTrue(ready, msg=missing)
        self.assertEqual(fields.get("quantity"), 500)
        self.assertEqual(fields["product_size"].get("LCM"), 37.0)

    def test_clarify_response_shape(self) -> None:
        resp = build_photo_quote_clarify_response(["成品长宽高"], "仅图片")
        self.assertEqual(resp.get("reply_type"), "photo_quote_clarify")
        self.assertFalse(resp.get("quote_ready"))


class PhotoQuotePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PHOTO_QUOTE_FORCE_RULE_VISION"] = "1"

    def tearDown(self) -> None:
        os.environ.pop("PHOTO_QUOTE_FORCE_RULE_VISION", None)

    def test_pipeline_builds_bom_draft(self) -> None:
        ready, missing, fields = assess_photo_quote_prerequisites(ROOT_TEXT)
        self.assertTrue(ready, msg=missing)
        items, meta, structure_text, status = run_photo_quote_pipeline(
            (("image/jpeg", "aGVsbG8="),),
            ROOT_TEXT,
            fields,
        )
        self.assertGreaterEqual(len(items), 4)
        self.assertTrue(meta.get("photo_quote_flow"))
        self.assertIn("图片", structure_text)
        self.assertTrue(status.get("vision_mode") or status.get("vision_fallback"))

    def test_image_inferred_rows_flagged(self) -> None:
        row = mark_image_inferred_row({"name": "扣具（图片结构推断）", "unit_price": "2元/个"})
        self.assertEqual(row.get("source_type"), SOURCE_IMAGE)
        self.assertTrue(row.get("inferred_by_ai"))
        self.assertTrue(row.get("pricing_review_required"))
        self.assertIn("图片推理", str(row.get("calc_note") or ""))

    def test_user_explicit_rows_flagged(self) -> None:
        _, _, fields = assess_photo_quote_prerequisites(ROOT_TEXT)
        user_rows = build_user_explicit_bom_rows(ROOT_TEXT, fields)
        self.assertTrue(user_rows)
        self.assertTrue(all(r.get("source_type") == SOURCE_USER_EXPLICIT for r in user_rows))

    def test_image_inferred_skips_price_kb_learn(self) -> None:
        row = mark_image_inferred_row({"name": "拉链拉头", "unit_price": "1.2元/个", "usage": "2个"})
        self.assertTrue(should_skip_knowledge_learn_row(row))

    @patch("kimi_client.complete_demand_quote")
    def test_photo_items_enter_quote_engine(self, mock_complete) -> None:
        ready, missing, fields = assess_photo_quote_prerequisites(ROOT_TEXT)
        self.assertTrue(ready, msg=missing)
        items, _, _, _ = run_photo_quote_pipeline((("image/jpeg", "aGVsbG8="),), ROOT_TEXT, fields)

        def _passthrough(**kwargs):
            rows = kwargs.get("items") or []
            filled = []
            for r in rows:
                nr = dict(r)
                if str(nr.get("usage") or "-").strip() in {"", "-"}:
                    nr["usage"] = "1"
                if str(nr.get("unit_price") or "-").strip() in {"", "-"}:
                    nr["unit_price"] = "10元/㎡"
                    nr["unit_price_ai"] = True
                nr["amount"] = 10.0
                filled.append(nr)
            return filled, {"ok": True}

        mock_complete.side_effect = _passthrough
        from photo_quote_flow import preserve_photo_row_source_markers

        before = list(items)
        after, _ = mock_complete(
            product={"name": "斜挎包", "type": "", "size": "37×12×17cm"},
            items=items,
            inline_prices=[],
            structure_text="包型：斜挎包",
            user_prompt=ROOT_TEXT,
        )
        merged = preserve_photo_row_source_markers(before, after)
        payload = {
            "product_name": "斜挎包",
            "quantities": [500],
            "items": merged,
            "processing_fee": 5.0,
        }
        result = calculate_quote(payload)
        self.assertTrue(result.get("tiers"))
        self.assertGreater(len(result.get("detail_rows") or []), 0)

    def test_merge_dedupes_user_and_vision_names(self) -> None:
        user = build_user_explicit_bom_rows(ROOT_TEXT, assess_photo_quote_prerequisites(ROOT_TEXT)[2])
        vision = [mark_image_inferred_row({"name": "扣具（图片结构推断）"})]
        merged = merge_photo_bom_draft(user, vision)
        keys = {str(r.get("name") or "") for r in merged}
        self.assertGreater(len(keys), len(user))


class PhotoQuoteSourceSummaryTest(unittest.TestCase):
    def test_summarize_sources(self) -> None:
        rows = [
            {"source_type": SOURCE_USER_EXPLICIT, "kb_hit": False},
            {"source_type": SOURCE_IMAGE, "kb_hit": False, "unit_price_ai": True},
            {"kb_hit": True, "source": "kb"},
        ]
        summary = summarize_photo_quote_sources(rows)
        self.assertEqual(summary["user_explicit_count"], 1)
        self.assertEqual(summary["image_inferred_count"], 1)
        self.assertEqual(summary["kb_count"], 1)


class PhotoQuoteCandidateTest(unittest.TestCase):
    def test_candidate_requires_vision_and_intent(self) -> None:
        self.assertTrue(
            is_photo_quote_candidate(ROOT_TEXT, has_uploaded_sheet=False, vision_count=1)
        )
        self.assertFalse(
            is_photo_quote_candidate(ROOT_TEXT, has_uploaded_sheet=True, vision_count=1)
        )
        self.assertFalse(
            is_photo_quote_candidate("", has_uploaded_sheet=False, vision_count=1)
        )


if __name__ == "__main__":
    unittest.main()
