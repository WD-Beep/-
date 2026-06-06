"""dual_intent_route：意图路由 quote / qa / hybrid / clarify + 统一信封。"""
from __future__ import annotations

import copy
import unittest

from dual_intent_route import (
    DUAL_INTENT_CLARIFY,
    DUAL_INTENT_HYBRID,
    DUAL_INTENT_QA,
    DUAL_INTENT_QUOTE,
    DUAL_INTENTS,
    apply_dual_mode_envelope,
    infer_dual_route,
)
from message_intent import classify_intent
from tests.fixtures.dual_intent_responses import (
    ENVELOPE_REQUIRED_KEYS,
    USER_PROMPT_PROCESSING_FEE_RECALC,
    USER_PROMPT_PURE_QUOTE,
    USER_PROMPT_UNCLEAR,
    USER_PROMPT_WHY_EXPENSIVE,
    raw_processing_fee_recalc_response,
    raw_pure_quote_response,
    raw_unclear_response,
    raw_why_expensive_follow_up_explain_response,
    raw_why_expensive_response,
)


def _apply_envelope(raw: dict, *, http_status: int = 200) -> dict:
    resp = copy.deepcopy(raw)
    apply_dual_mode_envelope(resp, trace={"t0": __import__("time").perf_counter()}, http_status=http_status)
    return resp


def assert_envelope_complete(test: unittest.TestCase, resp: dict) -> None:
    for key in ENVELOPE_REQUIRED_KEYS:
        test.assertIn(key, resp, msg=f"missing envelope key: {key}")
    test.assertIn(resp["intent"], DUAL_INTENTS)
    test.assertIsInstance(resp["actions"], list)
    test.assertIsInstance(resp["quote_patch"], dict)
    test.assertIsInstance(resp["confidence"], (int, float))
    test.assertGreaterEqual(float(resp["confidence"]), 0.0)
    test.assertLessEqual(float(resp["confidence"]), 1.0)
    test.assertIsInstance(resp["route_target"], str)
    test.assertTrue(str(resp["route_target"]).strip())
    test.assertIsInstance(resp["latency_ms"], (int, float))
    test.assertGreaterEqual(float(resp["latency_ms"]), 0.0)


class DualIntentRouteUnitTest(unittest.TestCase):
    def test_quote_ready_primary(self) -> None:
        intent, conf, target = infer_dual_route(
            {"quote_ready": True, "intent": "NEW_QUOTE"},
            http_status=200,
        )
        self.assertEqual(intent, DUAL_INTENT_QUOTE)
        self.assertGreater(conf, 0.8)
        self.assertEqual(target, "calculate_quote")

    def test_hybrid_extra_material(self) -> None:
        intent, _, target = infer_dual_route(
            {
                "quote_ready": True,
                "intent": "extra_material_calc",
                "metadata": {"is_extra_material_calc": True},
            },
            http_status=200,
        )
        self.assertEqual(intent, DUAL_INTENT_HYBRID)
        self.assertEqual(target, "follow_up_trial")

    def test_qa_chat_session(self) -> None:
        intent, _, target = infer_dual_route(
            {
                "quote_ready": False,
                "intent": "CHAT",
                "assistant_message": "您好",
            },
            http_status=200,
        )
        self.assertEqual(intent, DUAL_INTENT_QA)
        self.assertEqual(target, "session_chat")

    def test_qa_process_card(self) -> None:
        intent, _, target = infer_dual_route(
            {"quote_ready": False, "reply_type": "process_card"},
            http_status=200,
        )
        self.assertEqual(intent, DUAL_INTENT_QA)
        self.assertEqual(target, "process_card")

    def test_clarify_structure_gate(self) -> None:
        intent, _, target = infer_dual_route(
            {
                "quote_ready": False,
                "reply_type": "structure_confirmation",
            },
            http_status=200,
        )
        self.assertEqual(intent, DUAL_INTENT_CLARIFY)
        self.assertEqual(target, "structure_confirmation_gate")

    def test_clarify_client_error(self) -> None:
        intent, _, target = infer_dual_route(
            {"error": "invalid_material_pricing", "message": "无单价"},
            http_status=400,
        )
        self.assertEqual(intent, DUAL_INTENT_CLARIFY)
        self.assertEqual(target, "invalid_material_pricing")


