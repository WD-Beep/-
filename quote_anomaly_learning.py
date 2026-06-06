"""报价异常自动检测、记录与候选规则晋升（不写入外部价格知识库 xlsx）。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from material_spec_usage_enricher import is_missing_spec_usage_value
from quote_correction_learning import (
    APPLY_CONFIDENCE_MIN,
    RuleApplication,
    _append_hits,
    _connect,
    _has_admin_field,
    _has_trusted_raw_field,
    _json_list,
    _make_app,
    _row_to_rule,
    _utc_now_iso,
    ensure_correction_tables,
    init_correction_learning_storage,
    load_enabled_rules,
    record_correction,
)
from quote_correction_learning import CorrectionRule  # noqa: E402 — same package layer

logger = logging.getLogger(__name__)

FABRIC_LINING_MAX_REL_GAP = 0.30
_M2_USAGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*㎡", re.I)
_CM_ONLY_USAGE_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)\s*(?:/\s*[^㎡]+)?\s*$",
    re.I,
)
_LINING_RATIO_NOTE_RE = re.compile(r"里布占比|×\s*里布占比|LINING_SHELL|×\s*0\.22", re.I)
_FIXED_LOW_LINING_M2_RE = re.compile(r"^0\.2[0-5]\s*㎡$", re.I)
_INTERNAL_DISPLAY_RE = re.compile(
    r"系统估算|系统推断|系统推算|AI估算|AI推断|推断待核|推理待核|本地兜底",
    re.I,
)

HIGH_CERTAINTY_ANOMALY_TYPES = frozenset(
    {
        "customer_pack_internal_label",
        "product_image_untrusted",
        "fabric_lining_usage_gap",
        "lining_ratio_in_calc_note",
        "fixed_low_lining_m2",
        "main_bom_vs_piece_area_gap",
    }
)

AUTO_PROMOTE_MIN_OCCURRENCES = 2


@dataclass
class DetectedAnomaly:
    anomaly_type: str
    material_name: str
    field_name: str
    old_value: str
    expected_value: str
    reason: str
    confidence: float
    can_promote_to_rule: bool = True
    related_material: str = ""
    calc_note: str = ""


@dataclass
class AnomalyScanResult:
    ok: bool = True
    quote_uid: str = ""
    detected: list[DetectedAnomaly] = field(default_factory=list)
    recorded_ids: list[str] = field(default_factory=list)
    candidate_rules: list[str] = field(default_factory=list)
    promoted_rules: list[str] = field(default_factory=list)
    auto_fixes: list[RuleApplication] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "quote_uid": self.quote_uid,
            "detected_count": len(self.detected),
            "recorded_ids": self.recorded_ids,
            "candidate_rules": self.candidate_rules,
            "promoted_rules": self.promoted_rules,
            "auto_fixes": [asdict(a) for a in self.auto_fixes],
            "warnings": self.warnings,
            "anomalies": [asdict(a) for a in self.detected],
        }


def ensure_anomaly_tables(conn) -> None:
    ensure_correction_tables(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quote_anomaly_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anomaly_id TEXT NOT NULL UNIQUE,
            quote_uid TEXT NOT NULL,
            quote_id TEXT,
            product_name TEXT,
            material_name TEXT NOT NULL,
            related_material TEXT,
            field_name TEXT NOT NULL,
            old_value TEXT,
            expected_value TEXT,
            structure_text TEXT,
            piece_area_calculation TEXT,
            calc_note TEXT,
            reason TEXT NOT NULL,
            anomaly_type TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            confidence REAL NOT NULL,
            can_promote_to_rule INTEGER NOT NULL DEFAULT 1,
            signature TEXT NOT NULL,
            promoted_rule_id TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qah_sig ON quote_anomaly_history(signature, detected_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qah_quote ON quote_anomaly_history(quote_uid, detected_at DESC)"
    )
    for col_sql in (
        "ALTER TABLE quote_correction_rules ADD COLUMN rule_status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE quote_correction_rules ADD COLUMN auto_learned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE quote_correction_rules ADD COLUMN anomaly_type TEXT",
    ):
        try:
            conn.execute(col_sql)
        except Exception:
            pass


def _init_storage() -> None:
    init_correction_learning_storage()
    conn = _connect()
    try:
        ensure_anomaly_tables(conn)
        conn.commit()
        _seed_anomaly_builtin_rules(conn)
        conn.commit()
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()


def _seed_anomaly_builtin_rules(conn) -> None:
    now = _utc_now_iso()
    rules = [
        (
            "builtin-fabric-lining-shared-area",
            "fabric_lining_shared_area",
            "usage",
            json.dumps(["里布", "里料", "内里", "内衬", "涤纶"], ensure_ascii=False),
            "[]",
            "[]",
            json.dumps([r"里布占比", r"×\s*0\.22", r"^0\.2[0-5]\s*㎡$"], ensure_ascii=False),
            "__SHARED_BODY_M2__",
            0.92,
            1,
            1,
            1,
            "active",
            0,
            "fabric_lining_usage_gap",
            "同裁片集合下全包里布与主料共用裁片/外包络面积基准，禁止里布占比压低",
        ),
    ]
    for row in rules:
        conn.execute(
            """
            INSERT INTO quote_correction_rules (
                rule_id, rule_type, field_name, match_keywords, match_product_keywords,
                match_structure_keywords, bad_values, corrected_value, confidence, source_count,
                enabled, affects_calculation, created_at, updated_at, reason,
                rule_status, auto_learned, anomaly_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                rule_type=excluded.rule_type,
                confidence=excluded.confidence,
                enabled=excluded.enabled,
                reason=excluded.reason,
                rule_status=excluded.rule_status,
                anomaly_type=excluded.anomaly_type,
                updated_at=excluded.updated_at
            """,
            (*row, now, now),
        )


def _parse_m2(usage: str) -> float | None:
    m = _M2_USAGE_RE.search(str(usage or ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _usage_rel_gap(a: float, b: float) -> float:
    return abs(a - b) / max(max(a, b), 1e-6)


def _explicit_bom_m2(row: dict[str, Any]) -> float | None:
    from material_spec_usage_enricher import is_explicit_bom_usage_row

    if not is_explicit_bom_usage_row(row):
        return None
    return _parse_m2(str(row.get("usage") or ""))


def _quote_body_area_context(
    quote_obj: dict[str, Any],
) -> tuple[float, str, str, float | None] | None:
    """有尺寸时返回 (body_m2, target_usage_str, basis_note, shell_ref)。"""
    from structure_usage import (
        _body_area_basis_note,
        _dims_lwh_cm,
        _format_usage,
        _has_box_dims,
        _merge_product_size,
        _resolve_piece_area_calculation,
        _shared_body_fabric_area_m2,
    )

    rows = _quote_rows(quote_obj)
    st = str(
        quote_obj.get("structure_text_snapshot") or quote_obj.get("structure_text") or ""
    )
    ps = _merge_product_size(
        quote_obj.get("product_size") if isinstance(quote_obj.get("product_size"), dict) else {},
        st,
    )
    if not _has_box_dims(ps):
        return None
    l_, w_, h_ = _dims_lwh_cm(ps)
    piece_calc = _resolve_piece_area_calculation(
        quote_obj.get("piece_area_calculation")
        if isinstance(quote_obj.get("piece_area_calculation"), dict)
        else None,
        product_size=ps,
        structure_text=st,
        items=rows,
    )
    body_m2, basis, shell_ref = _shared_body_fabric_area_m2(l_, w_, h_, piece_calc)
    target = _format_usage(body_m2, "㎡")
    basis_note = _body_area_basis_note(body_m2, basis, shell_ref, l_, w_, h_)
    return body_m2, target, basis_note, shell_ref


def _paired_explicit_main_m2(
    paired: list[dict[str, Any]],
) -> tuple[float | None, dict[str, Any] | None]:
    for main in paired:
        m2 = _explicit_bom_m2(main)
        if m2 is not None:
            return m2, main
    return None, None


def _fabric_role(name: str, spec: str = "") -> str:
    blob = f"{name} {spec}".strip()
    from structure_usage import _FRONT_POCKET_LINING_PAT, _LINING_PAT, _MAIN_FAB_PAT, _ZIP_PAT

    if _ZIP_PAT.search(blob):
        return ""
    if _LINING_PAT.search(blob) and _FRONT_POCKET_LINING_PAT.search(blob):
        return "partial_lining"
    if _LINING_PAT.search(blob):
        return "lining"
    if _MAIN_FAB_PAT.search(blob):
        return "main_fabric"
    if any(k in blob for k in ("牛津", "尼龙布", "面料", "外料", "主面")):
        return "main_fabric"
    return ""


def _piece_part_key(row: dict[str, Any]) -> str:
    return re.sub(r"\s+", "", str(row.get("piece_part") or "").strip().lower())


def _same_piece_set(a: dict[str, Any], b: dict[str, Any]) -> bool:
    pa = _piece_part_key(a)
    pb = _piece_part_key(b)
    if pa and pb:
        return pa == pb
    if pa or pb:
        return False
    return True


def _quote_rows(quote_obj: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("detail_rows", "items"):
        src = quote_obj.get(key)
        if isinstance(src, list):
            for raw in src:
                if isinstance(raw, dict):
                    rows.append(raw)
    return rows


def _anomaly_signature(anomaly_type: str, field_name: str, reason: str) -> str:
    raw = f"{anomaly_type}|{field_name}|{reason[:120]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def record_anomaly(
    *,
    quote_uid: str,
    anomaly: DetectedAnomaly,
    quote_id: str = "",
    product_name: str = "",
    structure_text: str = "",
    piece_area_calculation: dict[str, Any] | None = None,
) -> str:
    _init_storage()
    sig = _anomaly_signature(anomaly.anomaly_type, anomaly.field_name, anomaly.reason)
    anomaly_id = str(uuid.uuid4())
    pac_json = ""
    if isinstance(piece_area_calculation, dict):
        pac_json = json.dumps(piece_area_calculation, ensure_ascii=False)[:8000]
    conn = _connect()
    try:
        dup = conn.execute(
            """
            SELECT anomaly_id FROM quote_anomaly_history
            WHERE quote_uid = ? AND signature = ? AND old_value = ? AND detected_at > datetime('now', '-1 day')
            """,
            (quote_uid, sig, str(anomaly.old_value or "")[:200]),
        ).fetchone()
        if dup:
            return str(dup["anomaly_id"])
        conn.execute(
            """
            INSERT INTO quote_anomaly_history (
                anomaly_id, quote_uid, quote_id, product_name, material_name, related_material,
                field_name, old_value, expected_value, structure_text, piece_area_calculation,
                calc_note, reason, anomaly_type, detected_at, confidence, can_promote_to_rule,
                signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                anomaly_id,
                quote_uid,
                quote_id,
                product_name[:200],
                anomaly.material_name[:120],
                anomaly.related_material[:120],
                anomaly.field_name,
                str(anomaly.old_value or "")[:500],
                str(anomaly.expected_value or "")[:500],
                structure_text[:2000],
                pac_json,
                anomaly.calc_note[:500],
                anomaly.reason[:500],
                anomaly.anomaly_type,
                _utc_now_iso(),
                float(anomaly.confidence),
                1 if anomaly.can_promote_to_rule else 0,
                sig,
            ),
        )
        conn.commit()
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()
    return anomaly_id


