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

ACCOUNT_TYPE_CN = "cn"
ACCOUNT_TYPE_FOREIGN = "foreign"

_CNY_CURRENCIES = frozenset({"", "CNY", "RMB"})
_FOREIGN_CURRENCIES = frozenset(
    {"USD", "USDT", "HKD", "EUR", "GBP", "JPY", "AUD", "CAD", "SGD", "CHF", "NZD"}
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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
        out.append(_normalize_account_row(row))
    return out


def classify_account_bucket(row: dict[str, Any]) -> str:
    """按 currency 优先，其次 SWIFT/英文银行信息等兜底，划分中国账户与外币账户。"""
    currency = str(row.get("currency") or "").strip().upper()
    if currency in _FOREIGN_CURRENCIES:
        return ACCOUNT_TYPE_FOREIGN
    if currency in _CNY_CURRENCIES:
        return ACCOUNT_TYPE_CN

    variant = str(row.get("account_variant") or "").strip().lower()
    if variant in {"usd", "foreign", "intl", "international"}:
        return ACCOUNT_TYPE_FOREIGN

    swift = str(row.get("swift_code") or "").strip()
    bank_en = str(row.get("bank_name_en") or "").strip()
    bank_cn = str(row.get("bank_name") or "").strip()
    if swift:
        return ACCOUNT_TYPE_FOREIGN
    if bank_en and not bank_cn:
        return ACCOUNT_TYPE_FOREIGN

    company_name = str(row.get("company_name") or "").strip()
    company_name_en = str(row.get("company_name_en") or "").strip()
    if company_name_en and (not company_name or not _CJK_RE.search(company_name)):
        if bank_en or swift:
            return ACCOUNT_TYPE_FOREIGN
    return ACCOUNT_TYPE_CN


def account_type_label(bucket: str) -> str:
    return "美金账户" if bucket == ACCOUNT_TYPE_FOREIGN else "中国账户"


def _normalize_account_row(row: dict[str, Any]) -> dict[str, str]:
    currency_raw = str(row.get("currency") or "").strip().upper()
    bucket = classify_account_bucket(row)
    if currency_raw:
        currency = currency_raw
    elif bucket == ACCOUNT_TYPE_FOREIGN:
        currency = "USD"
    else:
        currency = "CNY"
    return {
        "account_id": str(row.get("account_id") or "").strip(),
        "display_label_cn": str(row.get("display_label_cn") or "").strip(),
        "company_name": str(row.get("company_name") or "").strip(),
        "company_name_en": str(row.get("company_name_en") or "").strip(),
        "currency": currency,
        "account_type": bucket,
        "account_type_label": account_type_label(bucket),
        "account_variant": str(row.get("account_variant") or "").strip(),
        "bank_name": str(row.get("bank_name") or "").strip(),
        "bank_name_en": str(row.get("bank_name_en") or "").strip(),
        "bank_account": str(row.get("bank_account") or "").strip(),
        "bank_address_en": str(row.get("bank_address_en") or "").strip(),
        "swift_code": str(row.get("swift_code") or "").strip(),
        "bank_note_en": str(row.get("bank_note_en") or "").strip(),
        "alipay": str(row.get("alipay") or "").strip(),
    }


def _account_public(row: dict[str, str]) -> dict[str, str]:
    return dict(row)


def _account_match_keys(row: dict[str, str]) -> set[str]:
    keys: set[str] = set()
    for field in ("company_name", "company_name_en", "display_label_cn", "account_id"):
        norm = normalize_company_name(row.get(field))
        if norm:
            keys.add(norm)
    return keys


def find_exact_company_account(name: Any) -> dict[str, str] | None:
    key = normalize_company_name(name)
    if not key:
        return None
    for row in list_company_payment_accounts():
        if key in _account_match_keys(row):
            return _account_public(row)
    return None


def _filter_accounts_by_type(
    accounts: list[dict[str, str]],
    account_type: str | None,
) -> list[dict[str, str]]:
    bucket = str(account_type or "").strip().lower()
    if bucket not in {ACCOUNT_TYPE_CN, ACCOUNT_TYPE_FOREIGN}:
        return accounts
    return [row for row in accounts if str(row.get("account_type") or "") == bucket]


def search_company_accounts(
    query: Any,
    *,
    limit: int = 12,
    account_type: str | None = None,
) -> dict[str, Any]:
    """精确匹配优先；否则按公司名包含关系返回候选（不自动选定）。"""
    text = str(query or "").strip()
    norm_q = normalize_company_name(text)
    accounts = _filter_accounts_by_type(list_company_payment_accounts(), account_type)
    if not norm_q:
        return {
            "ok": True,
            "query": text,
            "account_type": str(account_type or "").strip().lower() or "",
            "exact": None,
            "candidates": [_account_public(row) for row in accounts[: max(1, int(limit))]],
        }

    exact = find_exact_company_account(text)
    if exact and (
        not account_type
        or str(exact.get("account_type") or "") == str(account_type).strip().lower()
    ):
        return {
            "ok": True,
            "query": text,
            "account_type": str(account_type or "").strip().lower() or "",
            "exact": exact,
            "candidates": [exact],
        }
    if exact and account_type:
        exact = None

    scored: list[tuple[int, dict[str, str]]] = []
    for row in accounts:
        best_score = None
        for norm_name in sorted(_account_match_keys(row), key=len, reverse=True):
            if norm_q in norm_name:
                score = 0 if norm_name.startswith(norm_q) else 1
                best_score = score if best_score is None else min(best_score, score)
            elif norm_name in norm_q:
                best_score = 2 if best_score is None else min(best_score, 2)
        if best_score is not None:
            scored.append((best_score, _account_public(row)))

    scored.sort(key=lambda item: (item[0], len(item[1].get("company_name") or "")))
    candidates = [row for _, row in scored[: max(1, int(limit))]]
    return {
        "ok": True,
        "query": text,
        "account_type": str(account_type or "").strip().lower() or "",
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
