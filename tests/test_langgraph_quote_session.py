"""正式报价会话接入 LangGraph 后的本地兜底行为。"""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch

from server import QuoteHandler


class LangGraphQuoteSessionHTTPTest(unittest.TestCase):
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

    def _get_json_with_headers(self, path: str) -> tuple[int, dict, dict]:
        headers = {}
        if self.cookie:
            headers["Cookie"] = self.cookie
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        out_headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        parsed = json.loads(raw.decode("utf-8"))
        return resp.status, parsed if isinstance(parsed, dict) else {}, out_headers

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
                "product_name": "测试包",
                "enable_kimi_autofill": False,
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(first.get("quote_ready"))
        return first

    @patch("quotation_agent.nodes.chat_completions", side_effect=RuntimeError("http_401"))
    @patch("quotation_agent.nodes.moonshot_api_key", return_value="bad-key")
    def test_explain_followup_uses_local_fallback_when_model_fails(
        self,
        _mock_key: object,
        _mock_chat: object,
    ) -> None:
        code, first = self._post_json(
            "/api/quote",
            {
                "message_text": "测试报价",
                "items": [
                    {
                        "name": "面料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    }
                ],
                "quantities": [500],
                "product_name": "测试包",
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(first.get("quote_ready"))
        self.assertTrue(first.get("quote_id"))

        code2, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "你怎么算的",
                "session_context": {
                    "currentQuoteId": first["quote_id"],
                    "fileName": "",
                    "primaryQuoteMsgId": "unit-card",
                },
            },
        )
        self.assertEqual(code2, 200)
        self.assertFalse(follow.get("quote_ready"))
        self.assertEqual(follow.get("reply_type"), "process_card")
        self.assertEqual(follow.get("intent"), "QUOTE_PROCESS")
        process_blob = json.dumps(follow.get("process") or {}, ensure_ascii=False)
        self.assertIn("物料合计", process_blob)
        self.assertNotIn("Invalid Authentication", process_blob)

    @patch("quotation_agent.nodes.chat_completions", side_effect=RuntimeError("http_401"))
    @patch("quotation_agent.nodes.moonshot_api_key", return_value="bad-key")
    def test_why_followup_uses_langgraph_local_fallback_when_model_fails(
        self,
        _mock_key: object,
        _mock_chat: object,
    ) -> None:
        code, first = self._post_json(
            "/api/quote",
            {
                "message_text": "测试报价",
                "items": [
                    {
                        "name": "面料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    }
                ],
                "quantities": [500],
                "product_name": "测试包",
            },
        )
        self.assertEqual(code, 200)
        code2, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "为什么跟你算的不一样",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code2, 200)
        self.assertFalse(follow.get("quote_ready"))
        self.assertEqual(follow.get("intent"), "QUOTE_EXPLAIN")
        text = str(follow.get("assistant_message") or "")
        self.assertIn("本地报价引擎", text)
        self.assertIn("物料合计", text)
        self.assertNotIn("Invalid Authentication", text)

    def test_difference_followup_restores_active_quote_when_client_omits_quote_id(self) -> None:
        code, first = self._post_json(
            "/api/quote",
            {
                "message_text": "测试报价",
                "items": [
                    {
                        "name": "面料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    }
                ],
                "quantities": [500],
                "product_name": "测试包",
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(first.get("quote_ready"))

        code2, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "为啥误差相差那么大",
                "session_context": {"currentQuoteId": ""},
            },
        )
        self.assertEqual(code2, 200)
        self.assertFalse(follow.get("quote_ready"))
        self.assertEqual(follow.get("intent"), "QUOTE_EXPLAIN")
        text = str(follow.get("assistant_message") or "")
        self.assertIn("物料合计", text)
        self.assertNotIn("您好，我是报价助手", text)

    def test_difference_followup_without_active_quote_returns_context_hint(self) -> None:
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "为啥误差相差那么大",
                "session_context": {"currentQuoteId": ""},
            },
        )
        self.assertEqual(code, 200)
        self.assertFalse(follow.get("quote_ready"))
        self.assertEqual(follow.get("intent"), "FOLLOW_UP")
        text = str(follow.get("assistant_message") or "")
        self.assertIn("没有可引用的 active_quote", text)
        self.assertNotIn("您好，我是报价助手", text)

    def test_margin_followup_restores_active_quote_when_client_omits_quote_id(self) -> None:
        code, first = self._post_json(
            "/api/quote",
            {
                "message_text": "测试报价",
                "items": [
                    {
                        "name": "面料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    }
                ],
                "quantities": [300],
                "product_name": "测试包",
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(first.get("quote_ready"))

        code2, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "按45%毛利的话是多少",
                "session_context": {"currentQuoteId": ""},
            },
        )
        self.assertEqual(code2, 200)
        self.assertTrue(follow.get("quote_ready"))
        self.assertEqual(follow.get("intent"), "agent_trial")
        self.assertEqual(follow["tiers"][0]["margin_rate_text"], "45%")
        self.assertNotIn("当前没有进行中的报价", str(follow.get("assistant_message") or ""))

    def test_quote_response_contains_missing_data_enrichment_report(self) -> None:
        code, result = self._post_json(
            "/api/quote",
            {
                "message_text": "帮我报价",
                "user_prompt": "帮我报价",
                "items": [
                    {
                        "name": "拉链",
                        "spec": "-",
                        "usage": "30cm",
                        "unit_price": "3.5元/米",
                        "amount": 0,
                    }
                ],
                "quantities": [300],
                "product_name": "测试包",
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(result.get("quote_ready"))
        report = result.get("missing_data_enrichment") or {}
        self.assertEqual(report.get("filled_count"), 1)
        self.assertEqual((report.get("filled") or [{}])[0].get("field"), "amount")
        self.assertAlmostEqual(float(result["detail_rows"][0]["amount"]), 1.05, places=2)

    def test_uploaded_sheet_requires_structure_confirmation_before_quote(self) -> None:
        sheet = {
            "name": "unit.csv",
            "content_base64": "bmFtZSx1c2FnZSx1bml0X3ByaWNlLGFtb3VudArmi4npk74sMeS4qiwxMOWFgy/kuKosMTAK",
        }
        payload = {
            "message_text": "帮我计算下表格的成本价",
            "user_prompt": "帮我计算下表格的成本价",
            "uploaded_sheet": sheet,
        }
        code, pre = self._post_json("/api/quote", payload)
        self.assertEqual(code, 200)
        self.assertFalse(pre.get("quote_ready"))
        self.assertEqual(pre.get("reply_type"), "structure_confirmation")
        self.assertEqual(pre.get("intent"), "STRUCTURE_CONFIRMATION_REQUIRED")
        self.assertNotIn("tiers", pre)

        payload["structure_confirmed"] = True
        code2, result = self._post_json("/api/quote", payload)
        self.assertEqual(code2, 200)
        self.assertTrue(result.get("quote_ready"))
        self.assertIn("tiers", result)

    def test_error_response_contains_request_id_and_error_code(self) -> None:
        code, body, headers = self._get_json_with_headers("/api/not-found-for-test")
        self.assertEqual(code, 404)
        self.assertIn("request_id", body)
        self.assertEqual(headers.get("x-request-id"), body.get("request_id"))
        self.assertFalse(body.get("ok"))
        self.assertTrue(body.get("error_code"))

    def test_process_followup_returns_process_card_without_model(self) -> None:
        code, first = self._post_json(
            "/api/quote",
            {
                "message_text": "测试报价",
                "items": [
                    {
                        "name": "拉链",
                        "spec": "-",
                        "usage": "30cm",
                        "unit_price": "0.03元/cm",
                        "amount": 0.9,
                    }
                ],
                "quantities": [500],
                "product_name": "测试包",
            },
        )
        self.assertEqual(code, 200)
        code2, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "计算过程拆解一下",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code2, 200)
        self.assertFalse(follow.get("quote_ready"))
        self.assertEqual(follow.get("reply_type"), "process_card")
        self.assertIn("process", follow)

    def test_quantity_followup_defaults_to_trial_not_commit(self) -> None:
        first = self._seed_quote()
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "这单500件呢",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(follow.get("quote_ready"))
        self.assertEqual(follow.get("intent"), "agent_trial")
        self.assertEqual((follow.get("metadata") or {}).get("mode"), "trial")
        self.assertEqual(follow["tiers"][0]["quantity"], 500)

    def test_quantity_commit_updates_active_quote(self) -> None:
        first = self._seed_quote()
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "改成500件，以这个为准",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(follow.get("intent"), "agent_commit")
        self.assertEqual(follow["tiers"][0]["quantity"], 500)
        code2, explain = self._post_json(
            "/api/quote",
            {
                "message_text": "计算过程",
                "session_context": {"currentQuoteId": follow["quote_id"]},
            },
        )
        self.assertEqual(code2, 200)
        self.assertEqual(explain.get("reply_type"), "process_card")

    def test_material_quantity_margin_combination_in_one_turn(self) -> None:
        first = self._seed_quote()
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "里料换涤纶，毛利改30%，500件再帮我算下",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(follow.get("quote_ready"))
        self.assertEqual(follow.get("intent"), "agent_trial")
        self.assertEqual(follow["tiers"][0]["quantity"], 500)
        self.assertEqual(follow["tiers"][0]["margin_rate_text"], "30%")
        tools = (follow.get("metadata") or {}).get("tools") or []
        self.assertIn("substitute_material", tools)
        self.assertIn("calculate", tools)

    def test_explain_then_recalculate_combination(self) -> None:
        first = self._seed_quote()
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "先告诉我怎么算的，再按500件重算",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(follow.get("quote_ready"))
        self.assertEqual(follow["tiers"][0]["quantity"], 500)
        self.assertIn("agent_process", follow)
        self.assertIn("process", follow["agent_process"])

    def test_alternatives_only_does_not_calculate(self) -> None:
        first = self._seed_quote()
        code, follow = self._post_json(
            "/api/quote",
            {
                "message_text": "如果换尼龙不合适，你给我两个替代方案",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertFalse(follow.get("quote_ready"))
        text = str(follow.get("assistant_message") or "")
        self.assertIn("替代", text)
        self.assertIn("先不覆盖", text)

    def test_explicit_trial_does_not_change_active_quote(self) -> None:
        first = self._seed_quote()
        code, trial = self._post_json(
            "/api/quote",
            {
                "message_text": "毛利改30%看看，这次先试算，不要覆盖主报价",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(trial.get("intent"), "agent_trial")
        code2, explain = self._post_json(
            "/api/quote",
            {
                "message_text": "计算过程",
                "session_context": {"currentQuoteId": first["quote_id"]},
            },
        )
        self.assertEqual(code2, 200)
        process = json.dumps(explain.get("process") or {}, ensure_ascii=False)
        self.assertIn("35%", process)


if __name__ == "__main__":
    unittest.main()
