# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：shopping seed checkpoint
"""Checkpoint helpers for shopping seed discovery and enrichment."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def normalize_checkpoint_key(value: str | None) -> str:
    return (value or "").strip().lower().rstrip("/")


def checkpoint_list(checkpoint: dict[str, Any], key: str) -> list[str]:
    values = checkpoint.get(key)
    if not isinstance(values, list):
        values = []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        marker = normalize_checkpoint_key(text)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        normalized.append(text)
    checkpoint[key] = normalized
    return normalized


def checkpoint_set(checkpoint: dict[str, Any], key: str) -> set[str]:
    return {normalize_checkpoint_key(value) for value in checkpoint_list(checkpoint, key)}


def append_checkpoint_value(checkpoint: dict[str, Any], key: str, value: str | None) -> bool:
    text = str(value or "").strip()
    marker = normalize_checkpoint_key(text)
    if not marker:
        return False
    values = checkpoint_list(checkpoint, key)
    existing = {normalize_checkpoint_key(item) for item in values}
    if marker in existing:
        return False
    values.append(text)
    return True


def extend_checkpoint_values(checkpoint: dict[str, Any], key: str, values: Iterable[str]) -> int:
    added = 0
    for value in values:
        if append_checkpoint_value(checkpoint, key, value):
            added += 1
    return added


def increment_checkpoint_count(checkpoint: dict[str, Any], key: str, amount: int = 1) -> int:
    current = checkpoint.get(key)
    if not isinstance(current, int):
        current = 0
    current += amount
    checkpoint[key] = current
    return current


def checkpoint_nested_set(checkpoint: dict[str, Any], key: str, nested_key: str) -> set[str]:
    values_by_key = checkpoint.get(key)
    if not isinstance(values_by_key, dict):
        return set()
    return {
        normalize_checkpoint_key(value)
        for value in values_by_key.get(normalize_checkpoint_key(nested_key), [])
        if normalize_checkpoint_key(str(value))
    }


def append_nested_checkpoint_value(
    checkpoint: dict[str, Any],
    key: str,
    nested_key: str | None,
    value: str | None,
) -> bool:
    marker_key = normalize_checkpoint_key(nested_key)
    text = str(value or "").strip()
    marker_value = normalize_checkpoint_key(text)
    if not marker_key or not marker_value:
        return False
    values_by_key = checkpoint.setdefault(key, {})
    if not isinstance(values_by_key, dict):
        values_by_key = {}
        checkpoint[key] = values_by_key
    values = values_by_key.setdefault(marker_key, [])
    if not isinstance(values, list):
        values = []
        values_by_key[marker_key] = values
    if marker_value in {normalize_checkpoint_key(item) for item in values}:
        return False
    values.append(text)
    return True