def _count_signature(conn, signature: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM quote_anomaly_history WHERE signature = ?",
        (signature,),
    ).fetchone()
    return int(row["c"] or 0) if row else 0


def _upsert_candidate_rule(
    conn,
    anomaly: DetectedAnomaly,
    *,
    signature: str,
    source_count: int,
    enable_now: bool,
) -> str:
    rule_id = f"candidate-{anomaly.anomaly_type}-{signature[:12]}"
    now = _utc_now_iso()
    keywords = []
    if anomaly.anomaly_type == "fabric_lining_usage_gap":
        keywords = ["里布", "里料", "内里", "涤纶"]
    elif anomaly.anomaly_type == "customer_pack_internal_label":
        keywords = ["包装", "纸箱", "胶袋"]
    bad = [str(anomaly.old_value or "")] if anomaly.old_value else []
    if anomaly.anomaly_type == "lining_ratio_in_calc_note":
        bad = [r"里布占比", r"×\s*0\.22"]
    status = "active" if enable_now else "pending_review"
    enabled = 1 if enable_now else 0
    conf = min(0.95, 0.55 + 0.1 * source_count) if not enable_now else max(
        APPLY_CONFIDENCE_MIN, anomaly.confidence
    )
    conn.execute(
        """
        INSERT INTO quote_correction_rules (
            rule_id, rule_type, field_name, match_keywords, match_product_keywords,
            match_structure_keywords, bad_values, corrected_value, confidence, source_count,
            enabled, affects_calculation, created_at, updated_at, reason,
            rule_status, auto_learned, anomaly_type
        ) VALUES (?, ?, ?, ?, '[]', '[]', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(rule_id) DO UPDATE SET
            source_count = MAX(source_count, excluded.source_count),
            confidence = MAX(confidence, excluded.confidence),
            enabled = MAX(enabled, excluded.enabled),
            rule_status = CASE
                WHEN excluded.rule_status = 'active' THEN 'active'
                ELSE quote_correction_rules.rule_status
            END,
            updated_at = excluded.updated_at
        """,
        (
            rule_id,
            f"auto_{anomaly.anomaly_type}",
            anomaly.field_name,
            json.dumps(keywords, ensure_ascii=False),
            json.dumps(bad, ensure_ascii=False),
            "__AUTO__",
            conf,
            source_count,
            enabled,
            now,
            now,
            anomaly.reason[:240],
            status,
            anomaly.anomaly_type,
        ),
    )
    return rule_id


