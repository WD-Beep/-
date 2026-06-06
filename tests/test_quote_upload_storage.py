"""quote_upload_storage 与管理员列表/下载路由的基础测试。"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
import threading
import unittest

import quote_upload_storage as qus
from quote_upload_storage import (
    admin_role_ok,
    archive_quote_snapshot,
    approve_saved_quote,
    get_saved_quote_admin_bundle,
    list_quote_files_for_quote,
    list_saved_quotes_summaries,
    get_admin_dashboard_stats,
    persist_uploaded_sheet_for_quote,
    resolve_stored_file_path,
    save_quote_calculation,
)
from test_db_isolation import (
    cleanup_isolated_quote_db,
    mount_isolated_quote_db,
    release_sqlite_db_locks,
    restore_quote_db,
)


class QuoteUploadStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()

    def tearDown(self) -> None:
        release_sqlite_db_locks(qus.DB_PATH)
        restore_quote_db(self._saved_db)
        cleanup_isolated_quote_db(self._root)

    def test_persist_creates_db_row_and_file(self) -> None:
        raw = b"fake-xlsx-bytes"
        b64 = base64.b64encode(raw).decode("ascii")
        rec = persist_uploaded_sheet_for_quote(
            "q-test-001",
            {"name": r"bom/../物料表.xlsx", "content_base64": b64},
        )
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["quote_id"], "q-test-001")
        self.assertEqual(rec["file_size"], len(raw))
        self.assertEqual(rec["file_hash_sha256"], hashlib.sha256(raw).hexdigest())

        path = resolve_stored_file_path(rec["stored_path"])
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.read_bytes(), raw)

        rows = list_quote_files_for_quote("q-test-001")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["original_name"], "物料表.xlsx")

    def test_version_increments_same_quote(self) -> None:
        b64 = base64.b64encode(b"a").decode("ascii")
        persist_uploaded_sheet_for_quote("q-same", {"name": "a.csv", "content_base64": b64})
        persist_uploaded_sheet_for_quote("q-same", {"name": "b.csv", "content_base64": b64})
        rows = list_quote_files_for_quote("q-same")
        self.assertEqual({r["version_no"] for r in rows}, {1, 2})

    def test_archive_quote_snapshot_inserts_row(self) -> None:
        qus.init_quote_storage()
        archive_quote_snapshot(
            "q-arch-test",
            sheet_original_name="样例.xlsx",
            quote_result={
                "product_name": "便当包",
                "material_total": 15.11,
                "tiers": [{"cost_before_margin": 36.11}],
            },
        )
        items, total = list_saved_quotes_summaries(limit=50, offset=0)
        self.assertGreaterEqual(total, 1)
        ids = {str(it.get("quote_id")) for it in items}
        self.assertIn("q-arch-test", ids)

    def test_same_series_two_versions(self) -> None:
        qus.init_quote_storage()

        def qr(cid: str, mt: float, intent: str | None = None) -> dict:
            return {
                "quote_id": cid,
                "intent": intent,
                "product_name": "P",
                "material_total": mt,
                "tiers": [{"cost_before_margin": mt}],
                "detail_rows": [
                    {
                        "name": "布",
                        "spec": "-",
                        "usage": "1",
                        "unit_price": "1",
                        "amount": mt,
                        "amount_text": str(mt),
                        "source": "kb",
                        "calc_note": "",
                        "kb_hit": True,
                    }
                ],
            }

        save_quote_calculation(
            quote_uid="series-z",
            calc_quote_id="calc-z1",
            sheet_original_display_name="t.xlsx",
            uploaded_sheet=None,
            quote_result=qr("calc-z1", 10.0),
        )
        save_quote_calculation(
            quote_uid="series-z",
            calc_quote_id="calc-z2",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=qr("calc-z2", 11.0, intent="FOLLOW_UP"),
        )
        bundle = get_saved_quote_admin_bundle("series-z")
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(bundle["meta"]["latest_version_no"], 2)
        self.assertEqual(len(bundle["versions"]), 2)
        self.assertEqual(bundle["meta"]["selected_calc_quote_id"], "calc-z2")
        b_v1 = get_saved_quote_admin_bundle("series-z", version_no=1)
        self.assertIsNotNone(b_v1)
        assert b_v1 is not None
        self.assertEqual(float(b_v1["quote"]["material_total"]), 10.0)

    def test_duplicate_calc_quote_id_is_idempotent(self) -> None:
        qus.init_quote_storage()
        quote = {
            "quote_id": "calc-same",
            "product_name": "P",
            "material_total": 10.0,
            "tiers": [{"cost_before_margin": 10.0}],
            "detail_rows": [],
        }
        save_quote_calculation(
            quote_uid="series-idem",
            calc_quote_id="calc-same",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=quote,
        )
        save_quote_calculation(
            quote_uid="series-idem",
            calc_quote_id="calc-same",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=quote,
        )
        bundle = get_saved_quote_admin_bundle("series-idem")
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(bundle["meta"]["latest_version_no"], 1)
        self.assertEqual(len(bundle["versions"]), 1)

    def test_approve_quote_version_and_new_version_resets_pending(self) -> None:
        qus.init_quote_storage()

        def quote(cid: str, mt: float) -> dict:
            return {
                "quote_id": cid,
                "product_name": "P",
                "material_total": mt,
                "tiers": [{"cost_before_margin": mt}],
                "detail_rows": [],
            }

        save_quote_calculation(
            quote_uid="series-approval",
            calc_quote_id="calc-a1",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=quote("calc-a1", 10.0),
        )
        before = get_saved_quote_admin_bundle("series-approval")
        self.assertEqual(before["meta"]["approval_status"], "pending")

        result = approve_saved_quote("series-approval", approved_by="admin")
        self.assertTrue(result["ok"])
        self.assertEqual(result["approved_version_no"], 1)
        approved = get_saved_quote_admin_bundle("series-approval")
        self.assertEqual(approved["meta"]["approval_status"], "approved")
        self.assertEqual(approved["meta"]["approved_version_no"], 1)

        save_quote_calculation(
            quote_uid="series-approval",
            calc_quote_id="calc-a2",
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result=quote("calc-a2", 11.0),
        )
        pending = get_saved_quote_admin_bundle("series-approval")
        self.assertEqual(pending["meta"]["latest_version_no"], 2)
        self.assertEqual(pending["meta"]["approval_status"], "pending")
        self.assertIsNone(pending["meta"]["approved_version_no"])

    def test_concurrent_same_calc_id_writes_one_version(self) -> None:
        qus.init_quote_storage()
        quote = {
            "quote_id": "calc-concurrent",
            "product_name": "P",
            "material_total": 12.0,
            "tiers": [{"cost_before_margin": 12.0}],
            "detail_rows": [],
        }

        def worker() -> None:
            save_quote_calculation(
                quote_uid="series-concurrent",
                calc_quote_id="calc-concurrent",
                sheet_original_display_name="",
                uploaded_sheet=None,
                quote_result=quote,
            )

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        bundle = get_saved_quote_admin_bundle("series-concurrent")
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(len(bundle["versions"]), 1)

    def test_engineering_indexes_exist_and_dashboard_cache_hits(self) -> None:
        qus.init_quote_storage()
        conn = sqlite3.connect(qus.DB_PATH)
        try:
            idx = {row[1] for row in conn.execute("PRAGMA index_list(quotes)").fetchall()}
            self.assertIn("idx_quotes_latest_saved_at", idx)
            self.assertIn("idx_quotes_product_name", idx)
        finally:
            conn.close()
        a = get_admin_dashboard_stats()
        b = get_admin_dashboard_stats()
        self.assertFalse((a.get("cache") or {}).get("hit"))
        self.assertTrue((b.get("cache") or {}).get("hit"))

    def test_admin_role_header(self) -> None:
        class _Hdr:
            def __init__(self, role: str | None) -> None:
                self._role = role

            def get(self, key: str, default=None):
                if str(key).lower() == "x-user-role":
                    return self._role
                return default

        self.assertTrue(admin_role_ok(_Hdr("admin")))
        self.assertFalse(admin_role_ok(_Hdr("user")))
        self.assertFalse(admin_role_ok(_Hdr(None)))


if __name__ == "__main__":
    unittest.main()
