"""报价价格自主学习：候选记录 → 统计建议 → 人工批准 → 正式覆盖层（不自动写正式价库）。"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "quotes.db"

_TEST_CONN: sqlite3.Connection | None = None

DEVIATION_THRESHOLD_PCT = 10.0
MIN_SAMPLES_FOR_SUGGESTION = 3
RECENT_RECORD_LIMIT = 20
MAX_AUTO_SUGGEST_ADJUST_PCT = 15.0

LEARNING_CANDIDATE = "candidate"
LEARNING_APPROVED = "approved"
LEARNING_REJECTED = "rejected"
LEARNING_EXCLUDED = "excluded"

SUGGESTION_PENDING = "pending"
SUGGESTION_APPROVED = "approved"
SUGGESTION_REJECTED = "rejected"

DEAL_PENDING = "pending"
DEAL_DEAL = "deal"
DEAL_LOST = "lost"
DEAL_UNKNOWN = "unknown"

SPECIAL_MATERIAL_KEYWORDS = (
    "稀有",
    "定制",
    "特殊",
    "进口真皮",
    "头层牛皮",
    "鳄鱼",
    "碳纤维",
    "限量",
    "样品",
    "打样",
    "高价",
    "限量款",
)

HIGH_UNIT_PRICE_THRESHOLD = 500.0

_PRICE_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _append_learning_audit(event: dict[str, Any]) -> None:
    try:
        from price_kb_paths import auto_learn_log_path

        path = auto_learn_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**event, "logged_at": _utc_now_iso()}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("learning audit log skipped", exc_info=True)


def _connect() -> sqlite3.Connection:
    if _TEST_CONN is not None:
        return _TEST_CONN
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=8.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


def parse_price_number(raw: object) -> float | None:
    text = str(raw or "").strip().replace(",", "")
    if not text or text in {"-", "—", "/"}:
        return None
    m = _PRICE_NUM_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def calc_deviation(system_price: object, manual_price: object) -> tuple[float | None, float | None]:
    sys_n = parse_price_number(system_price)
    man_n = parse_price_number(manual_price)
    if sys_n is None or man_n is None or sys_n <= 0:
        return None, None
    amount = round(man_n - sys_n, 6)
    pct = round((amount / sys_n) * 100.0, 4)
    return amount, pct


def is_special_material(material_name: str, category: str = "") -> bool:
    blob = f"{material_name} {category}".lower()
    return any(k.lower() in blob for k in SPECIAL_MATERIAL_KEYWORDS)


def is_high_unit_price(*prices: object) -> bool:
    for raw in prices:
        val = parse_price_number(raw)
        if val is not None and val >= HIGH_UNIT_PRICE_THRESHOLD:
            return True
    return False


def extract_deal_context(source: dict[str, Any] | None) -> dict[str, str]:
    """从报价保存 body / quote meta 提取成交信息（允许为空）。"""
    src = source if isinstance(source, dict) else {}
    deal_status = str(
        src.get("deal_status")
        or src.get("learning_deal_status")
        or src.get("quote_deal_status")
        or DEAL_UNKNOWN
    ).strip() or DEAL_UNKNOWN
    final_price = str(
        src.get("final_price")
        or src.get("deal_final_price")
        or src.get("learning_final_price")
        or ""
    ).strip()
    loss_reason = str(
        src.get("loss_reason")
        or src.get("deal_loss_reason")
        or src.get("learning_loss_reason")
        or ""
    ).strip()
    if deal_status not in {DEAL_PENDING, DEAL_DEAL, DEAL_LOST, DEAL_UNKNOWN}:
        deal_status = DEAL_UNKNOWN
    return {
        "deal_status": deal_status,
        "final_price": final_price,
        "loss_reason": loss_reason,
    }


def _parse_deal_summary(raw: object) -> dict[str, int]:
    if isinstance(raw, dict):
        return {str(k): int(v or 0) for k, v in raw.items()}
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {str(k): int(v or 0) for k, v in parsed.items()}
    except json.JSONDecodeError:
        pass
    return {}


def _enrich_suggestion_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    mat_key = str(out.get("material_key") or "")
    deal_counts = _parse_deal_summary(out.get("deal_summary"))
    out["deal_stats"] = {
        "deal": deal_counts.get(DEAL_DEAL, 0),
        "lost": deal_counts.get(DEAL_LOST, 0),
        "pending": deal_counts.get(DEAL_PENDING, 0),
        "unknown": deal_counts.get(DEAL_UNKNOWN, 0),
    }
    out["deal_stats_text"] = (
        f"成交 {deal_counts.get(DEAL_DEAL, 0)} / 丢单 {deal_counts.get(DEAL_LOST, 0)} / "
        f"待定 {deal_counts.get(DEAL_PENDING, 0)}"
    )
    ensure_price_learning_tables()
    conn = _connect()
    try:
        seen = conn.execute(
            """
            SELECT MAX(created_at) AS last_seen_at
            FROM quote_price_learning_records
            WHERE material_key = ? AND learning_status = ?
            """,
            (mat_key, LEARNING_CANDIDATE),
        ).fetchone()
        out["last_seen_at"] = str(seen["last_seen_at"] or "") if seen else ""
    finally:
        if _TEST_CONN is None:
            conn.close()
    return out


def _material_key(material_name: str, category: str = "", spec: str = "") -> str:
    parts = [
        str(material_name or "").strip().lower(),
        str(category or "").strip().lower(),
        str(spec or "-").strip().lower() or "-",
    ]
    return "|".join(parts)


def ensure_price_learning_tables() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS quote_price_learning_records (
                record_id TEXT PRIMARY KEY,
                quote_uid TEXT NOT NULL DEFAULT '',
                quote_id TEXT NOT NULL DEFAULT '',
                material_name TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                spec TEXT NOT NULL DEFAULT '-',
                system_price TEXT NOT NULL DEFAULT '',
                manual_price TEXT NOT NULL DEFAULT '',
                deviation_amount REAL,
                deviation_pct REAL,
                correction_reason TEXT NOT NULL DEFAULT '',
                deal_status TEXT NOT NULL DEFAULT 'unknown',
                final_price TEXT NOT NULL DEFAULT '',
                loss_reason TEXT NOT NULL DEFAULT '',
                learning_status TEXT NOT NULL DEFAULT 'candidate',
                material_key TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_qplr_material_key
                ON quote_price_learning_records(material_key, learning_status, created_at);
            CREATE TABLE IF NOT EXISTS quote_price_learning_suggestions (
                suggestion_id TEXT PRIMARY KEY,
                material_name TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                spec TEXT NOT NULL DEFAULT '-',
                material_key TEXT NOT NULL DEFAULT '',
                sample_count INTEGER NOT NULL DEFAULT 0,
                avg_system_price REAL,
                avg_manual_price REAL,
                avg_deviation_pct REAL,
                suggested_direction TEXT NOT NULL DEFAULT '',
                suggested_adjust_pct REAL,
                suggested_price TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT 'low',
                evidence TEXT NOT NULL DEFAULT '',
                risk_note TEXT NOT NULL DEFAULT '',
                deal_summary TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '',
                rule_source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_qpls_status
                ON quote_price_learning_suggestions(status, updated_at);
            """
        )
        conn.commit()
    finally:
        if _TEST_CONN is None:
            conn.close()


