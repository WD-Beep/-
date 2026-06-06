#!/usr/bin/env python3
"""Scan admin.js for mojibake and test repair."""
from __future__ import annotations

import re
from pathlib import Path

ADMIN = Path(__file__).resolve().parents[1] / "static" / "admin" / "admin.js"
MOJIBAKE_MARKERS = ("鍒", "瑙", "濂", "銆", "锛", "鎶", "涓", "褰", "鐗", "缂", "琛", "鍑")

def try_repair(s: str) -> str | None:
    """UTF-8 bytes mis-decoded as GBK then saved as UTF-8."""
    try:
        fixed = s.encode("gb18030").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if fixed == s:
        return None
    if any(m in fixed for m in MOJIBAKE_MARKERS):
        return None
    return fixed


def main() -> None:
    text = ADMIN.read_text(encoding="utf-8")
    str_re = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
    hits: list[tuple[int, str, str | None]] = []
    for m in str_re.finditer(text):
        raw = m.group(0)[1:-1]
        if not any(x in raw for x in MOJIBAKE_MARKERS):
            continue
        line = text[: m.start()].count("\n") + 1
        repaired = try_repair(raw)
        hits.append((line, raw[:80], repaired[:80] if repaired else None))

    out = ADMIN.parent / "_mojibake_scan.txt"
    lines_out = [f"Found {len(hits)} suspicious string literals\n"]
    for line, raw, fixed in hits:
        lines_out.append(f"L{line}: {raw!r}\n")
        if fixed:
            lines_out.append(f"      -> {fixed!r}\n")
    out.write_text("".join(lines_out), encoding="utf-8")
    print(f"wrote {out} ({len(hits)} hits)")


if __name__ == "__main__":
    main()
