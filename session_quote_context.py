"""进程内会话级报价上下文（TTL 30 分钟）。可选 Redis 时可替换为此模块的实现。"""
from __future__ import annotations

import os
import threading
import time
import uuid
from copy import deepcopy
from typing import Any
from urllib import parse as urllib_parse

SESSION_COOKIE_NAME = "aq_session_id"
SESSION_TTL_SECONDS = 30 * 60

# 业务员长期身份（与短时会话解耦；后续可替换为企业微信 userid）
SALES_USER_COOKIE_NAME = "aq_sales_user_id"
SALES_USER_NAME_COOKIE_NAME = "aq_sales_user_name"
SALES_USER_TTL_SECONDS = 365 * 24 * 60 * 60


def new_session_id() -> str:
    return uuid.uuid4().hex


def new_sales_user_id() -> str:
    return uuid.uuid4().hex


class SessionQuoteStore:
    """Key: session_id → 当前报价快照（单会话只保留最近一次成功报价）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_sid: dict[str, dict[str, Any]] = {}

    def _purge_unlocked(self) -> None:
        now = time.time()
        dead = [
            sid
            for sid, row in self._by_sid.items()
            if now - float(row.get("touched_at", 0)) > SESSION_TTL_SECONDS
        ]
        for sid in dead:
            del self._by_sid[sid]

    def purge_stale(self) -> None:
        with self._lock:
            self._purge_unlocked()

    def touch(self, sid: str) -> None:
        with self._lock:
            if sid in self._by_sid:
                self._by_sid[sid]["touched_at"] = time.time()

    def get(self, sid: str) -> dict[str, Any] | None:
        self.purge_stale()
        with self._lock:
            row = self._by_sid.get(sid)
            if not row:
                return None
            return deepcopy(row)

    def get_current_quote_id(self, sid: str) -> str:
        row = self.get(sid) or {}
        return str(row.get("quote_id") or "").strip()

    def set_current_quote(
        self,
        sid: str,
        quote_id: str,
        file_name: str,
        payload_snapshot: dict[str, Any],
        quote_result: dict[str, Any],
        *,
        quote_series_uid: str | None = None,
    ) -> None:
        now = time.time()
        series = str(quote_series_uid or quote_id or "").strip() or quote_id
        with self._lock:
            self._purge_unlocked()
            self._by_sid[sid] = {
                "touched_at": now,
                "created_at": now,
                "quote_id": quote_id,
                "quote_series_uid": series,
                "file_name": file_name or "",
                "payload_snapshot": deepcopy(payload_snapshot),
                "last_quote_result": deepcopy(quote_result),
                "pricing_gate_confirmed": False,
            }

    def validate_quote_id(self, sid: str, quote_id: str) -> bool:
        self.purge_stale()
        with self._lock:
            row = self._by_sid.get(sid)
            return bool(row and row.get("quote_id") == quote_id)

    def get_payload_for_quote(self, sid: str, quote_id: str) -> dict[str, Any] | None:
        if not self.validate_quote_id(sid, quote_id):
            return None
        with self._lock:
            row = self._by_sid.get(sid)
            if not row:
                return None
            return deepcopy(row.get("payload_snapshot") or {})

    def get_last_quote_result(self, sid: str, quote_id: str) -> dict[str, Any] | None:
        if not self.validate_quote_id(sid, quote_id):
            return None
        with self._lock:
            row = self._by_sid.get(sid)
            if not row:
                return None
            return deepcopy(row.get("last_quote_result") or {})

    def set_pricing_gate_confirmed(self, sid: str, value: bool) -> bool:
        with self._lock:
            row = self._by_sid.get(sid)
            if not row:
                return False
            row["pricing_gate_confirmed"] = bool(value)
            row["touched_at"] = time.time()
            return True

    def replace_last_quote_result(self, sid: str, quote_result: dict[str, Any]) -> bool:
        with self._lock:
            row = self._by_sid.get(sid)
            if not row:
                return False
            row["last_quote_result"] = deepcopy(quote_result)
            row["touched_at"] = time.time()
            return True

    def update_payload_snapshot(self, sid: str, payload_snapshot: dict[str, Any]) -> bool:
        with self._lock:
            row = self._by_sid.get(sid)
            if not row:
                return False
            row["payload_snapshot"] = deepcopy(payload_snapshot)
            row["touched_at"] = time.time()
            return True


GLOBAL_SESSION_STORE = SessionQuoteStore()


def parse_session_id_from_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{SESSION_COOKIE_NAME}="):
            return part.split("=", 1)[1].strip() or None
    return None


def parse_sales_user_id_from_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{SALES_USER_COOKIE_NAME}="):
            return part.split("=", 1)[1].strip() or None
    return None


def parse_sales_user_name_from_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{SALES_USER_NAME_COOKIE_NAME}="):
            val = part.split("=", 1)[1].strip()
            if val:
                return urllib_parse.unquote(val)
    return None


def cookie_secure_enabled() -> bool:
    """HTTPS 生产部署（企业微信）可设 COOKIE_SECURE=1 或 WECOM_COOKIE_SECURE=1。"""
    for key in ("WECOM_COOKIE_SECURE", "COOKIE_SECURE"):
        val = str(os.getenv(key, "") or "").strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
    return False


def cookie_samesite_value() -> str:
    """反代/跨子域部署可设 COOKIE_SAMESITE=none（须配合 HTTPS + Secure）。"""
    raw = str(os.getenv("COOKIE_SAMESITE", "") or "").strip().lower()
    if raw in ("none", "no_restriction", "cross-site"):
        return "None"
    if raw == "strict":
        return "Strict"
    return "Lax"


def cookie_secure_required() -> bool:
    return cookie_secure_enabled() or cookie_samesite_value() == "None"


def _cookie_secure_suffix() -> str:
    return "; Secure" if cookie_secure_required() else ""


def _cookie_samesite_suffix() -> str:
    return f"; SameSite={cookie_samesite_value()}"


def set_sales_user_cookie_header_value(sales_user_id: str) -> str:
    return (
        f"{SALES_USER_COOKIE_NAME}={sales_user_id}; Path=/; Max-Age={SALES_USER_TTL_SECONDS}"
        f"{_cookie_samesite_suffix()}{_cookie_secure_suffix()}"
    )


def set_sales_user_name_cookie_header_value(sales_user_name: str) -> str:
    val = urllib_parse.quote(str(sales_user_name or "").strip(), safe="")
    return (
        f"{SALES_USER_NAME_COOKIE_NAME}={val}; Path=/; Max-Age={SALES_USER_TTL_SECONDS}"
        f"{_cookie_samesite_suffix()}{_cookie_secure_suffix()}"
    )


def clear_sales_user_cookie_header_value() -> str:
    return (
        f"{SALES_USER_COOKIE_NAME}=; Path=/; Max-Age=0"
        f"{_cookie_samesite_suffix()}{_cookie_secure_suffix()}"
    )


def clear_sales_user_name_cookie_header_value() -> str:
    return (
        f"{SALES_USER_NAME_COOKIE_NAME}=; Path=/; Max-Age=0"
        f"{_cookie_samesite_suffix()}{_cookie_secure_suffix()}"
    )


def set_cookie_header_value(session_id: str) -> str:
    return (
        f"{SESSION_COOKIE_NAME}={session_id}; Path=/; Max-Age={SESSION_TTL_SECONDS}"
        f"{_cookie_samesite_suffix()}{_cookie_secure_suffix()}"
    )


def sales_user_id_from_session(session_id: str | None) -> str:
    """Return stable salesman identity string (NOT the short-lived aq_session_id)."""
    return str(session_id or "").strip()


def sales_user_name_placeholder(session_id: str | None) -> str:
    sid = sales_user_id_from_session(session_id)
    if not sid:
        return ""
    return f"业务员-{sid[:8]}"
