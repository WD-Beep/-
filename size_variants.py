"""多尺寸识别：从表格字段/文本解析 size_variants，兼容单尺寸。"""
from __future__ import annotations

import re
from typing import Any

from piece_area_table import _parse_lwh_from_text

_LWH_TRIPLE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米|mm|MM|毫米)?",
    re.I,
)

_LABELED_SIZE_RE = re.compile(
    r"(?P<label>(?:特)?(?:小|中|大)(?:号)?|(?:XX?L|XL|L|M|S)|尺寸\s*\d+|型号\s*[A-Za-z0-9]+)"
    r"\s*[：:\s]+"
    r"(?P<size>\d+(?:\.\d+)?\s*[×xX*]\s*\d+(?:\.\d+)?\s*[×xX*]\s*\d+(?:\.\d+)?\s*(?:cm|CM|厘米|mm|MM|毫米)?)",
    re.I,
)

_SIZE_COLUMN_KEY_RE = re.compile(
    r"^(?:成品)?尺寸\s*(\d+)$|^(?:size|variant)\s*(\d+)$",
    re.I,
)

_SIZE_TEXT_KEYS = (
    "成品尺寸",
    "尺寸",
    "产品尺寸",
    "product_size",
    "size",
    "size_text",
    "product_size_text",
)

_LABEL_FALLBACKS = ("小号", "中号", "大号", "特大号", "尺寸4", "尺寸5", "尺寸6")


def _lwh_to_product_size(l: float, w: float, h: float, *, raw: str = "") -> dict[str, float]:
    text = str(raw or "")
    if "mm" in text.lower() or "毫米" in text:
        l, w, h = l / 10.0, w / 10.0, h / 10.0
    return {"LCM": round(l, 4), "WCM": round(w, 4), "HCM": round(h, 4)}


def _format_size_text(ps: dict[str, float]) -> str:
    l = ps.get("LCM")
    w = ps.get("WCM")
    h = ps.get("HCM")
    if l and w and h:
        def _fmt(v: float) -> str:
            return str(int(v)) if abs(v - round(v)) < 1e-6 else f"{v:g}"

        return f"{_fmt(l)}×{_fmt(w)}×{_fmt(h)}cm"
    return ""


def _size_key(ps: dict[str, float]) -> tuple[float, float, float]:
    return (
        round(float(ps.get("LCM") or 0), 2),
        round(float(ps.get("WCM") or 0), 2),
        round(float(ps.get("HCM") or 0), 2),
    )


def _variant_dict(label: str, product_size: dict[str, float], *, size_text: str = "") -> dict[str, Any]:
    st = str(size_text or "").strip() or _format_size_text(product_size)
    lbl = str(label or "").strip() or st or "尺寸"
    return {
        "label": lbl,
        "size_text": st,
        "product_size": dict(product_size),
    }


def _dedupe_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[float, float, float]] = set()
    out: list[dict[str, Any]] = []
    for v in variants:
        ps = v.get("product_size") if isinstance(v.get("product_size"), dict) else {}
        key = _size_key(ps)
        if min(key) <= 0 or key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def parse_size_variants_from_text(text: str) -> list[dict[str, Any]]:
    """从一段文本识别多个 L×W×H 尺寸（至少 2 个才返回多档）。"""
    raw = str(text or "").strip()
    if not raw:
        return []

    labeled: list[dict[str, Any]] = []
    for m in _LABELED_SIZE_RE.finditer(raw):
        seg = str(m.group("size") or "").strip()
        triple = _parse_lwh_from_text(seg) or _parse_lwh_from_text(m.group(0) or "")
        if not triple:
            continue
        l, w, h = triple
        ps = _lwh_to_product_size(l, w, h, raw=seg)
        labeled.append(_variant_dict(str(m.group("label") or "").strip(), ps, size_text=seg))

    if len(labeled) >= 2:
        return _dedupe_variants(labeled)

    segments: list[str] = []
    for part in re.split(r"[\n\r/|;；]+", raw):
        part = part.strip(" ，,、")
        if part:
            segments.append(part)

    from_segments: list[dict[str, Any]] = []
    if len(segments) >= 2:
        for idx, seg in enumerate(segments):
            triple = _parse_lwh_from_text(seg)
            if not triple:
                from_segments = []
                break
            l, w, h = triple
            ps = _lwh_to_product_size(l, w, h, raw=seg)
            label = _LABEL_FALLBACKS[idx] if idx < len(_LABEL_FALLBACKS) else f"尺寸{idx + 1}"
            from_segments.append(_variant_dict(label, ps, size_text=seg))

    if len(from_segments) >= 2:
        return _dedupe_variants(from_segments)

    triples: list[tuple[str, tuple[float, float, float]]] = []
    for m in _LWH_TRIPLE_RE.finditer(raw):
        seg = m.group(0)
        parsed = _parse_lwh_from_text(seg)
        if parsed:
            triples.append((seg, parsed))

    if len(triples) >= 2:
        out: list[dict[str, Any]] = []
        for idx, (seg, (l, w, h)) in enumerate(triples):
            ps = _lwh_to_product_size(l, w, h, raw=seg)
            label = _LABEL_FALLBACKS[idx] if idx < len(_LABEL_FALLBACKS) else f"尺寸{idx + 1}"
            out.append(_variant_dict(label, ps, size_text=seg.strip()))
        return _dedupe_variants(out)

    return []


