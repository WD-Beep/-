"""报价解释模式：不重新报价，只读上一单结果。"""
from __future__ import annotations

import copy
import unittest

from quote_agent.graph import invoke_quote_agent
from quote_engine import calculate_quote
from quote_explain import explain_quote_difference


def _sample_quote() -> dict:
    payload = {
        "items": [
            {"name": "600D塔丝隆", "spec": "-", "usage": "2码", "unit_price": "10元/码", "amount": 20.0},
            {"name": "外纸箱", "spec": "-", "usage": "1个", "unit_price": "8元/个", "amount": 8.0},
        ],
        "quantities": [500],
        "processing_fee": 15.0,
        "system_overhead": 4.0,
        "gross_margin_rate": 0.30,
        "product_name": "测试包",
    }
    return calculate_quote(payload)


class ExplainQuoteDifferenceTest(unittest.TestCase):
    def test_business_vs_system_delta(self) -> None:
        quote = _sample_quote()
        tier = quote["tiers"][0]
        system_exw = float(tier["exw_price"])
        business = round(system_exw + 9.43, 2)
        body = explain_quote_difference(
            quote,
            user_question=f"为什么业务员算{business}你算{system_exw:.2f}",
        )
        ext = body.get("external_comparison") or {}
        self.assertAlmostEqual(float(ext.get("delta") or 0), 9.43, places=2)
        self.assertAlmostEqual(float(ext.get("external_amount") or 0), business, places=2)
        self.assertAlmostEqual(float(ext.get("system_amount") or 0), system_exw, places=2)
        msg = str(body.get("assistant_message") or "")
        self.assertIn("9.43", msg)
        self.assertIn("差额", msg)
        self.assertGreater(len(body.get("gap_sources_ranked") or []), 0)

    def test_processing_fee_component_question(self) -> None:
        quote = _sample_quote()
        body = explain_quote_difference(quote, user_question="加工费怎么来的")
        msg = str(body.get("assistant_message") or "")
        self.assertIn("加工费", msg)
        self.assertIn("15", msg)

    def test_largest_material_gap_question(self) -> None:
        quote = _sample_quote()
        body = explain_quote_difference(quote, user_question="哪个材料差距最大")
        ranked = body.get("material_rows_ranked") or []
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["name"], "600D塔丝隆")

    def test_agent_explain_does_not_requote(self) -> None:
        quote = _sample_quote()
        tier = quote["tiers"][0]
        system_exw = float(tier["exw_price"])
        business = round(system_exw + 9.43, 2)
        payload = {
            "items": quote.get("detail_rows"),
            "quantities": [500],
            "processing_fee": 15.0,
            "system_overhead": 4.0,
            "gross_margin_rate": 0.30,
        }
        base_qid = "q-explain"
        calls = {"commit": 0}

        def _set_quote(*args, **kwargs):
            calls["commit"] += 1

        out = invoke_quote_agent(
            sid="sid-explain",
            user_message=f"为什么业务员算{business}你算{system_exw:.2f}",
            session_context={"currentQuoteId": base_qid},
            llm_status={},
            memory={},
            get_payload_for_quote=lambda _s, _q: copy.deepcopy(payload),
            get_last_quote_result=lambda _s, _q: copy.deepcopy(quote),
            set_current_quote=_set_quote,
        )
        self.assertFalse(out.get("quote_ready"))
        self.assertEqual(out.get("intent"), "QUOTE_EXPLAIN")
        self.assertEqual(out.get("reply_type"), "quote_explain")
        self.assertEqual(calls["commit"], 0)
        self.assertIn("差额", str(out.get("assistant_message") or ""))
        self.assertIn("9.43", str(out.get("assistant_message") or ""))


if __name__ == "__main__":
    unittest.main()
