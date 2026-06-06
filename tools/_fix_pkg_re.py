from pathlib import Path

p = Path(__file__).resolve().parents[1] / "quote_engine.py"
text = p.read_text(encoding="utf-8")
marker = "_PKG_ROW_NAME_RE = re.compile("
idx = text.find(marker)
if idx == -1:
    raise SystemExit("marker not found")
start_paren = text.find("(", idx)
depth = 0
end = start_paren
for i in range(start_paren, len(text)):
    if text[i] == "(":
        depth += 1
    elif text[i] == ")":
        depth -= 1
        if depth == 0:
            end = i
            break
new_block = (
    "_PKG_ROW_NAME_RE = re.compile(\n"
    '    r"包装|OPP|胶袋|自封袋|纸箱|纸盒|纸卡|吊牌|标贴|封箱|包装袋|外箱|Packing|pe袋",\n'
    "    re.IGNORECASE,\n"
    ")"
)
text = text[:idx] + new_block + text[end + 1 :]
p.write_text(text, encoding="utf-8")
print("fixed")
