"""轻量 RAG 答疑策略。"""
from __future__ import annotations

import unittest
import json
from unittest.mock import MagicMock, patch

from qa_rag import (
    answer_qa,
    build_readonly_quote_context,
    get_oem_qa_system_prompt,
    is_qa_price_lookup,
    load_readonly_quote_context,
)
from request_intent_router import ROUTE_QA, route_quote_request


def _sample_active_quote_context() -> dict:
    payload = {
        "product_name": "粗茶背包",
        "items": [
            {
                "name": "6分D扣 2个",
                "usage": "2个",
                "unit_price": "0.6元/个",
                "amount": 1.2,
                "unit_price_ai": True,
                "amount_ai": True,
                "source": "ai",
                "recognition_status": "split",
            },
            {
                "name": "25mm织带",
                "usage": "1.2米",
                "unit_price": "0.8元/米",
                "amount": 0.96,
                "usage_ai": True,
                "source": "ai",
            },
            {
                "name": "210D外料",
                "usage": "1码²",
                "unit_price": "14元/码²",
                "amount": 14.0,
                "kb_hit": True,
                "kb_matched_name": "210D牛津",
                "kb_matched_spec": "150CM",
                "source": "kb",
            },
        ],
        "structure_checklist": {
            "is_bag_product": True,
            "extraction_complete": False,
            "items": [
                {
                    "name": "胸带",
                    "affects_cost": True,
                    "cost_item_ids": [],
                    "estimate_status": "needs_manual",
                    "risk_level": "high",
                },
                {
                    "name": "肩带",
                    "affects_cost": True,
                    "cost_item_ids": ["row-1"],
                    "estimate_status": "exact",
                    "risk_level": "low",
                },
            ],
            "extraction_leaks": [{"keyword": "腰封", "reason": "结构说明含腰封但未进清单"}],
        },
    }
    result = {
        "product_name": "粗茶背包",
        "detail_rows": payload["items"],
        "structure_checklist": payload["structure_checklist"],
        "material_total_text": "88.00元",
        "system_cost_text": "102.00元",
        "data_notice": "1 行 AI 参考价待复核",
        "pricing_gate": {
            "requires_manual_confirm": True,
            "high_risk_codes": ["bag_structure_extraction_leak"],
            "medium_risk_codes": ["ai_estimated_unit_price"],
        },
        "risk_flags": ["manual_review_required"],
        "tiers": [
            {
                "quantity_text": "500件",
                "cost_before_margin_text": "102.00元",
                "margin_rate_text": "18%",
                "exw_price_text": "120.36元",
            }
        ],
        "price_kb_sync": {
            "created": 1,
            "pending": 2,
            "conflicts": 0,
            "skipped": 3,
            "dropped": 1,
            "items": [
                {
                    "name": "210D外料",
                    "spec": "150CM",
                    "price": "14元/码²",
                    "status": "created",
                    "marker": "auto",
                },
                {
                    "name": "新辅料",
                    "spec": "25mm",
                    "price": "",
                    "status": "exception",
                    "marker": "pending",
                },
            ],
        },
    }
    return build_readonly_quote_context("q-test-001", payload, result)


