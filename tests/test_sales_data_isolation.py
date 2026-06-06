"""业务员数据隔离 + 管理员审批定向可见。"""
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
from quote_storage.db_common import sales_user_owns_quote
from quote_upload_storage import (
    batch_hide_quotes_for_sales_user,
    finalize_quote_persistence,
    get_my_quote_session_detail,
    get_saved_quote_approval_for_sales_user,
    list_my_quotes_for_sales_user,
    list_saved_quotes_summaries,
    save_quote_calculation,
    sales_user_can_access_quote,
    update_saved_quote_approval,
)
from server import QuoteHandler
from test_db_isolation import (
    WECOM_TEST_SALES_SECRET,
    WECOM_TEST_UA,
    cleanup_isolated_quote_db,
    mount_isolated_quote_db,
    restore_quote_db,
    sales_user_cookie,
    wecom_sales_user_cookie,
)
from wecom_auth import format_wecom_sales_user_id


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _sample_quote(*, calc_id: str, series_uid: str, product_name: str = "隔离测试包") -> dict:
    return {
        "quote_id": calc_id,
        "quote_series_uid": series_uid,
        "product_name": product_name,
        "material_total": 66.0,
        "material_total_text": "¥66.00",
        "detail_rows": [{"name": "面料", "amount": 66.0, "unit_price": "10元/码", "usage": "1码"}],
        "tiers": [{"cost_before_margin": 90.0, "total_cost": 90.0, "quantity": 300}],
        "quote_ready": True,
    }


class SalesUserOwnsQuoteTest(unittest.TestCase):
    def test_empty_owner_denied(self) -> None:
        self.assertFalse(sales_user_owns_quote("", "wecom:A"))
        self.assertFalse(sales_user_owns_quote("", "local-id"))

    def test_mismatch_denied(self) -> None:
        self.assertFalse(sales_user_owns_quote("wecom:A", "wecom:B"))

    def test_match_allowed(self) -> None:
        self.assertTrue(sales_user_owns_quote("wecom:A", "wecom:A"))


class SalesDataIsolationStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()
        self.sales_a = format_wecom_sales_user_id("UserA")
        self.sales_b = format_wecom_sales_user_id("UserB")

    def tearDown(self) -> None:
        restore_quote_db(self._saved_db)
        cleanup_isolated_quote_db(self._root)

    def _seed_quote(self, *, owner: str, owner_name: str, tag: str) -> str:
        series_uid = f"iso-{tag}-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{tag}-{uuid.uuid4().hex[:8]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name=f"{tag}.xlsx",
            uploaded_sheet=None,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid, product_name=f"产品-{tag}"),
            sales_user_id=owner,
            sales_user_name=owner_name,
        )
        return series_uid

    def test_list_and_detail_isolated_between_sales_users(self) -> None:
        uid_a = self._seed_quote(owner=self.sales_a, owner_name="张三", tag="a")
        uid_b = self._seed_quote(owner=self.sales_b, owner_name="李四", tag="b")

        items_a = list_my_quotes_for_sales_user(self.sales_a)
        items_b = list_my_quotes_for_sales_user(self.sales_b)
        self.assertEqual([it["quote_series_uid"] for it in items_a], [uid_a])
        self.assertEqual([it["quote_series_uid"] for it in items_b], [uid_b])

        self.assertIsNotNone(get_my_quote_session_detail(uid_a, self.sales_a))
        self.assertIsNone(get_my_quote_session_detail(uid_a, self.sales_b))
        self.assertIsNone(get_my_quote_session_detail(uid_b, self.sales_a))

    def test_guess_quote_uid_blocked_without_owner(self) -> None:
        series_uid = f"orphan-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="orphan.xlsx",
            uploaded_sheet=None,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
        )
        self.assertFalse(sales_user_can_access_quote(series_uid, self.sales_a))
        self.assertIsNone(get_my_quote_session_detail(series_uid, self.sales_a))

    def test_admin_approval_only_visible_to_owner(self) -> None:
        uid_a = self._seed_quote(owner=self.sales_a, owner_name="张三", tag="appr")
        update_saved_quote_approval(
            uid_a,
            approval_status="approved",
            approval_note="通过",
            reviewed_by="admin-test",
        )
        snap_a = get_saved_quote_approval_for_sales_user(uid_a, self.sales_a)
        snap_b = get_saved_quote_approval_for_sales_user(uid_a, self.sales_b)
        self.assertEqual(snap_a and snap_a.get("approval_status"), "approved")
        self.assertIsNone(snap_b)

        detail_a = get_my_quote_session_detail(uid_a, self.sales_a)
        assert detail_a is not None
        self.assertEqual(detail_a["approval_status"], "approved")
        self.assertIsNone(get_my_quote_session_detail(uid_a, self.sales_b))

    def test_batch_hide_only_own_records(self) -> None:
        uid_a = self._seed_quote(owner=self.sales_a, owner_name="张三", tag="hide")
        result = batch_hide_quotes_for_sales_user(self.sales_b, [uid_a])
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["not_found"], [uid_a])
        self.assertEqual(len(list_my_quotes_for_sales_user(self.sales_a)), 1)

        ok = batch_hide_quotes_for_sales_user(self.sales_a, [uid_a])
        self.assertEqual(ok["deleted"], 1)
        self.assertEqual(list_my_quotes_for_sales_user(self.sales_a), [])
        self.assertIsNotNone(qus.get_saved_quote_admin_bundle(uid_a))

    def test_admin_list_includes_sales_fields_and_filter(self) -> None:
        self._seed_quote(owner=self.sales_a, owner_name="张三", tag="adm1")
        self._seed_quote(owner=self.sales_b, owner_name="李四", tag="adm2")
        all_items, total = list_saved_quotes_summaries(limit=50, offset=0)
        self.assertGreaterEqual(total, 2)
        self.assertTrue(any(it.get("sales_user_id") == self.sales_a for it in all_items))

        filtered, ftotal = list_saved_quotes_summaries(limit=50, offset=0, sales_user_q="张三")
        self.assertGreaterEqual(ftotal, 1)
        self.assertTrue(all(self.sales_a in str(it.get("sales_user_id") or "") or "张三" in str(it.get("sales_user_name") or "") for it in filtered))


class SalesDataIsolationHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()
        self.front = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.front, "front")
        self.front_port = self.front.server_address[1]
        self.front_th = threading.Thread(target=self.front.serve_forever, daemon=True)
        self.front_th.start()
        self.sales_a = format_wecom_sales_user_id("HttpA")
        self.sales_b = format_wecom_sales_user_id("HttpB")
        self.series_a = f"http-a-{uuid.uuid4().hex[:8]}"
        self.calc_a = f"calc-a-{uuid.uuid4().hex[:8]}"
        finalize_quote_persistence(
            quote_series_uid=self.series_a,
            quote_result=_sample_quote(calc_id=self.calc_a, series_uid=self.series_a),
            uploaded_sheet=None,
            sheet_original_display_name="http-a.xlsx",
            sales_user_id=self.sales_a,
            sales_user_name="HttpA名",
        )

    def tearDown(self) -> None:
        self.front.shutdown()
        self.front_th.join(timeout=2)
        self.front.server_close()
        restore_quote_db(self._saved_db)
        cleanup_isolated_quote_db(self._root)

    def _front(
        self,
        method: str,
        path: str,
        *,
        cookie: str | None = None,
        payload: dict | None = None,
        user_agent: str | None = None,
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.front_port, timeout=8)
        hdr: dict[str, str] = {"User-Agent": user_agent or WECOM_TEST_UA}
        if cookie:
            hdr["Cookie"] = cookie
        body_raw = None
        if payload is not None:
            hdr["Content-Type"] = "application/json; charset=utf-8"
            body_raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request(method, path, body=body_raw, headers=hdr)
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8")) if buf else {}
        except json.JSONDecodeError:
            body = {"raw": buf.decode("utf-8", errors="replace")}
        return resp.status, body if isinstance(body, dict) else {}

    @mock.patch.dict(
        os.environ,
        {
            "WECOM_ENABLED": "1",
            "WECOM_CORP_ID": "ww-test",
            "WECOM_AGENT_ID": "1000001",
            "WECOM_CORP_SECRET": "secret",
            "WECOM_OAUTH_REDIRECT_URI": "http://127.0.0.1:8776/api/auth/wecom/callback",
            "WECOM_PUBLIC_BASE_URL": "http://127.0.0.1:8776",
            "QUOTE_SALES_SECRET": WECOM_TEST_SALES_SECRET,
        },
        clear=False,
    )
    def test_http_my_quotes_and_detail_isolated(self) -> None:
        cookie_a = wecom_sales_user_cookie("HttpA", name="HttpA名")
        cookie_b = wecom_sales_user_cookie("HttpB", name="HttpB名")

        st_a, body_a = self._front("GET", "/api/my/quotes", cookie=cookie_a)
        self.assertEqual(st_a, 200, msg=body_a)
        self.assertEqual(len(body_a.get("items") or []), 1)

        st_b, body_b = self._front("GET", "/api/my/quotes", cookie=cookie_b)
        self.assertEqual(st_b, 200, msg=body_b)
        self.assertEqual(body_b.get("items") or [], [])

        st_detail_b, _ = self._front(
            "GET",
            f"/api/my/quotes/{self.series_a}",
            cookie=cookie_b,
        )
        self.assertEqual(st_detail_b, 404)

        st_batch, body_batch = self._front(
            "POST",
            "/api/my/quotes/batch-delete",
            cookie=cookie_b,
            payload={"quote_uids": [self.series_a]},
        )
        self.assertEqual(st_batch, 200, msg=body_batch)
        self.assertEqual(body_batch.get("deleted"), 0)

        st_appr, _ = self._front(
            "GET",
            f"/api/quotes/{self.calc_a}/approval",
            cookie=cookie_b,
        )
        self.assertEqual(st_appr, 404)

        update_saved_quote_approval(
            self.series_a,
            approval_status="approved",
            approval_note="仅A可见",
            reviewed_by="admin",
        )
        st_appr_a, body_appr_a = self._front(
            "GET",
            f"/api/quotes/{self.calc_a}/approval",
            cookie=cookie_a,
        )
        self.assertEqual(st_appr_a, 200, msg=body_appr_a)
        self.assertEqual(body_appr_a.get("approval_status"), "approved")

        st_appr_b2, _ = self._front(
            "GET",
            f"/api/quotes/{self.calc_a}/approval",
            cookie=cookie_b,
        )
        self.assertEqual(st_appr_b2, 404)