def record_price_learning_candidate(
    *,
    quote_uid: str,
    quote_id: str = "",
    material_name: str,
    category: str = "",
    spec: str = "-",
    system_price: str,
    manual_price: str,
    correction_reason: str = "",
    corrected_by: str = "admin",
    deal_status: str = DEAL_UNKNOWN,
    final_price: str = "",
    loss_reason: str = "",
    exclude_learning: bool = False,
    deviation_threshold_pct: float = DEVIATION_THRESHOLD_PCT,
) -> dict[str, Any] | None:
    """人工改价后写入候选学习记录；未超阈值或无改动则跳过。"""
    ensure_price_learning_tables()
    sys_s = str(system_price or "").strip()
    man_s = str(manual_price or "").strip()
    if not sys_s or not man_s or sys_s == man_s:
        return None
    dev_amt, dev_pct = calc_deviation(sys_s, man_s)
    if dev_pct is None or abs(dev_pct) < float(deviation_threshold_pct):
        return None

    status = LEARNING_EXCLUDED if exclude_learning else LEARNING_CANDIDATE
    now = _utc_now_iso()
    record_id = f"plr-{uuid.uuid4().hex[:12]}"
    mat_key = _material_key(material_name, category, spec)
    row = {
        "record_id": record_id,
        "quote_uid": str(quote_uid or "").strip(),
        "quote_id": str(quote_id or "").strip(),
        "material_name": str(material_name or "").strip(),
        "category": str(category or "").strip(),
        "spec": str(spec or "-").strip() or "-",
        "system_price": sys_s,
        "manual_price": man_s,
        "deviation_amount": dev_amt,
        "deviation_pct": dev_pct,
        "correction_reason": str(correction_reason or corrected_by or "").strip(),
        "deal_status": str(deal_status or DEAL_UNKNOWN).strip() or DEAL_UNKNOWN,
        "final_price": str(final_price or "").strip(),
        "loss_reason": str(loss_reason or "").strip(),
        "learning_status": status,
        "material_key": mat_key,
        "created_at": now,
        "updated_at": now,
    }
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO quote_price_learning_records (
                record_id, quote_uid, quote_id, material_name, category, spec,
                system_price, manual_price, deviation_amount, deviation_pct,
                correction_reason, deal_status, final_price, loss_reason,
                learning_status, material_key, created_at, updated_at
            ) VALUES (
                :record_id, :quote_uid, :quote_id, :material_name, :category, :spec,
                :system_price, :manual_price, :deviation_amount, :deviation_pct,
                :correction_reason, :deal_status, :final_price, :loss_reason,
                :learning_status, :material_key, :created_at, :updated_at
            )
            """,
            row,
        )
        conn.commit()
    finally:
        if _TEST_CONN is None:
            conn.close()

    if status == LEARNING_CANDIDATE:
        try:
            refresh_suggestions_for_material_key(mat_key)
        except Exception:
            logger.exception("refresh_suggestions failed material_key=%s", mat_key)
    return row


def _fetch_candidate_records(material_key: str, *, limit: int = RECENT_RECORD_LIMIT) -> list[dict[str, Any]]:
    ensure_price_learning_tables()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM quote_price_learning_records
            WHERE material_key = ? AND learning_status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (material_key, LEARNING_CANDIDATE, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if _TEST_CONN is None:
            conn.close()


def _build_suggestion_from_records(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(records) < MIN_SAMPLES_FOR_SUGGESTION:
        return None
    first = records[0]
    name = str(first.get("material_name") or "").strip()
    category = str(first.get("category") or "").strip()
    spec = str(first.get("spec") or "-").strip() or "-"
    mat_key = str(first.get("material_key") or _material_key(name, category, spec))

    if is_special_material(name, category):
        return None

    pcts: list[float] = []
    sys_vals: list[float] = []
    man_vals: list[float] = []
    deal_counts = {DEAL_DEAL: 0, DEAL_LOST: 0, DEAL_PENDING: 0, DEAL_UNKNOWN: 0}
    for rec in records:
        pct = rec.get("deviation_pct")
        if pct is not None:
            pcts.append(float(pct))
        s = parse_price_number(rec.get("system_price"))
        m = parse_price_number(rec.get("manual_price"))
        if s is not None:
            sys_vals.append(s)
        if m is not None:
            man_vals.append(m)
        ds = str(rec.get("deal_status") or DEAL_UNKNOWN)
        deal_counts[ds] = deal_counts.get(ds, 0) + 1

    if not pcts:
        return None
    avg_pct = round(sum(pcts) / len(pcts), 4)
    if abs(avg_pct) < DEVIATION_THRESHOLD_PCT:
        return None

    avg_sys = round(sum(sys_vals) / len(sys_vals), 4) if sys_vals else None
    avg_man = round(sum(man_vals) / len(man_vals), 4) if man_vals else None
    if is_high_unit_price(avg_sys, avg_man):
        return None
    direction = "上调" if avg_pct > 0 else "下调"
    capped_pct = max(-MAX_AUTO_SUGGEST_ADJUST_PCT, min(MAX_AUTO_SUGGEST_ADJUST_PCT, avg_pct))
    suggested_price = ""
    if avg_sys is not None:
        suggested_price = f"{round(avg_sys * (1 + capped_pct / 100.0), 4)}"

    confidence = "high" if len(records) >= 5 else "medium" if len(records) >= 3 else "low"
    risk = ""
    if len(records) < MIN_SAMPLES_FOR_SUGGESTION:
        risk = "样本不足"
    elif abs(avg_pct) > MAX_AUTO_SUGGEST_ADJUST_PCT:
        risk = f"建议幅度已封顶至 {MAX_AUTO_SUGGEST_ADJUST_PCT}%"
    elif is_special_material(name, category):
        risk = "特殊/稀有材料，仅可人工审核"

    evidence = (
        f"最近 {len(records)} 次人工改价，平均偏差 {avg_pct:+.2f}%；"
        f"系统均价 {avg_sys}，人工均价 {avg_man}；"
        f"成交 {deal_counts.get(DEAL_DEAL, 0)} / 丢单 {deal_counts.get(DEAL_LOST, 0)}"
    )
    now = _utc_now_iso()
    return {
        "suggestion_id": f"pls-{uuid.uuid4().hex[:12]}",
        "material_name": name,
        "category": category,
        "spec": spec,
        "material_key": mat_key,
        "sample_count": len(records),
        "avg_system_price": avg_sys,
        "avg_manual_price": avg_man,
        "avg_deviation_pct": avg_pct,
        "suggested_direction": direction,
        "suggested_adjust_pct": capped_pct,
        "suggested_price": suggested_price,
        "confidence": confidence,
        "evidence": evidence,
        "risk_note": risk,
        "deal_summary": json.dumps(deal_counts, ensure_ascii=False),
        "status": SUGGESTION_PENDING,
        "approved_by": "",
        "approved_at": "",
        "rule_source": "",
        "created_at": now,
        "updated_at": now,
    }


def refresh_suggestions_for_material_key(material_key: str) -> dict[str, Any] | None:
    records = _fetch_candidate_records(material_key)
    suggestion = _build_suggestion_from_records(records)
    ensure_price_learning_tables()
    conn = _connect()
    try:
        existing = conn.execute(
            """
            SELECT suggestion_id, status FROM quote_price_learning_suggestions
            WHERE material_key = ? AND status = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (material_key, SUGGESTION_PENDING),
        ).fetchone()
        if suggestion is None:
            if existing:
                conn.execute(
                    "DELETE FROM quote_price_learning_suggestions WHERE suggestion_id = ?",
                    (str(existing["suggestion_id"]),),
                )
                conn.commit()
            return None
        if existing:
            suggestion["suggestion_id"] = str(existing["suggestion_id"])
            suggestion["created_at"] = _utc_now_iso()
        conn.execute(
            """
            INSERT INTO quote_price_learning_suggestions (
                suggestion_id, material_name, category, spec, material_key,
                sample_count, avg_system_price, avg_manual_price, avg_deviation_pct,
                suggested_direction, suggested_adjust_pct, suggested_price,
                confidence, evidence, risk_note, deal_summary, status,
                approved_by, approved_at, rule_source, created_at, updated_at
            ) VALUES (
                :suggestion_id, :material_name, :category, :spec, :material_key,
                :sample_count, :avg_system_price, :avg_manual_price, :avg_deviation_pct,
                :suggested_direction, :suggested_adjust_pct, :suggested_price,
                :confidence, :evidence, :risk_note, :deal_summary, :status,
                :approved_by, :approved_at, :rule_source, :created_at, :updated_at
            )
            ON CONFLICT(suggestion_id) DO UPDATE SET
                sample_count=excluded.sample_count,
                avg_system_price=excluded.avg_system_price,
                avg_manual_price=excluded.avg_manual_price,
                avg_deviation_pct=excluded.avg_deviation_pct,
                suggested_direction=excluded.suggested_direction,
                suggested_adjust_pct=excluded.suggested_adjust_pct,
                suggested_price=excluded.suggested_price,
                confidence=excluded.confidence,
                evidence=excluded.evidence,
                risk_note=excluded.risk_note,
                deal_summary=excluded.deal_summary,
                updated_at=excluded.updated_at
            """,
            suggestion,
        )
        conn.commit()
        return suggestion
    finally:
        if _TEST_CONN is None:
            conn.close()