def try_promote_candidate_rules(signature: str, anomaly: DetectedAnomaly) -> str | None:
    _init_storage()
    conn = _connect()
    try:
        cnt = _count_signature(conn, signature)
        enable = (
            anomaly.anomaly_type in HIGH_CERTAINTY_ANOMALY_TYPES
            and cnt >= 1
            and anomaly.confidence >= APPLY_CONFIDENCE_MIN
        ) or cnt >= AUTO_PROMOTE_MIN_OCCURRENCES
        if not enable and not anomaly.can_promote_to_rule:
            return None
        if cnt < 1:
            return None
        if cnt < AUTO_PROMOTE_MIN_OCCURRENCES and anomaly.anomaly_type not in HIGH_CERTAINTY_ANOMALY_TYPES:
            return _upsert_candidate_rule(
                conn, anomaly, signature=signature, source_count=cnt, enable_now=False
            )
        rule_id = _upsert_candidate_rule(
            conn, anomaly, signature=signature, source_count=cnt, enable_now=enable
        )
        conn.commit()
        return rule_id
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()


def detect_anomalies_in_quote(quote_obj: dict[str, Any]) -> list[DetectedAnomaly]:
    if not isinstance(quote_obj, dict):
        return []
    anomalies: list[DetectedAnomaly] = []
    rows = _quote_rows(quote_obj)
    st = str(
        quote_obj.get("structure_text_snapshot") or quote_obj.get("structure_text") or ""
    )
    pac = quote_obj.get("piece_area_calculation")

    main_rows: list[dict[str, Any]] = []
    lining_rows: list[dict[str, Any]] = []
    for row in rows:
        role = _fabric_role(str(row.get("name") or ""), str(row.get("spec") or ""))
        if role == "main_fabric":
            main_rows.append(row)
        elif role == "lining":
            lining_rows.append(row)

    area_ctx = _quote_body_area_context(quote_obj)
    if area_ctx is not None:
        body_m2, _piece_target, piece_note, _shell = area_ctx
        for main in main_rows:
            explicit_m2 = _explicit_bom_m2(main)
            if explicit_m2 is None:
                continue
            gap_piece = _usage_rel_gap(explicit_m2, body_m2)
            if gap_piece <= FABRIC_LINING_MAX_REL_GAP:
                continue
            main_name = str(main.get("name") or "")
            if any(
                a.anomaly_type == "main_bom_vs_piece_area_gap"
                and a.material_name == main_name
                for a in anomalies
            ):
                continue
            anomalies.append(
                DetectedAnomaly(
                    anomaly_type="main_bom_vs_piece_area_gap",
                    material_name=main_name,
                    field_name="usage",
                    old_value=str(main.get("usage") or ""),
                    expected_value=f"裁片面积表≈{body_m2:g}㎡（{piece_note[:80]}）",
                    reason=(
                        f"主料明确用量≈{explicit_m2:g}㎡与裁片面积表≈{body_m2:g}㎡差异"
                        f"{gap_piece:.0%}，超过{FABRIC_LINING_MAX_REL_GAP:.0%}，保留BOM待核"
                    ),
                    confidence=0.88,
                    can_promote_to_rule=False,
                )
            )

    for main in main_rows:
        main_m2 = _parse_m2(str(main.get("usage") or ""))
        if main_m2 is None:
            continue
        main_name = str(main.get("name") or "")
        for lin in lining_rows:
            if not _same_piece_set(main, lin):
                continue
            lin_m2 = _parse_m2(str(lin.get("usage") or ""))
            if lin_m2 is None:
                continue
            gap = abs(main_m2 - lin_m2) / max(main_m2, 1e-6)
            if gap <= FABRIC_LINING_MAX_REL_GAP:
                continue
            calc_note = str(lin.get("calc_note") or lin.get("calc_method") or "")
            anomalies.append(
                DetectedAnomaly(
                    anomaly_type="fabric_lining_usage_gap",
                    material_name=str(lin.get("name") or ""),
                    related_material=main_name,
                    field_name="usage",
                    old_value=str(lin.get("usage") or ""),
                    expected_value=f"与主料同面积基准（主料≈{main_m2:g}㎡）",
                    reason=(
                        f"同裁片/部位下主料≈{main_m2:g}㎡与里布≈{lin_m2:g}㎡差异{gap:.0%}，"
                        f"超过阈值{FABRIC_LINING_MAX_REL_GAP:.0%}"
                    ),
                    confidence=0.9 if gap > 0.5 else 0.75,
                    calc_note=calc_note,
                )
            )
            if _LINING_RATIO_NOTE_RE.search(calc_note):
                anomalies.append(
                    DetectedAnomaly(
                        anomaly_type="lining_ratio_in_calc_note",
                        material_name=str(lin.get("name") or ""),
                        field_name="calc_note",
                        old_value=calc_note[:200],
                        expected_value="里布与主料共用裁片面积说明",
                        reason="计算方式仍含里布占比/0.22系数",
                        confidence=0.92,
                    )
                )
            if _FIXED_LOW_LINING_M2_RE.match(str(lin.get("usage") or "").strip()):
                anomalies.append(
                    DetectedAnomaly(
                        anomaly_type="fixed_low_lining_m2",
                        material_name=str(lin.get("name") or ""),
                        field_name="usage",
                        old_value=str(lin.get("usage") or ""),
                        expected_value="按共用裁片面积重算",
                        reason="里布用量疑似固定兜底㎡",
                        confidence=0.88,
                    )
                )

    for row in rows:
        usage = str(row.get("usage") or "").strip()
        spec = str(row.get("spec") or "").strip()
        name = str(row.get("name") or "")
        if spec and re.fullmatch(r"\d+(?:\.\d+)?\s*(?:cm|CM|厘米)?", spec):
            if _CM_ONLY_USAGE_RE.match(usage) or (
                spec.replace(" ", "").lower() in usage.replace(" ", "").lower()
                and _parse_m2(usage) is None
                and re.search(rf"{re.escape(spec[:3])}", usage, re.I)
            ):
                anomalies.append(
                    DetectedAnomaly(
                        anomaly_type="spec_width_misused_as_usage",
                        material_name=name,
                        field_name="usage",
                        old_value=usage,
                        expected_value="按㎡或码用量",
                        reason=f"规格{spec}疑似被当作用量来源",
                        confidence=0.7,
                        can_promote_to_rule=False,
                    )
                )

    pack_text = str(quote_obj.get("pack") or quote_obj.get("_quote_sheet_pack_display") or "")
    if not pack_text:
        for row in rows:
            if "包装" in str(row.get("name") or ""):
                pack_text = str(row.get("usage") or row.get("spec") or "")
                break
    if pack_text and _INTERNAL_DISPLAY_RE.search(pack_text):
        anomalies.append(
            DetectedAnomaly(
                anomaly_type="customer_pack_internal_label",
                material_name="[包装]",
                field_name="pack",
                old_value=pack_text,
                expected_value="客户可读包装文案",
                reason="包装展示含系统估算/AI估算/推断",
                confidence=0.95,
            )
        )

    images = quote_obj.get("quote_sheet_images") or quote_obj.get("product_images") or []
    if isinstance(images, list):
        from quote_correction_learning import evaluate_product_image_item

        ctx = {"product_name": quote_obj.get("product_name"), "structure_text": st}
        for idx, item in enumerate(images):
            if not isinstance(item, dict):
                continue
            ok, hits = evaluate_product_image_item(item, ctx)
            if ok:
                continue
            anomalies.append(
                DetectedAnomaly(
                    anomaly_type="product_image_untrusted",
                    material_name=f"[款式图#{idx + 1}]",
                    field_name="image",
                    old_value=str(item.get("file_name") or item.get("image_role") or "embed"),
                    expected_value="reject_untrusted",
                    reason="客户报价单图片疑似表格/说明截图",
                    confidence=0.93,
                )
            )
            if hits:
                break

    for row in rows:
        calc = str(row.get("calc_note") or row.get("calc_method") or "")
        if _LINING_RATIO_NOTE_RE.search(calc) and not any(
            a.anomaly_type == "lining_ratio_in_calc_note" and a.material_name == str(row.get("name"))
            for a in anomalies
        ):
            anomalies.append(
                DetectedAnomaly(
                    anomaly_type="lining_ratio_in_calc_note",
                    material_name=str(row.get("name") or ""),
                    field_name="calc_note",
                    old_value=calc[:200],
                    expected_value="共用裁片面积",
                    reason="计算方式含里布占比系数",
                    confidence=0.85,
                )
            )

    return anomalies


