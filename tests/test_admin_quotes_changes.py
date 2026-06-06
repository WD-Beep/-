"""后台报价归档增量 changes 接口。"""
from __future__ import annotations

import http.client
import json
import sqlite3
import threading
import unittest
from http.server import HTTPServer

import quote_upload_storage as qus
from quote_upload_storage import list_saved_quotes_changes_since, save_quote_calculation
from server import QuoteHandler
from test_db_isolation import cleanup_isolated_quote_db, mount_isolated_quote_db, restore_quote_db


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _sample_quote(calc_id: str) -> dict:
    return {
        "quote_id": calc_id,
        "product_name": "测试包",
        "material_total": 10.0,
        "tiers": [{"cost_before_margin": 20.0}],
        "detail_rows": [],
    }


class QuoteChangesStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved = mount_isolated_quote_db()

    def tearDown(self) -> None:
        restore_quote_db(self._saved)
        cleanup_isolated_quote_db(self._root)

    def _set_saved_at(self, quote_uid: str, saved_at: str) -> None:
        with sqlite3.connect(qus.DB_PATH) as conn:
            conn.execute(
                "UPDATE quotes SET latest_saved_at = ?, updated_at = ? WHERE quote_uid = ?",
                (saved_at, saved_at, quote_uid),
            )
            conn.commit()

    def test_changes_since_filters_by_latest_saved_at(self) -> None:
        save_quote_calculation(
            quote_uid="series-old",
            calc_quote_id="calc-old",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=_sample_quote("calc-old"),
        )
        save_quote_calculation(
            quote_uid="series-new",
            calc_quote_id="calc-new",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=_sample_quote("calc-new"),
        )
        self._set_saved_at("series-old", "2026-05-01T08:00:00Z")
        self._set_saved_at("series-new", "2026-05-01T10:00:00Z")

        items, new_count = list_saved_quotes_changes_since("2026-05-01T09:00:00Z")
        self.assertEqual(new_count, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["quote_id"], "series-new")

    def test_empty_since_returns_nothing(self) -> None:
        save_quote_calculation(
            quote_uid="series-a",
            calc_quote_id="calc-a",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=_sample_quote("calc-a"),
        )
        items, new_count = list_saved_quotes_changes_since("")
        self.assertEqual(new_count, 0)
        self.assertEqual(items, [])


class QuoteChangesRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved = mount_isolated_quote_db()
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.httpd, "admin")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()
        save_quote_calculation(
            quote_uid="series-route",
            calc_quote_id="calc-route",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=_sample_quote("calc-route"),
        )
        with sqlite3.connect(qus.DB_PATH) as conn:
            conn.execute(
                "UPDATE quotes SET latest_saved_at = ?, updated_at = ? WHERE quote_uid = ?",
                ("2026-05-02T12:00:00Z", "2026-05-02T12:00:00Z", "series-route"),
            )
            conn.commit()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.th.join(timeout=2)
        self.httpd.server_close()
        restore_quote_db(self._saved)
        cleanup_isolated_quote_db(self._root)

    def _get_json(self, path: str) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers={"X-User-Role": "admin"})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        body = json.loads(raw.decode("utf-8"))
        return resp.status, body if isinstance(body, dict) else {}

    def test_changes_route_shape(self) -> None:
        code, body = self._get_json("/admin-api/quotes/changes?since=2026-05-02T11:00:00Z")
        self.assertEqual(code, 200)
        self.assertIn("server_time", body)
        self.assertIn("new_count", body)
        self.assertIn("items", body)
        self.assertGreaterEqual(int(body["new_count"]), 1)
        self.assertTrue(any(it.get("quote_id") == "series-route" for it in body["items"]))

    def test_changes_route_requires_admin(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/admin-api/quotes/changes?since=2026-05-01T00:00:00Z")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 403)


if __name__ == "__main__":
    unittest.main()
