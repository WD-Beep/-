"""后台报价表审批 HTTP 接口（/admin-api/quotes/{id}/approval）。"""
from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
import uuid
from http.server import HTTPServer

import quote_upload_storage as qus
from quote_upload_storage import save_quote_calculation
from server import QuoteHandler


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _admin_headers() -> dict[str, str]:
    return {"X-User-Role": "admin", "Content-Type": "application/json; charset=utf-8"}


def _approval_payload(**overrides) -> dict:
    payload = {"reviewer_name": "张三"}
    payload.update(overrides)
    return payload


class QuoteApprovalAdminRoutesTest(unittest.TestCase):
    """独立后台站点：报价表 approval_status 更新与列表/详情回读。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._seeded_uid: str | None = None

    def setUp(self) -> None:
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.httpd, "admin")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()
        if QuoteApprovalAdminRoutesTest._seeded_uid is None:
            QuoteApprovalAdminRoutesTest._seeded_uid = self._seed_quote_series()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.th.join(timeout=2)
        self.httpd.server_close()

    def _seed_quote_series(self) -> str:
        qus.init_quote_storage()
        series_uid = f"http-approval-{uuid.uuid4().hex[:12]}"
        calc_id = f"calc-{uuid.uuid4().hex[:12]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="route-test.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "product_name": "HTTP审批测试包",
                "material_total": 88.0,
                "tiers": [{"cost_before_margin": 88.0, "quantity": 500}],
                "detail_rows": [{"name": "主料", "amount": 10.0}],
            },
        )
        return series_uid

    @property
    def quote_uid(self) -> str:
        uid = QuoteApprovalAdminRoutesTest._seeded_uid
        assert uid
        return uid

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

    def _get_json(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        conn.request("GET", path, headers=dict(headers or {}))
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def test_approval_requires_admin(self) -> None:
        path = f"/admin-api/quotes/{self.quote_uid}/approval"
        code, body = self._post_json(
            path,
            {
                "approval_status": "approved",
                "approval_note": "已核实，报价表合格",
            },
        )
        self.assertEqual(code, 403, msg=body)
        self.assertEqual(body.get("error"), "forbidden")

    def test_legacy_approve_requires_admin(self) -> None:
        path = f"/admin-api/quotes/{self.quote_uid}/approve"
        code, body = self._post_json(path, {"approval_note": "仅测试权限"})
        self.assertEqual(code, 403, msg=body)
        self.assertEqual(body.get("error"), "forbidden")

    def test_admin_sets_approved_success(self) -> None:
        uid = f"http-approval-ok-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=uid,
            calc_quote_id=f"calc-{uuid.uuid4().hex[:12]}",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result={
                "quote_id": uid,
                "product_name": "审批成功样例",
                "material_total": 12.0,
                "tiers": [{"cost_before_margin": 12.0}],
                "detail_rows": [],
            },
        )
        path = f"/admin-api/quotes/{uid}/approval"
        payload = _approval_payload(
            approval_status="approved",
            approval_note="已核实，报价表合格",
            reviewer_name="Kelly",
        )
        code, body = self._post_json(path, payload, headers=_admin_headers())
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("approval_status"), "approved")
        self.assertEqual(body.get("approval_note"), "已核实，报价表合格")
        self.assertEqual(body.get("quote_uid"), uid)
        self.assertIsNotNone(body.get("approved_version_no"))
        self.assertTrue(body.get("approved_at"))
        self.assertEqual(body.get("approved_by"), "Kelly")

    def test_list_and_detail_return_approval_fields(self) -> None:
        uid = f"http-approval-read-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=uid,
            calc_quote_id=f"calc-{uuid.uuid4().hex[:12]}",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result={
                "quote_id": uid,
                "product_name": "列表详情回读",
                "material_total": 20.0,
                "tiers": [{"cost_before_margin": 20.0}],
                "detail_rows": [],
            },
        )
        note = "列表与详情应带回备注"
        code, _ = self._post_json(
            f"/admin-api/quotes/{uid}/approval",
            _approval_payload(approval_status="approved", approval_note=note),
            headers=_admin_headers(),
        )
        self.assertEqual(code, 200)

        list_code, list_body = self._get_json(
            f"/admin-api/quotes?page=1&page_size=50&q={uid}",
            headers={"X-User-Role": "admin"},
        )
        self.assertEqual(list_code, 200)
        items = list_body.get("items") or []
        row = next((x for x in items if x.get("quote_id") == uid), None)
        self.assertIsNotNone(row, msg=list_body)
        self.assertEqual(row.get("approval_status"), "approved")
        self.assertEqual(row.get("approval_note"), note)

        detail_code, detail = self._get_json(
            f"/admin-api/quotes/{uid}",
            headers={"X-User-Role": "admin"},
        )
        self.assertEqual(detail_code, 200)
        meta = detail.get("meta") or {}
        self.assertEqual(meta.get("approval_status"), "approved")
        self.assertEqual(meta.get("approval_note"), note)
        self.assertEqual(meta.get("approved_by"), "张三")

    def test_admin_sets_rejected_and_list_reflects(self) -> None:
        uid = f"http-approval-rej-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=uid,
            calc_quote_id=f"calc-{uuid.uuid4().hex[:12]}",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result={
                "quote_id": uid,
                "product_name": "驳回样例",
                "material_total": 9.0,
                "tiers": [{"cost_before_margin": 9.0}],
                "detail_rows": [],
            },
        )
        code, body = self._post_json(
            f"/admin-api/quotes/{uid}/approval",
            _approval_payload(
                approval_status="rejected",
                approval_note="用量口径不一致",
                reviewer_name="李四",
            ),
            headers=_admin_headers(),
        )
        self.assertEqual(code, 200)
        self.assertEqual(body.get("approval_status"), "rejected")
        self.assertIsNone(body.get("approved_version_no"))

        _, detail = self._get_json(f"/admin-api/quotes/{uid}", headers={"X-User-Role": "admin"})
        self.assertEqual((detail.get("meta") or {}).get("approval_status"), "rejected")
        self.assertEqual((detail.get("meta") or {}).get("approval_note"), "用量口径不一致")
        self.assertEqual((detail.get("meta") or {}).get("approved_by"), "李四")

    def test_approval_empty_reviewer_succeeds(self) -> None:
        uid = f"http-approval-no-reviewer-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=uid,
            calc_quote_id=f"calc-{uuid.uuid4().hex[:12]}",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result={
                "quote_id": uid,
                "product_name": "缺审核人",
                "material_total": 1.0,
                "tiers": [{"cost_before_margin": 1.0}],
                "detail_rows": [],
            },
        )
        code, body = self._post_json(
            f"/admin-api/quotes/{uid}/approval",
            {"approval_status": "approved", "approval_note": "无审核人"},
            headers=_admin_headers(),
        )
        self.assertEqual(code, 200)
        self.assertEqual(body.get("approval_status"), "approved")
        self.assertEqual(body.get("approval_note"), "无审核人")
        self.assertEqual(body.get("approved_by"), "")

        _, detail = self._get_json(f"/admin-api/quotes/{uid}", headers={"X-User-Role": "admin"})
        self.assertEqual((detail.get("meta") or {}).get("approval_status"), "approved")
        self.assertEqual((detail.get("meta") or {}).get("approval_note"), "无审核人")
        self.assertEqual((detail.get("meta") or {}).get("approved_by"), "")

    def test_approval_missing_status_returns_400(self) -> None:
        uid = f"http-approval-bad-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=uid,
            calc_quote_id=f"calc-{uuid.uuid4().hex[:12]}",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result={
                "quote_id": uid,
                "product_name": "缺状态",
                "material_total": 1.0,
                "tiers": [{"cost_before_margin": 1.0}],
                "detail_rows": [],
            },
        )
        code, body = self._post_json(
            f"/admin-api/quotes/{uid}/approval",
            {"approval_note": "无 status"},
            headers=_admin_headers(),
        )
        self.assertEqual(code, 400)
        self.assertEqual(body.get("error"), "invalid_request")

    def test_admin_approval_with_login_cookie_success(self) -> None:
        uid = f"http-approval-cookie-{uuid.uuid4().hex[:10]}"
        save_quote_calculation(
            quote_uid=uid,
            calc_quote_id=f"calc-{uuid.uuid4().hex[:12]}",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result={
                "quote_id": uid,
                "product_name": "Cookie审批",
                "material_total": 3.0,
                "tiers": [{"cost_before_margin": 3.0}],
                "detail_rows": [],
            },
        )
        prev = {k: os.environ.get(k) for k in ("QUOTE_ADMIN_USERNAME", "QUOTE_ADMIN_PASSWORD", "QUOTE_ADMIN_SECRET")}
        try:
            os.environ["QUOTE_ADMIN_USERNAME"] = "tadm"
            os.environ["QUOTE_ADMIN_PASSWORD"] = "tpw-secret"
            os.environ["QUOTE_ADMIN_SECRET"] = "unit-test-admin-secret-fixed-value"
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
            conn.request(
                "POST",
                "/admin-api/login",
                body=json.dumps({"username": "tadm", "password": "tpw-secret"}).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            login_resp = conn.getresponse()
            login_raw = login_resp.read()
            conn.close()
            self.assertEqual(login_resp.status, 200, msg=login_raw.decode("utf-8", errors="replace"))
            cookie_pair = login_resp.getheader("Set-Cookie", "").split(";", 1)[0].strip()
            self.assertTrue(cookie_pair.startswith("aq_admin_sess="))

            code, body = self._post_json(
                f"/admin-api/quotes/{uid}/approval",
                _approval_payload(approval_status="approved", approval_note="Cookie通过"),
                headers={"Cookie": cookie_pair},
            )
            self.assertEqual(code, 200, msg=body)
            self.assertEqual(body.get("approval_status"), "approved")
            self.assertEqual(body.get("approval_note"), "Cookie通过")
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
