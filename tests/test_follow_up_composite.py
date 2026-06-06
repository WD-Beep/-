"""Composite follow-up scenarios for the conversational quote agent."""
from __future__ import annotations

import copy
import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch

from server import QuoteHandler


def _fake_material_substitution(base_items, user_text: str, *, kb, llm_status_holder):
    items = copy.deepcopy(base_items)
    idx = 1 if "里料" in user_text and len(items) > 1 else 0
    label = "涤纶" if "涤纶" in user_text else "尼龙"
    old = str(items[idx].get("name") or "")
    items[idx]["name"] = label
    items[idx]["unit_price"] = "8元/码"
    items[idx]["amount"] = 8.0
    items[idx]["kb_hit"] = True
    return items, {
        "target_index": idx,
        "old_material_label": old,
        "new_material_label": label,
        "query_phrase": label,
    }


class FollowUpCompositeHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        setattr(self.httpd, "_quote_site", "front")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()
        self.cookie = ""

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.th.join(timeout=2)
        self.httpd.server_close()

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        set_cookie = resp.getheader("Set-Cookie") or ""
        conn.close()
        if set_cookie:
            self.cookie = set_cookie.split(";", 1)[0].strip()
        parsed = json.loads(raw.decode("utf-8"))
        return resp.status, parsed if isinstance(parsed, dict) else {}

    def _seed_quote(self) -> dict:
        code, first = self._post_json(
            "/api/quote",
            {
                "message_text": "测试报价",
                "items": [
                    {
                        "name": "主面料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    },
                    {
                        "name": "里料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "5元/码",
                        "amount": 5.0,
                    },
                ],
                "quantities": [300],
                "gross_margin_rate": 0.35,
                "product_name": "测试包",
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(first.get("quote_ready"))
        return first

    @patch("quote_agent.tools.apply_material_substitution", side_effect=_fake_material_substitution)
    def test_material_and_quantity_trial_in_one_message(self, _mock_sub: object) -> None:
        first = self._seed_quote()
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "临时换成尼龙，500件再帮我算下",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(follow.get("intent"), "agent_trial")
        self.assertEqual(follow["tiers"][0]["quantity"], 500)
        md = follow.get("metadata") or {}
        self.assertEqual(md.get("mode"), "trial")
        self.assertTrue(md.get("is_extra_material_calc"))
        self.assertEqual(md.get("calc_quantity"), 500)
        self.assertEqual(md.get("new_material_label"), "尼龙")
        self.assertTrue(follow.get("trial_items_snapshot"))

    @patch("quote_agent.tools.apply_material_substitution", side_effect=_fake_material_substitution)
    def test_material_and_margin_trial_in_one_message(self, _mock_sub: object) -> None:
        first = self._seed_quote()
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "里料换涤纶，毛利改30%",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(follow.get("intent"), "agent_trial")
        self.assertEqual(follow["tiers"][0]["margin_rate_text"], "30%")
        md = follow.get("metadata") or {}
        self.assertTrue(md.get("is_extra_material_calc"))
        self.assertEqual(md.get("new_material_label"), "涤纶")

    def test_quantity_trial_and_quantity_commit_modes(self) -> None:
        first = self._seed_quote()
        code, trial = self._post_json(
            "/api/quote",
            {
                "message_text": "500件呢",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(trial.get("intent"), "agent_trial")
        self.assertEqual(trial["tiers"][0]["quantity"], 500)

        code2, commit = self._post_json(
            "/api/quote",
            {
                "message_text": "改成500件",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code2, 200)
        self.assertEqual(commit.get("intent"), "agent_commit")
        self.assertEqual(commit["tiers"][0]["quantity"], 500)

    def test_no_session_followups_return_friendly_agent_prompt(self) -> None:
        for msg in ("换成尼龙试试", "500件呢", "你怎么算的"):
            code, out = self._post_json("/api/quote", {"message_text": msg})
            self.assertEqual(code, 200)
            self.assertFalse(out.get("quote_ready"))
            self.assertIn("上一单报价", str(out.get("assistant_message") or ""))
            self.assertEqual((out.get("llm_status") or {}).get("agent"), "langgraph_quote_agent")

    @patch("quotation_agent.nodes.chat_completions", side_effect=RuntimeError("http_401"))
    @patch("quotation_agent.nodes.moonshot_api_key", return_value="bad-key")
    def test_kimi_auth_failure_does_not_block_local_quantity_trial(
        self,
        _mock_key: object,
        _mock_chat: object,
    ) -> None:
        first = self._seed_quote()
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "500件呢",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(follow.get("intent"), "agent_trial")
        self.assertEqual(follow["tiers"][0]["quantity"], 500)

    @patch("quote_agent.tools.apply_material_substitution", side_effect=_fake_material_substitution)
    def test_existing_promote_buttons_still_work(self, _mock_sub: object) -> None:
        first = self._seed_quote()
        code, trial_qty = self._post_json(
            "/api/quote",
            {
                "message_text": "500件呢",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(trial_qty.get("intent"), "agent_trial")

        code2, promoted_qty = self._post_json(
            "/api/quote",
            {
                "client_action": "promote_extra_to_primary",
                "promote_quantity": 500,
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code2, 200)
        self.assertEqual(promoted_qty.get("intent"), "promote_to_primary")
        self.assertEqual(promoted_qty["tiers"][0]["quantity"], 500)

        code3, material_trial = self._post_json(
            "/api/quote",
            {
                "message_text": "临时换成尼龙试试",
                "session_context": {"currentQuoteId": promoted_qty["quote_id"]},
            },
        )
        self.assertEqual(code3, 200)
        self.assertEqual(material_trial.get("intent"), "agent_trial")
        self.assertTrue(material_trial.get("trial_items_snapshot"))

        code4, promoted_mat = self._post_json(
            "/api/quote",
            {
                "client_action": "promote_material_to_primary",
                "trial_items": material_trial["trial_items_snapshot"],
                "session_context": {"currentQuoteId": promoted_qty["quote_id"]},
            },
        )
        self.assertEqual(code4, 200)
        self.assertEqual(promoted_mat.get("intent"), "promote_material_to_primary")
        names = " ".join(str(row.get("name") or "") for row in promoted_mat.get("detail_rows") or [])
        self.assertIn("尼龙", names)


if __name__ == "__main__":
    unittest.main()

