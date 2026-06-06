from __future__ import annotations

import unittest

from request_intent_router import (
    INTENT_COMPARE_QUOTE,
    INTENT_CONSULT_MATERIAL,
    INTENT_EXPLAIN_PRICE,
    INTENT_FALLBACK_GENERAL,
    INTENT_GENERATE_QUOTE,
    INTENT_MODIFY_PARAMS,
    INTENT_NEGOTIATE_PRICE,
    ROUTE_ADMIN_ACTION,
    ROUTE_CAPABILITY_HELP,
    ROUTE_CLARIFY,
    ROUTE_COMPARE_EXPLAIN,
    ROUTE_EXPLAIN,
    ROUTE_QA,
    ROUTE_QUOTE,
    ROUTE_QUOTE_PATCH,
    route_quote_request,
)


class RequestIntentRouterTest(unittest.TestCase):
    def test_upload_routes_to_quote(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u5e2e\u6211\u6839\u636e\u8fd9\u4e2a\u8868\u76f4\u63a5\u62a5\u4ef7"},
            has_upload=True,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QUOTE)
        self.assertEqual(route.as_dict()["dialog_intent"], INTENT_GENERATE_QUOTE)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_upload_with_explain_text_routes_to_clarify_without_active_quote(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u4e3a\u4ec0\u4e48\u56fe\u4e00\u662f\u4e1a\u52a1\u5458\u7b97\u7684\u4f60\u8ddf\u4ed6\u7b97\u7684\u4e0d\u4e00\u6837"},
            has_upload=True,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_CLARIFY)
        self.assertGreaterEqual(route.route_confidence, 0.7)

    def test_upload_with_compare_text_routes_to_compare_with_active_quote(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u4e3a\u4ec0\u4e48\u56fe\u4e00\u662f\u4e1a\u52a1\u5458\u7b97\u7684\u4f60\u8ddf\u4ed6\u7b97\u7684\u4e0d\u4e00\u6837"},
            has_upload=True,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_COMPARE_EXPLAIN)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_packaging_price_change_routes_to_quote_patch(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u7bb1\u5b50\u63625\u5143\u4e00\u4e2a\u90a3\u4e48\u6210\u672c\u4ef7\u662f\u591a\u5c11"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_QUOTE_PATCH)
        self.assertEqual(route.as_dict()["dialog_intent"], INTENT_MODIFY_PARAMS)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_quantity_change_routes_to_quote_patch(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u6570\u91cf\u6539300\u4ef6"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_QUOTE_PATCH)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_compare_routes_to_compare_explain_with_active_quote(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u4e3a\u4ec0\u4e48\u4e1a\u52a1\u5458\u7b9769.2\u4f60\u7b9759.77"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_COMPARE_EXPLAIN)
        self.assertEqual(route.as_dict()["dialog_intent"], INTENT_COMPARE_QUOTE)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_explain_routes_to_explain_with_active_quote(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u8fd9\u4e2a\u62a5\u4ef7\u662f\u600e\u4e48\u7b97\u7684"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_EXPLAIN)
        self.assertEqual(route.as_dict()["dialog_intent"], INTENT_EXPLAIN_PRICE)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_material_question_routes_to_qa(self) -> None:
        route = route_quote_request(
            {"user_prompt": "600D\u5854\u4e1d\u9686\u662f\u4ec0\u4e48\u6750\u6599"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)
        self.assertEqual(route.as_dict()["dialog_intent"], INTENT_CONSULT_MATERIAL)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_backpack_consulting_routes_to_qa(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u65c5\u884c\u80cc\u5305\u9762\u6599\u600e\u4e48\u9009\u66f4\u8010\u78e8"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_unclear_price_without_context_routes_to_clarify(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u8fd9\u4e2a\u591a\u5c11\u94b1"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_CLARIFY)
        self.assertEqual(route.as_dict()["dialog_intent"], INTENT_FALLBACK_GENERAL)
        self.assertGreaterEqual(route.route_confidence, 0.45)
        self.assertLess(route.route_confidence, 0.75)

    def test_admin_kb_question_routes_to_admin_action(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u4ef7\u683c\u5e93\u600e\u4e48\u66f4\u65b0"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_ADMIN_ACTION)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_capability_question_routes_to_capability_help(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u4f60\u6709\u54ea\u4e9b\u529f\u80fd"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_CAPABILITY_HELP)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_compare_without_active_quote_routes_to_clarify(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u522b\u4eba\u62a569.2\uff0c\u4f60\u7b97\u7684\u5dee\u5728\u54ea"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_CLARIFY)
        self.assertEqual(route.route_reason, "compare_needs_active_quote_or_targets")

    def test_compare_amount_routes_to_compare_explain_with_active_quote(self) -> None:
        route = route_quote_request(
            {"user_prompt": "\u522b\u4eba\u62a569.2\uff0c\u4f60\u7b9750.36\uff0c\u5dee\u5728\u54ea"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_COMPARE_EXPLAIN)
        self.assertEqual(route.route_reason, "active_quote_with_compare_signal")

    def test_negotiate_routes_to_qa_with_business_intent(self) -> None:
        route = route_quote_request(
            {"user_prompt": "客户觉得太贵了，有没有降档或国产替代方案"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)
        self.assertEqual(route.as_dict()["dialog_intent"], INTENT_NEGOTIATE_PRICE)
        self.assertGreaterEqual(route.route_confidence, 0.75)

    def test_high_price_explain_with_active_quote(self) -> None:
        route = route_quote_request(
            {"user_prompt": "这个报价为什么这么高"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertEqual(route.route_intent, ROUTE_EXPLAIN)

    def test_cheaper_material_with_active_quote_routes_patch(self) -> None:
        route = route_quote_request(
            {"user_prompt": "换成便宜一点的材料会便宜多少"},
            has_upload=False,
            has_active_quote=True,
        )
        self.assertIn(route.route_intent, {ROUTE_QUOTE_PATCH, ROUTE_QA})

    def test_substitute_without_quote_routes_qa(self) -> None:
        route = route_quote_request(
            {"user_prompt": "这个材料有没有替代方案"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)

    def test_send_to_customer_without_quote_routes_qa(self) -> None:
        route = route_quote_request(
            {"user_prompt": "这个报价能不能发给客户"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)

    def test_customer_explain_without_quote_routes_qa(self) -> None:
        route = route_quote_request(
            {"user_prompt": "客户问为什么贵怎么解释"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)

    def test_sheet_risk_without_quote_routes_qa(self) -> None:
        route = route_quote_request(
            {"user_prompt": "这张表有什么风险"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)

    def test_field_meaning_without_quote_routes_qa(self) -> None:
        route = route_quote_request(
            {"user_prompt": "这个字段是什么意思"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)


if __name__ == "__main__":
    unittest.main()
