"""quote_agent LangGraph surface and local-only guarantees."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from quote_agent import nodes
from quote_agent.graph import invoke_quote_agent
from quote_engine import calculate_quote


def _payload() -> dict:
    return {
        "items": [
            {"name": "主面料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0},
            {"name": "里料", "spec": "-", "usage": "1码", "unit_price": "5元/码", "amount": 5.0},
        ],
        "quantities": [300],
        "gross_margin_rate": 0.35,
        "product_name": "测试包",
    }


class QuoteAgentGraphTest(unittest.TestCase):
    def test_required_nodes_are_exposed(self) -> None:
        for name in (
            "load_session_context",
            "understand_user_request",
            "validate_context",
            "plan_actions",
            "execute_quote_tools",
            "decide_commit_mode",
            "update_session",
            "build_response",
        ):
            self.assertTrue(callable(getattr(nodes, name)))

    def test_no_context_requests_return_natural_prompt(self) -> None:
        for msg in ("换成尼龙试试", "500件呢", "你怎么算的"):
            out = invoke_quote_agent(
                sid="sid-empty",
                user_message=msg,
                session_context={},
                llm_status={},
                memory={},
                get_payload_for_quote=lambda _sid, _qid: None,
                get_last_quote_result=lambda _sid, _qid: None,
                set_current_quote=lambda *args, **kwargs: None,
            )
            self.assertFalse(out.get("quote_ready"))
            self.assertIn("上一单报价", str(out.get("assistant_message") or ""))

    @patch("quotation_agent.moonshot_client.chat_completions", side_effect=RuntimeError("http_401"))
    @patch("quotation_agent.moonshot_client.moonshot_api_key", return_value="bad-key")
    def test_process_card_is_local_when_kimi_auth_fails(
        self,
        _mock_key: object,
        _mock_chat: object,
    ) -> None:
        payload = _payload()
        quote = calculate_quote(payload)
        out = invoke_quote_agent(
            sid="sid-one",
            user_message="你怎么算的",
            session_context={"currentQuoteId": "q1"},
            llm_status={"kimi": "auth_failed"},
            memory={},
            get_payload_for_quote=lambda _sid, _qid: copy.deepcopy(payload),
            get_last_quote_result=lambda _sid, _qid: copy.deepcopy(quote),
            set_current_quote=lambda *args, **kwargs: None,
        )
        self.assertEqual(out.get("reply_type"), "process_card")
        blob = json.dumps(out.get("process") or {}, ensure_ascii=False)
        self.assertIn("物料合计", blob)
        self.assertNotIn("Invalid Authentication", blob)
        self.assertEqual((out.get("llm_status") or {}).get("agent"), "langgraph_quote_agent")

    def test_packaging_price_patch_recalculates_from_active_quote(self) -> None:
        payload = {
            "items": [
                {"name": "主料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0},
                {"name": "外纸箱/包装费", "spec": "-", "usage": "1个", "unit_price": "8元/个", "amount": 8.0},
            ],
            "quantities": [300],
            "gross_margin_rate": 0.30,
            "processing_fee": 15.0,
            "system_overhead": 4.0,
            "product_name": "测试包",
        }
        base_quote = calculate_quote(payload)
        out = invoke_quote_agent(
            sid="sid-packaging",
            user_message="箱子换5元一个那么成本价是多少",
            session_context={"currentQuoteId": "q-packaging"},
            llm_status={},
            memory={},
            get_payload_for_quote=lambda _sid, _qid: copy.deepcopy(payload),
            get_last_quote_result=lambda _sid, _qid: copy.deepcopy(base_quote),
            set_current_quote=lambda *args, **kwargs: None,
        )

        self.assertTrue(out.get("quote_ready"))
        self.assertEqual(out.get("intent"), "agent_trial")
        self.assertAlmostEqual(float(out.get("material_total") or 0), 15.0, places=2)
        self.assertAlmostEqual((out.get("metadata") or {}).get("cost_delta_per_piece"), -3.0, places=2)
        self.assertTrue((out.get("metadata") or {}).get("is_price_patch_calc"))
        self.assertEqual((out.get("metadata") or {}).get("price_patch_new_unit_price"), "5元/个")
        patched_rows = [r for r in out.get("detail_rows", []) if "纸箱" in str(r.get("name") or "")]
        self.assertEqual(len(patched_rows), 1)
        self.assertAlmostEqual(float(patched_rows[0].get("amount") or 0), 5.0, places=2)

    def test_packaging_price_patch_overrides_system_packaging_estimate(self) -> None:
        """无显式包装行时，引擎按 product_size 估算 OPP/基础包装（非外箱 8 元/个）。

        口径见 quote_engine._estimate_packaging_addon：45×30×17cm 属「偏大基础包装」→ 2.00 元/个；
        主料 10 + 系统估算 2 = material_total 12.00。用户改箱价 5 元/个 → 15.00，delta +3。
        """
        payload = {
            "items": [
                {"name": "主料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0},
            ],
            "product_size": {"length_cm": 45, "width_cm": 30, "height_cm": 17},
            "quantities": [300],
            "processing_fee": 15.0,
            "system_overhead": 4.0,
        }
        base_quote = calculate_quote(payload)
        self.assertAlmostEqual(float(base_quote.get("material_total") or 0), 12.0, places=2)
        pkg_rows = [
            r
            for r in base_quote.get("detail_rows", [])
            if "包装" in str(r.get("name") or "") or "纸箱" in str(r.get("name") or "")
        ]
        self.assertEqual(len(pkg_rows), 1)
        self.assertAlmostEqual(float(pkg_rows[0].get("amount") or 0), 2.0, places=2)

        out = invoke_quote_agent(
            sid="sid-packaging-estimate",
            user_message="箱子换5元一个那么成本价是多少",
            session_context={"currentQuoteId": "q-packaging-estimate"},
            llm_status={},
            memory={},
            get_payload_for_quote=lambda _sid, _qid: copy.deepcopy(payload),
            get_last_quote_result=lambda _sid, _qid: copy.deepcopy(base_quote),
            set_current_quote=lambda *args, **kwargs: None,
        )

        self.assertTrue(out.get("quote_ready"))
        self.assertAlmostEqual(float(out.get("material_total") or 0), 15.0, places=2)
        self.assertAlmostEqual((out.get("metadata") or {}).get("cost_delta_per_piece"), 3.0, places=2)
        self.assertEqual(
            (out.get("metadata") or {}).get("price_patch_old_unit_price"),
            "2.00元/个",
        )

    def test_packaging_patch_returns_quote_patch_envelope(self) -> None:
        payload = {
            "items": [
                {"name": "主料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0},
                {"name": "外纸箱", "spec": "-", "usage": "1个", "unit_price": "8元/个", "amount": 8.0},
            ],
            "quantities": [300],
            "processing_fee": 15.0,
            "system_overhead": 4.0,
            "gross_margin_rate": 0.30,
        }
        base_quote = calculate_quote(payload)
        out = invoke_quote_agent(
            sid="sid-qp",
            user_message="箱子换5元一个那么成本价是多少",
            session_context={"currentQuoteId": "q-qp"},
            llm_status={},
            memory={},
            get_payload_for_quote=lambda _sid, _qid: copy.deepcopy(payload),
            get_last_quote_result=lambda _sid, _qid: copy.deepcopy(base_quote),
            set_current_quote=lambda *args, **kwargs: None,
        )
        qp = out.get("quote_patch") or {}
        self.assertEqual(qp.get("patch_type"), "packaging_unit_price")
        self.assertIn("original_cost", qp)
        self.assertIn("new_cost", qp)
        self.assertIn("cost_delta", qp)
        self.assertIn("原包装费", str(out.get("assistant_message") or ""))

    def test_material_unit_price_patch_from_active_quote(self) -> None:
        payload = {
            "items": [
                {"name": "600D塔丝隆", "spec": "-", "usage": "2码", "unit_price": "10元/码", "amount": 20.0},
                {"name": "里料", "spec": "-", "usage": "1码", "unit_price": "5元/码", "amount": 5.0},
            ],
            "quantities": [500],
            "processing_fee": 15.0,
            "system_overhead": 4.0,
            "gross_margin_rate": 0.30,
        }
        base_quote = calculate_quote(payload)
        out = invoke_quote_agent(
            sid="sid-mat",
            user_message="600D改12元/码",
            session_context={"currentQuoteId": "q-mat"},
            llm_status={},
            memory={},
            get_payload_for_quote=lambda _sid, _qid: copy.deepcopy(payload),
            get_last_quote_result=lambda _sid, _qid: copy.deepcopy(base_quote),
            set_current_quote=lambda *args, **kwargs: None,
        )
        self.assertEqual(out.get("intent"), "agent_trial")
        qp = out.get("quote_patch") or {}
        self.assertEqual(qp.get("patch_type"), "material_unit_price")
        self.assertEqual(qp.get("target_row"), "600D塔丝隆")
        self.assertAlmostEqual(float(qp.get("new_value") or 0), 24.0, places=2)
        self.assertGreater(float(qp.get("new_cost") or 0), float(qp.get("original_cost") or 0))

    def test_material_patch_missing_row_asks_confirmation(self) -> None:
        payload = {
            "items": [
                {"name": "主料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0},
            ],
            "quantities": [500],
            "processing_fee": 15.0,
            "system_overhead": 4.0,
        }
        base_quote = calculate_quote(payload)
        out = invoke_quote_agent(
            sid="sid-mat-miss",
            user_message="600D改12元/码",
            session_context={"currentQuoteId": "q-miss"},
            llm_status={},
            memory={},
            get_payload_for_quote=lambda _sid, _qid: copy.deepcopy(payload),
            get_last_quote_result=lambda _sid, _qid: copy.deepcopy(base_quote),
            set_current_quote=lambda *args, **kwargs: None,
        )
        self.assertFalse(out.get("quote_ready"))
        self.assertIn("600D", str(out.get("assistant_message") or ""))
        self.assertIn("确认", str(out.get("assistant_message") or ""))

    def test_quantity_patch_returns_quote_patch(self) -> None:
        payload = {
            "items": [
                {"name": "主料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0},
            ],
            "quantities": [500],
            "processing_fee": 15.0,
            "system_overhead": 4.0,
            "gross_margin_rate": 0.30,
        }
        base_quote = calculate_quote(payload)
        out = invoke_quote_agent(
            sid="sid-qty",
            user_message="数量改300件",
            session_context={"currentQuoteId": "q-qty"},
            llm_status={},
            memory={},
            get_payload_for_quote=lambda _sid, _qid: copy.deepcopy(payload),
            get_last_quote_result=lambda _sid, _qid: copy.deepcopy(base_quote),
            set_current_quote=lambda *args, **kwargs: None,
        )
        self.assertEqual(out.get("intent"), "agent_trial")
        qp = out.get("quote_patch") or {}
        self.assertEqual(qp.get("patch_type"), "quantity")
        self.assertEqual(qp.get("old_value"), 500)
        self.assertEqual(qp.get("new_value"), 300)
        self.assertIn("assistant_message", out)
        self.assertIn("300件", str(out.get("assistant_message") or ""))

    def test_processing_fee_patch_returns_quote_patch(self) -> None:
        payload = {
            "items": [
                {"name": "主料", "spec": "-", "usage": "1码", "unit_price": "10元/码", "amount": 10.0},
            ],
            "quantities": [500],
            "processing_fee": 15.0,
            "system_overhead": 4.0,
            "gross_margin_rate": 0.30,
        }
        base_quote = calculate_quote(payload)
        out = invoke_quote_agent(
            sid="sid-proc",
            user_message="加工费按20算",
            session_context={"currentQuoteId": "q-proc"},
            llm_status={},
            memory={},
            get_payload_for_quote=lambda _sid, _qid: copy.deepcopy(payload),
            get_last_quote_result=lambda _sid, _qid: copy.deepcopy(base_quote),
            set_current_quote=lambda *args, **kwargs: None,
        )
        qp = out.get("quote_patch") or {}
        self.assertEqual(qp.get("patch_type"), "processing_fee")
        self.assertAlmostEqual(float(qp.get("cost_delta") or 0), 5.0, places=2)
        self.assertIn("20", str(out.get("assistant_message") or ""))


if __name__ == "__main__":
    unittest.main()
