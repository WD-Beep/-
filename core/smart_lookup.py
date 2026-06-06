"""知识库检索主路径：优先 PriceKB 结构命中，miss 后可触发候选回流建议。"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from embedding.embedding_index import get_embedding_index, warm_prepare as _embedding_warm_prepare
from price_kb import (
    KBEntry,
    KBHit,
    PriceKB,
    SheetParseError,
    format_kb_entry_price_display,
    get_price_kb,
)
from price_kb_paths import official_kb_path


_TRUTHY = {"1", "true", "yes", "on"}


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def knowledge_auto_learn_enabled() -> bool:
    """MISS 后是否允许执行回流候选流程。"""
    return _env_truthy("KNOWLEDGE_AUTO_LEARN", default=False)


def knowledge_auto_write_enabled() -> bool:
    """是否允许自动写回 price_kb.xlsx。建议默认关闭并通过审批流程。"""
    return _env_truthy("KNOWLEDGE_AUTO_WRITE", default=False)


def knowledge_auto_learn_min_confidence() -> float:
    """自动写回的置信度下限。"""
    raw = os.environ.get("KNOWLEDGE_AUTO_LEARN_MIN_CONFIDENCE")
    try:
        value = float(raw) if raw is not None else 0.75
    except (TypeError, ValueError):
        value = 0.75
    return max(0.0, min(1.0, value))


def knowledge_auto_learn_pending_file() -> Path:
    """待审核回流候选记录文件。"""
    custom = str(os.environ.get("KNOWLEDGE_AUTO_LEARN_PENDING_FILE") or "").strip()
    if custom:
        return Path(custom)
    return Path(__file__).resolve().parents[1] / "knowledge_updates" / "pending_auto_learn.jsonl"


def _append_pending_auto_learn_record(
    *,
    query: str,
    spec: str,
    confidence: float,
    material: dict[str, Any],
    candidates: list[dict[str, Any]],
    reason: str,
) -> None:
    path = knowledge_auto_learn_pending_file().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "type": "kb_auto_learn_candidate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "spec": spec,
        "confidence": round(float(confidence), 6),
        "reason": reason,
        "material": {
            "name": str(material.get("name") or "").strip(),
            "spec": str(material.get("spec") or "").strip(),
            "price": str(material.get("price") or "").strip(),
        },
        "candidates": candidates,
    }
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")


def enqueue_knowledge_learn_after_rule_miss(
    query: str,
    spec: str | None = None,
    *,
    top_k: int = 5,
) -> None:
    """在查价 miss 后触发候选队列回流闭环（异步，不阻塞报价主流程）。"""
    if not knowledge_auto_learn_enabled():
        return
    q = str(query or "").strip()
    if not q:
        return
    spec_norm = "" if spec is None else str(spec)
    threading.Thread(
        target=_enqueue_knowledge_learn_worker,
        args=(q, spec_norm, int(top_k)),
        daemon=True,
        name="knowledge-enqueue",
    ).start()


def _enqueue_knowledge_learn_worker(query: str, spec_norm: str, top_k: int) -> None:
    try:
        _force_reload_index_if_dirty(max_wait_sec=3.0)
        q_for_embed = f"{query} {spec_norm}".strip() or query
        raw_hits: list[tuple[KBEntry, float]] = []
        index = get_embedding_index()
        if index.is_ready():
            try:
                raw_hits = index.search(q_for_embed, top_k=top_k)
            except Exception as exc:  # noqa: BLE001
                print(f"[embedding] enqueue_learn semantic search failed: {exc}", flush=True)
        if not raw_hits:
            return
        kb_path = official_kb_path()
        _knowledge_miss_closure(query, spec_norm, raw_hits, kb_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[embedding] enqueue_learn worker failed: {exc}", flush=True)


def _force_reload_index_if_dirty(*, max_wait_sec: float = 3.0) -> None:
    """索引脏态时尝试短暂恢复；失败不抛错，报价主路径继续走 PriceKB 规则匹配。"""
    from embedding.embedding_index import GLOBAL_INDEX_STATE, get_embedding_index

    deadline = time.perf_counter() + max(0.5, float(max_wait_sec))
    while time.perf_counter() < deadline:
        if GLOBAL_INDEX_STATE != "DIRTY":
            return
        try:
            from core.knowledge_reload import KNOWLEDGE_MUTATION_LOCK

            if KNOWLEDGE_MUTATION_LOCK.locked():
                time.sleep(0.05)
                continue
        except Exception:
            pass
        try:
            kb = get_price_kb()
            get_embedding_index().prepare(kb, official_kb_path())
        except Exception as exc:  # noqa: BLE001
            print(f"[embedding] dirty-reload prepare failed: {exc}", flush=True)
            return
        if GLOBAL_INDEX_STATE == "READY":
            return
        time.sleep(0.05)


def invalidate_embedding_index() -> None:
    """Invalidate runtime embedding cache."""
    from embedding.embedding_index import invalidate_embedding_index as _invalidate_embedding_runtime

    _invalidate_embedding_runtime()


def warm_embedding_index(kb_source_path: Path | None = None) -> None:
    """服务启动期预热 PriceKB 与 embedding 缓存。"""
    try:
        kb = get_price_kb()
    except (FileNotFoundError, SheetParseError) as exc:
        print(f"[embedding] warm skipped (no PriceKB): {exc}", flush=True)
        return
    path = kb_source_path if kb_source_path is not None else official_kb_path()
    _embedding_warm_prepare(kb, path)


def _knowledge_miss_closure(
    query: str,
    spec_norm: str,
    raw_hits: list[tuple[KBEntry, float]],
    kb_path: Path,
) -> None:
    """后台执行 judge -> write/review queue -> reload。"""
    from kimi_client import get_kimi_config

    candidates = [
        {
            "name": e.raw_name,
            "spec": e.raw_spec,
            "similarity": round(float(s), 6),
            "reference_price": e.raw_price,
        }
        for e, s in raw_hits
    ]
    try:
        if not get_kimi_config().api_key:
            return
        from core.knowledge_apply import apply_kb_write
        from core.knowledge_judge import judge_write_decision
        from core.knowledge_reload import KNOWLEDGE_MUTATION_LOCK, knowledge_reload_hook

        decision = judge_write_decision(query, spec_norm, candidates)
        act = str(decision.get("action") or "").strip()
        try:
            conf = float(decision.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        mat_obj = decision.get("material") if isinstance(decision.get("material"), dict) else {}
        mat: dict[str, Any] = {
            "name": str(mat_obj.get("name", "")).strip(),
            "spec": str(mat_obj.get("spec", "")).strip(),
            "price": str(mat_obj.get("price") or mat_obj.get("unit_price", "")).strip(),
        }

        min_conf = knowledge_auto_learn_min_confidence()
        if act != "write_to_kb" or conf < min_conf:
            return

        from kb_data_quality import KB_ACTION_AUTO, KB_ACTION_DROP, KB_ACTION_REVIEW, judge_kb_insert_candidate

        quality = judge_kb_insert_candidate(
            mat.get("name", ""),
            mat.get("spec", ""),
            mat.get("price", ""),
        )
        if quality.action == KB_ACTION_DROP:
            print(
                f"[knowledge-closure] quality drop query={query!r} reason={quality.reason}",
                flush=True,
            )
            return
        if quality.action == KB_ACTION_REVIEW:
            _append_pending_auto_learn_record(
                query=query,
                spec=spec_norm,
                confidence=conf,
                material=mat,
                candidates=candidates,
                reason=f"quality_review:{quality.reason}",
            )
            print(
                f"[knowledge-closure] quality review queued query={query!r} reason={quality.reason}",
                flush=True,
            )
            return

        if not knowledge_auto_write_enabled():
            _append_pending_auto_learn_record(
                query=query,
                spec=spec_norm,
                confidence=conf,
                material=mat,
                candidates=candidates,
                reason="auto_write_disabled",
            )
            print(
                f"[knowledge-closure] auto-write disabled, queued for review query={query!r} conf={conf:.3f}",
                flush=True,
            )
            return

        with KNOWLEDGE_MUTATION_LOCK:
            if apply_kb_write(mat, kb_path):
                try:
                    knowledge_reload_hook(kb_path)
                except Exception as reload_exc:  # noqa: BLE001
                    print(f"[knowledge-closure] reload failed: {reload_exc}", flush=True)
                    get_embedding_index().mark_unready()
    except Exception as exc:  # noqa: BLE001
        print(f"[knowledge-closure] {exc}", flush=True)


def smart_lookup(
    query: str,
    spec: str | None = None,
    *,
    kb: PriceKB | None = None,
    min_score: float = 0.30,
    top_k: int = 5,
) -> dict[str, Any]:
    """
    Step1: PriceKB.lookup
    Step2: 命中则返回 kb 单价
    Step3: miss 时做 embedding 检索，若开启 auto_learn 再走后台 judge/回流。
    """
    try:
        _force_reload_index_if_dirty(max_wait_sec=1.5)
    except Exception as exc:  # noqa: BLE001
        print(f"[embedding] smart_lookup dirty-reload skipped: {exc}", flush=True)
    spec_norm = "" if spec is None else str(spec)
    try:
        price_kb = kb if kb is not None else get_price_kb()
    except (FileNotFoundError, SheetParseError):
        return {"kb_hit": False, "unit_price": None, "candidates": []}

    hit: KBHit | None = price_kb.lookup(query, spec_norm, min_score=min_score)
    if hit is not None:
        return {
            "kb_hit": True,
            "unit_price": format_kb_entry_price_display(hit.entry),
            "candidates": [],
        }

    q_for_embed = f"{query} {spec_norm}".strip() or query
    candidates: list[dict[str, Any]] = []
    raw_hits: list[tuple[KBEntry, float]] = []
    index = get_embedding_index()
    if q_for_embed and index.is_ready():
        try:
            raw_hits = index.search(q_for_embed, top_k=top_k)
            for entry, sim in raw_hits:
                candidates.append(
                    {
                        "name": entry.raw_name,
                        "spec": entry.raw_spec,
                        "similarity": round(float(sim), 6),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[embedding] semantic search failed: {exc}", flush=True)
    elif q_for_embed and not index.is_ready():
        print("[embedding] semantic search skipped (index not ready)", flush=True)

    if raw_hits and knowledge_auto_learn_enabled():
        kb_path = official_kb_path()
        threading.Thread(
            target=_knowledge_miss_closure,
            args=(query, spec_norm, raw_hits, kb_path),
            daemon=True,
            name="knowledge-closure",
        ).start()

    return {"kb_hit": False, "unit_price": None, "candidates": candidates}
