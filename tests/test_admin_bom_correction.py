"""管理员 BOM 修正反馈：说明、修正版表格、业务员可见。"""
from __future__ import annotations

import base64
import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

from quote_upload_storage import (
    ADMIN_ATTACHMENT_MAX_BYTES,
    ADMIN_SHEET_KIND_CALCULATED,
    ADMIN_SHEET_KIND_CORRECTED,
    ADMIN_UPDATE_STATUS_PENDING,
    ADMIN_UPDATE_STATUS_VIEWED,
    _decode_admin_upload_sheet,
    build_admin_feedback_public,
    categorize_quote_files,
    count_unread_admin_updates_for_sales_user,
    delete_admin_correction_sheet,
    get_my_quote_session_detail,
    get_saved_quote_admin_bundle,
    list_my_admin_updates_for_sales_user,
    list_my_quotes_for_sales_user,
    list_quote_files_for_quote,
    mark_sales_admin_update_handled,
    mark_sales_admin_update_viewed,
    save_admin_quote_feedback,
    save_quote_calculation,
    update_saved_quote_approval,
)
from admin_correction_inbox import ADMIN_UPDATE_STATUS_HANDLED
from server import QuoteHandler
from test_db_isolation import cleanup_isolated_quote_db, mount_isolated_quote_db, restore_quote_db

ROOT = Path(__file__).resolve().parents[1]


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _admin_headers() -> dict[str, str]:
    return {"X-User-Role": "admin", "Content-Type": "application/json; charset=utf-8"}


def _sales_headers(sales_uid: str = "sales-test-1") -> dict[str, str]:
    return {
        "Cookie": f"aq_sales_user_id={sales_uid}; aq_sales_user_name=tester",
        "Content-Type": "application/json; charset=utf-8",
    }


def _quote_payload(calc_id: str) -> dict:
    return {
        "quote_id": calc_id,
        "product_name": "修正反馈测试包",
        "material_total": 10.0,
        "processing_fee": 5.0,
        "mold_fee": 0.0,
        "system_overhead": 2.0,
        "tiers": [{"quantity": 500, "cost_before_margin": 17.0, "processing_fee": 5.0}],
        "cost_bridge": {"system_overhead_per_pc": 2.0, "processing_fee_per_pc": 5.0},
        "detail_rows": [
            {"name": "主料A", "spec": "规格A", "usage": "1", "unit_price": "10元/㎡", "amount": 10.0}
        ],
        "items": [{"name": "主料A", "spec": "规格A", "usage": "1", "unit_price": "10元/㎡"}],
    }


class AdminBomCorrectionStaticTest(unittest.TestCase):
    def test_admin_html_has_correction_workspace(self) -> None:
        html = (ROOT / "static" / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="bomCorrectionWorkspace"', html)
        self.assertIn("保存管理员修正版", html)
        self.assertIn("管理员修正区", html)
        self.assertIn("bcwCalculatedToolbar", html)
        self.assertIn("上传管理员自算表格/附件", html)
        self.assertNotIn("bcw-compare-zones", html)
        self.assertNotIn("bcwZoneSalesBody", html)
        self.assertIn("参考与可选附件", html)
        self.assertIn("上传修正版表格", html)
        self.assertIn("adminCorrectionProblemTypes", html)

    def test_admin_js_has_correction_handlers(self) -> None:
        js = (ROOT / "static" / "admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("saveAdminFeedbackToSales", js)
        self.assertIn("submitAdminCorrectionFeedback", js)
        self.assertIn("renderAdminSavedCorrectionStatus", js)
        self.assertIn("uploadAdminCorrectionSheet", js)
        self.assertIn("uploadAdminCalculatedSheet", js)
        self.assertIn("deleteAdminCorrectionSheet", js)
        self.assertIn("deleteAdminCalculatedSheet", js)
        self.assertIn("data-bcw-delete-sheet", js)
        self.assertIn("业务员已处理", js)

    def test_front_has_admin_updates_inbox(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="navAdminUpdates"', html)
        self.assertIn('id="adminUpdatesBanner"', html)
        self.assertIn('id="workspaceAdminUpdates"', html)
        self.assertIn("/api/my/admin-updates", js)
        self.assertIn("fetchAdminUpdatesList", js)
        self.assertIn("loadAdminUpdatesPage", js)
        self.assertIn("markAdminUpdateHandled", js)
        self.assertIn('id="adminUpdatesBatchBar"', html)
        self.assertIn('id="adminUpdatesReadFilter"', html)
        self.assertIn("batchDeleteAdminUpdates", js)
        self.assertIn("batchMarkAdminUpdatesRead", js)
        self.assertIn("updateAdminUpdatesStats", js)

    def test_admin_updates_banner_does_not_steal_chat_grid_flex_row(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn(
            ".chat-window:has(#adminUpdatesBanner:not([hidden]))",
            css,
        )
        self.assertIn("grid-template-rows: auto auto 1fr auto", css)
        self.assertIn('activeAdminUpdateUid: ""', js)
        self.assertIn("resetAdminUpdatesWorkspaceUi", js)
        self.assertIn('[admin-updates] skip empty detail render', js)
        self.assertIn("state.currentView === \"chat\"", js)
        self.assertIn("showAdminUpdatesListView();", js)
        self.assertIn("adminUpdatesDetailView", js)
        self.assertIn("els.adminUpdatesDetailView.hidden = true", js)

    def test_front_inbox_detail_requires_admin_corrected_quote_for_visual(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("adminCorrectionHasVisualResult", js)
        self.assertNotIn(
            "fb.admin_corrected_quote_result || detail.latest_quote_result",
            js,
        )
        self.assertIn("修正后可视化报价", js)

    def test_admin_js_calculated_attachment_validation(self) -> None:
        js = (ROOT / "static" / "admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("ADMIN_CALCULATED_ATTACHMENT_SUFFIXES", js)
        self.assertIn("ADMIN_ATTACHMENT_BLOCKED_SUFFIXES", js)
        self.assertIn("isAllowedCalculatedAttachmentFile", js)
        self.assertIn("100 * 1024 * 1024", js)
        self.assertIn("bcwCalculatedToolbar", (ROOT / "static" / "admin" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("adminCorrectionProblemTypes", js)


class AdminBomCorrectionRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved = mount_isolated_quote_db()
        self.series_uid = "corr-series-1"
        self.calc_id = "corr-calc-1"
        self.sales_uid = "sales-corr-1"
        save_quote_calculation(
            quote_uid=self.series_uid,
            calc_quote_id=self.calc_id,
            sheet_original_display_name="sales-original.xlsx",
            uploaded_sheet={
                "name": "sales-original.xlsx",
                "content_base64": base64.b64encode(b"sales sheet bytes").decode("ascii"),
            },
            quote_result=_quote_payload(self.calc_id),
            sales_user_id=self.sales_uid,
            sales_user_name="测试业务员",
        )
        self.admin_httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.admin_httpd, "admin")
        self.admin_port = self.admin_httpd.server_address[1]
        self.admin_th = threading.Thread(target=self.admin_httpd.serve_forever, daemon=True)
        self.admin_th.start()

        self.front_httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.front_httpd, "front")
        self.front_port = self.front_httpd.server_address[1]
        self.front_th = threading.Thread(target=self.front_httpd.serve_forever, daemon=True)
        self.front_th.start()

    def tearDown(self) -> None:
        self.admin_httpd.shutdown()
        self.admin_th.join(timeout=2)
        self.admin_httpd.server_close()
        self.front_httpd.shutdown()
        self.front_th.join(timeout=2)
        self.front_httpd.server_close()
        restore_quote_db(self._saved)
        cleanup_isolated_quote_db(self._root)

    def _post_admin(self, path: str, payload: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.admin_port, timeout=15)
        conn.request(
            "POST",
            path,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=_admin_headers(),
        )
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _delete_admin(self, path: str) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.admin_port, timeout=15)
        conn.request("DELETE", path, headers=_admin_headers())
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _post_front(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.front_port, timeout=15)
        headers = _sales_headers(self.sales_uid)
        body_bytes = b""
        if payload is not None:
            body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request("POST", path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _get_front(self, path: str) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.front_port, timeout=15)
        conn.request("GET", path, headers=_sales_headers(self.sales_uid))
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _get_front_raw(self, path: str) -> tuple[int, bytes, dict[str, str]]:
        conn = http.client.HTTPConnection("127.0.0.1", self.front_port, timeout=15)
        conn.request("GET", path, headers=_sales_headers(self.sales_uid))
        resp = conn.getresponse()
        buf = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, buf, headers

    def test_admin_js_uses_quote_series_uid_for_upload(self) -> None:
        js = (ROOT / "static" / "admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("resolveAdminQuoteSeriesUid", js)
        self.assertIn("meta?.quote_uid", js)
        self.assertIn("correction-sheet", js)

    def test_correction_sheet_not_found_returns_clear_message(self) -> None:
        sheet_b64 = base64.b64encode(b"test").decode("ascii")
        code, body = self._post_admin(
            "/admin-api/quotes/nonexistent-series-uid/correction-sheet",
            {"uploaded_sheet": {"name": "fix.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 404, msg=body)
        self.assertEqual(body.get("error"), "not_found")
        self.assertIn("刷新列表", body.get("message") or "")

    def test_feedback_and_correction_sheet_flow(self) -> None:
        before_files = list_quote_files_for_quote(self.series_uid)
        self.assertEqual(len(before_files), 1)
        self.assertNotIn(
            str(before_files[0].get("file_role") or "sales_sheet"),
            {"admin_correction", "admin_corrected", "admin_calculated"},
        )

        sheet_b64 = base64.b64encode(b"admin corrected csv,data").decode("ascii")
        code, body = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
            {"uploaded_sheet": {"name": "admin-fixed.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(body.get("ok"), msg=body)
        self.assertEqual(body["file"]["original_name"], "admin-fixed.csv")

        code2, body2 = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
            {"uploaded_sheet": {"name": "admin-fixed2.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code2, 409, msg=body2)
        self.assertEqual(body2.get("error"), "replace_confirm_required")

        code3, body3 = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
            {
                "uploaded_sheet": {"name": "admin-fixed2.csv", "content_base64": sheet_b64},
                "replace_confirmed": True,
            },
        )
        self.assertEqual(code3, 200, msg=body3)

        files = list_quote_files_for_quote(self.series_uid)
        cat = categorize_quote_files(files)
        self.assertEqual(len(cat["sales"]), 1)
        self.assertIsNotNone(cat["admin_corrected"])
        self.assertEqual(cat["admin_corrected"]["original_name"], "admin-fixed2.csv")
        self.assertEqual(cat["admin_corrected"]["file_role"], "admin_corrected")

        note = "拉链单价已修正；DCH 外料用量已补充。"
        code4, body4 = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/feedback",
            {"correction_note": note},
        )
        self.assertEqual(code4, 200, msg=body4)
        self.assertTrue(body4.get("ok"), msg=body4)
        fb = body4.get("admin_feedback") or {}
        self.assertTrue(fb.get("has_feedback"))
        self.assertEqual(fb.get("correction_note"), note)
        self.assertIsNotNone(fb.get("correction_sheet"))
        self.assertTrue(fb.get("has_admin_update"))
        self.assertEqual(fb.get("admin_update_status"), ADMIN_UPDATE_STATUS_PENDING)

        bundle = get_saved_quote_admin_bundle(self.series_uid)
        meta = bundle.get("meta") or {}
        self.assertEqual(meta.get("admin_correction_note"), note)
        self.assertTrue(meta.get("admin_feedback_at"))

        detail = get_my_quote_session_detail(self.series_uid, self.sales_uid)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertTrue((detail.get("admin_feedback") or {}).get("has_feedback"))
        self.assertEqual((detail.get("admin_feedback") or {}).get("correction_note"), note)
        self.assertTrue((detail.get("admin_feedback") or {}).get("has_admin_update"))

        items = list_my_quotes_for_sales_user(self.sales_uid)
        row = next((x for x in items if x.get("quote_series_uid") == self.series_uid), None)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row.get("has_admin_update"))

        st_dl, raw, hdrs = self._get_front_raw(
            f"/api/my/quotes/{self.series_uid}/correction-sheet/download",
        )
        self.assertEqual(st_dl, 200, msg=raw[:200])
        self.assertIn(b"admin corrected", raw)
        disp = hdrs.get("content-disposition", "")
        self.assertIn("admin-fixed2.csv", disp)

    def test_delete_correction_sheet_flow(self) -> None:
        sheet_b64 = base64.b64encode(b"admin corrected csv,data").decode("ascii")
        code, body = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
            {"uploaded_sheet": {"name": "admin-fixed.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200, msg=body)

        sales_before = list_quote_files_for_quote(self.series_uid)
        cat_before = categorize_quote_files(sales_before)
        self.assertEqual(len(cat_before["sales"]), 1)

        code_del, body_del = self._delete_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
        )
        self.assertEqual(code_del, 200, msg=body_del)
        self.assertTrue(body_del.get("ok"), msg=body_del)
        self.assertTrue(body_del.get("deleted"))

        files = list_quote_files_for_quote(self.series_uid)
        cat = categorize_quote_files(files)
        self.assertIsNone(cat["admin_corrected"])
        self.assertEqual(len(cat["sales"]), 1)
        self.assertEqual(cat["sales"][0]["original_name"], "sales-original.xlsx")

        bundle = get_saved_quote_admin_bundle(self.series_uid)
        meta = bundle.get("meta") or {}
        self.assertFalse(meta.get("admin_correction_file_id"))
        self.assertFalse(meta.get("admin_correction_at"))
        self.assertFalse(meta.get("admin_correction_by"))

        fb = build_admin_feedback_public(meta, files)
        self.assertIsNone(fb.get("correction_sheet"))

        st_dl, raw, _ = self._get_front_raw(
            f"/api/my/quotes/{self.series_uid}/correction-sheet/download",
        )
        self.assertEqual(st_dl, 404)

        code2, body2 = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
            {"uploaded_sheet": {"name": "admin-reupload.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code2, 200, msg=body2)
        self.assertEqual(body2["file"]["original_name"], "admin-reupload.csv")

    def test_delete_correction_sheet_without_file(self) -> None:
        code, body = self._delete_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
        )
        self.assertEqual(code, 404, msg=body)
        self.assertEqual(body.get("error"), "no_correction_sheet")
        self.assertIn("没有管理员修正版表格", body.get("message") or "")

    def test_delete_correction_sheet_not_found(self) -> None:
        code, body = self._delete_admin(
            "/admin-api/quotes/nonexistent-series-uid/correction-sheet",
        )
        self.assertEqual(code, 404, msg=body)
        self.assertEqual(body.get("error"), "not_found")
        self.assertIn("刷新列表", body.get("message") or "")

    def test_delete_admin_correction_sheet_storage(self) -> None:
        sheet_b64 = base64.b64encode(b"storage delete test").decode("ascii")
        code, body = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
            {"uploaded_sheet": {"name": "to-delete.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200, msg=body)
        result = delete_admin_correction_sheet(self.series_uid, deleted_by="admin")
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("deleted"))
        files = list_quote_files_for_quote(self.series_uid)
        cat = categorize_quote_files(files)
        self.assertIsNone(cat["admin_corrected"])

    def test_build_admin_feedback_public_without_sheet(self) -> None:
        fb = build_admin_feedback_public({"admin_feedback_at": "2026-05-30T00:00:00Z"}, [])
        self.assertTrue(fb["has_feedback"])
        self.assertIsNone(fb["correction_sheet"])

    def test_calculated_sheet_and_view_status_flow(self) -> None:
        sheet_b64 = base64.b64encode(b"admin calculated csv,data").decode("ascii")
        code, body = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
            {"uploaded_sheet": {"name": "admin-calc.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200, msg=body)
        self.assertEqual(body["file"]["file_role"], "admin_calculated")

        files = list_quote_files_for_quote(self.series_uid)
        cat = categorize_quote_files(files)
        self.assertEqual(len(cat["sales"]), 1)
        self.assertIsNotNone(cat["admin_calculated"])
        self.assertIsNone(cat["admin_corrected"])

        bundle = get_saved_quote_admin_bundle(self.series_uid)
        meta = bundle.get("meta") or {}
        self.assertEqual(meta.get("admin_update_status"), ADMIN_UPDATE_STATUS_PENDING)

        detail = get_my_quote_session_detail(self.series_uid, self.sales_uid)
        assert detail is not None
        fb = detail.get("admin_feedback") or {}
        self.assertTrue(fb.get("has_admin_update"))
        self.assertIsNotNone(fb.get("calculated_sheet"))

        st_dl, raw, hdrs = self._get_front_raw(
            f"/api/my/quotes/{self.series_uid}/calculated-sheet/download",
        )
        self.assertEqual(st_dl, 200, msg=raw[:200])
        self.assertIn(b"admin calculated", raw)

        viewed = mark_sales_admin_update_viewed(self.series_uid, self.sales_uid)
        self.assertIsNotNone(viewed)
        assert viewed is not None
        self.assertEqual(
            (viewed.get("admin_feedback") or {}).get("admin_update_status"),
            ADMIN_UPDATE_STATUS_VIEWED,
        )

        items = list_my_quotes_for_sales_user(self.sales_uid)
        row = next((x for x in items if x.get("quote_series_uid") == self.series_uid), None)
        assert row is not None
        self.assertFalse(row.get("has_admin_update"))

        code_corr, _ = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
            {"uploaded_sheet": {"name": "admin-fixed.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code_corr, 200)
        items2 = list_my_quotes_for_sales_user(self.sales_uid)
        row2 = next((x for x in items2 if x.get("quote_series_uid") == self.series_uid), None)
        assert row2 is not None
        self.assertTrue(row2.get("has_admin_update"))

        code_del, body_del = self._delete_admin(
            f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
        )
        self.assertEqual(code_del, 200, msg=body_del)
        files_after = list_quote_files_for_quote(self.series_uid)
        cat_after = categorize_quote_files(files_after)
        self.assertIsNone(cat_after["admin_calculated"])
        self.assertIsNotNone(cat_after["admin_corrected"])
        self.assertEqual(len(cat_after["sales"]), 1)

    def test_admin_update_viewed_http_route(self) -> None:
        sheet_b64 = base64.b64encode(b"pending view test").decode("ascii")
        code, _ = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/correction-sheet",
            {"uploaded_sheet": {"name": "pending.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200)
        code_post, body_post = self._post_front(
            f"/api/my/quotes/{self.series_uid}/admin-update/viewed",
            {},
        )
        self.assertEqual(code_post, 200, msg=body_post)
        self.assertEqual(
            (body_post.get("admin_feedback") or {}).get("admin_update_status"),
            ADMIN_UPDATE_STATUS_VIEWED,
        )

    def test_admin_updates_inbox_list_and_unread(self) -> None:
        sheet_b64 = base64.b64encode(b"inbox test").decode("ascii")
        code, _ = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
            {"uploaded_sheet": {"name": "admin-calc.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200)

        items = list_my_admin_updates_for_sales_user(self.sales_uid)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["quote_series_uid"], self.series_uid)
        self.assertTrue(items[0]["has_admin_update"])
        self.assertEqual(items[0]["admin_update_status"], ADMIN_UPDATE_STATUS_PENDING)
        self.assertTrue(items[0].get("has_calculated_sheet"))

        unread = count_unread_admin_updates_for_sales_user(self.sales_uid)
        self.assertEqual(unread, 1)

        code_get, body_get = self._get_front("/api/my/admin-updates")
        self.assertEqual(code_get, 200, msg=body_get)
        self.assertEqual(body_get.get("unread_count"), 1)
        self.assertEqual(len(body_get.get("items") or []), 1)

    def test_admin_update_handled_http_route(self) -> None:
        sheet_b64 = base64.b64encode(b"handled test").decode("ascii")
        code, _ = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
            {"uploaded_sheet": {"name": "handled.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200)

        mark_sales_admin_update_viewed(self.series_uid, self.sales_uid)

        code_post, body_post = self._post_front(
            f"/api/my/quotes/{self.series_uid}/admin-update/handled",
            {},
        )
        self.assertEqual(code_post, 200, msg=body_post)
        self.assertEqual(
            (body_post.get("admin_feedback") or {}).get("admin_update_status"),
            ADMIN_UPDATE_STATUS_HANDLED,
        )
        self.assertTrue((body_post.get("admin_feedback") or {}).get("admin_update_handled_at"))

        unread = count_unread_admin_updates_for_sales_user(self.sales_uid)
        self.assertEqual(unread, 0)

        handled = mark_sales_admin_update_handled(self.series_uid, self.sales_uid)
        self.assertIsNotNone(handled)
        assert handled is not None
        self.assertEqual(
            (handled.get("admin_feedback") or {}).get("admin_update_status"),
            ADMIN_UPDATE_STATUS_HANDLED,
        )

    def test_admin_updates_forbidden_for_other_sales_user(self) -> None:
        sheet_b64 = base64.b64encode(b"private").decode("ascii")
        code, _ = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
            {"uploaded_sheet": {"name": "private.csv", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200)

        other_uid = "sales-other-999"
        conn = http.client.HTTPConnection("127.0.0.1", self.front_port, timeout=15)
        conn.request(
            "GET",
            f"/api/my/quotes/{self.series_uid}",
            headers=_sales_headers(other_uid),
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)

        detail = get_my_quote_session_detail(self.series_uid, other_uid)
        self.assertIsNone(detail)

        items = list_my_admin_updates_for_sales_user(other_uid)
        self.assertEqual(items, [])

    def test_admin_feedback_includes_bom_diff(self) -> None:
        from admin_bom_recalc import admin_recalc_and_save_bom

        admin_recalc_and_save_bom(
            self.series_uid,
            {
                "product": {"product_name": "修正反馈测试包", "quantities_text": "500个"},
                "items": [
                    {"name": "主料A", "spec": "规格A", "usage": "1.25", "unit_price": "10元/㎡"},
                    {"name": "包装辅料", "spec": "-", "usage": "1", "unit_price": "2.5元/套"},
                ],
            },
            admin_actor="admin",
        )
        detail = get_my_quote_session_detail(self.series_uid, self.sales_uid)
        self.assertIsNotNone(detail)
        assert detail is not None
        fb = detail.get("admin_feedback") or {}
        diff = fb.get("bom_diff") or {}
        self.assertTrue(
            diff.get("has_changes")
            or diff.get("lines")
            or diff.get("added")
            or diff.get("removed")
            or diff.get("changed")
        )

    def test_calculated_attachment_accepts_pdf_and_docx(self) -> None:
        cases = (
            ("admin-calc.pdf", b"%PDF-1.4 test"),
            ("admin-calc.docx", b"PK docx bytes"),
            ("admin-calc.rar", b"Rar! archive"),
        )
        for idx, (name, payload) in enumerate(cases):
            sheet_b64 = base64.b64encode(payload).decode("ascii")
            req_body: dict = {"uploaded_sheet": {"name": name, "content_base64": sheet_b64}}
            if idx > 0:
                req_body["replace_confirmed"] = True
            code, body = self._post_admin(
                f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
                req_body,
            )
            self.assertEqual(code, 200, msg=body)
            self.assertEqual(body["file"]["file_role"], "admin_calculated")
            self.assertEqual(body["file"]["original_name"], name)

    def test_calculated_attachment_rejects_dangerous_suffixes(self) -> None:
        blocked = (
            "evil.exe",
            "run.bat",
            "launch.cmd",
            "script.ps1",
            "payload.js",
            "macro.vbs",
            "setup.msi",
            "trojan.scr",
            "hack.dll",
            "run.com",
            "app.jar",
            "deploy.sh",
        )
        for name in blocked:
            sheet_b64 = base64.b64encode(b"blocked").decode("ascii")
            with self.assertRaises(ValueError, msg=name):
                _decode_admin_upload_sheet(
                    {"name": name, "content_base64": sheet_b64},
                    sheet_kind=ADMIN_SHEET_KIND_CALCULATED,
                )
            code, body = self._post_admin(
                f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
                {"uploaded_sheet": {"name": name, "content_base64": sheet_b64}},
            )
            self.assertEqual(code, 400, msg=body)
            self.assertNotEqual(body.get("ok"), True, msg=name)

    def test_calculated_attachment_does_not_replace_sales_or_visual_correction(self) -> None:
        from admin_bom_recalc import admin_recalc_and_save_bom

        admin_recalc_and_save_bom(
            self.series_uid,
            {
                "product": {"product_name": "修正反馈测试包", "quantities_text": "500个"},
                "items": [
                    {"name": "主料A", "spec": "规格A", "usage": "1.2", "unit_price": "10元/㎡"},
                ],
            },
            admin_actor="admin",
        )
        bundle_before = get_saved_quote_admin_bundle(self.series_uid)
        meta_before = bundle_before.get("meta") or {}
        self.assertEqual(int(meta_before.get("latest_version_no") or 0), 2)

        sheet_b64 = base64.b64encode(b"%PDF-1.4 attachment only").decode("ascii")
        code, body = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
            {"uploaded_sheet": {"name": "admin-only.pdf", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200, msg=body)

        bundle_after = get_saved_quote_admin_bundle(self.series_uid)
        meta_after = bundle_after.get("meta") or {}
        self.assertEqual(int(meta_after.get("latest_version_no") or 0), 2)
        self.assertEqual(meta_after.get("admin_update_status"), ADMIN_UPDATE_STATUS_PENDING)
        self.assertFalse(meta_after.get("admin_update_viewed_at"))
        self.assertFalse(meta_after.get("admin_update_handled_at"))

        files = list_quote_files_for_quote(self.series_uid)
        cat = categorize_quote_files(files)
        self.assertEqual(len(cat["sales"]), 1)
        self.assertIsNotNone(cat["admin_calculated"])
        self.assertIsNone(cat["admin_corrected"])

    def test_attachment_only_admin_update_detail_has_no_visual_quote(self) -> None:
        sheet_b64 = base64.b64encode(b"%PDF-1.4 only attachment").decode("ascii")
        code, _ = self._post_admin(
            f"/admin-api/quotes/{self.series_uid}/calculated-sheet",
            {"uploaded_sheet": {"name": "only-attachment.pdf", "content_base64": sheet_b64}},
        )
        self.assertEqual(code, 200)

        detail = get_my_quote_session_detail(self.series_uid, self.sales_uid)
        assert detail is not None
        fb = detail.get("admin_feedback") or {}
        self.assertIsNone(fb.get("admin_corrected_quote_result"))
        self.assertFalse(fb.get("has_visual_correction"))
        self.assertIsNotNone(fb.get("calculated_sheet"))
        bundle = get_saved_quote_admin_bundle(self.series_uid)
        self.assertEqual(int((bundle.get("meta") or {}).get("latest_version_no") or 0), 1)

    def test_attachment_max_bytes_is_100mb(self) -> None:
        self.assertEqual(ADMIN_ATTACHMENT_MAX_BYTES, 100 * 1024 * 1024)

    def test_feedback_saves_problem_types(self) -> None:
        result = save_admin_quote_feedback(
            self.series_uid,
            correction_note="请核对拉链用量",
            correction_problem_types=["unclear_usage", "agent_recognition_error", "invalid_key"],
            reviewed_by="admin",
        )
        self.assertTrue(result.get("ok"))
        fb = result.get("admin_feedback") or {}
        self.assertEqual(fb.get("correction_note"), "请核对拉链用量")
        types = fb.get("correction_problem_types") or []
        self.assertIn("unclear_usage", types)
        self.assertIn("agent_recognition_error", types)
        self.assertNotIn("invalid_key", types)
        labels = fb.get("correction_problem_types_label") or []
        self.assertIn("用量不清楚", labels)

    def test_feedback_allows_empty_correction_note(self) -> None:
        result = save_admin_quote_feedback(
            self.series_uid,
            correction_note="",
            correction_problem_types=["unclear_usage"],
            reviewed_by="admin",
        )
        self.assertTrue(result.get("ok"))
        fb = result.get("admin_feedback") or {}
        self.assertEqual(fb.get("correction_note"), "")
        self.assertTrue(fb.get("has_feedback"))
        self.assertTrue(fb.get("has_admin_update"))
        self.assertEqual(fb.get("admin_update_status"), ADMIN_UPDATE_STATUS_PENDING)

        bundle = get_saved_quote_admin_bundle(self.series_uid)
        meta = bundle.get("meta") or {}
        self.assertEqual(meta.get("admin_correction_note"), "")
        self.assertTrue(meta.get("admin_feedback_at"))

        detail = get_my_quote_session_detail(self.series_uid, self.sales_uid)
        assert detail is not None
        sales_fb = detail.get("admin_feedback") or {}
        self.assertEqual(sales_fb.get("correction_note"), "")
        self.assertTrue(sales_fb.get("has_admin_update"))

        items = list_my_quotes_for_sales_user(self.sales_uid)
        row = next((x for x in items if x.get("quote_series_uid") == self.series_uid), None)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row.get("has_admin_update"))

    def test_admin_bundle_includes_system_quote_after_visual_correction(self) -> None:
        from admin_bom_recalc import admin_recalc_and_save_bom

        admin_recalc_and_save_bom(
            self.series_uid,
            {
                "product": {"product_name": "修正反馈测试包", "quantities_text": "500个"},
                "items": [
                    {"name": "主料A", "spec": "规格A", "usage": "1.2", "unit_price": "10元/㎡"},
                ],
            },
            admin_actor="admin",
        )
        bundle = get_saved_quote_admin_bundle(self.series_uid)
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertIsInstance(bundle.get("system_quote"), dict)
        self.assertGreater(int((bundle.get("meta") or {}).get("latest_version_no") or 0), 1)


class ApprovalSalesNotificationTest(unittest.TestCase):
    """管理员审批后业务员端提醒：我的报价 + 管理员修正收件箱。"""

    def setUp(self) -> None:
        self._root, self._saved = mount_isolated_quote_db()
        self.series_uid = "approval-notify-series"
        self.calc_id = "approval-notify-calc"
        self.sales_uid = "sales-approval-notify"
        self.other_sales_uid = "sales-approval-other"
        save_quote_calculation(
            quote_uid=self.series_uid,
            calc_quote_id=self.calc_id,
            sheet_original_display_name="approval-notify.xlsx",
            uploaded_sheet=None,
            quote_result=_quote_payload(self.calc_id),
            sales_user_id=self.sales_uid,
            sales_user_name="审批提醒业务员",
        )

    def tearDown(self) -> None:
        restore_quote_db(self._saved)
        cleanup_isolated_quote_db(self._root)

    def test_all_approval_statuses_visible_in_my_quotes(self) -> None:
        for status in ("pending", "approved", "rejected"):
            update_saved_quote_approval(
                self.series_uid,
                approval_status=status,
                approval_note=f"note-{status}",
                reviewed_by="admin",
            )
            items = list_my_quotes_for_sales_user(self.sales_uid)
            row = next((x for x in items if x.get("quote_series_uid") == self.series_uid), None)
            self.assertIsNotNone(row, msg=status)
            assert row is not None
            self.assertEqual(row.get("approval_status"), status)

    def test_rejected_approval_triggers_admin_update_inbox(self) -> None:
        note = "拉链用量口径不一致"
        update_saved_quote_approval(
            self.series_uid,
            approval_status="rejected",
            approval_note=note,
            reviewed_by="admin",
        )
        items = list_my_quotes_for_sales_user(self.sales_uid)
        row = next((x for x in items if x.get("quote_series_uid") == self.series_uid), None)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row.get("has_admin_update"))
        self.assertEqual(row.get("approval_status"), "rejected")
        self.assertEqual(row.get("approval_comment"), note)

        inbox = list_my_admin_updates_for_sales_user(self.sales_uid)
        inbox_row = next((x for x in inbox if x.get("quote_series_uid") == self.series_uid), None)
        self.assertIsNotNone(inbox_row)
        assert inbox_row is not None
        self.assertTrue(inbox_row.get("has_admin_update"))
        self.assertEqual(inbox_row.get("approval_status"), "rejected")
        self.assertEqual(inbox_row.get("rejection_reason"), note)
        self.assertEqual(count_unread_admin_updates_for_sales_user(self.sales_uid), 1)

        detail = get_my_quote_session_detail(self.series_uid, self.sales_uid)
        assert detail is not None
        fb = detail.get("admin_feedback") or {}
        self.assertTrue(fb.get("has_admin_update"))
        self.assertEqual(fb.get("rejection_reason"), note)
        self.assertIn("approval_rejected", fb.get("correction_types") or [])

    def test_approved_approval_triggers_pending_view(self) -> None:
        update_saved_quote_approval(
            self.series_uid,
            approval_status="approved",
            approval_note="价格 OK",
            reviewed_by="admin",
        )
        items = list_my_quotes_for_sales_user(self.sales_uid)
        row = next((x for x in items if x.get("quote_series_uid") == self.series_uid), None)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row.get("has_admin_update"))
        self.assertEqual(row.get("approval_status"), "approved")

        viewed = mark_sales_admin_update_viewed(self.series_uid, self.sales_uid)
        self.assertEqual(
            (viewed.get("admin_feedback") or {}).get("admin_update_status"),
            ADMIN_UPDATE_STATUS_VIEWED,
        )
        items_after = list_my_quotes_for_sales_user(self.sales_uid)
        row_after = next((x for x in items_after if x.get("quote_series_uid") == self.series_uid), None)
        assert row_after is not None
        self.assertFalse(row_after.get("has_admin_update"))
        self.assertEqual(count_unread_admin_updates_for_sales_user(self.sales_uid), 0)

    def test_approval_notification_isolated_between_sales_users(self) -> None:
        update_saved_quote_approval(
            self.series_uid,
            approval_status="rejected",
            approval_note="仅 A 可见",
            reviewed_by="admin",
        )
        self.assertEqual(len(list_my_quotes_for_sales_user(self.other_sales_uid)), 0)
        self.assertEqual(list_my_admin_updates_for_sales_user(self.other_sales_uid), [])
        self.assertIsNone(get_my_quote_session_detail(self.series_uid, self.other_sales_uid))
        self.assertEqual(count_unread_admin_updates_for_sales_user(self.other_sales_uid), 0)
