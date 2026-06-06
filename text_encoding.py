"""UTF-8 / GBK mojibake detection and optional repair for API and stored text."""
from __future__ import annotations

import logging
import os
import re
from typing import Any

_log = logging.getLogger(__name__)

# High-frequency fragments when UTF-8 was mis-decoded as GBK (or double-encoded).
MOJIBAKE_MARKERS: tuple[str, ...] = ("鍒", "瑙", "濂", "銆", "锛", "鎶", "涓", "褰", "鐗", "缂", "琛", "鍑")

_MOJIBAKE_RE = re.compile("|".join(re.escape(m) for m in MOJIBAKE_MARKERS))


def looks_like_mojibake(text: str | None) -> bool:
    """Return True if text likely contains UTF-8-as-GBK mojibake."""
    if not text or not isinstance(text, str):
        return False
    return bool(_MOJIBAKE_RE.search(text))


def repair_mojibake(text: str) -> str | None:
    """
    Repair UTF-8 bytes that were decoded as GBK/GB18030 then stored as UTF-8.

    Returns repaired string, or None if repair is unsafe / not applicable.
    """
    if not text or not looks_like_mojibake(text):
        return None
    try:
        fixed = text.encode("gb18030").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if fixed == text or looks_like_mojibake(fixed):
        return None
    # Reject if repair introduces replacement chars or loses CJK coverage heavily.
    if "\ufffd" in fixed:
        return None
    return fixed


def repair_mojibake_if_enabled(text: str) -> str:
    """Apply repair when QUOTE_TEXT_MOJIBAKE_REPAIR=1 (default off)."""
    if os.environ.get("QUOTE_TEXT_MOJIBAKE_REPAIR", "").strip() not in {"1", "true", "yes"}:
        return text
    fixed = repair_mojibake(text)
    if fixed is not None:
        _log.warning("mojibake_repaired text_len=%s", len(text))
        return fixed
    if looks_like_mojibake(text):
        _log.warning("mojibake_detected_unrepaired text_len=%s", len(text))
    return text


def deep_repair_strings(obj: Any, *, enabled: bool | None = None) -> Any:
    """Recursively repair str values in dict/list structures (API payloads)."""
    if enabled is None:
        enabled = os.environ.get("QUOTE_TEXT_MOJIBAKE_REPAIR", "").strip() in {"1", "true", "yes"}
    if not enabled:
        return obj
    if isinstance(obj, str):
        return repair_mojibake_if_enabled(obj)
    if isinstance(obj, list):
        return [deep_repair_strings(x, enabled=True) for x in obj]
    if isinstance(obj, dict):
        return {k: deep_repair_strings(v, enabled=True) for k, v in obj.items()}
    return obj
