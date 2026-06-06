"""报价单客户资料保存、回填优先级与算价版本继承。"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from quote_sheet_meta import (
    auto_quote_no,
    build_prefill_meta,
    carry_forward_quote_sheet_meta,
    extract_saved_meta,
    is_internal_customer_quote_no,
    lookup_customer_profile,
    merge_meta_for_prefill,
    normalize_customer_key,
    quote_no_manual_from_saved,
    sanitize_customer_quote_no,
    save_quote_sheet_meta,
    upsert_customer_profile,
)
from quote_upload_storage import save_quote_calculation
from test_db_isolation import cleanup_isolated_quote_db, mount_isolated_quote_db, restore_quote_db


class QuoteSheetMetaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved_db = mount_isolated_quote_db()

    def tearDown(self) -> None:
        cleanup_isolated_quote_db(self._root)
        restore_quote_db(self._saved_db)

    def _seed_quote(self, series_uid: str, sales_uid: str = "sales_a") -> None:
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=f"calc-{series_uid[:8]}",
            sheet_original_display_name="demo.xlsx",
            uploaded_sheet=None,
            quote_result={
                "quote_id": f"Q-{series_uid[:8]}",
                "product_name": "测试包",
                "customer_name": "kelly case",
                "tiers": [{"quantity": 500, "exw_price": 10.0, "exw_price_text": "10.00元"}],
            },
            sales_user_id=sales_uid,
            sales_user_name="业务员A",
        )

    def test_merge_priority_saved_over_history(self) -> None:
        upsert_customer_profile(
            "sales_a",
            {
                "cust_name": "ACME",
                "cust_contact": "历史联系人",
                "cust_phone": "111",
                "cust_addr": "历史地址",
                "seller_email": "old@acme.com",
            },
        )
        merged = merge_meta_for_prefill(
            inferred={"cust_name": "ACME", "cust_contact": "", "cust_phone": "", "cust_addr": ""},
            saved={
                "cust_name": "ACME",
                "cust_contact": "当前联系人",
                "cust_phone": "",
                "cust_addr": "",
                "seller_email": "",
            },
            history=lookup_customer_profile("sales_a", "ACME"),
        )
        self.assertEqual(merged["cust_contact"], "当前联系人")
        self.assertEqual(merged["cust_phone"], "111")

    def test_save_and_reload_prefill(self) -> None:
        uid = str(uuid.uuid4())
        self._seed_quote(uid)
        meta = {
            "co_phone": "0755-00000000",
            "co_addr": "测试公司地址",
            "quote_no": "BJ-2026-TEST-01",
            "seller_contact": "张三",
            "seller_email": "zhang@corp.com",
            "cust_name": "kelly case",
            "cust_contact": "Kelly",
            "cust_phone": "13800000000",
            "cust_addr": "深圳南山",
            "quote_date_iso": "2026-06-04",
        }
        out = save_quote_sheet_meta(uid, "sales_a", meta, quote_no_manual=True)
        self.assertTrue(out.get("ok"))

        from quote_sheet_meta import _load_latest_quote_object

        quote = _load_latest_quote_object(uid)
        self.assertIsNotNone(quote)
        saved = extract_saved_meta(quote)
        self.assertEqual(saved["cust_contact"], "Kelly")
        self.assertEqual(saved["quote_no"], "BJ-2026-TEST-01")
        self.assertTrue(quote_no_manual_from_saved(quote))

        detail = {
            "quote_series_uid": uid,
            "sales_user_id": "sales_a",
            "sales_user_name": "业务员A",
        }
        prefill_meta = build_prefill_meta(detail, quote, sales_user_id="sales_a")
        self.assertEqual(prefill_meta["cust_phone"], "13800000000")
        self.assertEqual(prefill_meta["seller_email"], "zhang@corp.com")
        self.assertEqual(prefill_meta["quote_no"], "BJ-2026-TEST-01")

    def test_save_and_prefill_sample_fee_and_lead_time(self) -> None:
        uid = str(uuid.uuid4())
        self._seed_quote(uid)
        meta = {
            "cust_name": "kelly case",
            "sample_required": "yes",
            "sample_fee": "300元",
            "sample_lead_time": "5-7天",
        }
        out = save_quote_sheet_meta(uid, "sales_a", meta)
        self.assertTrue(out.get("ok"))

        from quote_sheet_meta import _load_latest_quote_object

        quote = _load_latest_quote_object(uid)
        saved = extract_saved_meta(quote)
        self.assertEqual(saved["sample_required"], "yes")
        self.assertEqual(saved["sample_fee"], "300元")
        self.assertEqual(saved["sample_lead_time"], "5-7天")

        prefill = build_prefill_meta(
            {"quote_series_uid": uid, "sales_user_id": "sales_a"},
            quote,
            sales_user_id="sales_a",
        )
        self.assertEqual(prefill["sample_required"], "yes")
        self.assertEqual(prefill["sample_fee"], "300元")
        self.assertEqual(prefill["sample_lead_time"], "5-7天")

    def test_sample_fields_not_filled_from_customer_history(self) -> None:
        upsert_customer_profile(
            "sales_a",
            {
                "cust_name": "ACME",
                "cust_contact": "历史联系人",
                "cust_phone": "111",
                "cust_addr": "历史地址",
                "seller_email": "old@acme.com",
            },
        )
        merged = merge_meta_for_prefill(
            inferred={"cust_name": "ACME", "sample_fee": "推断打样费", "sample_lead_time": "推断时间"},
            saved={"cust_name": "ACME", "sample_fee": "300元", "sample_lead_time": "5-7天"},
            history=lookup_customer_profile("sales_a", "ACME"),
        )
        self.assertEqual(merged["sample_fee"], "300元")
        self.assertEqual(merged["sample_lead_time"], "5-7天")

    def test_sample_fields_empty_when_unsaved(self) -> None:
        merged = merge_meta_for_prefill(
            inferred={"sample_fee": "", "sample_lead_time": ""},
            saved={"sample_fee": "", "sample_lead_time": ""},
            history={"sample_fee": "历史打样费", "sample_lead_time": "历史时间"},
        )
        self.assertEqual(merged["sample_fee"], "")
        self.assertEqual(merged["sample_lead_time"], "")

    def test_quote_no_manual_not_overwritten_by_auto(self) -> None:
        uid = str(uuid.uuid4())
        self._seed_quote(uid)
        save_quote_sheet_meta(
            uid,
            "sales_a",
            {
                "quote_no": "HAND-001",
                "cust_name": "客户A",
                "quote_date_iso": "2026-06-01",
            },
            quote_no_manual=True,
        )
        from quote_sheet_meta import _load_latest_quote_object

        quote = _load_latest_quote_object(uid)
        detail = {"quote_series_uid": uid}
        meta = build_prefill_meta(detail, quote, sales_user_id="sales_a")
        self.assertEqual(meta["quote_no"], "HAND-001")

    def test_carry_forward_on_recalc(self) -> None:
        uid = str(uuid.uuid4())
        self._seed_quote(uid)
        save_quote_sheet_meta(
            uid,
            "sales_a",
            {"cust_name": "客户B", "cust_contact": "李四", "quote_date_iso": "2026-05-01"},
        )
        new_result = {
            "quote_id": f"calc2-{uid[:8]}",
            "product_name": "测试包",
            "tiers": [{"quantity": 500, "exw_price": 11.0}],
        }
        carry_forward_quote_sheet_meta(uid, new_result)
        self.assertEqual(extract_saved_meta(new_result)["cust_contact"], "李四")

    def test_auto_quote_no_skips_uuid(self) -> None:
        uid = str(uuid.uuid4())
        no = auto_quote_no({"quote_id": uid}, {"quote_series_uid": uid})
        self.assertRegex(no, r"^BJ-\d{8}-\d{3}$")
        self.assertNotEqual(no, uid)
        self.assertNotRegex(no, r"[0-9a-f]{8}$")

    def test_sanitize_customer_quote_no_rejects_hash_suffix(self) -> None:
        uid = str(uuid.uuid4())
        legacy = f"BJ-20260605-{uid.replace('-', '')[:8]}"
        self.assertTrue(is_internal_customer_quote_no(legacy))
        fixed = sanitize_customer_quote_no(
            legacy,
            quote={"quote_series_uid": uid},
            detail={"quote_series_uid": uid},
        )
        self.assertRegex(fixed, r"^BJ-\d{8}-\d{3}$")
        self.assertNotEqual(fixed, legacy)

    def test_manual_quote_no_not_replaced(self) -> None:
        manual = "PO-2026-88-LONG-NUMBER-001"
        fixed = sanitize_customer_quote_no(manual, quote={}, detail={})
        self.assertEqual(fixed, manual)

    def test_normalize_customer_key(self) -> None:
        self.assertEqual(normalize_customer_key("  Kelly Case "), "kellycase")

    def test_prefill_payload_uses_saved_meta(self) -> None:
        from quote_sheet_prefill import build_quote_sheet_prefill_payload

        sales_uid = f"sales-{uuid.uuid4().hex[:8]}"
        series_uid = f"series-{uuid.uuid4().hex[:8]}"
        calc_id = f"calc-{uuid.uuid4().hex[:8]}"
        self._seed_quote(series_uid, sales_uid)
        save_quote_sheet_meta(
            series_uid,
            sales_uid,
            {
                "cust_name": "kelly case",
                "cust_contact": "Kelly Li",
                "cust_phone": "13900001111",
                "cust_addr": "深圳宝安",
                "seller_email": "sales@test.com",
                "quote_no": "PO-2026-88",
                "quote_date_iso": "2026-06-04",
            },
            quote_no_manual=True,
        )
        payload = build_quote_sheet_prefill_payload(series_uid, sales_uid)
        self.assertIsNotNone(payload)
        meta = payload.get("meta") or {}
        self.assertEqual(meta.get("cust_contact"), "Kelly Li")
        self.assertEqual(meta.get("quote_no"), "PO-2026-88")
        self.assertEqual(meta.get("seller_email"), "sales@test.com")

    def test_postgres_backend_delegates_meta_storage(self) -> None:
        import quote_sheet_meta as qsm

        with patch.object(qsm, "configured_quote_db_backend", return_value="postgres"), patch(
            "quote_storage.postgres_impl.lookup_customer_profile",
            return_value={"cust_contact": "PG历史联系人"},
        ) as lookup_mock, patch(
            "quote_storage.postgres_impl.upsert_customer_profile"
        ) as upsert_mock, patch(
            "quote_storage.postgres_impl.load_latest_quote_object",
            return_value={"quote_sheet_meta": {"cust_name": "PG客户"}},
        ) as load_mock, patch(
            "quote_storage.postgres_impl.save_quote_sheet_meta",
            return_value={"ok": True},
        ) as save_mock, patch.object(qsm, "sales_user_can_access_quote", return_value=True):
            self.assertEqual(
                qsm.lookup_customer_profile("sales_pg", "PG客户")["cust_contact"],
                "PG历史联系人",
            )
            qsm.upsert_customer_profile("sales_pg", {"cust_name": "PG客户", "cust_phone": "10086"})
            self.assertEqual(qsm._load_latest_quote_object("series_pg")["quote_sheet_meta"]["cust_name"], "PG客户")
            out = qsm.save_quote_sheet_meta(
                "series_pg",
                "sales_pg",
                {"cust_name": "PG客户", "quote_no": "PG-001"},
                quote_no_manual=True,
            )

        self.assertTrue(out.get("ok"))
        lookup_mock.assert_called_once()
        upsert_mock.assert_called_once()
        load_mock.assert_called_once_with("series_pg")
        save_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
