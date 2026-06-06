"""企业微信 OAuth 业务员身份（sales_user_id = wecom:{userid}）。"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

WECOM_SALES_ID_PREFIX = "wecom:"

_TOKEN_CACHE: dict[str, Any] = {"token": "", "expires_at": 0.0}
_TOKEN_LOCK = threading.Lock()


def wecom_enabled() -> bool:
    return str(os.getenv("WECOM_ENABLED", "0") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_wecom_browser_user_agent(user_agent: str) -> bool:
    """企业微信内置浏览器 UA 检测（仅 wxwork；普通微信 MicroMessenger 不算）。"""
    ua = str(user_agent or "")
    return bool(re.search(r"wxwork", ua, re.IGNORECASE))


def format_wecom_sales_user_id(userid: str) -> str:
    uid = str(userid or "").strip()
    if not uid:
        return ""
    if uid.startswith(WECOM_SALES_ID_PREFIX):
        return uid
    return f"{WECOM_SALES_ID_PREFIX}{uid}"


def is_wecom_sales_user_id(sales_user_id: str) -> bool:
    return str(sales_user_id or "").strip().startswith(WECOM_SALES_ID_PREFIX)


def wecom_userid_from_sales_id(sales_user_id: str) -> str:
    sid = str(sales_user_id or "").strip()
    if sid.startswith(WECOM_SALES_ID_PREFIX):
        return sid[len(WECOM_SALES_ID_PREFIX) :].strip()
    return ""


def sales_display_name(sales_user_id: str, *, explicit_name: str = "") -> str:
    name = str(explicit_name or "").strip()
    if name:
        return name
    sid = str(sales_user_id or "").strip()
    if is_wecom_sales_user_id(sid):
        uid = wecom_userid_from_sales_id(sid)
        tail = uid[:8] if uid else sid[6:14]
        return f"企微-{tail}"
    if sid:
        return f"业务员-{sid[:8]}"
    return ""


@dataclass(frozen=True)
class WecomConfig:
    corp_id: str
    agent_id: str
    corp_secret: str
    oauth_redirect_uri: str
    public_base_url: str


def get_wecom_config() -> WecomConfig | None:
    if not wecom_enabled():
        return None
    corp_id = str(os.getenv("WECOM_CORP_ID", "") or "").strip()
    agent_id = str(os.getenv("WECOM_AGENT_ID", "") or "").strip()
    corp_secret = str(os.getenv("WECOM_CORP_SECRET", "") or "").strip()
    redirect = str(os.getenv("WECOM_OAUTH_REDIRECT_URI", "") or "").strip()
    public_base = str(os.getenv("WECOM_PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if not public_base:
        public_base = str(os.getenv("QUOTE_FRONT_BASE_URL", "") or "http://127.0.0.1:8776").strip().rstrip("/")
    if not redirect and public_base:
        redirect = f"{public_base}/api/auth/wecom/callback"
    if not (corp_id and agent_id and corp_secret and redirect):
        return None
    return WecomConfig(
        corp_id=corp_id,
        agent_id=agent_id,
        corp_secret=corp_secret,
        oauth_redirect_uri=redirect,
        public_base_url=public_base,
    )


def sanitize_oauth_return_path(path: str) -> str:
    """OAuth state 回跳路径：仅允许站内相对路径，默认 /。"""
    p = str(path or "").strip()
    if not p or not p.startswith("/") or p.startswith("//"):
        return "/"
    if "://" in p:
        return "/"
    return p


def wecom_login_entry_path(*, return_path: str = "/") -> str:
    """业务员前台 OAuth 入口（由服务端再 302 到企业微信授权页）。"""
    ret = sanitize_oauth_return_path(return_path)
    qs = urllib.parse.urlencode({"state": ret})
    return f"/api/auth/wecom/login?{qs}"


def oauth_return_absolute_url(state: str, *, cfg: WecomConfig | None = None) -> str:
    """OAuth callback 成功后跳回的业务员前台地址。"""
    rel = sanitize_oauth_return_path(state)
    if cfg is None:
        cfg = get_wecom_config()
    base = (cfg.public_base_url if cfg else "").strip().rstrip("/")
    if base:
        return f"{base}{rel}"
    return rel


def build_oauth_authorize_url(*, state: str = "") -> str:
    cfg = get_wecom_config()
    if cfg is None:
        raise RuntimeError("企业微信 OAuth 未配置。")
    st = sanitize_oauth_return_path(str(state or "").strip() or "/")
    qs = urllib.parse.urlencode(
        {
            "appid": cfg.corp_id,
            "redirect_uri": cfg.oauth_redirect_uri,
            "response_type": "code",
            "scope": "snsapi_base",
            "state": st,
            "agentid": cfg.agent_id,
        }
    )
    return f"https://open.weixin.qq.com/connect/oauth2/authorize?{qs}#wechat_redirect"


def _http_get_json(url: str, *, timeout_s: float = 12.0) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _fetch_access_token(cfg: WecomConfig) -> str:
    now = time.time()
    with _TOKEN_LOCK:
        cached = str(_TOKEN_CACHE.get("token") or "").strip()
        exp = float(_TOKEN_CACHE.get("expires_at") or 0.0)
        if cached and exp > now + 30:
            return cached
    url = (
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
        + urllib.parse.urlencode({"corpid": cfg.corp_id, "corpsecret": cfg.corp_secret})
    )
    data = _http_get_json(url)
    err = int(data.get("errcode") or 0)
    if err != 0:
        raise RuntimeError(f"wecom_gettoken_failed:{err}:{data.get('errmsg')}")
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("wecom_gettoken_empty")
    ttl = int(data.get("expires_in") or 7200)
    with _TOKEN_LOCK:
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = now + max(60, ttl - 120)
    return token


def exchange_code_for_profile(code: str) -> tuple[str, str]:
    """Return (sales_user_id, display_name). sales_user_id is wecom:{userid}."""
    cfg = get_wecom_config()
    if cfg is None:
        raise RuntimeError("企业微信 OAuth 未配置。")
    auth_code = str(code or "").strip()
    if not auth_code:
        raise ValueError("missing_code")
    token = _fetch_access_token(cfg)
    info_url = (
        "https://qyapi.weixin.qq.com/cgi-bin/user/getuserinfo?"
        + urllib.parse.urlencode({"access_token": token, "code": auth_code})
    )
    info = _http_get_json(info_url)
    err = int(info.get("errcode") or 0)
    if err != 0:
        raise RuntimeError(f"wecom_getuserinfo_failed:{err}:{info.get('errmsg')}")
    userid = str(info.get("UserId") or info.get("userid") or "").strip()
    if not userid:
        raise RuntimeError("wecom_userid_missing")
    display = ""
    try:
        detail_url = (
            "https://qyapi.weixin.qq.com/cgi-bin/user/get?"
            + urllib.parse.urlencode({"access_token": token, "userid": userid})
        )
        detail = _http_get_json(detail_url)
        if int(detail.get("errcode") or 0) == 0:
            display = str(detail.get("name") or "").strip()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError):
        display = ""
    return format_wecom_sales_user_id(userid), display or sales_display_name(format_wecom_sales_user_id(userid))


def auth_status_payload(
    *,
    sales_user_id: str = "",
    sales_user_name: str = "",
    authenticated: bool = False,
) -> dict[str, Any]:
    cfg = get_wecom_config()
    enabled = wecom_enabled()
    login_url = ""
    if enabled and cfg is not None and not authenticated:
        login_url = wecom_login_entry_path(return_path="/")
    misconfigured = enabled and cfg is None
    return {
        "wecom_enabled": enabled,
        "wecom_configured": cfg is not None,
        "wecom_misconfigured": misconfigured,
        "authenticated": authenticated,
        "sales_user_id": sales_user_id if authenticated else "",
        "sales_user_name": sales_user_name if authenticated else "",
        "login_url": login_url,
        "auto_login": bool(enabled and cfg is not None and not authenticated),
        "identity_source": "wecom" if enabled and authenticated else ("local" if authenticated else ""),
        "entry_message": "请从企业微信进入报价系统" if enabled else "",
    }
