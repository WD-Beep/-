"""回归：POST /admin-api/price-exceptions/approve 权限与路由（防报价表审批改动误伤）。"""
from __future__ import annotations

import http.client
import json
import threading
import unittest
import uuid
from http.server import HTTPServer
from unittest.mock import patch

from server import QuoteHandler


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _admin_headers() -> dict[str, str]:
    return {"X-User-Role": "admin", "Content-Type": "application/json; charset=utf-8"}


class PriceExceptionsApproveRouteTest(unittest.TestCase):
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

    def test_approve_requires_admin(self) -> None:
        code, body = self._post_json(
            "/admin-api/price-exceptions/approve",
            {"exception_id": "exc-test", "price": "1.0/PCS"},
        )
        self.assertEqual(code, 403, msg=body)
        self.assertEqual(body.get("error"), "forbidden")

    def test_approve_route_missing_id_returns_400(self) -> None:
        code, body = self._post_json(
            "/admin-api/price-exceptions/approve",
            {},
            headers=_admin_headers(),
        )
        self.assertEqual(code, 400, msg=body)
        self.assertEqual(body.get("error"), "invalid_request")
        self.assertIn("异常", str(body.get("message") or ""))

    def test_approve_route_unknown_id_returns_400(self) -> None:
        code, body = self._post_json(
            "/admin-api/price-exceptions/approve",
            {"exception_id": f"no-such-{uuid.uuid4().hex}"},
            headers=_admin_headers(),
        )
        self.assertEqual(code, 400, msg=body)
        self.assertEqual(body.get("error"), "invalid_request")

    @patch("server.approve_price_exception")
    def test_approve_admin_success_delegates_to_store(self, mock_approve) -> None:
        eid = f"exc-http-{uuid.uuid4().hex[:10]}"
        mock_approve.return_value = {
            "ok": True,
            "exception_id": eid,
            "entry": {"name": "TEST_MAT", "status": "active"},
        }
        payload = {
            "exception_id": eid,
            "name": "TEST_MAT",
            "price": "2.5/PCS",
            "updated_by": "admin_tester",
        }
        code, body = self._post_json(
            "/admin-api/price-exceptions/approve",
            payload,
            headers=_admin_headers(),
        )
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("exception_id"), eid)
        mock_approve.assert_called_once()
        call_args = mock_approve.call_args
        self.assertEqual(call_args[0][0], eid)
        self.assertIsInstance(call_args[0][1], dict)

    def test_quote_approval_route_still_registered_on_admin_site(self) -> None:
        """报价表审批路由与价格异常审批并存，互不 404。"""
        code, body = self._post_json(
            "/admin-api/quotes/no-such-uid-for-route-check/approval",
            {"approval_status": "approved"},
            headers=_admin_headers(),
        )
        self.assertIn(code, (400, 500), msg=body)
        self.assertNotEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
