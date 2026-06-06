"""quote_chat_messages 后端分流：PostgreSQL 模式不写本地 SQLite。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import quote_upload_storage as qus
from quote_upload_storage import (
    approval_notice_message_id,
    list_quote_chat_messages,
    record_approval_chat_notification,
    save_quote_chat_message,
    upsert_quote_chat_messages,
)


class QuoteChatMessagesBackendRoutingTest(unittest.TestCase):
    def test_save_list_upsert_delegate_to_postgres_impl(self) -> None:
        with patch.object(qus, "configured_quote_db_backend", return_value="postgres"), patch(
            "quote_storage.postgres_impl.save_quote_chat_message",
            return_value="mid-1",
        ) as save_mock, patch(
            "quote_storage.postgres_impl.list_quote_chat_messages",
            return_value=[{"message_id": "mid-1"}],
        ) as list_mock, patch(
            "quote_storage.postgres_impl.upsert_quote_chat_messages",
            return_value=2,
        ) as upsert_mock:
            self.assertEqual(
                save_quote_chat_message("series-pg", "admin", "通知", message_id="mid-1"),
                "mid-1",
            )
            self.assertEqual(list_quote_chat_messages("series-pg"), [{"message_id": "mid-1"}])
            self.assertEqual(
                upsert_quote_chat_messages("series-pg", [{"message_id": "u1", "role": "user", "content": "hi"}]),
                2,
            )

        save_mock.assert_called_once_with(
            "series-pg",
            "admin",
            "通知",
            message_id="mid-1",
            metadata=None,
            created_at=None,
        )
        list_mock.assert_called_once_with("series-pg", limit=500)
        upsert_mock.assert_called_once()

    def test_record_approval_notification_uses_postgres_save(self) -> None:
        uid = "series-approval-pg"
        mid = approval_notice_message_id(uid)
        with patch.object(qus, "configured_quote_db_backend", return_value="postgres"), patch(
            "quote_storage.postgres_impl.save_quote_chat_message",
        ) as save_mock:
            record_approval_chat_notification(
                uid,
                {
                    "approval_status": "approved",
                    "approval_note": "第一次",
                    "approved_by": "admin-a",
                    "approved_at": "2026-06-05T10:00:00Z",
                },
            )
            record_approval_chat_notification(
                uid,
                {
                    "approval_status": "approved",
                    "approval_note": "第二次",
                    "approved_by": "admin-b",
                    "approved_at": "2026-06-05T11:00:00Z",
                },
            )

        self.assertEqual(save_mock.call_count, 2)
        for call in save_mock.call_args_list:
            self.assertEqual(call.args[0], uid)
            self.assertEqual(call.kwargs.get("message_id"), mid)
            meta = call.kwargs.get("metadata") or {}
            self.assertEqual(meta.get("type"), "approval_notice")

        last_meta = save_mock.call_args_list[-1].kwargs.get("metadata") or {}
        self.assertEqual(last_meta.get("approval_note"), "第二次")
        self.assertEqual(last_meta.get("approved_by"), "admin-b")

    def test_postgres_backend_does_not_open_sqlite_for_chat_messages(self) -> None:
        with patch.object(qus, "configured_quote_db_backend", return_value="postgres"), patch(
            "quote_storage.postgres_impl.save_quote_chat_message",
            return_value="mid-x",
        ), patch.object(qus, "_connect") as sqlite_connect_mock:
            save_quote_chat_message("series-x", "user", "hello", message_id="mid-x")
        sqlite_connect_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
