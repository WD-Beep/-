"""Repair quote_engine.py by fixing lines with unbalanced quotes only."""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "quote_engine.py"
BACKUP = ROOT / f"quote_engine.py.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"

# Known corrupted literals -> correct UTF-8
REPLACEMENTS = {
    '"闀?, "瀹?, "楂?)': '"长", "宽", "高")',
    '16*9*19cm or 闀?6瀹?楂?9.': '16*9*19cm or 长16宽9高19.',
    '.replace("锝?, "x")': '.replace("～", "x")',
    '.replace("姣毫米", "mm")': '.replace("毫米", "mm")',
    '.replace("鍘厘米", "cm")': '.replace("厘米", "cm")',
    '"灏忎欢鍖呰"': '"小件包装"',
    '"涓等灏哄鍖呰"': '"中等尺寸包装"',
    '"鍋忓ぇ鍖呰"': '"偏大包装"',
    'spec="鈥?,': 'spec="—",',
    'usage="1涓?,': 'usage="1个",',
    'usage="1濂?,': 'usage="1套",',
    'usage="1澶?,': 'usage="1处",',
    'unit_price=f"{addon:.2f}鍏?涓?,': 'unit_price=f"{addon:.2f}元/个",',
    'unit_price="80鍏?鐮?,': 'unit_price="80元/码²",',
    'usage="1.310 鐮?,': 'usage="1.310 码²",',
    'unit_price="5鍏?鐮?,': 'unit_price="5元/码²",',
    'usage="1.205 鐮?,': 'usage="1.205 码²",',
    'unit_price="7.94鍏?濂?,': 'unit_price="7.94元/套",',
    'unit_price="3.62鍏?濂?,': 'unit_price="3.62元/套",',
    'unit_price="4鍏?澶?,': 'unit_price="4元/处",',
    'unit_price="1.50鍏?濂?,': 'unit_price="1.50元/套",',
    'return f"{value:.2f}鍏?': 'return f"{value:.2f}元"',
    'name="鍖呰"': 'name="包装"',
    'product_name: str = "210D闃叉挄瑁傚凹榫欏寘"': 'product_name: str = "210D防撕裂尼龙包"',
    'item_name = "澶栫焊绠?鍖呰璐癸紙绯荤粺浼扮畻锛?': 'item_name = "外纸箱/包装费（系统估算）"',
    'item_name = "澶栫焊绠?鍖呰琚嬶紙鍔犺锛?': 'item_name = "外纸箱/包装袋（加计）"',
    '"鐮? not in usage': '"码²" not in usage',
    '"鐮? not in raw': '"码²" not in raw',
    '"鐮? not in pt': '"码²" not in pt',
    '"銕? in pt': '"㎡" in pt',
    '"鍏?绫? in pt': '"元/米" in pt',
    '"/绫? in pt': '"/米" in pt',
    'return f"{s}鍏?cm"': 'return f"{s}元/cm"',
    '| 鐗╂枡鍚嶇О | 璁＄畻鏂瑰紡 | 瑙勬牸 | 鐢ㄩ噺 | 鍗曚环 | 灏忚 |': '| 物料名称 | 计算方式 | 规格 | 用量 | 单价 | 小计 |',
}


def fix_odd_quote_line(line: str) -> str:
    if line.strip().startswith("#"):
        return line
    if line.count('"') % 2 == 0:
        return line
    out = line
    for old, new in REPLACEMENTS.items():
        out = out.replace(old, new)
    # generic: "foo?, "bar -> "foo", "bar
    out = re.sub(r'\?\s*,\s*"', '", "', out)
    # ...text? if cond -> ...text。" if cond
    out = re.sub(r'\?\s+if\s+', '。" if ', out)
    # ...text?, -> ...text",
    if out.count('"') % 2 == 1:
        out = re.sub(r'\?\s*,(?=\s*$|\s+#)', '",', out)
    # ...text?) -> ...text")
    if out.count('"') % 2 == 1:
        out = re.sub(r'\?\s*\)', '")', out)
    # f-string line ending: ...note? -> ...note"
    if out.count('"') % 2 == 1 and out.rstrip().endswith("?"):
        out = out.rstrip()[:-1] + '"'
    elif out.count('"') % 2 == 1:
        # close before end-of-line comment
        m = re.search(r'\?(?=\s*(?:#|$))', out)
        if m:
            out = out[: m.start()] + '"' + out[m.end() :]
    return out


def repair_text(text: str) -> str:
    lines = text.splitlines()
    for i in range(len(lines)):
        lines[i] = fix_odd_quote_line(lines[i])
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def main() -> None:
    original = TARGET.read_text(encoding="utf-8-sig")
    shutil.copy2(TARGET, BACKUP)
    fixed = repair_text(original)
    TARGET.write_text(fixed, encoding="utf-8")
    try:
        compile(fixed, str(TARGET), "exec")
        print("compile ok", BACKUP.name)
    except SyntaxError as e:
        print("still broken line", e.lineno, e.msg)
        # keep fixed version for next iteration
        print("partial fix saved; backup at", BACKUP.name)


if __name__ == "__main__":
    main()
