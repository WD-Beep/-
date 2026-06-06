"""业务员报价会话持久化 + 审批回看（前台 /api/my/quotes）。"""
from __future__ import annotations

import http.client
import json
import threading
import unittest
import uuid
from http.server import HTTPServer

import quote_upload_storage as qus
from quote_upload_storage import (
    batch_hide_quotes_for_sales_user,
    finalize_quote_persistence,
    get_my_quote_session_detail,
    get_saved_quote_approval_for_sales_user,
    list_my_quotes_for_sales_user,
    list_quote_chat_messages,
    save_quote_calculation,
    update_saved_quote_approval,
    upsert_quote_chat_messages,
)
from server import QuoteHandler
from test_db_isolation import (
    cleanup_isolated_quote_db,
    mount_isolated_quote_db,
    restore_quote_db,
    sales_user_cookie,
)


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _sample_quote(*, calc_id: str, series_uid: str) -> dict:
    return {
        "quote_id": calc_id,
        "quote_series_uid": series_uid,
        "product_name": "测试背包",
        "material_total": 88.5,
        "material_total_text": "¥88.50",
        "detail_rows": [{"name": "面料", "amount": 88.5, "unit_price": "10元/码", "usage": "1码"}],
        "tiers": [{"cost_before_margin": 120.0, "total_cost": 120.0, "quantity": 300}],
        "quote_ready": True,
    }


class SalesQuoteSessionStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()

    def tearDown(self) -> None:
        restore_quote_db(self._saved_db)
        cleanup_isolated_quote_db(self._root)

    def test_finalize_binds_sales_user_and_lists_history(self) -> None:
        sales_uid = f"sales-{uuid.uuid4().hex[:10]}"
        series_uid = f"series-{uuid.uuid4().hex[:10]}"
        calc_id = f"calc-{uuid.uuid4().hex[:10]}"
        quote = _sample_quote(calc_id=calc_id, series_uid=series_uid)
        finalize_quote_persistence(
            quote_series_uid=series_uid,
            quote_result=quote,
            uploaded_sheet=None,
            sheet_original_display_name="demo.xlsx",
            sales_user_id=sales_uid,
            sales_user_name="业务员-测试",
        )
        items = list_my_quotes_for_sales_user(sales_uid)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["quote_series_uid"], series_uid)
        self.assertEqual(items[0]["product_name"], "测试背包")
        self.assertEqual(items[0]["approval_status"], "pending")

    def test_save_and_restore_chat_messages(self) -> None:
        sales_uid = f"sales-{uuid.uuid4().hex[:10]}"
        series_uid = f"series-{uuid.uuid4().hex[:10]}"
        calc_id = f"calc-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="chat.xlsx",
            uploaded_sheet=None,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            sales_user_id=sales_uid,
        )
        saved = upsert_quote_chat_messages(
            series_uid,
            [
                {"message_id": "m-user-1", "role": "user", "content": "请报价", "metadata": {"type": "user_turn"}},
                {
                    "message_id": "m-asst-1",
                    "role": "assistant",
                    "content": "",
                    "metadata": {"type": "quote_card", "quote_id": calc_id},
                },
            ],
            sales_user_id=sales_uid,
        )
        self.assertEqual(saved, 2)
        detail = get_my_quote_session_detail(series_uid, sales_uid)
        assert detail is not None
        self.assertEqual(len(detail["messages"]), 2)
        self.assertIn("latest_quote_result", detail)
        self.assertEqual(detail["latest_quote_result"]["quote_id"], calc_id)

    def test_approval_updates_status_and_admin_message(self) -> None:
        sales_uid = f"sales-{uuid.uuid4().hex[:10]}"
        series_uid = f"series-{uuid.uuid4().hex[:10]}"
        calc_id = f"calc-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="appr.xlsx",
            uploaded_sheet=None,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            sales_user_id=sales_uid,
        )
        update_saved_quote_approval(
            series_uid,
            approval_status="approved",
            approval_note="价格 OK",
            reviewed_by="admin-test",
        )
        detail = get_my_quote_session_detail(series_uid, sales_uid)
        assert detail is not None
        self.assertEqual(detail["approval_status"], "approved")
        msgs = list_quote_chat_messages(series_uid)
        self.assertTrue(any(m.get("role") == "admin" for m in msgs))

        update_saved_quote_approval(
            series_uid,
            approval_status="rejected",
            approval_note="用量需复核",
            reviewed_by="admin-test",
        )
        detail2 = get_my_quote_session_detail(series_uid, sales_uid)
        assert detail2 is not None
        self.assertEqual(detail2["approval_status"], "rejected")
        self.assertIn("用量需复核", detail2["approval_comment"])

    def test_legacy_quote_without_sales_user_id_isolated_from_sales(self) -> None:
        series_uid = f"legacy-{uuid.uuid4().hex[:10]}"
        calc_id = f"calc-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="legacy.xlsx",
            uploaded_sheet=None,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
        )
        items = list_my_quotes_for_sales_user("any-session-id")
        self.assertEqual(items, [])
        detail = get_my_quote_session_detail(series_uid, "any-session-id")
        self.assertIsNone(detail)
        self.assertIsNotNone(qus.get_saved_quote_admin_bundle(series_uid))

    def test_approval_lookup_denies_other_sales_user(self) -> None:
        sales_a = f"sales-a-{uuid.uuid4().hex[:8]}"
        sales_b = f"sales-b-{uuid.uuid4().hex[:8]}"
        series_uid = f"series-{uuid.uuid4().hex[:10]}"
        calc_id = f"calc-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="iso.xlsx",
            uploaded_sheet=None,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            sales_user_id=sales_a,
        )
        self.assertIsNotNone(get_saved_quote_approval_for_sales_user(calc_id, sales_a))
        self.assertIsNone(get_saved_quote_approval_for_sales_user(calc_id, sales_b))

    def test_batch_hide_removes_from_sales_list_but_keeps_admin_bundle(self) -> None:
        sales_uid = f"sales-{uuid.uuid4().hex[:10]}"
        series_uid = f"series-{uuid.uuid4().hex[:10]}"
        calc_id = f"calc-{uuid.uuid4().hex[:10]}"
        finalize_quote_persistence(
            quote_series_uid=series_uid,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            uploaded_sheet=None,
            sheet_original_display_name="hide.xlsx",
            sales_user_id=sales_uid,
        )
        self.assertEqual(len(list_my_quotes_for_sales_user(sales_uid)), 1)
        result = batch_hide_quotes_for_sales_user(sales_uid, [series_uid])
        self.assertEqual(result, {"ok": True, "deleted": 1, "not_found": []})
        self.assertEqual(list_my_quotes_for_sales_user(sales_uid), [])
        self.assertIsNone(get_my_quote_session_detail(series_uid, sales_uid))
        self.assertIsNotNone(qus.get_saved_quote_admin_bundle(series_uid))

    def test_batch_hide_denies_other_sales_user(self) -> None:
        sales_a = f"sales-a-{uuid.uuid4().hex[:8]}"
        sales_b = f"sales-b-{uuid.uuid4().hex[:8]}"
        series_uid = f"series-{uuid.uuid4().hex[:10]}"
        calc_id = f"calc-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="deny.xlsx",
            uploaded_sheet=None,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            sales_user_id=sales_a,
        )
        result = batch_hide_quotes_for_sales_user(sales_b, [series_uid])
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["not_found"], [series_uid])
        self.assertEqual(len(list_my_quotes_for_sales_user(sales_a)), 1)


class SalesQuoteSessionHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()
        self.sales_user_id = f"sales-{uuid.uuid4().hex[:12]}"
        self.session_id_a = uuid.uuid4().hex
        self.session_id_b = uuid.uuid4().hex
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
        cookie: str | None = None,
    ) -> tuple[int, dict, list[str]]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        hdr: dict[str, str] = {}
        if cookie:
            hdr["Cookie"] = cookie
        body_raw = None
        if payload is not None:
            hdr["Content-Type"] = "application/json; charset=utf-8"
            body_raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request(method, path, body=body_raw, headers=hdr)
        resp = conn.getresponse()
        set_cookies = [v for (k, v) in resp.getheaders() if k.lower() == "set-cookie"]
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}, set_cookies

    def test_http_my_quotes_list_and_detail_with_cookie(self) -> None:
        series_uid = f"http-series-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        finalize_quote_persistence(
            quote_series_uid=series_uid,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            uploaded_sheet=None,
            sheet_original_display_name="http.xlsx",
            sales_user_id=self.sales_user_id,
        )
        upsert_quote_chat_messages(
            series_uid,
            [{"message_id": "u1", "role": "user", "content": "hello", "metadata": {"type": "text"}}],
            sales_user_id=self.sales_user_id,
        )
        cookie = sales_user_cookie(self.sales_user_id, session_id=self.session_id_a)

        st, body, _ = self._request("GET", "/api/my/quotes", cookie=cookie)
        self.assertEqual(st, 200)
        self.assertEqual(len(body.get("items") or []), 1)
        self.assertEqual(body.get("sales_user_id"), self.sales_user_id)

        st2, detail, _ = self._request(
            "GET",
            f"/api/my/quotes/{series_uid}",
            cookie=cookie,
        )
        self.assertEqual(st2, 200)
        self.assertEqual(detail.get("quote_series_uid"), series_uid)
        self.assertEqual(len(detail.get("messages") or []), 1)
        self.assertEqual(detail.get("latest_quote_result", {}).get("quote_id"), calc_id)

    def test_stable_sales_identity_survives_new_session_cookie(self) -> None:
        series_uid = f"http-stable-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        finalize_quote_persistence(
            quote_series_uid=series_uid,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            uploaded_sheet=None,
            sheet_original_display_name="stable.xlsx",
            sales_user_id=self.sales_user_id,
        )
        cookie_day1 = sales_user_cookie(self.sales_user_id, session_id=self.session_id_a)
        st1, body1, _ = self._request("GET", "/api/my/quotes", cookie=cookie_day1)
        self.assertEqual(st1, 200)
        self.assertEqual(len(body1.get("items") or []), 1)

        cookie_day2 = sales_user_cookie(self.sales_user_id, session_id=self.session_id_b)
        st2, body2, _ = self._request("GET", "/api/my/quotes", cookie=cookie_day2)
        self.assertEqual(st2, 200)
        self.assertEqual(len(body2.get("items") or []), 1)
        self.assertEqual(body2.get("sales_user_id"), self.sales_user_id)

    def test_http_cross_user_approval_is_blocked(self) -> None:
        other_sales = f"sales-other-{uuid.uuid4().hex[:8]}"
        series_uid = f"http-x-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        finalize_quote_persistence(
            quote_series_uid=series_uid,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            uploaded_sheet=None,
            sheet_original_display_name="x.xlsx",
            sales_user_id=self.sales_user_id,
        )
        st, body, _ = self._request(
            "GET",
            f"/api/quotes/{calc_id}/approval",
            cookie=sales_user_cookie(other_sales),
        )
        self.assertIn(st, (403, 404), msg=body)

    def test_http_post_messages_persists(self) -> None:
        series_uid = f"http-msg-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        finalize_quote_persistence(
            quote_series_uid=series_uid,
            quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
            uploaded_sheet=None,
            sheet_original_display_name="msg.xlsx",
            sales_user_id=self.sales_user_id,
        )
        st, body, _ = self._request(
            "POST",
            "/api/quote/messages",
            cookie=sales_user_cookie(self.sales_user_id),
            payload={
                "quote_series_uid": series_uid,
                "messages": [
                    {"message_id": "m1", "role": "user", "content": "追问", "metadata": {"type": "text"}},
                ],
            },
        )
        self.assertEqual(st, 200)
        self.assertEqual(body.get("saved"), 1)

    def test_http_batch_delete_hides_quotes_for_owner_only(self) -> None:
        series_a = f"http-del-a-{uuid.uuid4().hex[:8]}"
        series_b = f"http-del-b-{uuid.uuid4().hex[:8]}"
        calc_a = f"calc-{uuid.uuid4().hex[:8]}"
        calc_b = f"calc-{uuid.uuid4().hex[:8]}"
        other_sales = f"sales-other-{uuid.uuid4().hex[:8]}"
        for series_uid, calc_id, name in (
            (series_a, calc_a, "del-a.xlsx"),
            (series_b, calc_b, "del-b.xlsx"),
        ):
            finalize_quote_persistence(
                quote_series_uid=series_uid,
                quote_result=_sample_quote(calc_id=calc_id, series_uid=series_uid),
                uploaded_sheet=None,
                sheet_original_display_name=name,
                sales_user_id=self.sales_user_id,
            )
        cookie = sales_user_cookie(self.sales_user_id, session_id=self.session_id_a)

        st, body, _ = self._request(
            "POST",
            "/api/my/quotes/batch-delete",
            cookie=cookie,
            payload={"quote_uids": [series_a, series_b, "missing-uid"]},
        )
        self.assertEqual(st, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("deleted"), 2)
        self.assertEqual(body.get("not_found"), ["missing-uid"])

        st_list, list_body, _ = self._request("GET", "/api/my/quotes", cookie=cookie)
        self.assertEqual(st_list, 200)
        self.assertEqual(list_body.get("items") or [], [])

        st_detail, detail_body, _ = self._request(
            "GET",
            f"/api/my/quotes/{series_a}",
            cookie=cookie,
        )
        self.assertEqual(st_detail, 404)
        self.assertEqual(detail_body.get("error"), "not_found")

        st_other, other_body, _ = self._request(
            "POST",
            "/api/my/quotes/batch-delete",
            cookie=sales_user_cookie(other_sales),
            payload={"quote_uids": [series_a]},
        )
        self.assertEqual(st_other, 200)
        self.assertEqual(other_body.get("deleted"), 0)
        self.assertEqual(other_body.get("not_found"), [series_a])
        self.assertIsNotNone(qus.get_saved_quote_admin_bundle(series_a))
