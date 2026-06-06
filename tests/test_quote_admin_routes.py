"""前台阻断管理路径；后台站点（_quote_site=admin）提供 /admin-api/*。"""
from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
from http.server import HTTPServer

from server import QuoteHandler


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


class FrontSiteBlocksAdminHTTPTest(unittest.TestCase):
    """前台端口：不得暴露后台页面与管理下载接口。"""

    def setUp(self) -> None:
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.httpd, "front")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.th.join(timeout=2)
        self.httpd.server_close()

    def _get_json(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = dict(headers or {})
        conn.request("GET", path, headers=hdr)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request(
            "POST",
            path,
            body=raw,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _get_raw(self, path: str) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers, raw

    def test_blocked_paths_return_404_json(self) -> None:
        paths = (
            "/admin",
            "/admin/prices",
            "/admin/login",
            "/admin-api/session",
            "/api/admin/session",
            "/api/quotes/test-quote-id/files",
            "/api/quotes/files/nope/download",
        )
        for path in paths:
            code, body = self._get_json(path)
            self.assertEqual(code, 404, msg=path)
            self.assertEqual(body.get("error"), "not found", msg=path)

    def test_batch_delete_on_front_returns_404_not_admin_handler(self) -> None:
        """前台不得执行 admin-api POST（即使误配反向代理也不能写入后台）。"""
        code, body = self._post_json(
            "/admin-api/quotes/batch-delete",
            {"mode": "filtered_all", "confirm": "DELETE"},
        )
        self.assertEqual(code, 404, msg=body)
        self.assertEqual(body.get("error"), "not found")

    def test_batch_delete_normalized_double_slash_on_front(self) -> None:
        code, body = self._post_json(
            "/admin-api//quotes/batch-delete",
            {"mode": "filtered_all", "confirm": "DELETE"},
        )
        self.assertEqual(code, 404, msg=body)
        self.assertEqual(body.get("error"), "not found")

    def test_batch_delete_underscore_alias_on_front(self) -> None:
        code, body = self._post_json(
            "/admin-api/quotes/batch_delete",
            {"mode": "filtered_all", "confirm": "DELETE"},
        )
        self.assertEqual(code, 404, msg=body)
        self.assertEqual(body.get("error"), "not found")

    def test_correction_sheet_on_front_returns_404(self) -> None:
        """前台不得执行 correction-sheet 等 admin-api POST。"""
        code, body = self._post_json(
            "/admin-api/quotes/test-quote-uid/correction-sheet",
            {
                "uploaded_sheet": {
                    "name": "fix.csv",
                    "content_base64": "dGVzdA==",
                }
            },
        )
        self.assertEqual(code, 404, msg=body)
        self.assertEqual(body.get("error"), "not found")

    def test_translate_quote_sheet_endpoint(self) -> None:
        code, body = self._post_json(
            "/api/quote-sheet/translate-en",
            {
                "bundle": {
                    "meta": {"co_name": "深圳市栢博旅游用品有限公司", "quote_date_iso": "2026-05-17"},
                    "rows": [{"name": "尼龙包装袋", "qty": "300", "price": "2.5"}],
                }
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(body.get("ok"))
        self.assertIsInstance(body.get("meta_en"), dict)
        self.assertIsInstance(body.get("rows_en"), list)
        self.assertIsInstance(body.get("labels"), dict)
        self.assertIsInstance(body.get("fixed"), dict)

    def test_front_static_cache_bust_query(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/static/app.js?v=test")
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"const els", raw[:500])

    def test_front_root_with_wecom_query_serves_index(self) -> None:
        code, headers, raw = self._get_raw("/?wework_cf=test")
        self.assertEqual(code, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn(b"/static/app.js", raw)


class AdminSiteHTTPTest(unittest.TestCase):
    """独立后台站点：/admin-api/* 与会话。"""

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

    def _get_json(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = dict(headers or {})
        conn.request("GET", path, headers=hdr)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _post_raw(
        self, path: str, body: bytes, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = {"Content-Type": "application/json", **dict(headers or {})}
        conn.request("POST", path, body=body, headers=hdr)
        resp = conn.getresponse()
        raw = resp.read()
        out_headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, out_headers, raw

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request(
            "POST",
            path,
            body=raw,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def test_batch_delete_double_slash_on_admin_site(self) -> None:
        code, body = self._post_json(
            "/admin-api//quotes/batch-delete",
            {"mode": "filtered_all", "confirm": "DELETE"},
        )
        self.assertEqual(code, 403, msg=body)
        self.assertEqual(body.get("error"), "forbidden")

    def test_batch_delete_underscore_on_admin_site(self) -> None:
        code, body = self._post_json(
            "/admin-api/quotes/batch_delete",
            {"mode": "filtered_all", "confirm": "DELETE"},
        )
        self.assertEqual(code, 403, msg=body)
        self.assertEqual(body.get("error"), "forbidden")

    def test_list_files_requires_admin(self) -> None:
        code, body = self._get_json("/admin-api/quotes/test-quote-id/files")
        self.assertEqual(code, 403)
        self.assertEqual(body.get("error"), "forbidden")

    def test_list_files_admin_ok_shape(self) -> None:
        code, body = self._get_json(
            "/admin-api/quotes/test-quote-id/files",
            headers={"X-User-Role": "admin"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(body.get("quote_id"), "test-quote-id")
        self.assertIsInstance(body.get("files"), list)

    def test_admin_session_unauthenticated(self) -> None:
        code, body = self._get_json("/admin-api/session")
        self.assertEqual(code, 200)
        self.assertFalse(body.get("authenticated"))
        self.assertIsNone(body.get("role"))

    def test_admin_login_cookie_lists_quotes(self) -> None:
        prev = {k: os.environ.get(k) for k in ("QUOTE_ADMIN_USERNAME", "QUOTE_ADMIN_PASSWORD", "QUOTE_ADMIN_SECRET")}
        try:
            os.environ["QUOTE_ADMIN_USERNAME"] = "tadm"
            os.environ["QUOTE_ADMIN_PASSWORD"] = "tpw-secret"
            os.environ["QUOTE_ADMIN_SECRET"] = "unit-test-admin-secret-fixed-value"
            raw_body = json.dumps({"username": "tadm", "password": "tpw-secret"}).encode("utf-8")
            code, hdrs, raw = self._post_raw("/admin-api/login", raw_body)
            self.assertEqual(code, 200)
            parsed = json.loads(raw.decode("utf-8"))
            self.assertTrue(parsed.get("ok"))
            self.assertEqual(parsed.get("role"), "admin")
            set_cookie = hdrs.get("set-cookie", "")
            cookie_pair = set_cookie.split(";", 1)[0].strip()
            self.assertTrue(cookie_pair.startswith("aq_admin_sess="))

            code2, body2 = self._get_json(
                "/admin-api/quotes?page=1&page_size=10", headers={"Cookie": cookie_pair}
            )
            self.assertEqual(code2, 200)
            self.assertIn("items", body2)
            self.assertIn("total", body2)
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_get_admin_redirects_when_no_cookie(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/admin")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "/admin/login")
        self.assertEqual(len(body), 0)

    def test_user_cannot_login_admin_site(self) -> None:
        keys = (
            "QUOTE_ADMIN_USERNAME",
            "QUOTE_ADMIN_PASSWORD",
            "QUOTE_ADMIN_SECRET",
            "QUOTE_USER_USERNAME",
            "QUOTE_USER_PASSWORD",
        )
        prev = {k: os.environ.get(k) for k in keys}
        try:
            os.environ["QUOTE_ADMIN_SECRET"] = "unit-test-admin-secret-fixed-value"
            os.environ["QUOTE_ADMIN_USERNAME"] = "adm_x"
            os.environ["QUOTE_ADMIN_PASSWORD"] = "adm_pass_x"
            os.environ["QUOTE_USER_USERNAME"] = "usr_x"
            os.environ["QUOTE_USER_PASSWORD"] = "usr_pass_x"
            raw_body = json.dumps({"username": "usr_x", "password": "usr_pass_x"}).encode("utf-8")
            code, hdrs, raw = self._post_raw("/admin-api/login", raw_body)
            self.assertEqual(code, 403)
            parsed = json.loads(raw.decode("utf-8"))
            self.assertFalse(parsed.get("ok"))
            self.assertEqual(parsed.get("error"), "forbidden")
            self.assertFalse(hdrs.get("set-cookie", "").startswith("aq_admin_sess="))
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def _get_raw(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = dict(headers or {})
        conn.request("GET", path, headers=hdr)
        resp = conn.getresponse()
        raw = resp.read()
        out_headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, out_headers, raw

    def test_static_admin_js_cache_bust_query(self) -> None:
        code, hdrs, raw = self._get_raw("/static/admin/admin.js?v=utf8-test")
        self.assertEqual(code, 200, msg=raw[:200])
        ctype = hdrs.get("content-type", "")
        self.assertIn("javascript", ctype)
        self.assertIn(b"loadDashboardStats", raw)

    def test_admin_stats_requires_admin(self) -> None:
        code, body = self._get_json("/admin-api/stats")
        self.assertEqual(code, 403)
        self.assertEqual(body.get("error"), "forbidden")

    def test_admin_stats_shape_with_admin_header(self) -> None:
        code, body = self._get_json("/admin-api/stats", headers={"X-User-Role": "admin"})
        self.assertEqual(code, 200)
        self.assertIn("total_quotes", body)
        self.assertIn("today_new", body)
        self.assertIsInstance(body.get("total_quotes"), int)
        self.assertIsInstance(body.get("today_new"), int)

    def test_admin_quotes_list_default_filters(self) -> None:
        code, body = self._get_json(
            "/admin-api/quotes?page=1&page_size=10",
            headers={"X-User-Role": "admin"},
        )
        self.assertEqual(code, 200)
        self.assertIn("items", body)
        self.assertIn("total", body)
        self.assertIsInstance(body.get("items"), list)
        self.assertIsInstance(body.get("total"), int)

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/admin-api/quotes/files/nope/download")
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        self.assertEqual(resp.status, 403)
        body = json.loads(raw.decode("utf-8"))
        self.assertEqual(body.get("error"), "forbidden")

    def test_price_admin_requires_admin(self) -> None:
        code, body = self._get_json("/admin-api/prices")
        self.assertEqual(code, 403)
        self.assertEqual(body.get("error"), "forbidden")

    def test_price_admin_list_shape(self) -> None:
        code, body = self._get_json("/admin-api/prices", headers={"X-User-Role": "admin"})
        self.assertEqual(code, 200)
        self.assertIsInstance(body.get("items"), list)
        self.assertIn("total", body)

    def test_price_exceptions_requires_admin(self) -> None:
        code, body = self._get_json("/admin-api/price-exceptions")
        self.assertEqual(code, 403)
        self.assertEqual(body.get("error"), "forbidden")

    def test_price_exceptions_list_shape(self) -> None:
        code, body = self._get_json("/admin-api/price-exceptions", headers={"X-User-Role": "admin"})
        self.assertEqual(code, 200)
        self.assertIsInstance(body.get("items"), list)
        self.assertIn("total", body)

    def test_price_admin_stats_includes_exception_fields(self) -> None:
        code, body = self._get_json("/admin-api/prices/stats", headers={"X-User-Role": "admin"})
        self.assertEqual(code, 200)
        self.assertIn("open_exceptions", body)
        self.assertIn("total_exceptions", body)

    def test_price_admin_history_shape(self) -> None:
        code, body = self._get_json("/admin-api/prices/history", headers={"X-User-Role": "admin"})
        self.assertEqual(code, 200)
        self.assertIsInstance(body.get("items"), list)

    def test_price_delete_requires_admin(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("DELETE", "/admin-api/prices/row-2")
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        self.assertEqual(resp.status, 403)
        body = json.loads(raw.decode("utf-8"))
        self.assertEqual(body.get("error"), "forbidden")

    def test_price_export_requires_admin(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/admin-api/prices/export")
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        self.assertEqual(resp.status, 403)
        body = json.loads(raw.decode("utf-8"))
        self.assertEqual(body.get("error"), "forbidden")

    def test_price_export_returns_xlsx(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/admin-api/prices/export", headers={"X-User-Role": "admin"})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        ctype = resp.getheader("Content-Type") or ""
        self.assertIn("spreadsheetml", ctype)
        disp = resp.getheader("Content-Disposition") or ""
        self.assertIn("price_kb_", disp)
        self.assertGreater(len(raw), 100)
        self.assertEqual(raw[:2], b"PK")


if __name__ == "__main__":
    unittest.main()
