import re
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "quote_engine.py"
lines = p.read_text(encoding="utf-8-sig").splitlines()
bad = []
for i, line in enumerate(lines, 1):
    if line.strip().startswith("#"):
        continue
    q = len(re.findall(r'(?<!\\)"', line))
    if q % 2 == 1:
        bad.append((i, line))
print("odd quotes", len(bad))
for i, s in bad:
    print(i, s[:140])
