"""前台只读审批查询（GET /api/quotes/{id}/approval）。"""
from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
import uuid
from http.server import HTTPServer
from unittest import mock

from quote_upload_storage import save_quote_calculation
from server import QuoteHandler
from test_db_isolation import (
    cleanup_isolated_quote_db,
    mount_isolated_quote_db,
    restore_quote_db,
    sales_user_cookie,
)

_SAFE_PUBLIC_KEYS = frozenset(
    {
        "approval_status",
        "approval_note",
        "approved_at",
        "approved_by",
        "request_id",
    }
)


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _admin_headers() -> dict[str, str]:
    return {"X-User-Role": "admin", "Content-Type": "application/json; charset=utf-8"}


class QuoteApprovalFrontRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()
        self.sales_a = f"sales-a-{uuid.uuid4().hex[:10]}"
        self.sales_b = f"sales-b-{uuid.uuid4().hex[:10]}"
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.httpd, "front")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.th.join(timeout=2)
        self.httpd.server_close()
        restore_quote_db(self._saved_db)
        cleanup_isolated_quote_db(self._root)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        hdr = dict(headers or {})
        if cookie:
            hdr["Cookie"] = cookie
        body_raw = None
        if payload is not None:
            if "Content-Type" not in hdr:
                hdr["Content-Type"] = "application/json; charset=utf-8"
            body_raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request(method, path, body=body_raw, headers=hdr)
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _seed_series(self, *, sales_user_id: str | None = None) -> tuple[str, str]:
        series_uid = f"front-approval-{uuid.uuid4().hex[:12]}"
        calc_id = f"calc-{uuid.uuid4().hex[:12]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="front-route.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "product_name": "前台审批读回",
                "material_total": 30.0,
                "tiers": [{"cost_before_margin": 30.0}],
                "detail_rows": [{"name": "主料", "amount": 10.0}],
            },
            sales_user_id=sales_user_id,
        )
        return series_uid, calc_id

    def test_get_returns_only_safe_fields_default_pending(self) -> None:
        series_uid, calc_id = self._seed_series(sales_user_id=self.sales_a)
        cookie = sales_user_cookie(self.sales_a)
        code, body = self._request("GET", f"/api/quotes/{calc_id}/approval", cookie=cookie)
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(_SAFE_PUBLIC_KEYS.issuperset(body.keys()), msg=body.keys())
        self.assertEqual(body.get("approval_status"), "pending")
        self.assertEqual(body.get("approval_note"), "")
        self.assertNotIn("quote_uid", body)
        self.assertNotIn("quote_json", body)
        self.assertNotIn("items", body)
        self.assertNotIn("meta", body)

        code2, body2 = self._request("GET", f"/api/quotes/{series_uid}/approval", cookie=cookie)
        self.assertEqual(code2, 200)
        self.assertEqual(body2.get("approval_status"), "pending")

    def test_get_unknown_id_returns_not_found(self) -> None:
        cookie = sales_user_cookie(self.sales_a)
        code, body = self._request("GET", "/api/quotes/no-such-archive-id/approval", cookie=cookie)
        self.assertEqual(code, 404, msg=body)
        self.assertEqual(body.get("error"), "not_found")

    def test_other_sales_user_cannot_read_approval(self) -> None:
        series_uid, calc_id = self._seed_series(sales_user_id=self.sales_a)
        code, body = self._request(
            "GET",
            f"/api/quotes/{calc_id}/approval",
            cookie=sales_user_cookie(self.sales_b),
        )
        self.assertIn(code, (403, 404), msg=body)
        code2, _ = self._request(
            "GET",
            f"/api/quotes/{series_uid}/approval",
            cookie=sales_user_cookie(self.sales_b),
        )
        self.assertIn(code2, (403, 404))

    def test_front_cannot_post_approval_or_admin_api(self) -> None:
        series_uid, _ = self._seed_series(sales_user_id=self.sales_a)
        code, body = self._request(
            "POST",
            f"/api/quotes/{series_uid}/approval",
            payload={"approval_status": "approved"},
        )
        self.assertEqual(code, 404, msg=body)
        code2, body2 = self._request(
            "POST",
            f"/admin-api/quotes/{series_uid}/approval",
            payload={"approval_status": "approved"},
            headers=_admin_headers(),
        )
        self.assertEqual(code2, 404, msg=body2)

    def test_front_post_admin_api_approval_returns_json_404_on_keepalive(self) -> None:
        """Regression: front POST /admin-api/* must drain body and stay JSON 404 on keep-alive."""
        series_uid, _ = self._seed_series(sales_user_id=self.sales_a)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        paths = (
            f"/api/quotes/{series_uid}/approval",
            f"/admin-api/quotes/{series_uid}/approval",
        )
        try:
            for idx, path in enumerate(paths):
                hdr = {"Content-Type": "application/json; charset=utf-8"}
                if path.startswith("/admin-api"):
                    hdr.update(_admin_headers())
                conn.request(
                    "POST",
                    path,
                    body=json.dumps({"approval_status": "approved"}, ensure_ascii=False).encode("utf-8"),
                    headers=hdr,
                )
                resp = conn.getresponse()
                raw = resp.read()
                self.assertEqual(resp.status, 404, msg=raw.decode("utf-8", errors="replace"))
                payload = json.loads(raw.decode("utf-8"))
                self.assertIn(payload.get("error"), ("not found", "not_found"), msg=payload)
                if idx == 1:
                    self.assertFalse(payload.get("ok", True), msg=payload)
        finally:
            conn.close()

    def test_front_reads_admin_rejected_note(self) -> None:
        series_uid, calc_id = self._seed_series(sales_user_id=self.sales_a)
        cookie = sales_user_cookie(self.sales_a)
        _attach_site(self.httpd, "admin")
        note = "用量口径不一致"
        post_code, post_body = self._request(
            "POST",
            f"/admin-api/quotes/{series_uid}/approval",
            payload={
                "approval_status": "rejected",
                "approval_note": note,
                "reviewer_name": "张三",
            },
            headers=_admin_headers(),
        )
        self.assertEqual(post_code, 200, msg=post_body)
        _attach_site(self.httpd, "front")
        get_code, get_body = self._request("GET", f"/api/quotes/{calc_id}/approval", cookie=cookie)
        self.assertEqual(get_code, 200)
        self.assertEqual(get_body.get("approval_status"), "rejected")
        self.assertEqual(get_body.get("approval_note"), note)
        self.assertTrue(get_body.get("approved_at"))
        self.assertEqual(get_body.get("approved_by"), "张三")

    def test_admin_post_still_requires_admin_on_admin_site(self) -> None:
        series_uid, _ = self._seed_series(sales_user_id=self.sales_a)
        _attach_site(self.httpd, "admin")
        code, body = self._request(
            "POST",
            f"/admin-api/quotes/{series_uid}/approval",
            payload={"approval_status": "approved", "approval_note": "应拒绝"},
        )
        self.assertEqual(code, 403, msg=body)
        _attach_site(self.httpd, "front")

    @mock.patch.dict(
        os.environ,
        {
            "WECOM_ENABLED": "1",
            "WECOM_CORP_ID": "ww-test",
            "WECOM_AGENT_ID": "1000001",
            "WECOM_CORP_SECRET": "secret",
            "WECOM_OAUTH_REDIRECT_URI": "http://127.0.0.1:8776/api/auth/wecom/callback",
            "WECOM_PUBLIC_BASE_URL": "http://127.0.0.1:8776",
        },
        clear=False,
    )
    def test_wecom_front_rejects_forged_admin_header(self) -> None:
        series_uid, _ = self._seed_series(sales_user_id=self.sales_a)
        code, body = self._request(
            "POST",
            f"/admin-api/quotes/{series_uid}/approval",
            payload={"approval_status": "approved"},
            headers=_admin_headers(),
        )
        self.assertEqual(code, 404, msg=body)


if __name__ == "__main__":
    unittest.main()
