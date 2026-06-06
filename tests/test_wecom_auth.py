"""企业微信 OAuth 与业务员身份隔离。"""
from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
import uuid
from http.server import HTTPServer
from unittest import mock

import quote_upload_storage as qus
from quote_upload_storage import (
    finalize_quote_persistence,
    get_saved_quote_approval_for_sales_user,
    list_my_quotes_for_sales_user,
    save_quote_calculation,
)
from server import QuoteHandler
from session_quote_context import (
    clear_sales_user_cookie_header_value,
    cookie_secure_enabled,
    set_sales_user_cookie_header_value,
    set_sales_user_name_cookie_header_value,
)
from test_db_isolation import (
    WECOM_TEST_SALES_SECRET,
    WECOM_TEST_UA,
    cleanup_isolated_quote_db,
    mount_isolated_quote_db,
    restore_quote_db,
    sales_user_cookie,
    wecom_sales_user_cookie,
)


class WecomCookieSameSiteTest(unittest.TestCase):
    @mock.patch.dict(os.environ, {"COOKIE_SAMESITE": "none", "COOKIE_SECURE": "1"}, clear=False)
    def test_cookie_samesite_none_requires_secure(self) -> None:
        from session_quote_context import cookie_samesite_value, cookie_secure_required

        self.assertEqual(cookie_samesite_value(), "None")
        self.assertTrue(cookie_secure_required())
        hdr = set_sales_user_cookie_header_value("wecom:test")
        self.assertIn("SameSite=None", hdr)
        self.assertIn("Secure", hdr)


class WecomCookieSecureTest(unittest.TestCase):
    @mock.patch.dict(os.environ, {"COOKIE_SECURE": "0", "WECOM_COOKIE_SECURE": "0"}, clear=False)
    def test_cookie_secure_off_by_default(self) -> None:
        hdr = set_sales_user_cookie_header_value("wecom:test")
        self.assertIn("SameSite=Lax", hdr)
        self.assertNotIn("Secure", hdr)

    @mock.patch.dict(os.environ, {"COOKIE_SECURE": "1", "WECOM_COOKIE_SECURE": "0"}, clear=False)
    def test_cookie_secure_via_cookie_secure_env(self) -> None:
        self.assertTrue(cookie_secure_enabled())
        hdr = set_sales_user_cookie_header_value("wecom:test")
        self.assertIn("Secure", hdr)
        self.assertIn("SameSite=Lax", hdr)

    @mock.patch.dict(os.environ, {"COOKIE_SECURE": "0", "WECOM_COOKIE_SECURE": "1"}, clear=False)
    def test_cookie_secure_via_wecom_cookie_secure_env(self) -> None:
        self.assertTrue(cookie_secure_enabled())
        hdr = set_sales_user_name_cookie_header_value("张三")
        self.assertIn("Secure", hdr)
        self.assertIn("SameSite=Lax", hdr)
        self.assertIn("Max-Age=0", clear_sales_user_cookie_header_value())
        self.assertIn("Secure", clear_sales_user_cookie_header_value())


from wecom_auth import (
    format_wecom_sales_user_id,
    is_wecom_browser_user_agent,
    is_wecom_sales_user_id,
    oauth_return_absolute_url,
    sanitize_oauth_return_path,
    wecom_enabled,
    wecom_login_entry_path,
)


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


_WECOM_ENABLED_ENVS = {
    "WECOM_ENABLED": "1",
    "WECOM_CORP_ID": "ww-test",
    "WECOM_AGENT_ID": "1000001",
    "WECOM_CORP_SECRET": "secret",
    "WECOM_OAUTH_REDIRECT_URI": "http://127.0.0.1:8776/api/auth/wecom/callback",
    "WECOM_PUBLIC_BASE_URL": "http://127.0.0.1:8776",
    "QUOTE_SALES_SECRET": WECOM_TEST_SALES_SECRET,
}


