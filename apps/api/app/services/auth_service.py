# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：auth service
"""Password hashing and short-lived signed login tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time


PBKDF2_ITERATIONS = 210_000
TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            base64.urlsafe_b64decode(salt.encode()),
            int(iterations),
        )
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except (TypeError, ValueError):
        return False


def _token_secret() -> bytes:
    configured = os.getenv("AUTH_TOKEN_SECRET") or os.getenv("AUTH_PROXY_SHARED_SECRET")
    environment = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    if not configured and environment in {"prod", "production"}:
        raise RuntimeError("AUTH_TOKEN_SECRET is required in production")
    return (configured or "local-dev-auth-secret-change-me").encode()


def create_access_token(user_id: int) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_token_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def read_access_token(token: str) -> int | None:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(_token_secret(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if int(payload["exp"]) < int(time.time()):
            return None
        user_id = int(payload["sub"])
        return user_id if user_id > 0 else None
    except (KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
        return None
