"""Iteratively repair broken string literals in quote_engine.py."""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "quote_engine.py"


def fix_line(line: str) -> str | None:
    """Return fixed line or None if no rule matched."""
    original = line

    # docstring close: ...?"" -> ...。"""
    if line.lstrip().startswith('"""') and line.rstrip().endswith('?""'):
        return line.rstrip()[:-3] + '。"""'

    # docstring close triple at end: ...?"""  (already 3 quotes but ? before)
    if '"""' in line and re.search(r'\?\s*"""', line):
        return re.sub(r'\?\s*"""', '。"""', line)

    # tuple / list string keys: "长?, "宽 -> "长", "宽
    if re.search(r'\?\s*,\s*"', line):
        line = re.sub(r'\?\s*,\s*"', '", "', line)

    # ternary string: ...? if x else -> ...。" if x else
    if re.search(r'\?\s+if\s+', line):
        line = re.sub(r'\?\s+if\s+', '。" if ', line)

    # closing before comma at EOL
    if line.count('"') % 2 == 1 and re.search(r'\?\s*,\s*$', line):
        line = re.sub(r'\?\s*,\s*$', '",', line)

    # closing before paren
    if line.count('"') % 2 == 1 and re.search(r'\?\s*\)', line):
        line = re.sub(r'\?\s*\)', '")', line)

    # f-string continuation ending with ? (no comma)
    if line.count('"') % 2 == 1 and line.rstrip().endswith('?'):
        line = line.rstrip()[:-1] + '"'

    # .replace("x?, "y") patterns
    line = line.replace('.replace("锝?, "x")', '.replace("～", "x")')
    line = line.replace('.replace("锛?, "/")', '.replace("，", "/")')

    # specific dimension keys
    if '"闀?, "瀹?, "楂?)' in line:
        line = line.replace('"闀?, "瀹?, "楂?)', '"长", "宽", "高")')

    return line if line != original else None


def main() -> None:
    backup = TARGET.with_suffix(f".py.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(TARGET, backup)
    lines = TARGET.read_text(encoding="utf-8-sig").splitlines()

    for _ in range(500):
        text = "\n".join(lines) + "\n"
        try:
            compile(text, str(TARGET), "exec")
            TARGET.write_text(text, encoding="utf-8")
            print("compile ok after iterations; backup:", backup.name)
            return
        except SyntaxError as e:
            ln = e.lineno or 0
            if ln <= 0 or ln > len(lines):
                print("stuck:", e)
                break
            idx = ln - 1
            fixed = fix_line(lines[idx])
            if fixed is None:
                # manual fallbacks for known lines
                raw = lines[idx]
                manual = {
                    'for key in ("length_cm", "width_cm", "height_cm", "L", "W", "H", "闀?, "瀹?, "楂?):':
                        '        for key in ("length_cm", "width_cm", "height_cm", "L", "W", "H", "长", "宽", "高"):',
                }
                if raw.strip() in manual:
                    lines[idx] = manual[raw.strip()]
                    continue
                print(f"no rule for line {ln}: {raw[:100]!r}")
                break
            lines[idx] = fixed
    else:
        print("max iterations")
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("partial save; backup:", backup.name)


if __name__ == "__main__":
    main()