class QaRagTest(unittest.TestCase):
    def test_material_price_lookup_intent(self) -> None:
        self.assertTrue(is_qa_price_lookup("600D塔丝隆多少钱"))
        self.assertFalse(is_qa_price_lookup("500件多少钱"))
        route = route_quote_request(
            {"message_text": "600D塔丝隆多少钱"},
            has_upload=False,
            has_active_quote=False,
        )
        self.assertEqual(route.route_intent, ROUTE_QA)

    def test_backpack_consulting_does_not_become_price_lookup(self) -> None:
        with patch.dict("os.environ", {"QUOTE_QA_LLM_ENABLED": "0"}):
            resp = answer_qa("\u65c5\u884c\u80cc\u5305\u9762\u6599\u600e\u4e48\u9009\u66f4\u8010\u78e8")
        self.assertEqual(resp.get("reply_type"), "business_qa")
        self.assertIn("\u8010\u78e8", str(resp.get("assistant_message") or ""))
        self.assertNotIn("\u4ef7\u683c\u5e93\u6682\u65e0", str(resp.get("assistant_message") or ""))
        self.assertEqual((resp.get("qa_audit") or {}).get("route"), "fallback")
        self.assertFalse((resp.get("qa_audit") or {}).get("used"))

    @patch("kimi_client._send_chat_request_moonshot_with_400_relax")
    def test_backpack_consulting_uses_openai_when_enabled(self, mock_send: MagicMock) -> None:
        mock_send.return_value = json.dumps(
            {"choices": [{"message": {"content": "结论：建议优先升级包底和主面料。\n1. 600D/900D 牛津布适合常规旅行。\n2. 高频户外可提高到高强尼龙。\n3. 肩带连接位要做补强。"}}]},
            ensure_ascii=False,
        )
        with patch.dict(
            "os.environ",
            {
                "QUOTE_QA_LLM_ENABLED": "1",
                "OPENAI_API_KEY": "sk-openai-test",
                "OPENAI_BASE_URL": "https://code.codingplay.top/redeem",
                "OPENAI_MODEL": "gpt-5.5",
                "KIMI_MODEL": "kimi-k2.6",
            },
        ):
            resp = answer_qa("旅行背包面料怎么选更耐磨")
        self.assertEqual(resp.get("source_type"), "llm")
        self.assertTrue((resp.get("llm_status") or {}).get("used"))
        self.assertEqual((resp.get("llm_status") or {}).get("provider"), "openai-compatible")
        self.assertEqual((resp.get("llm_status") or {}).get("model"), "gpt-5.5")
        self.assertEqual((resp.get("qa_audit") or {}).get("route"), "llm")
        self.assertTrue((resp.get("qa_audit") or {}).get("used"))

    @patch("kimi_client._send_chat_request_moonshot_with_400_relax", side_effect=RuntimeError("boom"))
    def test_backpack_consulting_openai_failure_returns_natural_fallback(self, _mock_send: MagicMock) -> None:
        with patch.dict(
            "os.environ",
            {
                "QUOTE_QA_LLM_ENABLED": "1",
                "OPENAI_API_KEY": "sk-openai-test",
                "OPENAI_BASE_URL": "https://code.codingplay.top/redeem",
                "OPENAI_MODEL": "gpt-5.5",
            },
        ):
            resp = answer_qa("客户觉得报价贵怎么解释")
        msg = str(resp.get("assistant_message") or "")
        self.assertEqual(resp.get("source_type"), "fallback")
        self.assertIn("客户", msg)
        self.assertIn("材料", msg)
        self.assertNotRegex(msg, r"API|LLM|Kimi|Claude|payload|quote_engine")
        self.assertEqual((resp.get("qa_audit") or {}).get("fallback_reason"), "llm_failed")
        self.assertFalse((resp.get("qa_audit") or {}).get("used"))

    @patch("price_kb.get_price_kb")
    @patch("qa_rag._search_quote_history", return_value=[])
    def test_price_kb_hit(self, _mock_hist: object, mock_get_kb: MagicMock) -> None:
        ent = MagicMock()
        ent.raw_name = "600D塔丝隆格子布"
        ent.raw_spec = "150CM"
        ent.raw_price = "12元/码"
        hit = MagicMock()
        hit.entry = ent
        hit.score = 0.91
        kb = MagicMock()
        kb.lookup.return_value = hit
        mock_get_kb.return_value = kb
        resp = answer_qa("600D塔丝隆多少钱")
        self.assertEqual(resp.get("source_type"), "price_kb")
        self.assertIn("12元/码", str(resp.get("assistant_message") or ""))
        self.assertFalse(resp.get("quote_ready"))
        self.assertEqual((resp.get("qa_audit") or {}).get("route"), "price_kb")
        self.assertFalse((resp.get("qa_audit") or {}).get("used"))

    @patch("kimi_client._send_chat_request_moonshot_with_400_relax")
    @patch("price_kb.get_price_kb")
    @patch("qa_rag._search_quote_history", return_value=[])
    def test_price_lookup_does_not_use_llm(
        self,
        _mock_hist: object,
        mock_get_kb: MagicMock,
        mock_send: MagicMock,
    ) -> None:
        ent = MagicMock()
        ent.raw_name = "600D塔丝隆格子布"
        ent.raw_spec = "150CM"
        ent.raw_price = "12元/码"
        hit = MagicMock()
        hit.entry = ent
        hit.score = 0.91
        kb = MagicMock()
        kb.lookup.return_value = hit
        mock_get_kb.return_value = kb
        with patch.dict(
            "os.environ",
            {
                "QUOTE_QA_LLM_ENABLED": "1",
                "OPENAI_API_KEY": "sk-openai-test",
                "OPENAI_BASE_URL": "https://code.codingplay.top/redeem",
                "OPENAI_MODEL": "gpt-5.5",
            },
        ):
            resp = answer_qa("600D塔丝隆多少钱")
        self.assertEqual(resp.get("source_type"), "price_kb")
        self.assertFalse(mock_send.called)
        self.assertEqual((resp.get("qa_audit") or {}).get("route"), "price_kb")

    def test_admin_howto(self) -> None:
        resp = answer_qa("价格库怎么更新")
        self.assertEqual(resp.get("source_type"), "docs")
        self.assertIn("价格库", str(resp.get("assistant_message") or ""))
        self.assertIn("后台", str(resp.get("assistant_message") or ""))

    def test_missing_price_flow(self) -> None:
        resp = answer_qa("这个材料没有价格怎么办")
        self.assertEqual(resp.get("source_type"), "docs")
        self.assertIn("待补充", str(resp.get("assistant_message") or ""))
        self.assertNotIn("请上传表格", str(resp.get("assistant_message") or ""))

    @patch("qa_rag._search_quote_history", return_value=[])
    @patch("price_kb.get_price_kb")
    def test_price_kb_miss_fallback(self, mock_get_kb: MagicMock, _mock_hist: object) -> None:
        kb = MagicMock()
        kb.lookup.return_value = None
        kb.suggest_entries_for_query.return_value = []
        mock_get_kb.return_value = kb
        resp = answer_qa("稀有面料XYZ多少钱")
        self.assertEqual(resp.get("source_type"), "fallback")
        self.assertIn("价格库暂无", str(resp.get("assistant_message") or ""))

    @patch("qa_rag._search_quote_history")
    @patch("price_kb.get_price_kb")
    def test_quote_history_when_kb_miss(
        self,
        mock_get_kb: MagicMock,
        mock_hist: MagicMock,
    ) -> None:
        kb = MagicMock()
        kb.lookup.return_value = None
        mock_get_kb.return_value = kb
        mock_hist.return_value = [
            {
                "name": "600D塔丝隆",
                "unit_price": "11元/码",
                "amount_text": "22.00元",
                "product_name": "测试包",
                "saved_at": "2026-05-01",
            }
        ]
        resp = answer_qa("600D塔丝隆多少钱")
        self.assertEqual(resp.get("source_type"), "quote_history")
        self.assertIn("历史报价", str(resp.get("assistant_message") or ""))

    def test_build_readonly_quote_context_includes_ai_and_structure(self) -> None:
        ctx = _sample_active_quote_context()
        self.assertTrue(ctx.get("has_active_quote"))
        self.assertEqual(ctx.get("quote_id"), "q-test-001")
        self.assertEqual(len(ctx.get("ai_estimated_rows") or []), 2)
        self.assertEqual(len(ctx.get("kb_matched_rows") or []), 1)
        sc = ctx.get("structure_checklist") or {}
        self.assertIn("胸带", sc.get("items_without_cost") or [])
        self.assertTrue(sc.get("extraction_leaks"))

    def test_build_readonly_quote_context_preserves_explicit_ai_booleans(self) -> None:
        ctx = _sample_active_quote_context()
        usage_only = next(r for r in ctx["cost_rows"] if r.get("name") == "25mm织带")
        self.assertTrue(usage_only.get("usage_ai"))
        self.assertFalse(usage_only.get("unit_price_ai"))
        self.assertIn("usage_ai", usage_only.get("ai_flags") or [])

    def test_build_readonly_quote_context_matched_kb_and_risk_flags(self) -> None:
        ctx = _sample_active_quote_context()
        matched_kb = ctx.get("matched_kb") or {}
        self.assertEqual(matched_kb.get("count"), 1)
        rows = matched_kb.get("rows") or []
        self.assertEqual(rows[0].get("kb_matched_name"), "210D牛津")
        self.assertEqual(rows[0].get("kb_matched_spec"), "150CM")
        risk_flags = ctx.get("risk_flags") or []
        self.assertIn("bag_structure_extraction_leak", risk_flags)
        self.assertIn("ai_estimated_unit_price", risk_flags)
        self.assertIn("manual_review_required", risk_flags)

    def test_build_readonly_quote_context_price_kb_sync_summary(self) -> None:
        ctx = _sample_active_quote_context()
        sync = ctx.get("price_kb_sync") or {}
        self.assertEqual(sync.get("created"), 1)
        self.assertEqual(sync.get("pending"), 2)
        self.assertEqual(sync.get("skipped"), 3)
        self.assertEqual(sync.get("dropped"), 1)
        self.assertEqual(sync.get("items_count"), 2)
        sample = sync.get("items_sample") or []
        self.assertEqual(sample[0].get("status"), "created")
        self.assertEqual(sample[1].get("status"), "exception")

    @patch("qa_rag.load_readonly_quote_context")
    def test_answer_qa_uses_sid_for_active_quote_local_ai_rows(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value = _sample_active_quote_context()
        with patch.dict("os.environ", {"QUOTE_QA_LLM_ENABLED": "0"}):
            resp = answer_qa("哪些是 AI 估算", sid="sess-abc")
        msg = str(resp.get("assistant_message") or "")
        self.assertIn("6分D扣", msg)
        self.assertIn("25mm织带", msg)
        self.assertIn("usage_ai", msg)
        self.assertTrue((resp.get("qa_quote_context") or {}).get("used"))
        mock_ctx.assert_called_once_with("sess-abc")

    @patch("qa_rag.load_readonly_quote_context")
    def test_answer_qa_structure_leak_risk_uses_context(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value = _sample_active_quote_context()
        with patch.dict("os.environ", {"QUOTE_QA_LLM_ENABLED": "0"}):
            resp = answer_qa("这单为什么有结构漏项风险", sid="sess-abc")
        msg = str(resp.get("assistant_message") or "")
        self.assertIn("胸带", msg)
        self.assertTrue("腰封" in msg or "漏项" in msg or "结构" in msg)

    @patch("kimi_client._send_chat_request_moonshot_with_400_relax")
    @patch("qa_rag.load_readonly_quote_context")
    def test_active_quote_context_passed_to_openai(
        self,
        mock_ctx: MagicMock,
        mock_send: MagicMock,
    ) -> None:
        mock_ctx.return_value = _sample_active_quote_context()
        mock_send.return_value = json.dumps(
            {"choices": [{"message": {"content": "当前报价中 6分D扣 为 AI 市场估算，需人工复核。"}}]},
            ensure_ascii=False,
        )
        with patch.dict(
            "os.environ",
            {
                "QUOTE_QA_LLM_ENABLED": "1",
                "OPENAI_API_KEY": "sk-openai-test",
                "OPENAI_BASE_URL": "https://code.codingplay.top/redeem",
                "OPENAI_MODEL": "gpt-5.5",
            },
        ):
            resp = answer_qa("业务员下一步该补什么信息", sid="sess-abc")
        self.assertEqual(resp.get("source_type"), "llm")
        body = mock_send.call_args.kwargs.get("body") or mock_send.call_args[0][2]
        system_msg = body["messages"][0]["content"]
        user_msg = body["messages"][-1]["content"]
        self.assertIn("定制软包 OEM 报价业务顾问", system_msg)
        self.assertIn("quote_context", user_msg)
        self.assertIn("risk_flags", user_msg)
        self.assertIn("matched_kb", user_msg)
        self.assertIn("usage_ai", user_msg)
        self.assertIn("6分D扣", user_msg)
        self.assertIn("胸带", user_msg)

    @patch("qa_rag.load_readonly_quote_context", return_value=None)
    @patch("kimi_client._send_chat_request_moonshot_with_400_relax")
    def test_no_active_quote_keeps_generic_consulting(
        self,
        mock_send: MagicMock,
        _mock_ctx: MagicMock,
    ) -> None:
        mock_send.return_value = json.dumps(
            {"choices": [{"message": {"content": "建议优先升级包底和受力位面料。"}}]},
            ensure_ascii=False,
        )
        with patch.dict(
            "os.environ",
            {
                "QUOTE_QA_LLM_ENABLED": "1",
                "OPENAI_API_KEY": "sk-openai-test",
                "OPENAI_BASE_URL": "https://code.codingplay.top/redeem",
                "OPENAI_MODEL": "gpt-5.5",
            },
        ):
            resp = answer_qa("旅行背包面料怎么选更耐磨", sid="sess-empty")
        user_msg = mock_send.call_args.kwargs.get("body") or mock_send.call_args[0][2]
        user_msg = user_msg["messages"][-1]["content"]
        self.assertNotIn("quote_context", user_msg)
        self.assertEqual(resp.get("source_type"), "llm")

    @patch("qa_rag.load_readonly_quote_context")
    @patch("kimi_client._send_chat_request_moonshot_with_400_relax")
    @patch("price_kb.get_price_kb")
    @patch("qa_rag._search_quote_history", return_value=[])
    def test_price_lookup_with_sid_still_skips_llm(
        self,
        _mock_hist: object,
        mock_get_kb: MagicMock,
        mock_send: MagicMock,
        mock_ctx: MagicMock,
    ) -> None:
        mock_ctx.return_value = _sample_active_quote_context()
        ent = MagicMock()
        ent.raw_name = "600D塔丝隆格子布"
        ent.raw_spec = "150CM"
        ent.raw_price = "12元/码"
        hit = MagicMock()
        hit.entry = ent
        hit.score = 0.91
        kb = MagicMock()
        kb.lookup.return_value = hit
        mock_get_kb.return_value = kb
        with patch.dict(
            "os.environ",
            {
                "QUOTE_QA_LLM_ENABLED": "1",
                "OPENAI_API_KEY": "sk-openai-test",
            },
        ):
            resp = answer_qa("600D塔丝隆多少钱", sid="sess-abc")
        self.assertEqual(resp.get("source_type"), "price_kb")
        self.assertFalse(mock_send.called)

    @patch("local_quote_patch.resolve_active_quote")
    def test_load_readonly_quote_context_from_session_store(self, mock_resolve: MagicMock) -> None:
        payload = {"product_name": "测试包", "items": [{"name": "织带", "unit_price": "1元/米"}]}
        result = {"detail_rows": payload["items"], "material_total_text": "1.00元"}
        mock_resolve.return_value = ("q-123", payload, result)
        ctx = load_readonly_quote_context("sid-1")
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("quote_id"), "q-123")
        self.assertEqual(ctx.get("product_name"), "测试包")

    def test_oem_qa_system_prompts(self) -> None:
        active = get_oem_qa_system_prompt(has_active_quote=True)
        general = get_oem_qa_system_prompt(has_active_quote=False)
        self.assertIn("定制软包 OEM 报价业务顾问", active)
        self.assertIn("定制软包 OEM 报价业务顾问", general)
        self.assertIn("quote_context", active)
        self.assertIn("没有绑定具体报价单", general)
        self.assertNotIn("定制旅行背包专业答疑顾问", general)

    @patch("qa_rag.load_readonly_quote_context")
    def test_active_quote_expensive_explanation_uses_context_local(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value = _sample_active_quote_context()
        with patch.dict("os.environ", {"QUOTE_QA_LLM_ENABLED": "0"}):
            resp = answer_qa("客户觉得这单贵怎么解释", sid="sess-abc")
        msg = str(resp.get("assistant_message") or "")
        self.assertIn("粗茶背包", msg)
        self.assertIn("88.00元", msg)
        self.assertIn("AI", msg)
        self.assertNotRegex(msg, r"120\.36元.*建议改价|降到|再报\s*\d")

    @patch("qa_rag.load_readonly_quote_context")
    def test_active_quote_manual_review_points_local(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value = _sample_active_quote_context()
        with patch.dict("os.environ", {"QUOTE_QA_LLM_ENABLED": "0"}):
            resp = answer_qa("这单哪些地方要人工复核", sid="sess-abc")
        msg = str(resp.get("assistant_message") or "")
        self.assertIn("6分D扣", msg)
        self.assertTrue("胸带" in msg or "结构" in msg or "AI" in msg)

    def test_generic_cost_reduction_no_formal_price(self) -> None:
        with patch.dict("os.environ", {"QUOTE_QA_LLM_ENABLED": "0"}):
            resp = answer_qa("旅行背包怎么降本")
        msg = str(resp.get("assistant_message") or "")
        self.assertIn("降本", msg)
        self.assertNotRegex(msg, r"总价|EXW|FOB|系统成本|物料合计")

    @patch("kimi_client._send_chat_request_moonshot_with_400_relax")
    def test_active_quote_system_prompt_sent_to_llm(self, mock_send: MagicMock) -> None:
        mock_send.return_value = json.dumps(
            {"choices": [{"message": {"content": "建议先复核 AI 估算行后再对外解释。"}}]},
            ensure_ascii=False,
        )
        with patch("qa_rag.load_readonly_quote_context", return_value=_sample_active_quote_context()):
            with patch.dict(
                "os.environ",
                {
                    "QUOTE_QA_LLM_ENABLED": "1",
                    "OPENAI_API_KEY": "sk-openai-test",
                    "OPENAI_BASE_URL": "https://code.codingplay.top/redeem",
                    "OPENAI_MODEL": "gpt-5.5",
                },
            ):
                answer_qa("审批驳回后怎么跟客户说清楚", sid="sess-abc")
        system_msg = mock_send.call_args.kwargs.get("body") or mock_send.call_args[0][2]
        system_msg = system_msg["messages"][0]["content"]
        self.assertIn("定制软包 OEM 报价业务顾问", system_msg)
        self.assertIn("只读边界", system_msg)


if __name__ == "__main__":
    unittest.main()