class SalesAuthSecurityHTTPTest(unittest.TestCase):
    """企微开启时：伪造 Cookie / 前台伪造管理员头 必须失败。"""

    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()
        self.front = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.front, "front")
        self.front_port = self.front.server_address[1]
        self.front_th = threading.Thread(target=self.front.serve_forever, daemon=True)
        self.front_th.start()
        self.admin = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.admin, "admin")
        self.admin_port = self.admin.server_address[1]
        self.admin_th = threading.Thread(target=self.admin.serve_forever, daemon=True)
        self.admin_th.start()
        self.sales_a = format_wecom_sales_user_id("SecA")
        self.series_a = f"sec-a-{uuid.uuid4().hex[:8]}"
        self.calc_a = f"calc-a-{uuid.uuid4().hex[:8]}"
        finalize_quote_persistence(
            quote_series_uid=self.series_a,
            quote_result=_sample_quote(calc_id=self.calc_a, series_uid=self.series_a),
            uploaded_sheet=None,
            sheet_original_display_name="sec-a.xlsx",
            sales_user_id=self.sales_a,
            sales_user_name="SecA名",
        )

    def tearDown(self) -> None:
        self.front.shutdown()
        self.front_th.join(timeout=2)
        self.front.server_close()
        self.admin.shutdown()
        self.admin_th.join(timeout=2)
        self.admin.server_close()
        restore_quote_db(self._saved_db)
        cleanup_isolated_quote_db(self._root)

    def _front(
        self,
        method: str,
        path: str,
        *,
        cookie: str | None = None,
        payload: dict | None = None,
        headers: dict | None = None,
        user_agent: str | None = None,
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.front_port, timeout=8)
        hdr = dict(headers or {})
        hdr.setdefault("User-Agent", user_agent or WECOM_TEST_UA)
        if cookie:
            hdr["Cookie"] = cookie
        body_raw = None
        if payload is not None:
            hdr["Content-Type"] = "application/json; charset=utf-8"
            body_raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request(method, path, body=body_raw, headers=hdr)
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8")) if buf else {}
        except json.JSONDecodeError:
            body = {"raw": buf.decode("utf-8", errors="replace")}
        return resp.status, body if isinstance(body, dict) else {}

    def _admin(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.admin_port, timeout=8)
        hdr = dict(headers or {})
        body_raw = None
        if payload is not None:
            hdr["Content-Type"] = "application/json; charset=utf-8"
            body_raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request(method, path, body=body_raw, headers=hdr)
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8")) if buf else {}
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    @mock.patch.dict(
        os.environ,
        {
            "WECOM_ENABLED": "1",
            "WECOM_CORP_ID": "ww-test",
            "WECOM_AGENT_ID": "1000001",
            "WECOM_CORP_SECRET": "secret",
            "WECOM_OAUTH_REDIRECT_URI": "http://127.0.0.1:8776/api/auth/wecom/callback",
            "WECOM_PUBLIC_BASE_URL": "http://127.0.0.1:8776",
            "QUOTE_SALES_SECRET": WECOM_TEST_SALES_SECRET,
        },
        clear=False,
    )
    def test_forged_plain_cookie_cannot_read_other_user(self) -> None:
        from test_db_isolation import forged_wecom_plain_cookie

        st, body = self._front(
            "GET",
            f"/api/my/quotes/{self.series_a}",
            cookie=forged_wecom_plain_cookie("AttackerB"),
        )
        self.assertEqual(st, 401, msg=body)

        st2, _ = self._front(
            "GET",
            f"/api/quotes/{self.calc_a}/approval",
            cookie=forged_wecom_plain_cookie("AttackerB"),
        )
        self.assertEqual(st2, 401)

    @mock.patch.dict(
        os.environ,
        {
            "WECOM_ENABLED": "1",
            "WECOM_CORP_ID": "ww-test",
            "WECOM_AGENT_ID": "1000001",
            "WECOM_CORP_SECRET": "secret",
            "WECOM_OAUTH_REDIRECT_URI": "http://127.0.0.1:8776/api/auth/wecom/callback",
            "WECOM_PUBLIC_BASE_URL": "http://127.0.0.1:8776",
            "QUOTE_SALES_SECRET": WECOM_TEST_SALES_SECRET,
        },
        clear=False,
    )
    def test_front_forged_admin_header_cannot_approve(self) -> None:
        st, body = self._front(
            "POST",
            f"/admin-api/quotes/{self.series_a}/approval",
            payload={"approval_status": "approved", "approval_note": "hack"},
            headers={"X-User-Role": "admin"},
        )
        self.assertEqual(st, 404, msg=body)

    @mock.patch.dict(
        os.environ,
        {
            "WECOM_ENABLED": "1",
            "WECOM_CORP_ID": "ww-test",
            "WECOM_AGENT_ID": "1000001",
            "WECOM_CORP_SECRET": "secret",
            "WECOM_OAUTH_REDIRECT_URI": "http://127.0.0.1:8776/api/auth/wecom/callback",
            "WECOM_PUBLIC_BASE_URL": "http://127.0.0.1:8776",
            "QUOTE_SALES_SECRET": WECOM_TEST_SALES_SECRET,
        },
        clear=False,
    )
    def test_admin_site_rejects_header_without_dev_flag(self) -> None:
        st, body = self._admin(
            "POST",
            f"/admin-api/quotes/{self.series_a}/approval",
            payload={"approval_status": "approved", "approval_note": "hack"},
            headers={"X-User-Role": "admin"},
        )
        self.assertEqual(st, 403, msg=body)
        self.assertEqual(body.get("error"), "forbidden")
