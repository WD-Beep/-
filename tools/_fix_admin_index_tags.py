"""一次性修复 static/admin/index.html 中损坏的闭合标签 ?/tag> → </tag>。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "static" / "admin" / "index.html"


def main() -> None:
    s = HTML.read_text(encoding="utf-8")
    s2, n = re.subn(r"\?/([a-z][a-z0-9]*)>", r"</\1>", s, flags=re.IGNORECASE)
    print("closing_tag_fixes:", n)
    # 搜索框占位（原文件把「/」与错误编码混在一起）
    old_ph = 'placeholder="鏂囦欢鍚?/ 浜у搧鍚?/ 鎶ヤ环 UID"'
    new_ph = 'placeholder="文件名 / 产品名 / 报价 UID"'
    if old_ph in s2:
        s2 = s2.replace(old_ph, new_ph)
        print("placeholder: fixed")
    HTML.write_text(s2, encoding="utf-8")


if __name__ == "__main__":
    main()
