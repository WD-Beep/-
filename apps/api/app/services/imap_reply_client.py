"""Fetch unread messages from IMAP inbox."""

from __future__ import annotations

import email
import imaplib
import logging
from datetime import UTC, datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime

from app.core.config import settings
from app.schemas.email_reply import InboundEmailPayload
from app.services.email_reply_utils import extract_email_address, parse_references

logger = logging.getLogger(__name__)


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and part.get_content_disposition() != "attachment":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(payload or "")


def _header_map(msg: email.message.Message) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in msg.items():
        headers[key] = _decode_header_value(value)
    return headers


def _received_at(msg: email.message.Message) -> datetime:
    date_header = msg.get("Date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now(UTC)


def fetch_unread_imap_messages(*, mark_seen: bool = False) -> list[InboundEmailPayload]:
    if not settings.is_imap_configured:
        raise RuntimeError("邮箱收件配置未完成")

    try:
        conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    except OSError as exc:
        raise RuntimeError("无法连接邮箱收件服务器，请检查 IMAP 地址和端口") from exc
    try:
        try:
            conn.login(settings.imap_user, settings.imap_password)
        except imaplib.IMAP4.error as exc:
            raise RuntimeError("邮箱登录失败，请检查邮箱账号和客户端授权码") from exc
        folder = settings.imap_folder or "INBOX"
        status, _selected = conn.select(folder)
        if status != "OK":
            raise RuntimeError(f"邮箱文件夹 {folder} 打不开，请检查 IMAP 文件夹配置")
        status, data = conn.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return []

        messages: list[InboundEmailPayload] = []
        for num in data[0].split():
            fetch_status, fetched = conn.fetch(num, "(RFC822)")
            if fetch_status != "OK" or not fetched:
                continue
            raw = fetched[0][1]
            msg = email.message_from_bytes(raw)
            headers = _header_map(msg)
            from_address = extract_email_address(headers.get("From")) or ""
            to_address = extract_email_address(headers.get("To")) or settings.inbound_email_address or settings.imap_user
            body = _extract_body(msg)
            messages.append(
                InboundEmailPayload(
                    message_id=headers.get("Message-ID"),
                    in_reply_to=headers.get("In-Reply-To"),
                    references=parse_references(headers.get("References")),
                    from_address=from_address,
                    to_address=to_address,
                    subject=_decode_header_value(msg.get("Subject")),
                    body=body,
                    raw_headers=headers,
                    received_at=_received_at(msg),
                )
            )
            if mark_seen:
                conn.store(num, "+FLAGS", "\\Seen")
        return messages
    finally:
        try:
            conn.logout()
        except Exception:
            logger.debug("IMAP logout failed", exc_info=True)
