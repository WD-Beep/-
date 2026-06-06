"""回归：异常数据批量删除 store + POST /admin-api/price-exceptions/delete-batch。"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
import uuid
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

from price_admin_store import delete_price_exceptions_bulk
from server import QuoteHandler


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _admin_headers() -> dict[str, str]:
    return {"X-User-Role": "admin", "Content-Type": "application/json; charset=utf-8"}


class DeletePriceExceptionsBulkStoreTest(unittest.TestCase):
    def test_bulk_delete_removes_selected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "price_exceptions.jsonl"
            rows = [
                {"exception_id": "exc-a", "name": "A", "exception_status": "open"},
                {"exception_id": "exc-b", "name": "B", "exception_status": "open"},
                {"exception_id": "exc-c", "name": "C", "exception_status": "open"},
            ]
            path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )
            result = delete_price_exceptions_bulk(
                ["exc-a", "exc-c"],
                exception_path=path,
                updated_by="tester",
            )
            self.assertTrue(result.get("ok"))
            self.assertEqual(result.get("deleted_count"), 2)
            remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].get("exception_id"), "exc-b")

    def test_bulk_delete_empty_ids_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "price_exceptions.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                delete_price_exceptions_bulk([], exception_path=path)


class PriceExceptionsBatchDeleteRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.httpd, "admin")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.th.join(timeout=2)
        self.httpd.server_close()

    def _post_json(
        self, path: str, payload: dict, headers: dict[str, str] | None = None
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        hdr = dict(headers or {})
        if "Content-Type" not in hdr:
            hdr["Content-Type"] = "application/json; charset=utf-8"
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request("POST", path, body=raw, headers=hdr)
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def test_batch_delete_requires_admin(self) -> None:
        code, body = self._post_json(
            "/admin-api/price-exceptions/delete-batch",
            {"exception_ids": ["exc-test"]},
        )
        self.assertEqual(code, 403, msg=body)
        self.assertEqual(body.get("error"), "forbidden")

    def test_batch_delete_empty_ids_returns_400(self) -> None:
        code, body = self._post_json(
            "/admin-api/price-exceptions/delete-batch",
            {"exception_ids": []},
            headers=_admin_headers(),
        )
        self.assertEqual(code, 400, msg=body)
        self.assertEqual(body.get("error"), "invalid_request")

    @patch("server.delete_price_exceptions_bulk")
    def test_batch_delete_admin_success(self, mock_bulk) -> None:
        ids = [f"exc-{uuid.uuid4().hex[:8]}" for _ in range(2)]
        mock_bulk.return_value = {
            "ok": True,
            "deleted_count": 2,
            "deleted": [{"exception_id": ids[0]}, {"exception_id": ids[1]}],
            "not_found_ids": [],
        }
        code, body = self._post_json(
            "/admin-api/price-exceptions/delete-batch",
            {"exception_ids": ids, "updated_by": "admin_tester"},
            headers=_admin_headers(),
        )
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("deleted_count"), 2)
        mock_bulk.assert_called_once()
        call_args = mock_bulk.call_args
        self.assertEqual(call_args[0][0], ids)
        self.assertEqual(call_args[1].get("updated_by"), "admin_tester")


if __name__ == "__main__":
    unittest.main()
