"""报价单中英文术语库与字段翻译（不报 LLM：术语表替换 + [UNTRANSLATED] 回退）。

编辑 data/i18n/quote_sheet_zh_en.json 后会在下一次请求按 mtime 自动重载。"""
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


def _as_trimmed_str(v: Any) -> str:
    return "" if v is None else str(v)


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
    if not _CJK_RE.search(t) and re.fullmatch(r"[\d\s\-+/().]+", t):
        return True
    return False


def apply_glossary_phrases(text: str, pairs: list[tuple[str, str]]) -> str:
    out = text
    for zh, en in pairs:
        out = out.replace(zh, en)
    return out


def translate_free_text(original: Any, pairs: list[tuple[str, str]]) -> str:
    s_in = _as_trimmed_str(original).strip()
    if not s_in:
        return ""
    if should_skip_translate(s_in):
        return s_in
    out = apply_glossary_phrases(s_in, pairs)
    if _CJK_RE.search(out):
        return f"{s_in} [UNTRANSLATED]"
    return out


def _sanitize_pack_for_translate(value: object) -> str:
    try:
        from quote_sheet_prefill import sanitize_customer_pack_display

        return sanitize_customer_pack_display(value)
    except Exception:
        return _as_trimmed_str(value).strip()


def translate_pack_for_quote_sheet(text: object, pairs: list[tuple[str, str]]) -> str:
    """包装列英文：数量+单位模板，禁止 [UNTRANSLATED] 进客户 PDF。"""
    s = _UNTRANSLATED_RE.sub("", _sanitize_pack_for_translate(text)).strip()
    if not s:
        return ""
    m = _PACK_QTY_RE.match(s)
    if m:
        unit = _PACK_UNIT_EN.get(m.group(2), "pc")
        return f"{m.group(1)} {unit}"
    out = apply_glossary_phrases(s, pairs)
    out = _UNTRANSLATED_RE.sub("", out).strip()
    if _CJK_RE.search(out):
        return ""
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


def translate_quote_sheet_fields(bundle: dict[str, Any]) -> dict[str, Any]:
    """字段级翻译；数值纯数字、ISO 日期、邮箱跳过；残余中文退回原文+[UNTRANSLATED]。"""
    terms = _load_terms()
    pairs = _phrase_pairs(terms)
    meta_in = bundle.get("meta")
    meta = meta_in if isinstance(meta_in, dict) else {}
    rows_in = bundle.get("rows")
    rows_raw: list[Any] = rows_in if isinstance(rows_in, list) else []

    meta_en: dict[str, Any] = {}
    for k, v in meta.items():
        if k in {"quote_date_iso", "sample_required"}:
            meta_en[k] = v
            continue
        meta_en[k] = translate_free_text(v, pairs)

    rows_en: list[dict[str, Any]] = []
    for i, raw in enumerate(rows_raw):
        if not isinstance(raw, dict):
            continue
        rows_en.append(
            {
                "name": translate_free_text(raw.get("name"), pairs),
                "size": translate_free_text(raw.get("size"), pairs),
                "desc": translate_free_text(raw.get("desc"), pairs),
                "pack": translate_pack_for_quote_sheet(raw.get("pack"), pairs),
                "qty": translate_free_text(raw.get("qty"), pairs),
                "price": _as_trimmed_str(raw.get("price")),
                "note": translate_free_text(raw.get("note"), pairs),
                "line_order": raw.get("line_order", i),
                **_row_fob_usd_fields(raw),
            }
        )

    hints_meta = [
        f"meta.{k}" for k, v in meta_en.items() if isinstance(v, str) and "[UNTRANSLATED]" in v
    ]
    hints_rows: list[str] = []
    for i, rr in enumerate(rows_en):
        for fk, fv in rr.items():
            if isinstance(fv, str) and "[UNTRANSLATED]" in fv:
                hints_rows.append(f"rows[{i}].{fk}")

    return {
        "ok": True,
        "meta_en": meta_en,
        "rows_en": rows_en,
        "untranslated_fields": [*hints_meta, *hints_rows],
    }
