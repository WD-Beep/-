"""quotation_agent LangGraph 冒烟测试（未安装 langgraph 时跳过）。"""
from __future__ import annotations

import unittest
from unittest.mock import patch


class QuotationAgentSmokeTest(unittest.TestCase):
    def test_chitchat_turn(self) -> None:
        try:
            from quotation_agent import empty_quotation_state, invoke_turn
        except ImportError:
            self.skipTest("langgraph/langchain-core 未安装")

        s = empty_quotation_state()
        out = invoke_turn(s, user_message="你好")
        self.assertIsInstance(out.get("chat_history"), list)
        self.assertTrue(any(x.get("role") == "assistant" for x in out["chat_history"]))

    def test_parameter_then_calculate(self) -> None:
        try:
            from quotation_agent import empty_quotation_state, invoke_turn
        except ImportError:
            self.skipTest("langgraph/langchain-core 未安装")

        s = empty_quotation_state()
        s["parameters"] = {
            "items": [
                {
                    "name": "面料",
                    "spec": "-",
                    "usage": "1码",
                    "unit_price": "10元/码",
                    "amount": 10.0,
                },
            ],
        }
        out = invoke_turn(s, user_message="数量改成500个")
        calc = out.get("calculation_result") or {}
        self.assertNotIn("error", calc)
        self.assertAlmostEqual(float(calc.get("material_total", 0)), 10.0, places=2)

    def test_route_after_vision(self) -> None:
        try:
            from quotation_agent.nodes import route_after_vision
        except ImportError:
            self.skipTest("langgraph/langchain-core 未安装")

        self.assertEqual(route_after_vision({"parameters": {}}), "generate_response")
        self.assertEqual(route_after_vision({"parameters": {"items": []}}), "generate_response")
        self.assertEqual(
            route_after_vision({"parameters": {"items": [{"name": "面料"}]}}),
            "calculator",
        )

    @patch("quotation_agent.nodes._classify_intent_llm", return_value=None)
    def test_intent_router_quote_explain(self, _mock_llm: object) -> None:
        from quotation_agent import empty_quotation_state
        from quotation_agent.nodes import intent_router_node

        s = empty_quotation_state()
        s["calculation_result"] = {"material_total_text": "10"}
        out = intent_router_node({**s, "user_message": "你怎么算的"})
        self.assertEqual(out.get("last_intent"), "quote_explain")

    @patch("quotation_agent.nodes.chat_completions", return_value="单元测试解释")
    @patch("quotation_agent.nodes.moonshot_api_key", return_value="fake-key")
    @patch("quotation_agent.nodes._classify_intent_llm", return_value=None)
    def test_invoke_quote_explain_path(self, _mock_llm: object, _mock_key: object, _mock_chat: object) -> None:
        try:
            from quotation_agent import empty_quotation_state, invoke_turn
        except ImportError:
            self.skipTest("langgraph/langchain-core 未安装")

        s = empty_quotation_state()
        s["calculation_result"] = {"material_total_text": "17.90元", "tiers": [{"quantity": 500}]}
        s["parameters"] = {"items": [{"name": "面料", "amount": 1}]}
        out = invoke_turn(s, user_message="为什么跟你算的不一样")
        self.assertEqual(out.get("last_intent"), "quote_explain")
        self.assertIn("单元测试解释", out.get("final_reply") or "")
if __name__ == "__main__":
    unittest.main()
