"""Embedding 降级与报价主流程不被 HuggingFace 超时阻塞。"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class BGEEncoderFallbackTest(unittest.TestCase):
    def test_batch_encode_returns_empty_when_encoder_marked_unavailable(self) -> None:
        from embedding.bge_encoder import BGEEncoder

        enc = BGEEncoder(model_name="BAAI/bge-m3")
        enc._available = False
        enc._load_error = "ConnectTimeout"
        mat = enc.batch_encode(["面料A", "拉链B"])
        self.assertEqual(mat.shape, (2, 0))

    def test_encode_returns_empty_when_load_fails(self) -> None:
        from embedding.bge_encoder import BGEEncoder

        enc = BGEEncoder(model_name="/nonexistent/local/bge-m3")
        with patch.object(enc, "_ensure_backend", side_effect=RuntimeError("offline")):
            enc._available = False
            enc._load_error = "offline"
            vec = enc.encode("测试物料")
        self.assertEqual(vec.size, 0)

    def test_offline_mode_detects_local_path(self) -> None:
        from embedding.bge_encoder import _offline_mode_requested

        self.assertTrue(_offline_mode_requested(str(ROOT)))


class SmartLookupFallbackTest(unittest.TestCase):
    def test_smart_lookup_without_ready_index_returns_empty_candidates(self) -> None:
        from core.smart_lookup import smart_lookup

        mock_kb = MagicMock()
        mock_kb.lookup.return_value = None
        mock_index = MagicMock()
        mock_index.is_ready.return_value = False

        with patch("core.smart_lookup.get_price_kb", return_value=mock_kb):
            with patch("core.smart_lookup._force_reload_index_if_dirty"):
                with patch("core.smart_lookup.get_embedding_index", return_value=mock_index):
                    result = smart_lookup("牛津布", "210D", kb=mock_kb)

        self.assertFalse(result["kb_hit"])
        self.assertIsNone(result["unit_price"])
        self.assertEqual(result["candidates"], [])

    def test_enqueue_learn_does_not_block_caller(self) -> None:
        from core import smart_lookup as sl

        with patch.object(sl, "knowledge_auto_learn_enabled", return_value=True):
            with patch.object(sl.threading, "Thread") as mock_thread:
                sl.enqueue_knowledge_learn_after_rule_miss("面料", "210D")
        mock_thread.assert_called_once()
        self.assertEqual(mock_thread.call_args.kwargs.get("daemon"), True)


class CalculateQuoteWithEmbeddingDegradedTest(unittest.TestCase):
    def test_calculate_quote_works_when_semantic_search_empty(self) -> None:
        import quote_engine

        payload = {
            "product_name": "篮球包",
            "quantities": [300],
            "gross_margin_rate": 0.35,
            "items": [
                {
                    "name": "面料",
                    "spec": "210D",
                    "unit_price": 12.5,
                    "usage": "1.2㎡",
                    "subtotal": 15.0,
                    "kb_hit": True,
                },
                {
                    "name": "拉链",
                    "spec": "5#",
                    "unit_price": 0.8,
                    "usage": "1条",
                    "subtotal": 0.8,
                    "kb_hit": True,
                },
            ],
        }
        result = quote_engine.calculate_quote(payload)
        self.assertTrue(result.get("tiers"))


class ServerQuoteGuardTest(unittest.TestCase):
    def test_quote_timeout_message_defined(self) -> None:
        import server

        self.assertIn("报价生成超时", server.QUOTE_TIMEOUT_USER_MESSAGE)
        self.assertGreaterEqual(server._quote_request_timeout_sec(), 30.0)


class FrontendQuoteTimeoutTest(unittest.TestCase):
    def test_app_js_has_quote_fetch_timeout(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("quoteFetchWithTimeout", js)
        self.assertIn("QUOTE_FETCH_TIMEOUT_MS", js)
        self.assertIn("AbortError", js)
        self.assertIn("报价生成超时", js)


if __name__ == "__main__":
    unittest.main()