def _may_auto_fix_row(row: dict[str, Any], field_name: str) -> bool:
    from material_spec_usage_enricher import (
        is_explicit_bom_usage_row,
        is_usage_eligible_for_auto_fix,
    )

    if _has_admin_field(row, field_name):
        return False
    if field_name == "usage":
        if is_explicit_bom_usage_row(row):
            return False
        if not is_usage_eligible_for_auto_fix(row):
            return False
        dummy_rule = CorrectionRule(
            rule_id="chk",
            rule_type="check",
            field_name="usage",
            match_keywords=[],
            match_product_keywords=[],
            match_structure_keywords=[],
            bad_values=["1套"],
            corrected_value="",
            confidence=1.0,
            source_count=1,
            enabled=True,
            affects_calculation=True,
        )
        if _has_trusted_raw_field(row, "usage", dummy_rule):
            return False
    return True


def _mark_usage_anomaly_pending(quote_obj: dict[str, Any], an: DetectedAnomaly) -> None:
    """明确 BOM / 不可自动改写时仅标记待核，不改 usage。"""
    for row in _quote_rows(quote_obj):
        if str(row.get("name") or "").strip() != str(an.material_name or "").strip():
            continue
        flags = list(row.get("_anomaly_flags") or [])
        flags.append(
            {
                "type": an.anomaly_type,
                "field": an.field_name,
                "reason": an.reason,
                "confidence": an.confidence,
                "expected": an.expected_value,
            }
        )
        row["_anomaly_flags"] = flags
        row["_anomaly_pending_review"] = True
        if an.field_name == "usage" and an.expected_value:
            row["_anomaly_suggested_usage"] = an.expected_value
        note = str(row.get("calc_note") or row.get("calc_method") or "").strip()
        hint = f"用量待核：{an.reason}"
        if hint not in note:
            row["calc_note"] = f"{note}；{hint}"[:260] if note else hint[:260]
        break


