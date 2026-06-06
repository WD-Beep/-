"""message_intent：报价解释类追问路由（不重算）。"""
from __future__ import annotations

import unittest

from message_intent import classify_intent, should_explain_quote_without_requote


class MessageIntentExplainTest(unittest.TestCase):
    def test_dispute_classified_follow_up_with_session(self) -> None:
        self.assertEqual(
            classify_intent(
                "为什么你跟我算的不一样",
                has_new_upload=False,
                has_session_quote=True,
            ),
            "FOLLOW_UP",
        )

    def test_should_explain_dispute_and_how(self) -> None:
        self.assertTrue(should_explain_quote_without_requote("为什么你跟我算的不一样"))
        self.assertTrue(should_explain_quote_without_requote("你怎么算的"))
        self.assertTrue(should_explain_quote_without_requote("成本构成拆解一下"))

    def test_quantity_price_not_explain_only(self) -> None:
        self.assertFalse(should_explain_quote_without_requote("500件多少钱"))

    def test_business_compare_should_explain(self) -> None:
        self.assertTrue(
            should_explain_quote_without_requote("为什么业务员算69.2你算59.77")
        )
        self.assertTrue(should_explain_quote_without_requote("加工费怎么来的"))


if __name__ == "__main__":
    unittest.main()