class DualIntentScenarioTest(unittest.TestCase):
    """五类业务场景：话术 → 模拟业务响应 → 双模式 intent + 信封字段。"""

    def test_scenario_1_pure_quote_request_maps_to_quote(self) -> None:
        self.assertEqual(
            classify_intent(USER_PROMPT_PURE_QUOTE, has_new_upload=False, has_session_quote=False),
            "NEW_QUOTE",
        )
        env = _apply_envelope(raw_pure_quote_response())
        assert_envelope_complete(self, env)
        self.assertEqual(env["intent"], DUAL_INTENT_QUOTE)
        self.assertTrue(env["quote_ready"])
        self.assertEqual(env["route_target"], "calculate_quote")
        self.assertEqual(env["flow_intent"], "NEW_QUOTE")
        self.assertIn(env["quote_id"], "fixture-quote-primary-001")
        self.assertIsInstance(env["tiers"], list)
        self.assertGreater(len(env["tiers"]), 0)

    def test_scenario_2_why_expensive_maps_to_qa_or_hybrid(self) -> None:
        self.assertEqual(
            classify_intent(USER_PROMPT_WHY_EXPENSIVE, has_new_upload=False, has_session_quote=True),
            "CHAT",
        )
        env_chat = _apply_envelope(raw_why_expensive_response())
        assert_envelope_complete(self, env_chat)
        self.assertEqual(env_chat["intent"], DUAL_INTENT_QA)
        self.assertFalse(env_chat["quote_ready"])
        self.assertEqual(env_chat["route_target"], "session_chat")
        self.assertEqual(env_chat["flow_intent"], "CHAT")
        self.assertIn("偏高", env_chat["answer"])

        env_explain = _apply_envelope(raw_why_expensive_follow_up_explain_response())
        assert_envelope_complete(self, env_explain)
        self.assertIn(env_explain["intent"], (DUAL_INTENT_QA, DUAL_INTENT_HYBRID, DUAL_INTENT_CLARIFY))
        self.assertFalse(env_explain["quote_ready"])
        self.assertEqual(env_explain["flow_intent"], "QUOTE_EXPLAIN")
        self.assertTrue(env_explain["answer"])

    def test_scenario_3_processing_fee_change_recalc_maps_to_hybrid(self) -> None:
        self.assertEqual(
            classify_intent(
                USER_PROMPT_PROCESSING_FEE_RECALC,
                has_new_upload=False,
                has_session_quote=True,
            ),
            "FOLLOW_UP",
        )
        env = _apply_envelope(raw_processing_fee_recalc_response())
        assert_envelope_complete(self, env)
        self.assertEqual(env["intent"], DUAL_INTENT_HYBRID)
        self.assertTrue(env["quote_ready"])
        self.assertEqual(env["route_target"], "follow_up_trial")
        self.assertEqual(env["flow_intent"], "agent_trial")
        self.assertIn("22", env["answer"])
        md = env.get("metadata") or {}
        self.assertTrue(md.get("is_extra_calc") is True)
        self.assertEqual(md.get("processing_fee_override"), 22)

    def test_scenario_4_unclear_intent_maps_to_clarify(self) -> None:
        self.assertEqual(
            classify_intent(USER_PROMPT_UNCLEAR, has_new_upload=False, has_session_quote=False),
            "CHAT",
        )
        env = _apply_envelope(raw_unclear_response())
        assert_envelope_complete(self, env)
        self.assertEqual(env["intent"], DUAL_INTENT_CLARIFY)
        self.assertFalse(env["quote_ready"])
        self.assertEqual(env["route_target"], "default_deferred")
        self.assertEqual(env["answer"], "")
        self.assertEqual(env["actions"], [])
        self.assertEqual(env["quote_patch"], {})

    def test_scenario_5_envelope_fields_always_complete_across_intents(self) -> None:
        samples = [
            raw_pure_quote_response(),
            raw_why_expensive_response(),
            raw_processing_fee_recalc_response(),
            raw_unclear_response(),
            {"quote_ready": False, "reply_type": "structure_confirmation"},
            {"error": "sheet_parse_failed", "message": "表格解析失败"},
        ]
        for raw in samples:
            with self.subTest(keys=tuple(raw.keys())[:4]):
                env = _apply_envelope(raw, http_status=400 if raw.get("error") else 200)
                assert_envelope_complete(self, env)


if __name__ == "__main__":
    unittest.main()
