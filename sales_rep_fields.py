"""业务员编号/姓名：从上传表 quote_params 提取、合并展示（sales_display）。"""
from __future__ import annotations

import re
from typing import Any

SALES_CODE_ALIASES: tuple[str, ...] = (
    "业务员编号",
    "编号",
    "sales_code",
    "salesperson_id",
    "sales_id",
    "seller_id",
    "staff_id",
)

SALES_NAME_ALIASES: tuple[str, ...] = (
    "业务员姓名",
    "业务员",
    "销售姓名",
    "sales_name",
    "salesperson",
    "salesperson_name",
    "seller_name",
    "staff_name",
)

_COMBINED_SALES_RE = re.compile(
    r"^\s*(?P<code>[^\s/|，,、\-]+)\s*[-\s/|，,、]\s*(?P<name>.+?)\s*$"
)


def normalize_field_key(text: str) -> str:
    """与 demand_parser._normalise_key 对齐，便于匹配上传表表头。"""
    if text is None:
        return ""
    cleaned = str(text).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[（）()\[\]【】%]", "", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    for ch in ("/", "\\", ",", "，", ":", "：", ".", "。"):
        cleaned = cleaned.replace(ch, "")
    return cleaned.lower()


def pick_section_value(
    section: dict[str, Any] | None,
    *candidates: str,
    exclude_key_substrings: tuple[str, ...] = (),
) -> str:
    if not isinstance(section, dict):
        return ""
    norm_map: dict[str, str] = {}
    for raw_key, raw_val in section.items():
        nk = normalize_field_key(str(raw_key or ""))
        val = str(raw_val or "").strip()
        if nk and val and val not in {"-", "—"}:
            norm_map.setdefault(nk, val)
    for label in candidates:
        nk = normalize_field_key(label)
        if nk in norm_map:
            return norm_map[nk]
    for label in candidates:
        nk = normalize_field_key(label)
        if not nk:
            continue
        for key, val in section.items():
            key_n = normalize_field_key(str(key or ""))
            if any(ex in key_n for ex in exclude_key_substrings):
                continue
            v = str(val or "").strip()
            if not v or v in {"-", "—"}:
                continue
            if nk in key_n or key_n in nk:
                return v
    return ""


def split_combined_sales(text: str) -> tuple[str, str]:
    """解析同格「编号-姓名」如 23-刘朋 / 23 刘朋 / 23/刘朋。"""
    t = str(text or "").strip()
    if not t or t in {"-", "—"}:
        return "", ""
    m = _COMBINED_SALES_RE.match(t)
    if m:
        return m.group("code").strip(), m.group("name").strip()
    if re.match(r"^[\w\-]+$", t) and re.search(r"\d", t):
        return t, ""
    return "", t


def format_sales_display(code: str, name: str) -> str:
    c = str(code or "").strip()
    n = str(name or "").strip()
    if not c and not n:
        return "-"
    if c and n:
        if c == n:
            return c
        if n in c or re.search(r"[-\s/|，,、]", c):
            return c
        return f"{c}-{n}"
    return c or n


def extract_sales_fields(quote_params: dict[str, Any] | None) -> dict[str, str]:
    sec_a: dict[str, Any] = {}
    if isinstance(quote_params, dict):
        raw = quote_params.get("A") or quote_params.get("a")
        if isinstance(raw, dict):
            sec_a = raw

    code = pick_section_value(sec_a, *SALES_CODE_ALIASES)
    name = pick_section_value(
        sec_a,
        *SALES_NAME_ALIASES,
        exclude_key_substrings=("编号", "code", "id"),
    )

    if code and not name:
        c2, n2 = split_combined_sales(code)
        if n2:
            code, name = c2, n2
    if name and not code:
        c2, n2 = split_combined_sales(name)
        if c2:
            code, name = c2, n2
    if name == code and code and re.fullmatch(r"[\d\w\-]+", code):
        name = ""

    return {
        "sales_code": code,
        "sales_name": name,
        "sales_display": format_sales_display(code, name),
    }


def enrich_quote_sales_fields(quote: dict[str, Any]) -> None:
    """就地补全 quote 上的 sales_code / sales_name / sales_display。"""
    if not isinstance(quote, dict):
        return
    extracted = extract_sales_fields(quote.get("quote_params"))
    if not str(quote.get("sales_code") or "").strip():
        quote["sales_code"] = extracted["sales_code"]
    if not str(quote.get("sales_name") or "").strip():
        quote["sales_name"] = extracted["sales_name"]
    quote["sales_display"] = format_sales_display(
        str(quote.get("sales_code") or ""),
        str(quote.get("sales_name") or ""),
    )


def merge_quote_sales_from_payload(quote: dict[str, Any], payload: dict[str, Any]) -> None:
    """报价结果入库/返回前：保留 quote_params 并写入业务员字段。"""
    if not isinstance(quote, dict) or not isinstance(payload, dict):
        return
    qp = payload.get("quote_params")
    if isinstance(qp, dict) and qp:
        quote["quote_params"] = qp
    for key in ("sales_code", "sales_name"):
        val = payload.get(key)
        if val is not None and str(val).strip():
            quote[key] = str(val).strip()
    enrich_quote_sales_fields(quote)


def apply_sales_fields_to_payload(payload: dict[str, Any]) -> None:
    """解析完成后把业务员字段写入 payload（供后续 merge）。"""
    if not isinstance(payload, dict):
        return
    fields = extract_sales_fields(payload.get("quote_params"))
    for key, val in fields.items():
        if key == "sales_display":
            continue
        if val:
            payload[key] = val
