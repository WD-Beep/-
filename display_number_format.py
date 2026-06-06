"""业务员/客户可见数字的展示格式化（最多 1 位小数，整数不带 .0）。"""
from __future__ import annotations

import math
import re
from typing import Any

DISPLAY_MAX_DECIMALS = 1

_NUMBER_IN_TEXT_RE = re.compile(r"\d+\.\d+")


def round_display_number(value: float, max_decimals: int = DISPLAY_MAX_DECIMALS) -> float:
    return round(float(value), max_decimals)


def format_display_number(value: Any, max_decimals: int = DISPLAY_MAX_DECIMALS) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if not math.isfinite(x):
        return str(value)
    x = round_display_number(x, max_decimals)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    text = f"{x:.{max_decimals}f}"
    return text.rstrip("0").rstrip(".")


def format_display_money_cny(value: Any, max_decimals: int = DISPLAY_MAX_DECIMALS) -> str:
    return f"{format_display_number(value, max_decimals)}元"


def format_display_money_usd(value: Any, max_decimals: int = DISPLAY_MAX_DECIMALS) -> str:
    return f"${format_display_number(value, max_decimals)}"


def format_numbers_in_display_text(text: Any, max_decimals: int = DISPLAY_MAX_DECIMALS) -> str:
    """格式化文本内嵌小数，如 12.5579元/㎡ → 12.6元/㎡。"""
    raw = str(text or "").strip()
    if not raw or raw in {"-", "—", "/"}:
        return raw

    def _repl(match: re.Match[str]) -> str:
        num_str = match.group(0)
        try:
            x = float(num_str)
        except ValueError:
            return num_str
        if not math.isfinite(x):
            return num_str
        return format_display_number(x, max_decimals)

    return _NUMBER_IN_TEXT_RE.sub(_repl, raw)
