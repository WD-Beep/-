"""Regression tests for UTF-8 / GBK mojibake detection and repair."""
from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from text_encoding import (
    MOJIBAKE_MARKERS,
    deep_repair_strings,
    looks_like_mojibake,
    repair_mojibake,
    repair_mojibake_if_enabled,
)

ROOT = Path(__file__).resolve().parents[1]
ADMIN_JS = ROOT / "static" / "admin" / "admin.js"


class TestMojibakeRepair(unittest.TestCase):
  def test_normal_chinese_unchanged(self) -> None:
      samples = ["利润率", "规格/用量", "各物料成本计算", "三档报价对比", "删除失败"]
      for s in samples:
          self.assertFalse(looks_like_mojibake(s))
          self.assertIsNone(repair_mojibake(s))
          self.assertEqual(repair_mojibake_if_enabled(s), s)

  def test_gbk_mojibake_roundtrip(self) -> None:
      original = "报价 UID"
      corrupted = original.encode("utf-8").decode("gb18030")
      self.assertTrue(looks_like_mojibake(corrupted))
      fixed = repair_mojibake(corrupted)
      self.assertEqual(fixed, original)

  def _corrupt_utf8_as_gb18030(self, original: str) -> str:
      return original.encode("utf-8").decode("gb18030")

  def test_deep_repair_disabled_by_default(self) -> None:
      corrupted = self._corrupt_utf8_as_gb18030("报价备注")
      payload = {"quote": {"note": corrupted}}
      with patch.dict(os.environ, {"QUOTE_TEXT_MOJIBAKE_REPAIR": ""}, clear=False):
          out = deep_repair_strings(payload)
      self.assertEqual(out["quote"]["note"], corrupted)

  def test_deep_repair_enabled(self) -> None:
      original = "规格"
      corrupted = self._corrupt_utf8_as_gb18030(original)
      payload = {"items": [{"spec": corrupted}]}
      with patch.dict(os.environ, {"QUOTE_TEXT_MOJIBAKE_REPAIR": "1"}, clear=False):
          out = deep_repair_strings(payload)
      self.assertEqual(out["items"][0]["spec"], original)

  def test_marker_detection(self) -> None:
      for m in MOJIBAKE_MARKERS[:4]:
          self.assertTrue(looks_like_mojibake(f"prefix{m}suffix"))


class TestAdminStaticEncoding(unittest.TestCase):
  def test_admin_js_literals_no_mojibake_markers(self) -> None:
      text = ADMIN_JS.read_text(encoding="utf-8")
      str_re = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
      offenders: list[str] = []
      for m in str_re.finditer(text):
          inner = m.group(0)[1:-1]
          if any(marker in inner for marker in MOJIBAKE_MARKERS):
              offenders.append(inner[:80])
      self.assertEqual(
          offenders,
          [],
          f"admin.js still has mojibake string literals: {offenders[:5]}",
      )

  def test_admin_js_has_key_ui_labels(self) -> None:
      text = ADMIN_JS.read_text(encoding="utf-8")
      for label in ("三档报价对比", "各物料成本计算", "利润率", "规格", "业务员（上传表）"):
          self.assertIn(label, text, f"missing UI label: {label}")
      self.assertNotIn("业务员编号（上传表）", text)


class TestApiCharsetHeader(unittest.TestCase):
  def test_write_json_content_type_includes_utf8(self) -> None:
      from server import QuoteHandler

      class _H(QuoteHandler):
          def __init__(self) -> None:
              self.headers = {}
              self._response_status = 0
              self._response_headers: list[tuple[str, str]] = []
              self.wfile = _BytesIO()

          def send_response(self, code: int, message: str | None = None) -> None:
              self._response_status = code

          def send_header(self, key: str, value: str) -> None:
              self._response_headers.append((key, value))

          def end_headers(self) -> None:
              pass

      class _BytesIO:
          def __init__(self) -> None:
              self.buf = b""

          def write(self, data: bytes) -> int:
              self.buf += data
              return len(data)

      h = _H()
      h.write_json({"ok": True, "message": "利润率"})
      ct = dict(h._response_headers).get("Content-Type", "")
      self.assertIn("charset=utf-8", ct.lower())
      body = json.loads(h.wfile.buf.decode("utf-8"))
      self.assertEqual(body["message"], "利润率")


if __name__ == "__main__":
  unittest.main()