def list_learning_records(
    *,
    learning_status: str = "",
    material_key: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    ensure_price_learning_tables()
    clauses = ["1=1"]
    params: list[Any] = []
    if learning_status:
        clauses.append("learning_status = ?")
        params.append(str(learning_status).strip())
    if material_key:
        clauses.append("material_key = ?")
        params.append(str(material_key).strip())
    params.append(int(limit))
    conn = _connect()
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM quote_price_learning_records
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if _TEST_CONN is None:
            conn.close()


def list_learning_suggestions(*, status: str = SUGGESTION_PENDING, limit: int = 100) -> list[dict[str, Any]]:
    ensure_price_learning_tables()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM quote_price_learning_suggestions
            WHERE status = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (str(status or SUGGESTION_PENDING).strip(), int(limit)),
        ).fetchall()
        return [_enrich_suggestion_row(dict(r)) for r in rows]
    finally:
        if _TEST_CONN is None:
            conn.close()


def patch_quote_learning_deal_info(
    quote_uid: str,
    *,
    deal_status: str = "",
    final_price: str = "",
    loss_reason: str = "",
    operator: str = "admin",
) -> dict[str, Any]:
    """补录/更新某报价下全部候选学习记录的成交信息。"""
    q_uid = str(quote_uid or "").strip()
    if not q_uid:
        raise ValueError("quote_uid 不能为空。")
    ctx = extract_deal_context(
        {
            "deal_status": deal_status,
            "final_price": final_price,
            "loss_reason": loss_reason,
        }
    )
    now = _utc_now_iso()
    ensure_price_learning_tables()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            UPDATE quote_price_learning_records
            SET deal_status = ?, final_price = ?, loss_reason = ?, updated_at = ?
            WHERE quote_uid = ? AND learning_status IN (?, ?)
            """,
            (
                ctx["deal_status"],
                ctx["final_price"],
                ctx["loss_reason"],
                now,
                q_uid,
                LEARNING_CANDIDATE,
                LEARNING_APPROVED,
            ),
        )
        conn.commit()
        updated = int(cur.rowcount or 0)
        mat_keys = {
            str(r["material_key"] or "")
            for r in conn.execute(
                """
                SELECT DISTINCT material_key FROM quote_price_learning_records
                WHERE quote_uid = ?
                """,
                (q_uid,),
            ).fetchall()
            if str(r["material_key"] or "")
        }
    finally:
        if _TEST_CONN is None:
            conn.close()
    for key in mat_keys:
        if not key:
            continue
        try:
            refresh_suggestions_for_material_key(key)
        except Exception:
            logger.exception("refresh after deal patch failed key=%s", key)
    _append_learning_audit(
        {
            "action": "patch_quote_learning_deal_info",
            "quote_uid": q_uid,
            "operator": operator,
            **ctx,
            "updated_count": updated,
        }
    )
    return {"ok": True, "quote_uid": q_uid, "updated_count": updated, **ctx}


def patch_learning_record_deal_info(
    record_id: str,
    *,
    deal_status: str = "",
    final_price: str = "",
    loss_reason: str = "",
    operator: str = "admin",
) -> dict[str, Any]:
    """后台单条学习记录补录成交信息。"""
    rid = str(record_id or "").strip()
    if not rid:
        raise ValueError("record_id 不能为空。")
    ctx = extract_deal_context(
        {
            "deal_status": deal_status,
            "final_price": final_price,
            "loss_reason": loss_reason,
        }
    )
    now = _utc_now_iso()
    ensure_price_learning_tables()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT material_key FROM quote_price_learning_records WHERE record_id = ?",
            (rid,),
        ).fetchone()
        if not row:
            raise ValueError("学习记录不存在。")
        conn.execute(
            """
            UPDATE quote_price_learning_records
            SET deal_status = ?, final_price = ?, loss_reason = ?, updated_at = ?
            WHERE record_id = ?
            """,
            (ctx["deal_status"], ctx["final_price"], ctx["loss_reason"], now, rid),
        )
        conn.commit()
        mat_key = str(row["material_key"] or "")
    finally:
        if _TEST_CONN is None:
            conn.close()
    refresh_suggestions_for_material_key(mat_key)
    _append_learning_audit(
        {
            "action": "patch_learning_record_deal_info",
            "record_id": rid,
            "operator": operator,
            **ctx,
        }
    )
    return {"ok": True, "record_id": rid, **ctx}


def _get_suggestion(suggestion_id: str) -> dict[str, Any] | None:
    ensure_price_learning_tables()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM quote_price_learning_suggestions WHERE suggestion_id = ?",
            (str(suggestion_id or "").strip(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        if _TEST_CONN is None:
            conn.close()


def approve_learning_suggestion(
    suggestion_id: str,
    *,
    approved_by: str = "admin",
    final_price: str = "",
) -> dict[str, Any]:
    """主管批准：写入正式价库 + 已确认覆盖层；候选记录标记 approved。"""
    sug = _get_suggestion(suggestion_id)
    if not sug:
        raise ValueError("学习建议不存在。")
    if str(sug.get("status") or "") != SUGGESTION_PENDING:
        raise ValueError("该建议已处理。")
    if is_special_material(str(sug.get("material_name") or ""), str(sug.get("category") or "")):
        raise ValueError("特殊/稀有材料不可自动批准，请人工逐条处理。")
    if int(sug.get("sample_count") or 0) < MIN_SAMPLES_FOR_SUGGESTION:
        raise ValueError(f"样本不足 {MIN_SAMPLES_FOR_SUGGESTION} 条，不能批准。")

    price_text = str(final_price or sug.get("suggested_price") or "").strip()
    if not price_text:
        raise ValueError("批准前需指定单价。")
    name = str(sug.get("material_name") or "").strip()
    spec = str(sug.get("spec") or "-").strip() or "-"
    operator = str(approved_by or "admin").strip() or "admin"
    evidence = str(sug.get("evidence") or "").strip()
    rule_source = "manual_approved_learning"

    from price_admin_store import upsert_confirmed_price_override, upsert_price_entry

    upsert_price_entry(
        {"name": name, "spec": spec, "price": price_text, "status": "active", "updated_by": operator},
        source="manual_approved_learning",
    )
    override_entry = upsert_confirmed_price_override(
        material_name=name,
        spec=spec,
        price=price_text,
        operator=operator,
        source_type=rule_source,
        candidate_id=str(sug.get("suggestion_id") or ""),
        note=evidence,
    )

    now = _utc_now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE quote_price_learning_suggestions
            SET status = ?, approved_by = ?, approved_at = ?, rule_source = ?,
                suggested_price = ?, updated_at = ?
            WHERE suggestion_id = ?
            """,
            (SUGGESTION_APPROVED, operator, now, rule_source, price_text, now, suggestion_id),
        )
        conn.execute(
            """
            UPDATE quote_price_learning_records
            SET learning_status = ?, updated_at = ?
            WHERE material_key = ? AND learning_status = ?
            """,
            (LEARNING_APPROVED, now, str(sug.get("material_key") or ""), LEARNING_CANDIDATE),
        )
        conn.commit()
    finally:
        if _TEST_CONN is None:
            conn.close()

    try:
        from core.knowledge_reload import knowledge_reload_hook

        knowledge_reload_hook()
    except Exception:
        logger.debug("knowledge reload after learning approve skipped", exc_info=True)

    _append_learning_audit(
        {
            "action": "approve_learning_suggestion",
            "suggestion_id": suggestion_id,
            "material_name": name,
            "spec": spec,
            "price": price_text,
            "approved_by": operator,
            "rule_source": rule_source,
            "evidence": evidence,
        }
    )

    return {
        "ok": True,
        "suggestion_id": suggestion_id,
        "approved_by": operator,
        "approved_at": now,
        "rule_source": rule_source,
        "override_id": str(override_entry.get("override_id") or ""),
        "price": price_text,
        "evidence": evidence,
    }


