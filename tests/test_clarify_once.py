"""一句澄清机制。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from clarify_once import (
    build_clarify_response,
    detect_pre_quote_clarify,
    detect_request_clarify,
    is_vague_patch_without_target,
)
from request_intent_router import ROUTE_CLARIFY, ROUTE_QUOTE_PATCH, route_quote_request


class ClarifyOnceTest(unittest.TestCase):
    def test_vague_price_without_context(self) -> None:
        spec = detect_request_clarify(
            "这个多少钱",
            has_upload=False,
            has_active_quote=False,
            route_reason="unclear_quote_request_without_context",
        )
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertIn("上传", spec.message)
        resp = build_clarify_response(spec)
        self.assertEqual(resp["reply_type"], "clarify_question")
        self.assertFalse(resp["quote_ready"])
        self.assertIn("upload_or_bom", resp["missing_fields"])

    def test_vague_patch_without_target(self) -> None:
        self.assertTrue(is_vague_patch_without_target("改成5元"))
        route = route_quote_request(
            {"user_prompt": "改成5元"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_CLARIFY)
        self.assertEqual(route.route_reason, "patch_missing_target")
        spec = detect_request_clarify(
            "改成5元",
            has_upload=False,
            has_active_quote=True,
            route_reason=route.route_reason,
        )
        assert spec is not None
        self.assertIn("哪个材料", spec.message)

    def test_specific_patch_not_clarify(self) -> None:
        route = route_quote_request(
            {"user_prompt": "箱子换5元一个"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_QUOTE_PATCH)

    def test_explain_needs_active_quote(self) -> None:
        spec = detect_request_clarify(
            "为什么业务员算69.2",
            has_upload=False,
            has_active_quote=False,
            route_reason="explain_needs_active_quote",
        )
        assert spec is not None
        self.assertIn("active_quote", spec.missing_fields)

    def test_unit_mismatch_pre_quote_auto_convertible_not_blocked(self) -> None:
        payload = {
            "items": [
                {
                    "name": "面料",
                    "usage": "2㎡",
                    "unit_price": "10元/码",
                    "amount": 20.0,
                    "kb_hit": True,
                }
            ],
            "quantities": [500],
        }
        spec = detect_pre_quote_clarify(payload)
        self.assertIsNone(spec)

    def test_unit_mismatch_pre_quote_irreconcilable_still_blocked(self) -> None:
        payload = {
            "items": [
                {
                    "name": "五金扣具",
                    "usage": "1套",
                    "unit_price": "8元/码",
                    "amount": 8.0,
                }
            ],
            "quantities": [500],
        }
        spec = detect_pre_quote_clarify(payload)
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.reason, "unit_usage_mismatch")

    @patch("price_kb.get_price_kb")
    def test_kb_ambiguous_pre_quote(self, mock_get_kb: MagicMock) -> None:
        ent1 = MagicMock()
        ent1.raw_name = "600D塔丝隆A"
        ent1.raw_spec = "150"
        ent1.raw_price = "12元/码"
        ent2 = MagicMock()
        ent2.raw_name = "600D塔丝隆B"
        ent2.raw_spec = "160"
        ent2.raw_price = "13元/码"
        h1 = MagicMock(entry=ent1, score=0.82)
        h2 = MagicMock(entry=ent2, score=0.80)
        kb = MagicMock()
        kb.lookup_ranked.return_value = [h1, h2]
        mock_get_kb.return_value = kb
        spec = detect_pre_quote_clarify(
            {
                "items": [{"name": "600D塔丝隆", "spec": "-", "usage": "2码", "amount": 0}],
                "quantities": [500],
            }
        )
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.reason, "price_kb_ambiguous")
        self.assertIn("600D", spec.message)


if __name__ == "__main__":
    unittest.main()
