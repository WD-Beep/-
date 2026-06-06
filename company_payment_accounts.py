"""报价单收款公司账户资料（静态 JSON，不入库）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_ACCOUNTS_PATH = ROOT / "data" / "company_payment_accounts.json"

_CACHE_MTIME: float | None = None
_CACHE_PAYLOAD: dict[str, Any] | None = None


def normalize_company_name(name: Any) -> str:
    """去除前后空格并去掉所有空白字符，便于精确/模糊匹配。"""
    return re.sub(r"\s+", "", str(name or "").strip())


def _load_payload(force: bool = False) -> dict[str, Any]:
    global _CACHE_MTIME, _CACHE_PAYLOAD
    try:
        mtime = _ACCOUNTS_PATH.stat().st_mtime
    except OSError:
        return {"version": 1, "accounts": []}
    if not force and _CACHE_PAYLOAD is not None and _CACHE_MTIME == mtime:
        return _CACHE_PAYLOAD
    try:
        raw = _ACCOUNTS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        data = {"version": 1, "accounts": []}
    if not isinstance(data, dict):
        data = {"version": 1, "accounts": []}
    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        data["accounts"] = []
    _CACHE_MTIME = mtime
    _CACHE_PAYLOAD = data
    return data


def reload_company_payment_accounts() -> dict[str, Any]:
    return _load_payload(force=True)


def list_company_payment_accounts() -> list[dict[str, str]]:
    payload = _load_payload()
    rows = payload.get("accounts")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        company_name = str(row.get("company_name") or "").strip()
        if not company_name:
            continue
        out.append(
            {
                "company_name": company_name,
                "bank_name": str(row.get("bank_name") or "").strip(),
                "bank_account": str(row.get("bank_account") or "").strip(),
                "alipay": str(row.get("alipay") or "").strip(),
            }
        )
    return out


def _account_public(row: dict[str, str]) -> dict[str, str]:
    return {
        "company_name": row.get("company_name") or "",
        "bank_name": row.get("bank_name") or "",
        "bank_account": row.get("bank_account") or "",
        "alipay": row.get("alipay") or "",
    }


def find_exact_company_account(name: Any) -> dict[str, str] | None:
    key = normalize_company_name(name)
    if not key:
        return None
    for row in list_company_payment_accounts():
        if normalize_company_name(row.get("company_name")) == key:
            return _account_public(row)
    return None


def search_company_accounts(query: Any, *, limit: int = 12) -> dict[str, Any]:
    """精确匹配优先；否则按公司名包含关系返回候选（不自动选定）。"""
    text = str(query or "").strip()
    norm_q = normalize_company_name(text)
    accounts = list_company_payment_accounts()
    if not norm_q:
        return {
            "ok": True,
            "query": text,
            "exact": None,
            "candidates": [_account_public(row) for row in accounts[: max(1, int(limit))]],
        }

    exact = find_exact_company_account(text)
    if exact:
        return {
            "ok": True,
            "query": text,
            "exact": exact,
            "candidates": [exact],
        }

    scored: list[tuple[int, dict[str, str]]] = []
    for row in accounts:
        norm_name = normalize_company_name(row.get("company_name"))
        if not norm_name:
            continue
        if norm_q in norm_name:
            score = 0 if norm_name.startswith(norm_q) else 1
            scored.append((score, _account_public(row)))
        elif norm_name in norm_q:
            scored.append((2, _account_public(row)))

    scored.sort(key=lambda item: (item[0], len(item[1].get("company_name") or "")))
    candidates = [row for _, row in scored[: max(1, int(limit))]]
    return {
        "ok": True,
        "query": text,
        "exact": None,
        "candidates": candidates,
    }


def format_bank_info_text(account: dict[str, str] | None) -> str:
    if not isinstance(account, dict):
        return ""
    bank_name = str(account.get("bank_name") or "").strip()
    bank_account = str(account.get("bank_account") or "").strip()
    if bank_name and bank_account:
        return f"{bank_name} {bank_account}"
    if bank_name:
        return bank_name
    if bank_account:
        return bank_account
    return ""


def format_alipay_info_text(account: dict[str, str] | None) -> str:
    if not isinstance(account, dict):
        return ""
    return str(account.get("alipay") or "").strip()


def get_company_payment_accounts_public() -> dict[str, Any]:
    payload = _load_payload()
    accounts = list_company_payment_accounts()
    try:
        rel = str(_ACCOUNTS_PATH.relative_to(ROOT))
    except ValueError:
        rel = str(_ACCOUNTS_PATH)
    return {
        "ok": True,
        "accounts_path": rel,
        "version": payload.get("version"),
        "source": payload.get("source"),
        "count": len(accounts),
    }