def reject_learning_suggestion(suggestion_id: str, *, operator: str = "admin", reason: str = "") -> dict[str, Any]:
    sug = _get_suggestion(suggestion_id)
    if not sug:
        raise ValueError("学习建议不存在。")
    now = _utc_now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE quote_price_learning_suggestions
            SET status = ?, risk_note = ?, updated_at = ?, approved_by = ?
            WHERE suggestion_id = ?
            """,
            (SUGGESTION_REJECTED, str(reason or "").strip(), now, str(operator or "admin"), suggestion_id),
        )
        conn.execute(
            """
            UPDATE quote_price_learning_records
            SET learning_status = ?, updated_at = ?
            WHERE material_key = ? AND learning_status = ?
            """,
            (LEARNING_REJECTED, now, str(sug.get("material_key") or ""), LEARNING_CANDIDATE),
        )
        conn.commit()
    finally:
        if _TEST_CONN is None:
            conn.close()
    _append_learning_audit(
        {
            "action": "reject_learning_suggestion",
            "suggestion_id": suggestion_id,
            "operator": operator,
            "reason": reason,
            "material_key": str(sug.get("material_key") or ""),
        }
    )
    return {"ok": True, "suggestion_id": suggestion_id, "status": SUGGESTION_REJECTED}


def exclude_learning_record(record_id: str, *, operator: str = "admin") -> dict[str, Any]:
    ensure_price_learning_tables()
    now = _utc_now_iso()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT material_key FROM quote_price_learning_records WHERE record_id = ?",
            (str(record_id or "").strip(),),
        ).fetchone()
        if not row:
            raise ValueError("学习记录不存在。")
        conn.execute(
            """
            UPDATE quote_price_learning_records
            SET learning_status = ?, correction_reason = correction_reason || ?, updated_at = ?
            WHERE record_id = ?
            """,
            (LEARNING_EXCLUDED, f" [excluded by {operator}]", now, record_id),
        )
        conn.commit()
        mat_key = str(row["material_key"] or "")
    finally:
        if _TEST_CONN is None:
            conn.close()
    refresh_suggestions_for_material_key(mat_key)
    return {"ok": True, "record_id": record_id, "learning_status": LEARNING_EXCLUDED}


def capture_unit_price_learning_from_correction(
    *,
    quote_uid: str,
    material_name: str,
    spec: str,
    old_price: str,
    new_price: str,
    quote_id: str = "",
    product_name: str = "",
    corrected_by: str = "admin",
    correction_context: str = "",
    category: str = "",
    exclude_learning: bool = False,
    deal_status: str = DEAL_UNKNOWN,
    final_price: str = "",
    loss_reason: str = "",
) -> dict[str, Any] | None:
    """从 BOM 单价修正接入候选学习（仅展示层学习，不改计价逻辑）。"""
    cat = str(category or product_name or "").strip()
    reason = str(correction_context or "").strip() or f"人工改价 by {corrected_by}"
    return record_price_learning_candidate(
        quote_uid=quote_uid,
        quote_id=quote_id,
        material_name=material_name,
        category=cat,
        spec=spec or "-",
        system_price=old_price,
        manual_price=new_price,
        correction_reason=reason,
        corrected_by=corrected_by,
        deal_status=deal_status,
        final_price=final_price,
        loss_reason=loss_reason,
        exclude_learning=exclude_learning,
    )
