"""quote follow-up LangGraph node surface."""
from __future__ import annotations

import unittest

from agent_graph import quote_followup as qf


class QuoteFollowupGraphNodesTest(unittest.TestCase):
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
            self.assertTrue(callable(getattr(qf, name)))

    def test_validate_context_returns_friendly_prompt(self) -> None:
        state = {
            "has_valid_context": False,
            "understood": {"quantity": 500, "material_change": False},
        }
        out = qf.validate_context(state)
        self.assertIn("没有可引用的上一单报价", out.get("context_error", ""))


if __name__ == "__main__":
    unittest.main()
