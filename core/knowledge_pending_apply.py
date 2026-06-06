"""Apply reviewed auto-learn candidates from JSONL into unified price learn queue."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.smart_lookup import knowledge_auto_learn_min_confidence, knowledge_auto_learn_pending_file
from price_admin_store import enqueue_price_learn_candidate
from price_kb_paths import exception_path as default_exception_path, official_kb_path


@dataclass
class PendingApplyResult:
    total: int = 0
    applied: int = 0
    skipped_existing: int = 0
    invalid: int = 0
    failed: int = 0
    kept: int = 0
    enqueued: int = 0
    applied_records: list[dict[str, Any]] = field(default_factory=list)
    kept_records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def apply_pending_auto_learn(
    *,
    pending_file: Path | None = None,
    kb_path: Path | None = None,
    min_confidence: float | None = None,
    dry_run: bool = False,
    reload_after_write: bool = True,
    exception_path: Path | None = None,
) -> PendingApplyResult:
    """Consume legacy pending_auto_learn JSONL and enqueue unified learn candidates.

    不再直接写入正式价格库；审核通过后由后台 approve 写库并 reload。
    """
    _ = kb_path, reload_after_write  # 兼容旧签名
    queue_path = Path(pending_file or knowledge_auto_learn_pending_file()).resolve()
    target_exc = Path(exception_path or default_exception_path()).resolve()
    target_kb = Path(kb_path or official_kb_path()).resolve()
    result = PendingApplyResult()

    if not queue_path.is_file():
        return result

    threshold = (
        knowledge_auto_learn_min_confidence()
        if min_confidence is None
        else max(0.0, min(1.0, float(min_confidence)))
    )

    raw_lines = queue_path.read_text(encoding="utf-8").splitlines()
    for line_no, raw_line in enumerate(raw_lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        result.total += 1
        rec = _load_record(line, line_no, result)
        if rec is None:
            continue

        ok, reason = _record_is_enqueueable(rec, threshold)
        if not ok:
            result.invalid += 1
            result.kept += 1
            _keep_record(result, rec, reason)
            continue

        material = _extract_material(rec)
        try:
            from core.knowledge_apply import kb_material_name_spec_exists, kb_material_row_exists

            if kb_material_row_exists(material, target_kb):
                result.skipped_existing += 1
                continue
            if kb_material_name_spec_exists(material, target_kb):
                result.skipped_existing += 1
                continue
            if dry_run:
                result.enqueued += 1
                result.applied += 1
                result.applied_records.append(rec)
                continue
            enqueue_price_learn_candidate(
                material_name=material["name"],
                spec=material["spec"],
                new_price=material["price"],
                source_type="low_confidence" if reason == "low_confidence" else "smart_lookup_miss",
                confidence=float(rec.get("confidence") or 0.0),
                operator="pending_auto_learn",
                note=str(rec.get("reason") or "legacy pending_auto_learn"),
                raw_context={"legacy_record": rec},
                exception_path=target_exc,
            )
            result.enqueued += 1
            result.applied += 1
            result.applied_records.append(rec)
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.kept += 1
            _keep_record(result, rec, f"exception:{exc}")

    if not dry_run:
        _rewrite_pending_file(queue_path, result.kept_records)
    return result


def _load_record(line: str, line_no: int, result: PendingApplyResult) -> dict[str, Any] | None:
    try:
        rec = json.loads(line)
    except json.JSONDecodeError as exc:
        result.invalid += 1
        result.kept += 1
        result.errors.append(f"line {line_no}: invalid json: {exc}")
        result.kept_records.append({"_raw": line, "_error": "invalid_json"})
        return None
    if not isinstance(rec, dict):
        result.invalid += 1
        result.kept += 1
        result.errors.append(f"line {line_no}: record is not an object")
        result.kept_records.append({"_raw": line, "_error": "not_object"})
        return None
    return rec


def _record_is_enqueueable(rec: dict[str, Any], min_confidence: float) -> tuple[bool, str]:
    if str(rec.get("type") or "").strip() != "kb_auto_learn_candidate":
        return False, "unexpected_type"
    try:
        confidence = float(rec.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return False, "invalid_confidence"
    if confidence < min_confidence:
        return False, "low_confidence"
    material = _extract_material(rec)
    if not material["name"] or not material["price"]:
        return False, "missing_material_name_or_price"
    from kb_data_quality import KB_ACTION_AUTO, KB_ACTION_DROP, judge_kb_insert_candidate

    quality = judge_kb_insert_candidate(material["name"], material["spec"], material["price"])
    if quality.action == KB_ACTION_DROP:
        return False, f"quality_drop:{quality.reason}"
    if quality.action != KB_ACTION_AUTO:
        return False, f"quality_review:{quality.reason}"
    if _has_kb_garbage_symbol(material["name"], material["spec"], material["price"]):
        return False, "garbage_symbol"
    if not _looks_like_real_material_name(material["name"]):
        return False, "non_material_name"
    return True, ""


def _extract_material(rec: dict[str, Any]) -> dict[str, str]:
    raw = rec.get("material") if isinstance(rec.get("material"), dict) else {}
    return {
        "name": str(raw.get("name") or "").strip(),
        "spec": str(raw.get("spec") or "").strip() or "-",
        "price": str(raw.get("price") or raw.get("unit_price") or "").strip(),
    }


def _has_kb_garbage_symbol(*values: object) -> bool:
    return any("?" in str(value or "") or "？" in str(value or "") for value in values)


_DESC_ACTION_HINTS = (
    "外侧使用",
    "内侧为",
    "用于",
    "结构",
    "说明",
    "建议",
    "工艺",
    "调节",
    "固定",
    "包袋",
)
_MATERIAL_HINTS = (
    "料",
    "布",
    "网布",
    "拉链",
    "织带",
    "肩带",
    "插扣",
    "日字扣",
    "d扣",
    "扣",
    "猪鼻扣",
    "配件",
    "fabric",
    "lining",
    "zipper",
    "webbing",
    "buckle",
)
_CONNECTOR_HINTS = ("和", "及", "并", "以及", "搭配", "、", "+", "/")
_QTY_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:个|只|条|颗|套|pcs?|pc)", flags=re.IGNORECASE)


def _looks_like_real_material_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    normalized = text.lower()
    if any(k in normalized for k in _DESC_ACTION_HINTS):
        if len(text) >= 6 and not _QTY_PATTERN.search(text):
            return False
    if _looks_like_concatenated_non_single_material_name(text):
        return False
    return True


def _looks_like_concatenated_non_single_material_name(name: str) -> bool:
    qty_hits = len(_QTY_PATTERN.findall(name))
    if qty_hits < 2:
        return False
    if any(k in name for k in _CONNECTOR_HINTS):
        return True
    return len(name.replace(" ", "")) >= 12 and any(k in name.lower() for k in _MATERIAL_HINTS)


def _keep_record(result: PendingApplyResult, rec: dict[str, Any], reason: str) -> None:
    kept = dict(rec)
    kept["_pending_apply_error"] = reason
    result.kept_records.append(kept)


def _rewrite_pending_file(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
            for rec in records:
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        Path(tmp_name).replace(path)
    except Exception:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise
