"""业务员身份：企微 OAuth 后签发 HMAC 签名 HttpOnly Cookie（WECOM_ENABLED=1 时不可伪造）。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import unquote

from admin_auth import parse_cookie
from wecom_auth import is_wecom_sales_user_id, wecom_enabled

COOKIE_NAME = "aq_sales_sess"
_DEFAULT_SECRET_WARNING = "dev-change-me-set-env-QUOTE_SALES_SECRET"
_SALES_SECRET_MISSING_MSG = "WECOM_ENABLED=1 时必须配置 QUOTE_SALES_SECRET（或 QUOTE_ADMIN_SECRET）。"
_SESSION_TTL_SECONDS = int(os.environ.get("QUOTE_SALES_SESSION_TTL", str(86400 * 7)))


def _configured_secret_raw() -> str:
    return (
        os.environ.get("QUOTE_SALES_SECRET", "").strip()
        or os.environ.get("QUOTE_ADMIN_SECRET", "").strip()
    )


def sales_session_secret_configured() -> bool:
    return bool(_configured_secret_raw())


def sales_session_crypto_ready() -> bool:
    """企微模式须配置强密钥；本地 WECOM_ENABLED=0 时允许开发默认密钥。"""
    if wecom_enabled():
        return sales_session_secret_configured()
    return True


def _secret_bytes() -> bytes:
    raw = _configured_secret_raw()
    if raw:
        return raw.encode("utf-8")
    if wecom_enabled():
        raise RuntimeError(_SALES_SECRET_MISSING_MSG)
    return _DEFAULT_SECRET_WARNING.encode("utf-8")


def issue_sales_session_token(sales_user_id: str, sales_user_name: str = "") -> str:
    if wecom_enabled() and not sales_session_secret_configured():
        raise RuntimeError(_SALES_SECRET_MISSING_MSG)
    sid = str(sales_user_id or "").strip()
    if not sid:
        return ""
    payload = {
        "exp": int(time.time()) + _SESSION_TTL_SECONDS,
        "v": 1,
        "sales_user_id": sid,
        "sales_user_name": str(sales_user_name or "").strip(),
    }
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    sig = hmac.new(_secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def decode_sales_session_token(token: str) -> dict[str, Any] | None:
    if wecom_enabled() and not sales_session_secret_configured():
        return None
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
        sid = str(data.get("sales_user_id") or "").strip()
        if not sid:
            return None
        return {
            "sales_user_id": sid,
            "sales_user_name": str(data.get("sales_user_name") or "").strip(),
            "exp": exp,
            "v": int(data.get("v") or 1),
        }
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def decode_sales_session_from_cookie(cookie_header: str | None) -> dict[str, Any] | None:
    tok = parse_cookie(cookie_header, COOKIE_NAME)
    if not tok:
        return None
    return decode_sales_session_token(tok)


def verify_signed_sales_session(cookie_header: str | None) -> tuple[str, str] | None:
    """校验签名 Cookie；返回 (sales_user_id, sales_user_name) 或 None。"""
    data = decode_sales_session_from_cookie(cookie_header)
    if not data:
        return None
    sid = str(data.get("sales_user_id") or "").strip()
    if not is_wecom_sales_user_id(sid):
        return None
    name = str(data.get("sales_user_name") or "").strip()
    return sid, name


def _cookie_secure_suffix() -> str:
    from session_quote_context import cookie_secure_required

    return "; Secure" if cookie_secure_required() else ""


def _cookie_samesite_suffix() -> str:
    from session_quote_context import cookie_samesite_value

    return f"; SameSite={cookie_samesite_value()}"


def set_sales_session_cookie_header(token: str) -> tuple[str, str]:
    val = (
        f"{COOKIE_NAME}={token}; Path=/; HttpOnly{_cookie_samesite_suffix()}; "
        f"Max-Age={_SESSION_TTL_SECONDS}{_cookie_secure_suffix()}"
    )
    return ("Set-Cookie", val)


def clear_sales_session_cookie_header() -> tuple[str, str]:
    return (
        "Set-Cookie",
        f"{COOKIE_NAME}=; Path=/; HttpOnly{_cookie_samesite_suffix()}; "
        f"Max-Age=0{_cookie_secure_suffix()}",
    )
