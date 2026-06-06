"""前台审批刷新：JS 契约 + 只读接口二次拉取（无浏览器测试框架时的替代验证）。"""
from __future__ import annotations

import http.client
import json
import re
import threading
import unittest
import uuid
from http.server import HTTPServer
from pathlib import Path

from quote_upload_storage import save_quote_calculation
from server import QuoteHandler
from test_db_isolation import (
    cleanup_isolated_quote_db,
    mount_isolated_quote_db,
    restore_quote_db,
    sales_user_cookie,
)

APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _admin_headers() -> dict[str, str]:
    return {"X-User-Role": "admin", "Content-Type": "application/json; charset=utf-8"}


class FrontQuoteApprovalJsContractTest(unittest.TestCase):
    """项目无 Jest/Vitest/Puppeteer：用静态契约验证 app.js 接线。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app_js = APP_JS.read_text(encoding="utf-8")

    def test_app_js_does_not_call_admin_api(self) -> None:
        self.assertNotIn("/admin-api/", self.app_js)
        self.assertNotIn("admin-api", self.app_js)

    def test_approval_fetch_uses_public_get_only(self) -> None:
        self.assertIn(
            "quoteFetch(`/api/quotes/${encodeURIComponent(key)}/approval`)",
            self.app_js,
        )
        self.assertIn('credentials: "include"', self.app_js)
        self.assertIn('console.warn("[quote-approval] lookup failed"', self.app_js)
        self.assertIn('console.error("[quote-approval] lookup network error"', self.app_js)
        matches = re.findall(r"quoteFetch\([^)]+\)", self.app_js)
        admin_calls = [m for m in matches if "/admin-api/" in m or "/admin-api" in m]
        self.assertEqual(admin_calls, [], msg=admin_calls)

    def test_approval_lookup_id_accepts_archived_and_calc_ids(self) -> None:
        self.assertIn("quote?.quote_series_uid", self.app_js)
        self.assertIn("quote?.quote_uid", self.app_js)
        self.assertIn("quote?.quote_id", self.app_js)
        self.assertIn("quote?.calc_quote_id", self.app_js)
        self.assertIn("quote?.approved_calc_quote_id", self.app_js)

    def test_focus_visibility_and_render_triggers_registered(self) -> None:
        self.assertIn("function bindQuoteApprovalRefreshTriggers", self.app_js)
        self.assertIn('scheduleQuoteCardsApprovalRefresh("focus")', self.app_js)
        self.assertIn("visibilitychange", self.app_js)
        self.assertIn('scheduleQuoteCardsApprovalRefresh("visibility")', self.app_js)
        self.assertIn('scheduleQuoteCardsApprovalRefresh("render")', self.app_js)
        self.assertIn("bindQuoteApprovalRefreshTriggers();", self.app_js)
        self.assertIn("scheduleQuoteApprovalHydration(next)", self.app_js)

    def test_focus_visibility_use_force_refresh(self) -> None:
        self.assertIn('const force = reason === "focus" || reason === "visibility"', self.app_js)
        self.assertIn("refreshAllQuoteCardsApproval({ force })", self.app_js)

    def test_sales_sync_polling_and_triggers_wired(self) -> None:
        self.assertIn("SALES_SYNC_POLL_INTERVAL_MS", self.app_js)
        self.assertIn("startSalesSyncPolling", self.app_js)
        self.assertIn("refreshSalesSyncBundle", self.app_js)
        self.assertIn('scheduleSalesSyncRefresh("focus")', self.app_js)
        self.assertIn('scheduleSalesSyncRefresh("visibility")', self.app_js)
        self.assertIn('scheduleSalesSyncRefresh("online")', self.app_js)
        self.assertIn('addEventListener("online"', self.app_js)
        self.assertIn("/api/my/quotes", self.app_js)
        self.assertIn("/api/my/admin-updates", self.app_js)
        self.assertIn("isUserActivelyComposing", self.app_js)

    def test_sales_sync_auth_and_network_errors_surface_to_user(self) -> None:
        self.assertIn("throwIfSalesSyncAuthResponse", self.app_js)
        self.assertIn("res.status === 401 || res.status === 403", self.app_js)
        self.assertIn("notifySalesSyncAuthExpired", self.app_js)
        self.assertIn("notifySalesSyncNetworkIssue", self.app_js)
        self.assertIn("handleSalesSyncFetchError", self.app_js)
        self.assertIn("登录状态已过期", self.app_js)
        self.assertIn("refreshAdminUpdatesBadge({ silent: true })", self.app_js)
        self.assertIn("refreshMyQuotesPreview({ silent: true })", self.app_js)

    def test_wecom_entry_gate_and_auto_login_wired(self) -> None:
        self.assertIn("请从企业微信进入报价系统", self.app_js)
        self.assertIn("function renderWecomEntryGate", self.app_js)
        self.assertIn("function maybeAutoWecomLogin", self.app_js)
        self.assertIn("function handleWecomAuthUrlErrors", self.app_js)
        self.assertIn("wecom_browser_required", self.app_js)


class FrontQuoteApprovalRefreshFetchTest(unittest.TestCase):
    """模拟 focus/visibility 后的二次 GET：后台改状态后前台只读接口能读到。"""

    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()
        self.sales_uid = f"sales-{uuid.uuid4().hex[:10]}"
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

    def _get_json(self, path: str, *, cookie: str | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        hdr = {"Cookie": cookie} if cookie else {}
        conn.request("GET", path, headers=hdr)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _post_admin_approval(self, series_uid: str, payload: dict) -> None:
        body_payload = {"reviewer_name": "张三", **payload}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        raw = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")
        conn.request(
            "POST",
            f"/admin-api/quotes/{series_uid}/approval",
            body=raw,
            headers=_admin_headers(),
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)

    def test_second_get_after_admin_approved_simulates_refresh(self) -> None:
        series_uid = f"refresh-{uuid.uuid4().hex[:12]}"
        calc_id = f"calc-{uuid.uuid4().hex[:12]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="r.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "product_name": "刷新模拟",
                "material_total": 1.0,
                "tiers": [{"cost_before_margin": 1.0}],
                "detail_rows": [],
            },
            sales_user_id=self.sales_uid,
        )
        cookie = sales_user_cookie(self.sales_uid)
        code1, body1 = self._get_json(f"/api/quotes/{calc_id}/approval", cookie=cookie)
        self.assertEqual(code1, 200)
        self.assertEqual(body1.get("approval_status"), "pending")

        _attach_site(self.httpd, "admin")
        self._post_admin_approval(
            series_uid,
            {"approval_status": "approved", "approval_note": "二次拉取应看到合格"},
        )
        _attach_site(self.httpd, "front")

        code2, body2 = self._get_json(f"/api/quotes/{calc_id}/approval", cookie=cookie)
        self.assertEqual(code2, 200)
        self.assertEqual(body2.get("approval_status"), "approved")
        self.assertEqual(body2.get("approval_note"), "二次拉取应看到合格")
        self.assertNotIn("quote_uid", body2)

    def test_admin_approved_visible_in_my_quotes_and_admin_updates(self) -> None:
        series_uid = f"sync-{uuid.uuid4().hex[:12]}"
        calc_id = f"calc-{uuid.uuid4().hex[:12]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="sync.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "product_name": "同步验收",
                "material_total": 2.0,
                "tiers": [{"cost_before_margin": 2.0}],
                "detail_rows": [],
            },
            sales_user_id=self.sales_uid,
        )
        cookie = sales_user_cookie(self.sales_uid)
        _attach_site(self.httpd, "admin")
        self._post_admin_approval(
            series_uid,
            {"approval_status": "approved", "approval_note": "可对外报价"},
        )
        _attach_site(self.httpd, "front")

        code_m, body_m = self._get_json("/api/my/quotes", cookie=cookie)
        self.assertEqual(code_m, 200)
        row = next(
            (x for x in (body_m.get("items") or []) if x.get("quote_series_uid") == series_uid),
            None,
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.get("approval_status"), "approved")
        self.assertTrue(row.get("has_admin_update"))

        code_u, body_u = self._get_json("/api/my/admin-updates", cookie=cookie)
        self.assertEqual(code_u, 200)
        self.assertGreaterEqual(int(body_u.get("unread_count") or 0), 1)
        inbox = next(
            (x for x in (body_u.get("items") or []) if x.get("quote_series_uid") == series_uid),
            None,
        )
        self.assertIsNotNone(inbox)
        assert inbox is not None
        self.assertEqual(inbox.get("approval_status"), "approved")
        self.assertTrue(inbox.get("has_admin_update"))

    def test_admin_rejected_visible_in_admin_updates(self) -> None:
        series_uid = f"rej-{uuid.uuid4().hex[:12]}"
        calc_id = f"calc-{uuid.uuid4().hex[:12]}"
        note = "规格用量需重核"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="rej.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "product_name": "驳回同步",
                "material_total": 3.0,
                "tiers": [{"cost_before_margin": 3.0}],
                "detail_rows": [],
            },
            sales_user_id=self.sales_uid,
        )
        cookie = sales_user_cookie(self.sales_uid)
        _attach_site(self.httpd, "admin")
        self._post_admin_approval(
            series_uid,
            {"approval_status": "rejected", "approval_note": note},
        )
        _attach_site(self.httpd, "front")

        code_a, body_a = self._get_json(f"/api/quotes/{calc_id}/approval", cookie=cookie)
        self.assertEqual(code_a, 200)
        self.assertEqual(body_a.get("approval_status"), "rejected")
        self.assertEqual(body_a.get("approval_note"), note)

        code_u, body_u = self._get_json("/api/my/admin-updates", cookie=cookie)
        self.assertEqual(code_u, 200)
        inbox = next(
            (x for x in (body_u.get("items") or []) if x.get("quote_series_uid") == series_uid),
            None,
        )
        self.assertIsNotNone(inbox)
        assert inbox is not None
        self.assertTrue(inbox.get("has_admin_update"))
        self.assertEqual(inbox.get("rejection_reason"), note)
        self.assertGreaterEqual(int(body_u.get("unread_count") or 0), 1)


MANUAL_FRONT_REFRESH_STEPS = """
手动验收（无浏览器 E2E 框架时）：
1. 前台 8776 生成报价卡片，保持页面不关。
2. 后台 8777 将同一条改为「合格」或「不合格」并保存。
3. 切到其他窗口/标签再切回前台（触发 focus + visibilitychange）。
4. 约 0.5s 内横幅应更新；Network 仅见 GET /api/quotes/{id}/approval，无 /admin-api/*。
"""


if __name__ == "__main__":
    unittest.main()
