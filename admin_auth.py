"""后台登录：用户名密码 + HttpOnly Cookie（HMAC），载荷含角色 admin/user。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from typing import Any, Literal
from urllib.parse import unquote

COOKIE_NAME = "aq_admin_sess"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
_SESSION_TTL_SECONDS = int(os.environ.get("QUOTE_ADMIN_SESSION_TTL", str(86400 * 2)))
_DEFAULT_SECRET_WARNING = "dev-change-me-set-env-QUOTE_ADMIN_SECRET"


def _secret_bytes() -> bytes:
    raw = os.environ.get("QUOTE_ADMIN_SECRET", "").strip()
    if not raw:
        raw = _DEFAULT_SECRET_WARNING
    return raw.encode("utf-8")


def admin_credentials() -> tuple[str, str]:
    user = os.environ.get("QUOTE_ADMIN_USERNAME", "admin").strip()
    pwd = os.environ.get("QUOTE_ADMIN_PASSWORD", "baibo")
    return user, pwd


def user_credentials() -> tuple[str, str]:
    user = os.environ.get("QUOTE_USER_USERNAME", "user").strip()
    pwd = os.environ.get("QUOTE_USER_PASSWORD", "user")
    return user, pwd


def parse_cookie(cookie_header: str | None, name: str) -> str | None:
    if not cookie_header:
        return None
    prefix = name + "="
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(prefix):
            return unquote(part[len(prefix) :].strip())
    return None


def issue_session_token(role: Literal["admin", "user"]) -> str:
    payload = {"exp": int(time.time()) + _SESSION_TTL_SECONDS, "v": 2, "role": role}
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    sig = hmac.new(_secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def decode_session_token(token: str) -> dict[str, Any] | None:
    parts = str(token or "").split(".", 1)
    if len(parts) != 2:
        return None
    payload_b64, sig = parts
    expect = hmac.new(_secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    pad = "=" * (-len(payload_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_b64 + pad)
        data = json.loads(raw.decode("utf-8"))
        exp = int(data.get("exp") or 0)
        if exp <= int(time.time()):
            return None
        role_raw = str(data.get("role") or "").strip().lower()
        ver = int(data.get("v") or 1)
        if ver < 2 or not role_raw:
            role_raw = ROLE_ADMIN
        if role_raw not in (ROLE_ADMIN, ROLE_USER):
            return None
        return {"role": role_raw, "exp": exp, "v": ver}
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def decode_session_from_cookie(cookie_header: str | None) -> dict[str, Any] | None:
    tok = parse_cookie(cookie_header, COOKIE_NAME)
    if not tok:
        return None
    return decode_session_token(tok)


def verify_backend_admin_cookie(cookie_header: str | None) -> bool:
    sess = decode_session_from_cookie(cookie_header)
    return bool(sess and sess.get("role") == ROLE_ADMIN)


def authenticate(username: Any, password: Any) -> Literal["admin", "user"] | None:
    try:
        gu = str(username or "").strip()
        gp = str(password or "")
    except Exception:
        return None
    au, ap = admin_credentials()
    if gu == au:
        return ROLE_ADMIN if hmac.compare_digest(gp.encode("utf-8"), ap.encode("utf-8")) else None
    uu, up = user_credentials()
    if not uu:
        return None
    if gu == uu:
        return ROLE_USER if hmac.compare_digest(gp.encode("utf-8"), up.encode("utf-8")) else None
    return None


def set_login_cookie_headers(token: str) -> list[tuple[str, str]]:
    val = (
        f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
        f"Max-Age={_SESSION_TTL_SECONDS}"
    )
    return [("Set-Cookie", val)]


def set_logout_cookie_header() -> tuple[str, str]:
    return ("Set-Cookie", f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
