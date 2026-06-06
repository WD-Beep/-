"""Aggregate LLM participation for quote responses (audit only; never overrides calculate_quote)."""
from __future__ import annotations

from typing import Any

FINAL_TRUTH_SOURCE = "local_formula_calculate_quote"

_MERGE_TRACK_FIELDS = ("usage", "unit_price", "spec", "calc_note")


def _collect_llm_amount_rejections(after_items: list[dict[str, Any]]) -> list[str]:
    rejected: list[str] = []
    if any(isinstance(r, dict) and r.get("llm_suggested_amount") is not None for r in after_items):
        rejected.append("final_amount_must_be_local_formula")
    return rejected


def _truthy_ai(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(val, (int, float)):
        return val != 0
    return False


def diff_merge_fields(
    before_items: list[dict[str, Any]],
    after_items: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Compare item rows before/after LLM merge; return accepted vs rejected field groups."""
    accepted: set[str] = set()
    rejected: set[str] = set()
    for b, a in zip(before_items, after_items):
        if not isinstance(b, dict) or not isinstance(a, dict):
            continue
        kb_hit = bool(b.get("kb_hit"))
        for field in _MERGE_TRACK_FIELDS:
            bv = str(b.get(field) or "").strip()
            av = str(a.get(field) or "").strip()
            if bv == av:
                continue
            flag = f"{field}_ai"
            if field == "unit_price" and kb_hit:
                rejected.add("unit_price_when_kb_hit")
                continue
            if _truthy_ai(a.get(flag)) or (field == "calc_note" and av and av != bv):
                accepted.add(field)
    return sorted(accepted), sorted(rejected)


class LlmAuditCollector:
    def __init__(self) -> None:
        self._calls: list[dict[str, Any]] = []
        self._provider = ""
        self._model = ""
        self._enabled = False

    def seed_from_status(self, status: dict[str, Any] | None) -> None:
        if not isinstance(status, dict):
            return
        if status.get("provider"):
            self._provider = str(status["provider"])
        if status.get("model"):
            self._model = str(status["model"])
        if "enabled" in status:
            self._enabled = bool(status["enabled"])

    def record_stage(
        self,
        stage: str,
        status: dict[str, Any] | None,
        *,
        input_rows: int = 0,
        output_rows: int = 0,
        before_items: list[dict[str, Any]] | None = None,
        after_items: list[dict[str, Any]] | None = None,
        skipped_reason: str = "",
    ) -> None:
        st = status if isinstance(status, dict) else {}
        self.seed_from_status(st)
        accepted: list[str] = []
        rejected: list[str] = []
        if before_items and after_items:
            accepted, rejected = diff_merge_fields(before_items, after_items)
            for tag in _collect_llm_amount_rejections(after_items):
                if tag not in rejected:
                    rejected.append(tag)

        extra_rejected = st.get("llm_rejected_fields")
        if isinstance(extra_rejected, list):
            rejected = sorted(set(rejected) | {str(x) for x in extra_rejected if x})

        err = str(st.get("error") or skipped_reason or "").strip()
        fallback = bool(st.get("fallback_used"))
        used = bool(st.get("used")) or fallback
        success = bool(st.get("used")) and not err and not fallback

        self._calls.append(
            {
                "stage": stage,
                "used": used,
                "success": success,
                "error": err,
                "input_rows": input_rows,
                "output_rows": output_rows,
                "accepted_fields": accepted,
                "rejected_fields": rejected,
                "duration_ms": int(st.get("duration_ms") or 0),
                "fallback_used": fallback,
            }
        )

    def record_skipped(self, stage: str, reason: str) -> None:
        self._calls.append(
            {
                "stage": stage,
                "used": False,
                "success": False,
                "error": reason,
                "input_rows": 0,
                "output_rows": 0,
                "accepted_fields": [],
                "rejected_fields": [],
                "duration_ms": 0,
                "fallback_used": False,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self._provider,
            "model": self._model,
            "enabled": self._enabled,
            "calls": list(self._calls),
            "final_truth_source": FINAL_TRUTH_SOURCE,
            "model_overrides_final_price": False,
        }


def build_llm_audit(
    collector: LlmAuditCollector | None,
    llm_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if collector is not None:
        if isinstance(llm_status, dict):
            collector.seed_from_status(llm_status)
        return collector.to_dict()
    out = LlmAuditCollector()
    out.seed_from_status(llm_status if isinstance(llm_status, dict) else {})
    return out.to_dict()
