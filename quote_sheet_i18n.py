"""报价单中英文术语库与字段翻译（术语表 + 英文导出安全兜底，禁止 [UNTRANSLATED] 进 PDF）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_TERMS_PATH = ROOT / "data" / "i18n" / "quote_sheet_zh_en.json"

_CACHE_MTIME: float | None = None
_CACHE_PAYLOAD: dict[str, Any] | None = None

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PURE_NUMBER_RE = re.compile(r"^[\s\d.,]+$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNTRANSLATED_RE = re.compile(r"\s*\[UNTRANSLATED\]\s*", re.I)
_PACK_QTY_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(个|套|条|张|件|只|卷|米|码|㎡|m²)$",
    re.I,
)
_PACK_UNIT_EN = {
    "个": "pc",
    "套": "set",
    "条": "pc",
    "张": "sheet",
    "件": "pc",
    "只": "pc",
    "卷": "roll",
    "米": "m",
    "码": "yd",
    "㎡": "sqm",
    "m²": "sqm",
}

_EN_FALLBACK = "To be confirmed"
_EN_NA = "N/A"

_META_FIELD_FIXED_KEY: dict[str, str] = {
    "co_name": "default_company_name",
    "co_addr": "default_company_address",
}

_KNOWN_CO_NAME_ZH = "深圳市栢博旅游用品有限公司"

_BANK_TOKEN_EN: tuple[tuple[str, str], ...] = (
    ("中国银行股份有限公司", "Bank of China"),
    ("中国银行", "Bank of China"),
    ("招商银行股份有限公司", "China Merchants Bank"),
    ("招商银行", "China Merchants Bank"),
    ("中国工商银行股份有限公司", "Industrial and Commercial Bank of China"),
    ("中国工商银行", "Industrial and Commercial Bank of China"),
    ("中国农业银行股份有限公司", "Agricultural Bank of China"),
    ("中国农业银行", "Agricultural Bank of China"),
    ("未开户", "Account not opened"),
    ("支行", " Sub-branch"),
    ("分行", " Branch"),
)


def _load_terms(force: bool = False) -> dict[str, Any]:
    global _CACHE_MTIME, _CACHE_PAYLOAD
    try:
        mtime = _TERMS_PATH.stat().st_mtime
    except OSError:
        return {"fixed": {}, "labels": {}, "phrases": []}
    if not force and _CACHE_PAYLOAD is not None and _CACHE_MTIME == mtime:
        return _CACHE_PAYLOAD
    try:
        raw = _TERMS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        data = {"fixed": {}, "labels": {}, "phrases": []}
    if not isinstance(data, dict):
        data = {"fixed": {}, "labels": {}, "phrases": []}
    _CACHE_MTIME = mtime
    _CACHE_PAYLOAD = data
    return data


def reload_quote_sheet_terms() -> dict[str, Any]:
    return _load_terms(force=True)


def get_quote_sheet_terms_public() -> dict[str, Any]:
    t = _load_terms()
    phrases = t.get("phrases")
    phrase_count = len(phrases) if isinstance(phrases, list) else 0
    lbl = t.get("labels")
    if not isinstance(lbl, dict):
        lbl = {}
    fixed = t.get("fixed")
    if not isinstance(fixed, dict):
        fixed = {}
    try:
        rel = str(_TERMS_PATH.relative_to(ROOT))
    except ValueError:
        rel = str(_TERMS_PATH)
    return {"ok": True, "terms_path": rel, "labels": lbl, "fixed": fixed, "phrase_count": phrase_count}


def _phrase_pairs(terms: dict[str, Any]) -> list[tuple[str, str]]:
    phrases = terms.get("phrases")
    if not isinstance(phrases, list):
        return []
    out: list[tuple[str, str]] = []
    for pair in phrases:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            zh = str(pair[0] or "").strip()
            en = str(pair[1] or "")
            if not zh or not en.strip():
                continue
            if zh and en:
                out.append((zh, en))
        elif isinstance(pair, dict):
            zh = str(pair.get("zh") or pair.get("from") or "").strip()
            en = str(pair.get("en") or pair.get("to") or "")
            if zh and en.strip():
                out.append((zh, en))
    out.sort(key=lambda x: len(x[0]), reverse=True)
    return out


def _terms_fixed(terms: dict[str, Any]) -> dict[str, str]:
    fixed = terms.get("fixed")
    if not isinstance(fixed, dict):
        return {}
    return {str(k): str(v) for k, v in fixed.items() if str(v or "").strip()}


def _as_trimmed_str(v: Any) -> str:
    return "" if v is None else str(v)


def contains_cjk(text: Any) -> bool:
    return bool(_CJK_RE.search(_as_trimmed_str(text)))


def should_skip_translate(s: str) -> bool:
    t = s.strip()
    if not t:
        return True
    if _PURE_NUMBER_RE.fullmatch(t):
        return True
    if _ISO_DATE_RE.fullmatch(t):
        return True
    if re.fullmatch(r"[\w.\-+_@]+@[\w.\-]+\.[A-Za-z]{2,}", t):
        return True
    if not _CJK_RE.search(t) and re.fullmatch(r"[\d\s\-+/().#A-Za-z]+", t):
        return True
    return False


def apply_glossary_phrases(text: str, pairs: list[tuple[str, str]]) -> str:
    out = text
    for zh, en in pairs:
        out = out.replace(zh, en)
    return out


def _translate_bank_name(text: str, pairs: list[tuple[str, str]]) -> str:
    s = _UNTRANSLATED_RE.sub("", _as_trimmed_str(text)).strip()
    if not s:
        return ""
    out = apply_glossary_phrases(s, pairs)
    if not contains_cjk(out):
        return out.strip()
    for zh, en in _BANK_TOKEN_EN:
        out = out.replace(zh, en)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,")
    if contains_cjk(out):
        return _EN_FALLBACK
    return out


def _strip_cjk_runs(text: str) -> str:
    cleaned = _CJK_RE.sub("", text)
    cleaned = re.sub(r"[-_/.,\s]+", " ", cleaned).strip()
    return cleaned


def ensure_english_quote_text(
    original: Any,
    *,
    field_name: str = "",
    pairs: list[tuple[str, str]] | None = None,
    fixed: dict[str, str] | None = None,
    fallback: str = _EN_FALLBACK,
) -> tuple[str, bool]:
    """英文导出文本：禁止输出中文与 [UNTRANSLATED]；无法翻译时用 fallback。"""
    phrase_list = pairs or []
    fixed_map = fixed or {}
    s = _UNTRANSLATED_RE.sub("", _as_trimmed_str(original)).strip()
    if not s or s in ("-", "—"):
        return "", False

    fixed_key = _META_FIELD_FIXED_KEY.get(field_name)
    if fixed_key and fixed_map.get(fixed_key) and field_name == "co_name" and s == _KNOWN_CO_NAME_ZH:
        return fixed_map[fixed_key], False

    if should_skip_translate(s) and not contains_cjk(s):
        return s, False

    out = apply_glossary_phrases(s, phrase_list)
    out = _UNTRANSLATED_RE.sub("", out).strip()
    if field_name == "bank_name":
        bank_out = _translate_bank_name(out, phrase_list)
        if bank_out:
            return bank_out, bank_out == fallback
        return fallback, True
    if not contains_cjk(out):
        return out, False

    if field_name in ("company_name", "authorized_payee"):
        en_company = str(
            fixed_map.get("default_company_name")
            or fixed_map.get("default_authorized_payee")
            or ""
        ).strip()
        if s == _KNOWN_CO_NAME_ZH and en_company:
            return en_company, False

    if field_name in ("quote_no", "co_phone", "cust_phone"):
        ascii_only = _strip_cjk_runs(out)
        if ascii_only:
            return ascii_only, True

    return fallback, True


def sanitize_english_export_text(text: Any, *, fallback: str = _EN_FALLBACK) -> str:
    s = _UNTRANSLATED_RE.sub("", _as_trimmed_str(text)).strip()
    if not s or s in ("-", "—"):
        return ""
    if contains_cjk(s):
        return fallback
    return s


def translate_free_text(
    original: Any,
    pairs: list[tuple[str, str]],
    *,
    field_name: str = "",
    fixed: dict[str, str] | None = None,
) -> str:
    text, _ = ensure_english_quote_text(
        original,
        field_name=field_name,
        pairs=pairs,
        fixed=fixed,
    )
    return text


def _sanitize_pack_for_translate(value: object) -> str:
    try:
        from quote_sheet_prefill import sanitize_customer_pack_display

        return sanitize_customer_pack_display(value)
    except Exception:
        return _as_trimmed_str(value).strip()


def translate_pack_for_quote_sheet(
    text: object,
    pairs: list[tuple[str, str]],
    *,
    fixed: dict[str, str] | None = None,
) -> str:
    """包装列英文：数量+单位模板，禁止中文进客户 PDF。"""
    del fixed
    s = _UNTRANSLATED_RE.sub("", _sanitize_pack_for_translate(text)).strip()
    if not s:
        return ""
    m = _PACK_QTY_RE.match(s)
    if m:
        unit = _PACK_UNIT_EN.get(m.group(2), "pc")
        return f"{m.group(1)} {unit}"
    out = apply_glossary_phrases(s, pairs)
    out = _UNTRANSLATED_RE.sub("", out).strip()
    if contains_cjk(out):
        return _EN_NA
    return out


def _row_fob_usd_fields(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in (
        "fob_price",
        "fob_price_text",
        "fob_price_usd",
        "fob_price_usd_text",
        "fob_total",
        "fob_total_usd",
    ):
        val = _as_trimmed_str(raw.get(key))
        if val:
            out[key] = val
    return out


def _finalize_english_meta(
    meta_en: dict[str, Any],
    fixed: dict[str, str],
    meta_src: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    src = meta_src if isinstance(meta_src, dict) else {}
    out = dict(meta_en)
    zh_addr = "广东省深圳市龙岗区平湖街道宝能智创谷B栋A单元6A01"
    if fixed.get("default_company_name"):
        src_co = _as_trimmed_str(src.get("co_name")).strip()
        if src_co == _KNOWN_CO_NAME_ZH or contains_cjk(out.get("co_name")):
            out["co_name"] = fixed["default_company_name"]
    if fixed.get("default_company_address"):
        src_addr = _as_trimmed_str(src.get("co_addr")).strip()
        if src_addr == zh_addr or contains_cjk(out.get("co_addr")):
            out["co_addr"] = fixed["default_company_address"]
    for key, val in list(out.items()):
        if key in {"quote_date_iso", "sample_required"}:
            continue
        if not isinstance(val, str):
            continue
        cleaned = sanitize_english_export_text(val)
        if cleaned != val and contains_cjk(val):
            warnings.append(f"meta.{key}")
        out[key] = cleaned
    return out, warnings


def is_usd_payee_account(payee: dict[str, Any] | None) -> bool:
    if not isinstance(payee, dict):
        return False
    from company_payment_accounts import ACCOUNT_TYPE_FOREIGN, classify_account_bucket

    bucket = str(payee.get("account_type") or "").strip().lower()
    if bucket == ACCOUNT_TYPE_FOREIGN:
        return True
    if bucket == "cn":
        return False
    return classify_account_bucket(payee) == ACCOUNT_TYPE_FOREIGN


def payee_fields_preserve_chinese(
    payee: dict[str, Any] | None,
    *,
    selected_bank_account_type: str = "",
) -> bool:
    """收款主体语言由所选账户类型决定，不由报价单语言覆盖。"""
    from company_payment_accounts import ACCOUNT_TYPE_CN, ACCOUNT_TYPE_FOREIGN

    selected = str(selected_bank_account_type or "").strip().lower()
    if selected == ACCOUNT_TYPE_FOREIGN:
        return False
    if selected == ACCOUNT_TYPE_CN:
        return True
    if not isinstance(payee, dict):
        return True
    return not is_usd_payee_account(payee)


def payee_fields_for_chinese_presentation(payee: dict[str, Any]) -> dict[str, str]:
    company = _first_payee_str(payee.get("company_name"), payee.get("display_label_cn"))
    return {
        "company_name": company,
        "bank_name": _first_payee_str(payee.get("bank_name"), payee.get("bank_name_en")),
        "bank_account": re.sub(r"\s+", " ", _as_trimmed_str(payee.get("bank_account"))).strip(),
        "alipay": _as_trimmed_str(payee.get("alipay")).strip(),
        "currency": str(payee.get("currency") or "CNY").strip().upper() or "CNY",
        "is_usd_account": "",
        "preserve_chinese": "1",
    }


def format_usd_bank_block_en(payee: dict[str, Any]) -> str:
    """美金账户英文 PDF 银行信息块。"""
    name = _first_payee_str(payee.get("company_name_en"), payee.get("company_name"))
    account = re.sub(r"\s+", " ", _as_trimmed_str(payee.get("bank_account"))).strip()
    bank = _first_payee_str(payee.get("bank_name_en"), payee.get("bank_name"))
    swift = _as_trimmed_str(payee.get("swift_code")).strip()
    address = _as_trimmed_str(payee.get("bank_address_en")).strip()
    note = _as_trimmed_str(payee.get("bank_note_en")).strip()
    lines = ["Bank Information:"]
    if name:
        lines.append(f"NAME: {name}")
    if account:
        lines.append(f"A/C: {account}")
    if bank:
        lines.append(f"BANK NAME: {bank}")
    if swift:
        lines.append(f"SWIFT CODE: {swift}")
    if address:
        lines.append(f"ADD: {address}")
    if note:
        lines.append(f"NOTE: {note}")
    return "\n".join(lines)


def resolve_payee_for_export_language(
    payee: dict[str, Any] | None,
    export_lang: str,
    *,
    selected_bank_account_type: str = "",
) -> dict[str, str]:
    """按导出语言解析最终 PDF 收款字段（不依赖输入框原文）。"""
    if not isinstance(payee, dict):
        return {}
    if payee_fields_preserve_chinese(payee, selected_bank_account_type=selected_bank_account_type):
        return payee_fields_for_chinese_presentation(payee)
    lang = str(export_lang or "cn").strip().lower()
    if lang == "en" and is_usd_payee_account(payee):
        company = _first_payee_str(payee.get("company_name_en"), payee.get("company_name"))
        return {
            "company_name": company,
            "bank_name": "",
            "bank_account": "",
            "bank_block_text": format_usd_bank_block_en(payee),
            "swift_code": _as_trimmed_str(payee.get("swift_code")).strip(),
            "bank_address_en": _as_trimmed_str(payee.get("bank_address_en")).strip(),
            "bank_note_en": _as_trimmed_str(payee.get("bank_note_en")).strip(),
            "alipay": "",
            "currency": "USD",
            "is_usd_account": "1",
        }
    company = _first_payee_str(payee.get("display_label_cn"), payee.get("company_name"))
    return {
        "company_name": company,
        "bank_name": _first_payee_str(payee.get("bank_name"), payee.get("bank_name_en")),
        "bank_account": re.sub(r"\s+", " ", _as_trimmed_str(payee.get("bank_account"))).strip(),
        "alipay": _as_trimmed_str(payee.get("alipay")).strip(),
        "currency": str(payee.get("currency") or "CNY").strip().upper() or "CNY",
        "is_usd_account": "",
    }


def translate_payment_for_export(
    payee: dict[str, Any] | None,
    *,
    pairs: list[tuple[str, str]],
    fixed: dict[str, str],
    selected_bank_account_type: str = "",
) -> tuple[dict[str, str] | None, list[str]]:
    if not isinstance(payee, dict):
        return None, []
    if payee_fields_preserve_chinese(payee, selected_bank_account_type=selected_bank_account_type):
        return payee_fields_for_chinese_presentation(payee), []
    warnings: list[str] = []
    if is_usd_payee_account(payee):
        company = _first_payee_str(payee.get("company_name_en"), payee.get("company_name"))
        if not company or contains_cjk(company):
            warnings.append("payee.company_name")
            company = company or fixed.get("default_company_name") or _EN_FALLBACK
        block = format_usd_bank_block_en(payee)
        return (
            {
                "company_name": company,
                "bank_name": "",
                "bank_account": "",
                "bank_block_text": block,
                "swift_code": _as_trimmed_str(payee.get("swift_code")).strip(),
                "bank_address_en": _as_trimmed_str(payee.get("bank_address_en")).strip(),
                "bank_note_en": _as_trimmed_str(payee.get("bank_note_en")).strip(),
                "alipay": "",
                "currency": "USD",
                "is_usd_account": "1",
            },
            warnings,
        )
    company_src = _first_payee_str(
        payee.get("company_name_en"),
        payee.get("company_name"),
    )
    bank_src = _first_payee_str(payee.get("bank_name_en"), payee.get("bank_name"))
    company_en, fb1 = ensure_english_quote_text(
        company_src,
        field_name="authorized_payee",
        pairs=pairs,
        fixed=fixed,
    )
    if fb1:
        warnings.append("payee.company_name")
    bank_en, fb2 = ensure_english_quote_text(
        bank_src,
        field_name="bank_name",
        pairs=pairs,
        fixed=fixed,
    )
    if fb2:
        warnings.append("payee.bank_name")
    account = re.sub(r"\s+", " ", _as_trimmed_str(payee.get("bank_account"))).strip()
    alipay = _as_trimmed_str(payee.get("alipay")).strip()
    return (
        {
            "company_name": company_en or fixed.get("default_company_name") or _EN_FALLBACK,
            "bank_name": bank_en or _EN_NA,
            "bank_account": account,
            "alipay": alipay,
            "currency": str(payee.get("currency") or "CNY").strip().upper() or "CNY",
            "is_usd_account": "",
        },
        warnings,
    )


def _first_payee_str(*candidates: Any) -> str:
    for value in candidates:
        text = _as_trimmed_str(value).strip()
        if text and text not in ("-", "—"):
            return text
    return ""


def finalize_english_export_bundle(result: dict[str, Any]) -> dict[str, Any]:
    """导出前最后一遍清洗，确保无中文与 [UNTRANSLATED]。"""
    out = dict(result)
    row_keys = ("name", "size", "desc", "pack", "note")
    meta_en = out.get("meta_en")
    if isinstance(meta_en, dict):
        cleaned_meta: dict[str, Any] = {}
        for key, val in meta_en.items():
            if key in {"quote_date_iso", "sample_required"}:
                cleaned_meta[key] = val
            elif isinstance(val, str):
                cleaned_meta[key] = sanitize_english_export_text(val)
            else:
                cleaned_meta[key] = val
        out["meta_en"] = cleaned_meta
    rows_en = out.get("rows_en")
    if isinstance(rows_en, list):
        cleaned_rows: list[dict[str, Any]] = []
        for raw in rows_en:
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            for key in row_keys:
                if isinstance(row.get(key), str):
                    row[key] = sanitize_english_export_text(row[key])
            cleaned_rows.append(row)
        out["rows_en"] = cleaned_rows
    payee_en = out.get("payee_en")
    if isinstance(payee_en, dict):
        cleaned_payee = dict(payee_en)
        if str(cleaned_payee.get("preserve_chinese") or "").strip() != "1":
            for key in ("company_name", "bank_name", "bank_block_text"):
                if isinstance(cleaned_payee.get(key), str):
                    cleaned_payee[key] = sanitize_english_export_text(cleaned_payee[key])
        out["payee_en"] = cleaned_payee
    return out


def translate_quote_sheet_fields(bundle: dict[str, Any]) -> dict[str, Any]:
    """字段级英文翻译；残余中文使用 To be confirmed，并记录 english_warnings。"""
    terms = _load_terms()
    pairs = _phrase_pairs(terms)
    fixed = _terms_fixed(terms)
    meta_in = bundle.get("meta")
    meta = meta_in if isinstance(meta_in, dict) else {}
    rows_in = bundle.get("rows")
    rows_raw: list[Any] = rows_in if isinstance(rows_in, list) else []
    payee_in = bundle.get("payee") if isinstance(bundle.get("payee"), dict) else None
    selected_type = str(
        bundle.get("selected_bank_account_type")
        or bundle.get("payee_account_type")
        or ""
    ).strip().lower()

    meta_en: dict[str, Any] = {}
    warnings: list[str] = []
    for k, v in meta.items():
        if k in {"quote_date_iso", "sample_required"}:
            meta_en[k] = v
            continue
        text, used_fallback = ensure_english_quote_text(
            v,
            field_name=str(k),
            pairs=pairs,
            fixed=fixed,
        )
        if used_fallback:
            warnings.append(f"meta.{k}")
        meta_en[k] = text

    meta_en, meta_finalize_warnings = _finalize_english_meta(meta_en, fixed, meta)
    warnings.extend(meta_finalize_warnings)

    rows_en: list[dict[str, Any]] = []
    for i, raw in enumerate(rows_raw):
        if not isinstance(raw, dict):
            continue
        row_out: dict[str, Any] = {
            "line_order": raw.get("line_order", i),
            **_row_fob_usd_fields(raw),
            "qty": translate_free_text(raw.get("qty"), pairs, field_name="qty", fixed=fixed),
            "price": _as_trimmed_str(raw.get("price")),
        }
        for fk in ("name", "size", "desc", "note"):
            text, used_fallback = ensure_english_quote_text(
                raw.get(fk),
                field_name=fk,
                pairs=pairs,
                fixed=fixed,
            )
            if used_fallback:
                warnings.append(f"rows[{i}].{fk}")
            row_out[fk] = text
        pack_text = translate_pack_for_quote_sheet(raw.get("pack"), pairs, fixed=fixed)
        if contains_cjk(pack_text):
            warnings.append(f"rows[{i}].pack")
            pack_text = _EN_NA
        row_out["pack"] = pack_text
        rows_en.append(row_out)

    payee_en, payee_warnings = translate_payment_for_export(
        payee_in,
        pairs=pairs,
        fixed=fixed,
        selected_bank_account_type=selected_type,
    )
    warnings.extend(payee_warnings)

    result = {
        "ok": True,
        "meta_en": meta_en,
        "rows_en": rows_en,
        "payee_en": payee_en,
        "untranslated_fields": sorted(set(warnings)),
        "english_warnings": sorted(set(warnings)),
    }
    return finalize_english_export_bundle(result)
