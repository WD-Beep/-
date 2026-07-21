# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：collect errors
"""采集/导入过程可读错误汇总。"""

from __future__ import annotations

INFORMATIONAL_EMPTY_DISCOVERY_PHRASES = (
    "暂无候选结果",
    "暂无匹配结果",
    "发现阶段结束",
    "但未返回候选",
    "可能关键词无结果",
    "响应较慢",
    "Apify/API 响应较慢",
)

STALE_INTERRUPT_PHRASES = (
    "任务已超时中断",
    "可重新运行从 checkpoint 继续",
)


def is_informational_empty_discovery_message(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    return any(phrase in text for phrase in INFORMATIONAL_EMPTY_DISCOVERY_PHRASES)


def is_stale_interrupt_message(message: str | None) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    return any(phrase in text for phrase in STALE_INTERRUPT_PHRASES)


def filter_fatal_discovery_errors(errors: list[str]) -> list[str]:
    return [
        err
        for err in errors
        if err.strip() and not is_informational_empty_discovery_message(err)
    ]


def filter_actionable_collection_errors(errors: list[str]) -> list[str]:
    return [
        err
        for err in errors
        if err.strip() and not is_stale_interrupt_message(err)
    ]


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
