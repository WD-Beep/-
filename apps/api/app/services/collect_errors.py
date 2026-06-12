"""采集/导入过程可读错误汇总。"""

from __future__ import annotations


def summarize_errors(errors: list[str], *, max_items: int = 8, prefix: str = "") -> str | None:
    if not errors:
        return None
    unique: list[str] = []
    seen: set[str] = set()
    for item in errors:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    if not unique:
        return None
    head = unique[:max_items]
    body = "；".join(head)
    if len(unique) > max_items:
        body += f"；另有 {len(unique) - max_items} 条类似问题"
    if prefix:
        return f"{prefix}{body}"[:2000]
    return body[:2000]