def _apply_lining_usage_value(
    lin: dict[str, Any],
    *,
    rule: CorrectionRule,
    old: str,
    target: str,
    note_suffix: str,
) -> RuleApplication:
    lin["usage"] = target
    lin["calc_note"] = f"异常规则（{rule.rule_id}）：{note_suffix}，取{target}"[:260]
    lin["correction_rule_id"] = rule.rule_id
    lin["correction_rule_source"] = "anomaly_auto_fix"
    lin["_anomaly_auto_fixed"] = True
    lin.pop("_anomaly_pending_review", None)
    app = _make_app(
        rule,
        material_name=str(lin.get("name") or ""),
        field_name="usage",
        old_val=old,
        applied=target,
        mode="applied",
    )
    _append_hits(lin, [app])
    return app


def _ensure_same_piece_gap_resolved(quote_obj: dict[str, Any]) -> None:
    """修复后同裁片主料/里布差异仍 >30% 时必须待核（并给出对齐建议）。"""
    rows = _quote_rows(quote_obj)
    main_rows = [
        r
        for r in rows
        if _fabric_role(str(r.get("name") or ""), str(r.get("spec") or "")) == "main_fabric"
    ]
    lining_rows = [
        r
        for r in rows
        if _fabric_role(str(r.get("name") or ""), str(r.get("spec") or "")) == "lining"
    ]
    for main in main_rows:
        main_m2 = _parse_m2(str(main.get("usage") or ""))
        if main_m2 is None:
            continue
        main_name = str(main.get("name") or "")
        main_usage = str(main.get("usage") or "").strip()
        for lin in lining_rows:
            if not _same_piece_set(main, lin):
                continue
            lin_m2 = _parse_m2(str(lin.get("usage") or ""))
            if lin_m2 is None:
                continue
            if _usage_rel_gap(main_m2, lin_m2) <= FABRIC_LINING_MAX_REL_GAP:
                continue
            if lin.get("_anomaly_pending_review"):
                continue
            expected = (
                f"与主料明确用量 {main_usage} 对齐"
                if _explicit_bom_m2(main) is not None
                else f"与主料同面积基准（主料≈{main_m2:g}㎡）"
            )
            _mark_usage_anomaly_pending(
                quote_obj,
                DetectedAnomaly(
                    anomaly_type="fabric_lining_usage_gap",
                    material_name=str(lin.get("name") or ""),
                    related_material=main_name,
                    field_name="usage",
                    old_value=str(lin.get("usage") or ""),
                    expected_value=expected,
                    reason=(
                        f"修复后主料≈{main_m2:g}㎡与里布≈{lin_m2:g}㎡仍差"
                        f"{_usage_rel_gap(main_m2, lin_m2):.0%}，超过{FABRIC_LINING_MAX_REL_GAP:.0%}"
                    ),
                    confidence=0.9,
                ),
            )