def _variants_from_section_map(section: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(section, dict):
        return []
    numbered: list[tuple[int, str, str]] = []
    for key, value in section.items():
        val = str(value or "").strip()
        if not val:
            continue
        m = _SIZE_COLUMN_KEY_RE.match(str(key or "").strip())
        if m:
            num = int(m.group(1) or m.group(2) or 0)
            numbered.append((num, str(key), val))
    numbered.sort(key=lambda x: x[0])
    out: list[dict[str, Any]] = []
    for num, key, val in numbered:
        triple = _parse_lwh_from_text(val)
        if not triple:
            parsed = parse_size_variants_from_text(val)
            if len(parsed) == 1:
                out.append(parsed[0])
            continue
        l, w, h = triple
        ps = _lwh_to_product_size(l, w, h, raw=val)
        out.append(_variant_dict(f"尺寸{num or len(out) + 1}", ps, size_text=val))
    if len(out) >= 2:
        return _dedupe_variants(out)

    for key in _SIZE_TEXT_KEYS:
        val = str(section.get(key) or "").strip()
        if val:
            parsed = parse_size_variants_from_text(val)
            if len(parsed) >= 2:
                return parsed
    return []


def variant_from_product_size(product_size: dict[str, float] | None, *, label: str = "") -> dict[str, Any] | None:
    if not isinstance(product_size, dict):
        return None
    try:
        l = float(product_size.get("LCM") or product_size.get("length_cm") or product_size.get("lcm") or 0)
        w = float(product_size.get("WCM") or product_size.get("width_cm") or product_size.get("wcm") or 0)
        h = float(product_size.get("HCM") or product_size.get("height_cm") or product_size.get("hcm") or 0)
    except (TypeError, ValueError):
        return None
    if min(l, w, h) <= 0:
        return None
    ps = {"LCM": l, "WCM": w, "HCM": h}
    return _variant_dict(label or "默认尺寸", ps)


def extract_size_variants_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从 payload / quote_params 提取尺寸变体；仅 1 个时返回单元素列表。"""
    if not isinstance(payload, dict):
        return []

    explicit = payload.get("size_variants")
    if isinstance(explicit, list) and explicit:
        cleaned: list[dict[str, Any]] = []
        for idx, row in enumerate(explicit):
            if not isinstance(row, dict):
                continue
            ps = row.get("product_size") if isinstance(row.get("product_size"), dict) else {}
            if not ps and str(row.get("size_text") or "").strip():
                triple = _parse_lwh_from_text(str(row.get("size_text")))
                if triple:
                    ps = _lwh_to_product_size(*triple, raw=str(row.get("size_text")))
            v = variant_from_product_size(ps, label=str(row.get("label") or f"尺寸{idx + 1}"))
            if v:
                if str(row.get("size_text") or "").strip():
                    v["size_text"] = str(row.get("size_text")).strip()
                cleaned.append(v)
        cleaned = _dedupe_variants(cleaned)
        if cleaned:
            return cleaned

    found: list[dict[str, Any]] = []

    qp = payload.get("quote_params")
    if isinstance(qp, dict):
        sec_b = qp.get("B") if isinstance(qp.get("B"), dict) else {}
        found.extend(_variants_from_section_map(sec_b))

    meta = payload.get("sheet_metadata")
    if isinstance(meta, dict):
        size_meta = str(meta.get("尺寸") or meta.get("成品尺寸") or "").strip()
        if size_meta:
            found.extend(parse_size_variants_from_text(size_meta))

    for key in ("product_size_text", "size_text"):
        text = str(payload.get(key) or "").strip()
        if text:
            parsed = parse_size_variants_from_text(text)
            if parsed:
                found.extend(parsed)

    found = _dedupe_variants(found)
    if len(found) >= 2:
        return found

    single = variant_from_product_size(payload.get("product_size") if isinstance(payload.get("product_size"), dict) else None)
    if single:
        return [single]

    if len(found) == 1:
        return found

    return []


def enrich_payload_size_variants(payload: dict[str, Any]) -> int:
    """写入 payload['size_variants']；返回变体数量（>=1 时含单尺寸）。"""
    variants = extract_size_variants_from_payload(payload)
    if not variants:
        payload.pop("size_variants", None)
        payload.pop("multi_size", None)
        return 0
    payload["size_variants"] = variants
    payload["multi_size"] = len(variants) >= 2
    primary = variants[0]
    payload["product_size"] = dict(primary.get("product_size") or {})
    if str(primary.get("size_text") or "").strip():
        payload["product_size_text"] = str(primary.get("size_text")).strip()
    return len(variants)
