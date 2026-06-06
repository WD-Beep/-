import re
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "quote_engine.py"
text = p.read_text(encoding="utf-8-sig")
lines = text.splitlines()

# patterns where ? ate closing quote
patterns = [
    (r'?\s*,\s*"', '", "'),  # "长?, "宽 -> "长", "宽
]
count_q_comma = sum(1 for ln in lines if re.search(r'\?\s*,', ln))
count_q_end = sum(1 for ln in lines if re.search(r'\?\s*\)', ln))
count_q_only = sum(1 for ln in lines if '?' in ln)
print('lines with ?', count_q_only)
print('lines with ?,', count_q_comma)
print('lines with ?)', count_q_end)

# show unique ? endings
endings = set()
for ln in lines:
    for m in re.finditer(r'.{0,8}\?', ln):
        endings.add(m.group(0))
print('sample endings', sorted(endings)[:30])
