#!/usr/bin/env python3
"""One-shot repair of UTF-8-as-GBK mojibake in static/admin/admin.js."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from text_encoding import MOJIBAKE_MARKERS, looks_like_mojibake, repair_mojibake

ADMIN_JS = ROOT / "static" / "admin" / "admin.js"

# Manual fixes when automatic gb18030 round-trip fails (partial corruption).
MANUAL: dict[str, str] = {
    "涓€妗ｆ瘺鍒╁墠鎴愭湰锛堝揩鐓э級": "一档毛利前成本（快照）",
    "鐗╂枡鍚堣\ue178锛堝揩鐓э級": "物料合计（快照）",
    "鏈€鏂版牳绠?ID": "最新核算 ID",
    "涓庡垪琛?GET 鍚屾簮绛涢€夊瓧娈碉紝鐢ㄤ簬銆屾寜绛涢€夊叏閮ㄥ垹闄ゃ€嶃€?": "与列表 GET 同源筛选字段，用于「按筛选全部删除」。",
    "鍐嶆\u200b纭\u200b\u8ba4锛氱湡鐨勮\u8981鍏ㄩ儴鍒犻櫎鍚楋紵": "再次确认：真的要全部删除吗？",
}


def repair_segment(s: str) -> str:
    if s in MANUAL:
        return MANUAL[s]
    fixed = repair_mojibake(s)
    return fixed if fixed is not None else s


def repair_file(text: str) -> tuple[str, int]:
    changed = 0

    def sub_literal(match: re.Match[str]) -> str:
        nonlocal changed
        quote = match.group(1)
        body = match.group(2)
        if not looks_like_mojibake(body):
            return match.group(0)
        new_body = repair_segment(body)
        if new_body != body:
            changed += 1
            escaped = new_body.replace("\\", "\\\\").replace(quote, "\\" + quote)
            return f"{quote}{escaped}{quote}"
        return match.group(0)

    # Double-quoted, single-quoted (not regex), template-free chunks in comments handled separately.
    lit_re = re.compile(r'(["\'])(.*?)(?<!\\)\1', re.DOTALL)
    text = lit_re.sub(sub_literal, text)

    # Block comments /** ... */
    def sub_comment(match: re.Match[str]) -> str:
        nonlocal changed
        inner = match.group(1)
        if not looks_like_mojibake(inner):
            return match.group(0)
        new_inner = repair_segment(inner)
        if new_inner != inner:
            changed += 1
            return f"/** {new_inner} */"
        return match.group(0)

    text = re.sub(r"/\*\*\s*(.*?)\s*\*/", sub_comment, text, flags=re.DOTALL)
    return text, changed


def main() -> None:
    raw = ADMIN_JS.read_text(encoding="utf-8")
    fixed, n = repair_file(raw)
    ADMIN_JS.write_text(fixed, encoding="utf-8", newline="\n")
    remaining = sum(1 for m in MOJIBAKE_MARKERS if m in fixed)
    print(f"admin.js: repaired {n} segments; marker hits left: {remaining}")


if __name__ == "__main__":
    main()