def _apply_fabric_lining_shared_area(
    quote_obj: dict[str, Any],
    rule: CorrectionRule,
) -> list[RuleApplication]:
    from material_spec_usage_enricher import _parse_bool_flag, is_explicit_bom_usage_row
    from structure_usage import _format_usage

    hits: list[RuleApplication] = []
    area_ctx = _quote_body_area_context(quote_obj)
    if area_ctx is None:
        return hits
    body_m2, piece_target, piece_basis_note, _shell = area_ctx
    rows = _quote_rows(quote_obj)
    main_rows = [
        r
        for r in rows
        if _fabric_role(str(r.get("name") or ""), str(r.get("spec") or "")) == "main_fabric"
    ]

    for lin in rows:
        if _fabric_role(str(lin.get("name") or ""), str(lin.get("spec") or "")) != "lining":
            continue
        if not _may_auto_fix_row(lin, "usage"):
            continue
        old = str(lin.get("usage") or "")
        lin_m2 = _parse_m2(old)
        paired = [m for m in main_rows if _same_piece_set(lin, m)]
        if main_rows and not paired:
            continue
        explicit_m2, _explicit_main = _paired_explicit_main_m2(paired)

        bad_hit = (
            _LINING_RATIO_NOTE_RE.search(str(lin.get("calc_note") or ""))
            or (lin_m2 is not None and _FIXED_LOW_LINING_M2_RE.match(old.strip()))
            or (
                lin_m2 is not None
                and paired
                and any(
                    (m2 := _parse_m2(str(m.get("usage") or ""))) is not None
                    and _usage_rel_gap(m2, lin_m2) > FABRIC_LINING_MAX_REL_GAP
                    for m in paired
                )
            )
        )
        if not bad_hit and lin_m2 is not None:
            if explicit_m2 is None and _usage_rel_gap(lin_m2, body_m2) <= FABRIC_LINING_MAX_REL_GAP:
                continue
            if explicit_m2 is not None and _usage_rel_gap(lin_m2, explicit_m2) <= FABRIC_LINING_MAX_REL_GAP:
                continue

        if explicit_m2 is not None:
            target = _format_usage(explicit_m2, "㎡")
            note = f"里布与主料明确用量对齐（主料≈{explicit_m2:g}㎡）"
            hits.append(
                _apply_lining_usage_value(
                    lin,
                    rule=rule,
                    old=old,
                    target=target,
                    note_suffix=note,
                )
            )
            continue

        if lin_m2 is not None and _usage_rel_gap(lin_m2, body_m2) <= FABRIC_LINING_MAX_REL_GAP:
            continue
        if not bad_hit:
            continue

        hits.append(
            _apply_lining_usage_value(
                lin,
                rule=rule,
                old=old,
                target=piece_target,
                note_suffix=f"里布与主料共用{piece_basis_note}",
            )
        )
        for main in paired:
            if is_explicit_bom_usage_row(main):
                continue
            if not (_may_auto_fix_row(main, "usage") or _parse_bool_flag(main, "usage_ai")):
                continue
            main_old = str(main.get("usage") or "")
            main_m2 = _parse_m2(main_old)
            if main_m2 is None:
                continue
            if _usage_rel_gap(main_m2, body_m2) <= FABRIC_LINING_MAX_REL_GAP:
                continue
            main["usage"] = piece_target
            main["calc_note"] = (
                f"异常规则（{rule.rule_id}）：主料与里布共用{piece_basis_note}，取{piece_target}"
            )[:260]
            main["correction_rule_id"] = rule.rule_id
            main["correction_rule_source"] = "anomaly_auto_fix"
            main["_anomaly_auto_fixed"] = True
            app = _make_app(
                rule,
                material_name=str(main.get("name") or ""),
                field_name="usage",
                old_val=main_old,
                applied=piece_target,
                mode="applied",
            )
            hits.append(app)
            _append_hits(main, [app])

    _ensure_same_piece_gap_resolved(quote_obj)
    return hits


