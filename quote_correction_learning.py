"""报价修正反馈闭环：记录人工修正、沉淀规则、推断前查询（SQLite）。"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from material_spec_usage_enricher import (
    ADMIN_SPEC_KEYS,
    ADMIN_USAGE_KEYS,
    RAW_SPEC_KEYS,
    RAW_USAGE_KEYS,
    TIER_ADMIN,
    TIER_MISSING,
    TIER_RAW,
    is_dynamic_rule_usage_token,
    is_explicit_bom_usage_row,
    is_missing_spec_usage_value,
    resolve_spec_from_row,
    resolve_usage_from_row,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "quotes.db"

_TEST_CONN: sqlite3.Connection | None = None

APPLY_CONFIDENCE_MIN = 0.8
SUGGEST_CONFIDENCE_MIN = 0.6

_BAD_USAGE_GROUP_RE = re.compile(r"^\s*1\s*(?:套|组)\s*$|^\s*一\s*组\s*$", re.I)
_BAD_USAGE_PATTERNS = (
    r"^\s*1\s*套\s*$",
    r"^\s*1\s*组\s*$",
    r"^\s*一\s*组\s*$",
    r"^\s*套\s*$",
)
_GROUP_IN_TEXT_RE = re.compile(r"[（(]\s*(?:1\s*组|一组)\s*[)）]|(?:^|[；;])\s*[^；;]*组")
_INTERNAL_PACK_RE = re.compile(
    r"系统估算|系统推断|系统推算|系统近似|AI估算|AI推断|本地兜底|推断待核|推理待核",
    re.I,
)

BUCKLE_MATERIAL_KEYWORDS = (
    "扣具",
    "插扣",
    "d扣",
    "d环",
    "调节扣",
    "梯扣",
    "猪鼻",
    "日字扣",
    "方扣",
    "buckle",
)
BUCKLE_STRUCTURE_KEYWORDS = ("双肩", "两侧", "左右", "侧边", "双扣", "肩带")
SIDE_PIECE_KEYWORDS = ("侧片", "左右片", "双侧")

TRACK_FIELDS = frozenset(
    {
        "name",
        "spec",
        "usage",
        "unit_price",
        "calc_note",
        "calc_method",
        "piece_part",
        "piece_count",
        "quantity",
        "pack",
        "image",
        "pdf_size",
        "pdf_pack",
        "pdf_desc",
    }
)

BOM_ITEM_COMPARE_FIELDS = (
    "name",
    "spec",
    "usage",
    "unit_price",
    "calc_note",
    "calc_method",
    "piece_part",
    "piece_count",
    "quantity",
)

QUOTE_META_COMPARE_FIELDS = (
    ("product_name", "product_name"),
    ("structure_text", "structure_text"),
    ("structure_text_snapshot", "structure_text"),
    ("product_size_text", "product_size_text"),
)


def configure_db(data_dir: Path, db_path: Path) -> None:
    global DATA_DIR, DB_PATH
    DATA_DIR = data_dir
    DB_PATH = db_path


def set_test_connection(conn: sqlite3.Connection | None) -> None:
    global _TEST_CONN
    _TEST_CONN = conn


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect() -> sqlite3.Connection:
    if _TEST_CONN is not None:
        return _TEST_CONN
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=8.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_correction_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quote_correction_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id TEXT NOT NULL UNIQUE,
            quote_uid TEXT NOT NULL,
            quote_id TEXT,
            material_name TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            corrected_by TEXT NOT NULL,
            corrected_at TEXT NOT NULL,
            product_name TEXT,
            structure_text TEXT,
            calc_note TEXT,
            correction_context TEXT,
            can_promote_rule INTEGER NOT NULL DEFAULT 1,
            material_key TEXT,
            old_value_norm TEXT,
            new_value_norm TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qch_promote ON quote_correction_history"
        "(material_key, field_name, old_value_norm, new_value_norm)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qch_quote ON quote_correction_history(quote_uid, corrected_at DESC)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quote_correction_rules (
            rule_id TEXT PRIMARY KEY,
            rule_type TEXT NOT NULL,
            field_name TEXT NOT NULL,
            match_keywords TEXT NOT NULL,
            match_product_keywords TEXT NOT NULL DEFAULT '[]',
            match_structure_keywords TEXT NOT NULL DEFAULT '[]',
            bad_values TEXT NOT NULL DEFAULT '[]',
            corrected_value TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.75,
            source_count INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            affects_calculation INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reason TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qcr_enabled ON quote_correction_rules(enabled, rule_type)"
    )


def init_correction_learning_storage() -> None:
    conn = _connect()
    try:
        ensure_correction_tables(conn)
        conn.commit()
        _seed_builtin_rules(conn)
        conn.commit()
        try:
            from quote_anomaly_learning import ensure_anomaly_tables, _seed_anomaly_builtin_rules

            ensure_anomaly_tables(conn)
            _seed_anomaly_builtin_rules(conn)
            conn.commit()
        except Exception:
            logger.debug("anomaly learning tables seed skipped", exc_info=True)
    finally:
        if _TEST_CONN is None:
            conn.close()


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            return [value.strip()]
    return []


def _norm_value(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _material_category_key(material_name: str) -> str:
    name = str(material_name or "").lower()
    if any(k in name for k in BUCKLE_MATERIAL_KEYWORDS):
        return "buckle"
    if any(k in name for k in SIDE_PIECE_KEYWORDS):
        return "side_piece"
    if "包装" in name or "纸箱" in name or "胶袋" in name:
        return "packaging"
    return "generic"


def _structure_blob(ctx: dict[str, Any]) -> str:
    return str(
        ctx.get("structure_text") or ctx.get("structure_text_snapshot") or ""
    ).strip()


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    blob = str(text or "").lower()
    return any(k.lower() in blob for k in keywords)


def _value_matches_bad(current: str, bad_values: list[str]) -> bool:
    cur = str(current or "").strip()
    if is_missing_spec_usage_value(cur):
        return True
    for pat in bad_values:
        if not pat:
            continue
        if pat.startswith("^") or pat.endswith("$") or "\\" in pat:
            if re.search(pat, cur, re.I):
                return True
        elif cur.lower() == pat.lower():
            return True
    if _BAD_USAGE_GROUP_RE.match(cur):
        return True
    if _INTERNAL_PACK_RE.search(cur):
        return True
    return False


@dataclass
class CorrectionRule:
    rule_id: str
    rule_type: str
    field_name: str
    match_keywords: list[str]
    match_product_keywords: list[str]
    match_structure_keywords: list[str]
    bad_values: list[str]
    corrected_value: str
    confidence: float
    source_count: int
    enabled: bool
    affects_calculation: bool
    reason: str = ""


@dataclass
class RuleApplication:
    rule_id: str
    rule_type: str
    material_name: str
    field_name: str
    old_inferred_value: str
    applied_value: str
    confidence: float
    reason: str
    affects_calculation: bool = True
    mode: str = "applied"  # applied | suggested | rejected


@dataclass
class LearningCaptureResult:
    ok: bool = True
    history_ids: list[str] = field(default_factory=list)
    recorded_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _builtin_rules() -> list[CorrectionRule]:
    return [
        CorrectionRule(
            rule_id="builtin-buckle-dual-qty",
            rule_type="buckle_quantity",
            field_name="usage",
            match_keywords=list(BUCKLE_MATERIAL_KEYWORDS),
            match_product_keywords=[],
            match_structure_keywords=list(BUCKLE_STRUCTURE_KEYWORDS),
            bad_values=list(_BAD_USAGE_PATTERNS) + ["", "-"],
            corrected_value="2个",
            confidence=0.85,
            source_count=1,
            enabled=True,
            affects_calculation=True,
            reason="双肩/两侧场景扣具默认 2 个，禁止 1套/1组",
        ),
        CorrectionRule(
            rule_id="builtin-side-piece-no-group",
            rule_type="side_piece_qty_display",
            field_name="piece_part",
            match_keywords=list(SIDE_PIECE_KEYWORDS),
            match_product_keywords=[],
            match_structure_keywords=[],
            bad_values=[r"组", r"1\s*组", r"一\s*组", r"（1组）", r"（一组）"],
            corrected_value="2片",
            confidence=0.85,
            source_count=1,
            enabled=True,
            affects_calculation=False,
            reason="侧片禁止按组展示，使用 2 片",
        ),
        CorrectionRule(
            rule_id="builtin-customer-pack-sanitize",
            rule_type="customer_pack_display",
            field_name="pack",
            match_keywords=["包装", "纸箱", "胶袋", "pack"],
            match_product_keywords=[],
            match_structure_keywords=[],
            bad_values=[
                r"系统估算",
                r"AI估算",
                r"推断",
                r"估算",
                r"待核",
                r"推理待核",
            ],
            corrected_value="",
            confidence=0.95,
            source_count=1,
            enabled=True,
            affects_calculation=False,
            reason="客户报价单包装列隐藏内部口径",
        ),
        CorrectionRule(
            rule_id="builtin-product-image-filter",
            rule_type="product_image_filter",
            field_name="image",
            match_keywords=["图", "款式", "产品", "image"],
            match_product_keywords=[],
            match_structure_keywords=[],
            bad_values=[r"sheet_embed_untrusted", r"document_screenshot"],
            corrected_value="reject_untrusted",
            confidence=0.95,
            source_count=1,
            enabled=True,
            affects_calculation=False,
            reason="款式图仅接受可信产品图，拒绝表格/说明截图",
        ),
    ]


def _seed_builtin_rules(conn: sqlite3.Connection) -> None:
    now = _utc_now_iso()
    for rule in _builtin_rules():
        conn.execute(
            """
            INSERT INTO quote_correction_rules (
                rule_id, rule_type, field_name, match_keywords, match_product_keywords,
                match_structure_keywords, bad_values, corrected_value, confidence, source_count,
                enabled, affects_calculation, created_at, updated_at, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                rule_type=excluded.rule_type,
                field_name=excluded.field_name,
                match_keywords=excluded.match_keywords,
                match_product_keywords=excluded.match_product_keywords,
                match_structure_keywords=excluded.match_structure_keywords,
                bad_values=excluded.bad_values,
                corrected_value=excluded.corrected_value,
                confidence=excluded.confidence,
                enabled=excluded.enabled,
                affects_calculation=excluded.affects_calculation,
                updated_at=excluded.updated_at,
                reason=excluded.reason
            """,
            (
                rule.rule_id,
                rule.rule_type,
                rule.field_name,
                json.dumps(rule.match_keywords, ensure_ascii=False),
                json.dumps(rule.match_product_keywords, ensure_ascii=False),
                json.dumps(rule.match_structure_keywords, ensure_ascii=False),
                json.dumps(rule.bad_values, ensure_ascii=False),
                rule.corrected_value,
                rule.confidence,
                rule.source_count,
                1 if rule.enabled else 0,
                1 if rule.affects_calculation else 0,
                now,
                now,
                rule.reason,
            ),
        )


def _row_to_rule(row: sqlite3.Row) -> CorrectionRule:
    return CorrectionRule(
        rule_id=str(row["rule_id"]),
        rule_type=str(row["rule_type"]),
        field_name=str(row["field_name"]),
        match_keywords=_json_list(row["match_keywords"]),
        match_product_keywords=_json_list(row["match_product_keywords"]),
        match_structure_keywords=_json_list(row["match_structure_keywords"]),
        bad_values=_json_list(row["bad_values"]),
        corrected_value=str(row["corrected_value"] or ""),
        confidence=float(row["confidence"] or 0.7),
        source_count=int(row["source_count"] or 1),
        enabled=bool(row["enabled"]),
        affects_calculation=bool(row["affects_calculation"]),
        reason=str(row["reason"] or ""),
    )


def load_enabled_rules() -> list[CorrectionRule]:
    init_correction_learning_storage()
    rules: list[CorrectionRule] = []
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM quote_correction_rules WHERE enabled = 1"
            " ORDER BY confidence DESC, source_count DESC"
        ).fetchall()
        for row in rows:
            keys = row.keys() if hasattr(row, "keys") else ()
            status = str(row["rule_status"] or "active") if "rule_status" in keys else "active"
            if status in ("pending_review", "rejected"):
                continue
            rules.append(_row_to_rule(row))
    finally:
        if _TEST_CONN is None:
            conn.close()
    seen = {r.rule_id for r in rules}
    for br in _builtin_rules():
        if br.rule_id not in seen:
            rules.append(br)
    return rules


def record_correction(
    *,
    quote_uid: str,
    material_name: str,
    field_name: str,
    old_value: str,
    new_value: str,
    corrected_by: str,
    quote_id: str = "",
    product_name: str = "",
    structure_text: str = "",
    calc_note: str = "",
    correction_context: str = "",
    can_promote_rule: bool = True,
) -> str:
    field_name = str(field_name or "").strip()
    if field_name not in TRACK_FIELDS:
        return ""
    old_s = str(old_value if old_value is not None else "").strip()
    new_s = str(new_value if new_value is not None else "").strip()
    if old_s == new_s:
        return ""
    init_correction_learning_storage()
    history_id = str(uuid.uuid4())
    material_key = _material_category_key(material_name)
    now = _utc_now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO quote_correction_history (
                history_id, quote_uid, quote_id, material_name, field_name,
                old_value, new_value, corrected_by, corrected_at,
                product_name, structure_text, calc_note, correction_context,
                can_promote_rule, material_key, old_value_norm, new_value_norm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                history_id,
                quote_uid,
                quote_id,
                material_name,
                field_name,
                old_s,
                new_s,
                corrected_by,
                now,
                product_name,
                structure_text[:2000],
                calc_note[:500],
                correction_context[:500],
                1 if can_promote_rule else 0,
                material_key,
                _norm_value(old_s),
                _norm_value(new_s),
            ),
        )
        conn.commit()
        if can_promote_rule:
            _maybe_promote_rule(conn, material_key, field_name, old_s, new_s, material_name)
            conn.commit()
    finally:
        if _TEST_CONN is None:
            conn.close()
    return history_id


def _maybe_promote_rule(
    conn: sqlite3.Connection,
    material_key: str,
    field_name: str,
    old_value: str,
    new_value: str,
    material_name: str,
) -> None:
    if field_name not in TRACK_FIELDS:
        return
    old_n = _norm_value(old_value)
    new_n = _norm_value(new_value)
    if not new_n and field_name not in ("pack", "image"):
        return
    cnt = conn.execute(
        """
        SELECT COUNT(*) AS c FROM quote_correction_history
        WHERE material_key = ? AND field_name = ? AND old_value_norm = ? AND new_value_norm = ?
        """,
        (material_key, field_name, old_n, new_n),
    ).fetchone()
    if not cnt or int(cnt["c"] or 0) < 2:
        return
    rule_id = f"learned-{material_key}-{field_name}-{old_n}-{new_n}"[:120]
    keywords = [material_name[:40]] if material_name else []
    if material_key == "buckle":
        keywords = list(BUCKLE_MATERIAL_KEYWORDS[:6])
    elif material_key == "side_piece":
        keywords = list(SIDE_PIECE_KEYWORDS)
    bad_json = json.dumps([old_value] if old_value else list(_BAD_USAGE_PATTERNS), ensure_ascii=False)
    affects = 1 if field_name in ("usage", "quantity", "piece_count") else 0
    now = _utc_now_iso()
    conn.execute(
        """
        INSERT INTO quote_correction_rules (
            rule_id, rule_type, field_name, match_keywords, match_product_keywords,
            match_structure_keywords, bad_values, corrected_value, confidence, source_count,
            enabled, affects_calculation, created_at, updated_at, reason
        ) VALUES (?, ?, ?, ?, '[]', '[]', ?, ?, ?, ?, 1, ?, ?, ?, ?)
        ON CONFLICT(rule_id) DO UPDATE SET
            source_count = source_count + 1,
            confidence = MIN(0.95, confidence + 0.05),
            updated_at = excluded.updated_at
        """,
        (
            rule_id,
            f"learned_{material_key}",
            field_name,
            json.dumps(keywords, ensure_ascii=False),
            bad_json,
            new_value,
            0.75,
            int(cnt["c"]),
            affects,
            now,
            now,
            f"同类人工修正累计 {cnt['c']} 次",
        ),
    )


def _has_admin_field(row: dict[str, Any], field_name: str) -> bool:
    key_map = {
        "usage": ADMIN_USAGE_KEYS,
        "spec": ADMIN_SPEC_KEYS,
    }
    for key in key_map.get(field_name, ()):
        val = str(row.get(key) or "").strip()
        if val and not is_missing_spec_usage_value(val):
            return True
    admin_key = f"admin_corrected_{field_name}"
    val = str(row.get(admin_key) or row.get(f"corrected_{field_name}") or "").strip()
    return bool(val and not is_missing_spec_usage_value(val))


def _has_trusted_raw_field(row: dict[str, Any], field_name: str, rule: CorrectionRule) -> bool:
    key_map = {
        "usage": RAW_USAGE_KEYS,
        "spec": RAW_SPEC_KEYS,
    }
    for key in key_map.get(field_name, ()):
        val = str(row.get(key) or "").strip()
        if not val or is_missing_spec_usage_value(val):
            continue
        if _value_matches_bad(val, rule.bad_values):
            continue
        return True
    return False


def _rule_matches_row(rule: CorrectionRule, row: dict[str, Any], ctx: dict[str, Any]) -> bool:
    if rule.field_name in ("pack", "image", "pdf_size", "pdf_pack"):
        return True
    name = str(row.get("name") or ctx.get("material_name") or "报价单")
    if rule.field_name == "piece_part":
        name = f"{name} {row.get('piece_part') or ''}"
    if rule.match_keywords and not _matches_keywords(name, rule.match_keywords):
        if rule.field_name not in ("pack", "image"):
            return False
    st = _structure_blob(ctx)
    pn = str(ctx.get("product_name") or "")
    if rule.match_structure_keywords and not _matches_keywords(st, rule.match_structure_keywords):
        return False
    if rule.match_product_keywords and not _matches_keywords(pn, rule.match_product_keywords):
        return False
    return True


def _current_field_value(row: dict[str, Any], field_name: str) -> str:
    if field_name == "usage":
        return str(row.get("usage") or resolve_usage_from_row(row).value or "")
    if field_name == "spec":
        return str(row.get("spec") or "")
    if field_name == "piece_part":
        return str(row.get("piece_part") or "")
    if field_name == "pack":
        return str(row.get("pack") or "")
    return str(row.get(field_name) or "")


def _append_hits(row: dict[str, Any], hits: list[RuleApplication]) -> None:
    if not hits:
        return
    existing = list(row.get("_correction_rule_hits") or [])
    row["_correction_rule_hits"] = existing + [asdict(h) for h in hits]


def _make_app(
    rule: CorrectionRule,
    *,
    material_name: str,
    field_name: str,
    old_val: str,
    applied: str,
    mode: str,
) -> RuleApplication:
    return RuleApplication(
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        material_name=material_name,
        field_name=field_name,
        old_inferred_value=old_val,
        applied_value=applied,
        confidence=rule.confidence,
        reason=rule.reason or rule.rule_type,
        affects_calculation=rule.affects_calculation,
        mode=mode,
    )


def _is_special_usage_rule(rule: CorrectionRule) -> bool:
    if rule.rule_type in ("fabric_lining_shared_area",):
        return True
    return is_dynamic_rule_usage_token(rule.corrected_value)


def _may_apply_usage_rule(row: dict[str, Any], rule: CorrectionRule) -> bool:
    if _is_special_usage_rule(rule):
        return False
    if _has_admin_field(row, "usage"):
        return False
    if is_explicit_bom_usage_row(row):
        return False
    if _has_trusted_raw_field(row, "usage", rule):
        return False
    usage_res = resolve_usage_from_row(row)
    if usage_res.tier == TIER_ADMIN:
        return False
    if usage_res.tier == TIER_RAW and usage_res.value and not _value_matches_bad(
        usage_res.value, rule.bad_values
    ):
        return False
    cur = _current_field_value(row, "usage")
    if not _value_matches_bad(cur, rule.bad_values) and usage_res.tier not in (TIER_MISSING,):
        if usage_res.tier != TIER_RAW or not cur:
            return False
    return True


def _apply_usage_rule(
    row: dict[str, Any],
    rule: CorrectionRule,
    ctx: dict[str, Any],
) -> RuleApplication | None:
    if not _may_apply_usage_rule(row, rule):
        return None
    if not rule.corrected_value or is_dynamic_rule_usage_token(rule.corrected_value):
        return None
    old_val = _current_field_value(row, "usage")
    mode = "applied" if rule.confidence >= APPLY_CONFIDENCE_MIN else "suggested"
    if mode == "applied":
        row["usage"] = rule.corrected_value
        if rule.affects_calculation:
            row["correction_rule_id"] = rule.rule_id
            row["correction_rule_source"] = "correction_rule"
            row["_correction_rule_applied"] = True
    else:
        row["_correction_rule_suggested_usage"] = rule.corrected_value
        row.setdefault("_correction_rule_suggest_reason", rule.reason)
    return _make_app(rule, material_name=str(row.get("name") or ""), field_name="usage", old_val=old_val, applied=rule.corrected_value, mode=mode)


def _sanitize_piece_part_text(text: str, rule: CorrectionRule) -> str:
    t = str(text or "").strip()
    if not t:
        return t
    t = re.sub(r"[（(]\s*(?:1\s*组|一组)\s*[)）]", "", t)
    t = re.sub(r"\s*组\s*", "", t)
    if _value_matches_bad(t, rule.bad_values) or "组" in t:
        if rule.confidence >= APPLY_CONFIDENCE_MIN and rule.corrected_value:
            if any(k in t for k in SIDE_PIECE_KEYWORDS):
                if "2片" not in t and "（2片）" not in t:
                    t = re.sub(r"侧片([^（；;]*)", r"侧片（2片）\1", t, count=1) if "侧片" in t else t
                    if t == text.strip():
                        t = f"侧片（2片） {rule.corrected_value}".strip()
            elif rule.corrected_value:
                t = rule.corrected_value
        elif rule.confidence >= SUGGEST_CONFIDENCE_MIN:
            return t + "（待核）" if "待核" not in t else t
    return t.strip("；; ")


def _apply_piece_part_rule(row: dict[str, Any], rule: CorrectionRule) -> RuleApplication | None:
    if _has_admin_field(row, "piece_part"):
        return None
    cur = _current_field_value(row, "piece_part")
    if not cur and not any(k in str(row.get("name") or "") for k in SIDE_PIECE_KEYWORDS):
        return None
    if not _value_matches_bad(cur, rule.bad_values) and "组" not in cur:
        return None
    new_val = _sanitize_piece_part_text(cur, rule)
    mode = "applied" if rule.confidence >= APPLY_CONFIDENCE_MIN else "suggested"
    if mode == "applied" and new_val != cur:
        row["piece_part"] = new_val
    elif mode == "suggested":
        row["_correction_rule_suggested_piece_part"] = new_val or rule.corrected_value or "待核"
    else:
        return None
    return _make_app(
        rule,
        material_name=str(row.get("name") or ""),
        field_name="piece_part",
        old_val=cur,
        applied=new_val or rule.corrected_value,
        mode=mode,
    )


def apply_customer_pack_text(
    text: str,
    ctx: dict[str, Any] | None = None,
    *,
    rules: list[CorrectionRule] | None = None,
) -> tuple[str, list[RuleApplication]]:
    """客户报价单包装：走规则库清洗并返回命中。"""
    ctx = ctx if isinstance(ctx, dict) else {}
    rules = rules if rules is not None else load_enabled_rules()
    raw = str(text or "").strip()
    if not raw:
        return "", []
    hits: list[RuleApplication] = []
    for rule in rules:
        if rule.field_name != "pack" or not rule.enabled:
            continue
        if not _rule_matches_row(rule, {}, ctx):
            continue
        from quote_sheet_prefill import sanitize_customer_pack_display

        new_text = sanitize_customer_pack_display(raw)
        mode = "applied" if rule.confidence >= APPLY_CONFIDENCE_MIN else "suggested"
        hits.append(
            _make_app(
                rule,
                material_name=str(ctx.get("product_name") or "包装"),
                field_name="pack",
                old_val=raw,
                applied=new_text,
                mode=mode,
            )
        )
        if mode == "applied":
            return new_text, hits
        return sanitize_customer_pack_display(raw), hits
    from quote_sheet_prefill import sanitize_customer_pack_display

    return sanitize_customer_pack_display(raw), hits


def evaluate_product_image_item(
    item: dict[str, Any],
    ctx: dict[str, Any] | None = None,
    *,
    rules: list[CorrectionRule] | None = None,
) -> tuple[bool, list[RuleApplication]]:
    """可信产品图判定 + 规则命中（拒绝时 mode=rejected）。"""
    from quote_sheet_content import is_trusted_quote_sheet_image_item

    ctx = ctx if isinstance(ctx, dict) else {}
    rules = rules if rules is not None else load_enabled_rules()
    if not isinstance(item, dict):
        return False, []
    trusted = is_trusted_quote_sheet_image_item(item)
    hits: list[RuleApplication] = []
    for rule in rules:
        if rule.field_name != "image" or not rule.enabled:
            continue
        if not _rule_matches_row(rule, {}, ctx):
            continue
        reason_detail = "trusted_product_style"
        if item.get("from_sheet_embed") and not item.get("image_role"):
            reason_detail = "sheet_embed_untrusted"
        elif not trusted:
            reason_detail = "document_screenshot_or_untrusted"
        mode = "applied" if trusted else "rejected"
        hits.append(
            _make_app(
                rule,
                material_name=str(ctx.get("product_name") or "款式图"),
                field_name="image",
                old_val=reason_detail,
                applied="accept" if trusted else "reject_untrusted",
                mode=mode,
            )
        )
        break
    return trusted, hits


def apply_correction_rules_to_row(
    row: dict[str, Any],
    ctx: dict[str, Any],
    *,
    rules: list[CorrectionRule] | None = None,
) -> tuple[dict[str, Any], list[RuleApplication]]:
    if not isinstance(row, dict):
        return row, []
    rules = rules if rules is not None else load_enabled_rules()
    hits: list[RuleApplication] = []
    applied_fields: set[str] = set()

    for rule in rules:
        if not rule.enabled:
            continue
        if rule.rule_type in ("fabric_lining_shared_area",):
            continue
        fn = rule.field_name
        if fn in applied_fields:
            continue
        if fn == "usage":
            if not _rule_matches_row(rule, row, ctx):
                continue
            app = _apply_usage_rule(row, rule, ctx)
            if app:
                hits.append(app)
                applied_fields.add("usage")
        elif fn == "piece_part":
            if not _rule_matches_row(rule, row, ctx):
                continue
            app = _apply_piece_part_rule(row, rule)
            if app:
                hits.append(app)
                applied_fields.add("piece_part")

    _append_hits(row, hits)
    return row, hits


def apply_learning_rules_to_quote(quote_obj: dict[str, Any]) -> list[RuleApplication]:
    """对报价结果/detail_rows 应用展示类规则并收集命中。"""
    if not isinstance(quote_obj, dict):
        return []
    ctx = {
        "structure_text": quote_obj.get("structure_text_snapshot") or quote_obj.get("structure_text"),
        "product_name": quote_obj.get("product_name"),
    }
    rules = load_enabled_rules()
    all_hits: list[RuleApplication] = []
    for raw in quote_obj.get("detail_rows") or []:
        if isinstance(raw, dict):
            _, hits = apply_correction_rules_to_row(raw, ctx, rules=rules)
            all_hits.extend(hits)
    pack_raw = ""
    for raw in quote_obj.get("detail_rows") or []:
        if isinstance(raw, dict) and "包装" in str(raw.get("name") or ""):
            pack_raw = str(raw.get("usage") or raw.get("spec") or "")
            break
    from quote_sheet_prefill import sanitize_customer_pack_display

    pack_new = sanitize_customer_pack_display(pack_raw)
    _, pack_hits = apply_customer_pack_text(pack_raw, ctx, rules=rules)
    all_hits.extend(pack_hits)
    if pack_hits:
        quote_obj["_quote_sheet_pack_display"] = pack_new
    if all_hits:
        quote_obj["correction_rule_applications"] = [asdict(h) for h in all_hits]
    return all_hits


def apply_correction_rules_to_items(
    items: list[Any],
    ctx: dict[str, Any],
    *,
    rules: list[CorrectionRule] | None = None,
) -> list[RuleApplication]:
    rules = rules if rules is not None else load_enabled_rules()
    all_hits: list[RuleApplication] = []
    if not isinstance(items, list):
        return all_hits
    for raw in items:
        if not isinstance(raw, dict):
            continue
        _, hits = apply_correction_rules_to_row(raw, ctx, rules=rules)
        all_hits.extend(hits)
    return all_hits


def apply_correction_rules_to_payload(payload: dict[str, Any]) -> list[RuleApplication]:
    if not isinstance(payload, dict):
        return []
    from material_spec_usage_enricher import (
        purge_dynamic_usage_placeholders,
        stamp_trusted_bom_source_fields,
    )

    stamp_trusted_bom_source_fields(payload.get("items"))
    ctx = {
        "structure_text": payload.get("structure_text_snapshot") or payload.get("structure_text"),
        "product_name": payload.get("product_name"),
    }
    items = payload.get("items")
    hits = apply_correction_rules_to_items(items if isinstance(items, list) else [], ctx)
    purge_dynamic_usage_placeholders(items if isinstance(items, list) else [])
    if hits:
        payload["correction_rule_applications"] = [asdict(h) for h in hits]
    return hits


def _compare_field(
    *,
    quote_uid: str,
    material_name: str,
    field_name: str,
    old_v: str,
    new_v: str,
    corrected_by: str,
    quote_id: str,
    product_name: str,
    structure_text: str,
    calc_note: str,
    context: str,
    can_promote: bool,
    result: LearningCaptureResult,
    spec: str = "",
) -> None:
    if old_v == new_v:
        return
    try:
        hid = record_correction(
            quote_uid=quote_uid,
            material_name=material_name,
            field_name=field_name,
            old_value=old_v,
            new_value=new_v,
            corrected_by=corrected_by,
            quote_id=quote_id,
            product_name=product_name,
            structure_text=structure_text,
            calc_note=calc_note,
            correction_context=context,
            can_promote_rule=can_promote,
        )
        if hid:
            result.history_ids.append(hid)
            result.recorded_count += 1
            if (
                corrected_by == "admin"
                and field_name == "unit_price"
                and str(new_v or "").strip()
            ):
                try:
                    from price_admin_store import enqueue_price_learn_candidate

                    enqueue_price_learn_candidate(
                        material_name=material_name,
                        spec=str(spec or "-").strip() or "-",
                        old_price=old_v,
                        new_price=new_v,
                        source_type="admin_correction",
                        quote_id=quote_id,
                        product_name=product_name,
                        operator=corrected_by,
                        note=f"管理员修正单价（{context}）",
                        raw_context={
                            "quote_uid": quote_uid,
                            "field_name": field_name,
                            "correction_context": context,
                        },
                    )
                except Exception:
                    logger.debug("price learn candidate enqueue skipped", exc_info=True)
            if (
                can_promote
                and corrected_by == "admin"
                and field_name == "usage"
                and old_v != new_v
            ):
                try:
                    from quote_anomaly_learning import link_admin_correction_to_anomaly_promotion

                    link_admin_correction_to_anomaly_promotion(
                        quote_uid, material_name, field_name, old_v, new_v
                    )
                except Exception:
                    logger.debug("anomaly promotion after admin edit skipped", exc_info=True)
    except Exception as exc:
        msg = f"记录修正失败 {field_name}: {exc}"
        logger.exception("quote_correction_history write failed quote_uid=%s field=%s", quote_uid, field_name)
        result.errors.append(msg)
        result.ok = False


def capture_bom_edit_corrections(
    quote_uid: str,
    *,
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    quote: dict[str, Any] | None = None,
    old_quote: dict[str, Any] | None = None,
    new_product: dict[str, Any] | None = None,
    corrected_by: str = "admin",
) -> LearningCaptureResult:
    """对比 BOM / 产品元数据保存前后，写入修正历史。"""
    result = LearningCaptureResult()
    q = quote if isinstance(quote, dict) else {}
    oq = old_quote if isinstance(old_quote, dict) else {}
    st = str(q.get("structure_text_snapshot") or q.get("structure_text") or "")
    pn = str(q.get("product_name") or "")
    qid = str(q.get("quote_id") or "")

    old_map: dict[int, dict[str, Any]] = {}
    for i, row in enumerate(old_items or [], start=1):
        if isinstance(row, dict):
            old_map[i] = row

    for i, new_row in enumerate(new_items or [], start=1):
        if not isinstance(new_row, dict):
            continue
        old_row = old_map.get(i) or {}
        name = str(new_row.get("name") or old_row.get("name") or "").strip() or f"行{i}"
        calc_note = str(new_row.get("calc_note") or new_row.get("calc_method") or "")
        row_spec = str(new_row.get("spec") or old_row.get("spec") or "").strip() or "-"
        for field in BOM_ITEM_COMPARE_FIELDS:
            old_v = str(old_row.get(field) or "").strip()
            new_v = str(new_row.get(field) or "").strip()
            _compare_field(
                quote_uid=quote_uid,
                material_name=name,
                field_name=field,
                old_v=old_v,
                new_v=new_v,
                corrected_by=corrected_by,
                quote_id=qid,
                product_name=pn,
                structure_text=st,
                calc_note=calc_note,
                context="admin_bom_edit",
                can_promote=field in ("usage", "spec", "piece_part", "unit_price", "piece_count"),
                result=result,
                spec=row_spec,
            )

    old_dr = {str(r.get("name") or ""): r for r in (oq.get("detail_rows") or []) if isinstance(r, dict)}
    for new_row in new_items or []:
        if not isinstance(new_row, dict):
            continue
        name = str(new_row.get("name") or "").strip()
        if not name:
            continue
        old_dr_row = old_dr.get(name) or {}
        old_pp = str(old_dr_row.get("piece_part") or "").strip()
        new_pp = str(new_row.get("piece_part") or "").strip()
        if old_pp != new_pp and (old_pp or new_pp):
            _compare_field(
                quote_uid=quote_uid,
                material_name=name,
                field_name="piece_part",
                old_v=old_pp,
                new_v=new_pp,
                corrected_by=corrected_by,
                quote_id=qid,
                product_name=pn,
                structure_text=st,
                calc_note="",
                context="admin_bom_edit_detail_piece_part",
                can_promote=True,
                result=result,
            )

    prod = new_product if isinstance(new_product, dict) else {}
    for new_key, old_key in QUOTE_META_COMPARE_FIELDS:
        old_v = str(oq.get(old_key) or "").strip()
        new_v = str(prod.get(new_key) or q.get(new_key) or "").strip()
        _compare_field(
            quote_uid=quote_uid,
            material_name="[产品信息]",
            field_name=new_key if new_key != "structure_text_snapshot" else "structure_text",
            old_v=old_v,
            new_v=new_v,
            corrected_by=corrected_by,
            quote_id=qid,
            product_name=pn,
            structure_text=st,
            calc_note="",
            context="admin_bom_edit_product_meta",
            can_promote=False,
            result=result,
        )

    if result.errors:
        result.warnings.append("部分修正历史写入失败，请查看日志")
    return result


def capture_learning_from_bom_save(
    quote_uid: str,
    *,
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    quote: dict[str, Any] | None = None,
    old_quote: dict[str, Any] | None = None,
    new_product: dict[str, Any] | None = None,
    corrected_by: str = "admin",
) -> LearningCaptureResult:
    try:
        return capture_bom_edit_corrections(
            quote_uid,
            old_items=old_items,
            new_items=new_items,
            quote=quote,
            old_quote=old_quote,
            new_product=new_product,
            corrected_by=corrected_by,
        )
    except Exception as exc:
        logger.exception("capture_learning_from_bom_save failed quote_uid=%s", quote_uid)
        return LearningCaptureResult(
            ok=False,
            errors=[str(exc)],
            warnings=["修正历史记录异常，已记入日志"],
        )


def format_rule_notice_lines(applications: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for app in applications:
        if not isinstance(app, dict):
            continue
        rid = str(app.get("rule_id") or "")
        mat = str(app.get("material_name") or "")
        applied = str(app.get("applied_value") or "")
        reason = str(app.get("reason") or "")
        mode = str(app.get("mode") or "applied")
        if not rid:
            continue
        if mode == "rejected":
            lines.append(f"历史规则（{rid}）：{mat} 图片未通过可信校验（{applied}）。")
            continue
        if mode == "suggested":
            lines.append(f"历史规则建议（{rid}）：{mat} 建议 {applied}，待人工确认。{reason}")
            continue
        if applied:
            lines.append(
                f"已参考历史修正规则（{rid}）：{mat} 按 {applied} 处理，可人工覆盖。{reason}"
            )
    return lines


# 兼容旧调用
def sanitize_customer_pack_via_rules(text: str, ctx: dict[str, Any] | None = None) -> str:
    out, _ = apply_customer_pack_text(text, ctx)
    return out


def customer_image_allowed(item: dict[str, Any], ctx: dict[str, Any] | None = None) -> bool:
    ok, _ = evaluate_product_image_item(item, ctx)
    return ok
