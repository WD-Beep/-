"""邮箱地址展示格式化（不含敏感信息）。"""

from __future__ import annotations


def format_email_display(email: str | None, display_name: str | None = None) -> str:
    address = (email or "").strip()
    name = (display_name or "").strip()
    if name and address:
        return f"{name} <{address}>"
    return address or "-"
