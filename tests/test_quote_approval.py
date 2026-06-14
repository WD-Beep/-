"""报价归档审批状态扩展（pending / approved / rejected + approval_note）。"""
from __future__ import annotations

import unittest
import uuid

import quote_upload_storage as qus
from quote_approval import normalize_approval_status, normalize_reviewer_name
from quote_upload_storage import (
    approval_notice_message_id,
    approve_saved_quote,
    get_saved_quote_admin_bundle,
    get_saved_quote_approval_public,
    list_quote_chat_messages,
    save_quote_calculation,
    update_saved_quote_approval,
)


class QuoteApprovalTest(unittest.TestCase):
    def test_normalize_status_aliases(self) -> None:
        self.assertEqual(normalize_approval_status("pending"), "pending")
        self.assertEqual(normalize_approval_status("合格"), "approved")
        self.assertEqual(normalize_approval_status("rejected"), "rejected")

    def test_reviewer_name_optional(self) -> None:
        self.assertEqual(normalize_reviewer_name(""), "")
        self.assertEqual(normalize_reviewer_name(None), "")
        self.assertEqual(normalize_reviewer_name("  Kelly "), "Kelly")

    def test_approval_allows_empty_reviewer(self) -> None:
        uid = self._seed_quote()
        result = update_saved_quote_approval(
            uid,
            approval_status="approved",
            approval_note="未填审核人",
            reviewed_by="",
        )
        self.assertEqual(result["approval_status"], "approved")
        self.assertEqual(result["approval_note"], "未填审核人")
        self.assertEqual(result["approved_by"], "")
        bundle = get_saved_quote_admin_bundle(uid)
        self.assertEqual(bundle["meta"]["approved_by"], "")

    def _seed_quote(self, uid: str | None = None) -> str:
        qus.init_quote_storage()
        series_uid = uid or f"series-approval-{uuid.uuid4().hex[:10]}"
        calc_id = f"calc-{uuid.uuid4().hex[:12]}"
        save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="",
            uploaded_sheet=None,
            quote_result={
                "quote_id": calc_id,
                "product_name": "P",
                "material_total": 10.0,
                "tiers": [{"cost_before_margin": 10.0}],
                "detail_rows": [],
            },
        )
        return series_uid

    def test_new_quote_defaults_pending(self) -> None:
        uid = self._seed_quote()
        bundle = get_saved_quote_admin_bundle(uid)
        self.assertEqual(bundle["meta"]["approval_status"], "pending")
        self.assertIn("approval_note", bundle["meta"])

    def test_approval_endpoint_fields_in_list_and_detail(self) -> None:
        uid = self._seed_quote()
        update_saved_quote_approval(
            uid,
            approval_status="approved",
            approval_note="已核实，报价表合格",
            reviewed_by="admin-test",
        )
        bundle = get_saved_quote_admin_bundle(uid)
        self.assertEqual(bundle["meta"]["approval_status"], "approved")
        self.assertEqual(bundle["meta"]["approval_note"], "已核实，报价表合格")
        self.assertEqual(bundle["meta"]["approved_by"], "admin-test")
        self.assertTrue(bundle["meta"]["approved_at"])

        items, _ = qus.list_saved_quotes_summaries(limit=50, search_q=uid)
        row = next((x for x in items if x.get("quote_id") == uid), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["approval_status"], "approved")
        self.assertEqual(row["approval_note"], "已核实，报价表合格")

    def test_rejected_clears_approved_version(self) -> None:
        uid = self._seed_quote()
        approve_saved_quote(uid, approved_by="a1")
        result = update_saved_quote_approval(
            uid,
            approval_status="rejected",
            approval_note="用量口径不一致",
            reviewed_by="a2",
        )
        self.assertEqual(result["approval_status"], "rejected")
        bundle = get_saved_quote_admin_bundle(uid)
        self.assertEqual(bundle["meta"]["approval_status"], "rejected")
        self.assertEqual(bundle["meta"]["approval_note"], "用量口径不一致")
        self.assertIsNone(bundle["meta"]["approved_version_no"])

    def test_pending_reset_after_reject(self) -> None:
        uid = self._seed_quote()
        update_saved_quote_approval(
            uid,
            approval_status="rejected",
            approval_note="待改",
            reviewed_by="李四",
        )
        update_saved_quote_approval(
            uid,
            approval_status="pending",
            approval_note="重新核实",
            reviewed_by="王五",
        )
        bundle = get_saved_quote_admin_bundle(uid)
        self.assertEqual(bundle["meta"]["approval_status"], "pending")
        self.assertEqual(bundle["meta"]["approval_note"], "重新核实")

    def _approval_notices(self, uid: str) -> list[dict]:
        return [
            m
            for m in list_quote_chat_messages(uid)
            if (m.get("metadata") or {}).get("type") == "approval_notice"
        ]

    def test_approval_notice_idempotent_on_repeat_save(self) -> None:
        uid = self._seed_quote()
        self.assertEqual(approval_notice_message_id(uid), f"approval-notice:{uid}")
        update_saved_quote_approval(
            uid,
            approval_status="approved",
            approval_note="第一次备注",
            reviewed_by="admin-a",
        )
        update_saved_quote_approval(
            uid,
            approval_status="approved",
            approval_note="第二次备注",
            reviewed_by="admin-b",
        )
        notices = self._approval_notices(uid)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].get("message_id"), approval_notice_message_id(uid))
        meta = notices[0].get("metadata") or {}
        self.assertEqual(meta.get("approval_status"), "approved")
        self.assertEqual(meta.get("approval_note"), "第二次备注")
        self.assertEqual(meta.get("approved_by"), "admin-b")

    def test_approval_notice_updates_content_on_status_change(self) -> None:
        uid = self._seed_quote()
        update_saved_quote_approval(
            uid,
            approval_status="approved",
            approval_note="通过",
            reviewed_by="admin-a",
        )
        update_saved_quote_approval(
            uid,
            approval_status="rejected",
            approval_note="用量需重核",
            reviewed_by="admin-b",
        )
        notices = self._approval_notices(uid)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].get("message_id"), approval_notice_message_id(uid))
        self.assertIn("用量需重核", str(notices[0].get("content") or ""))
        meta = notices[0].get("metadata") or {}
        self.assertEqual(meta.get("approval_status"), "rejected")
        self.assertEqual(meta.get("approval_note"), "用量需重核")

    def test_public_approval_by_series_and_calc_id(self):
        uid = "series-public-approval"
        calc_id = "calc-public-001"
        save_quote_calculation(
            quote_uid=uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="t.xlsx",
            uploaded_sheet=None,
            quote_result={"quote_id": calc_id, "product_name": "P", "tiers": []},
        )
        update_saved_quote_approval(
            uid,
            approval_status="rejected",
            approval_note="口径不一致",
            reviewed_by="赵六",
        )
        by_series = get_saved_quote_approval_public(uid)
        self.assertEqual(by_series["approval_status"], "rejected")
        self.assertEqual(by_series["approval_note"], "口径不一致")
        by_calc = get_saved_quote_approval_public(calc_id)
        self.assertEqual(by_calc["approval_status"], "rejected")
        update_saved_quote_approval(
            uid,
            approval_status="approved",
            approval_note="按最新版通过",
            reviewed_by="孙七",
        )
        bundle = get_saved_quote_admin_bundle(uid)
        approved_calc = bundle["meta"].get("approved_calc_quote_id")
        if approved_calc:
            by_approved_calc = get_saved_quote_approval_public(str(approved_calc))
            self.assertEqual(by_approved_calc["approval_status"], "approved")
        unknown = get_saved_quote_approval_public("no-such-quote")
        self.assertEqual(unknown["approval_status"], "pending")


if __name__ == "__main__":
    unittest.main()