class WecomAuthUnitTest(unittest.TestCase):
    def test_format_wecom_sales_user_id(self) -> None:
        self.assertEqual(format_wecom_sales_user_id("ZhangSan"), "wecom:ZhangSan")
        self.assertEqual(format_wecom_sales_user_id("wecom:ZhangSan"), "wecom:ZhangSan")
        self.assertTrue(is_wecom_sales_user_id("wecom:ZhangSan"))
        self.assertFalse(is_wecom_sales_user_id("local-uuid"))

    def test_is_wecom_browser_user_agent(self) -> None:
        self.assertTrue(is_wecom_browser_user_agent("Mozilla/5.0 wxwork/4.0"))
        self.assertFalse(is_wecom_browser_user_agent("MicroMessenger/8.0"))
        self.assertFalse(is_wecom_browser_user_agent("Mozilla/5.0 Chrome/120.0"))

    @mock.patch.dict(os.environ, {"WECOM_ENABLED": "0"}, clear=False)
    def test_wecom_disabled_by_default(self) -> None:
        self.assertFalse(wecom_enabled())

    @mock.patch.dict(
        os.environ,
        {"WECOM_ENABLED": "1", "QUOTE_SALES_SECRET": "", "QUOTE_ADMIN_SECRET": ""},
        clear=False,
    )
    def test_wecom_without_secret_cannot_issue_or_verify_session(self) -> None:
        from sales_auth import (
            decode_sales_session_token,
            issue_sales_session_token,
            sales_session_crypto_ready,
            sales_session_secret_configured,
        )

        self.assertFalse(sales_session_secret_configured())
        self.assertFalse(sales_session_crypto_ready())
        with self.assertRaises(RuntimeError) as ctx:
            issue_sales_session_token("wecom:test")
        self.assertIn("QUOTE_SALES_SECRET", str(ctx.exception))

        with mock.patch.dict(os.environ, {"WECOM_ENABLED": "0"}, clear=False):
            dev_token = issue_sales_session_token("wecom:test")
        self.assertTrue(dev_token)
        with mock.patch.dict(os.environ, {"WECOM_ENABLED": "1"}, clear=False):
            self.assertIsNone(decode_sales_session_token(dev_token))

    def test_sanitize_oauth_return_path(self) -> None:
        self.assertEqual(sanitize_oauth_return_path("/"), "/")
        self.assertEqual(sanitize_oauth_return_path("//evil"), "/")
        self.assertEqual(sanitize_oauth_return_path("http://evil/"), "/")
        self.assertEqual(sanitize_oauth_return_path(""), "/")

    def test_wecom_login_entry_path(self) -> None:
        self.assertEqual(wecom_login_entry_path(return_path="/"), "/api/auth/wecom/login?state=%2F")

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_oauth_return_absolute_url(self) -> None:
        from wecom_auth import get_wecom_config

        cfg = get_wecom_config()
        assert cfg is not None
        self.assertEqual(oauth_return_absolute_url("/", cfg=cfg), "http://127.0.0.1:8776/")

    @mock.patch.dict(os.environ, {"WECOM_ENABLED": "0"}, clear=False)
    def test_local_mode_uses_dev_secret_for_session(self) -> None:
        from sales_auth import decode_sales_session_token, issue_sales_session_token

        token = issue_sales_session_token("wecom:local-dev")
        data = decode_sales_session_token(token)
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data.get("sales_user_id"), "wecom:local-dev")


class WecomAuthHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.httpd, "front")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()
        self.user_a = "ZhangSan"
        self.user_b = "LiSi"

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
        cookie: str | None = None,
        payload: dict | None = None,
        user_agent: str | None = None,
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        hdr: dict[str, str] = {}
        if cookie:
            hdr["Cookie"] = cookie
        hdr["User-Agent"] = user_agent or WECOM_TEST_UA
        body_raw = None
        if payload is not None:
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

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_front_entry_redirects_to_wecom_login_without_cookie(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request("GET", "/", headers={"User-Agent": WECOM_TEST_UA})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 302)
        location = resp.getheader("Location") or ""
        conn.close()
        self.assertIn("/api/auth/wecom/login", location)
        self.assertIn("state=", location)

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_front_entry_serves_html_when_authenticated(self) -> None:
        cookie = wecom_sales_user_cookie(self.user_a, name="张三")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request("GET", "/", headers={"User-Agent": WECOM_TEST_UA, "Cookie": cookie})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"<!doctype html>", body[:500].lower())

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_front_entry_skips_redirect_after_oauth_error(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request(
            "GET",
            "/?wecom_auth_error=wecom_oauth_failed&wecom_auth_message=fail",
            headers={"User-Agent": WECOM_TEST_UA},
        )
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"<!doctype html>", body[:500].lower())

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_wecom_login_redirects_to_oauth(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request("GET", "/api/auth/wecom/login?state=/", headers={"User-Agent": WECOM_TEST_UA})
        resp = conn.getresponse()
        location = resp.getheader("Location") or ""
        conn.close()
        self.assertEqual(resp.status, 302)
        self.assertIn("open.weixin.qq.com/connect/oauth2/authorize", location)
        self.assertIn("state=%2F", location)

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_auth_status_exposes_login_entry_not_raw_oauth(self) -> None:
        st, body = self._request("GET", "/api/auth/status")
        self.assertEqual(st, 200, msg=body)
        self.assertTrue(body.get("wecom_enabled"))
        self.assertFalse(body.get("authenticated"))
        login_url = str(body.get("login_url") or "")
        self.assertIn("/api/auth/wecom/login", login_url)
        self.assertNotIn("open.weixin.qq.com", login_url)
        self.assertTrue(body.get("auto_login"))

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_wecom_enabled_requires_auth_for_my_quotes(self) -> None:
        st, body = self._request("GET", "/api/my/quotes")
        self.assertEqual(st, 401, msg=body)
        self.assertEqual(body.get("error"), "auth_required")

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_wecom_user_can_list_own_quotes(self) -> None:
        sales_uid = format_wecom_sales_user_id(self.user_a)
        series_uid = f"wecom-series-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        finalize_quote_persistence(
            quote_series_uid=series_uid,
            quote_result={
                "quote_id": calc_id,
                "product_name": "企微报价",
                "material_total": 10.0,
                "tiers": [{"cost_before_margin": 10.0}],
                "detail_rows": [],
            },
            uploaded_sheet=None,
            sheet_original_display_name="w.xlsx",
            sales_user_id=sales_uid,
            sales_user_name="张三",
        )
        cookie = wecom_sales_user_cookie(self.user_a, name="张三")
        st, body = self._request("GET", "/api/my/quotes", cookie=cookie)
        self.assertEqual(st, 200, msg=body)
        self.assertEqual(body.get("sales_user_id"), sales_uid)
        self.assertEqual(len(body.get("items") or []), 1)

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_wecom_cross_user_approval_blocked(self) -> None:
        sales_a = format_wecom_sales_user_id(self.user_a)
        series_uid = f"wecom-appr-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="a.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "product_name": "隔离",
                "material_total": 1.0,
                "tiers": [{"cost_before_margin": 1.0}],
                "detail_rows": [],
            },
            sales_user_id=sales_a,
        )
        self.assertIsNotNone(get_saved_quote_approval_for_sales_user(calc_id, sales_a))
        st, body = self._request(
            "GET",
            f"/api/quotes/{calc_id}/approval",
            cookie=wecom_sales_user_cookie(self.user_b),
        )
        self.assertEqual(st, 404, msg=body)

    @mock.patch.dict(os.environ, {"WECOM_ENABLED": "0"}, clear=False)
    def test_local_mode_still_auto_identity(self) -> None:
        st, body = self._request("GET", "/api/auth/status")
        self.assertEqual(st, 200)
        self.assertFalse(body.get("wecom_enabled"))
        st2, body2 = self._request("GET", "/api/my/quotes", cookie=sales_user_cookie(f"local-{uuid.uuid4().hex[:8]}"))
        self.assertEqual(st2, 200)

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    @mock.patch("server.exchange_code_for_profile", return_value=("wecom:OAuthUser", "OAuth用户"))
    def test_wecom_oauth_callback_sets_identity(self, _mock_exchange: mock.Mock) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request("GET", "/api/auth/wecom/callback?code=fake-code&state=/")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 302)
        location = resp.getheader("Location") or ""
        cookies = [v for (k, v) in resp.getheaders() if k.lower() == "set-cookie"]
        conn.close()
        self.assertEqual(location, "http://127.0.0.1:8776/")
        joined = " ".join(cookies)
        self.assertIn("aq_sales_sess=", joined)
        self.assertIn("HttpOnly", joined)
        cookie = wecom_sales_user_cookie("OAuthUser", name="OAuth用户")
        st, body = self._request("GET", "/api/auth/status", cookie=cookie)
        self.assertEqual(st, 200)
        self.assertTrue(body.get("authenticated"))
        self.assertEqual(body.get("sales_user_id"), "wecom:OAuthUser")

    @mock.patch.dict(
        os.environ,
        {**_WECOM_ENABLED_ENVS, "WECOM_COOKIE_SECURE": "1"},
        clear=False,
    )
    @mock.patch("server.exchange_code_for_profile", return_value=("wecom:SecureUser", "Secure"))
    def test_wecom_oauth_callback_sets_secure_cookie(self, _mock_exchange: mock.Mock) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request("GET", "/api/auth/wecom/callback?code=fake-code&state=abc")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 302)
        cookies = [v for (k, v) in resp.getheaders() if k.lower() == "set-cookie"]
        conn.close()
        joined = " ".join(cookies)
        self.assertIn("aq_sales_sess=", joined)
        self.assertIn("Secure", joined)

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_forged_plain_wecom_cookie_rejected(self) -> None:
        from test_db_isolation import forged_wecom_plain_cookie

        cookie = forged_wecom_plain_cookie("Attacker")
        st, body = self._request("GET", "/api/my/quotes", cookie=cookie)
        self.assertEqual(st, 401, msg=body)
        self.assertEqual(body.get("error"), "auth_required")

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_non_wecom_browser_blocked_from_my_quotes(self) -> None:
        cookie = wecom_sales_user_cookie(self.user_a, name="张三")
        st, body = self._request(
            "GET",
            "/api/my/quotes",
            cookie=cookie,
            user_agent="Mozilla/5.0 Chrome/120.0",
        )
        self.assertEqual(st, 403, msg=body)
        self.assertEqual(body.get("error"), "wecom_browser_required")
        self.assertIn("企业微信", str(body.get("message") or ""))

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_wecom_browser_with_cookie_can_access_my_quotes(self) -> None:
        sales_uid = format_wecom_sales_user_id(self.user_a)
        series_uid = f"wecom-ua-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        finalize_quote_persistence(
            quote_series_uid=series_uid,
            quote_result={
                "quote_id": calc_id,
                "product_name": "UA检测",
                "material_total": 1.0,
                "tiers": [{"cost_before_margin": 1.0}],
                "detail_rows": [],
            },
            uploaded_sheet=None,
            sheet_original_display_name="ua.xlsx",
            sales_user_id=sales_uid,
            sales_user_name="张三",
        )
        cookie = wecom_sales_user_cookie(self.user_a, name="张三")
        st, body = self._request(
            "GET",
            "/api/my/quotes",
            cookie=cookie,
            user_agent="Mozilla/5.0 wxwork/4.0",
        )
        self.assertEqual(st, 200, msg=body)
        self.assertEqual(len(body.get("items") or []), 1)

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_non_wecom_browser_blocked_from_quote_api(self) -> None:
        st, body = self._request(
            "POST",
            "/api/quote",
            payload={"user_prompt": "测试"},
            user_agent="Mozilla/5.0 Chrome/120.0",
        )
        self.assertEqual(st, 403, msg=body)
        self.assertEqual(body.get("error"), "wecom_browser_required")

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_wecom_oauth_callback_error_redirects(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request("GET", "/api/auth/wecom/callback?state=abc")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 302)
        location = resp.getheader("Location") or ""
        conn.close()
        self.assertIn("wecom_auth_error=", location)
        self.assertIn("wecom_auth_message=", location)

    @mock.patch.dict(os.environ, _WECOM_ENABLED_ENVS, clear=False)
    def test_wechat_micromessenger_ua_blocked_from_my_quotes(self) -> None:
        cookie = wecom_sales_user_cookie(self.user_a, name="张三")
        st, body = self._request(
            "GET",
            "/api/my/quotes",
            cookie=cookie,
            user_agent="Mozilla/5.0 MicroMessenger/8.0",
        )
        self.assertEqual(st, 403, msg=body)
        self.assertEqual(body.get("error"), "wecom_browser_required")

    @mock.patch.dict(
        os.environ,
        {
            "WECOM_ENABLED": "1",
            "WECOM_CORP_ID": "ww-test",
            "WECOM_AGENT_ID": "1000001",
            "WECOM_CORP_SECRET": "secret",
            "WECOM_OAUTH_REDIRECT_URI": "http://127.0.0.1:8776/api/auth/wecom/callback",
            "WECOM_PUBLIC_BASE_URL": "http://127.0.0.1:8776",
            "QUOTE_SALES_SECRET": "",
            "QUOTE_ADMIN_SECRET": "",
        },
        clear=False,
    )
    @mock.patch("server.exchange_code_for_profile", return_value=("wecom:NoSecret", "无密钥"))
    def test_wecom_oauth_callback_fails_without_sales_secret(self, _mock_exchange: mock.Mock) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request("GET", "/api/auth/wecom/callback?code=fake-code&state=abc")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 302)
        location = resp.getheader("Location") or ""
        conn.close()
        self.assertIn("sales_secret_missing", location)
        self.assertIn("QUOTE_SALES_SECRET", location)


if __name__ == "__main__":
    unittest.main()