def apply_anomaly_auto_fixes(quote_obj: dict[str, Any]) -> list[RuleApplication]:
    if not isinstance(quote_obj, dict):
        return []
    rules = load_enabled_rules()
    all_hits: list[RuleApplication] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.rule_type == "fabric_lining_shared_area":
            all_hits.extend(_apply_fabric_lining_shared_area(quote_obj, rule))
    if all_hits:
        existing = list(quote_obj.get("correction_rule_applications") or [])
        quote_obj["correction_rule_applications"] = existing + [asdict(h) for h in all_hits]
        quote_obj["anomaly_auto_fixes"] = [asdict(h) for h in all_hits]
    from material_spec_usage_enricher import purge_dynamic_usage_placeholders

    purge_dynamic_usage_placeholders(_quote_rows(quote_obj))
    return all_hits


def scan_and_learn_from_quote(
    quote_obj: dict[str, Any],
    *,
    quote_uid: str = "",
    apply_auto_fix: bool = True,
    record_history: bool = True,
) -> AnomalyScanResult:
    """检测异常 → 写入 anomaly_history → 候选/晋升规则 → 可选自动修复。"""
    result = AnomalyScanResult()
    if not isinstance(quote_obj, dict):
        result.ok = False
        return result
    uid = str(quote_uid or quote_obj.get("quote_uid") or quote_obj.get("id") or "").strip()
    result.quote_uid = uid
    anomalies: list[DetectedAnomaly] = []
    try:
        anomalies = detect_anomalies_in_quote(quote_obj)
        result.detected = anomalies
        qid = str(quote_obj.get("quote_id") or "")
        pn = str(quote_obj.get("product_name") or "")
        st = str(
            quote_obj.get("structure_text_snapshot") or quote_obj.get("structure_text") or ""
        )
        pac = quote_obj.get("piece_area_calculation")
        for an in anomalies:
            sig = _anomaly_signature(an.anomaly_type, an.field_name, an.reason)
            if record_history and uid:
                try:
                    aid = record_anomaly(
                        quote_uid=uid,
                        anomaly=an,
                        quote_id=qid,
                        product_name=pn,
                        structure_text=st,
                        piece_area_calculation=pac if isinstance(pac, dict) else None,
                    )
                    if aid:
                        result.recorded_ids.append(aid)
                except Exception as exc:
                    logger.warning("record_anomaly failed: %s", exc)
                    result.warnings.append(str(exc))
            if an.can_promote_to_rule:
                try:
                    rid = try_promote_candidate_rules(sig, an)
                except Exception as exc:
                    logger.warning("promote candidate rule failed: %s", exc)
                    rid = None
                if rid:
                    if "candidate-" in rid:
                        result.candidate_rules.append(rid)
                    if rid.startswith("builtin-") or "active" in str(rid):
                        result.promoted_rules.append(rid)
                    elif rid not in result.candidate_rules:
                        result.promoted_rules.append(rid)
        if apply_auto_fix:
            result.auto_fixes = apply_anomaly_auto_fixes(quote_obj)
        fixed_materials = {h.material_name for h in result.auto_fixes}
        for an in anomalies:
            if an.anomaly_type == "main_bom_vs_piece_area_gap":
                _mark_usage_anomaly_pending(quote_obj, an)
                continue
            if an.field_name != "usage":
                continue
            if an.material_name in fixed_materials:
                continue
            from material_spec_usage_enricher import (
                is_explicit_bom_usage_row,
                is_usage_eligible_for_auto_fix,
            )

            for row in _quote_rows(quote_obj):
                if str(row.get("name") or "").strip() != str(an.material_name or "").strip():
                    continue
                if is_explicit_bom_usage_row(row) or not is_usage_eligible_for_auto_fix(row):
                    _mark_usage_anomaly_pending(quote_obj, an)
                break
    except Exception as exc:
        logger.exception("scan_and_learn_from_quote failed quote_uid=%s", uid)
        result.ok = False
        result.warnings.append(str(exc))
    finally:
        scan_doc = result.to_dict()
        quote_obj["anomaly_scan"] = scan_doc
        if result.auto_fixes:
            quote_obj["anomaly_auto_fixes"] = [asdict(h) for h in result.auto_fixes]
        elif scan_doc.get("auto_fixes"):
            quote_obj["anomaly_auto_fixes"] = scan_doc["auto_fixes"]
    return result


def link_admin_correction_to_anomaly_promotion(
    quote_uid: str,
    material_name: str,
    field_name: str,
    old_value: str,
    new_value: str,
) -> None:
    """管理员修正确认后，对同类里布/用量异常立即晋升通用规则。"""
    if field_name != "usage" or old_value == new_value:
        return
    if _fabric_role(material_name) not in ("lining", "main_fabric"):
        return
    an = DetectedAnomaly(
        anomaly_type="fabric_lining_usage_gap",
        material_name=material_name,
        field_name="usage",
        old_value=old_value,
        expected_value=new_value,
        reason="管理员修正确认：主料/里布用量对齐",
        confidence=0.95,
    )
    sig = _anomaly_signature(an.anomaly_type, an.field_name, an.reason)
    record_anomaly(
        quote_uid=quote_uid,
        anomaly=an,
        product_name="",
        structure_text="",
    )
    try_promote_candidate_rules(sig, an)
