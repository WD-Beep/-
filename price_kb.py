"""Local material price knowledge base.

Loads `data/price_kb.xlsx` (the company "材料询价" 标价表) into memory once,
normalises material names + prices, and exposes a fuzzy lookup so that
incoming demand-form materials can be priced before falling back to LLM
completion.

Knowledge base file format: three columns named 材料名称 / 规格大小 / 单价.
Material names commonly carry编号 prefixes (`111-05321-000010织带夹20MM 多耐福`)
and brand suffixes (`多耐福`, `利富高`, `WJ`, `YKK`, `WooJin`). Prices use
mixed units: `7元/码`, `0.32/PCS`, `0.95/1.3/SET`, raw `13.38`, `3.5/Y`,
`14元/码²`. We keep the raw price text and ALSO surface a parsed numeric
unit price for the quote engine.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sheet_parser import (
    SheetParseError,
    normalize_rows,
    parse_sheet_xml_rows,
    read_sheet_entries,
    read_shared_strings,
)


ROOT = Path(__file__).resolve().parent
from price_kb_paths import LEGACY_PROJECT_KB_PATH, official_kb_path  # noqa: E402

LEGACY_DEFAULT_KB_PATH = LEGACY_PROJECT_KB_PATH


def __getattr__(name: str):
    if name == "DEFAULT_KB_PATH":
        return official_kb_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

DEFAULT_LOOKUP_MIN_SCORE = 0.34


def resolve_lookup_min_score(explicit: float | None) -> float:
    """未显式传入时使用略紧的默认阈值，可用环境变量 QUOTE_KB_MIN_SCORE（0~1）放宽/收紧。"""
    if explicit is not None:
        return explicit
    raw = os.environ.get("QUOTE_KB_MIN_SCORE", "").strip()
    if not raw:
        return DEFAULT_LOOKUP_MIN_SCORE
    try:
        v = float(raw)
        return min(0.99, max(0.05, v))
    except ValueError:
        return DEFAULT_LOOKUP_MIN_SCORE


# Brand or vendor tokens that show up as suffixes on material names. We
# strip them when normalising so a user query like "20MM 织带夹" can match
# "111-05321-000010织带夹20MM 多耐福".
KNOWN_BRAND_TOKENS = (
    "多耐福", "利富高", "woojin", "wj", "ykk", "3m",
    "格罗夫", "格罗维", "尼龙", "金狮", "杜邦",
)

# Common stop fragments inside material names — we keep them but DO NOT
# treat them as discriminators when scoring.
NAME_STOP_TOKENS = {"的", "和", "与", "型", "款", "用", "在"}


# Regex bits ----------------------------------------------------------------
_CODE_PREFIX_PATTERN = re.compile(
    r"^(?:\d{2,4}[-\.]\d{3,6}[-\.]\d{2,8}\s*/?\s*)+"
)
_TRAILING_BRAND_PATTERN = re.compile(
    r"\s*(?:" + "|".join(re.escape(b) for b in KNOWN_BRAND_TOKENS) + r")\s*$",
    re.IGNORECASE,
)
_TOKENIZE_PATTERN = re.compile(r"[A-Za-z]+|\d+(?:\.\d+)?|[一-鿿]")
_PRICE_NUMERIC_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
_PRICE_UNIT_PATTERN = re.compile(
    r"(?:元?\s*/\s*)(码²|码|个|套|件|条|米|m|y|pcs|pc|pair|set|hset|kg|g|箱)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class KBEntry:
    raw_name: str
    raw_spec: str
    raw_price: str
    auto_learned: bool
    normalised_name: str
    name_tokens: frozenset[str]
    unit_price_value: float           # numeric portion of the price (CNY)
    unit_price_unit: str              # 码/PCS/SET/etc., or '' when price was a bare number
    price_note: str                   # '0.95/1.3/SET' style multi-component note


@dataclass(frozen=True)
class KBHit:
    entry: KBEntry
    score: float


class PriceKB:
    """Loaded once at import-time; thread-safe read access."""

    def __init__(self, entries: list[KBEntry]):
        self._entries = entries
        self.version: int = 0
        self.content_hash: str = ""
        # Inverted index: token -> set of entry indices, so we can score
        # candidate entries by token overlap in O(matches) instead of O(N).
        self._token_index: dict[str, list[int]] = {}
        for idx, entry in enumerate(entries):
            for token in entry.name_tokens:
                self._token_index.setdefault(token, []).append(idx)

    @property
    def size(self) -> int:
        return len(self._entries)

    def lookup(self, name: str, spec: str = "", *, min_score: float | None = None) -> Optional[KBHit]:
        """Return the highest-scoring entry for the given material name +
        spec, or None when nothing crosses ``min_score`` (range 0..1).

        Default ``min_score`` 略高于 0.30，以降低「名称略像但并非同一物料」的假命中；
        需兼容弱匹配时设置环境变量 ``QUOTE_KB_MIN_SCORE`` 或直接传入更小的 ``min_score``。"""
        ms = resolve_lookup_min_score(min_score)
        query_tokens = _tokens_from_text(f"{name} {spec}")
        if not query_tokens:
            return None
        candidates: dict[int, int] = {}
        for token in query_tokens:
            for idx in self._token_index.get(token, ()):
                candidates[idx] = candidates.get(idx, 0) + 1
        if not candidates:
            return None
        best: Optional[KBHit] = None
        for idx, overlap in candidates.items():
            entry = self._entries[idx]
            score = _score_entry(query_tokens, entry, overlap, spec)
            if score < ms:
                continue
            if best is None or score > best.score:
                best = KBHit(entry=entry, score=score)
        return best

    def lookup_ranked(
        self,
        name: str,
        spec: str = "",
        *,
        limit: int = 5,
        min_score: float | None = None,
    ) -> list[KBHit]:
        """返回按分数降序的候选列表，用于多候选澄清。"""
        ms = resolve_lookup_min_score(min_score)
        query_tokens = _tokens_from_text(f"{name} {spec}")
        if not query_tokens:
            return []
        candidates: dict[int, int] = {}
        for token in query_tokens:
            for idx in self._token_index.get(token, ()):
                candidates[idx] = candidates.get(idx, 0) + 1
        if not candidates:
            return []
        hits: list[KBHit] = []
        for idx, overlap in candidates.items():
            entry = self._entries[idx]
            score = _score_entry(query_tokens, entry, overlap, spec)
            if score < ms:
                continue
            hits.append(KBHit(entry=entry, score=score))
        hits.sort(key=lambda h: (-h.score, h.entry.raw_name))
        return hits[: max(1, int(limit))]

    def lookup_many(
        self,
        items: list[dict[str, str]],
        *,
        min_score: float | None = None,
    ) -> tuple[dict[int, KBHit], list[int]]:
        """Bulk lookup helper. Returns (hits_by_index, miss_indices)."""
        ms = resolve_lookup_min_score(min_score)
        hits: dict[int, KBHit] = {}
        misses: list[int] = []
        for idx, item in enumerate(items):
            name = str(item.get("name", "")).strip()
            spec = str(item.get("spec", "")).strip()
            hit = self.lookup(name, spec, min_score=ms)
            if hit is None:
                misses.append(idx)
            else:
                hits[idx] = hit
        return hits, misses


    def suggest_entries_for_query(self, query: str, *, limit: int = 6) -> list[KBEntry]:
        """lookup 未命中时：按 query 分词在名称中弱匹配，用于向用户提示相近物料。"""
        q = (query or "").strip()
        if not q:
            return []
        q_tokens = _tokens_from_text(q)
        q_tokens = {t for t in q_tokens if len(t) >= 2 or (t.isdigit() and len(t) >= 1)}
        if not q_tokens:
            return []
        scored: list[tuple[float, int]] = []
        for idx, ent in enumerate(self._entries):
            name_blob = f"{ent.normalised_name} {ent.raw_name}"
            etoks = ent.name_tokens
            ov = 0.0
            for t in q_tokens:
                if t in etoks:
                    ov += 2.0
                elif t in name_blob:
                    ov += 1.0
            if ov <= 0:
                continue
            scored.append((ov, idx))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out: list[KBEntry] = []
        seen: set[str] = set()
        for sc, i in scored:
            e = self._entries[i]
            key = f"{e.raw_name}|{e.raw_price}"
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
            if len(out) >= limit:
                break
        return out


# Module-level singleton --------------------------------------------------

_kb_singleton: Optional[PriceKB] = None
_kb_lock = threading.Lock()
# KB 磁盘写入代数（仅在 apply_kb_write 成功后递增；reload 后与 PriceKB.version 对齐）
_kb_disk_mutation_seq: int = 0


def get_kb_disk_mutation_seq() -> int:
    """KB 代数唯一真相源：内存中 PriceKB.version 仅能与此相等（由 get_price_kb 赋值）。"""
    return _kb_disk_mutation_seq


def note_kb_disk_write_success(path: Path | None = None) -> int:
    """标价表已成功落盘后：递增代数并丢弃内存 KB 单例，下一轮 get_price_kb 必重读盘以对齐 version/content_hash/条目。"""
    global _kb_disk_mutation_seq, _kb_singleton
    _ = path  # 调用方传入 kb_path；重载仅以磁盘为准
    _kb_disk_mutation_seq += 1
    with _kb_lock:
        _kb_singleton = None
    return _kb_disk_mutation_seq


def get_price_kb(path: Path | None = None) -> PriceKB:
    global _kb_singleton
    target = path or official_kb_path()
    with _kb_lock:
        if _kb_singleton is not None and path is None:
            return _kb_singleton
        kb = _load_kb_from_xlsx(target)
        kb.version = get_kb_disk_mutation_seq()
        try:
            from embedding import cache_manager as _cm_kb

            kb.content_hash = _cm_kb.compute_file_md5(Path(target).resolve())
        except Exception:
            kb.content_hash = ""
        if path is None:
            _kb_singleton = kb
        return kb


def reset_price_kb() -> None:
    """Clear the cached singleton — useful for tests."""
    global _kb_singleton
    with _kb_lock:
        _kb_singleton = None
    try:
        from embedding.embedding_index import invalidate_embedding_index

        invalidate_embedding_index()
    except Exception:
        pass


# Loading -----------------------------------------------------------------

def _load_kb_from_xlsx(path: Path) -> PriceKB:
    if not path.exists():
        raise FileNotFoundError(f"Price KB not found at {path}")
    file_bytes = path.read_bytes()

    import io
    import zipfile
    archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    shared_strings = read_shared_strings(archive)
    sheets = read_sheet_entries(archive)
    if not sheets:
        raise SheetParseError("Price KB workbook has no sheets.")
    # The KB has a single sheet; if it ever grows multiple, prefer the
    # one whose name contains 询价/材料.
    sheet_name, sheet_xml = sheets[0]
    for name, xml in sheets:
        if "询价" in name or "材料" in name:
            sheet_name, sheet_xml = name, xml
            break
    rows = normalize_rows(parse_sheet_xml_rows(sheet_xml, shared_strings))
    return _rows_to_kb(rows)


def _rows_to_kb(rows: list[list[str]]) -> PriceKB:
    entries: list[KBEntry] = []
    header_seen = False
    for row in rows:
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue
        if not header_seen and _looks_like_header(cells):
            header_seen = True
            continue
        if len(cells) < 2:
            continue
        raw_name = cells[0]
        raw_spec = cells[1] if len(cells) > 1 else ""
        raw_price = cells[2] if len(cells) > 2 else ""
        marker = cells[3] if len(cells) > 3 else ""
        status = cells[4] if len(cells) > 4 else ""
        if not raw_name or not raw_price:
            continue
        if _status_marks_inactive(status):
            continue

        normalised = _normalise_name(raw_name)
        if not normalised:
            continue
        tokens = _tokens_from_text(f"{normalised} {raw_spec}")
        if not tokens:
            continue
        unit_value, unit_unit, price_note = _parse_price(raw_price)
        if unit_value <= 0:
            continue
        entries.append(
            KBEntry(
                raw_name=raw_name,
                raw_spec=raw_spec,
                raw_price=raw_price,
                auto_learned=_is_auto_learn_marker(marker),
                normalised_name=normalised,
                name_tokens=frozenset(tokens),
                unit_price_value=unit_value,
                unit_price_unit=unit_unit,
                price_note=price_note,
            )
        )
    return PriceKB(entries)


def _status_marks_inactive(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return text in {"inactive", "停用", "disabled", "禁用", "pending", "待补充", "待补价", "待确认"}


def _is_auto_learn_marker(value: object) -> bool:
    marker = str(value or "").strip().lower()
    if not marker:
        return False
    return marker in {"kb自增", "kb auto", "kb_auto", "auto_learn", "auto-learn", "auto_quote_sync"} or (
        "kb" in marker and ("自增" in marker or "auto" in marker)
    ) or marker.startswith("auto_")


def _looks_like_header(cells: list[str]) -> bool:
    head = "".join(cells[:3]).lower()
    return ("材料名称" in head or "名称" in head) and ("单价" in head or "价" in head)


def _normalise_name(name: str) -> str:
    text = name.strip()
    # Strip leading "111-05321-000010" / "111-05321-000010/111-20299-000000"
    text = _CODE_PREFIX_PATTERN.sub("", text)
    text = _TRAILING_BRAND_PATTERN.sub("", text)
    return text.strip()


def _tokens_from_text(text: str) -> set[str]:
    if not text:
        return set()
    text = text.lower()
    tokens = set()
    for raw in _TOKENIZE_PATTERN.findall(text):
        if raw in NAME_STOP_TOKENS:
            continue
        if raw.isdigit() and len(raw) > 8:
            # 12-digit material codes don't help fuzzy matching by themselves
            continue
        tokens.add(raw)
    return tokens


def _parse_price(raw: str) -> tuple[float, str, str]:
    text = raw.strip()
    if not text:
        return 0.0, "", ""
    unit_match = _PRICE_UNIT_PATTERN.search(text)
    unit = (unit_match.group(1) if unit_match else "").upper()
    numbers = [float(m.group(0)) for m in _PRICE_NUMERIC_PATTERN.finditer(text)]
    if not numbers:
        return 0.0, "", ""
    primary = numbers[0]
    note = ""
    if len(numbers) > 1:
        note = "/".join(_PRICE_NUMERIC_PATTERN.findall(text))
        if unit:
            note = f"{note}/{unit}"
    return primary, unit, note


_DISTINCTIVE_TOKEN_PATTERN = re.compile(r"^[A-Za-z]{2,}\d*$|^\d+(?:\.\d+)?$")


def _score_entry(query_tokens: set[str], entry: KBEntry, overlap: int, spec: str) -> float:
    """Combine token overlap with a spec bonus to rank candidates."""
    if not query_tokens:
        return 0.0
    union = len(query_tokens | entry.name_tokens)
    jaccard = overlap / union if union else 0.0
    coverage = overlap / len(query_tokens)
    score = 0.65 * jaccard + 0.35 * coverage
    # Distinctive tokens (latin codes like "DCH", "VX21", numeric specs
    # like "210", "3.2") should outweigh common Chinese chars.
    distinctive_matches = sum(
        1
        for token in query_tokens & entry.name_tokens
        if _DISTINCTIVE_TOKEN_PATTERN.match(token)
    )
    if distinctive_matches:
        score += min(0.20, 0.10 * distinctive_matches)
    if spec:
        spec_norm = spec.strip().lower()
        if spec_norm and spec_norm in entry.raw_spec.lower():
            score += 0.10
    return min(score, 1.0)


def _fmt_price_number(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _infer_material_price_unit(
    *,
    name: str = "",
    spec: str = "",
    usage: str = "",
    role: str = "",
) -> str:
    """裸数字单价补全展示/入库单位（与报价引擎用量口径尽量一致）。"""
    blob = " ".join([name, spec, usage, role]).strip()
    low = blob.lower()
    if any(x in blob for x in ("㎡", "平方", "m²", "m2")) or "码²" in blob or "码2" in blob:
        return "元/㎡" if any(x in blob for x in ("㎡", "平方", "m²", "m2")) else "元/码²"
    if role == "拉头" or ("拉头" in blob and "拉链" not in blob):
        return "元/个"
    if role == "拉链" or "拉链" in blob:
        return "元/条"
    if role == "扣具" or any(x in blob for x in ("扣具", "插扣", "日字扣", "D环")):
        return "元/个"
    if role in ("织带", "绳带", "肩带") or any(x in blob for x in ("织带", "绳带", "背带", "坑带")):
        return "元/米"
    if re.search(r"(?<![.\d])(\d+(?:\.\d+)?)\s*码(?!\s*[²2])", blob) or re.search(
        r"/\s*y(?:d)?\b", low
    ):
        return "元/码"
    if "米" in blob or re.search(r"\bm\b", low):
        return "元/米"
    if any(x in blob for x in ("布", "料", "尼龙", "涤纶", "牛津", "帆布", "革", "pu", "pvc")):
        return "元/码"
    return "元/个"


def _slash_token_to_display_unit(token: str, *, name: str = "", spec: str = "", usage: str = "", role: str = "") -> str:
    t = str(token or "").strip().upper()
    if t in {"Y", "YD"}:
        inferred = _infer_material_price_unit(name=name, spec=spec, usage=usage, role=role)
        if inferred in {"元/个", "元/条", "元/米"}:
            return inferred
        return "元/码"
    if t == "M":
        return "元/米"
    if t in {"PCS", "PC", "SET", "HSET", "PAIR"}:
        return "元/个"
    if t == "?":
        return _infer_material_price_unit(name=name, spec=spec, usage=usage, role=role)
    return _infer_material_price_unit(name=name, spec=spec, usage=usage, role=role)


def format_material_unit_price_text(
    price_text: str,
    *,
    name: str = "",
    spec: str = "",
    usage: str = "",
    role: str = "",
) -> str:
    """将价格库/报价行中的裸数字或简写（6.5、0.3/Y）规范为带「元/单位」的展示文本。"""
    text = str(price_text or "").strip()
    if not text or text in {"-", "—", "/"}:
        return text
    if "元" in text and _PRICE_UNIT_PATTERN.search(text):
        return text

    slash_m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*/\s*([A-Za-z?]+)\s*", text)
    if slash_m:
        val = float(slash_m.group(1))
        unit = _slash_token_to_display_unit(
            slash_m.group(2), name=name, spec=spec, usage=usage, role=role
        )
        return f"{_fmt_price_number(val)}{unit}"

    num_m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*", text.replace(",", ""))
    if num_m and not _PRICE_UNIT_PATTERN.search(text):
        val = float(num_m.group(1))
        if val > 0:
            unit = _infer_material_price_unit(name=name, spec=spec, usage=usage, role=role)
            return f"{_fmt_price_number(val)}{unit}"
    return text


def format_kb_entry_price_display(
    entry: KBEntry,
    *,
    role: str = "",
    usage: str = "",
) -> str:
    return format_material_unit_price_text(
        entry.raw_price,
        name=entry.raw_name,
        spec=entry.raw_spec,
        usage=usage,
        role=role,
    )
